from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from cosmas_os.application import beta_bootstrap as beta_bootstrap_module
from cosmas_os.application.beta_bootstrap import (
    BOOTSTRAP_READBACK_CONTRACT,
    BetaBootstrapError,
    BetaBootstrapManifest,
    bootstrap_beta_identity,
    seed_beta_synthetic_queue,
    verify_beta_bootstrap_state,
)
from cosmas_os.config import Settings
from cosmas_os.models import (
    ActionRevision,
    AppointmentObservation,
    Artifact,
    AuditEvent,
    BoxContext,
    CapabilityConfig,
    Decision,
    ExternalIdentity,
    Operation,
    PatientLink,
    Principal,
    Ticket,
)

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

    first = verify_beta_bootstrap_state(session, runtime, _manifest()).sanitized_json()
    bootstrap_beta_identity(session, runtime, _manifest())
    seed_beta_synthetic_queue(session, runtime)
    second = verify_beta_bootstrap_state(session, runtime, _manifest()).sanitized_json()
    assert first == second
    readback = json.loads(second)
    assert readback["contract"] == BOOTSTRAP_READBACK_CONTRACT
    assert readback["box_count"] == 1
    assert readback["active_owner_count"] == 1
    assert readback["active_baseline_agent_count"] == 3
    assert readback["clerk_binding_count"] == 1
    assert readback["appointment_observation_count"] == 2
    assert readback["pending_ticket_count"] == 1
    assert readback["total_ticket_count"] == 1
    assert readback["action_revision_count"] == 1
    assert readback["decision_count"] == 0
    assert readback["operation_count"] == 0
    assert readback["artifact_count"] == 0
    assert readback["capability_config_count"] == 0
    assert readback["audit_event_count"] == 3
    assert BOX_ID not in second


@pytest.mark.parametrize("external_id", ["appt-1001", "appt-1002"])
def test_bootstrap_readback_rejects_missing_appointment_start(session, external_id: str) -> None:
    _empty_database(session)
    runtime = _runtime()
    manifest = _manifest()
    bootstrap_beta_identity(session, runtime, manifest)
    seed_beta_synthetic_queue(session, runtime)
    appointment = session.scalar(
        select(AppointmentObservation).where(AppointmentObservation.external_id == external_id)
    )
    assert appointment is not None
    # Persisted CSV rows require a start time. Exercise a nullable cached value
    # without weakening that constraint or flushing the injected fault.
    appointment.start_at = None
    try:
        with session.no_autoflush, pytest.raises(BetaBootstrapError, match="readback differs"):
            verify_beta_bootstrap_state(session, runtime, manifest)
    finally:
        session.expire(appointment, ["start_at"])


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


def test_bootstrap_manifest_rejects_extra_fields_and_noncanonical_box_id() -> None:
    values = _manifest().model_dump(mode="json")
    with pytest.raises(ValueError):
        BetaBootstrapManifest.model_validate({**values, "ignored": "not allowed"})
    with pytest.raises(ValueError):
        BetaBootstrapManifest.model_validate(
            {**values, "box_id": "00000000-0000-4000-8000-00000000010A"}
        )


def test_bootstrap_refuses_nonempty_dedicated_database(session) -> None:
    _empty_database(session)
    session.add(BoxContext(display_name="Unexpected Existing Box"))
    session.flush()
    with pytest.raises(BetaBootstrapError, match="not empty"):
        bootstrap_beta_identity(session, _runtime(), _manifest())


def test_bootstrap_readback_rejects_unexpected_same_box_ticket(session) -> None:
    _empty_database(session)
    runtime = _runtime()
    manifest = _manifest()
    bootstrap_beta_identity(session, runtime, manifest)
    seed_beta_synthetic_queue(session, runtime)
    original = session.scalar(select(Ticket).where(Ticket.box_id == BOX_ID))
    revision = session.scalar(select(ActionRevision).where(ActionRevision.box_id == BOX_ID))
    assert original is not None and revision is not None
    session.add(
        Ticket(
            box_id=BOX_ID,
            lane="artifact_chase",
            state="sent",
            version=1,
            created_by_principal_id=original.created_by_principal_id,
            appointment_id=original.appointment_id,
            patient_link_id=original.patient_link_id,
            current_revision_id=revision.id,
        )
    )
    session.commit()

    with pytest.raises(BetaBootstrapError, match="readback differs"):
        verify_beta_bootstrap_state(session, runtime, manifest)


