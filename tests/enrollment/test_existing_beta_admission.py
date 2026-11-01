"""Existing synthetic beta users retain local authority during enrollment changes."""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event, func, select
from tests.unit.test_practice_access import case as _practice_case
from tests.unit.test_practice_access import verifier

from cosmas_os.adapters.enrollment_admission import (
    ACCESS_REQUIRED,
    ADMISSION_UNAVAILABLE,
    PUBLIC_ADMISSION_HEADER,
    PUBLIC_ENROLLMENT_USER_HEADER,
    EnrollmentAdmissionAdapter,
)
from cosmas_os.api import app as api
from cosmas_os.api import practice_access_routes
from cosmas_os.application import (
    conversation,
    enrollment_existing_user,
    handoffs,
    practice_access,
    provider_team,
    workspace,
)
from cosmas_os.application.enrollment_existing_user import EXISTING_USER_CUTOVER
from cosmas_os.enrollment import domain, service
from cosmas_os.enrollment.admission import (
    ADMISSION_HEADER,
    MAX_AGE_SECONDS,
    AdmissionRequest,
    encode,
    signature,
)
from cosmas_os.model_registry import metadata
from cosmas_os.models import (
    AuditEvent,
    BoxContext,
    EncounterWorkspace,
    ExternalIdentity,
    Principal,
    WorkspaceEntry,
)
from cosmas_os.practice_access_models import PracticeAccessRequest
from cosmas_os.practice_setup_models import PracticeSetupProfile

practice_case = _practice_case


@pytest.fixture
def existing_beta(practice_case, monkeypatch):
    c = practice_case
    # The existing fixture owns a private PostgreSQL schema and supports real,
    # independent transactions. No hosted database or identity service is used.
    metadata.create_all(c.engine)
    c.config = c.config.model_copy(update={
        "workspace_enrollment_managed": True,
        "workspace_enrollment_practice_id": str(uuid4()),
        "workspace_enrollment_api_origin": "https://enrollment.example.invalid",
        "workspace_enrollment_account_origin": "https://app.example.invalid",
        "workspace_enrollment_origin_allowlist": "https://enrollment.example.invalid,https://app.example.invalid",
        "workspace_enrollment_admission_secret": SecretStr("c" * 64),
        "workspace_release_source_commit": "a" * 40,
        "workspace_release_image_sha256": "b" * 64,
    })
    assert c.config.runtime_configuration_errors() == []
    with c.factory.begin() as session:
        binding = session.scalar(select(ExternalIdentity).where(
            ExternalIdentity.subject == c.owner.subject))
        binding.created_at = EXISTING_USER_CUTOVER - timedelta(days=1)
        binding_id = binding.id
    with c.factory() as session:
        draft = workspace.create_private_draft(session, c.config.beta_box_id,
            c.owner_id, "Invented retained beta notebook", str(uuid4()))

    state = SimpleNamespace(mode="outage", http_calls=[], before_commit=None)
    key = c.config.workspace_enrollment_admission_secret.get_secret_value()

    def transport(request):
        state.http_calls.append(request.url.path)
        if state.mode == "outage":
            raise httpx.ReadTimeout("Invented enrollment outage", request=request)
        assert state.mode == "agreement"
        command = AdmissionRequest.model_validate_json(request.content)
        now = int(time.time())
        value = {**command.model_dump(exclude={"issued_at", "token_sha256"}),
            "request_issued_at": command.issued_at,
            "request_sha256": hashlib.sha256(request.content).hexdigest(),
            "decision": "deny", "reason": "agreement_required",
            "issued_at": now, "expires_at": now + MAX_AGE_SECONDS,
            "member_role": None, "display_name": None}
        raw = encode(value)
        return httpx.Response(200, content=raw, headers={
            "Content-Type": "application/json", "Cache-Control": "no-store",
            ADMISSION_HEADER: signature(key, raw, direction="response", nonce=command.nonce)})

    checked, token = verifier(c)
    with httpx.Client(transport=httpx.MockTransport(transport)) as control_client:
        adapter = EnrollmentAdmissionAdapter(c.config, client=control_client)
        adapter.authorize = Mock(wraps=adapter.authorize)
        monkeypatch.setattr(api, "settings", c.config)
        monkeypatch.setattr(api, "SessionLocal", c.factory)
        monkeypatch.setattr(api, "_clerk_verifier", lambda *_args: checked)
        monkeypatch.setattr(api, "_runtime_admission_adapter", lambda: adapter)
        for module in (provider_team, conversation, handoffs):
            monkeypatch.setattr(module, "runtime_settings", c.config)

        def get_session():
            with c.factory() as session:
                if state.before_commit is not None:
                    event.listen(session, "before_commit", state.before_commit, once=True)
                yield session

        api.app.dependency_overrides[api.get_session] = get_session
        headers = {"Authorization": "Bearer " + token(c.owner),
            "X-Cosmas-Draft-Recovery": "2", "X-Cosmas-Workspace-Protocol": "1",
            "X-Cosmas-Team-Contract": "2", "X-Cosmas-Model-Contract": "1",
            "X-Cosmas-Private-Draft": "1", "X-Cosmas-Practice-Access-Contract": "1"}
        try:
            with TestClient(api.app) as client:
                yield SimpleNamespace(case=c, client=client, headers=headers, token=token,
                    draft=draft, binding_id=binding_id, adapter=adapter, state=state)
        finally:
            api.app.dependency_overrides.pop(api.get_session, None)


