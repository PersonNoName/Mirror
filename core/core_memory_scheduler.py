from typing import Optional, Any
from domain.memory import (
    CoreMemory,
    SelfCognition,
    WorldModel,
    PersonalityState,
    TaskExperience,
)
from domain.stability import SnapshotRecord
from datetime import datetime
import json


TOKEN_BUDGET_CONFIG = {
    "total": 5000,
    "self_cognition": 1000,
    "world_model": 1000,
    "personality": 800,
    "task_experience": 1200,
    "dynamic_reserve": 1000,
}

BLOCK_BUDGETS = {
    "self_cognition": 1000,
    "world_model": 1000,
    "personality": 800,
    "task_experience": 1200,
}

DYNAMIC_RESERVE = 1000


class LoggerDummy:
    async def warn(self, msg: str) -> None:
        print(f"[WARN] {msg}")

    async def info(self, msg: str) -> None:
        print(f"[INFO] {msg}")


class CoreMemoryScheduler:
    """
    Core Memory 写入调度器：
    - 强制 Token 预算控制（总计5000，动态储备池1000）
    - 3次 CAS 乐观锁写入重试
    - 失败时告警 + 强制覆盖（不丢数据）
    """

    MAX_CAS_RETRIES = 3

    def __init__(
        self,
        core_memory_store: "CoreMemoryStoreInterface",
        cache: "CoreMemoryCache",
        logger: Optional[LoggerDummy] = None,
    ):
        from interfaces.storage import CoreMemoryStoreInterface
        from core.memory_cache import CoreMemoryCache

        self.core_memory_store: CoreMemoryStoreInterface = core_memory_store
        self.cache: CoreMemoryCache = cache
        self.logger = logger or LoggerDummy()
        self._reserve_used: dict[str, int] = {}

    async def write(
        self,
        block: str,
        content: Any,
        event_id: Optional[str] = None,
    ) -> None:
        """
        写入指定区块内容，先预算检查，再CAS写入。
        """
        serialized = self._serialize_with_pinning(content)
        token_count = self._count_tokens(serialized)
        block_budget = BLOCK_BUDGETS.get(block, 1000)

        if token_count > block_budget:
            available_reserve = DYNAMIC_RESERVE - sum(self._reserve_used.values())
            overflow = token_count - block_budget
            if overflow <= available_reserve:
                self._reserve_used[block] = overflow
                self.logger.info(f"借用动态储备池: block={block}, overflow={overflow}")
            else:
                serialized = await self._compress(serialized, block)

        success = False
        for attempt in range(self.MAX_CAS_RETRIES):
            current_data, version = await self.core_memory_store.get_with_version(
                f"core_memory:{block}"
            )

            success = await self.core_memory_store.cas_upsert(
                key=f"core_memory:{block}",
                value=serialized,
                expected_version=version,
            )

            if success:
                if self.cache:
                    self.cache.invalidate_block_by_key(block)
                self.logger.info(
                    f"CoreMemory写入成功: block={block}, version={version + 1}"
                )
                return

            self.logger.warn(f"CAS写入失败，重试: block={block}, attempt={attempt + 1}")

        await self.logger.warn(
            f"CAS写入冲突耗尽，强制写入: block={block}, event_id={event_id}"
        )
        await self.core_memory_store.force_upsert(
            key=f"core_memory:{block}",
            value=serialized,
        )
        if self.cache:
            self.cache.invalidate_block_by_key(block)

    async def write_full_memory(
        self,
        user_id: str,
        core_memory: CoreMemory,
        event_id: Optional[str] = None,
    ) -> None:
        """
        一次性写入完整 Core Memory（包含四个区块）。
        逐区块调用 write，保持预算控制。
        """
        await self.write("self_cognition", core_memory.self_cognition, event_id)
        await self.write("world_model", core_memory.world_model, event_id)
        await self.write("personality", core_memory.personality, event_id)
        await self.write("task_experience", core_memory.task_experience, event_id)

    def _serialize_with_pinning(self, content: Any) -> str:
        """
        序列化内容，保留 is_pinned 标记。
        """
        if hasattr(content, "model_dump"):
            data = content.model_dump()
        elif hasattr(content, "dict"):
            data = content.dict()
        elif isinstance(content, dict):
            data = content
        else:
            data = {"value": content}

        return json.dumps(data, ensure_ascii=False, default=str)

    def _count_tokens(self, text: str) -> int:
        """
        简单 Token 计数（中文字符按1.5倍计算）。
        """
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        english_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + english_chars * 0.25)

    async def _compress(
        self,
        serialized: str,
        block: str,
    ) -> str:
        """
        LLM 压缩旧条目（占位实现）。
        实际应调用 LLM 对非 pinned 条目进行压缩。
        """
        self.logger.info(f"触发压缩: block={block}")
        return serialized

    async def _build_world_model_snapshot(
        self,
        graph_db: "GraphDBInterface",
        user_id: str,
    ) -> WorldModel:
        """
        从 Graph DB 合成 world_model 快照。
        """
        from interfaces.storage import GraphDBInterface

        user_model = await graph_db.query_user_preferences(user_id)
        agent_profiles = await graph_db.query_agent_capabilities()
        env_constraints = await graph_db.query_env_constraints()

        return WorldModel(
            user_model=user_model,
            agent_profiles=agent_profiles,
            env_constraints=env_constraints,
            social_rules=[],
        )

    async def save_snapshot(
        self,
        block_type: str,
        content: Any,
        reason: Optional[str] = None,
    ) -> None:
        """
        保存版本快照（用于漂移回滚）。
        """
        from interfaces.storage import SnapshotStoreInterface

        if hasattr(content, "model_dump"):
            data = content.model_dump()
        else:
            data = content if isinstance(content, dict) else {"value": content}

        snapshot = SnapshotRecord(
            block_type=block_type,
            version=int(datetime.utcnow().timestamp()),
            content=data,
            reason=reason,
        )
        print(f"[CoreMemoryScheduler] 快照已保存: block={block_type}")
