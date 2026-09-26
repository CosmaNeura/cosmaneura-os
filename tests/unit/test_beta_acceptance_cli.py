from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cosmas_os.application import beta_acceptance
from cosmas_os.application.beta_acceptance import (
    AUDIT_REPLAY_CONTRACT,
    PURGE_ACCEPTANCE_CONTRACT,
    WORKFLOW_ACCEPTANCE_CONTRACT,
)
from cosmas_os.cli import app

_KEY = "a1" * 32
_UAMI = "11111111-1111-4111-8111-111111111111"


class StubSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class StubResult:
    def __init__(self, serialized: str) -> None:
        self._serialized = serialized

    def sanitized_json(self) -> str:
        return self._serialized


def _environment() -> dict[str, str]:
    return {
        "COSMAS_ENV": "early_adopter_beta",
        "DATA_MODE": "synthetic",
        "COSMAS_ACCEPTANCE_HMAC_KEY": _KEY,
        "AZURE_CLIENT_ID": _UAMI,
        "EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID": _UAMI,
    }


def _protected_state(tmp_path: Path, content: str = '{"opaque":"state"}') -> Path:
    state_path = tmp_path / "acceptance-state.json"
    state_path.write_text(content, encoding="utf-8")
    state_path.chmod(0o600)
    return state_path


def test_workflow_baseline_cli_emits_one_sanitized_state(monkeypatch) -> None:
    serialized = '{"contract":"cosmas-os-d3-workflow-acceptance-v1","status":"ready_for_browser"}'
    session = StubSession()
    monkeypatch.setattr("cosmas_os.cli._session", lambda: session)
    monkeypatch.setattr(
        beta_acceptance,
        "baseline_beta_workflow_acceptance",
        lambda _session, _settings, _key: StubResult(serialized),
    )

    result = CliRunner().invoke(
        app,
        [
            "baseline-beta-workflow-acceptance",
            "--confirm-synthetic-only",
            "--confirm-async-worker",
        ],
        env=_environment(),
    )

    assert result.exit_code == 0
    assert result.output.strip() == serialized
    assert result.output.count("\n") == 1
    assert session.closed is True
    assert _KEY not in result.output


def test_workflow_verify_cli_reads_only_protected_state(monkeypatch, tmp_path) -> None:
    state_path = _protected_state(tmp_path)
    serialized = '{"contract":"cosmas-os-d3-workflow-acceptance-v1","status":"verified"}'
    seen: list[str] = []
    monkeypatch.setattr("cosmas_os.cli._session", StubSession)
    monkeypatch.setattr(
        beta_acceptance,
        "verify_beta_workflow_acceptance",
        lambda _session, _settings, state, _key: seen.append(state) or StubResult(serialized),
    )

    result = CliRunner().invoke(
        app,
        [
            "verify-beta-workflow-acceptance",
            str(state_path),
            "--confirm-synthetic-only",
            "--confirm-browser-complete",
        ],
        env=_environment(),
    )

    assert result.exit_code == 0
    assert result.output.strip() == serialized
    assert seen == ['{"opaque":"state"}']


def test_workflow_verify_cli_accepts_bounded_job_environment_state(monkeypatch) -> None:
    opaque_state = '{"opaque":"job-state"}'
    serialized = '{"contract":"cosmas-os-d3-workflow-acceptance-v1","status":"verified"}'
    seen: list[str] = []
    monkeypatch.setattr("cosmas_os.cli._session", StubSession)
    monkeypatch.setattr(
        beta_acceptance,
        "verify_beta_workflow_acceptance",
        lambda _session, _settings, state, _key: seen.append(state) or StubResult(serialized),
    )

    result = CliRunner().invoke(
        app,
        [
            "verify-beta-workflow-acceptance",
            "--confirm-synthetic-only",
            "--confirm-browser-complete",
        ],
        env={**_environment(), "COSMAS_ACCEPTANCE_STATE": opaque_state},
    )

    assert result.exit_code == 0
    assert result.output.strip() == serialized
    assert seen == [opaque_state]


def test_purge_prepare_cli_passes_exact_identity_binding(monkeypatch) -> None:
    serialized = (
        '{"contract":"cosmas-os-d3-physical-purge-acceptance-v1","status":"ready_for_browser"}'
    )
    seen: list[tuple[str | None, str | None]] = []
    monkeypatch.setattr("cosmas_os.cli._session", StubSession)

    def prepare(_session, _settings, _key, **kwargs):
        seen.append(
            (
                kwargs["managed_identity_client_id"],
                kwargs["expected_managed_identity_client_id"],
            )
        )
        return StubResult(serialized)

    monkeypatch.setattr(beta_acceptance, "prepare_beta_purge_acceptance", prepare)
    result = CliRunner().invoke(
        app,
        [
            "prepare-beta-purge-acceptance",
            "--confirm-synthetic-only",
            "--confirm-runtime-uami",
        ],
        env=_environment(),
    )

    assert result.exit_code == 0
    assert result.output.strip() == serialized
    assert seen == [(_UAMI, _UAMI)]


