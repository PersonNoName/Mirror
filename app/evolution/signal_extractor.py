"""Rule-based signal extraction for session adaptation."""

from __future__ import annotations

from typing import Any

from app.evolution.event_bus import Event, EventType, InteractionSignal


class SignalExtractor:
    """Extract lightweight interaction signals without LLM calls."""

    def __init__(self, personality_evolver: Any) -> None:
        self.personality_evolver = personality_evolver

    async def handle_dialogue_ended(self, event: Event) -> None:
        text = f"{event.payload.get('text', '')}\n{event.payload.get('reply', '')}".lower()
        signal = self._extract_signal(event, text)
        if signal is None:
            return
        await self.personality_evolver.fast_adapt(signal)

    def _extract_signal(self, event: Event, text: str) -> InteractionSignal | None:
        content = None
        signal_type = None
        if any(token in text for token in ("简洁一点", "简短", "少点", "别太长", "concise", "shorter")):
            signal_type = "prefer_concise"
            content = "本次对话使用更简洁的回复"
        elif any(token in text for token in ("中文", "说中文", "请用中文", "chinese")):
            signal_type = "language_zh"
            content = "本次对话使用中文回复"
        elif any(token in text for token in ("少点客套", "直接一点", "不要太客气")):
            signal_type = "tone_direct"
            content = "本次对话保持直接、少客套"
        if signal_type is None:
            return None
        return InteractionSignal(
            signal_type=signal_type,
            user_id=event.payload.get("user_id", ""),
            session_id=event.payload.get("session_id", ""),
            content=content or "",
            confidence=0.9,
            source_event_id=event.id,
            metadata={"source": EventType.DIALOGUE_ENDED},
        )
