from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from cosmas_os.api.app import _identity, app, get_session
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.application.beta_bootstrap import (
    BetaBootstrapManifest,
    bootstrap_beta_identity,
)
from cosmas_os.application.beta_identity_admin import (
    BetaIdentityAdminError,
    bind_beta_identity,
    deactivate_beta_identity,
    list_beta_identities,
    reactivate_beta_identity,
    transfer_beta_ownership,
)
from cosmas_os.config import Settings
from cosmas_os.db import make_session_factory
from cosmas_os.domain.enums import PrincipalState, PrincipalType
from cosmas_os.domain.rules import AuthorizationError
from cosmas_os.models import AuditEvent, ExternalIdentity, Principal

BOX_ID = "00000000-0000-4000-8000-000000000201"


def _empty_database(session) -> None:
    session.execute(
        text(
            "TRUNCATE external_identities, capability_configs, artifacts, audit_events, "
            "operations, decisions, action_revisions, tickets, appointment_observations, "
            "patient_links, principals, box_contexts CASCADE"
        )
    )


def _runtime(**overrides) -> Settings:
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
        "beta_box_id": BOX_ID,
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


def _bootstrap(session) -> Principal:
    bootstrap_beta_identity(
        session,
        _runtime(),
        BetaBootstrapManifest.model_validate(
            {
                "schema_version": "cosmas-os/d3-beta-bootstrap/v1",
                "box_id": BOX_ID,
                "clinic_display_name": "Cosmas Synthetic Beta Lab",
                "owner_display_name": "Taylor Owner",
                "clerk_issuer": "https://clerk.example.invalid",
                "clerk_subject": "user_test_beta_owner",
                "clerk_organization_id": "org_test_beta",
                "reviewed_by": "Test Reviewer",
                "evidence_ref": "deploy:test-review",
            }
        ),
    )
    owner = session.scalar(
        select(Principal).where(Principal.box_id == BOX_ID, Principal.is_owner.is_(True))
    )
    assert owner is not None
    return owner


def _bind_member(session, owner: Principal, *, subject: str = "user_test_member") -> None:
    bind_beta_identity(
        session,
        _runtime(),
        actor_principal_id=owner.id,
        clerk_subject=subject,
        display_name="Morgan Tester",
        evidence_ref="identity-review:test-member",
    )


def test_authenticated_owner_can_bind_member_idempotently_with_audit_evidence(session) -> None:
    _empty_database(session)
    owner = _bootstrap(session)

    _bind_member(session, owner)
    _bind_member(session, owner)

    binding = session.scalar(
        select(ExternalIdentity).where(ExternalIdentity.subject == "user_test_member")
    )
    assert binding is not None and binding.active
    principal = session.get(Principal, binding.principal_id)
    assert principal is not None
    assert principal.principal_type == PrincipalType.HUMAN.value
    assert principal.state == PrincipalState.ACTIVE.value
    assert not principal.is_owner
    audit = session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == "external_identity.bound",
            AuditEvent.aggregate_id == binding.id,
        )
    )
    assert audit is not None
    assert audit.actor_principal_id == owner.id
    assert audit.initiated_by_principal_id == owner.id
    assert audit.approved_by_principal_id == owner.id
    assert audit.detail["evidence_ref"] == "identity-review:test-member"
    assert len(audit.detail["request_digest"]) == 64
    audit_count = session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.event_type == "external_identity.bound",
            AuditEvent.aggregate_id == binding.id,
        )
    )
    assert audit_count == 1


def test_non_owner_cannot_bind_member(session) -> None:
    _empty_database(session)
    owner = _bootstrap(session)
    _bind_member(session, owner)
    member_binding = session.scalar(
        select(ExternalIdentity).where(ExternalIdentity.subject == "user_test_member")
    )
    assert member_binding is not None

    with pytest.raises(AuthorizationError, match="owner authority"):
        bind_beta_identity(
            session,
            _runtime(),
            actor_principal_id=member_binding.principal_id,
            clerk_subject="user_test_second",
            display_name="Second Tester",
            evidence_ref="identity-review:test-second",
        )


