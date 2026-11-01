"""Direct runtime HTTP/worker journeys on an isolated PostgreSQL workspace."""
from __future__ import annotations

import hashlib
import os
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from tests.enrollment.test_runtime_admission import activate
from tests.enrollment.test_runtime_admission import admission_case as _admission_case
from tests.helpers.task_brief import REQUIREMENTS

from cosmas_os.adapters.enrollment_admission import ACCESS_REQUIRED
from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import conversation, handoffs, model_work, provider_team
from cosmas_os.application.beta_bootstrap import BetaBootstrapManifest
from cosmas_os.application.practice_setup import reserve_first_owner
from cosmas_os.enrollment.models import Practice
from cosmas_os.model_registry import metadata
from cosmas_os.models import (
    EncounterWorkspace,
    ExternalIdentity,
    ModelWorkAdmission,
    Principal,
    WorkspaceReply,
)
from cosmas_os.ports.bot_capabilities import BotReply, DraftBrief

admission_case = _admission_case
URL = os.environ.get("ENROLLMENT_RUNTIME_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="Isolated runtime PostgreSQL rehearsal was not provided")


@pytest.fixture
def runtime_engine():
    engine = create_engine(URL, pool_pre_ping=True)
    assert engine.url.host == "127.0.0.1" and engine.url.database == "enrollment_runtime_synthetic"
    cfg = Config("alembic.ini")
    cfg.attributes["configure_logger"] = False
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def runtime_case(admission_case, monkeypatch, runtime_engine):
    c = admission_case
    engine = runtime_engine
    with engine.begin() as connection:
        tables = ",".join(engine.dialect.identifier_preparer.format_table(table) for table in metadata.sorted_tables)
        connection.exec_driver_sql("TRUNCATE TABLE " + tables + " RESTART IDENTITY CASCADE")
    sessions = sessionmaker(engine, expire_on_commit=False)
    # Deployment settings remain hosted-shaped; the injected session factory
    # below exclusively uses this test's temporary migrated loopback database.
    runtime = c.runtime.model_copy(update={"database_url": "postgresql+psycopg://synthetic:invented@db.example.invalid:5432/cosmas_os?sslmode=verify-full&sslrootcert=system",
        "redis_url": "rediss://:invented@redis.example.invalid:6380/0?ssl_cert_reqs=required", "workspace_enabled": True, "workspace_authenticated_enabled": True,
        "workspace_hosted_enabled": True, "workspace_team_setup_enabled": True, "synth_seed": False, "sync_worker": False,
        "clerk_jwks_url": c.issuer + "/.well-known/jwks.json", "clerk_authorized_parties": "https://app.example.invalid",
        "cors_allowed_origins": "https://app.example.invalid", "blob_backend": "azure", "azure_storage_account_url": "https://storage.example.invalid",
        "azure_blob_container": "invented-container", "human_deploy_evidence_ref": "synthetic:release", "workspace_release_source_commit": "a" * 40,
        "workspace_release_image_sha256": "b" * 64})
    assert runtime.runtime_configuration_errors() == [], " | ".join(runtime.runtime_configuration_errors())
    manifest = BetaBootstrapManifest.model_validate({"schema_version": "cosmas-os/d3-beta-bootstrap/v1",
        "box_id": c.box_id, "clinic_display_name": "Example Practice", "owner_display_name": "Alex Example",
        "clerk_issuer": c.issuer, "clerk_subject": "user_synthetic_owner-a", "clerk_organization_id": c.org,
        "reviewed_by": "Synthetic operator", "evidence_ref": runtime.human_deploy_evidence_ref})
    with sessions() as session:
        reserve_first_owner(session, runtime, manifest)
    identities = c.app.state.synthetic_identities
    class Keys:
        def get_signing_keys(self, refresh):
            return [SimpleNamespace(key_id=jwt.get_unverified_header(c.token)["kid"], key=identities.key.public_key())]
    verifier = ClerkTokenVerifier(runtime, jwks_client=Keys(), start_background_refresh=False)
    monkeypatch.setattr(api, "settings", runtime)
    monkeypatch.setattr(api, "SessionLocal", sessions)
    monkeypatch.setattr(api, "_clerk_verifier", lambda *_args: verifier)
    monkeypatch.setattr(api, "_runtime_admission_adapter", lambda: c.adapter)
    for module in (provider_team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", runtime)
    from cosmas_os.application import enrollment_access
    monkeypatch.setattr(enrollment_access, "EnrollmentAdmissionAdapter", lambda _runtime: c.adapter)
    def get_session():
        with sessions() as session:
            yield session
    api.app.dependency_overrides[api.get_session] = get_session
    try:
        with TestClient(api.app) as client:
            yield SimpleNamespace(control=c, client=client, engine=engine, sessions=sessions, runtime=runtime,
                actor=None, binding_id=None, headers={"Authorization": "Bearer " + c.token,
                "X-Cosmas-Workspace-Protocol": "1", "X-Cosmas-Team-Contract": "2", "X-Cosmas-Model-Contract": "1",
                "X-Cosmas-Private-Draft": "1", "X-Cosmas-Practice-Access-Contract": "1"})
    finally:
        api.app.dependency_overrides.pop(api.get_session, None)


def complete_setup(f):
    response = f.client.post("/practice-access/setup/complete", headers=f.headers, json={"idempotency_key": str(uuid4()),
        "display_name": "Alex Example", "practice_name": "Example Practice", "specialty": None, "confirm": True})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "owner_ready"
    with f.sessions() as session:
        binding = session.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == "user_synthetic_owner-a"))
        f.actor, f.binding_id = binding.principal_id, binding.id


