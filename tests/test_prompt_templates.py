from __future__ import annotations

from app.agents.code_agent import CodeAgent
from app.prompts import (
    get_prompt_template,
    load_prompt_templates,
    render_code_agent_core_prompt,
    render_soul_core_system_prompt,
)
from app.tasks.models import Task

from tests.conftest import DummyBlackboard, DummyTaskStore


def test_prompt_templates_load_from_json_store() -> None:
    prompts = load_prompt_templates()

    assert "soul_core_system" in prompts
    assert "code_agent_core" in prompts
    assert prompts["code_agent_core"].startswith("You are Mirror's code execution agent.")


def test_get_prompt_template_reads_single_json_entry() -> None:
    prompt = get_prompt_template("soul_core_system")

    assert "## Self Cognition" in prompt
    assert "## Output Format" in prompt


def test_soul_core_prompt_template_stays_isolated_from_auto_appended_context() -> None:
    prompt = render_soul_core_system_prompt(
        self_cognition="self",
        world_model="world",
        stable_identity="identity",
        relationship_style="style",
        relationship_stage="stage",
        proactivity_policy="policy",
        emotional_context="emotion",
        user_emotional_state="user_emotion",
        agent_continuity_state="agent_continuity",
        support_policy="support",
        session_adaptations="session",
        task_experience="experience",
        tool_list="tools",
        shared_experiences="experiences",
        agent_emotional_state="agent_emotion",
    )

    assert "## Session Raw Context" not in prompt
    assert "## Retrieved Context" not in prompt
    assert "## Self Cognition" in prompt
    assert "## Output Format" in prompt


def test_code_agent_prompt_keeps_core_directive_separate_from_runtime_context() -> None:
    agent = CodeAgent(
        task_store=DummyTaskStore(),
        blackboard=DummyBlackboard(),
        task_system=object(),
        base_url="http://example.com",
    )
    task = Task(
        id="task-1",
        intent="Refactor prompt loading",
        metadata={"working_dir": "/repo", "constraints": "Keep tests green"},
    )

    prompt = agent._build_prompt(task)
    core_prompt = render_code_agent_core_prompt()

    assert prompt.startswith("Task intent: Refactor prompt loading")
    assert "Working directory: /repo" in prompt
    assert "Constraints: Keep tests green" in prompt
    assert prompt.endswith(core_prompt)
    assert "You are Mirror's code execution agent." in core_prompt