def test_owner_can_list_only_privacy_minimized_beta_roster(session) -> None:
    _empty_database(session)
    owner = _bootstrap(session)
    _bind_member(session, owner)

    roster = list_beta_identities(
        session,
        _runtime(),
        actor_principal_id=owner.id,
    )

    assert [entry.clerk_subject for entry in roster] == [
        "user_test_beta_owner",
        "user_test_member",
    ]
    assert roster[0].display_name == "Taylor Owner"
    assert roster[0].is_owner
    assert roster[0].active
    assert roster[1].display_name == "Morgan Tester"
    assert not roster[1].is_owner
    assert roster[1].principal_state == PrincipalState.ACTIVE.value


def test_non_owner_cannot_list_beta_roster(session) -> None:
    _empty_database(session)
    owner = _bootstrap(session)
    _bind_member(session, owner)
    member_binding = session.scalar(
        select(ExternalIdentity).where(ExternalIdentity.subject == "user_test_member")
    )
    assert member_binding is not None

    with pytest.raises(AuthorizationError, match="owner authority"):
        list_beta_identities(
            session,
            _runtime(),
            actor_principal_id=member_binding.principal_id,
        )


def test_identity_roster_route_is_owner_scoped_privacy_minimized_and_not_cached(
    monkeypatch, session
) -> None:
    _empty_database(session)
    owner = _bootstrap(session)
    _bind_member(session, owner)
    member_binding = session.scalar(
        select(ExternalIdentity).where(ExternalIdentity.subject == "user_test_member")
    )
    assert member_binding is not None
    owner_id = owner.id
    member_id = member_binding.principal_id

    monkeypatch.setattr("cosmas_os.api.app.settings", _runtime())
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[_identity] = lambda: RequestIdentity(
        box_id=BOX_ID,
        principal_id=owner_id,
        auth_mode="clerk_jwt",
        organization_id="org_test_beta",
    )
    try:
        with TestClient(app) as client:
            response = client.get("/admin/identities")
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "no-store"
            assert response.json() == [
                {
                    "clerk_subject": "user_test_beta_owner",
                    "display_name": "Taylor Owner",
                    "active": True,
                    "principal_state": PrincipalState.ACTIVE.value,
                    "is_owner": True,
                },
                {
                    "clerk_subject": "user_test_member",
                    "display_name": "Morgan Tester",
                    "active": True,
                    "principal_state": PrincipalState.ACTIVE.value,
                    "is_owner": False,
                },
            ]

            app.dependency_overrides[_identity] = lambda: RequestIdentity(
                box_id=BOX_ID,
                principal_id=member_id,
                auth_mode="clerk_jwt",
                organization_id="org_test_beta",
            )
            denied = client.get("/admin/identities")
            assert denied.status_code == 403
            assert denied.json() == {"detail": "active Box owner authority is required"}
    finally:
        app.dependency_overrides.pop(_identity, None)
        app.dependency_overrides.pop(get_session, None)


def test_wrong_runtime_cannot_bind_member(session) -> None:
    _empty_database(session)
    owner = _bootstrap(session)
    owner_id = owner.id
    with pytest.raises(RuntimeError, match="CLERK_ORGANIZATION_ID is required"):
        bind_beta_identity(
            session,
            _runtime(clerk_organization_id=None),
            actor_principal_id=owner_id,
            clerk_subject="user_test_second",
            display_name="Second Tester",
            evidence_ref="identity-review:test-second",
        )


def test_bind_rejects_subject_rebinding(session) -> None:
    _empty_database(session)
    owner = _bootstrap(session)
    _bind_member(session, owner)

    with pytest.raises(BetaIdentityAdminError, match="already bound differently"):
        bind_beta_identity(
            session,
            _runtime(),
            actor_principal_id=owner.id,
            clerk_subject="user_test_member",
            display_name="Different Person",
            evidence_ref="identity-review:test-member",
        )


