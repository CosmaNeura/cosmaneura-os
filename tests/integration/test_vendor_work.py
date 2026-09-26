"""F8 delivery ledger against PostgreSQL, with no provider or credential access."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from cosmas_os.api import vendor_work_schemas as p
from cosmas_os.application import note_review as notes
from cosmas_os.application import vendor_execution as execution
from cosmas_os.application import vendor_shared
from cosmas_os.application import vendor_work as flow
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.models import (
    ActionRevision,
    AppointmentObservation,
    EncounterWorkspace,
    Operation,
    PatientLink,
    WorkspaceEntry,
)
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.vendor_models import (
    VendorConnectionVersion,
    VendorCorrespondenceVersion,
    VendorProviderObservation,
    VendorSubmitClaim,
    VendorWork,
)


@pytest.fixture(autouse=True)
def gates(monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)


@pytest.fixture
def vendor_case(session, seeded):
    s = session
    box, actor = seeded["box_id"], seeded["owner_id"]
    link = PatientLink(
        box_id=box,
        source_pair_key=str(uuid4()),
        label="Invented W36 patient",
        state="confirmed",
        confirmed_by_principal_id=actor,
        attested_at=datetime.now(UTC),
    )
    s.add(link)
    s.flush()
    visit = AppointmentObservation(
        box_id=box,
        patient_link_id=link.id,
        external_id=str(uuid4()),
        source="synthetic",
        start_at=datetime.now(UTC),
        patient_label="Invented W36 visit",
    )
    s.add(visit)
    s.commit()
    w = ws.create(s, box, actor, visit.id, "create-vendor-work")
    w = notes.save(
        s,
        box,
        actor,
        w["id"],
        expected=1,
        key="private-vendor-note",
        base_note_id=None,
        source_reply_id=None,
        content="Invented reviewed clinical source; never publish this text.",
    )["workspace"]
    n = w["note"]["latest"]
    w = notes.review(
        s,
        box,
        actor,
        w["id"],
        n["id"],
        expected=2,
        key="review-vendor-note",
        content_hash=n["content_hash"],
        source_hash=n["source_fingerprint"],
    )["workspace"]
    cid, coid = str(uuid4()), str(uuid4())
    chosen = private.ConnectionSelection(
        vendor="spruce",
        connection_id=cid,
        box_id=box,
        owner_id=actor,
        environment="production",
        remote_account_id="invented_account",
        credential_ref=str(uuid4()),
        configuration_sha256="a" * 64,
    )
    cv = {
        "id": cid,
        "revision": 1,
        "vendor": "spruce",
        "environment": "production",
        "label": "Invented Spruce practice",
        "actions": ["spruce_secure_message", "spruce_media_upload", "spruce_fax"],
        "availability": "enabled",
    }
    cv["public_sha256"] = p.public_digest("cosmas-vendor-public-selection.v1", cv)
    config = VendorConnectionVersion(
        id=cid,
        family_id=str(uuid4()),
        revision=1,
        box_id=box,
        owner_id=actor,
        vendor="spruce",
        environment="production",
        private_selection=chosen.model_dump(mode="json"),
        routing={"internal_endpoint_id": "invented_endpoint", "event_route_id": str(uuid4())},
        private_sha256=chosen.commitment(),
        public_view=cv,
        public_sha256=cv["public_sha256"],
        reviewed_by=actor,
        reviewed_at=datetime.now(UTC),
        write_enabled=True,
        read_enabled=True,
    )
    s.add(config)
    s.flush()
    expiry = datetime.now(UTC) + timedelta(days=2)
    cov = {
        "id": coid,
        "revision": 1,
        "connection_id": cid,
        "channel": "secure",
        "recipient_label": "Invented recipient",
        "destination_display": "Reviewed invented portal contact",
        "permission": "reviewed",
        "expires_at": p.timestamp(expiry),
    }
    cov["public_sha256"] = p.public_digest("cosmas-vendor-public-selection.v1", cov)
    proof = {
        "destination": {"channel": "secure", "contact_id": "invented_contact"},
        "permission_sha256": "b" * 64,
        "patient_mapping_sha256": "c" * 64,
        "practice_mapping_sha256": "d" * 64,
        "recipient_mapping_sha256": "e" * 64,
    }
    co = VendorCorrespondenceVersion(
        id=coid,
        family_id=str(uuid4()),
        revision=1,
        box_id=box,
        owner_id=actor,
        patient_link_id=link.id,
        connection_version_id=cid,
        private_proof=proof,
        private_sha256=private.digest("cosmas-vendor-correspondence.v1", proof),
        public_view=cov,
        public_sha256=cov["public_sha256"],
        reviewed_by=actor,
        reviewed_at=datetime.now(UTC),
        expires_at=expiry,
    )
    s.add(co)
    s.commit()
    return {
        "box": box,
        "actor": actor,
        "wid": w["id"],
        "source": {
            "kind": "reviewed_note",
            "note_id": n["id"],
            "content_sha256": n["content_hash"],
            "source_fingerprint": n["source_fingerprint"],
        },
        "config": config,
        "correspondence": co,
    }


def proposal(case, **extra):
    c, co = case["config"], case["correspondence"]
    return p.VendorProposal.model_validate(
        {
            "expected_workspace_revision": 3,
            "idempotency_key": "proposal-" + str(uuid4()),
            "proposed_operation_id": str(uuid4()),
            "action": "spruce_secure_message",
            "connection": {"id": c.id, "revision": 1, "public_sha256": c.public_sha256},
            "correspondence": {"id": co.id, "revision": 1, "public_sha256": co.public_sha256},
            "source": case["source"],
            "due_date": "2026-10-01",
            "expected_outcome": "Invented patient receives the reviewed follow-up.",
            "share_to_practice": False,
            "message": "Invented secure message.",
            **extra,
        }
    )


def call(s, case, function, *args, **kwargs):
    return function(s, case["box"], case["actor"], case["wid"], *args, **kwargs)


def bound(detail, **extra):
    v = detail["summary"]
    return {
        "expected_version": v["version"],
        "operation_id": v["operation_id"],
        "revision_id": v["revision_id"],
        "payload_hash": v["payload_hash"],
        "idempotency_key": "command-" + str(uuid4()),
        **extra,
    }


def immediate(s):
    s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    s.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def test_proposal_approval_has_no_network_claim_and_does_not_consume_notebook(session, vendor_case):
    c = vendor_case
    s = session
    before = s.scalar(
        select(func.count())
        .select_from(WorkspaceEntry)
        .where(WorkspaceEntry.workspace_id == c["wid"])
    )
    request = proposal(c)
    receipt = call(s, c, flow.propose, request)
    immediate(s)
    tid = receipt["effect"]["ticket_id"]
    detail = call(s, c, flow.detail, tid)
    assert detail["review"]["message"] == request.message
    assert detail["summary"]["state"] == "pending_approval"
    assert s.get(EncounterWorkspace, c["wid"]).revision == 3
    assert (
        s.scalar(
            select(func.count())
            .select_from(WorkspaceEntry)
            .where(WorkspaceEntry.workspace_id == c["wid"])
        )
        == before
    )
    assert s.get(Operation, request.proposed_operation_id) is None
    approve = p.VendorDecision(
        **bound(detail, review_sha256=detail["review_sha256"], choice="approve")
    )
    accepted = call(s, c, flow.decide, tid, approve)
    immediate(s)
    op = s.get(Operation, request.proposed_operation_id)
    assert op.status == "pending" and op.attempt_count == 0 and op.adapter == "workspace_vendor"
    assert accepted["summary"] == {"effect": "approved", "publication_recorded": False}
    assert "invented_contact" not in str(detail) and str(
        c["config"].private_selection["credential_ref"]
    ) not in str(detail)
    action = s.get(ActionRevision, detail["summary"]["revision_id"])
    assert action.content == flow.CONTENT and request.message not in str(action.payload)


def test_old_receipt_resolves_after_new_revision_and_disabled_gate(
    session, vendor_case, monkeypatch
):
    c = vendor_case
    s = session
    request = proposal(c)
    first = call(s, c, flow.propose, request)
    tid = first["effect"]["ticket_id"]
    d = call(s, c, flow.detail, tid)
    second = proposal(
        c,
        revises={
            "ticket_id": tid,
            "expected_version": d["summary"]["version"],
            "revision_id": d["summary"]["revision_id"],
            "payload_hash": d["summary"]["payload_hash"],
        },
        message="New explicitly reviewed message",
    )
    call(s, c, flow.propose, second)
    immediate(s)
    monkeypatch.setattr(settings, "vendor_work_enabled", False)
    recovered = call(
        s,
        c,
        flow.resolve,
        p.VendorResolve(
            command_kind="propose",
            idempotency_key=request.idempotency_key,
            request_sha256=first["request_sha256"],
        ),
    )
    assert recovered["effect"] == first["effect"] and recovered["summary"] == first["summary"]
    assert call(s, c, flow.propose, request)["effect"] == first["effect"]
    assert call(s, c, flow.detail, tid)["review"]["message"] == second.message


def test_multiple_vendor_origins_use_actual_same_notebook_revision(session, vendor_case):
    c = vendor_case
    s = session
    call(s, c, flow.propose, proposal(c))
    call(s, c, flow.propose, proposal(c))
    immediate(s)
    assert (
        s.scalar(
            select(func.count()).select_from(VendorWork).where(VendorWork.workspace_id == c["wid"])
        )
        == 2
    )
    assert s.get(EncounterWorkspace, c["wid"]).revision == 3


def test_known_private_credential_reference_rejected(session, vendor_case):
    c = vendor_case
    request = proposal(
        c, message="Never publish " + str(c["config"].private_selection["credential_ref"])
    )
    with pytest.raises(ws.WorkspaceError, match="vendor_credential_text_forbidden"):
        call(session, c, flow.propose, request)


def test_direct_close_and_action_mutation_fail_database(session, vendor_case):
    c = vendor_case
    s = session
    result = call(s, c, flow.propose, proposal(c))
    immediate(s)
    tid = result["effect"]["ticket_id"]
    with s.begin_nested():
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE tickets SET state='closed' WHERE id=:id"), {"id": tid})
            s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        s.rollback()


def approved(s, c):
    created = call(s, c, flow.propose, proposal(c))
    tid = created["effect"]["ticket_id"]
    d = call(s, c, flow.detail, tid)
    call(
        s,
        c,
        flow.decide,
        tid,
        p.VendorDecision(**bound(d, review_sha256=d["review_sha256"], choice="approve")),
    )
    return tid, call(s, c, flow.detail, tid)


def acceptance(invocation, state="accepted", response="f" * 64):
    command = invocation.command
    ref = private.ProviderReference(
        vendor="spruce",
        connection_id=command.selection.connection_id,
        environment="production",
        selection_sha256=command.selection.commitment(),
        operation_id=command.operation_id,
        request_sha256=command.commitment(),
        kind="async_request",
        value="invented_request",
        observed_at=datetime.now(UTC),
    )
    return private.SubmissionObservation(
        vendor="spruce",
        connection_id=command.selection.connection_id,
        operation_id=command.operation_id,
        request_sha256=command.commitment(),
        observed_at=datetime.now(UTC),
        state=state,
        reference=ref if state == "accepted" else None,
        safe_error=None if state == "accepted" else "provider_rejected",
        response_sha256=response,
    )


def test_submit_claim_commits_once_and_exact_resolution_never_invokes(
    session, vendor_case, monkeypatch
):
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    s = session
    c = vendor_case
    tid, d = approved(s, c)
    request = p.BoundCommand(**bound(d))
    receipt, invocation = call(s, c, execution.claim_submit, tid, request)
    immediate(s)
    assert invocation is not None and receipt["summary"]["effect"] == "submit_claimed"
    assert s.get(VendorSubmitClaim, invocation.operation_id) is not None
    assert s.get(Operation, invocation.operation_id).attempt_count == 1
    second, again = call(s, c, execution.claim_submit, tid, request)
    assert again is None and second["effect"] == receipt["effect"]
    fresh = p.BoundCommand(**bound(call(s, c, flow.detail, tid)))
    with pytest.raises(ws.WorkspaceError, match="vendor_submit_already_claimed"):
        call(s, c, execution.claim_submit, tid, fresh)
    resolved = call(
        s,
        c,
        flow.resolve,
        p.VendorResolve(
            command_kind="submit",
            idempotency_key=request.idempotency_key,
            request_sha256=receipt["request_sha256"],
        ),
    )
    assert resolved["effect"] == receipt["effect"]


def test_proved_predispatch_denial_is_spent_forever(session, vendor_case, monkeypatch):
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    s = session
    c = vendor_case
    tid, d = approved(s, c)
    _, invocation = call(s, c, execution.claim_submit, tid, p.BoundCommand(**bound(d)))
    execution.mark_invocation(s, invocation)
    execution.settle(s, invocation, failure=private.VendorError("authority_required"))
    immediate(s)
    d = call(s, c, flow.detail, tid)
    assert d["summary"]["dispatch"] == "proved_not_dispatched" and d["summary"]["submit_claimed"]
    assert not d["availability"]["submit"]["allowed"]
    with pytest.raises(ws.WorkspaceError, match="vendor_submit_already_claimed"):
        call(s, c, flow.withdraw, tid, p.BoundCommand(**bound(d)))


def test_trusted_late_acceptance_survives_owner_revocation_privately(
    session, vendor_case, monkeypatch
):
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    s = session
    c = vendor_case
    tid, d = approved(s, c)
    _, invocation = call(s, c, execution.claim_submit, tid, p.BoundCommand(**bound(d)))
    execution.mark_invocation(s, invocation)
    from cosmas_os.models import Principal

    actor = s.get(Principal, c["actor"])
    actor.state = "disabled"
    s.commit()
    execution.settle(s, invocation, observation=acceptance(invocation))
    immediate(s)
    assert s.get(Operation, invocation.operation_id).status == "succeeded"
    assert (
        s.scalar(
            select(func.count())
            .select_from(VendorProviderObservation)
            .where(VendorProviderObservation.operation_id == invocation.operation_id)
        )
        == 2
    )
    with pytest.raises(ws.WorkspaceError, match="workspace_access_denied"):
        call(s, c, flow.detail, tid)


def test_spruce_async_acceptance_does_not_invent_readable_item(session, vendor_case, monkeypatch):
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    s = session
    c = vendor_case
    tid, d = approved(s, c)
    _, invocation = call(s, c, execution.claim_submit, tid, p.BoundCommand(**bound(d)))
    execution.mark_invocation(s, invocation)
    execution.settle(s, invocation, observation=acceptance(invocation))
    immediate(s)
    with pytest.raises(ws.WorkspaceError, match="vendor_reference_unavailable"):
        call(s, c, execution.claim_read, tid, p.BoundCommand(**bound(call(s, c, flow.detail, tid))))


def test_unknown_transport_requires_owner_manual_result_before_verification(
    session, vendor_case, monkeypatch
):
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    s = session
    c = vendor_case
    tid, d = approved(s, c)
    _, invocation = call(s, c, execution.claim_submit, tid, p.BoundCommand(**bound(d)))
    execution.mark_invocation(s, invocation)
    execution.settle(
        s, invocation, failure=private.VendorError("transport_unconfirmed", attempted=True)
    )
    d = call(s, c, flow.detail, tid)
    request = p.VendorResult(
        **bound(
            d,
            observation_head=d["summary"]["observation_head"],
            evidence_sha256=d["summary"]["evidence_sha256"],
            disposition="reported_success",
            evidence="Invented staff report.",
        )
    )
    result = call(s, c, flow.record_result, tid, request)
    d = call(s, c, flow.detail, tid)
    verify = p.VendorVerify(
        **bound(
            d,
            result_receipt_id=result["effect"]["receipt_id"],
            result_receipt_sha256=result["effect"]["receipt_sha256"],
            observation_head=d["summary"]["observation_head"],
            evidence_sha256=d["summary"]["evidence_sha256"],
            reviewed_result=True,
            reviewed_observations=True,
            outcome_confirmed=True,
            reviewed_conflicting_evidence=False,
        )
    )
    with pytest.raises(ws.WorkspaceError, match="vendor_exception_unresolved"):
        call(s, c, flow.verify, tid, verify)
    d = call(s, c, flow.detail, tid)
    manual = p.VendorResult(
        **bound(
            d,
            observation_head=d["summary"]["observation_head"],
            evidence_sha256=d["summary"]["evidence_sha256"],
            disposition="verified_in_vendor",
            evidence="Owner checked invented vendor record and outcome.",
        )
    )
    result = call(s, c, flow.record_result, tid, manual)
    d = call(s, c, flow.detail, tid)
    verify = p.VendorVerify(
        **bound(
            d,
            result_receipt_id=result["effect"]["receipt_id"],
            result_receipt_sha256=result["effect"]["receipt_sha256"],
            observation_head=d["summary"]["observation_head"],
            evidence_sha256=d["summary"]["evidence_sha256"],
            reviewed_result=True,
            reviewed_observations=True,
            outcome_confirmed=True,
            reviewed_conflicting_evidence=False,
        )
    )
    call(s, c, flow.verify, tid, verify)
    immediate(s)
    assert call(s, c, flow.detail, tid)["summary"]["state"] == "closed"


def test_staff_publication_is_revision_scoped_and_has_no_private_review(session, vendor_case):
    from cosmas_os.models import Principal

    c = vendor_case
    s = session
    colleague = Principal(
        box_id=c["box"],
        principal_type="human",
        display_name="Invented accepted colleague",
        state="active",
    )
    outsider = Principal(
        box_id=c["box"],
        principal_type="human",
        display_name="Invented unrelated colleague",
        state="active",
    )
    s.add_all([colleague, outsider])
    s.commit()
    request = proposal(c, share_to_practice=True)
    receipt = call(s, c, flow.propose, request)
    tid = receipt["effect"]["ticket_id"]
    d = call(s, c, flow.detail, tid)
    call(
        s,
        c,
        flow.decide,
        tid,
        p.VendorDecision(**bound(d, review_sha256=d["review_sha256"], choice="approve")),
    )
    d = call(s, c, flow.detail, tid)
    offer = p.VendorHandoff(
        expected_version=d["summary"]["version"],
        revision_id=d["summary"]["revision_id"],
        payload_hash=d["summary"]["payload_hash"],
        idempotency_key="offer-" + str(uuid4()),
        kind="offer",
        recipient_id=colleague.id,
    )
    vendor_shared.handoff(s, c["box"], c["actor"], tid, offer)
    shared = vendor_shared.read(s, c["box"], colleague.id, tid)
    assert (
        "review" not in shared and "source" not in shared and "invented_contact" not in str(shared)
    )
    assert request.message not in str(shared) and shared["pending_offer"] is not None
    accept = p.VendorHandoff(
        expected_version=shared["version"],
        revision_id=shared["revision_id"],
        payload_hash=shared["payload_hash"],
        idempotency_key="accept-" + str(uuid4()),
        kind="accept",
        offer_id=shared["pending_offer"]["id"],
    )
    accepted = vendor_shared.handoff(s, c["box"], colleague.id, tid, accept)
    shared = vendor_shared.read(s, c["box"], colleague.id, tid)
    assert shared["responsible"]["id"] == colleague.id
    with pytest.raises(ws.WorkspaceError, match="vendor_work_unavailable"):
        vendor_shared.read(s, c["box"], outsider.id, tid)
    d = call(s, c, flow.detail, tid)
    call(
        s,
        c,
        flow.propose,
        proposal(
            c,
            message="Later private text",
            revises={
                "ticket_id": tid,
                "expected_version": d["summary"]["version"],
                "revision_id": d["summary"]["revision_id"],
                "payload_hash": d["summary"]["payload_hash"],
            },
        ),
    )
    immediate(s)
    historical = vendor_shared.read(s, c["box"], colleague.id, tid)
    assert historical["historical"] and historical["revision_id"] == shared["revision_id"]
    assert "Later private text" not in str(historical)
    recovered = vendor_shared.resolve(
        s,
        c["box"],
        colleague.id,
        tid,
        p.VendorStaffResolve(
            command_kind="handoff",
            idempotency_key=accept.idempotency_key,
            request_sha256=accepted["request_sha256"],
        ),
    )
    assert recovered["effect"] == accepted["effect"]
    with pytest.raises(ws.WorkspaceError, match="vendor_revision_changed"):
        vendor_shared.handoff(
            s,
            c["box"],
            colleague.id,
            tid,
            p.VendorHandoff(
                expected_version=historical["version"],
                revision_id=historical["revision_id"],
                payload_hash=historical["payload_hash"],
                idempotency_key="new-offer-" + str(uuid4()),
                kind="offer",
                recipient_id=outsider.id,
            ),
        )
