from __future__ import annotations

import pytest

from cosmas_os.api.auth import AccessDenied, AuthenticationFailed, authenticate_request
from cosmas_os.config import Settings
from cosmas_os.domain.enums import PrincipalState
from cosmas_os.models import ExternalIdentity, Principal


class FakeVerifier:
    def __init__(self, claims: dict[str, object]) -> None:
        self.claims = claims

    def verify(self, token: str) -> dict[str, object]:
        assert token == "verified-token"
        return self.claims


def _beta_settings(box_id: str) -> Settings:
    return Settings(
        cosmas_env="early_adopter_beta",
        auth_mode="clerk_jwt",
        cors_allowed_origins="https://beta.example.invalid",
        synth_seed=False,
        blob_backend="azure",
        azure_storage_account_url="https://storage.example.invalid",
        azure_blob_container="box-data",
        clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-beta-api",
        clerk_organization_id="org_test_beta",
        clerk_authorized_parties="https://beta.example.invalid",
        beta_box_id=box_id,
        clinic_approval_ref="approval:test-clinic",
        baa_evidence_ref="baa:test-evidence",
        human_deploy_evidence_ref="deploy:test-review",
        database_url=(
            "postgresql+psycopg://test:test@pg.example.invalid/cosmas_os?"
            "sslmode=verify-full&sslrootcert=system"
        ),
        redis_url="rediss://:invented-secret@redis.example.invalid:6380/0?ssl_cert_reqs=required",
        sync_worker=False,
    )


def _bind_owner(session, seeded) -> ExternalIdentity:
    binding = ExternalIdentity(
        box_id=seeded["box_id"],
        principal_id=seeded["owner_id"],
        provider="clerk",
        issuer="https://clerk.example.invalid",
        subject="user_test_owner",
        organization_id="org_test_beta",
        reviewed_by="Test Reviewer",
        evidence_ref="test:identity-binding",
    )
    session.add(binding)
    session.commit()
    return binding


def test_synth_headers_are_checked_against_principal_box(session, seeded) -> None:
    identity = authenticate_request(
        session,
        Settings(),
        authorization=None,
        box_header=seeded["box_id"],
        actor_header=seeded["owner_id"],
    )
    assert identity.box_id == seeded["box_id"]
    assert identity.principal_id == seeded["owner_id"]

    with pytest.raises(AccessDenied):
        authenticate_request(
            session,
            Settings(),
            authorization=None,
            box_header="00000000-0000-4000-8000-000000000099",
            actor_header=seeded["owner_id"],
        )


def test_beta_derives_box_and_principal_from_reviewed_binding(session, seeded) -> None:
    _bind_owner(session, seeded)
    identity = authenticate_request(
        session,
        _beta_settings(seeded["box_id"]),
        authorization="Bearer verified-token",
        box_header=None,
        actor_header=None,
        verifier=FakeVerifier(
            {"sub": "user_test_owner", "o": {"id": "org_test_beta"}}
        ),
    )
    assert identity.box_id == seeded["box_id"]
    assert identity.principal_id == seeded["owner_id"]
    assert identity.organization_id == "org_test_beta"


def test_beta_rejects_caller_supplied_box_or_actor_headers(session, seeded) -> None:
    _bind_owner(session, seeded)
    with pytest.raises(AuthenticationFailed, match="not accepted"):
        authenticate_request(
            session,
            _beta_settings(seeded["box_id"]),
            authorization="Bearer verified-token",
            box_header=seeded["box_id"],
            actor_header=seeded["owner_id"],
            verifier=FakeVerifier(
                {"sub": "user_test_owner", "org_id": "org_test_beta"}
            ),
        )


def test_beta_rejects_unprovisioned_and_wrong_org_identities(session, seeded) -> None:
    configured = _beta_settings(seeded["box_id"])
    with pytest.raises(AccessDenied, match="not provisioned"):
        authenticate_request(
            session,
            configured,
            authorization="Bearer verified-token",
            box_header=None,
            actor_header=None,
            verifier=FakeVerifier(
                {"sub": "user_not_bound", "org_id": "org_test_beta"}
            ),
        )
    with pytest.raises(AccessDenied, match="outside the configured organization"):
        authenticate_request(
            session,
            configured,
            authorization="Bearer verified-token",
            box_header=None,
            actor_header=None,
            verifier=FakeVerifier(
                {"sub": "user_test_owner", "org_id": "org_wrong"}
            ),
        )


def test_beta_rejects_inactive_bound_human(session, seeded) -> None:
    _bind_owner(session, seeded)
    owner = session.get(Principal, seeded["owner_id"])
    assert owner is not None
    owner.state = PrincipalState.TOMBSTONED.value
    session.commit()
    with pytest.raises(AccessDenied, match="active human"):
        authenticate_request(
            session,
            _beta_settings(seeded["box_id"]),
            authorization="Bearer verified-token",
            box_header=None,
            actor_header=None,
            verifier=FakeVerifier(
                {"sub": "user_test_owner", "org_id": "org_test_beta"}
            ),
        )
