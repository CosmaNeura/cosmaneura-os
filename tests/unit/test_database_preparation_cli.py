from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cosmas_os.application.database_preparation import (
    DatabasePreparationError,
    _scram_sha_256_verifier,
    _validate_boundaries,
)
from cosmas_os.cli import app


def test_database_preparation_cli_never_reflects_credentials() -> None:
    secret_marker = "do-not-print-this-database-secret"
    result = CliRunner().invoke(
        app,
        ["prepare-beta-database", "--confirm-forward-only"],
        env={
            "COSMAS_ENV": "early_adopter_beta",
            "DATABASE_ADMIN_URL": secret_marker,
            "DATABASE_URL": (
                "postgresql+psycopg://cosmas_runtime:also-secret@example.invalid/"
                "cosmas_os?sslmode=verify-full&sslrootcert=system"
            ),
        },
    )

    assert result.exit_code == 1
    assert (result.stdout + result.stderr).strip() == (
        '{"contract":"cosmas-os-d3-database-preparation-v1","status":"failed"}'
    )
    assert secret_marker not in result.output
    assert "also-secret" not in result.output


def test_database_preparation_rejects_shared_admin_and_runtime_password() -> None:
    shared_secret = "invented-shared-password-1234"

    with pytest.raises(
        DatabasePreparationError,
        match="runtime credential must differ from the administrator",
    ):
        _validate_boundaries(
            (
                "postgresql+psycopg://cosmas_beta_admin:"
                f"{shared_secret}@database.example.invalid/cosmas_os?"
                "sslmode=verify-full&sslrootcert=system"
            ),
            (
                "postgresql+psycopg://cosmas_runtime:"
                f"{shared_secret}@database.example.invalid/cosmas_os?"
                "sslmode=verify-full&sslrootcert=system"
            ),
            require_verify_full=True,
        )


@pytest.mark.parametrize("runtime_password", ["x", "x" * 23])
def test_database_preparation_rejects_short_runtime_password(runtime_password: str) -> None:
    with pytest.raises(
        DatabasePreparationError,
        match="runtime credential must contain at least 24 printable ASCII characters",
    ):
        _validate_boundaries(
            "postgresql+psycopg://cosmas_beta_admin:invented-admin-password-1234@database.example.invalid/cosmas_os?sslmode=verify-full&sslrootcert=system",
            (
                "postgresql+psycopg://cosmas_runtime:"
                f"{runtime_password}@database.example.invalid/cosmas_os?"
                "sslmode=verify-full&sslrootcert=system"
            ),
            require_verify_full=True,
        )


def test_database_preparation_accepts_24_character_decoded_runtime_password() -> None:
    _, runtime = _validate_boundaries(
        "postgresql+psycopg://cosmas_beta_admin:invented-admin-password-1234@database.example.invalid/cosmas_os?sslmode=verify-full&sslrootcert=system",
        "postgresql+psycopg://cosmas_runtime:12345678901234567890123%21@database.example.invalid/cosmas_os?sslmode=verify-full&sslrootcert=system",
        require_verify_full=True,
    )

    assert runtime.password == "12345678901234567890123!"


def test_database_preparation_rejects_percent_encoded_unicode_runtime_password() -> None:
    with pytest.raises(
        DatabasePreparationError,
        match="runtime credential must contain at least 24 printable ASCII characters",
    ):
        _validate_boundaries(
            "postgresql+psycopg://cosmas_beta_admin:invented-admin-password-1234@database.example.invalid/cosmas_os?sslmode=verify-full&sslrootcert=system",
            "postgresql+psycopg://cosmas_runtime:12345678901234567890123%C3%A9@database.example.invalid/cosmas_os?sslmode=verify-full&sslrootcert=system",
            require_verify_full=True,
        )


@pytest.mark.parametrize(
    "query",
    [
        "sslmode=verify-full",
        "sslmode=verify-full&sslrootcert=/tmp/unreviewed-root.crt",
        "sslmode=verify-full&sslrootcert=system&application_name=unreviewed",
    ],
)
def test_database_preparation_requires_the_system_trust_store(query: str) -> None:
    with pytest.raises(DatabasePreparationError, match="system trust store"):
        _validate_boundaries(
            "postgresql+psycopg://cosmas_beta_admin:invented-admin-password-1234@"
            f"database.example.invalid/cosmas_os?{query}",
            "postgresql+psycopg://cosmas_runtime:invented-runtime-password-1234@"
            f"database.example.invalid/cosmas_os?{query}",
            require_verify_full=True,
        )


def test_runtime_password_is_converted_to_deterministic_scram_verifier() -> None:
    plaintext = "invented-runtime-password-1234"
    verifier = _scram_sha_256_verifier(plaintext, salt=b"0123456789abcdef")

    assert verifier.startswith("SCRAM-SHA-256$4096:MDEyMzQ1Njc4OWFiY2RlZg==$")
    assert plaintext not in verifier
    assert verifier == _scram_sha_256_verifier(plaintext, salt=b"0123456789abcdef")
