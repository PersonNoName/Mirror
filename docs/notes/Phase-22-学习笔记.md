# Phase 22 学习笔记：伴侣评估套件

> **前置阶段**：[[Phase-21-学习笔记]]  
> **目标**：建立专用的伴侣评估切片，支持多轮/多会话的确定性回归测试  
> **里程碑**：本阶段完成后系统具备长期伴侣行为回归测试能力，覆盖 Phase 16-21 的关键场景

---

## 目录

- [概述](#概述)
- [1. Phase 22 文件清单](#1-phase-22-文件清单)
- [2. 为什么需要评估套件](#2-为什么需要评估套件)
- [3. 评估数据结构](#3-评估数据结构)
- [4. EvalHarness 设计](#4-evalharness-设计)
- [5. 场景定义](#5-场景定义)
- [6. 六长期场景](#6-六长期场景)
- [7. 伴侣指标集](#7-伴侣指标集)
- [8. 评估测试](#8-评估测试)
- [9. pytest 标记](#9-pytest-标记)
- [10. 验证与验收](#10-验证与验收)
- [11. Explicitly Not Done Yet](#11-explicitly-not-done-yet)
- [12. Phase 22 的意义](#12-phase-22-的意义)

---

## 概述

### 目标

Phase 22 的目标是**建立伴侣评估套件**，让系统具备：

- 专用的评估目录切片（`tests/evals/`）
- 结构化评估数据结构
- 可复用的进程内 EvalHarness
- 六长期伴侣场景覆盖
- 确定性伴侣指标集
- 多轮/多会话回归测试

### Phase 21 到 Phase 22 的演进

Phase 21 建立了用户记忆治理，系统具备完整的记忆控制能力。Phase 22 则关注**系统行为可验证性**：

```
Phase 21 完成时
     ↓
Phase 0-21 全部完成
     ↓
系统具备完整能力
     ↓
但缺乏长期行为回归测试
     ↓
     ↓
┌─────────────────────────────────────────┐
│  Phase 21 的测试缺失                      │
├─────────────────────────────────────────┤
│  • 单元测试仅覆盖单模块                   │
│  • 无多轮/多会话场景测试                 │
│  • 无跨系统回归验证                       │
│  • 无长期行为指标测量                     │
└─────────────────────────────────────────┘

Phase 22 新增
     ↓
伴侣评估套件
     ↓
tests/evals/ 独立目录
     ↓
EvalHarness 连接真实子系统
     ↓
六长期场景覆盖
     ↓
确定性指标测量
```

### 评估设计原则

```
Phase 22 评估原则
     ↓
┌─────────────────────────────────────────┐
│  1. 本地确定性                           │
│     - 无真实 Redis/Postgres/Neo4j/Qdrant │
│     - 无外部 judge 模型                  │
│     - 所有测试确定性可复现                │
├─────────────────────────────────────────┤
│  2. 低侵入                              │
│     - 无生产端点变更                     │
│     - 无运行时契约变更                   │
│     - 无新存储依赖                       │
├─────────────────────────────────────────┤
│  3. 场景复用                            │
│     - 复用已实现的 Phase16-21 能力      │
│     - 不添加 mock-only 产品行为         │
└─────────────────────────────────────────┘
```

---

## 1. Phase 22 文件清单

| 文件 | 内容 |
|------|------|
| `tests/evals/` | 评估目录（新增） |
| `tests/evals/fixtures.py` | 评估数据结构定义 |
| `tests/evals/scenarios.py` | 场景包定义 |
| `tests/test_companion_evals.py` | Phase 22 新增，顶层评估测试 |
| `tests/evals/__init__.py` | 评估包初始化 |
| `pytest.ini` | 更新：eval 标记 |

---

## 2. 为什么需要评估套件

### 2.1 之前的问题

Phase 21 之前，测试存在以下局限：

| 问题 | 描述 | 影响 |
|------|------|------|
| **单元测试局限** | 仅覆盖单模块正确性 | 无法验证跨系统交互 |
| **无多会话测试** | 无法验证跨会话记忆/关系 | 长期行为无保证 |
| **无回归网** | 修改可能破坏 Phase16-21 能力 | 迭代风险高 |
| **无指标测量** | 无长期行为量化指标 | 改进无依据 |

### 2.2 评估套件的价值

```
评估套件 = 确定性 + 可复现 + 指标化

价值1: 回归保证
    ↓
新增 Phase 可验证之前能力未破坏
     ↓
安全迭代

价值2: 多会话验证
    ↓
跨会话记忆/关系/人格连续性
     ↓
长期行为正确

价值3: 指标驱动
    ↓
量化伴侣行为质量
     ↓
改进有依据
```

---

## 3. 评估数据结构

### 3.1 CompanionEvalScenario

```python
@dataclass
class CompanionEvalScenario:
    """伴侣评估场景"""
    
    name: str                           # 场景名称
    description: str                    # 场景描述
    turns: list[CompanionEvalTurn]     # 评估轮次
    expected_metrics: dict[str, float]  # 期望指标值
    tags: list[str]                     # 场景标签
```

### 3.2 CompanionEvalTurn

```python
@dataclass
class CompanionEvalTurn:
    """伴侣评估单轮"""
    
    turn_id: int                       # 轮次ID
    user_message: str                  # 用户消息
    expected_action_type: str | None   # 期望动作类型（可选）
    expected_memory_keys: list[str]    # 期望记忆键（可选）
    expected_stage: str | None         # 期望关系阶段（可选）
    expected_support_mode: str | None  # 期望支持模式（可选）
    metadata: dict                     # 元数据
```

### 3.3 CompanionEvalResult

```python
@dataclass
class CompanionEvalResult:
    """伴侣评估结果"""
    
    scenario_name: str                    # 场景名称
    passed: bool                        # 是否通过
    turn_results: list[CompanionEvalTurnResult]  # 每轮结果
    metric_results: list[CompanionMetricResult]  # 指标结果
    total_turns: int                   # 总轮次
    passed_turns: int                  # 通过轮次
    failed_turns: int                  # 失败轮次
```

### 3.4 CompanionMetricResult

```python
@dataclass
class CompanionMetricResult:
    """伴侣指标结果"""
    
    metric_name: str                   # 指标名称
    score: float                       # 得分 0.0-1.0
    threshold: float                   # 阈值
    passed: bool                      # 是否通过
    details: dict                     # 详情
```

---

## 4. EvalHarness 设计

### 4.1 目的

```python
class EvalHarness:
    """
    评估工具
    - 进程内复用真实子系统
    - 无外部依赖
    - 确定性可复现
    """
```

### 4.2 连接组件

```python
class EvalHarness:
    def __init__(self) -> None:
        # Phase 16-21 的核心子系统
        self.soul_engine: SoulEngine
        self.cognition_updater: CognitionUpdater
        self.personality_evolver: PersonalityEvolver
        self.relationship_state_machine: RelationshipStateMachine
        self.memory_governance_service: MemoryGovernanceService
        
        # 状态
        self.journal: EvolutionJournal
        self.candidate_manager: EvolutionCandidateManager
        self.snapshot_store: PersonalitySnapshotStore
        self.world_model_state: WorldModel
```

### 4.3 运行场景

```python
async def run_scenario(
    self,
    scenario: CompanionEvalScenario,
    user_id: str = "eval_user",
) -> CompanionEvalResult:
    """运行评估场景"""
    
    turn_results = []
    
    for turn in scenario.turns:
        # 1. 构建入站消息
        message = InboundMessage(
            text=turn.user_message,
            user_id=user_id,
            session_id=f"session_{turn.turn_id}",
        )
        
        # 2. 运行 SoulEngine
        action = await self.soul_engine.run(message)
        
        # 3. 验证动作
        turn_result = await self._verify_turn(turn, action, user_id)
        turn_results.append(turn_result)
        
        # 4. 处理对话结束事件（触发进化）
        await self._process_dialogue_ended(message, user_id)
    
    # 5. 计算指标
    metric_results = await self._compute_metrics(scenario, turn_results)
    
    # 6. 判断通过
    passed = all(m.passed for m in metric_results)
    
    return CompanionEvalResult(
        scenario_name=scenario.name,
        passed=passed,
        turn_results=turn_results,
        metric_results=metric_results,
        total_turns=len(scenario.turns),
        passed_turns=sum(1 for r in turn_results if r.passed),
        failed_turns=sum(1 for r in turn_results if not r.passed),
    )
```

### 4.4 本地确定性设计

```python
# 无外部依赖
LOCAL_DEPENDENCIES = {
    "Redis": None,           # 不使用
    "Postgres": None,        # 不使用
    "Neo4j": None,           # 不使用
    "Qdrant": None,          # 不使用
    "ExternalJudge": None,   # 不使用
}

# 使用内存实现
class InMemoryTaskStore:
    ...

class InMemoryOutboxStore:
    ...

class InMemoryJournal:
    ...
```

---

## 5. 场景定义

### 5.1 场景结构

```python
# tests/evals/scenarios.py

COMPANION_SCENARIOS: list[CompanionEvalScenario] = [
    multi_session_memory_accuracy,
    relationship_continuity_progression,
    emotional_support_mode_stability,
    mistaken_learning_and_governance,
    personality_drift_and_rollback,
    repair_recovery_continuity,
]
```

### 5.2 场景包组织

```python
SCENARIO_PACKS = {
    "memory": [
        multi_session_memory_accuracy,
        mistaken_learning_and_governance,
    ],
    "relationship": [
        relationship_continuity_progression,
        repair_recovery_continuity,
    ],
    "personality": [
        personality_drift_and_rollback,
    ],
    "emotional": [
        emotional_support_mode_stability,
    ],
}
```

---

## 6. 六长期场景

### 6.1 multi_session_memory_accuracy

**多会话记忆准确性**

```
场景：用户在不同会话中提到的事实应被记住

轮次1: 用户说"我叫张三"
轮次2: 用户说"我喜欢Python"
轮次3: 用户问"我叫什么名字？" → 应回答"张三"

指标：memory_accuracy >= 0.8
```

### 6.2 relationship_continuity_progression

**关系连续性演进**

```
场景：关系阶段应随多次交互逐步演进

轮次1-3: 初始交互 → unfamiliar
轮次4-6: 多次正面交互 → trust_building
轮次7-9: 持续正面交互 → stable_companion

指标：relationship_continuity >= 0.9
```

### 6.3 emotional_support_mode_stability

**情感支持模式稳定性**

```
场景：相同情感信号应路由到相同的支持模式

轮次1: 用户说"我最近很焦虑" → medium risk → safety_constrained
轮次2: 用户说"压力好大" → medium risk → safety_constrained
轮次3: 用户说"心里很难受" → medium risk → safety_constrained

指标：consistency >= 0.9
```

### 6.4 mistaken_learning_and_governance

**错误学习与治理**

```
场景：用户可通过治理修正错误记忆

轮次1: 用户说"我擅长Java"
轮次2: 用户通过 /memory/correct 修正为"我擅长Python"
轮次3: 系统记忆应为"擅长Python"，非"擅长Java"

指标：mistaken_learning_rate <= 0.1
```

### 6.5 personality_drift_and_rollback

**人格漂移与回滚**

```
场景：人格漂移应触发回滚

轮次1-5: 正常交互
轮次6-10: 大量冲突信号
轮次11: 检测到漂移 → 触发回滚
轮次12: 人格应恢复到漂移前状态

指标：drift_rate <= 0.1
```

### 6.6 repair_recovery_continuity

**修复恢复连续性**

```
场景：关系破裂后应进入修复阶段

轮次1-5: stable_companion
轮次6: 用户表达强烈不满 → repair_and_recovery
轮次7-10: 修复交互 → 恢复到 trust_building

指标：relationship_continuity >= 0.8
```

---

## 7. 伴侣指标集

### 7.1 固定指标词汇

```python
COMPANION_METRICS = {
    "memory_accuracy": {
        "description": "记忆准确性 - 系统记住的事实与用户陈述一致",
        "threshold": 0.8,
        "measurement": "正确记忆数 / 总记忆数",
    },
    "consistency": {
        "description": "一致性 - 相同输入应产生相同输出",
        "threshold": 0.9,
        "measurement": "一致响应数 / 总响应数",
    },
    "felt_understanding_proxy": {
        "description": "被理解感代理 - 正确使用记忆 + 正确路由支持模式 + 正确的修复阶段提示",
        "threshold": 0.8,
        "measurement": "综合代理指标",
    },
    "relationship_continuity": {
        "description": "关系连续性 - 关系阶段转换符合预期",
        "threshold": 0.8,
        "measurement": "正确转换数 / 总转换数",
    },
    "mistaken_learning_rate": {
        "description": "错误学习率 - 被治理修正的错误记忆比例",
        "threshold": 0.1,
        "measurement": "错误记忆数 / 总新记忆数",
    },
    "drift_rate": {
        "description": "漂移率 - 人格漂移触发回滚的比例",
        "threshold": 0.1,
        "measurement": "回滚次数 / 进化尝试次数",
    },
}
```

### 7.2 felt_understanding_proxy 实现

"felt understanding" 使用代理指标实现，非主观评分：

```python
def _compute_felt_understanding_proxy(
    self,
    turn_results: list[CompanionEvalTurnResult],
) -> CompanionMetricResult:
    """
    felt_understanding_proxy = 代理指标
    - 正确记忆使用
    - 正确支持模式路由
    - 正确的修复阶段提示约束
    """
    
    correct_memory_use = 0
    correct_support_mode = 0
    correct_repair_constraint = 0
    total = len(turn_results)
    
    for result in turn_results:
        if result.memory_used_correctly:
            correct_memory_use += 1
        if result.support_mode_correct:
            correct_support_mode += 1
        if result.repair_constraint_correct:
            correct_repair_constraint += 1
    
    # 代理得分
    score = (
        correct_memory_use / total * 0.4 +
        correct_support_mode / total * 0.3 +
        correct_repair_constraint / total * 0.3
    )
    
    return CompanionMetricResult(
        metric_name="felt_understanding_proxy",
        score=score,
        threshold=COMPANION_METRICS["felt_understanding_proxy"]["threshold"],
        passed=score >= 0.8,
        details={
            "correct_memory_use_rate": correct_memory_use / total,
            "correct_support_mode_rate": correct_support_mode / total,
            "correct_repair_constraint_rate": correct_repair_constraint / total,
        },
    )
```

---

## 8. 评估测试

### 8.1 test_companion_evals.py

```python
# tests/test_companion_evals.py

@pytest.mark.eval
class TestCompanionEvals:
    """伴侣评估测试"""
    
    async def test_all_scenarios_pass(self):
        """所有场景应通过"""
        harness = EvalHarness()
        scenarios = load_scenarios()
        
        results = []
        for scenario in scenarios:
            result = await harness.run_scenario(scenario)
            results.append(result)
        
        # 验证所有场景通过
        failed = [r for r in results if not r.passed]
        assert len(failed) == 0, f"Failed scenarios: {[r.scenario_name for r in failed]}"
    
    async def test_metric_aggregation(self):
        """指标应正确聚合"""
        harness = EvalHarness()
        scenarios = load_scenarios()
        
        all_metrics = {}
        for scenario in scenarios:
            result = await harness.run_scenario(scenario)
            for metric in result.metric_results:
                if metric.metric_name not in all_metrics:
                    all_metrics[metric.metric_name] = []
                all_metrics[metric.metric_name].append(metric.score)
        
        # 验证所有指标名称存在
        for expected_metric in COMPANION_METRICS.keys():
            assert expected_metric in all_metrics
    
    async def test_scenario_metric_thresholds(self):
        """场景指标应达到阈值"""
        harness = EvalHarness()
        scenarios = load_scenarios()
        
        for scenario in scenarios:
            result = await harness.run_scenario(scenario)
            
            for metric_result in result.metric_results:
                threshold = COMPANION_METRICS[metric_result.metric_name]["threshold"]
                assert metric_result.score >= threshold, (
                    f"Scenario {scenario.name}, "
                    f"metric {metric_result.metric_name}: "
                    f"{metric_result.score} < {threshold}"
                )
```

### 8.2 运行评估

```bash
# 运行所有评估
python -m pytest tests/test_companion_evals.py

# 运行特定场景
python -m pytest tests/test_companion_evals.py -k "multi_session_memory"

# 运行特定指标
python -m pytest tests/test_companion_evals.py -k "memory_accuracy"
```

---

## 9. pytest 标记

### 9.1 pytest.ini 更新

```ini
[pytest]
markers =
    eval: companion evaluation tests (deselect with '-m "not eval"')
    unit: unit tests
    integration: integration tests
```

### 9.2 使用标记

```bash
# 只运行评估
python -m pytest -m eval

# 排除评估
python -m pytest -m "not eval"

# 只运行单元测试
python -m pytest -m unit
```

---

## 10. 验证与验收

### 10.1 验证命令

```bash
# 评估套件专项测试
python -m pytest tests/test_companion_evals.py

# 完整测试套件
python -m pytest

# 字节码编译检查
python -m compileall app tests
```

### 10.2 验收检查项

- [ ] 112 个测试全部通过（Phase 21 的 105 + Phase 22 新增）
- [ ] `tests/evals/` 目录存在且结构正确
- [ ] `tests/evals/fixtures.py` 定义了所有评估数据结构
- [ ] `tests/evals/scenarios.py` 定义了六场景
- [ ] `tests/test_companion_evals.py` 覆盖所有场景
- [ ] EvalHarness 正确连接 Phase 16-21 子系统
- [ ] 六场景正确实现
- [ ] 伴侣指标集正确定义
- [ ] felt_understanding_proxy 代理指标正确实现
- [ ] pytest eval 标记正确定义
- [ ] 评估套件无外部依赖
- [ ] 所有测试确定性可复现

### 10.3 测试覆盖

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/test_companion_evals.py` | 评估套件顶层测试 |

---

## 11. Explicitly Not Done Yet

以下功能在 Phase 22 中**仍未完成**：

- [ ] 外部 benchmark runner 或离线评分 CLI（仅 pytest）
- [ ] 持久化历史评估结果存储
- [ ] 人工标注 pipeline
- [ ] 模型对比 harness
- [ ] Phase 23 主动行为场景包
- [ ] Phase 24 依赖风险/操纵性语言场景包

---

## 12. Phase 22 的意义

### 12.1 从"能开发"到"能验证"

Phase 22 完成后，系统从"能开发"升级到"能验证"：

```
Phase 21 之前
     ↓
Phase 0-21 功能完成
     ↓
但无长期行为回归保证
     ↓
修改可能破坏已有能力

Phase 22 新增
     ↓
伴侣评估套件
     ↓
六长期场景覆盖
     ↓
确定性指标测量
     ↓
安全迭代有保证
```

### 12.2 评估分层

Phase 22 确立了评估分层：

```
单元测试（现有）
     ↓
模块级正确性
     ↓
集成测试（现有）
     ↓
子系统交互正确性
     ↓
评估套件（Phase 22 新增）
     ↓
多轮/多会话回归
     ↓
长期行为正确性
```

### 12.3 为未来 Phase 奠定基础

Phase 22 建立的评估套件是后续 Phase 的基石：

- Phase 23 主动行为场景 → 基于评估框架扩展
- Phase 24 风险场景 → 基于评估框架扩展
- 外部 benchmark → 可接入现有 harness
- 持久化评估结果 → 基于现有结构扩展

### 12.4 关键设计原则

Phase 22 确立的关键设计原则：

| 原则 | 说明 |
|------|------|
| **本地确定性** | 无外部依赖，所有测试可复现 |
| **低侵入** | 无生产端点/运行时变更 |
| **场景复用** | 复用 Phase 16-21 实现 |
| **指标标准化** | 固定指标词汇，不可随意变更 |
| **可扩展** | 新场景只需扩展场景定义文件 |

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[LONG_TERM_COMPANION_PLAN.md|LONG_TERM_COMPANION_PLAN]] — 长期陪伴计划
- [[Phase-21-学习笔记]] — 用户记忆治理
- [[../phase_22_status.md|phase_22_status.md]] — Phase 22 给 Codex 的状态文档