def private_workspace(f):
    response = f.client.post("/workspaces/private-drafts", headers=f.headers, json={"title": "Invented onboarding draft", "idempotency_key": str(uuid4())})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def setup_model(f, monkeypatch, reply):
    f.runtime.workspace_llm_backend = "azure_gpt41"
    f.runtime.workspace_llm_api_key = SecretStr("synthetic-no-model-network")
    result = f.client.post("/provider-team", headers=f.headers, json={"expected_revision": 0,
        "idempotency_key": str(uuid4()), "configuration": provider_team.default_configuration()})
    assert result.status_code == 200, result.text
    monkeypatch.setattr(model_work, "dispatch_claim", reply)


def test_bound_setup_before_trial_direct_read_and_paid_member_pagination(runtime_case):
    f = runtime_case
    assert f.control.adapter.authorize(f.control.token, "user_synthetic_owner-a", purpose="qualification")["enforced"]
    qualification = f.client.get("/practice-access/enrollment-qualification", headers=f.headers)
    assert qualification.status_code == 403, qualification.text
    setup = f.client.get("/practice-access/setup", headers=f.headers)
    assert setup.status_code == 200 and setup.json()["state"] == "solo_setup_available"
    assert f.client.get("/account/identity", headers=f.headers).status_code == 403
    assert not f.control.app.state.synthetic_commerce.sessions
    complete_setup(f)
    qualified = f.client.get("/practice-access/enrollment-qualification", headers=f.headers).json()
    assert qualified["initial_setup_complete"] is True
    assert qualified["enrollment_admission"] == {"contract_version": "cosmas-enrollment-admission.v1",
        "enforced": True, "practice_id": f.control.practice_id, "purpose": "qualification"}
    activate(f.control)
    assert f.client.get("/workspaces", headers=f.headers).status_code == 200
    roster = f.client.post("/practice-access/members", headers=f.headers, json={"after_id": None})
    assert roster.status_code == 200 and roster.json()["members"][0]["state"] == "active"
    assert f.client.get("/account/identity", headers=f.headers).json()["state"] == "allowed"
    config = f.client.get("/config")
    assert config.headers["cache-control"] == "no-store"
    assert config.json()["enrollment_recovery_url"] == "https://app.example.invalid/onboarding"


