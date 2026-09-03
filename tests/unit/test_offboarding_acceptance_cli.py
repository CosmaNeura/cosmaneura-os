from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cosmas_os.application import offboarding_acceptance
from cosmas_os.cli import app

_KEY = "d4" * 32


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
    }


def _private_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "offboarding-state.json"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_offboarding_baseline_cli_reads_private_request_and_hides_failures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    secret = "user_private_target"
    path = _private_file(tmp_path, json.dumps({"target": secret}))
    session = StubSession()
    seen: list[str] = []
    monkeypatch.setattr("cosmas_os.cli._session", lambda: session)
    monkeypatch.setattr(
        offboarding_acceptance,
        "baseline_beta_offboarding_acceptance",
        lambda _session, _settings, request, _key: seen.append(request)
        or StubResult('{"contract":"cosmas-os-d3-offboarding-acceptance-v1","status":"ready_for_owner"}'),
    )

    result = CliRunner().invoke(
        app,
        [
            "baseline-beta-offboarding-acceptance",
            str(path),
            "--confirm-synthetic-only",
            "--confirm-reviewed-target",
        ],
        env=_environment(),
    )

    assert result.exit_code == 0
    assert seen == [json.dumps({"target": secret})]
    assert secret not in result.output
    assert session.closed


def test_offboarding_verify_cli_uses_bounded_environment_state(monkeypatch) -> None:
    private_state = '{"prior_state":{"opaque":"target"}}'
    session = StubSession()
    seen: list[str] = []
    monkeypatch.setattr("cosmas_os.cli._session", lambda: session)
    monkeypatch.setattr(
        offboarding_acceptance,
        "verify_beta_offboarding_acceptance",
        lambda _session, _settings, state, _key: seen.append(state)
        or StubResult('{"contract":"cosmas-os-d3-offboarding-acceptance-v1","status":"verified"}'),
    )

    result = CliRunner().invoke(
        app,
        [
            "verify-beta-offboarding-acceptance",
            "--confirm-synthetic-only",
            "--confirm-browser-complete",
        ],
        env={**_environment(), "COSMAS_ACCEPTANCE_STATE": private_state},
    )

    assert result.exit_code == 0
    assert seen == [private_state]
    assert "opaque" not in result.output
    assert session.closed


def test_offboarding_cli_failure_is_generic(monkeypatch, tmp_path: Path) -> None:
    secret = "user_secret_failure"
    path = _private_file(tmp_path, json.dumps({"target": secret}))
    monkeypatch.setattr("cosmas_os.cli._session", StubSession)
    monkeypatch.setattr(
        offboarding_acceptance,
        "baseline_beta_offboarding_acceptance",
        lambda *_args: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    result = CliRunner().invoke(
        app,
        [
            "baseline-beta-offboarding-acceptance",
            str(path),
            "--confirm-synthetic-only",
            "--confirm-reviewed-target",
        ],
        env=_environment(),
    )

    assert result.exit_code == 1
    assert result.output.strip() == json.dumps(
        {
            "contract": "cosmas-os-d3-offboarding-acceptance-v1",
            "status": "failed",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    assert secret not in result.output
