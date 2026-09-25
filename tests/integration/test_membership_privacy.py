"""Production API/privacy selectors, signed Core fences and no generic membership access."""

import base64
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_core_note_review import capture_case as capture_case
from tests.integration.test_core_note_review import case as case
from tests.integration.test_core_note_review import reviewed
from tests.integration.test_membership_work import (
    POLICY,
    bound,
    call,
    created,
    detail,
    proposal,
    result,
    verification,
)
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.api import app as api
from cosmas_os.api import membership_work_schemas as p
from cosmas_os.application import membership_work as flow
from cosmas_os.application import routines, services, shared_work
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.domain.enums import DecisionKind
from cosmas_os.domain.rules import AuthorizationError
from cosmas_os.domain.work_lanes import PRIVATE_CONNECTOR_LANES
from cosmas_os.membership_models import MembershipReceipt
from cosmas_os.models import (
    Artifact,
    Decision,
    EncounterWorkspace,
    ExternalIdentity,
    Operation,
    Principal,
    Ticket,
)


@pytest.fixture
def other_humans(session, vendor_case):
    users = []
    for label, is_owner in (("Other practice owner", True), ("Practice staff", False)):
        person = Principal(
            box_id=vendor_case["box"],
            principal_type="human",
            display_name=label,
            state="active",
            is_owner=is_owner,
        )
        session.add(person)
        session.flush()
        users.append(person.id)
    session.commit()
    return users


def test_all_legacy_commands_and_audit_are_denied_without_writes(
    session, vendor_case, other_humans
):
    c = vendor_case
    tid = created(session, c)
    before = detail(session, c, tid)
    container = services.Container(session)
    assert flow.LANE in PRIVATE_CONNECTOR_LANES
    assert tid not in {item["id"] for item in services.list_queue(container, c["box"])}
    for actor in [c["actor"], *other_humans]:
        for invoke in (
            lambda actor=actor: services.edit_revision(
                container, tid, actor, "Forbidden generic membership edit"
            ),
            lambda actor=actor: services.decide(container, tid, actor, DecisionKind.APPROVE),
            lambda actor=actor: services.close_ticket(container, tid, actor),
            lambda actor=actor: services.simulate_upload_and_verify(
                container, tid, actor, b"fake", b"fake"
            ),
            lambda: services.audit_timeline(container, c["box"], tid),
        ):
            with pytest.raises(AuthorizationError):
                invoke()
    assert detail(session, c, tid) == before
    assert session.scalar(select(Operation.id).where(Operation.ticket_id == tid)) is None
    assert session.scalar(select(Artifact.id).where(Artifact.ticket_id == tid)) is None
    assert (
        session.scalar(select(func.count()).select_from(Decision).where(Decision.ticket_id == tid))
        == 1
    )


@pytest.mark.parametrize("closed", [False, True])
def test_no_other_owner_or_staff_candidate_link_or_published_work(
    session, vendor_case, other_humans, closed
):
    c = vendor_case
    tid = created(session, c)
    if closed:
        result(session, c, tid)
        call(session, c, flow.command, tid, "verify", verification(session, c, tid))
    original = session.get(EncounterWorkspace, c["wid"])
    assert original is not None
    for actor in other_humans:
        theirs = ws.create(
            session, c["box"], actor, original.appointment_id, "membership-private-" + str(uuid4())
        )
        assert tid not in {item["id"] for item in theirs["work_candidates"]}
        with pytest.raises(ws.WorkspaceError, match="work_unavailable"):
            ws.append(
                session,
                c["box"],
                actor,
                theirs["id"],
                expected=1,
                key="forbidden-membership-link-" + str(uuid4()),
                kind="work_link",
                ticket_id=tid,
            )
        for method, args in ((flow.catalog, ()), (flow.detail, (tid,)), (flow.history, (tid,))):
            with pytest.raises(ws.WorkspaceError, match="membership_work_unavailable"):
                method(session, c["box"], actor, c["wid"], *args, policy=POLICY)
    for actor in [c["actor"], *other_humans]:
        for vendor in (False, True):
            assert tid not in {
                item["ticket_id"]
                for item in shared_work.catalog(session, c["box"], actor, vendor=vendor)["items"]
            }
            with pytest.raises(ws.WorkspaceError, match="shared_work_unavailable"):
                shared_work.read(session, c["box"], actor, tid, vendor=vendor)
        assert tid not in {
            item["ticket_id"]
            for item in routines._snapshot(session, c["box"], actor, "2026-09-21")["items"]
        }
    assert tid in {
        item["id"] for item in ws.read(session, c["box"], c["actor"], c["wid"])["work_candidates"]
    }


