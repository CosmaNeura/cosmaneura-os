from uuid import uuid4

import pytest
from pydantic import ValidationError

from cosmas_os.api.workspace_schemas import WorkspaceAppend, WorkspaceCreate
from cosmas_os.config import Settings


def test_entry_does_not_accept_claimed_actor_service_or_approval():
    valid = dict(
        expected_revision=1,
        idempotency_key="entry-key-1",
        kind="conversation",
        content="Invented question",
    )
    for forged in [
        {"actor_id": str(uuid4())},
        {"origin": "core"},
        {"approved": True},
        {"kind": "synthetic_source"},
    ]:
        with pytest.raises(ValidationError):
            WorkspaceAppend(**{**valid, **forged})
    assert WorkspaceAppend(**valid).content == "Invented question"


@pytest.mark.parametrize(
    "change",
    [
        {"content": " "},
        {"content": "x" * 20001},
        {"expected_revision": 0},
        {"expected_revision": True},
        {"idempotency_key": "bad key"},
        {"kind": "evidence"},
        {"source_label": "forged service source"},
    ],
)
def test_entry_bounds(change):
    with pytest.raises(ValidationError):
        WorkspaceAppend(
            **{
                **dict(
                    expected_revision=1,
                    idempotency_key="entry-key-1",
                    kind="scratchpad",
                    content="Invented note",
                ),
                **change,
            }
        )


def test_create_cannot_select_owner_or_box():
    with pytest.raises(ValidationError):
        WorkspaceCreate(appointment_id=uuid4(), idempotency_key="create-key", owner_id=uuid4())


@pytest.mark.parametrize(
    "change",
    [
        {"cosmas_env": "early_adopter_beta"},
        {"data_mode": "authorized_beta"},
        {"auth_mode": "clerk_jwt"},
        {"blob_backend": "azure"},
        {"database_url": "postgresql+psycopg://user@remote.invalid/w1a_test"},
        {"database_url": "postgresql+psycopg://user@127.0.0.1/cosmas_os"},
        {"cors_allowed_origins": "https://example.invalid"},
        {"cors_allowed_origins": "http://user@127.0.0.1"},
        {"cors_allowed_origins": "http://127.0.0.1/path"},
        {"cors_allowed_origins": ""},
    ],
)
def test_feature_rejects_nonlocal_or_non_synthetic_configuration(change):
    s = Settings(
        _env_file=None,
        **{
            **dict(
                workspace_enabled=True,
                database_url="postgresql+psycopg://w1a_synth@127.0.0.1:55439/w1a_test",
            ),
            **change,
        },
    )
    assert not s.workspace_available
    assert any("WORKSPACE_ENABLED" in message for message in s.runtime_configuration_errors())


def test_feature_defaults_off_and_accepts_only_explicit_local_setup():
    assert not Settings(_env_file=None).workspace_available
    s = Settings(
        _env_file=None,
        workspace_enabled=True,
        database_url="postgresql+psycopg://w1a_synth@127.0.0.1:55439/w1a_test",
    )
    assert s.workspace_available


@pytest.mark.parametrize("change", [
    {}, {"synth_seed": True}, {"auth_mode": "synth_headers"},
    {"clerk_issuer": "http://issuer.invalid"},
    {"clerk_jwks_url": "https://other.invalid/.well-known/jwks.json"},
    {"clerk_jwks_url": "https://issuer.invalid/unrelated"},
    {"clerk_authorized_parties": "http://other.invalid"},
    {"beta_box_id": "not-a-box"}, {"workspace_native_synthetic_enabled": True},
    {"cosmas_env": "early_adopter_beta"}, {"data_mode": "authorized_beta"},
    {"database_url": "postgresql+psycopg://user@remote.invalid/w1a_test"},
    {"workspace_enabled": False},
])
def test_authenticated_workspace_is_explicit_local_and_cannot_seed(change):
    settings = Settings(_env_file=None, **{
        **dict(workspace_enabled=True, workspace_authenticated_enabled=True,
            auth_mode="clerk_jwt", synth_seed=False,
            database_url="postgresql+psycopg://w1a_synth@127.0.0.1:55439/w1a_test",
            clerk_issuer="https://issuer.invalid",
            clerk_jwks_url="https://issuer.invalid/.well-known/jwks.json",
            clerk_organization_id="org_invented", clerk_audience="workspace-local",
            clerk_authorized_parties="http://localhost:5173", beta_box_id=str(uuid4())),
        **change,
    })
    assert settings.workspace_available is (not change)
    assert bool(settings.runtime_configuration_errors()) is bool(change)