def test_audit_replay_cli_emits_only_sanitized_evidence(monkeypatch) -> None:
    serialized = '{"contract":"cosmas-os-d3-audit-replay-acceptance-v1","status":"verified"}'
    session = StubSession()
    monkeypatch.setattr("cosmas_os.cli._session", lambda: session)
    monkeypatch.setattr(
        beta_acceptance,
        "verify_beta_audit_replay",
        lambda _session, _settings: StubResult(serialized),
    )

    result = CliRunner().invoke(
        app,
        [
            "verify-beta-audit-replay",
            "--confirm-synthetic-only",
            "--confirm-no-content-export",
        ],
        env=_environment(),
    )

    assert result.exit_code == 0
    assert result.output.strip() == serialized
    assert session.closed is True


@pytest.mark.parametrize(
    ("command", "contract"),
    [
        ("baseline-beta-workflow-acceptance", WORKFLOW_ACCEPTANCE_CONTRACT),
        ("verify-beta-audit-replay", AUDIT_REPLAY_CONTRACT),
        ("prepare-beta-purge-acceptance", PURGE_ACCEPTANCE_CONTRACT),
    ],
)
def test_acceptance_cli_fails_closed_without_confirmations(command: str, contract: str) -> None:
    result = CliRunner().invoke(app, [command], env=_environment())

    assert result.exit_code == 1
    assert result.output.strip() == json.dumps(
        {"contract": contract, "status": "failed"},
        sort_keys=True,
        separators=(",", ":"),
    )


def test_acceptance_cli_hides_state_and_exception_details(monkeypatch, tmp_path) -> None:
    secret = "invented-row-id-and-secret"
    state_path = _protected_state(tmp_path, secret)
    monkeypatch.setattr("cosmas_os.cli._session", StubSession)
    monkeypatch.setattr(
        beta_acceptance,
        "verify_beta_purge_acceptance",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    result = CliRunner().invoke(
        app,
        [
            "verify-beta-purge-acceptance",
            str(state_path),
            "--confirm-synthetic-only",
            "--confirm-runtime-uami",
            "--confirm-browser-complete",
        ],
        env=_environment(),
    )

    assert result.exit_code == 1
    assert result.output.strip() == json.dumps(
        {"contract": PURGE_ACCEPTANCE_CONTRACT, "status": "failed"},
        sort_keys=True,
        separators=(",", ":"),
    )
    assert secret not in result.output


def test_acceptance_cli_rejects_group_readable_state_before_database_access(
    monkeypatch,
    tmp_path,
) -> None:
    state_path = _protected_state(tmp_path)
    state_path.chmod(0o640)
    called = False

    def unexpected_session():
        nonlocal called
        called = True
        return StubSession()

    monkeypatch.setattr("cosmas_os.cli._session", unexpected_session)
    result = CliRunner().invoke(
        app,
        [
            "verify-beta-workflow-acceptance",
            str(state_path),
            "--confirm-synthetic-only",
            "--confirm-browser-complete",
        ],
        env=_environment(),
    )

    assert result.exit_code == 1
    assert called is False
    assert str(state_path) not in result.output


@pytest.mark.parametrize("environment_state", ['{"opaque":"duplicate"}', "x" * 16_385])
def test_acceptance_cli_rejects_ambiguous_or_oversized_state_before_database_access(
    monkeypatch,
    tmp_path,
    environment_state: str,
) -> None:
    state_path = _protected_state(tmp_path)
    called = False

    def unexpected_session():
        nonlocal called
        called = True
        return StubSession()

    monkeypatch.setattr("cosmas_os.cli._session", unexpected_session)
    arguments = [
        "verify-beta-workflow-acceptance",
        "--confirm-synthetic-only",
        "--confirm-browser-complete",
    ]
    if len(environment_state) < 16_385:
        arguments.insert(1, str(state_path))
    result = CliRunner().invoke(
        app,
        arguments,
        env={**_environment(), "COSMAS_ACCEPTANCE_STATE": environment_state},
    )

    assert result.exit_code == 1
    assert called is False
    assert result.output.strip() == json.dumps(
        {"contract": WORKFLOW_ACCEPTANCE_CONTRACT, "status": "failed"},
        sort_keys=True,
        separators=(",", ":"),
    )
