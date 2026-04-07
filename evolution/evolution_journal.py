from typing import Optional
from domain.evolution import EvolutionEntry


class LLMInterfaceDummy:
    """LLM 调用占位实现"""

    async def generate(self, prompt: str) -> str:
        print(f"[LLM] 生成调用（占位）: {prompt[:100]}...")
        return "这是基于成长记录生成的摘要"


class JournalStoreDummy:
    """JournalStore 占位实现"""

    def __init__(self):
        self._entries: list[EvolutionEntry] = []

    async def append(self, entry: EvolutionEntry) -> None:
        self._entries.append(entry)
        print(f"[JournalStore] 追加条目: {entry.type} - {entry.summary}")

    async def get_recent(self, last_n: int) -> list[EvolutionEntry]:
        return self._entries[-last_n:] if self._entries else []

    async def get_by_session(self, session_id: str) -> list[EvolutionEntry]:
        return [e for e in self._entries if e.session_id == session_id]


class EvolutionJournal:
    """
    成长日志：记录所有进化事件，使用 LLM 生成可读摘要。
    用户可查，AI 可引用。
    """

    MAX_ENTRIES = 200

    def __init__(
        self,
        journal_store: Optional[JournalStoreDummy] = None,
        llm_lite: Optional[LLMInterfaceDummy] = None,
    ):
        self.journal_store = journal_store or JournalStoreDummy()
        self.llm_lite = llm_lite or LLMInterfaceDummy()

    async def record(self, event: dict) -> EvolutionEntry:
        """
        记录进化事件到成长日志。
        """
        entry = EvolutionEntry(
            type=event.get("type", "fast_adaptation"),
            summary=event.get("summary", ""),
            detail=event.get("detail", {}),
            session_id=event.get("session_id"),
        )

        await self.journal_store.append(entry)
        await self._trim_if_needed()

        return entry

    async def get_growth_summary(self, last_n: int = 20) -> str:
        """
        供 Soul Engine 响应用户 "你了解我什么？" 时调用。
        """
        entries = await self.journal_store.get_recent(last_n)
        if not entries:
            return "暂无成长记录"

        summaries = [e.summary for e in entries]
        prompt = f"""以第一人称总结以下成长记录，简洁自然，不超过200字：
{sumaries}"""

        return await self.llm_lite.generate(prompt)

    async def get_recent_changes(self, last_n: int = 5) -> list[EvolutionEntry]:
        """
        供 AI 主动引用近期变化时使用。
        """
        return await self.journal_store.get_recent(last_n)

    async def get_session_changes(self, session_id: str) -> list[EvolutionEntry]:
        """
        获取特定 Session 的所有变化。
        """
        return await self.journal_store.get_by_session(session_id)

    async def _trim_if_needed(self) -> None:
        entries = await self.journal_store.get_recent(self.MAX_ENTRIES + 1)
        if len(entries) > self.MAX_ENTRIES:
            print(f"[EvolutionJournal] 裁剪旧记录，保留最近 {self.MAX_ENTRIES} 条")