def test_bootstrap_readback_rejects_unexpected_same_box_identity_binding(session) -> None:
    _empty_database(session)
    runtime = _runtime()
    manifest = _manifest()
    bootstrap_beta_identity(session, runtime, manifest)
    seed_beta_synthetic_queue(session, runtime)
    owner = session.scalar(
        select(Principal).where(Principal.box_id == BOX_ID, Principal.is_owner.is_(True))
    )
    assert owner is not None
    session.add(
        ExternalIdentity(
            box_id=BOX_ID,
            principal_id=owner.id,
            provider="other",
            issuer="https://other.example.invalid",
            subject="user_unexpected",
            organization_id="org_unexpected",
            active=True,
            reviewed_by="Unexpected Reviewer",
            evidence_ref="unexpected:evidence",
        )
    )
    session.commit()

    with pytest.raises(BetaBootstrapError, match="readback differs"):
        verify_beta_bootstrap_state(session, runtime, manifest)


@pytest.mark.parametrize(
    ("principal_kind", "field_name", "unexpected_value"),
    [
        ("agent", "display_name", "Renamed Chaser"),
        ("agent", "policy_version", "policy-v2"),
        ("agent", "charter_version", "charter-v2"),
        ("agent", "config_version", "config-v2"),
        ("agent", "tombstoned_at", datetime(2026, 9, 1, tzinfo=UTC)),
        ("owner", "agent_key", "unexpected-owner-key"),
        ("owner", "policy_version", "policy-v2"),
        ("owner", "charter_version", "charter-v2"),
        ("owner", "config_version", "config-v2"),
        ("owner", "tombstoned_at", datetime(2026, 9, 1, tzinfo=UTC)),
    ],
)
def test_bootstrap_readback_binds_every_bootstrap_principal_default(
    session,
    principal_kind: str,
    field_name: str,
    unexpected_value: object,
) -> None:
    _empty_database(session)
    runtime = _runtime()
    manifest = _manifest()
    bootstrap_beta_identity(session, runtime, manifest)
    seed_beta_synthetic_queue(session, runtime)
    if principal_kind == "owner":
        principal = session.scalar(
            select(Principal).where(
                Principal.box_id == BOX_ID,
                Principal.is_owner.is_(True),
            )
        )
    else:
        principal = session.scalar(
            select(Principal).where(
                Principal.box_id == BOX_ID,
                Principal.agent_key == "chaser",
            )
        )
    assert principal is not None
    setattr(principal, field_name, unexpected_value)
    session.commit()

    with pytest.raises(BetaBootstrapError, match="readback differs"):
        verify_beta_bootstrap_state(session, runtime, manifest)


@pytest.mark.parametrize(
    "unexpected_table",
    ["decision", "operation", "artifact", "capability_config"],
)
def test_bootstrap_readback_requires_post_seed_mutation_tables_to_be_empty(
    session,
    unexpected_table: str,
) -> None:
    _empty_database(session)
    runtime = _runtime()
    manifest = _manifest()
    bootstrap_beta_identity(session, runtime, manifest)
    seed_beta_synthetic_queue(session, runtime)
    ticket = session.scalar(select(Ticket).where(Ticket.box_id == BOX_ID))
    revision = session.scalar(select(ActionRevision).where(ActionRevision.box_id == BOX_ID))
    owner = session.scalar(
        select(Principal).where(Principal.box_id == BOX_ID, Principal.is_owner.is_(True))
    )
    assert ticket is not None and revision is not None and owner is not None

    if unexpected_table == "decision":
        unexpected = Decision(
            box_id=BOX_ID,
            ticket_id=ticket.id,
            action_revision_id=revision.id,
            actor_principal_id=owner.id,
            kind="approve",
        )
    elif unexpected_table == "operation":
        unexpected = Operation(
            box_id=BOX_ID,
            ticket_id=ticket.id,
            action_revision_id=revision.id,
            idempotency_key=f"unexpected:{revision.id}",
            adapter="notify",
            status="pending",
        )
    elif unexpected_table == "artifact":
        unexpected = Artifact(
            box_id=BOX_ID,
            ticket_id=ticket.id,
            classification="unexpected",
            side="front",
        )
    else:
        unexpected = CapabilityConfig(
            box_id=BOX_ID,
            key="unexpected.capability",
            enabled=False,
        )
    session.add(unexpected)
    session.commit()

    with pytest.raises(BetaBootstrapError, match="readback differs"):
        verify_beta_bootstrap_state(session, runtime, manifest)


