from __future__ import annotations

import pytest
from sqlalchemy import select, text

from cosmas_os.application.beta_bootstrap import (
    BetaBootstrapError,
    BetaBootstrapManifest,
    bootstrap_beta_identity,
    seed_beta_synthetic_queue,
)
from cosmas_os.config import Settings
from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, Principal, Ticket

BOX_ID = "00000000-0000-4000-8000-000000000101"


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


def _manifest(**overrides) -> BetaBootstrapManifest:
    values = {
        "schema_version": "cosmas-os/d3-beta-bootstrap/v1",
        "box_id": BOX_ID,
        "clinic_display_name": "Example Beta Clinic",
        "owner_display_name": "Taylor Owner",
        "clerk_issuer": "https://clerk.example.invalid",
        "clerk_subject": "user_test_beta_owner",
        "clerk_organization_id": "org_test_beta",
        "reviewed_by": "Test Reviewer",
        "evidence_ref": "deploy:test-review",
    }
    values.update(overrides)
    return BetaBootstrapManifest.model_validate(values)


def test_bootstrap_creates_one_box_owner_agents_binding_and_audit(session) -> None:
    _empty_database(session)
    manifest = _manifest()
    bootstrap_beta_identity(session, _runtime(), manifest)
    bootstrap_beta_identity(session, _runtime(), manifest)

    boxes = session.scalars(select(BoxContext)).all()
    principals = session.scalars(select(Principal)).all()
    binding = session.scalar(select(ExternalIdentity))
    audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "external_identity.bound")
    )
    assert len(boxes) == 1
    assert len(principals) == 4
    assert binding is not None and binding.box_id == BOX_ID
    assert audit is not None and audit.detail == {"provider": "clerk", "human_deploy": True}


def test_reviewed_beta_can_seed_exact_synthetic_queue_idempotently(session) -> None:
    _empty_database(session)
    runtime = _runtime()
    bootstrap_beta_identity(session, runtime, _manifest())

    seed_beta_synthetic_queue(session, runtime)
    seed_beta_synthetic_queue(session, runtime)

    tickets = session.scalars(select(Ticket).where(Ticket.box_id == BOX_ID)).all()
    assert len(tickets) == 1
    assert tickets[0].state == "pending_approval"


def test_beta_seed_refuses_authorized_data_mode(session) -> None:
    _empty_database(session)
    runtime = _runtime()
    bootstrap_beta_identity(session, runtime, _manifest())

    with pytest.raises(BetaBootstrapError, match="unavailable"):
        seed_beta_synthetic_queue(
            session,
            _runtime(data_mode="authorized_beta", phi_authorization_ref="phi:test"),
        )


def test_bootstrap_refuses_manifest_that_differs_from_runtime(session) -> None:
    _empty_database(session)
    with pytest.raises(BetaBootstrapError, match="does not match"):
        bootstrap_beta_identity(
            session,
            _runtime(),
            _manifest(clerk_organization_id="org_wrong"),
        )
    assert session.scalar(select(BoxContext)) is None


def test_bootstrap_refuses_nonempty_dedicated_database(session) -> None:
    _empty_database(session)
    session.add(BoxContext(display_name="Unexpected Existing Box"))
    session.flush()
    with pytest.raises(BetaBootstrapError, match="not empty"):
        bootstrap_beta_identity(session, _runtime(), _manifest())