@pytest.mark.parametrize("hold", ["canceled", "unpaid", "revoked", "outage"])
def test_bookmarked_runtime_calls_deny_and_recover_without_navigation_gate(runtime_case, hold):
    f = runtime_case
    complete_setup(f)
    activate(f.control)
    wid = private_workspace(f)
    if hold == "outage":
        old = f.control.adapter.client
        import httpx
        f.control.adapter.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    else:
        with f.control.app.state.enrollment_service.sessions.begin() as session:
            if hold == "revoked":
                from cosmas_os.enrollment.models import Membership
                member = session.scalar(select(Membership).where(Membership.practice_id == f.control.practice_id, Membership.role == "owner"))
                member.active = False
            else:
                session.get(Practice, f.control.practice_id).subscription_status = hold
    for path in ("/workspaces", "/workspaces/" + wid, "/account/identity", "/provider-team", "/practice-access"):
        response = f.client.get(path, headers=f.headers)
        assert response.status_code in (403, 503), response.text
        assert response.headers["x-cosmas-enrollment-admission"] in {ACCESS_REQUIRED, "workspace_enrollment_admission_unavailable"}
    if hold == "outage":
        f.control.adapter.client = old
    else:
        with f.control.app.state.enrollment_service.sessions.begin() as session:
            session.get(Practice, f.control.practice_id).subscription_status = "trialing"
            if hold == "revoked":
                member = session.scalar(select(Membership).where(Membership.practice_id == f.control.practice_id, Membership.role == "owner"))
                member.active = True
    assert f.client.get("/workspaces/" + wid, headers=f.headers).status_code == 200


def test_runtime_owner_paths_cannot_add_humans_outside_purchased_registry(runtime_case):
    f = runtime_case
    complete_setup(f)
    activate(f.control)
    for path in ("/practice-access/invitation/create", "/practice-access/decide", "/practice-access/member-change", "/admin/identities/bind",
                 "/admin/identities/reactivate", "/admin/identities/deactivate"):
        response = f.client.post(path, headers=f.headers, json={})
        assert response.status_code == 403, (path, response.text)
    extra = str(uuid4())
    with f.sessions.begin() as session:
        session.add(Principal(id=extra, box_id=f.control.box_id, principal_type="human", state="active", display_name="Invented extra human"))
        session.flush()
        session.add(ExternalIdentity(box_id=f.control.box_id, principal_id=extra, provider="clerk", issuer=f.control.issuer,
            organization_id=f.control.org, subject="user_synthetic_staff-a", active=True, reviewed_by="Synthetic test", evidence_ref="synthetic:uncapped-old-path"))
    token = f.control.client.post("/lab/session", json={"user": "staff-a", "organization_id": f.control.org}).json()["token"]
    response = f.client.get("/workspaces", headers={**f.headers, "Authorization": "Bearer " + token})
    assert response.status_code == 403 and response.json()["detail"] == ACCESS_REQUIRED


