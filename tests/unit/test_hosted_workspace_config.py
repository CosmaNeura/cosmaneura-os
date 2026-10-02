from __future__ import annotations

import pytest

from cosmas_os.config import Settings


def hosted(**changes):
    values = dict(cosmas_env="early_adopter_beta", data_mode="synthetic", auth_mode="clerk_jwt",
        workspace_enabled=True, workspace_authenticated_enabled=True, workspace_hosted_enabled=True,
        synth_seed=False, sync_worker=False, blob_backend="azure",
        azure_storage_account_url="https://storage.example.invalid", azure_blob_container="workspace",
        clerk_issuer="https://identity.example.invalid", clerk_jwks_url="https://identity.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas", clerk_organization_id="org_invented", beta_box_id="00000000-0000-4000-8000-000000000001",
        cors_allowed_origins="https://workspace.example.invalid", clerk_authorized_parties="https://workspace.example.invalid",
        human_deploy_evidence_ref="invented:offline-test-only",
        database_url="postgresql+psycopg://invented:invented@db.example.invalid/cosmas_os?sslmode=verify-full&sslrootcert=system",
        redis_url="rediss://:invented@redis.example.invalid/0?ssl_cert_reqs=required")
    values.update(changes)
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue] -- BaseSettings accepts _env_file at runtime.


def test_hosted_workspace_and_existing_feature_gates():
    config = hosted(workspace_scheduling_enabled=True)
    config.validate_runtime_configuration()
    assert config.workspace_available and config.workspace_scheduling_available
    assert not config.vendor_io_enabled and not config.finance_io_enabled
    assert not config.workspace_capture_available and not config.workspace_llm_available


def test_patient_setup_requires_sign_in_and_proposals_with_its_own_default_closed_gate():
    config = hosted(workspace_scheduling_enabled=True, workspace_appointments_enabled=True,
        workspace_scheduling_login_enabled=True)
    assert not config.workspace_scheduling_patient_setup_available
    config.workspace_scheduling_patient_setup_enabled = True
    config.validate_runtime_configuration()
    assert config.workspace_scheduling_patient_setup_available
    for gate in ("workspace_scheduling_enabled", "workspace_appointments_enabled", "workspace_scheduling_login_enabled"):
        changed = config.model_copy(update={gate: False})
        assert not changed.workspace_scheduling_patient_setup_available
        with pytest.raises(RuntimeError, match="Scheduling patient setup"):
            changed.validate_runtime_configuration()


@pytest.mark.parametrize("changes", [
    {"workspace_hosted_enabled": False}, {"auth_mode": "synth_headers"}, {"synth_seed": True},
    {"workspace_authenticated_enabled": False}, {"human_deploy_evidence_ref": None},
    {"blob_backend": "local"}, {"cosmas_env": "synth_os"}, {"sync_worker": True},
    {"workspace_desktop_local_transport_enabled": True}, {"workspace_apple_local_transport_enabled": True},
    {"cors_allowed_origins": "http://localhost:5173"}, {"cors_allowed_origins": "https://workspace.example.invalid:444"},
    {"cors_allowed_origins": "https://workspace.example.invalid/"},
    {"clerk_jwks_url": "https://other.example.invalid/.well-known/jwks.json"},
    {"database_url": "postgresql+psycopg://u:p@db.example.invalid/cosmas_os?sslmode=require"},
    {"redis_url": "rediss://:invented@redis.example.invalid/0?ssl_cert_reqs=none"},
    {"data_mode": "authorized_beta"},
])
def test_partial_or_weaker_profiles_cannot_open_the_workspace(changes):
    config = hosted(**changes)
    assert not config.workspace_available
    with pytest.raises(RuntimeError):
        config.validate_runtime_configuration()


def test_native_origins_require_the_independent_hosted_flags_and_exact_parties():
    origins = "https://workspace.example.invalid,app://cosmas,capacitor://localhost"
    config = hosted(cors_allowed_origins=origins, clerk_authorized_parties=origins,
                    workspace_desktop_hosted_transport_enabled=True, workspace_apple_hosted_transport_enabled=True)
    config.validate_runtime_configuration()
    assert config.workspace_available
    config.workspace_apple_hosted_transport_enabled = False
    assert not config.workspace_available
    config.workspace_apple_hosted_transport_enabled = True
    config.clerk_authorized_parties = "https://workspace.example.invalid,app://cosmas"
    assert not config.workspace_available


def test_authorized_data_still_requires_all_existing_evidence():
    config = hosted(data_mode="authorized_beta", clinic_approval_ref="invented:clinic",
                    baa_evidence_ref="invented:baa", phi_authorization_ref="invented:phi")
    config.validate_runtime_configuration()
    assert config.workspace_available
    config.phi_authorization_ref = None
    assert not config.workspace_available
