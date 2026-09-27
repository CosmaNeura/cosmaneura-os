from __future__ import annotations

import pytest

from cosmas_os.config import Settings


def _beta_settings(**overrides) -> Settings:
    values = {
        "cosmas_env": "early_adopter_beta",
        "data_mode": "synthetic",
        "auth_mode": "clerk_jwt",
        "cors_allowed_origins": "https://beta.example.invalid",
        "synth_seed": False,
        "blob_backend": "azure",
        "azure_storage_account_url": "https://storage.example.invalid",
        "azure_blob_container": "box-data",
        "clerk_issuer": "https://clerk.example.invalid",
        "clerk_jwks_url": "https://clerk.example.invalid/.well-known/jwks.json",
        "clerk_audience": "cosmas-beta-api",
        "clerk_organization_id": "org_test_beta",
        "clerk_authorized_parties": "https://beta.example.invalid",
        "beta_box_id": "00000000-0000-4000-8000-000000000001",
        "clinic_approval_ref": "approval:test-clinic",
        "baa_evidence_ref": "baa:test-evidence",
        "human_deploy_evidence_ref": "deploy:test-review",
        "database_url": (
            "postgresql+psycopg://test:test@pg.example.invalid/cosmas_os?"
            "sslmode=verify-full&sslrootcert=system"
        ),
        "redis_url": "rediss://:invented-secret@redis.example.invalid:6380/0?ssl_cert_reqs=required",
        "sync_worker": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_valid_beta_runtime_configuration() -> None:
    configured = _beta_settings()
    assert configured.runtime_configuration_errors() == []
    configured.validate_runtime_configuration()


def test_shared_session_policy_is_explicit_and_limited_to_synthetic_development_identity():
    values = dict(clerk_session_policy="shared_staging", clerk_audience="",
                  clerk_issuer="https://invented.clerk.accounts.dev",
                  clerk_jwks_url="https://invented.clerk.accounts.dev/.well-known/jwks.json",
                  workspace_enabled=True, workspace_authenticated_enabled=True, workspace_hosted_enabled=True)
    configured = _beta_settings(**values)
    assert configured.runtime_configuration_errors() == []
    assert configured.workspace_available
    for changed in [dict(clerk_audience=None), dict(clerk_audience="another-api"),
                    dict(data_mode="authorized_beta"), dict(cosmas_env="synth_os"),
                    dict(auth_mode="synth_headers"), dict(clerk_issuer="https://production.example.invalid")]:
        invalid = _beta_settings(**(values | changed))
        assert invalid.clerk_session_configuration_errors()
        assert invalid.runtime_configuration_errors()
        assert not invalid.workspace_available


def test_beta_configuration_fails_closed_without_real_prerequisites() -> None:
    configured = Settings(
        cosmas_env="early_adopter_beta",
        cors_allowed_origins="*",
    )
    errors = configured.runtime_configuration_errors()
    assert "AUTH_MODE must be clerk_jwt" in errors
    assert "BLOB_BACKEND must be azure" in errors
    assert "CLERK_ORGANIZATION_ID is required" in errors
    assert "CLERK_AUDIENCE is required" in errors
    assert not any("CLINIC_APPROVAL_REF" in error for error in errors)
    assert not any("BAA_EVIDENCE_REF" in error for error in errors)
    assert "HUMAN_DEPLOY_EVIDENCE_REF is required" in errors
    assert "CORS_ALLOWED_ORIGINS must not contain a wildcard" in errors


def test_beta_rejects_non_tls_and_misaligned_authorized_party() -> None:
    configured = _beta_settings(
        cors_allowed_origins="https://beta.example.invalid",
        clerk_authorized_parties="https://other.example.invalid",
        azure_storage_account_url="http://storage.example.invalid",
        redis_url="redis://redis.example.invalid:6379/0",
    )
    errors = configured.runtime_configuration_errors()
    assert "CLERK_AUTHORIZED_PARTIES must be a subset of CORS_ALLOWED_ORIGINS" in errors
    assert "AZURE_STORAGE_ACCOUNT_URL must use https" in errors
    assert "REDIS_URL must use a non-local rediss endpoint" in errors
    assert "REDIS_URL must require certificate verification" in errors
    assert "DATABASE_URL must use a non-local PostgreSQL psycopg endpoint" not in errors


def test_beta_rejects_tls_without_server_identity_verification() -> None:
    configured = _beta_settings(
        database_url=(
            "postgresql+psycopg://test:test@pg.example.invalid/cosmas_os?sslmode=require"
        )
    )
    assert "DATABASE_URL must use sslmode=verify-full" in configured.runtime_configuration_errors()


def test_beta_rejects_verify_full_without_an_explicit_system_trust_store() -> None:
    configured = _beta_settings(
        database_url=(
            "postgresql+psycopg://test:test@pg.example.invalid/cosmas_os?"
            "sslmode=verify-full"
        )
    )
    assert "DATABASE_URL must use sslrootcert=system" in (
        configured.runtime_configuration_errors()
    )


def test_beta_rejects_duplicate_postgres_tls_parameters() -> None:
    configured = _beta_settings(
        database_url=(
            "postgresql+psycopg://test:test@pg.example.invalid/cosmas_os?"
            "sslmode=require&sslmode=verify-full&sslrootcert=system"
        )
    )
    assert "DATABASE_URL must use sslmode=verify-full" in (
        configured.runtime_configuration_errors()
    )


def test_beta_rejects_unreviewed_postgres_query_parameters() -> None:
    configured = _beta_settings(
        database_url=(
            "postgresql+psycopg://test:test@pg.example.invalid/cosmas_os?"
            "sslmode=verify-full&sslrootcert=system&application_name=unreviewed"
        )
    )
    assert "DATABASE_URL must contain only the required TLS parameters" in (
        configured.runtime_configuration_errors()
    )


def test_beta_rejects_wrong_postgres_database() -> None:
    configured = _beta_settings(
        database_url=(
            "postgresql+psycopg://test:test@pg.example.invalid/postgres?"
            "sslmode=verify-full&sslrootcert=system"
        )
    )
    assert "DATABASE_URL must use the dedicated authenticated cosmas_os database" in (
        configured.runtime_configuration_errors()
    )


def test_beta_rejects_postgres_without_a_password() -> None:
    configured = _beta_settings(
        database_url=(
            "postgresql+psycopg://test@pg.example.invalid/cosmas_os?"
            "sslmode=verify-full&sslrootcert=system"
        )
    )
    assert "DATABASE_URL must use the dedicated authenticated cosmas_os database" in (
        configured.runtime_configuration_errors()
    )


@pytest.mark.parametrize(
    "redis_url",
    [
        "rediss://redis.example.invalid:6380/0?ssl_cert_reqs=required",
        "rediss://:@redis.example.invalid:6380/0?ssl_cert_reqs=required",
        "rediss://:invented-secret@redis.example.invalid:6380/1?ssl_cert_reqs=required",
        "rediss://:invented-secret@redis.example.invalid:6380/0?ssl_cert_reqs=required&decode_responses=true",
        "rediss://:invented-secret@redis.example.invalid:6380/0?ssl_cert_reqs=none&ssl_cert_reqs=required",
    ],
)
def test_beta_rejects_ambiguous_redis_endpoint(redis_url: str) -> None:
    errors = _beta_settings(redis_url=redis_url).runtime_configuration_errors()
    assert any(error.startswith("REDIS_URL must") for error in errors)


def test_synth_configuration_has_exact_local_origins() -> None:
    configured = Settings()
    assert "*" not in configured.allowed_origins
    assert configured.runtime_configuration_errors() == []


def test_synthetic_beta_lab_does_not_claim_clinic_or_baa_authority() -> None:
    configured = _beta_settings(clinic_approval_ref=None, baa_evidence_ref=None)
    assert configured.runtime_configuration_errors() == []


def test_authorized_beta_data_requires_clinic_baa_and_phi_authorization() -> None:
    configured = _beta_settings(
        data_mode="authorized_beta",
        clinic_approval_ref=None,
        baa_evidence_ref=None,
        phi_authorization_ref=None,
    )
    errors = configured.runtime_configuration_errors()
    assert "authorized_beta data requires CLINIC_APPROVAL_REF" in errors
    assert "authorized_beta data requires BAA_EVIDENCE_REF" in errors
    assert "authorized_beta data requires PHI_AUTHORIZATION_REF" in errors