def assert_no_enrollment_gate(response):
    assert PUBLIC_ADMISSION_HEADER not in response.headers
    assert PUBLIC_ENROLLMENT_USER_HEADER not in response.headers
    assert response.headers["cache-control"] == "no-store"


def note_body(f, content):
    return {"expected_revision": f.draft["revision"], "idempotency_key": str(uuid4()),
            "kind": "scratchpad", "content": content}


@pytest.mark.parametrize("change", ["outage", "agreement"])
def test_existing_beta_chief_workspace_and_practice_stay_available(existing_beta, monkeypatch, change):
    f = existing_beta
    f.state.mode = change
    if change == "agreement":
        for module in (domain, service):
            monkeypatch.setattr(module, "BAA_VERSION", "invented-next-agreement")
            monkeypatch.setattr(module, "BAA_SHA256", "d" * 64)
    for path in ("/provider-team", "/workspaces", "/workspaces/" + f.draft["id"],
                 "/account/identity", "/practice-access", "/practice-access/enrollment-qualification"):
        response = f.client.get(path, headers=f.headers)
        assert response.status_code == 200, (path, response.text)
        assert_no_enrollment_gate(response)
        assert "enrollment_admission" not in response.json()
    response = f.client.post("/practice-access/request", headers=f.headers,
        json={"idempotency_key": str(uuid4()), "display_name": "Invented existing owner"})
    assert response.status_code == 200 and response.json()["state"] == "connected", response.text
    assert_no_enrollment_gate(response)
    note = "Invented existing beta note during " + change
    response = f.client.post("/workspaces/" + f.draft["id"] + "/entries",
        headers=f.headers, json=note_body(f, note))
    assert response.status_code == 200, response.text
    assert_no_enrollment_gate(response)
    with f.case.factory() as session:
        assert session.scalar(select(WorkspaceEntry.content).where(
            WorkspaceEntry.workspace_id == f.draft["id"])) == note
        assert session.scalar(select(func.count()).select_from(PracticeAccessRequest)) == 0
        assert session.scalar(select(func.count()).select_from(Principal)) == 1
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
    f.adapter.authorize.assert_not_called()
    assert f.state.http_calls == []


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("change,status,code", [
    ("outage", 503, ADMISSION_UNAVAILABLE), ("agreement", 403, ACCESS_REQUIRED)])
def test_new_user_still_requires_enrollment_with_recovery_headers(existing_beta, bound, change, status, code):
    f = existing_beta
    f.state.mode = change
    if bound:
        with f.case.factory.begin() as session:
            person = Principal(box_id=f.case.config.beta_box_id, principal_type="human",
                state="active", display_name="Invented new teammate")
            session.add(person)
            session.flush()
            session.add(ExternalIdentity(box_id=person.box_id, principal_id=person.id,
                issuer=f.case.config.clerk_issuer, organization_id=f.case.config.clerk_organization_id,
                subject=f.case.applicant.subject, active=True,
                reviewed_by="Synthetic fixture", evidence_ref="invented:new-beta-user"))
    headers = {**f.headers, "Authorization": "Bearer " + f.token(f.case.applicant)}
    for path in ("/provider-team", "/workspaces/" + f.draft["id"],
                 "/account/identity", "/practice-access", "/practice-access/enrollment-qualification"):
        response = f.client.get(path, headers=headers)
        assert response.status_code == status, (path, response.text)
        assert response.headers[PUBLIC_ADMISSION_HEADER] == code
        assert response.headers[PUBLIC_ENROLLMENT_USER_HEADER] == "new"
        assert response.headers["cache-control"] == "no-store"
    assert f.adapter.authorize.call_count == 5 and len(f.state.http_calls) == 5
    with f.case.factory() as session:
        assert session.scalar(select(func.count()).select_from(Principal)) == (2 if bound else 1)
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == (2 if bound else 1)
        assert session.scalar(select(func.count()).select_from(WorkspaceEntry)) == 0
        assert session.scalar(select(func.count()).select_from(PracticeAccessRequest)) == 0