def test_deactivate_and_reactivate_preserve_review_evidence(session) -> None:
    _empty_database(session)
    owner = _bootstrap(session)
    _bind_member(session, owner)

    deactivate_beta_identity(
        session,
        _runtime(),
        actor_principal_id=owner.id,
        clerk_subject="user_test_member",
        evidence_ref="identity-review:test-offboarding",
    )
    binding = session.scalar(
        select(ExternalIdentity).where(ExternalIdentity.subject == "user_test_member")
    )
    assert binding is not None and not binding.active
    principal = session.get(Principal, binding.principal_id)
    assert principal is not None and principal.state == PrincipalState.DISABLED.value
    deactivation = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "external_identity.deactivated")
    )
    assert deactivation is not None
    assert deactivation.detail["evidence_ref"] == "identity-review:test-offboarding"
    assert len(deactivation.detail["request_digest"]) == 64

    reactivate_beta_identity(
        session,
        _runtime(),
        actor_principal_id=owner.id,
        clerk_subject="user_test_member",
        evidence_ref="identity-review:test-reactivation",
    )
    assert binding.active
    assert principal.state == PrincipalState.ACTIVE.value
    reactivation = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "external_identity.reactivated")
    )
    assert reactivation is not None
    assert reactivation.detail["evidence_ref"] == "identity-review:test-reactivation"


def test_owner_cannot_be_deactivated_before_transfer(session) -> None:
    _empty_database(session)
    owner = _bootstrap(session)

    with pytest.raises(BetaIdentityAdminError, match="transfer ownership"):
        deactivate_beta_identity(
            session,
            _runtime(),
            actor_principal_id=owner.id,
            clerk_subject="user_test_beta_owner",
            evidence_ref="identity-review:test-owner-offboarding",
        )


def test_owner_can_transfer_to_active_bound_member_atomically(session) -> None:
    _empty_database(session)
    owner = _bootstrap(session)
    _bind_member(session, owner)
    binding = session.scalar(
        select(ExternalIdentity).where(ExternalIdentity.subject == "user_test_member")
    )
    assert binding is not None
    successor = session.get(Principal, binding.principal_id)
    assert successor is not None

    transfer_beta_ownership(
        session,
        _runtime(),
        actor_principal_id=owner.id,
        successor_clerk_subject="user_test_member",
        evidence_ref="identity-review:test-owner-transfer",
    )

    assert not owner.is_owner
    assert successor.is_owner
    transfer_audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "owner.transferred")
    )
    assert transfer_audit is not None
    assert transfer_audit.approved_by_principal_id == owner.id
    with pytest.raises(AuthorizationError, match="owner authority"):
        bind_beta_identity(
            session,
            _runtime(),
            actor_principal_id=owner.id,
            clerk_subject="user_test_after_transfer",
            display_name="Later Tester",
            evidence_ref="identity-review:test-later",
        )


def test_stale_authenticated_owner_is_denied_after_concurrent_transfer(engine) -> None:
    SessionLocal = make_session_factory(engine)
    setup = SessionLocal()
    session_a = SessionLocal()
    session_b = SessionLocal()
    cleanup = SessionLocal()
    try:
        _empty_database(setup)
        setup.commit()
        owner = _bootstrap(setup)
        owner_id = owner.id
        _bind_member(setup, owner)
        successor_binding = setup.scalar(
            select(ExternalIdentity).where(ExternalIdentity.subject == "user_test_member")
        )
        assert successor_binding is not None

        stale_owner = session_a.get(Principal, owner_id)
        assert stale_owner is not None and stale_owner.is_owner

        transfer_beta_ownership(
            session_b,
            _runtime(),
            actor_principal_id=owner_id,
            successor_clerk_subject="user_test_member",
            evidence_ref="identity-review:test-concurrent-transfer",
        )

        with pytest.raises(AuthorizationError, match="owner authority"):
            bind_beta_identity(
                session_a,
                _runtime(),
                actor_principal_id=owner_id,
                clerk_subject="user_test_stale_owner_attempt",
                display_name="Blocked Tester",
                evidence_ref="identity-review:test-blocked",
            )
    finally:
        session_a.close()
        session_b.close()
        setup.close()
        _empty_database(cleanup)
        cleanup.commit()
        cleanup.close()