@pytest.fixture
def production_client(session):
    # Clone exact installed production routes/middleware, omitting startup workers.
    app = FastAPI(middleware=list(api.app.user_middleware))
    app.exception_handlers.update(api.app.exception_handlers)
    app.include_router(api.app.router)
    connection = session.connection()

    def request_session():
        # Each request owns its Session while sharing the fixture's outer
        # transaction. Capture request ownership must never be reused or reset.
        with Session(bind=connection, autoflush=False,
                     join_transaction_mode="create_savepoint") as current:
            yield current

    class FixtureClient(TestClient):
        def request(self, *args, **kwargs):
            session.flush()
            try:
                return super().request(*args, **kwargs)
            finally:
                session.expire_all()

    app.dependency_overrides[api.get_session] = request_session
    app.dependency_overrides[api._membership_policy] = lambda: POLICY
    with FixtureClient(app) as client:
        yield client


def identity(c, actor=None):
    return {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": actor or c["actor"],
        "X-Cosmas-Draft-Recovery": "2",
    }


def test_production_http_withholds_generic_routes_and_owner_details(
    production_client, session, vendor_case, other_humans, tmp_path
):
    http, c = production_client, vendor_case
    req = proposal(session, c, instructions="Invented private membership instructions sentinel")
    root = f"/workspaces/{c['wid']}/membership-work"
    headers = identity(c) | {"X-Cosmas-Membership-Contract": "1"}
    response = http.post(root, headers=headers, json=req.public())
    assert response.status_code == 200, response.text
    receipt = response.json()
    tid = receipt["effect"]["ticket_id"]
    for actor in [c["actor"], *other_humans]:
        h = identity(c, actor)
        assert tid not in {item["id"] for item in http.get("/queue", headers=h).json()}
        assert http.get(f"/tickets/{tid}/timeline", headers=h).status_code == 403
        for path, body in (
            ("edit", {"body": "Forbidden generic body"}),
            ("decide", {"kind": "approve"}),
            ("close", {}),
            (
                "upload-verify",
                {
                    "front_b64": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode(),
                    "back_b64": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode(),
                },
            ),
        ):
            denied = http.post(f"/tickets/{tid}/{path}", headers=h, json=body)
            assert denied.status_code == 403, (path, denied.text)
            assert "instructions sentinel" not in denied.text
        assert http.get(f"/practice-work/{tid}", headers=h).status_code == 404
        if actor != c["actor"]:
            h["X-Cosmas-Membership-Contract"] = "1"
            for suffix in ("", "/options", "/" + tid, "/" + tid + "/history"):
                denied = http.get(root + suffix, headers=h)
                assert denied.status_code == 404 and "instructions sentinel" not in denied.text
            denied = http.post(
                root + "/resolve",
                headers=h,
                json={
                    "command_kind": "propose",
                    "idempotency_key": req.idempotency_key,
                    "request_sha256": receipt["request_sha256"],
                },
            )
            assert denied.status_code == 404
    assert http.get(root + "/" + tid, headers=headers).status_code == 200
    origin = api.settings.allowed_origins[0]
    rejected = http.get(root + "?unexpected=1", headers=headers | {"Origin": origin})
    assert rejected.status_code == 426 and rejected.headers["access-control-allow-origin"] == origin
    preflight = http.options(
        root,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-cosmas-membership-contract",
        },
    )
    assert (
        preflight.status_code == 200
        and "x-cosmas-membership-contract"
        in preflight.headers["access-control-allow-headers"].lower()
    )
    (tmp_path / "actual-membership-integrated-private-http.json").write_text(
        json.dumps(
            {
                "request": req.public(),
                "receipt": receipt,
                "detail": http.get(root + "/" + tid, headers=headers).json(),
            },
            indent=2,
        )
    )


def test_default_off_policy_and_gate_are_independent(monkeypatch):
    assert Settings.model_fields["membership_work_enabled"].default is False
    assert flow.DEFAULT_POLICY.private_selectors_ready is False
    monkeypatch.setattr(api.settings, "membership_work_enabled", False)
    assert api._membership_policy().enabled is False


def test_disabled_recovery_and_stale_source_rejection_in_installed_routes(
    production_client, session, vendor_case
):
    http, c = production_client, vendor_case
    req = proposal(session, c)
    root = f"/workspaces/{c['wid']}/membership-work"
    h = identity(c) | {"X-Cosmas-Membership-Contract": "1"}
    receipt = http.post(root, headers=h, json=req.public()).json()
    tid = receipt["effect"]["ticket_id"]
    d = http.get(root + "/" + tid, headers=h).json()
    decision = p.Decision(
        **bound(d),
        review_sha256=d["review_sha256"],
        choice="approve",
        reviewed_patient=True,
        reviewed_local_only_authority=True,
    )
    http.app.dependency_overrides[api._membership_policy] = lambda: flow.MembershipPolicy(
        False, True
    )
    assert http.post(root, headers=h, json=req.public()).json() == receipt
    assert (
        http.post(root + "/" + tid + "/decide", headers=h, json=decision.public()).status_code
        == 403
    )
    http.app.dependency_overrides[api._membership_policy] = lambda: POLICY
    w = session.get(EncounterWorkspace, c["wid"])
    assert w is not None
    w.revision += 1
    session.commit()
    assert http.get(root + "/" + tid, headers=h).json()["summary"]["source_current"] is False
    rejected = http.post(root + "/" + tid + "/decide", headers=h, json=decision.public())
    assert rejected.status_code == 409
    ticket = session.get(Ticket, tid)
    assert ticket is not None and ticket.state == "pending_approval"