def test_bootstrap_readback_rejects_incomplete_or_fabricated_audit_set(session) -> None:
    _empty_database(session)
    runtime = _runtime()
    manifest = _manifest()
    bootstrap_beta_identity(session, runtime, manifest)
    seed_beta_synthetic_queue(session, runtime)
    ticket = session.scalar(select(Ticket).where(Ticket.box_id == BOX_ID))
    assert ticket is not None
    session.add(
        AuditEvent(
            box_id=BOX_ID,
            aggregate_type="ticket",
            aggregate_id=ticket.id,
            event_type="operation.succeeded",
            outcome="succeeded",
            detail={},
        )
    )
    session.commit()

    with pytest.raises(BetaBootstrapError, match="readback differs"):
        verify_beta_bootstrap_state(session, runtime, manifest)

    fabricated = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "operation.succeeded")
    )
    assert fabricated is not None
    session.delete(fabricated)
    ticket_opened = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "ticket.opened")
    )
    assert ticket_opened is not None
    ticket_opened.aggregate_id = str(manifest.box_id)
    session.commit()

    with pytest.raises(BetaBootstrapError, match="readback differs"):
        verify_beta_bootstrap_state(session, runtime, manifest)


@pytest.mark.parametrize("mutation", ["future", "reordered", "ancient_attestation"])
def test_bootstrap_readback_rejects_invalid_bootstrap_chronology(
    session,
    mutation: str,
) -> None:
    _empty_database(session)
    runtime = _runtime()
    manifest = _manifest()
    bootstrap_beta_identity(session, runtime, manifest)
    seed_beta_synthetic_queue(session, runtime)
    link_audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "patient_link.attested")
    )
    ticket_audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "ticket.opened")
    )
    patient_link = session.scalar(select(PatientLink).where(PatientLink.box_id == BOX_ID))
    assert link_audit is not None and ticket_audit is not None and patient_link is not None
    if mutation == "future":
        ticket_audit.created_at = datetime(2035, 1, 1, tzinfo=UTC)
    elif mutation == "reordered":
        ticket_audit.created_at = link_audit.created_at - timedelta(seconds=1)
    else:
        patient_link.attested_at = link_audit.created_at - timedelta(seconds=6)
    session.commit()

    with pytest.raises(BetaBootstrapError, match="readback differs"):
        verify_beta_bootstrap_state(session, runtime, manifest)


def test_bootstrap_readback_allows_bounded_application_clock_ahead_of_database(
    session,
    monkeypatch,
) -> None:
    _empty_database(session)
    runtime = _runtime()
    manifest = _manifest()
    bootstrap_beta_identity(session, runtime, manifest)
    seed_beta_synthetic_queue(session, runtime)
    ticket = session.scalar(select(Ticket).where(Ticket.box_id == BOX_ID))
    revision = session.scalar(select(ActionRevision).where(ActionRevision.box_id == BOX_ID))
    patient_link = session.scalar(select(PatientLink).where(PatientLink.box_id == BOX_ID))
    link_audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "patient_link.attested")
    )
    ticket_audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "ticket.opened")
    )
    assert ticket is not None and revision is not None and patient_link is not None
    assert link_audit is not None and ticket_audit is not None
    database_observed_at = max(ticket.created_at, revision.created_at)
    patient_link.attested_at = database_observed_at + timedelta(seconds=2)
    link_audit.created_at = database_observed_at + timedelta(seconds=2, milliseconds=100)
    ticket_audit.created_at = database_observed_at + timedelta(seconds=2, milliseconds=200)
    session.commit()
    monkeypatch.setattr(
        beta_bootstrap_module,
        "_database_now",
        lambda _session: database_observed_at,
    )

    assert verify_beta_bootstrap_state(session, runtime, manifest).status == "verified"
