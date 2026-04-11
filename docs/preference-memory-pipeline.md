# Preference Memory Pipeline

## Goal

Capture user preferences without letting the agent freely promote every mention into long-term memory.

The pipeline now separates four memory outcomes:

1. Explicit fact
2. Inferred preference
3. Short-term session hint
4. Review-required candidate

## Layers

### 1. Explicit rule extraction

File: `app/evolution/signal_extractor.py`

High-confidence first-person statements still use rule extraction first.

Examples:

- `I like Python`
- `我很喜欢 Python`
- `我主要用 VSCode`

These can become `explicit_preference` lessons and later durable facts.

### 2. Meta-instruction review guard

The extractor now treats summary, translation, rewrite, polish, example, log, and quoted-content contexts as review-sensitive evidence.

Examples:

- `帮我总结一下下面的话：我喜欢 Python`
- `translate the following: I like Python`
- `这是示例文案：我喜欢 Python`

This guard runs before long-term promotion so pasted material is less likely to be mistaken for the user's own preference.

### 3. AI review for attribution

When a message is ambiguous, the lightweight reviewer model classifies whether the preference is:

- `self_reported`
- `quoted_or_forwarded`
- `uncertain`

This reviewer is a second pass. If it fails, the system falls back to conservative rule-based review.

### 4. AI extraction for implicit preference candidates

When a message is not an explicit preference statement, the system can ask the model for a structured implicit-preference candidate.

Expected output shape:

```json
{
  "classification": "self_reported | quoted_or_forwarded | uncertain",
  "preference_strength": "explicit | implicit | weak | none",
  "durability": "stable | situational | unknown",
  "relation": "likes | dislikes | prefers | uses | none",
  "object": "coffee",
  "confidence": 0.63,
  "reason": "short explanation"
}
```

Examples:

- `晚上来杯咖啡真惬意啊` -> plausible implicit candidate
- `今天好想喝点甜的` -> likely situational hint
- `帮我总结下面的话：我喜欢玩游戏` -> not a direct fact, should stay reviewed or ignored

## Storage Policy

File: `app/evolution/cognition_updater.py`

### Explicit fact

Conditions:

- explicit statement
- attributed to the user
- durable enough to promote

Stored as:

- `fact:explicit_preference:likes:python`

### Review-required candidate

Conditions:

- quoted, copied, forwarded, or ambiguous attribution

Stored as:

- pending confirmation
- inference memory key

Example:

- `inference:explicit_preference:likes:python`

### Inferred preference

Conditions:

- plausible preference signal
- not explicit enough to be a fact

Stored as `InferredMemory`.

### Short-term session hint

Conditions:

- implicit preference
- situational rather than stable

Stored as an inferred memory with:

- `time_horizon="short_term"`
- `metadata.memory_tier="session_hint"`

This avoids creating a HITL confirmation task for every soft preference cue while still preserving a bounded hint.

Example:

- `inference:implicit_preference:likes:coffee`

## Example Outcomes

### Direct preference

`我喜欢 Python`

Outcome:

- explicit fact

### Copied preference text

`下面是我复制的一段话：“我喜欢 Python”`

Outcome:

- review-required candidate
- no direct fact promotion

### Situational implicit preference

`晚上来杯咖啡真惬意啊`

Outcome:

- implicit preference candidate
- stored as short-term inferred hint, not a fact

### Summary request over supplied content

`帮我总结一下下面的话：我比较喜欢玩游戏`

Outcome:

- review-sensitive context
- should not be promoted as the user's durable preference by default

## Why This Is Better Than Keyword Growth

- Rules still cover high-precision explicit statements.
- AI handles open phrasing and indirect language.
- Governance decides storage tier instead of the extractor making a permanent decision.
- Situational expressions are no longer forced into the same bucket as durable preferences.

## Verification

Relevant tests:

- `tests/test_emotional_support_policy.py`
- `tests/test_relationship_memory.py`
- `tests/test_observer_preferences.py`
- `tests/test_runtime_bootstrap.py`

Suggested command:

```powershell
pytest tests\test_emotional_support_policy.py tests\test_relationship_memory.py tests\test_observer_preferences.py tests\test_runtime_bootstrap.py -q
```
