import pytest

from cosmas_os.config import Settings


def settings(**values):
    return Settings(
        _env_file=None,
        **{
            "workspace_enabled": True,
            "workspace_native_synthetic_enabled": True,
            "database_url": "postgresql+psycopg://invented@127.0.0.1:55439/w1a_native_test",
            "cors_allowed_origins": "http://127.0.0.1:5188,capacitor://localhost",
            **values,
        },
    )


def test_native_origin_requires_explicit_synthetic_gate():
    assert not settings(workspace_native_synthetic_enabled=False).workspace_available
    enabled = settings()
    assert enabled.workspace_available
    assert not enabled.runtime_configuration_errors()


@pytest.mark.parametrize(
    "origin",
    [
        "capacitor://other",
        "capacitor://localhost:8018",
        "capacitor://localhost/path",
        "capacitor://user@localhost",
        "capacitor://localhost?source=external",
        "capacitor://localhost#external",
        "capacitor://localhost/",
        "https://example.invalid",
        "*",
    ],
)
def test_native_gate_does_not_allow_other_origins(origin):
    config = settings(cors_allowed_origins=origin)
    assert not config.workspace_available
    assert config.runtime_configuration_errors()


@pytest.mark.parametrize(
    "override",
    [
        {"workspace_enabled": False},
        {"cosmas_env": "early_adopter_beta"},
        {"data_mode": "authorized_beta"},
        {"auth_mode": "clerk_jwt"},
        {"blob_backend": "azure"},
        {"database_url": "postgresql+psycopg://invented@remote.invalid/w1a_native_test"},
        {"database_url": "postgresql+psycopg://invented@localhost/cosmas_os"},
    ],
)
def test_native_gate_cannot_activate_hosted_or_real_data_modes(override):
    config = settings(**override)
    assert not config.workspace_available
    assert config.runtime_configuration_errors()
