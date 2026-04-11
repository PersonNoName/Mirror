# Phase 19 学习笔记：情感理解与支持策略

> **前置阶段**：[[Phase-18-学习笔记]]  
> **目标**：建立前台情感解释和支持策略机制，区分临时情感状态与持久支持偏好记忆  
> **里程碑**：本阶段完成后系统具备情感感知能力，高风险情感可短路处理，支持偏好可学习

---

## 目录

- [概述](#概述)
- [1. Phase 19 文件清单](#1-phase-19-文件清单)
- [2. 为什么需要情感理解](#2-为什么需要情感理解)
- [3. 情感理解数据结构](#3-情感理解数据结构)
- [4. SoulEngine 情感解释](#4-soulinge-情感解释)
- [5. 高风险情感短路处理](#5-高风险情感短路处理)
- [6. 支持策略塑形](#6-支持策略塑形)
- [7. 支持偏好记忆格式化](#7-支持偏好记忆格式化)
- [8. SignalExtractor 支持偏好学习](#8-signalextractor-支持偏好学习)
- [9. CognitionUpdater 支持偏好处理](#9-cognitionupdater-支持偏好处理)
- [10. 支持偏好 vs 情感状态](#10-支持偏好-vs-情感状态)
- [11. 验证与验收](#11-验证与验收)
- [12. Explicitly Not Done Yet](#12-explicitly-not-done-yet)
- [13. Phase 19 的意义](#13-phase-19-的意义)

---

## 概述

### 目标

Phase 19 的目标是**建立情感理解与支持策略**，让系统具备：

- 前台轻量级情感解释（基于规则，非ML）
- 高风险情感短路处理（不调用模型）
- 中/高风险支持策略塑形
- 支持偏好持久化学习（通过Phase 18候选管道）
- 区分临时情感状态与持久支持偏好

### Phase 18 到 Phase 19 的演进

Phase 18 建立了受控进化管道，Phase 19 则关注**情感理解**：

```
Phase 18 完成时
     ↓
进化系统具备候选管道 + 审批机制
     ↓
但系统缺乏情感理解能力
     ↓
     ↓
┌─────────────────────────────────────────┐
│  Phase 18 的情感缺失                      │
├─────────────────────────────────────────┤
│  • 无法识别用户情感状态                   │
│  • 高风险情感（如自杀）无特殊处理          │
│  • 支持风格完全隐式，无偏好学习           │
│  • 所有回复平等对待，无情感感知           │
└─────────────────────────────────────────┘

Phase 19 新增
     ↓
情感解释（基于规则的前台处理）
     ↓
高风险情感短路 → 安全回复
     ↓
支持偏好记忆 → 通过候选管道学习
     ↓
支持策略塑形 → prompt 注入策略
```

### 新的系统形态

```
用户消息 → 情感解释
     ↓
┌─────────────────────────────────────────┐
│  规则基础情感解释                         │
├─────────────────────────────────────────┤
│  emotion_class / intensity / duration    │
│  emotional_risk (low/medium/high)         │
└─────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────┐
│  风险路由                                │
├─────────────────────────────────────────┤
│  HIGH  → 短路 → 安全回复（不调用模型）    │
│  MEDIUM → 塑形 → safety_constrained 模式  │
│  LOW   → 正常 → 模型推理                 │
└─────────────────────────────────────────┘
     ↓
支持偏好 → SignalExtractor → 候选管道 → 持久记忆
```

---

## 1. Phase 19 文件清单

| 文件 | 内容 |
|------|------|
| `app/soul/models.py` | 新增 EmotionalInterpretation / SupportPolicyDecision 及相关字面量 |
| `app/soul/engine.py` | 更新：情感解释、支持策略注入、高风险短路 |
| `app/evolution/signal_extractor.py` | 更新：支持偏好信号提取 |
| `app/evolution/cognition_updater.py` | 更新：支持偏好分类路由 |
| `app/soul/__init__.py` | 导出新类型 |
| `tests/test_emotional_support_policy.py` | Phase 19 新增测试 |
| `tests/test_soul_engine.py` | 更新覆盖情感支持 |
| `tests/test_relationship_memory.py` | 更新 |
| `tests/test_integration_runtime.py` | 更新 |
| `tests/test_runtime_bootstrap.py` | 更新 |

---

## 2. 为什么需要情感理解

### 2.1 之前的问题

Phase 18 之前，系统缺乏情感理解：

| 问题 | 描述 | 影响 |
|------|------|------|
| **无情感识别** | 无法识别用户当前情感状态 | 回复缺乏共情 |
| **高风险无保护** | 自杀/自伤等高风险内容无特殊处理 | 可能加剧危机 |
| **支持风格隐式** | 支持风格完全由模型隐式决定 | 偏好不一致 |
| **无偏好学习** | 用户支持偏好（倾听vs解决问题）不持久化 | 每次都重新推断 |

### 2.2 情感理解的价值

```
情感理解 = 安全 + 共情 + 个性化

价值1: 安全
    ↓
高风险情感短路处理
    ↓
不调用模型，返回安全引导

价值2: 共情
    ↓
识别情感状态
    ↓
prompt 注入情感上下文

价值3: 个性化
    ↓
支持偏好持久化
    ↓
学习用户喜欢倾听还是解决问题
```

---

## 3. 情感理解数据结构

### 3.1 情感解释

```python
@dataclass
class EmotionalInterpretation:
    """前台情感解释结果"""
    
    emotion_class: EmotionClass          # 情感类别
    intensity: EmotionIntensity           # 强度：low / medium / high
    duration_hint: DurationHint          # 持续性：brief / sustained / ongoing
    support_preference: SupportPreference  # 支持偏好
    emotional_risk: EmotionalRisk        # 风险级别：low / medium / high
    explicit_signals: list[str]          # 显式情感信号
    implicit_signals: list[str]          # 隐式情感信号
```

### 3.2 支持策略决策

```python
@dataclass
class SupportPolicyDecision:
    """支持策略决策"""
    
    support_mode: SupportMode            # 支持模式
    policy_constraints: list[str]        # 策略约束
    emotional_context: str                # 情感上下文（prompt用）
    support_preference_from_memory: SupportPreference | None  # 记忆中的偏好
    reasoning: str                       # 决策理由
```

### 3.3 情感类别

```python
class EmotionClass:
    FEAR = "fear"                      # 恐惧
    SADNESS = "sadness"                # 悲伤
    ANGER = "anger"                    # 愤怒
    JOY = "joy"                        # 喜悦
    SURPRISE = "surprise"              # 惊讶
    DISGUST = "disgust"                # 厌恶
    TRUST = "trust"                    # 信任
    ANTICIPATION = "anticipation"      # 期待
    CONFUSION = "confusion"            # 困惑
    FRUSTRATION = "frustration"       # 挫败
    ANXIETY = "anxiety"                # 焦虑
    HOPELESSNESS = "hopelessness"      # 无望
    LONELINESS = "loneliness"          # 孤独
    OVERWHELM = "overwhelm"            # 被淹没感
    NEUTRAL = "neutral"                # 中性
```

### 3.4 情感强度

```python
class EmotionIntensity:
    LOW = "low"        # 轻微
    MEDIUM = "medium"  # 中等
    HIGH = "high"      # 强烈
```

### 3.5 持续性提示

```python
class DurationHint:
    BRIEF = "brief"          # 短暂
    SUSTAINED = "sustained"  # 持续
    ONGOING = "ongoing"      # 进行中
```

### 3.6 支持偏好

```python
class SupportPreference:
    LISTENING = "listening"           # 倾听优先
    PROBLEM_SOLVING = "problem_solving"  # 解决问题优先
    MIXED = "mixed"                   # 混合
    UNKNOWN = "unknown"               # 未知
```

### 3.7 支持模式

```python
class SupportMode:
    NORMAL = "normal"                      # 正常模式
    SAFETY_CONSTRAINED = "safety_constrained"  # 安全约束模式
    CRISIS_RESPONSE = "crisis_response"    # 危机响应
    LISTENING_HEAVY = "listening_heavy"    # 倾听为主
    SOLUTION_HEAVY = "solution_heavy"      # 解决方案为主
```

### 3.8 情感风险

```python
class EmotionalRisk:
    LOW = "low"          # 低风险
    MEDIUM = "medium"    # 中风险
    HIGH = "high"        # 高风险（自杀/自伤/伤害他人等）
```

---

## 4. SoulEngine 情感解释

### 4.1 基于规则的轻量解释

Phase 19 的情感解释是**基于规则**的，不是ML模型：

```python
def _interpret_emotion(self, message: InboundMessage) -> EmotionalInterpretation:
    """
    基于规则的轻量情感解释
    - 确定性，无随机性
    - 直接可单元测试
    - 不调用外部模型
    """
    text = message.text.lower()
    
    # 1. 提取显式信号
    explicit_signals = self._extract_explicit_signals(text)
    
    # 2. 提取隐式信号
    implicit_signals = self._extract_implicit_signals(text)
    
    # 3. 分类情感
    emotion_class = self._classify_emotion(explicit_signals, implicit_signals)
    
    # 4. 评估强度
    intensity = self._assess_intensity(explicit_signals, implicit_signals)
    
    # 5. 评估持续性
    duration = self._assess_duration(explicit_signals)
    
    # 6. 推断支持偏好
    support_pref = self._infer_support_preference(text)
    
    # 7. 评估情感风险
    emotional_risk = self._assess_emotional_risk(explicit_signals)
    
    return EmotionalInterpretation(
        emotion_class=emotion_class,
        intensity=intensity,
        duration_hint=duration,
        support_preference=support_pref,
        emotional_risk=emotional_risk,
        explicit_signals=explicit_signals,
        implicit_signals=implicit_signals,
    )


def _extract_explicit_signals(self, text: str) -> list[str]:
    """提取显式情感信号"""
    signals = []
    
    # 高风险信号
    HIGH_RISK_PATTERNS = [
        "suicide", "kill myself", "end my life",
        "自残", "自杀", "不想活了",
        "hurt myself", "harm myself",
        "kill you", "hurt others", "harm others",
    ]
    
    for pattern in HIGH_RISK_PATTERNS:
        if pattern in text:
            signals.append(f"HIGH_RISK:{pattern}")
    
    # 情感词
    EMOTION_KEYWORDS = {
        EmotionClass.FEAR: ["afraid", "scared", "fear", "害怕", "恐惧"],
        EmotionClass.SADNESS: ["sad", "unhappy", "depressed", "悲伤", "难过"],
        EmotionClass.ANGER: ["angry", "mad", "furious", "生气", "愤怒"],
        EmotionClass.JOY: ["happy", "glad", "joy", "高兴", "开心"],
        # ...
    }
    
    for emotion, keywords in EMOTION_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                signals.append(f"{emotion}:{kw}")
    
    return signals


def _assess_emotional_risk(self, signals: list[str]) -> EmotionalRisk:
    """评估情感风险"""
    high_risk_signals = [s for s in signals if s.startswith("HIGH_RISK")]
    
    if high_risk_signals:
        return EmotionalRisk.HIGH
    
    # 检查其他高风险模式
    for signal in signals:
        if any(kw in signal for kw in ["hopelessness", "loneliness:overwhelm"]):
            return EmotionalRisk.HIGH
    
    return EmotionalRisk.LOW
```

### 4.2 支持偏好推断

```python
def _infer_support_preference(self, text: str) -> SupportPreference:
    """从当前消息推断支持偏好"""
    
    # 明确倾听请求
    LISTENING_SIGNALS = [
        "just listen", "listen first",
        "先听我说", "不要急着给建议",
        "i just need to vent", "let me talk",
        "don't solve", "not looking for advice",
    ]
    
    for signal in LISTENING_SIGNALS:
        if signal in text.lower():
            return SupportPreference.LISTENING
    
    # 明确解决问题请求
    PROBLEM_SOLVING_SIGNALS = [
        "help me solve", "tell me what to do",
        "give me steps", "直接告诉我怎么做",
        "solve this", "find a solution",
    ]
    
    for signal in PROBLEM_SOLVING_SIGNALS:
        if signal in text.lower():
            return SupportPreference.PROBLEM_SOLVING
    
    return SupportPreference.UNKNOWN
```

---

## 5. 高风险情感短路处理

### 5.1 短路逻辑

Phase 19 对高风险情感进行**短路处理**：

```python
async def run(self, message: InboundMessage) -> Action:
    """主推理入口"""
    
    # 1. 情感解释（规则基础，无模型调用）
    emotional_ctx = self._interpret_emotion(message)
    
    # 2. 高风险情感检查
    if emotional_ctx.emotional_risk == EmotionalRisk.HIGH:
        # 短路：不调用模型，直接返回安全回复
        return self._create_crisis_response(emotional_ctx)
    
    # 3. 正常推理路径
    action = await self._normal_reasoning(message, emotional_ctx)
    
    return action
```

### 5.2 危机响应

```python
def _create_crisis_response(
    self,
    emotional_ctx: EmotionalInterpretation,
) -> Action:
    """创建危机响应"""
    
    # 提取关键词用于个性化
    topic = ""
    if emotional_ctx.explicit_signals:
        topic = emotional_ctx.explicit_signals[0]
    
    response = (
        "I'm really sorry you're going through this. "
        "What you're describing sounds really painful, "
        "and I want you to know you don't have to face it alone.\n\n"
        "Please reach out to a crisis helpline in your area:\n"
        "- US: 988 Suicide & Crisis Lifeline (call or text 988)\n"
        "- UK: Samaritans (116 123)\n"
        "- China: Beijing Psychological Crisis Research (010-82951332)\n\n"
        "If you're in immediate danger, please contact emergency services (911/120/110) right away.\n\n"
        "I'm here to listen, and I'm not going anywhere."
    )
    
    return Action(
        type="direct_reply",
        content=response,
        inner_thoughts=f"[CRISIS_RESPONSE] High-risk emotional signal detected: {topic}. Safety response provided without model invocation.",
    )
```

### 5.3 高风险处理原则

Phase 19 确立的高风险处理原则：

| 原则 | 说明 |
|------|------|
| **模型独立** | 高风险判断不依赖主模型自我审查 |
| **短路处理** | 不调用 publish_task / tool_call |
| **安全回复** | 提供危机热线和资源 |
| **不判断真假** | 假设高风险信号为真 |
| **持续倾听** | 表示陪伴

---

## 6. 支持策略塑形

### 6.1 中/高风险支持模式

```python
def _resolve_support_policy(
    self,
    emotional_ctx: EmotionalInterpretation,
    memory_support_pref: SupportPreference | None,
) -> SupportPolicyDecision:
    """解析支持策略"""
    
    # 1. 当前请求偏好
    current_pref = emotional_ctx.support_preference
    
    # 2. 记忆中的偏好
    memory_pref = memory_support_pref
    
    # 3. 解决冲突：当前请求 > 记忆偏好
    effective_pref = current_pref
    if current_pref == SupportPreference.UNKNOWN and memory_pref:
        effective_pref = memory_pref
    
    # 4. 确定支持模式
    if emotional_ctx.emotional_risk == EmotionalRisk.HIGH:
        # 高风险 → 安全约束模式（已在 _create_crisis_response 处理）
        support_mode = SupportMode.CRISIS_RESPONSE
        constraints = [
            "do not offer solutions",
            "do not ask problem-solving questions",
            "validate emotions first",
            "provide crisis resources",
        ]
    elif emotional_ctx.emotional_risk == EmotionalRisk.MEDIUM:
        # 中风险 → 安全约束模式
        support_mode = SupportMode.SAFETY_CONSTRAINED
        constraints = [
            "keep advice conservative",
            "prioritize emotional validation",
            "do not rush to solutions",
        ]
    elif effective_pref == SupportPreference.LISTENING:
        support_mode = SupportMode.LISTENING_HEAVY
        constraints = ["prioritize listening", "reflect back", "do not interrupt"]
    elif effective_pref == SupportPreference.PROBLEM_SOLVING:
        support_mode = SupportMode.SOLUTION_HEAVY
        constraints = ["offer structured help", "break down steps"]
    else:
        support_mode = SupportMode.NORMAL
        constraints = []
    
    return SupportPolicyDecision(
        support_mode=support_mode,
        policy_constraints=constraints,
        emotional_context=self._format_emotional_context(emotional_ctx),
        support_preference_from_memory=memory_pref,
        reasoning=f"emotional_risk={emotional_ctx.emotional_risk}, current_pref={current_pref}, memory_pref={memory_pref}",
    )
```

### 6.2 Prompt 注入

支持策略决策注入到 prompt：

```
## Emotional Context
Emotion: sadness | intensity: medium | duration: sustained
Risk Level: medium

## Support Policy
Mode: safety_constrained
Constraints:
- keep advice conservative
- prioritize emotional validation
- do not rush to solutions
```

### 6.3 安全约束模式提示

```python
SAFETY_CONSTRAINED_INSTRUCTIONS = """
In this mode:
- Keep advice practical and low-stakes
- Do not suggest major life changes
- Focus on immediate next steps only
- Validate the user's feelings before offering any guidance
- Prefer questions over statements when possible
""".strip()
```

---

## 7. 支持偏好记忆格式化

### 7.1 记忆格式化区分

Phase 19 的检索结果格式化支持偏好记忆**可区分**：

```
Phase 19 之前
     ↓
## Retrieved Context
- 用户偏好倾听，不要急着给建议

Phase 19 现在
     ↓
## Retrieved Context
- [support_preference|fact|confirmed] 用户偏好倾听，不要急着给建议
- [support_preference|inference|active] 用户遇到问题希望先被倾听
```

### 7.2 支持偏好 Key 结构

```python
SUPPORT_PREFERENCE_KEYS = {
    SupportPreference.LISTENING: "support_preference:listening",
    SupportPreference.PROBLEM_SOLVING: "support_preference:problem_solving",
    SupportPreference.MIXED: "support_preference:mixed",
}
```

### 7.3 格式化函数

```python
def _format_retrieved_context(self, matches: list[dict]) -> str:
    lines = []
    for item in matches:
        content = item.get("content", "")
        truth_type = item.get("truth_type", "unknown")
        status = item.get("status", "active")
        
        # 支持偏好特殊标记
        if "support_preference" in item.get("namespace", ""):
            prefix = f"[support_preference|{truth_type}|{status}]"
            line = f"{prefix} {content}"
        else:
            prefix = f"[{truth_type}|{status}]"
            line = f"{prefix} {content}"
        
        lines.append(line)
    
    return "\n".join(lines) if lines else "- No retrieved context."
```

---

## 8. SignalExtractor 支持偏好学习

### 8.1 新增支持偏好提取

Phase 19 的 SignalExtractor 现在可以提取支持偏好信号：

```python
async def handle_dialogue_ended(self, event: Event) -> None:
    """处理对话结束事件"""
    
    dialogue = event.payload.get("dialogue", "")
    user_id = event.payload.get("user_id")
    session_id = event.payload.get("session_id")
    
    # 1. 原有功能：会话适应信号
    await self._emit_session_adaptation_signals(dialogue, user_id, session_id)
    
    # 2. Phase 19 新增：支持偏好显式声明检测
    support_pref_signal = self._extract_support_preference(dialogue)
    
    if support_pref_signal:
        # 通过 lesson_generated 路径持久化
        await self._emit_support_preference_lesson(
            signal=support_pref_signal,
            user_id=user_id,
            session_id=session_id,
        )


def _extract_support_preference(self, dialogue: str) -> InteractionSignal | None:
    """提取支持偏好信号"""
    text_lower = dialogue.lower()
    
    # 倾听偏好
    LISTENING_PATTERNS = [
        "just listen",
        "listen first",
        "先听我说",
        "不要急着给建议",
        "i just need to vent",
        "don't solve",
        "not looking for advice",
        "just let me talk",
    ]
    
    for pattern in LISTENING_PATTERNS:
        if pattern in text_lower:
            return InteractionSignal(
                signal_type="support_preference",
                user_id="",  # 由调用方填充
                session_id="",  # 由调用方填充
                content="support_preference:listening",
                confidence=0.95,
                metadata={"explicit": True, "pattern": pattern},
            )
    
    # 解决问题偏好
    PROBLEM_SOLVING_PATTERNS = [
        "help me solve",
        "tell me what to do",
        "give me steps",
        "直接告诉我怎么做",
        "solve this",
        "find a solution",
        "what should i do",
    ]
    
    for pattern in PROBLEM_SOLVING_PATTERNS:
        if pattern in text_lower:
            return InteractionSignal(
                signal_type="support_preference",
                user_id="",
                session_id="",
                content="support_preference:problem_solving",
                confidence=0.95,
                metadata={"explicit": True, "pattern": pattern},
            )
    
    return None
```

### 8.2 支持偏好 Lesson 生成

```python
async def _emit_support_preference_lesson(
    self,
    signal: InteractionSignal,
    user_id: str,
    session_id: str,
) -> None:
    """生成支持偏好 lesson"""
    
    pref_type = signal.content  # e.g., "support_preference:listening"
    
    lesson = {
        "user_id": user_id,
        "session_id": session_id,
        "content": f"用户表达了支持偏好: {pref_type}",
        "type": "support_preference",
        "is_self_cognition": False,
        "is_world_model": True,
        "confidence": signal.confidence,
        "metadata": {
            "signal_type": signal.signal_type,
            "pattern": signal.metadata.get("pattern"),
            "explicit": signal.metadata.get("explicit", False),
        },
    }
    
    # 通过事件总线发出
    event = Event(
        type="lesson_generated",
        payload={"lesson": lesson, "signal": asdict(signal)},
    )
    
    await self.event_bus.emit(event)
```

---

## 9. CognitionUpdater 支持偏好处理

### 9.1 支持偏好分类路由

Phase 19 的 CognitionUpdater 对支持偏好进行分类：

```python
async def handle_lesson_generated(self, event: Event) -> None:
    lesson = event.payload["lesson"]
    
    # 支持偏好处理（Phase 19 新增）
    if lesson.get("type") == "support_preference":
        await self._handle_support_preference_lesson(lesson)
        return
    
    # Phase 18 的原有逻辑
    if lesson.is_self_cognition:
        await self._handle_self_cognition(lesson)
    elif lesson.is_world_model:
        await self._handle_world_model(lesson)


async def _handle_support_preference_lesson(
    self,
    lesson: dict,
) -> None:
    """处理支持偏好 lesson"""
    
    pref_key = lesson["content"].replace("用户表达了支持偏好: ", "")
    user_id = lesson["user_id"]
    
    # 分类到稳定 key
    stable_key = self._to_stable_key(pref_key)
    
    if lesson.get("metadata", {}).get("explicit"):
        # 显式声明 → FactualMemory
        memory = FactualMemory(
            content=f"用户支持偏好: {pref_key}",
            source="user_statement",
            confidence=lesson["confidence"],
            updated_at=utc_now(),
            confirmed_by_user=False,  # 通过 Phase 18 候选管道确认
            time_horizon="long_term",
            sensitivity="normal",
        )
        
        # 通过候选管道
        await self.candidate_manager.submit(
            user_id=user_id,
            affected_area=EvolutionAffectedArea.WORLD_MODEL_FACT,
            proposed_change={
                "type": "upsert",
                "key": stable_key,
                "memory": asdict(memory),
            },
            evidence=[lesson],
            context_ids=[lesson.get("session_id", "")],
        )
    else:
        # 非显式 → InferredMemory
        memory = InferredMemory(
            content=f"用户可能偏好: {pref_key}",
            inference_chain=["从对话行为推断"],
            confidence=lesson["confidence"],
            updated_at=utc_now(),
            confirmed_by_user=False,
            truth_type="inference",
            time_horizon="long_term",
            sensitivity="normal",
            status="pending_confirmation",
        )
        
        # 通过候选管道
        await self.candidate_manager.submit(
            user_id=user_id,
            affected_area=EvolutionAffectedArea.WORLD_MODEL_INFERENCE,
            proposed_change={
                "type": "upsert",
                "key": stable_key,
                "memory": asdict(memory),
            },
            evidence=[lesson],
            context_ids=[lesson.get("session_id", "")],
        )
```

### 9.2 稳定 Key 映射

```python
STABLE_KEY_MAPPING = {
    "support_preference:listening": "support_preference:listening",
    "support_preference:problem_solving": "support_preference:problem_solving",
    "support_preference:mixed": "support_preference:mixed",
}


def _to_stable_key(self, pref_key: str) -> str:
    """转换为稳定 key"""
    return STABLE_KEY_MAPPING.get(pref_key, pref_key)
```

---

## 10. 支持偏好 vs 情感状态

### 10.1 关键区分

Phase 19 明确区分两种记忆：

| 类型 | 持久性 | 示例 | 处理 |
|------|--------|------|------|
| **当前情感状态** | 临时，ephemeral | 用户现在悲伤 | 仅 prompt-facing，不写入持久记忆 |
| **支持偏好** | 持久 durable | 用户喜欢倾听 | 通过候选管道学习 |

### 10.2 当前情感状态不持久化

```python
# Phase 19 原则
"""
当前轮次的情感解读**不**写入持久确认记忆。

原因：
- 情感是波动的，今天悲伤不代表明天悲伤
- 频繁变化的状态不适合作为长期事实
- prompt-facing 足以支持当前回复
"""
```

### 10.3 支持偏好持久化

```python
# Phase 19 原则
"""
支持偏好（用户喜欢倾听还是解决问题）是**稳定偏好**，可以持久化。

原因：
- 偏好相对稳定
- 跨会话一致性有价值
- 通过候选管道控制，确保高质量
"""
```

---

## 11. 验证与验收

### 11.1 验证命令

```bash
# 情感/支持策略专项测试
python -m pytest tests/test_soul_engine.py \
  tests/test_emotional_support_policy.py \
  tests/test_relationship_memory.py \
  tests/test_integration_runtime.py \
  tests/test_runtime_bootstrap.py

# 完整测试套件
python -m pytest

# 字节码编译检查
python -m compileall app tests
```

### 11.2 验收检查项

- [ ] 90 个测试全部通过（Phase 18 的 82 + Phase 19 新增）
- [ ] `test_emotional_support_policy.py` 存在且覆盖关键路径
- [ ] EmotionalInterpretation / SupportPolicyDecision 类型正确
- [ ] 情感类别、强度、持续性、风险级别定义完整
- [ ] 支持偏好推断正确识别 listening / problem_solving 信号
- [ ] 高风险情感短路处理正确（不调用模型）
- [ ] 中风险情感塑形为 safety_constrained 模式
- [ ] 支持偏好记忆格式化可区分（support_preference 前缀）
- [ ] SignalExtractor 正确提取支持偏好信号
- [ ] CognitionUpdater 支持偏好分类路由正确
- [ ] 支持偏好通过 Phase 18 候选管道而非直接写入
- [ ] 当前情感状态不写入持久记忆
- [ ] prompt 正确注入情感上下文和支持策略

### 11.3 测试覆盖

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/test_emotional_support_policy.py` | Phase 19 新增，测试情感解释、支持策略、高风险短路 |
| `tests/test_soul_engine.py` | 更新覆盖情感支持 |
| `tests/test_relationship_memory.py` | 更新支持偏好格式化 |
| `tests/test_integration_runtime.py` | 更新 |
| `tests/test_runtime_bootstrap.py` | 更新 |

---

## 12. Explicitly Not Done Yet

以下功能在 Phase 19 中**仍未完成**：

- [ ] 按国家/地区本地化的热线/资源查询
- [ ] 持久情感状态时间线或衰减模型
- [ ] `/health` 或 `/evolution/journal` 中的专用情感风险审计面
- [ ] 超越 `listening` / `problem_solving` / `mixed` 的更丰富支持偏好 taxonomy
- [ ] 临床升级工作流、治疗声明或危机专家角色行为

---

## 13. Phase 19 的意义

### 13.1 从"能回复"到"懂情感"

Phase 19 完成后，系统从"能回复"升级到"懂情感"：

```
Phase 18 之前
     ↓
用户消息 → 模型推理 → 回复
     ↓
无情感理解，无安全保护

Phase 19 新增
     ↓
用户消息 → 情感解释 → 风险评估
     ↓
HIGH  → 短路 → 安全回复
MEDIUM → 塑形 → 保守策略
LOW   → 正常 → 模型推理
     ↓
支持偏好学习 → 持久记忆
```

### 13.2 安全与个性化的平衡

Phase 19 确立了安全与个性化的平衡：

```
安全优先
     ↓
高风险情感不依赖模型判断
     ↓
规则基础解释，模型独立短路

个性化其次
     ↓
支持偏好通过候选管道学习
     ↓
确保高质量、可追溯、可回滚
```

### 13.3 为未来 Phase 奠定基础

Phase 19 建立的情感理解是后续 Phase 的基石：

- 本地化危机资源 → 扩展安全回复内容
- 情感时间线 → 基于当前情感状态扩展
- 更丰富支持偏好 → 基于当前三种偏好扩展
- 临床升级 → 基于当前危机响应扩展

### 13.4 关键设计原则

Phase 19 确立的关键设计原则：

| 原则 | 说明 |
|------|------|
| **规则基础** | 情感解释是确定性的，非ML |
| **模型独立** | 高风险判断不依赖主模型 |
| **安全优先** | 高风险立即短路 |
| **临时 vs 持久** | 当前情感状态不持久，支持偏好持久 |
| **候选管道** | 支持偏好通过 Phase 18 管道，确保质量 |
| **可区分格式** | 检索结果中支持偏好可识别 |

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[LONG_TERM_COMPANION_PLAN.md|LONG_TERM_COMPANION_PLAN]] — 长期陪伴计划
- [[Phase-18-学习笔记]] — 受控进化管道
- [[../phase_19_status.md|phase_19_status.md]] — Phase 19 给 Codex 的状态文档