@pytest.mark.parametrize("change", ["inactive", "organization", "provider", "box"])
def test_revoked_existing_binding_denies_locally_without_enrollment(existing_beta, change):
    f = existing_beta
    with f.case.factory.begin() as session:
        binding = session.get(ExternalIdentity, f.binding_id)
        if change == "inactive":
            binding.active = False
        elif change == "organization":
            binding.organization_id = "org_invented_other"
        elif change == "provider":
            binding.provider = "invented_other_provider"
        else:
            # Preserve real composite FK constraints while moving the saved
            # identity outside this configured Box. No remapping is repaired.
            other_box = BoxContext(display_name="Invented other practice")
            session.add(other_box)
            session.flush()
            other_person = Principal(box_id=other_box.id, principal_type="human",
                state="active", display_name="Invented other local human")
            session.add(other_person)
            session.flush()
            binding.box_id, binding.principal_id = other_box.id, other_person.id
    for path in ("/provider-team", "/workspaces/" + f.draft["id"], "/practice-access"):
        response = f.client.get(path, headers=f.headers)
        assert response.status_code == 403, (path, response.text)
        assert_no_enrollment_gate(response)
    f.adapter.authorize.assert_not_called()
    assert f.state.http_calls == []


def test_existing_beta_commit_fence_rechecks_local_revocation_without_enrollment(existing_beta):
    f = existing_beta
    revocations = []

    def revoke_before_commit(_current):
        # A real independent commit changes local authority after authentication,
        # before this request's fence. Enrollment remains unavailable throughout.
        with f.case.factory.begin() as session:
            session.get(ExternalIdentity, f.binding_id).active = False
        revocations.append(True)

    f.state.before_commit = revoke_before_commit
    response = f.client.post("/workspaces/" + f.draft["id"] + "/entries", headers=f.headers,
        json=note_body(f, "Invented note that must roll back after local revocation"))
    assert response.status_code == 403, response.text
    assert_no_enrollment_gate(response)
    assert revocations == [True]
    with f.case.factory() as session:
        assert session.get(ExternalIdentity, f.binding_id).active is False
        assert session.get(EncounterWorkspace, f.draft["id"]).revision == f.draft["revision"]
        assert session.scalar(select(func.count()).select_from(WorkspaceEntry)) == 0
    f.adapter.authorize.assert_not_called()
    assert f.state.http_calls == []


