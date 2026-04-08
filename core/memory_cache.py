from typing import Set
from domain.memory import (
    CoreMemory,
    SelfCognition,
    WorldModel,
    PersonalityState,
    TaskExperience,
)


class CoreMemoryCache:
    """
    Core Memory 常驻内存，进程启动时加载，进化写入后立即刷新。
    注意：Core Memory 是 per-user 的（非 per-session），同一用户的所有
    活跃 Session 共享同一份 Core Memory。进化写入后需通知所有活跃 Session 刷新。
    """

    def __init__(self):
        self._cache: dict[str, CoreMemory] = {}
        self._active_sessions: dict[str, Set[str]] = {}

    def get(self, user_id: str) -> CoreMemory:
        if user_id not in self._cache:
            self._cache[user_id] = CoreMemory()
        return self._cache[user_id]

    def set(self, user_id: str, core_memory: CoreMemory) -> None:
        self._cache[user_id] = core_memory

    def invalidate(self, user_id: str) -> None:
        if user_id in self._cache:
            self._cache[user_id] = self._load_from_db(user_id)

    def invalidate_block_by_key(self, block_key: str) -> None:
        """
        根据 block key (如 'core_memory:self_cognition') 使缓存失效。
        简化实现：直接清除所有用户的该区块缓存。
        """
        block_name = block_key.replace("core_memory:", "")
        for user_id in list(self._cache.keys()):
            cm = self._cache[user_id]
            if block_name == "self_cognition":
                cm.self_cognition = SelfCognition()
            elif block_name == "world_model":
                cm.world_model = WorldModel()
            elif block_name == "personality":
                cm.personality = PersonalityState()
            elif block_name == "task_experience":
                cm.task_experience = TaskExperience()
            self._cache[user_id] = cm

    def register_session(self, user_id: str, session_id: str) -> None:
        if user_id not in self._active_sessions:
            self._active_sessions[user_id] = set()
        self._active_sessions[user_id].add(session_id)

    def unregister_session(self, user_id: str, session_id: str) -> None:
        if user_id in self._active_sessions:
            self._active_sessions[user_id].discard(session_id)

    def get_active_sessions(self, user_id: str) -> Set[str]:
        return self._active_sessions.get(user_id, set())

    def _load_from_db(self, user_id: str) -> CoreMemory:
        return CoreMemory()
