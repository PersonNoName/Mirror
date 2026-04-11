from __future__ import annotations

import pytest

from tests.evals import COMPANION_EVAL_SCENARIOS, build_eval_harness


@pytest.mark.eval
@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", COMPANION_EVAL_SCENARIOS, ids=[item.scenario_id for item in COMPANION_EVAL_SCENARIOS])
async def test_companion_eval_scenarios_pass(scenario) -> None:
    harness = build_eval_harness()

    result = await scenario.runner(harness)

    assert result.scenario_id == scenario.scenario_id
    assert result.metrics
    assert result.passed, f"{scenario.scenario_id} failed metrics={result.metrics} failures={result.failures}"
    assert all(metric.passed for metric in result.metrics)


@pytest.mark.eval
@pytest.mark.asyncio
async def test_companion_eval_suite_aggregates_expected_metrics() -> None:
    results = []
    for scenario in COMPANION_EVAL_SCENARIOS:
        harness = build_eval_harness()
        results.append(await scenario.runner(harness))

    metric_names = {metric.name for result in results for metric in result.metrics}
    passed_count = sum(1 for result in results if result.passed)
    average_scores = {
        metric_name: (
            sum(metric.score for result in results for metric in result.metrics if metric.name == metric_name)
            / sum(1 for result in results for metric in result.metrics if metric.name == metric_name)
        )
        for metric_name in metric_names
    }

    assert len(results) == len(COMPANION_EVAL_SCENARIOS)
    assert passed_count == len(results)
    assert metric_names == {
        "memory_accuracy",
        "consistency",
        "felt_understanding_proxy",
        "relationship_continuity",
        "mistaken_learning_rate",
        "drift_rate",
    }
    assert all(score >= 1.0 for score in average_scores.values())
