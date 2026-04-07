from typing import Optional
from domain.evolution import InteractionSignal


class SignalExtractor:
    """
    信号抽取器：从对话中提取显式指令与隐式行为模式。
    订阅 EventBus 的 dialogue_ended 事件，与 Observer 并行执行。
    """

    STYLE_KEYWORDS = [
        "简洁",
        "直接",
        "详细",
        "用中文",
        "用英文",
        "正式",
        "口语化",
        "别废话",
        "展开说",
        "不要解释",
    ]

    IMPLICIT_PATTERNS = {
        "shorten_response",
        "language_switch",
        "repeated_correction",
        "style_preference",
        "topic_redirect",
    }

    async def extract(
        self,
        dialogue: list[dict],
        session_id: str,
        turn_index: int,
    ) -> list[InteractionSignal]:
        signals = []

        explicit = self._detect_explicit(dialogue, session_id, turn_index)
        if explicit:
            signals.append(explicit)

        implicit = self._detect_implicit_patterns(dialogue, session_id, turn_index)
        signals.extend(implicit)

        return signals

    def _detect_explicit(
        self,
        dialogue: list[dict],
        session_id: str,
        turn_index: int,
    ) -> Optional[InteractionSignal]:
        last_user_msg = self._get_last_user_message(dialogue)
        if not last_user_msg:
            return None

        for kw in self.STYLE_KEYWORDS:
            if kw in last_user_msg:
                return InteractionSignal(
                    type="explicit_instruction",
                    content=last_user_msg,
                    behavior_tag=None,
                    strength=1.0,
                    session_id=session_id,
                    turn_index=turn_index,
                )
        return None

    def _detect_implicit_patterns(
        self,
        dialogue: list[dict],
        session_id: str,
        turn_index: int,
    ) -> list[InteractionSignal]:
        signals = []

        if self._user_truncates_responses(dialogue, threshold=3):
            signals.append(
                InteractionSignal(
                    type="implicit_behavior",
                    content="用户倾向于更短的回复",
                    behavior_tag="shorten_response",
                    strength=0.7,
                    session_id=session_id,
                    turn_index=turn_index,
                )
            )

        if self._language_mismatch(dialogue):
            detected_lang = self._detect_user_language(dialogue)
            signals.append(
                InteractionSignal(
                    type="implicit_behavior",
                    content=f"用户使用 {detected_lang} 交流",
                    behavior_tag="language_switch",
                    strength=0.9,
                    session_id=session_id,
                    turn_index=turn_index,
                )
            )

        if self._user_repeatedly_corrects(dialogue, threshold=2):
            signals.append(
                InteractionSignal(
                    type="implicit_behavior",
                    content="用户反复纠正同一类问题",
                    behavior_tag="repeated_correction",
                    strength=0.8,
                    session_id=session_id,
                    turn_index=turn_index,
                )
            )

        return signals

    def _get_last_user_message(self, dialogue: list[dict]) -> str:
        for msg in reversed(dialogue):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _user_truncates_responses(
        self, dialogue: list[dict], threshold: int = 3
    ) -> bool:
        short_count = 0
        ai_responses = []
        for msg in dialogue:
            if msg.get("role") == "assistant":
                ai_responses.append(msg.get("content", ""))

        for content in ai_responses[-threshold * 2 :]:
            if len(content) < 50:
                short_count += 1

        return short_count >= threshold

    def _language_mismatch(self, dialogue: list[dict]) -> bool:
        user_lang = None
        ai_lang = None

        for msg in dialogue[-4:]:
            content = msg.get("content", "")
            if msg.get("role") == "user":
                user_lang = self._detect_language(content)
            elif msg.get("role") == "assistant":
                ai_lang = self._detect_language(content)

        return user_lang is not None and ai_lang is not None and user_lang != ai_lang

    def _detect_language(self, text: str) -> Optional[str]:
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        if chinese_chars / max(len(text), 1) > 0.3:
            return "中文"
        return "英文"

    def _user_repeatedly_corrects(
        self, dialogue: list[dict], threshold: int = 2
    ) -> bool:
        correction_keywords = ["不对", "不是", "错了", "应该", "更正"]
        correction_count = 0

        for msg in dialogue:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if any(kw in content for kw in correction_keywords):
                    correction_count += 1

        return correction_count >= threshold

    def _detect_user_language(self, dialogue: list[dict]) -> Optional[str]:
        for msg in reversed(dialogue):
            if msg.get("role") == "user":
                return self._detect_language(msg.get("content", ""))
        return None
