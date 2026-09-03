from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from cosmas_os.application import database_fingerprint
from cosmas_os.application.database_fingerprint import (
    DATABASE_FINGERPRINT_CONTRACT,
    DatabaseFingerprintEvidence,
)
from cosmas_os.cli import app


def successful_fingerprint() -> DatabaseFingerprintEvidence:
    structures = {"box_contexts": {"count": 1, "sha256": "a" * 64}}
    return DatabaseFingerprintEvidence(
        contract=DATABASE_FINGERPRINT_CONTRACT,
        status="ready",
        schema_revision="0002_external_identities",
        schema_at_expected_head=True,
        structures=structures,
        aggregate_sha256="b" * 64,
    )


def test_database_fingerprint_cli_emits_exactly_one_sanitized_result(monkeypatch) -> None:
    evidence = successful_fingerprint()
    seen: list[str] = []
    monkeypatch.setattr(
        database_fingerprint,
        "fingerprint_beta_database",
        lambda database_url, **_kwargs: seen.append(database_url) or evidence,
    )

    result = CliRunner().invoke(
        app,
        ["fingerprint-beta-database", "--confirm-synthetic-only", "--confirm-read-only"],
        env={
            "COSMAS_ENV": "early_adopter_beta",
            "DATA_MODE": "synthetic",
            "DATABASE_URL": "postgresql+psycopg://runtime:secret@database.example.invalid/cosmas_os",
        },
    )

    assert result.exit_code == 0
    assert result.output.strip() == evidence.sanitized_json()
    assert result.output.count("\n") == 1
    assert seen == [
        "postgresql+psycopg://runtime:secret@database.example.invalid/cosmas_os"
    ]
    assert "secret" not in result.output


@pytest.mark.parametrize(
    ("arguments", "environment"),
    [
        ([], {"COSMAS_ENV": "early_adopter_beta", "DATA_MODE": "synthetic"}),
        (["--confirm-synthetic-only"], {"COSMAS_ENV": "early_adopter_beta", "DATA_MODE": "synthetic"}),
        (["--confirm-read-only"], {"COSMAS_ENV": "early_adopter_beta", "DATA_MODE": "synthetic"}),
        (
            ["--confirm-synthetic-only", "--confirm-read-only"],
            {"COSMAS_ENV": "synth_os", "DATA_MODE": "synthetic"},
        ),
        (
            ["--confirm-synthetic-only", "--confirm-read-only"],
            {"COSMAS_ENV": "early_adopter_beta", "DATA_MODE": "authorized_beta"},
        ),
    ],
)
def test_database_fingerprint_cli_fails_closed_before_connect(
    monkeypatch, arguments, environment
) -> None:
    called = False

    def unexpected_call(_database_url, **_kwargs):
        nonlocal called
        called = True
        return successful_fingerprint()

    monkeypatch.setattr(database_fingerprint, "fingerprint_beta_database", unexpected_call)
    result = CliRunner().invoke(app, ["fingerprint-beta-database", *arguments], env=environment)

    assert result.exit_code == 1
    assert result.output.strip() == (
        '{"contract":"cosmas-os-d3-database-fingerprint-v1","status":"failed"}'
    )
    assert called is False


def test_database_fingerprint_cli_hides_connection_and_exception_details(monkeypatch) -> None:
    database_url = "postgresql+psycopg://runtime:do-not-print@database.example.invalid/cosmas_os"

    def fail(_database_url, **_kwargs):
        raise RuntimeError("invented row value and do-not-print")

    monkeypatch.setattr(database_fingerprint, "fingerprint_beta_database", fail)
    result = CliRunner().invoke(
        app,
        ["fingerprint-beta-database", "--confirm-synthetic-only", "--confirm-read-only"],
        env={
            "COSMAS_ENV": "early_adopter_beta",
            "DATA_MODE": "synthetic",
            "DATABASE_URL": database_url,
        },
    )

    assert result.exit_code == 1
    assert result.output.strip() == json.dumps(
        {"contract": DATABASE_FINGERPRINT_CONTRACT, "status": "failed"},
        sort_keys=True,
        separators=(",", ":"),
    )
    assert database_url not in result.output
    assert "do-not-print" not in result.output
