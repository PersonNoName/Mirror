"""Core foreground prompt templates for the soul engine."""

from __future__ import annotations

from app.prompts.store import get_prompt_template


def render_soul_core_system_prompt(**sections: str) -> str:
    """Render the immutable soul prompt scaffold with injected memory sections."""

    return get_prompt_template("soul_core_system").format(**sections)
