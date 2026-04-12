"""JSON-backed prompt template store."""

from __future__ import annotations

import json
from pathlib import Path


PROMPT_STORE_PATH = Path(__file__).with_name("templates.json")

_templates_cache: dict[str, str] | None = None

_DEFAULT_TEMPLATES: dict[str, str] = {
    "soul_core_system": 'You are Mirror\'s foreground reasoning agent.\nYou are a direct collaborator, not a submissive assistant.\n\n## Self Cognition\n{self_cognition}\n\n## World Model\n{world_model}\n\n## Stable Identity\n{stable_identity}\n\n## Relationship Style\n{relationship_style}\n\n## Relationship Stage\n{relationship_stage}\n\n## Proactivity Policy\n{proactivity_policy}\n\n## Emotional Context\n{emotional_context}\n\n## Support Policy\n{support_policy}\n\n## Session Adaptation\n{session_adaptations}\n\n## Task Experience\n{task_experience}\n\n## Available Tools\n{tool_list}\n\n## Constraints\n- Avoid filler acknowledgements such as "of course", "sure", or "glad to help".\n- If the user\'s request is unreasonable, record that in `<inner_thoughts>`.\n- Treat confirmed facts as highest-trust memory.\n- Never present an inferred memory as if the user explicitly confirmed it.\n- If memory conflicts exist, answer conservatively or ask for confirmation.\n- In listening mode, prioritize acknowledgement, clarification, and presence over advice.\n- In problem-solving mode, give bounded suggestions without sounding commanding or clinical.\n- In blended mode, acknowledge feelings first, then offer a small number of optional next steps.\n- Stored support preferences are hints only; current explicit user intent takes precedence.\n- In safety-constrained mode, avoid tool/task escalation and keep advice conservative.\n- Any proactive follow-up must stay low-frequency, reference prior context conservatively, and avoid repetitive reminder phrasing.\n- Do not claim you stored or remembered a new user fact unless it already appears in the supplied world model.\n- Think before acting. Every action must follow the required output format.\n\n## Output Format\n<inner_thoughts>\n[private reasoning]\n</inner_thoughts>\n<action>\n[one of: direct_reply | tool_call | publish_task | hitl_relay]\n</action>\n<content>\n[content for the selected action]\n</content>',
    "code_agent_core": "You are Mirror's code execution agent.\nComplete the task and return the result strictly in the provided JSON schema.\nPrefer a concise summary and list every changed file path when applicable.",
}


def load_prompt_templates() -> dict[str, str]:
    """Load prompt templates from the package JSON store."""

    global _templates_cache
    if _templates_cache is not None:
        return _templates_cache

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
    _templates_cache = normalized
    return normalized


def get_prompt_template(key: str) -> str:
    """Fetch a single prompt template by key."""

    prompts = load_prompt_templates()
    if key not in prompts:
        raise KeyError(f"prompt template not found: {key}")
    return prompts[key]


def get_default_prompt(key: str) -> str:
    """Fetch the default value for a prompt template."""
    if key not in _DEFAULT_TEMPLATES:
        raise KeyError(f"default not found for prompt template: {key}")
    return _DEFAULT_TEMPLATES[key]


def get_default_templates() -> dict[str, str]:
    """Return all default prompt templates."""
    return dict(_DEFAULT_TEMPLATES)


def update_prompt_template(key: str, content: str) -> None:
    """Update a single prompt template and persist to disk."""

    prompts = load_prompt_templates()
    if key not in prompts:
        raise KeyError(f"prompt template not found: {key}")

    prompts[key] = content.strip()

    global _templates_cache
    _templates_cache = prompts

    with PROMPT_STORE_PATH.open("w", encoding="utf-8") as fh:
        json.dump({"prompts": prompts}, fh, indent=2, ensure_ascii=False)


def reset_prompt_template(key: str) -> str:
    """Reset a prompt template to its default value and persist to disk."""
    if key not in _DEFAULT_TEMPLATES:
        raise KeyError(f"default not found for prompt template: {key}")

    prompts = load_prompt_templates()
    if key not in prompts:
        raise KeyError(f"prompt template not found: {key}")

    prompts[key] = _DEFAULT_TEMPLATES[key]

    global _templates_cache
    _templates_cache = prompts

    with PROMPT_STORE_PATH.open("w", encoding="utf-8") as fh:
        json.dump({"prompts": prompts}, fh, indent=2, ensure_ascii=False)

    return prompts[key]
