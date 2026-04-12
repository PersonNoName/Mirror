"""Core prompt templates for task sub-agents."""

from __future__ import annotations

from app.prompts.store import get_prompt_template


def render_code_agent_core_prompt() -> str:
    """Return the immutable code-agent instruction block."""

    return get_prompt_template("code_agent_core")