@pytest.mark.parametrize("initial_hold", ["pending", "canceled"])
def test_invited_staff_paid_lazy_binding_and_revocation_never_remaps(runtime_case, initial_hold):
    f, c = runtime_case, runtime_case.control
    complete_setup(f)
    invitation = c.write("/invitations", {"email": "staff-a@example.invalid", "role": "admin", "can_sign": True})
    pre_org = c.client.post("/lab/session", json={"user": "staff-a"}).json()["token"]
    central_headers = {"Authorization": "Bearer " + pre_org}
    def staff_write(path, body, method="POST"):
        revision = c.client.get("/enrollment/v1/status", headers=central_headers).json()["revision"]
        response = c.client.request(method, "/enrollment/v1" + path,
            headers={**central_headers, "Idempotency-Key": str(uuid4())}, json={"expected_revision": revision, **body})
        assert response.status_code == 200, response.text
    staff_write("/profile", {"display_name": "Casey Example", "title": "Administrator"}, "PUT")
    staff_write("/join", {"token": invitation["token"]})
    token = c.client.post("/lab/session", json={"user": "staff-a", "organization_id": c.org}).json()["token"]
    headers = {**f.headers, "Authorization": "Bearer " + token}
    if initial_hold == "canceled":
        activate(c)
        with c.app.state.enrollment_service.sessions.begin() as session:
            session.get(Practice, c.practice_id).subscription_status = "canceled"
    denied = f.client.get("/practice-access/enrollment-qualification", headers=headers)
    assert denied.status_code == 403 and denied.headers["x-cosmas-enrollment-admission"] == ACCESS_REQUIRED
    with f.sessions() as session:
        assert session.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == "user_synthetic_staff-a")) is None
        assert session.scalar(select(func.count()).select_from(Principal).where(Principal.principal_type == "human")) == 1
    if initial_hold == "pending":
        activate(c)
    else:
        with c.app.state.enrollment_service.sessions.begin() as session:
            session.get(Practice, c.practice_id).subscription_status = "trialing"
    qualified = f.client.get("/practice-access/enrollment-qualification", headers=headers)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["role"] == "member" and qualified.json()["initial_setup_complete"] is True
    assert qualified.json()["enrollment_admission"] == {"contract_version": "cosmas-enrollment-admission.v1",
        "enforced": True, "practice_id": c.practice_id, "purpose": "qualification"}
    with f.sessions() as session:
        binding = session.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == "user_synthetic_staff-a"))
        principal = session.get(Principal, binding.principal_id)
        assert principal.state == "active" and not principal.is_owner
        binding_id, principal_id = binding.id, principal.id
    assert f.client.get("/workspaces", headers=headers).status_code == 403  # No public ready shortcut.
    c.app.state.enrollment_service.record_membership_ready(c.practice_id, issuer=c.issuer,
        subject="user_synthetic_staff-a", organization_id=c.org, proof_sha256=hashlib.sha256(qualified.content).hexdigest())
    assert f.client.get("/workspaces", headers=headers).status_code == 200
    c.app.state.synthetic_identities.removed_memberships.add(("user_synthetic_staff-a", c.org))
    assert f.client.get("/workspaces", headers=headers).status_code == 403
    assert f.client.get("/practice-access/enrollment-qualification", headers=headers).status_code == 403
    c.app.state.synthetic_identities.removed_memberships.clear()
    with f.sessions.begin() as session:
        session.get(ExternalIdentity, binding_id).active = False
    assert f.client.get("/practice-access/enrollment-qualification", headers=headers).status_code == 403
    with f.sessions() as session:
        unchanged = session.get(ExternalIdentity, binding_id)
        assert not unchanged.active and unchanged.principal_id == principal_id
        assert session.scalar(select(func.count()).select_from(ExternalIdentity).where(ExternalIdentity.subject == "user_synthetic_staff-a")) == 1


def test_commit_fence_prevents_write_after_billing_changes(runtime_case):
    f = runtime_case
    complete_setup(f)
    activate(f.control)
    def get_session():
        with f.sessions() as session:
            def cancel_before_commit(_):
                with f.control.app.state.enrollment_service.sessions.begin() as control:
                    control.get(Practice, f.control.practice_id).subscription_status = "unpaid"
            event.listen(session, "before_commit", cancel_before_commit)
            yield session
    api.app.dependency_overrides[api.get_session] = get_session
    response = f.client.post("/workspaces/private-drafts", headers=f.headers, json={"title": "Must not commit", "idempotency_key": str(uuid4())})
    assert response.status_code == 403, response.text
    with f.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EncounterWorkspace)) == 0


def test_actual_first_chief_action_and_denied_settlement_retains_usage(runtime_case, monkeypatch):
    f = runtime_case
    complete_setup(f)
    activate(f.control)
    wid = private_workspace(f)
    calls = []
    def reply(claim):
        calls.append(claim.admission_id)
        return BotReply("Invented Chief response.", (), "azure_gpt41", 20, 7)
    setup_model(f, monkeypatch, reply)
    body = {"expected_revision": 1, "team_revision": 1, "idempotency_key": str(uuid4()), "role": "chief", "content": "Help me get started."}
    response = f.client.post(f"/workspaces/{wid}/conversation", headers=f.headers, json=body)
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    with f.sessions() as session:
        assert session.scalar(select(ModelWorkAdmission)).state == "completed"
        assert session.scalar(select(WorkspaceReply)).content == "Invented Chief response."
    def cancel_and_reply(claim):
        with f.control.app.state.enrollment_service.sessions.begin() as session:
            session.get(Practice, f.control.practice_id).subscription_status = "unpaid"
        return BotReply("Withheld after cancellation.", (), "azure_gpt41", 30, 9)
    monkeypatch.setattr(model_work, "dispatch_claim", cancel_and_reply)
    with f.sessions() as session:
        revision = session.get(EncounterWorkspace, wid).revision
    response = f.client.post(f"/workspaces/{wid}/conversation", headers=f.headers, json={**body, "expected_revision": revision, "idempotency_key": str(uuid4())})
    assert response.status_code == 403 and response.headers["x-cosmas-enrollment-admission"] == ACCESS_REQUIRED
    with f.sessions() as session:
        admissions = list(session.scalars(select(ModelWorkAdmission).order_by(ModelWorkAdmission.admitted_at)))
        assert admissions[-1].state == "failed"
        assert session.scalar(select(func.count()).select_from(WorkspaceReply)) == 1


