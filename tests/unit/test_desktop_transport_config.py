import pytest

from cosmas_os.config import Settings


def configured(**changes):
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue] -- BaseSettings runtime-only option.
        **{
        "workspace_enabled": True, "workspace_authenticated_enabled": True,
        "workspace_desktop_local_transport_enabled": True,
        "database_url": "postgresql+psycopg://invented@127.0.0.1:55439/w1a_desktop_test",
        "auth_mode": "clerk_jwt", "synth_seed": False,
        "cors_allowed_origins": "app://cosmas", "clerk_authorized_parties": "app://cosmas",
        "clerk_issuer": "https://clerk.example.invalid",
        "clerk_jwks_url": "https://clerk.example.invalid/.well-known/jwks.json",
        "clerk_audience": "workspace-local", "clerk_organization_id": "org_invented",
        "beta_box_id": "00000000-0000-4000-8000-000000000001", **changes,
    })


def test_desktop_transport_requires_its_own_signed_synthetic_gate():
    defaults = Settings(_env_file=None)  # pyright: ignore[reportCallIssue] -- BaseSettings runtime-only option.
    assert not defaults.workspace_desktop_local_transport_enabled
    assert configured().workspace_available
    assert configured().runtime_configuration_errors() == []


@pytest.mark.parametrize("changes", [
    {"workspace_desktop_local_transport_enabled": False},
    {"workspace_authenticated_enabled": False}, {"workspace_enabled": False},
    {"workspace_native_synthetic_enabled": True}, {"auth_mode": "synth_headers"},
    {"synth_seed": True}, {"blob_backend": "azure"}, {"data_mode": "authorized_beta"},
    {"cosmas_env": "early_adopter_beta"},
    {"database_url": "postgresql+psycopg://invented@remote.invalid/w1a_desktop_test"},
    {"database_url": "postgresql+psycopg://invented@localhost/existing_data"},
    {"cors_allowed_origins": "http://localhost:5173"},
    {"clerk_authorized_parties": "http://localhost:5173"},
    {"cors_allowed_origins": "app://cosmas/"},
    {"clerk_authorized_parties": "app://cosmas/"},
    {"cors_allowed_origins": "app://cosmas:8046"},
    {"cors_allowed_origins": "app://other"},
])
def test_desktop_cannot_widen_data_environment_or_identity_rules(changes):
    result = configured(**changes)
    assert not result.workspace_available
    assert result.runtime_configuration_errors()
