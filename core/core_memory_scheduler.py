from typing import TYPE_CHECKING, Optional, Any
from domain.memory import (
    CoreMemory,
    WorldModel,
)
from domain.stability import SnapshotRecord
from datetime import datetime
import json

if TYPE_CHECKING:
    from interfaces.storage import SnapshotStoreInterface, GraphDBInterface
    from core.memory_cache import CoreMemoryCache
    from interfaces.storage import CoreMemoryStoreInterface
    from services.llm import LLMInterface


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
        snapshot_store: Optional["SnapshotStoreInterface"] = None,
        llm: Optional["LLMInterface"] = None,
    ):
        self.core_memory_store: "CoreMemoryStoreInterface" = core_memory_store
        self.cache: "CoreMemoryCache" = cache
        self.logger = logger or LoggerDummy()
        self.snapshot_store: Optional["SnapshotStoreInterface"] = snapshot_store
        self._llm: Optional["LLMInterface"] = llm
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
        LLM 压缩非 pinned 条目。
        策略：保留所有 is_pinned=true 的条目，其余条目由 LLM 提炼摘要。
        """
        self.logger.info(f"触发 LLM 压缩: block={block}")

        if not self._llm:
            self.logger.info("无 LLM 配置，跳过压缩")
            return serialized

        try:
            data = json.loads(serialized)
        except (json.JSONDecodeError, TypeError):
            self.logger.info("非 JSON 内容，跳过压缩")
            return serialized

        pinned, non_pinned = self._extract_pinned_items(data)

        if not non_pinned:
            self.logger.info("全部为 pinned 内容，跳过压缩")
            return serialized

        if not pinned:
            compressed = await self._llm_compress_summary(non_pinned, block)
            return json.dumps(compressed, ensure_ascii=False, default=str)

        compressed_non_pinned = await self._llm_compress_summary(non_pinned, block)
        result = {**pinned, "_compressed_summary": compressed_non_pinned}
        return json.dumps(result, ensure_ascii=False, default=str)

    def _extract_pinned_items(self, data: Any, path: str = "") -> tuple[dict, list]:
        """
        递归分离 pinned 和 non-pinned 内容。
        返回 (pinned_dict, non_pinned_list)。
        """
        pinned = {} if isinstance(data, dict) else []
        non_pinned = []

        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{path}.{key}" if path else key
                if isinstance(value, dict):
                    if value.get("is_pinned") is True:
                        pinned[key] = value
                        continue
                    p, n = self._extract_pinned_items(value, current_path)
                    if p:
                        pinned[key] = p
                    non_pinned.extend(n)
                elif isinstance(value, list):
                    pinned_items_list = []
                    for i, item in enumerate(value):
                        if isinstance(item, dict) and item.get("is_pinned") is True:
                            pinned_items_list.append(item)
                        else:
                            p, n = self._extract_pinned_items(
                                item, f"{current_path}[{i}]"
                            )
                            if p:
                                pinned_items_list.append(p)
                            non_pinned.extend(n)
                    if pinned_items_list:
                        pinned[key] = pinned_items_list
                else:
                    non_pinned.append({key: value})
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, dict) and item.get("is_pinned") is True:
                    pinned.append(item)
                else:
                    p, n = self._extract_pinned_items(item, f"{path}[{i}]")
                    if p:
                        pinned.append(p)
                    non_pinned.extend(n)
        else:
            non_pinned.append(data)

        return pinned, non_pinned

    async def _llm_compress_summary(self, non_pinned: list, block: str) -> dict:
        content_str = json.dumps(non_pinned, ensure_ascii=False, default=str, indent=2)

        prompt = f"""你是一个记忆压缩助手。以下是某个 AI Agent 的{block}内容（共 {len(non_pinned)} 条非核心条目）：

{content_str}

请将这些内容提炼为简洁的摘要（不超过 200 字），保留核心信息。
直接输出 JSON 对象，格式：{{"summary": "摘要文字", "count": 条目数量}}

不要有任何解释或前缀。"""

        response = await self._llm.generate(prompt)

        try:
            result = json.loads(response)
            if isinstance(result, dict) and "summary" in result:
                return result
        except json.JSONDecodeError:
            pass

        summary_text = response.strip()
        return {"summary": summary_text, "count": len(non_pinned)}

    async def _build_world_model_snapshot(
        self,
        graph_db: "GraphDBInterface",
        user_id: str,
    ) -> WorldModel:
        """
        从 Graph DB 合成 world_model 快照。
        """
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

        if self.snapshot_store:
            await self.snapshot_store.save(snapshot)
            print(f"[CoreMemoryScheduler] 快照已保存到存储: block={block_type}")
        else:
            print(f"[CoreMemoryScheduler] 快照已创建（未持久化）: block={block_type}")
