"""Shared emotion detection constants used by both SignalExtractor and SoulEngine.

Centralising these avoids subtle drift between the extraction pipeline
(which writes emotional carryover) and the prompt assembly pipeline
(which reads and interprets it).
"""

from __future__ import annotations

# ── Emotion class keywords ───────────────────────────────────────────
# Mapping from canonical emotion class → detection tokens (both EN and ZH).
EMOTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "overwhelm": ("overwhelmed", "撑不住", "太多了", "崩溃", "burned out"),
    "anxiety": ("anxious", "anxiety", "panic", "紧张", "害怕", "慌"),
    "sadness": ("sad", "depressed", "难过", "伤心", "低落"),
    "loneliness": ("lonely", "alone", "孤独", "没人懂"),
    "anger": ("angry", "furious", "气死", "愤怒"),
    "frustration": ("frustrated", "annoyed", "烦", "挫败", "受不了"),
    "relief": ("relieved", "松了口气", "终于好了"),
    "joy": ("happy", "excited", "开心", "高兴"),
}

# ── Intensity tokens ─────────────────────────────────────────────────
HIGH_INTENSITY_TOKENS: tuple[str, ...] = (
    "extremely",
    "severely",
    "completely",
    "totally",
    "really bad",
    "struggling",
    "马上",
    "立刻",
    "完全",
    "崩溃",
    "撑不住",
)

MEDIUM_INTENSITY_TOKENS: tuple[str, ...] = (
    "very",
    "pretty",
    "really",
    "很",
    "特别",
    "非常",
)

# ── Emotional risk tokens ────────────────────────────────────────────
HIGH_RISK_TOKENS: tuple[str, ...] = (
    "kill myself",
    "suicide",
    "end my life",
    "hurt myself",
    "不想活了",
    "想自杀",
    "伤害自己",
)

MEDIUM_RISK_TOKENS: tuple[str, ...] = (
    "can't go on",
    "falling apart",
    "breaking down",
    "崩溃边缘",
    "快不行了",
)

# ── Resolution signals ───────────────────────────────────────────────
RESOLUTION_TOKENS: tuple[str, ...] = (
    "i'm okay now",
    "i am okay now",
    "it's fine now",
    "it's better now",
    "problem solved",
    "resolved",
    "已经好了",
    "没事了",
    "好多了",
    "解决了",
    "缓过来了",
)

# ── Unresolved topic detection ───────────────────────────────────────
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "work": ("工作", "job", "work", "老板", "deadline", "项目"),
    "relationship": ("感情", "关系", "partner", "boyfriend", "girlfriend", "family", "家里"),
    "health": ("健康", "身体", "sleep", "失眠", "焦虑", "panic"),
    "study": ("学习", "考试", "study", "school", "作业"),
}

# ── Support mode detection ───────────────────────────────────────────
LISTENING_TOKENS: tuple[str, ...] = (
    "just listen",
    "listen first",
    "先听我说",
    "先陪我聊聊",
)

PROBLEM_SOLVING_TOKENS: tuple[str, ...] = (
    "help me solve",
    "tell me what to do",
    "帮我解决",
    "告诉我该怎么做",
)

# ── Duration hint tokens ─────────────────────────────────────────────
ONGOING_DURATION_TOKENS: tuple[str, ...] = (
    "for months",
    "for weeks",
    "一直",
    "长期",
    "最近一直",
    "ongoing",
)

RECENT_DURATION_TOKENS: tuple[str, ...] = (
    "recently",
    "these days",
    "最近",
    "这几天",
)

MOMENTARY_DURATION_TOKENS: tuple[str, ...] = (
    "right now",
    "today",
    "现在",
    "刚刚",
)

# ── Negative / vulnerable emotion classes ────────────────────────────
VULNERABLE_EMOTION_CLASSES: frozenset[str] = frozenset(
    {"sadness", "anxiety", "loneliness", "overwhelm"}
)


# ── Utility functions ────────────────────────────────────────────────
def detect_emotion_class(text: str) -> str:
    """Return the first matching emotion class from *text*, or ``"neutral"``."""
    for emotion_class, tokens in EMOTION_KEYWORDS.items():
        if any(token in text for token in tokens):
            return emotion_class
    return "neutral"


def detect_intensity(text: str, emotion_class: str) -> str:
    """Return ``"high"`` / ``"medium"`` / ``"low"`` intensity for *text*."""
    if any(token in text for token in HIGH_INTENSITY_TOKENS):
        return "high"
    if any(token in text for token in MEDIUM_INTENSITY_TOKENS) or emotion_class != "neutral":
        return "medium"
    return "low"


def detect_emotional_risk(text: str) -> str:
    """Return ``"high"`` / ``"medium"`` / ``"low"`` risk for *text*."""
    if any(token in text for token in HIGH_RISK_TOKENS):
        return "high"
    if any(token in text for token in MEDIUM_RISK_TOKENS):
        return "medium"
    return "low"


def detect_duration_hint(text: str) -> str:
    """Return ``"ongoing"`` / ``"recent"`` / ``"momentary"`` / ``"unknown"``."""
    if any(token in text for token in ONGOING_DURATION_TOKENS):
        return "ongoing"
    if any(token in text for token in RECENT_DURATION_TOKENS):
        return "recent"
    if any(token in text for token in MOMENTARY_DURATION_TOKENS):
        return "momentary"
    return "unknown"


def extract_unresolved_topics(text: str) -> list[str]:
    """Return up to 3 topic labels detected in *text*."""
    topics: list[str] = []
    lowered = text.lower()
    for label, tokens in TOPIC_KEYWORDS.items():
        if any(token in text or token in lowered for token in tokens):
            topics.append(label)
    return topics[:3]


def is_resolution_signal(text: str) -> bool:
    """Return ``True`` if *text* contains a resolution signal."""
    return any(token in text for token in RESOLUTION_TOKENS)


def text_has_topic_overlap(text: str, unresolved_topics: list[str]) -> bool:
    """Return ``True`` if *text* mentions any of the *unresolved_topics*.

    Used to guard carryover emotion inheritance — only inherit previous
    emotional context when the current message is topically related.
    """
    if not unresolved_topics:
        return False
    lowered = text.lower()
    for topic in unresolved_topics:
        topic_tokens = TOPIC_KEYWORDS.get(topic, ())
        if any(token in lowered for token in topic_tokens):
            return True
    return False