@pytest.mark.parametrize("admission_state", ["active", "unpaid", "canceled", "registry_revoked", "clerk_revoked", "outage", "forged_actor"])
def test_private_handoff_worker_uses_retained_human_not_agent_approval(runtime_case, monkeypatch, admission_state):
    f = runtime_case
    complete_setup(f)
    activate(f.control)
    wid = private_workspace(f)
    calls = []
    def reply(claim):
        calls.append(claim.admission_id)
        return BotReply("Invented human-requested delegation.", (), "azure_gpt41", 20, 7,
            (DraftBrief("visit_prep", "Organize the saved private draft.", REQUIREMENTS),))
    setup_model(f, monkeypatch, reply)
    body = {"expected_revision": 1, "team_revision": 1, "idempotency_key": str(uuid4()), "role": "chief", "content": "Ask Visit prep to organize this private draft."}
    response = f.client.post(f"/workspaces/{wid}/conversation", headers=f.headers, json=body)
    assert response.status_code == 200, response.text
    with f.sessions() as session:
        queued = session.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.kind == "private_handoff"))
        assert queued is not None and queued.state == "reserved"
    denied = admission_state != "active"
    if admission_state in {"unpaid", "canceled"}:
        with f.control.app.state.enrollment_service.sessions.begin() as session:
            session.get(Practice, f.control.practice_id).subscription_status = admission_state
    elif admission_state == "registry_revoked":
        from cosmas_os.enrollment.models import Membership
        with f.control.app.state.enrollment_service.sessions.begin() as session:
            session.scalar(select(Membership).where(Membership.practice_id == f.control.practice_id, Membership.role == "owner")).active = False
    elif admission_state == "clerk_revoked":
        f.control.app.state.synthetic_identities.removed_memberships.add(("user_synthetic_owner-a", f.control.org))
    elif admission_state == "outage":
        import httpx
        f.control.adapter.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    elif admission_state == "forged_actor":
        from sqlalchemy.exc import DBAPIError

        from cosmas_os.adapters.enrollment_admission import RuntimeAdmissionError
        from cosmas_os.application.enrollment_access import require_worker_admission
        with f.sessions() as session:
            queued = session.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.kind == "private_handoff"))
            agent = session.scalar(select(Principal).where(Principal.principal_type == "agent", Principal.box_id == f.control.box_id))
            with pytest.raises(RuntimeAdmissionError):
                require_worker_admission(session, f.runtime, box=f.control.box_id, owner=agent.id,
                    operation_id=queued.id, approval_sha256=queued.envelope_sha256)
            queued.owner_id = agent.id
            with pytest.raises(DBAPIError):
                session.commit()
            session.rollback()
        assert len(calls) == 1
        return  # PostgreSQL refuses to persist the forged immutable actor.
    def worker_reply(claim):
        calls.append(claim.admission_id)
        return BotReply("Invented authorized handoff result.", (), "azure_gpt41", 10, 4)
    assert model_work.process_next(f.sessions, dispatch=worker_reply) is True
    assert len(calls) == (1 if denied else 2)
    with f.sessions() as session:
        queued = session.scalar(select(ModelWorkAdmission).where(ModelWorkAdmission.kind == "private_handoff"))
        assert queued.state == ("failed" if denied else "completed")