@pytest.mark.parametrize("phase", ["propose", "decide", "result", "verify"])
def test_signed_current_core_note_is_rechecked_for_membership(case, phase):
    f = case
    reviewed(f)
    api.app.dependency_overrides[api._membership_policy] = lambda: POLICY
    try:
        root = f.root + "/membership-work"
        h = {"Authorization": "Bearer " + f.token(), "X-Cosmas-Membership-Contract": "1"}
        options = f.client.get(root + "/options", headers=h).json()
        req = p.Proposal(
            expected_workspace_revision=options["expected_workspace_revision"],
            source=options["source"],
            patient_link_id=options["patient_link_id"],
            purpose="membership_status_review",
            due_date="2026-09-30",
            expected_outcome="Review local membership information",
            instructions="No source vendor is selected.",
            idempotency_key="membership-core-propose",
        )
        path, body, expected_count = root, req.public(), 0
        if phase != "propose":
            first = f.client.post(root, headers=h, json=body)
            assert first.status_code == 200, first.text
            tid = first.json()["effect"]["ticket_id"]
            d = f.client.get(root + "/" + tid, headers=h).json()
            decision = p.Decision(
                **bound(d),
                review_sha256=d["review_sha256"],
                choice="approve",
                reviewed_patient=True,
                reviewed_local_only_authority=True,
            )
            path, body, expected_count = root + "/" + tid + "/decide", decision.public(), 1
            if phase in {"result", "verify"}:
                assert f.client.post(path, headers=h, json=body).status_code == 200
                d = f.client.get(root + "/" + tid, headers=h).json()
                result = p.Result(
                    **bound(d),
                    disposition="local_preparation_ready",
                    evidence="Invented local review only",
                )
                path, body, expected_count = root + "/" + tid + "/result", result.public(), 2
                if phase == "verify":
                    assert f.client.post(path, headers=h, json=body).status_code == 200
                    d = f.client.get(root + "/" + tid, headers=h).json()
                    verify = p.Verify(
                        **bound(d),
                        result_receipt_id=d["latest_result"]["receipt_id"],
                        result_receipt_sha256=d["latest_result"]["receipt_sha256"],
                        evidence_classification="local_unreconciled",
                        reviewed_patient=True,
                        reviewed_result=True,
                        reviewed_evidence_limits=True,
                        confirm_review_completion=True,
                    )
                    path, body, expected_count = root + "/" + tid + "/verify", verify.public(), 3
        f.port.calls.clear()
        assert f.draft["source_sha256"] != "b" * 64
        f.draft["source_sha256"] = "b" * 64
        rejected = f.client.post(path, headers=h, json=body)
        assert rejected.status_code == 409, rejected.text
        assert "note" in f.port.calls
        with Session(f.engine) as s:
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(MembershipReceipt)
                    .where(MembershipReceipt.workspace_id == f.workspace["id"])
                )
                == expected_count
            )
    finally:
        api.app.dependency_overrides.pop(api._membership_policy, None)


def test_signed_identity_revocation_during_core_read_prevents_admission(case):
    f = case
    reviewed(f)
    api.app.dependency_overrides[api._membership_policy] = lambda: POLICY
    try:
        root = f.root + "/membership-work"
        h = {"Authorization": "Bearer " + f.token(), "X-Cosmas-Membership-Contract": "1"}
        options = f.client.get(root + "/options", headers=h).json()
        req = p.Proposal(
            expected_workspace_revision=options["expected_workspace_revision"],
            source=options["source"],
            patient_link_id=options["patient_link_id"],
            purpose="enrollment_assistance",
            due_date="2026-09-30",
            expected_outcome="Local review only",
            instructions="Do not enroll or charge.",
            idempotency_key="membership-revoked-core",
        )

        def revoke(phase):
            if phase == "note":
                with Session(f.engine) as s:
                    row = s.get(ExternalIdentity, f.identity_id)
                    assert row is not None
                    row.active = False
                    s.commit()

        f.port.after = revoke
        rejected = f.client.post(root, headers=h, json=req.public())
        assert rejected.status_code in {403, 404}, rejected.text
        with Session(f.engine) as s:
            assert (
                s.scalar(
                    select(MembershipReceipt.id).where(
                        MembershipReceipt.workspace_id == f.workspace["id"]
                    )
                )
                is None
            )
    finally:
        api.app.dependency_overrides.pop(api._membership_policy, None)
