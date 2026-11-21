"""Router lane assignment and escalation (mutation-killing)."""

from __future__ import annotations

import pytest

from local_model_router.config import RouterConfig
from local_model_router.models import Job
from local_model_router.router import next_escalation, route_job


def _job(**kwargs) -> Job:
    base = {
        "job_id": "j",
        "task_type": "unit_tests",
        "file_count": 1,
        "token_estimate": 2000,
        "free_memory_percent": 40.0,
        "gemma_12b_loaded": False,
    }
    base.update(kwargs)
    return Job.from_dict(base)


def test_ci_log_routes_to_12b(config: RouterConfig) -> None:
    decision = route_job(_job(task_type="ci_log_summary", log_kind="ci"), config)
    assert decision.lane == "gemma4_12b"
    assert decision.aborted is False


def test_build_and_test_logs_route_to_12b(config: RouterConfig) -> None:
    for task, kind in (
        ("build_log_summary", "build"),
        ("test_log_summary", "test"),
    ):
        decision = route_job(_job(task_type=task, log_kind=kind), config)
        assert decision.lane == "gemma4_12b", task


def test_diff_pre_review_routes_to_12b(config: RouterConfig) -> None:
    decision = route_job(_job(task_type="diff_pre_review"), config)
    assert decision.lane == "gemma4_12b"


def test_unit_tests_and_single_file_route_to_inkling(config: RouterConfig) -> None:
    for task in ("unit_tests", "single_file_fix", "strict_structured_output"):
        decision = route_job(_job(task_type=task, token_estimate=3500), config)
        assert decision.lane == "inkling_2_mini", task
        assert decision.size == "T3"


def test_lint_doc_routes_to_26b(config: RouterConfig) -> None:
    decision = route_job(
        _job(task_type="lint_doc_batch", file_count=2, token_estimate=6000),
        config,
    )
    assert decision.lane == "gemma4_26b"
    assert decision.size == "T3"


def test_oversize_inkling_escalates_to_azure_codex_mini(config: RouterConfig) -> None:
    decision = route_job(
        _job(task_type="single_file_fix", file_count=1, token_estimate=20000),
        config,
    )
    assert decision.escalate is True
    assert decision.lane == "azure_codex_mini"
    assert decision.fable_review_required is True


def test_multi_file_feature_escalates_to_cloud_agent(config: RouterConfig) -> None:
    decision = route_job(
        _job(task_type="single_file_fix", multi_file_feature=True, file_count=4),
        config,
    )
    assert decision.lane == "cursor_cloud_agent"
    assert decision.escalate is True


def test_security_sensitive_escalates_to_cloud_agent(config: RouterConfig) -> None:
    decision = route_job(_job(security_sensitive=True), config)
    assert decision.lane == "cursor_cloud_agent"


def test_escalation_chain_order(config: RouterConfig) -> None:
    assert config.escalation_chain == (
        "azure_codex_mini",
        "gpt_5_3_codex",
        "cursor_cloud_agent",
    )
    assert next_escalation(None, config) == "azure_codex_mini"
    assert next_escalation("azure_codex_mini", config) == "gpt_5_3_codex"
    assert next_escalation("gpt_5_3_codex", config) == "cursor_cloud_agent"
    assert next_escalation("cursor_cloud_agent", config) is None


def test_long_log_forces_12b_even_for_large_tokens(config: RouterConfig) -> None:
    decision = route_job(
        _job(
            task_type="log_summary",
            log_kind="long",
            token_estimate=10960,
            tokens_sent=10960,
            tokens_processed=10960,
        ),
        config,
    )
    # Truncation not failing here; lane must still be 12b.
    assert decision.lane == "gemma4_12b"
    assert "12B" in decision.reason or "12b" in decision.reason.lower()


def test_unknown_task_escalates(config: RouterConfig) -> None:
    decision = route_job(_job(task_type="briefs_and_prompts"), config)
    assert decision.escalate is True
    assert decision.lane == "azure_codex_mini"


def test_single_file_fix_with_two_files_escalates(config: RouterConfig) -> None:
    decision = route_job(
        _job(task_type="single_file_fix", file_count=2, token_estimate=3000),
        config,
    )
    assert decision.lane == "azure_codex_mini"
    assert decision.escalate is True


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
    decision = route_job(_job(task_type=task_type, token_estimate=3000), config)
    assert decision.lane == expected
