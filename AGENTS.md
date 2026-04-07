# AGENTS.md — Mirror Agent System

## Project Overview

Mirror is an AI Agent system with a three-layer architecture:
- **Foreground Sync Layer**: Memory cache, Soul Engine (prompt builder), Action Router
- **Task Execution Layer**: Task System, Blackboard, Sub-agents
- **Background Async Evolution Layer**: Event Bus, Observer, PersonalityEvolver, CognitionUpdater, MetaCognition, EvolutionJournal

## Build / Lint / Test Commands

```bash
# Run all tests
python tests/test_full_system.py

# Run a single test (via pytest or manually)
pytest tests/test_full_system.py::test_core_memory_cache -v
python -c "import sys; sys.path.insert(0,'.'); from tests.test_full_system import test_core_memory_cache; import asyncio; asyncio.run(test_core_memory_cache())"

# Lint with ruff
ruff check .
ruff check domain/ core/ events/ evolution/ interfaces/ services/

# Format with ruff
ruff format .
```

## Code Style Guidelines

### Data Models (domain/)
- Use `pydantic.BaseModel` for all data classes
- Use `Field(default_factory=...)` for mutable defaults (lists, dicts)
- Use `uuid.uuid4()` as factory for `id` fields
- Immutable fields use `Literal` types where appropriate
- All domain exports via `domain/__init__.py`

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
import uuid
from datetime import datetime

class MyModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    items: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Async Pattern
- All business logic methods MUST be `async def`
- Use `asyncio.create_task()` for fire-and-forget, never `await` unless waiting for result
- Use `TYPE_CHECKING` guard for interface imports to avoid circular imports

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from interfaces.storage import TaskStoreInterface

class MyClass:
    def __init__(self, task_store: "TaskStoreInterface"):
        self.task_store = task_store
```

### Imports Organization
Order per file:
1. Standard library (`asyncio`, `datetime`, `typing`, `uuid`)
2. Third-party (`pydantic`)
3. Local absolute imports (`from domain.task import ...`)

```python
import asyncio
from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field

from domain.task import Task, TaskStatus
from core.memory_cache import CoreMemoryCache
```

### Naming Conventions
| Element | Convention | Example |
|---------|------------|---------|
| Classes | PascalCase | `CoreMemory`, `SoulEngine` |
| Methods/Variables | snake_case | `estimate_capability`, `task_store` |
| Constants | SCREAMING_SNAKE | `TOKEN_BUDGET_CONFIG` |
| Private methods | `_underscore` | `_serialize_with_pinning` |
| Type variables | PascalCase | `T`, `TaskT` |

### Error Handling
- Use early returns with error messages, not nested try/except
- Print `[ClassName]` prefix in log messages
- Raise exceptions for truly exceptional cases, not normal flow

```python
async def get(self, task_id: str) -> Optional[Task]:
    task = self._tasks.get(task_id)
    if not task:
        print(f"[TaskStore] Task {task_id} not found")
        return None
    return task
```

### Module Structure
```
domain/         # Pure data models (Task, CoreMemory, Event, etc.)
interfaces/     # Abstract ABCs (SubAgent, storage interfaces)
core/           # Business logic (SoulEngine, Blackboard, TaskSystem)
events/         # EventBus (async queue, pub/sub)
evolution/      # Background evolution (PersonalityEvolver, etc.)
services/       # External backend adapters (GraphDB, VectorDB)
tests/          # All tests in test_full_system.py
```

### Configuration Patterns
- Use module-level dicts for config constants
- Use Pydantic for complex config with defaults
- Keep hardcoded magic numbers in named constants

```python
TOKEN_BUDGET_CONFIG = {
    "total": 5000,
    "self_cognition": 1000,
    "world_model": 1000,
}
```

### Behavioral Rules
- Behavioral rules are the **primary evolution carrier**, NOT numeric traits
- `is_pinned: bool` marks rules immune to eviction/compression
- Rules have `source`, `confidence`, `hit_count` for tracking

### Soul Engine Prompt Template
- Templates use `{placeholder}` syntax for pre-built string sections
- Sections are built separately, then injected: `self_cognition_section`, `world_model_section`, etc.

### Dummy/Mock Objects
- Create `*Dummy` classes for external dependencies (LLM, storage)
- Dummy classes implement the same interface with in-memory storage
- Use Dummy objects in tests and when real backends are unavailable

### Testing Guidelines
- All tests are async and return `bool` (True = pass)
- Use `sys.path.insert(0, ...)` to resolve local imports
- Test naming: `test_<component>_<scenario>`
- Group related assertions in a single test

```python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

async def test_my_component():
    # arrange
    cache = CoreMemoryCache()
    # act
    result = await cache.get("user123")
    # assert
    return result is not None
```

### Type Hints
- Use lowercase for built-in types in Python 3.11+: `list[str]`, `dict[str, int]`
- For older versions or complex types, use `typing.List`, `typing.Dict`
- Use `Optional[X]` instead of `X | None` for compatibility
- Use string quotes for forward references: `"TaskStoreInterface"`

### Version Tracking
- Models with mutable state (SelfCognition, PersonalityState) include `version: int`
- Increment version on meaningful updates for CAS retry logic
