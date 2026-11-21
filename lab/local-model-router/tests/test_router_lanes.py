"""Router lane assignment, long-log scope, unrouted, multi-file → cloud."""

from __future__ import annotations

import pytest

from local_model_router.config import RouterConfig
from local_model_router.memory import MemorySnapshot
from local_model_router.plan import FABLE_STEP, UNLOAD_12B_STEP
from local_model_router.router import next_escalation, route_job
from local_model_router.router_types import LOG_TASK_TYPES, is_coding_task

from .conftest import make_job


def _route(job_kwargs: dict, config: RouterConfig):
    return route_job(
        make_job(**job_kwargs),
        config,
        dry_run=True,
        memory_reader=lambda: MemorySnapshot(50.0, False, False, True),
    )


def test_ci_log_routes_to_12b(config: RouterConfig) -> None:
    decision = _route(
        {
            "task_type": "ci_log_summary",
            "log_kind": "ci",
            "tokens_sent": 100,
            "tokens_processed": 100,
            "source_text": "ok 1",
            "summary_text": "ok 1",
        },
        config,
    )
    assert decision.lane == "gemma4_12b"
    assert decision.aborted is False
    assert "aider_attempt_1" not in decision.plan_steps
    assert FABLE_STEP not in decision.plan_steps


def test_diff_pre_review_routes_to_12b_with_fable(config: RouterConfig) -> None:
    decision = _route({"task_type": "diff_pre_review"}, config)
    assert decision.lane == "gemma4_12b"
    assert decision.fable_review_required is True
    assert decision.plan_steps[-1] == FABLE_STEP
    assert "aider_attempt_1" in decision.plan_steps


def test_unit_tests_and_single_file_route_to_inkling(config: RouterConfig) -> None:
    for task in ("unit_tests", "single_file_fix", "strict_structured_output"):
        decision = _route({"task_type": task, "token_estimate": 3500}, config)
        assert decision.lane == "inkling_2_mini", task
        assert decision.size == "T3"
        assert decision.plan_steps[-1] == FABLE_STEP
        assert UNLOAD_12B_STEP in decision.plan_steps


def test_lint_doc_routes_to_26b(config: RouterConfig) -> None:
    decision = _route(
        {"task_type": "lint_doc_batch", "file_count": 2, "token_estimate": 6000},
        config,
    )
    assert decision.lane == "gemma4_26b"
    assert decision.size == "T3"


def test_oversize_inkling_escalates_to_azure_codex_mini(config: RouterConfig) -> None:
    decision = _route(
        {"task_type": "single_file_fix", "file_count": 1, "token_estimate": 20000},
        config,
    )
    assert decision.escalate is True
    assert decision.lane == "azure_codex_mini"
    assert decision.batch_kind == "azure"
    assert decision.fable_review_required is True


def test_multi_file_feature_escalates_to_cloud_agent(config: RouterConfig) -> None:
    decision = _route(
        {
            "task_type": "single_file_fix",
            "multi_file_feature": True,
            "file_count": 4,
        },
        config,
    )
    assert decision.lane == "cursor_cloud_agent"
    assert decision.escalate is True


def test_single_file_fix_with_two_files_escalates_to_cloud(config: RouterConfig) -> None:
    """(2) file_count > 1 that does not fit local lane → cursor_cloud_agent."""
    decision = _route(
        {"task_type": "single_file_fix", "file_count": 2, "token_estimate": 3000},
        config,
    )
    assert decision.lane == "cursor_cloud_agent"
    assert decision.escalate is True
    assert decision.batch_kind == "cloud"


def test_unknown_task_is_unrouted(config: RouterConfig) -> None:
    """(3) Unknown task types return lane unrouted with no escalation."""
    decision = _route({"task_type": "briefs_and_prompts"}, config)
    assert decision.lane == "unrouted"
    assert decision.escalate is False
    assert decision.escalation_target is None
    assert decision.batch_kind == "none"


def test_long_log_override_only_for_log_task_types(config: RouterConfig) -> None:
    """(1) log_kind=long on single_file_fix must NOT force 12B; keeps Fable."""
    decision = _route(
        {
            "task_type": "single_file_fix",
            "log_kind": "long",
            "token_estimate": 3000,
        },
        config,
    )
    assert decision.lane == "inkling_2_mini"
    assert decision.fable_review_required is True
    assert decision.plan_steps[-1] == FABLE_STEP


def test_long_log_forces_12b_for_log_summary(config: RouterConfig) -> None:
    decision = _route(
        {
            "task_type": "log_summary",
            "log_kind": "long",
            "token_estimate": 10960,
            "tokens_sent": 10960,
            "tokens_processed": 10960,
            "source_text": "lines 10960",
            "summary_text": "lines 10960",
        },
        config,
    )
    assert decision.lane == "gemma4_12b"
    assert "aider" not in " ".join(decision.plan_steps)


def test_coding_derived_from_task_type() -> None:
    for task in LOG_TASK_TYPES:
        assert is_coding_task(task) is False
    assert is_coding_task("single_file_fix") is True
    assert is_coding_task("diff_pre_review") is True
    assert is_coding_task("briefs_and_prompts") is True


def test_escalation_chain_order(config: RouterConfig) -> None:
    assert next_escalation(None, config) == "azure_codex_mini"
    assert next_escalation("azure_codex_mini", config) == "gpt_5_3_codex"
    assert next_escalation("gpt_5_3_codex", config) == "cursor_cloud_agent"
    assert next_escalation("cursor_cloud_agent", config) is None


@pytest.mark.parametrize(
    "task_type,expected",
    [
        ("ci_log_summary", "gemma4_12b"),
        ("unit_tests", "inkling_2_mini"),
        ("lint_doc_fix", "gemma4_26b"),
    ],
)
def test_lane_table_parametrized(
    config: RouterConfig, task_type: str, expected: str
) -> None:
    kwargs: dict = {"task_type": task_type, "token_estimate": 3000}
    if task_type in LOG_TASK_TYPES:
        kwargs.update(
            {
                "tokens_sent": 3000,
                "tokens_processed": 3000,
                "source_text": "x 3000",
                "summary_text": "x 3000",
            }
        )
    decision = _route(kwargs, config)
    assert decision.lane == expected
