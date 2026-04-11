# Preference Memory Pipeline

## Goal

Store durable user preferences without relying on a single extraction strategy.

The implemented design uses three layers:

1. Rule-based extraction for high-confidence explicit statements.
2. Observer triple extraction for broader phrasing coverage.
3. Existing memory governance and `CognitionUpdater` write controls for durable storage.

## What Changed

### 1. Rule-based explicit preference capture

File: `app/evolution/signal_extractor.py`

Added a new explicit-preference lesson extractor that emits `lesson_generated` for direct user statements such as:

- `I like Python`
- `I prefer TypeScript`
- `I use VSCode`
- `我很喜欢 Python`
- `我偏好简洁回复`

The extractor writes structured lesson details instead of writing memory directly:

- `domain=explicit_preference`
- `details.preference_relation`
- `details.preference_object`
- `details.explicit_user_statement=true`

This keeps extraction and storage decoupled.

### 2. Observer triples now bridge into the same lesson pipeline

File: `app/evolution/observer.py`

The observer prompt was rewritten into stable English and now asks for:

- explicit user facts only
- `subject='user'`
- allowed durable relations only
- JSON array output with confidence

When the observer extracts a durable preference triple such as `user PREFERS Python`, it now emits a matching `lesson_generated` event. This means open-ended model extraction and rule extraction both feed the same governance path.

`observation_done` remains available as an audit/debug event, but it is no longer the only artifact produced by observer extraction.

### 3. Durable storage for explicit preference lessons

File: `app/evolution/cognition_updater.py`

`CognitionUpdater._classify_memory()` now recognizes `domain="explicit_preference"` and promotes it into durable factual memory with stable keys like:

- `fact:explicit_preference:likes:python`
- `fact:explicit_preference:prefers:typescript`
- `fact:explicit_preference:uses:vscode`

This means explicit user preference statements can be merged, deduplicated, governed, inspected, corrected, and deleted through the existing memory governance APIs.

### 4. Foreground prompt safety

File: `app/soul/engine.py`

Added a prompt constraint:

- do not claim the system stored or remembered a new user fact unless it already appears in the supplied world model

This reduces false claims like "I remembered that" when the write path has not completed.

## Current Flow

### Explicit rule match

User says `I like Python`
-> `SignalExtractor`
-> `lesson_generated`
-> `CognitionUpdater`
-> governed factual memory write

### Observer match

User says something less templated but still explicit
-> `ObserverEngine`
-> extracted triple
-> `lesson_generated`
-> `CognitionUpdater`
-> governed memory write

## Verification

Relevant tests added or updated:

- `tests/test_emotional_support_policy.py`
- `tests/test_relationship_memory.py`
- `tests/test_observer_preferences.py`

Verified with:

```powershell
pytest tests\test_emotional_support_policy.py tests\test_relationship_memory.py tests\test_observer_preferences.py -q
```

Result:

- `19 passed`

## Known Limits

- The running `uvicorn` process must be restarted or hot-reloaded before live HTTP traffic uses these changes.
- The observer path still depends on the configured extraction model being reachable.
- The rule extractor currently focuses on explicit first-person statements. More implicit preference phrasing can still be added later.

## Recommended Next Steps

1. Restart the running app process so the live runtime loads the new extractor and updater code.
2. Add journal records for accepted preference-memory writes if you want the `/evolution/journal` endpoint to show successful preference promotions directly.
3. Expand preference categories over time, for example:
   - preferred languages
   - preferred tooling
   - communication preferences
   - workflow habits
