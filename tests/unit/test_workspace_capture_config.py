from typing import Any
from uuid import uuid4

import pytest

from cosmas_os.config import Settings


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"workspace_capture_backend": "disabled"},
        {"workspace_enabled": False},
        {"workspace_authenticated_enabled": False},
        {"auth_mode": "synth_headers"},
        {"synth_seed": True},
        {"cosmas_env": "early_adopter_beta"},
        {"workspace_native_synthetic_enabled": True},
        {"core_capture_origin": "http://core.example.invalid"},
        {"core_capture_origin": "https://core.example.invalid/path"},
        {"core_capture_origin": "https://user@core.example.invalid"},
        {"core_capture_origin": "https://core.example.invalid?override=true"},
        {"core_capture_origin": "https://core.example.invalid:8443"},
        {"core_capture_origin": "https://core.example.invalid:bad"},
        {"core_capture_scope": "https://core.example.invalid/.default"},
        {"core_capture_scope": "api://synthetic-core"},
        {"core_capture_managed_identity_client_id": ""},
        {"core_capture_managed_identity_client_id": "not-a-uuid"},
    ],
)
def test_capture_requires_explicit_authenticated_local_profile_and_workload_identity(change):
    settings = Settings(
        **{
            "_env_file": None,
            "workspace_enabled": True,
            "workspace_authenticated_enabled": True,
            "auth_mode": "clerk_jwt",
            "synth_seed": False,
            "database_url": "postgresql+psycopg://w1a_synth@127.0.0.1:55439/w1a_test",
            "clerk_issuer": "https://issuer.invalid",
            "clerk_jwks_url": "https://issuer.invalid/.well-known/jwks.json",
            "clerk_organization_id": "org_invented",
            "clerk_audience": "workspace-local",
            "clerk_authorized_parties": "http://localhost:5173",
            "beta_box_id": str(uuid4()),
            "workspace_capture_backend": "core",
            "core_capture_origin": "https://core.example.invalid",
            "core_capture_scope": "api://synthetic-core/.default",
            "core_capture_managed_identity_client_id": str(uuid4()),
            **change,
        },
    )
    assert settings.workspace_capture_available is (not change)
    capture_errors = [
        value for value in settings.runtime_configuration_errors() if "capture" in value.lower()
    ]
    assert bool(capture_errors) is bool(change and change != {"workspace_capture_backend": "disabled"})


def test_capture_is_disabled_by_default():
    # BaseSettings accepts this runtime option outside the generated field signature.
    options: dict[str, Any] = {"_env_file": None}
    assert not Settings(**options).workspace_capture_available
