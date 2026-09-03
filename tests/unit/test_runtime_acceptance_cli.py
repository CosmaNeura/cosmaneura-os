from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from cosmas_os.application import runtime_acceptance
from cosmas_os.application.runtime_acceptance import (
    RUNTIME_ACCEPTANCE_CONTRACT,
    RuntimeAcceptanceEvidence,
)
from cosmas_os.cli import app


def successful_evidence() -> RuntimeAcceptanceEvidence:
    return RuntimeAcceptanceEvidence(
        contract=RUNTIME_ACCEPTANCE_CONTRACT,
        status="ready",
        completed_at=datetime(2026, 9, 3, 16, 0, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        environment="early_adopter_beta",
        data_mode="synthetic",
        blob_backend="azure",
        sync_worker_disabled=True,
        user_assigned_managed_identity=True,
        blob_write_read_sha_match=True,
        blob_current_representation_absent_after_delete=True,
        blob_version_representations_absent_after_delete=True,
        blob_snapshot_representations_absent_after_delete=True,
        blob_deleted_representations_absent_after_delete=True,
        blob_recoverable_absence_verified=True,
        redis_round_trip=True,
        redis_cleanup_confirmed=True,
        database_schema_revision="0002_external_identities",
        database_schema_at_expected_head=True,
        database_insert_read_rolled_back=True,
    )


def test_runtime_acceptance_cli_emits_exactly_one_sanitized_attestation(monkeypatch) -> None:
    evidence = successful_evidence()
    monkeypatch.setattr(runtime_acceptance, "verify_beta_runtime", lambda _settings: evidence)

    result = CliRunner().invoke(
        app,
        ["verify-beta-runtime", "--confirm-synthetic-only", "--confirm-runtime-uami"],
    )

    assert result.exit_code == 0
    assert result.output.strip() == evidence.sanitized_json()
    assert result.output.count("\n") == 1


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--confirm-synthetic-only"],
        ["--confirm-runtime-uami"],
    ],
)
def test_runtime_acceptance_cli_requires_both_confirmations(monkeypatch, arguments) -> None:
    called = False

    def unexpected_call(_settings):
        nonlocal called
        called = True
        return successful_evidence()

    monkeypatch.setattr(runtime_acceptance, "verify_beta_runtime", unexpected_call)
    result = CliRunner().invoke(app, ["verify-beta-runtime", *arguments])

    assert result.exit_code == 1
    assert result.output.strip() == (
        '{"contract":"cosmas-os-d3-runtime-acceptance-v2","status":"failed"}'
    )
    assert called is False


def test_runtime_acceptance_cli_hides_all_dependency_details(monkeypatch) -> None:
    secret = "postgresql://user:do-not-print@example.invalid/cosmas_os"

    def fail(_settings):
        raise RuntimeError(secret)

    monkeypatch.setattr(runtime_acceptance, "verify_beta_runtime", fail)
    result = CliRunner().invoke(
        app,
        ["verify-beta-runtime", "--confirm-synthetic-only", "--confirm-runtime-uami"],
    )

    assert result.exit_code == 1
    assert result.output.strip() == json.dumps(
        {"contract": RUNTIME_ACCEPTANCE_CONTRACT, "status": "failed"},
        sort_keys=True,
        separators=(",", ":"),
    )
    assert secret not in result.output