@pytest.mark.parametrize("phase", ["initial_classification", "first_scope_fence"])
@pytest.mark.parametrize("revocation", ["disable_human", "remove_binding", "remap_binding"])
def test_old_box_existing_practice_fence_retains_classification_and_denies_revocation_locally(
    existing_beta, monkeypatch, phase, revocation
):
    f = existing_beta
    # Only the active already-bound human in an old Box qualifies initially.
    # Binding/principal dates, profile, approval and agreement cannot carry it.
    with f.case.factory.begin() as session:
        session.get(BoxContext, f.case.config.beta_box_id).created_at = EXISTING_USER_CUTOVER - timedelta(days=1)
        session.get(Principal, f.case.owner_id).created_at = EXISTING_USER_CUTOVER + timedelta(days=1)
        session.get(ExternalIdentity, f.binding_id).created_at = EXISTING_USER_CUTOVER + timedelta(days=1)
    with f.case.factory() as session:
        assert session.scalar(select(func.count()).select_from(PracticeSetupProfile)) == 0
        assert session.scalar(select(func.count()).select_from(PracticeAccessRequest)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.event_type == "cosmaneura.agreement.accepted")) == 0
        before_audit = session.scalar(select(func.count()).select_from(AuditEvent))
        assert enrollment_existing_user.is_existing_user(session, f.case.config, f.case.owner.subject)

    revocations, classifier_calls, remapped_ids = [], [], []
    actual_classifier = enrollment_existing_user.is_existing_user

    def revoke_in_independent_transaction():
        def commit_revocation():
            with f.case.factory.begin() as session:
                if revocation == "disable_human":
                    session.get(Principal, f.case.owner_id).state = "disabled"
                elif revocation == "remove_binding":
                    session.delete(session.get(ExternalIdentity, f.binding_id))
                else:
                    replacement = Principal(box_id=f.case.config.beta_box_id,
                        principal_type="human", state="active", display_name="Invented replacement human",
                        created_at=EXISTING_USER_CUTOVER + timedelta(days=1))
                    session.add(replacement)
                    session.flush()
                    session.get(ExternalIdentity, f.binding_id).principal_id = replacement.id
                    remapped_ids.append(replacement.id)
            revocations.append(True)
        # The real request remains live while a different thread/transaction
        # commits the revocation; no registry failure or authority is faked.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(commit_revocation).result(timeout=5)

    def classify(*args, **kwargs):
        result = actual_classifier(*args, **kwargs)
        classifier_calls.append(result)
        if phase == "initial_classification" and result and not revocations:
            revoke_in_independent_transaction()
        return result

    monkeypatch.setattr(enrollment_existing_user, "is_existing_user", classify)
    operation = practice_access.status

    def status_after_revocation(*args, **kwargs):
        if phase == "first_scope_fence":
            revoke_in_independent_transaction()
        return operation(*args, **kwargs)

    monkeypatch.setitem(practice_access_routes.PATHS, "/practice-access",
        ("GET", None, status_after_revocation))
    response = f.client.get("/practice-access", headers=f.headers)
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "practice_access_denied"}
    assert_no_enrollment_gate(response)
    assert revocations == [True] and classifier_calls == [True]
    f.adapter.authorize.assert_not_called()
    assert f.state.http_calls == []
    with f.case.factory() as session:
        assert session.get(EncounterWorkspace, f.draft["id"]).revision == f.draft["revision"]
        assert session.scalar(select(func.count()).select_from(WorkspaceEntry)) == 0
        assert session.scalar(select(func.count()).select_from(PracticeAccessRequest)) == 0
        assert session.scalar(select(func.count()).select_from(PracticeSetupProfile)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == before_audit
        assert session.scalar(select(func.count()).select_from(Principal)) == (2 if revocation == "remap_binding" else 1)
        if revocation == "disable_human":
            assert session.get(Principal, f.case.owner_id).state == "disabled"
            assert session.get(ExternalIdentity, f.binding_id).active is True
        elif revocation == "remove_binding":
            assert session.get(ExternalIdentity, f.binding_id) is None
        else:
            assert session.get(ExternalIdentity, f.binding_id).principal_id == remapped_ids[0]
            assert session.get(Principal, remapped_ids[0]).is_owner is False


@pytest.mark.parametrize("is_owner", [False, True])
def test_canonical_checked_existing_setup_keeps_original_local_owner_authority(
    existing_beta, monkeypatch, is_owner
):
    f = existing_beta
    with f.case.factory.begin() as session:
        session.get(Principal, f.case.owner_id).is_owner = is_owner
    # Exercise the canonical helper's own history decision after the optional
    # preliminary lookup misses. No browser flag or fabricated allow is used.
    monkeypatch.setattr(practice_access_routes, "existing_user_admission", lambda *_: None)
    classifier = Mock(wraps=enrollment_existing_user.is_existing_user)
    monkeypatch.setattr(enrollment_existing_user, "is_existing_user", classifier)
    response = f.client.post("/practice-access/setup/complete", headers=f.headers, json={
        "idempotency_key": str(uuid4()), "display_name": "Invented existing human",
        "practice_name": "Invented retained practice", "specialty": None, "confirm": True})
    assert response.status_code == (200 if is_owner else 403), response.text
    assert_no_enrollment_gate(response)
    assert "enrollment_admission" not in response.json()
    if is_owner:
        assert response.json()["state"] == "owner_ready"
    else:
        assert response.json() == {"detail": "practice_access_denied"}
    classifier.assert_called_once()
    f.adapter.authorize.assert_not_called()
    assert f.state.http_calls == []
    with f.case.factory() as session:
        assert session.get(Principal, f.case.owner_id).is_owner is is_owner
        assert session.scalar(select(func.count()).select_from(Principal)) == 1
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
        assert session.scalar(select(func.count()).select_from(PracticeAccessRequest)) == 0
        assert session.scalar(select(func.count()).select_from(WorkspaceEntry)) == 0
        profile = session.get(PracticeSetupProfile, f.case.config.beta_box_id)
        assert (profile is not None) is is_owner
        if profile is not None:
            assert profile.owner_id == f.case.owner_id
