"""JSON-backed prompt template store."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


PROMPT_STORE_PATH = Path(__file__).with_name("templates.json")


@lru_cache(maxsize=1)
def load_prompt_templates() -> dict[str, str]:
    """Load prompt templates from the package JSON store."""

    with PROMPT_STORE_PATH.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    prompts = payload.get("prompts", {})
    if not isinstance(prompts, dict):
        raise ValueError("prompt store must contain a 'prompts' object")
    normalized: dict[str, str] = {}
    for key, value in prompts.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("prompt store keys and values must be strings")
        normalized[key] = value.strip()
    return normalized


def get_prompt_template(key: str) -> str:
    """Fetch a single prompt template by key."""

    prompts = load_prompt_templates()
    if key not in prompts:
        raise KeyError(f"prompt template not found: {key}")
    return prompts[key]
