"""Saved beta history survives enrollment/BAA changes without inventing membership."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.enrollment.test_journey import accepted, enrolled, mutate, ready_checkout, signed, status

from cosmas_os.adapters.enrollment_admission import RuntimeAdmissionError
from cosmas_os.application.enrollment_access import prepare_registered_member
from cosmas_os.application.enrollment_existing_user import EXISTING_USER_CUTOVER, is_existing_user
from cosmas_os.enrollment import service as enrollment_service
from cosmas_os.enrollment.synthetic import create_synthetic_app
from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, Principal
from cosmas_os.practice_access_models import PracticeAccessRequest
from cosmas_os.practice_setup_models import PracticeSetupProfile

BEFORE = EXISTING_USER_CUTOVER - timedelta(seconds=1)
AFTER = EXISTING_USER_CUTOVER + timedelta(seconds=1)
SUBJECT = "user_invented_existing"


def member(session, *, binding_at=AFTER, box_at=AFTER, person_at=AFTER, bound=True):
    box = BoxContext(id=str(uuid4()), display_name="Invented practice", created_at=box_at)
    person = Principal(id=str(uuid4()), box_id=box.id, principal_type="human", state="active",
                       is_owner=True, display_name="Invented owner", created_at=person_at)
    session.add_all([box, person])
    session.flush()
    runtime = SimpleNamespace(beta_box_id=box.id, clerk_issuer="https://issuer.example.invalid",
                              clerk_organization_id="org_invented")
    binding = None
    if bound:
        binding = ExternalIdentity(box_id=box.id, principal_id=person.id, provider="clerk",
            issuer=runtime.clerk_issuer, subject=SUBJECT, organization_id=runtime.clerk_organization_id,
            active=True, reviewed_by="Invented owner", evidence_ref="synthetic:review", created_at=binding_at)
        session.add(binding)
        session.flush()
    return runtime, person, binding


def profile(session, runtime, owner, completed_at=BEFORE):
    session.add(PracticeSetupProfile(box_id=runtime.beta_box_id, owner_id=owner.id,
        display_name="Invented practice", owner_display_name=owner.display_name,
        request_key=str(uuid4()), request_sha256="a" * 64, completed_at=completed_at))
    session.flush()


def approval(session, runtime, person, *, state="approved", decided_at=BEFORE, created_at=BEFORE):
    row = PracticeAccessRequest(id=str(uuid4()), box_id=runtime.beta_box_id,
        issuer=runtime.clerk_issuer, organization_id=runtime.clerk_organization_id, subject=SUBJECT,
        request_key=str(uuid4()), display_name=person.display_name, review_sha256="a" * 64,
        state=state, created_at=created_at, expires_at=AFTER + timedelta(days=1),
        decided_at=decided_at if state != "pending" else None,
        decided_by=person.id if state in {"approved", "declined"} else None)
    session.add(row)
    session.flush()
    return row


def agreement(session, runtime, actor, *, created_at=BEFORE, **detail):
    row = AuditEvent(box_id=runtime.beta_box_id, aggregate_type="agreement", aggregate_id=str(uuid4()),
        event_type="cosmaneura.agreement.accepted", actor_principal_id=actor.id, outcome="accepted",
        detail={"issuer": runtime.clerk_issuer, "subject": SUBJECT,
                "organization_id": runtime.clerk_organization_id, "doc_id": "CN-BAA-CUST-CW",
                "version": "2.2", **detail}, created_at=created_at)
    session.add(row)
    session.flush()
    return row


def test_prior_identity_retains_history_without_reactivation(session):
    runtime, person, binding = member(session, binding_at=BEFORE)
    assert binding is not None
    binding.active = False
    person.state = "paused"
    session.flush()
    assert is_existing_user(session, runtime, SUBJECT) is True
    assert binding.active is False and person.state == "paused"


def test_active_bound_human_in_old_box_is_existing_even_with_newer_principal(session):
    runtime, _, _ = member(session, box_at=BEFORE)
    assert is_existing_user(session, runtime, SUBJECT) is True


def test_unknown_subject_in_old_box_does_not_inherit_existing_owner_profile(session):
    runtime, owner, _ = member(session, box_at=BEFORE, bound=False)
    profile(session, runtime, owner)
    assert is_existing_user(session, runtime, SUBJECT) is False


def test_old_owned_profile_is_independent_of_principal_and_binding_creation(session):
    runtime, person, _ = member(session)
    profile(session, runtime, person)
    assert is_existing_user(session, runtime, SUBJECT) is True


@pytest.mark.parametrize("criterion", ["binding", "box", "profile", "approval"])
def test_cutover_is_exclusive_and_fixed_for_each_temporal_criterion(session, criterion, monkeypatch):
    runtime, person, _ = member(session,
        binding_at=EXISTING_USER_CUTOVER if criterion == "binding" else AFTER,
        box_at=EXISTING_USER_CUTOVER if criterion == "box" else AFTER)
    if criterion == "profile":
        profile(session, runtime, person, EXISTING_USER_CUTOVER)
    if criterion == "approval":
        approval(session, runtime, person, decided_at=EXISTING_USER_CUTOVER)
    runtime.existing_user = True
    monkeypatch.setenv("ENROLLMENT_EXISTING_USER_CUTOVER", "2099-01-01T00:00:00Z")
    assert is_existing_user(session, runtime, SUBJECT) is False


@pytest.mark.parametrize("field", ["issuer", "organization", "box", "subject", "principal", "agent"])
def test_existing_identity_requires_exact_verified_scope_and_human(session, field):
    runtime, person, _ = member(session, binding_at=BEFORE)
    subject, principal_id = SUBJECT, None
    if field == "issuer":
        runtime.clerk_issuer = "https://other.example.invalid"
    elif field == "organization":
        runtime.clerk_organization_id = "org_other"
    elif field == "box":
        runtime.beta_box_id = str(uuid4())
    elif field == "subject":
        subject = "user_other"
    elif field == "principal":
        principal_id = str(uuid4())
    else:
        person.principal_type = "agent"
        session.flush()
    assert is_existing_user(session, runtime, subject, principal_id) is False


@pytest.mark.parametrize("bound", [False, True])
def test_prior_approved_membership_is_independent_of_later_binding(session, bound):
    runtime, person, _ = member(session, bound=bound)
    approval(session, runtime, person, created_at=AFTER)
    assert is_existing_user(session, runtime, SUBJECT) is True


@pytest.mark.parametrize("case", ["pending", "declined", "late", "issuer", "subject", "organization"])
def test_membership_must_be_approved_before_cutover_for_exact_identity(session, case):
    runtime, person, _ = member(session)
    row = approval(session, runtime, person,
        state=case if case in {"pending", "declined"} else "approved",
        decided_at=AFTER if case == "late" else BEFORE)
    if case == "issuer":
        row.issuer = "https://other.example.invalid"
    elif case == "subject":
        row.subject = "user_other"
    elif case == "organization":
        row.organization_id = "org_other"
    session.flush()
    assert is_existing_user(session, runtime, SUBJECT) is False


@pytest.mark.parametrize("bound,recorded_at", [(False, BEFORE), (True, BEFORE), (False, AFTER)])
def test_legacy_agreement_is_independent_of_binding_and_recording_time(session, bound, recorded_at):
    runtime, person, _ = member(session, bound=bound)
    agreement(session, runtime, person, created_at=recorded_at)
    assert is_existing_user(session, runtime, SUBJECT) is True
    assert is_existing_user(session, runtime, SUBJECT, principal_id=person.id) is True
    assert is_existing_user(session, runtime, SUBJECT, principal_id=str(uuid4())) is False


@pytest.mark.parametrize("case", ["issuer", "subject", "organization_id", "doc_id", "version", "event_type", "outcome", "agent"])
def test_legacy_agreement_needs_scoped_executed_human_evidence(session, case):
    runtime, person, _ = member(session, bound=False)
    changed = {case: "" if case == "version" else "other"} if case in {"issuer", "subject", "organization_id", "doc_id", "version"} else {}
    row = agreement(session, runtime, person)
    row.detail = {**row.detail, **changed}
    if case == "event_type":
        row.event_type = "agreement.proposed"
    elif case == "outcome":
        row.outcome = "pending"
    elif case == "agent":
        person.principal_type = "agent"
    session.flush()
    assert is_existing_user(session, runtime, SUBJECT) is False


def test_classification_does_not_flush_pending_new_principals(session):
    runtime, _, _ = member(session)
    pending = Principal(id=str(uuid4()), box_id=runtime.beta_box_id, principal_type="human",
                        display_name="Pending invented human", state="active", created_at=BEFORE)
    session.add(pending)
    assert is_existing_user(session, runtime, SUBJECT) is False
    assert pending in session.new


def test_only_server_existing_marker_skips_member_provisioning():
    runtime = SimpleNamespace(workspace_enrollment_managed=True, workspace_enrollment_practice_id="invented")
    def fence():
        raise AssertionError("Existing history must not create a registry binding")
    prepare_registered_member(object(), runtime, object(),
        {"decision": "allow", "existing_user": True, "enforced": False}, fence=fence)
    with pytest.raises(RuntimeAdmissionError):
        prepare_registered_member(object(), runtime, object(),
            {"decision": "allow", "existing_user": True, "enforced": True}, fence=fence)


@pytest.fixture
def lab():
    app = create_synthetic_app()
    try:
        with TestClient(app) as client:
            yield app, client
    finally:
        app.state.enrollment_service.sessions.kw["bind"].dispose()


def offer_new_baa(monkeypatch):
    monkeypatch.setattr(enrollment_service, "BAA_VERSION", "2.4")
    monkeypatch.setattr(enrollment_service, "BAA_SHA256", "f" * 64)


def test_executed_baa_version_hash_receipt_and_ready_state_survive_new_offer(lab, monkeypatch):
    _, client = lab
    headers = signed(client)
    ready_checkout(client, headers)
    assert client.post("/lab/checkout/complete", json={"session_id": "cs_synthetic1"}).status_code == 200
    before = status(client, headers)
    receipt = client.get("/enrollment/v1/baa/receipt", headers=headers).json()
    assert before["stage"] == "ready"
    offer_new_baa(monkeypatch)
    after = status(client, headers)
    assert after["stage"] == "ready" and after["agreement"] == before["agreement"]
    assert after["billing"] == before["billing"]
    assert client.get("/enrollment/v1/baa/receipt", headers=headers).json() == receipt
    other = signed(client, "owner-b")
    fresh = enrolled(client, other)
    assert fresh["stage"] == "agreement" and fresh["agreement"]["accepted"] is False
    assert fresh["agreement"]["version"] == "2.4" and fresh["agreement"]["sha256"] == "f" * 64
    old = receipt["receipt"]
    assert mutate(client, other, "/baa/accept", {"doc_id": old["doc_id"], "version": old["version"],
        "sha256": old["sha256"], "signature_name": "Invented owner", "signature_title": "Owner",
        "accepted": True, "authority_confirmed": True}).status_code == 409


@pytest.mark.parametrize("missing", [False, True])
def test_unavailable_archive_never_resets_executed_agreement(lab, monkeypatch, tmp_path, missing):
    _, client = lab
    headers = signed(client)
    before = accepted(client, headers)
    archive = tmp_path / "unavailable-archive.html"
    if not missing:
        archive.write_text("Changed invented archive")
    monkeypatch.setattr(enrollment_service, "_BAA_V23_ARCHIVE", archive)
    offer_new_baa(monkeypatch)
    response = client.get("/enrollment/v1/baa/receipt", headers=headers)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "enrollment_agreement_archive_unavailable"
    assert status(client, headers)["agreement"] == before["agreement"]
