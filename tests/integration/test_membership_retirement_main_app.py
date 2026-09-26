"""Membership retirement through the exact main-app router and middleware."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from tests.integration.test_membership_privacy import identity
from tests.integration.test_membership_privacy import other_humans as other_humans
from tests.integration.test_membership_privacy import (
    production_client as production_client,
)
from tests.integration.test_membership_retirement import advance_note, envelope
from tests.integration.test_membership_work import OFF, bound, proposal
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.api import app as api
from cosmas_os.api import membership_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import membership_work as flow
from cosmas_os.membership_models import MembershipCommandRetirement, MembershipReceipt
from cosmas_os.models import Operation, Ticket


def headers(c, actor=None):
    return identity(c, actor) | {
        "X-Cosmas-Membership-Contract": "1",
        "Origin": api.settings.allowed_origins[0],
    }


def test_real_app_registers_retirement_and_keeps_inbox_default_off():
    route = [r for r in api.app.routes
             if getattr(r, "path", "") == "/workspaces/{workspace_id}/membership-work/retire"]
    assert len(route) == 1 and getattr(route[0], "methods", None) == {"POST"}
    assert any(getattr(r, "path", "") == "/inbox" for r in api.app.routes)
    assert api._inbox_policy().enabled is False
    assert api._inbox_registry()().grants == {}
    assert flow.DEFAULT_POLICY.enabled is False


def test_main_app_retirement_exact_recovery_cors_and_disabled_policy(
    production_client, session, vendor_case, tmp_path,
):
    c, client = vendor_case, production_client
    root = f"/workspaces/{c['wid']}/membership-work"
    old = proposal(session, c)
    request = envelope(c, "propose", old)
    advance_note(session, c, old)
    h = headers(c)
    reject = client.post(root, headers=h, json=old.public())
    assert reject.status_code == 409 and reject.json()["error"]["code"] == "membership_source_changed"
    query = {"command_kind": "propose", "idempotency_key": old.idempotency_key,
             "request_sha256": request.request_sha256}
    assert client.post(root + "/resolve", headers=h, json=query).json()["outcome"] == "not_found"
    client.app.dependency_overrides[api._membership_policy] = lambda: OFF
    response = client.post(root + "/retire", headers=h, json=request.public())
    assert response.status_code == 200, response.text
    proof = response.json()
    assert proof["outcome"] == "retired" and proof["effect"] is None
    assert len(response.content) <= 8192
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == h["Origin"]
    assert client.post(root + "/resolve", headers=h, json=query).json() == proof
    assert client.post(root + "/retire", headers=h, json=request.public()).json() == proof
    assert client.post(root, headers=h, json=old.public()).json() == proof
    assert session.scalar(select(func.count()).select_from(MembershipCommandRetirement).where(
        MembershipCommandRetirement.workspace_id == c["wid"])) == 1
    assert session.scalar(select(MembershipReceipt.id).where(MembershipReceipt.workspace_id == c["wid"])) is None
    assert session.scalar(select(Operation.id).join(Ticket).where(Ticket.box_id == c["box"])) is None
    (tmp_path / "actual-main-app-retirement.json").write_text(json.dumps({
        "request": request.public(), "proof": proof, "schema": "7f15c39ad842",
        "cors_origin": h["Origin"], "response_bytes": len(response.content),
    }, indent=2))


def test_main_app_retirement_wrapper_and_original_caps(production_client, session, vendor_case):
    c, client = vendor_case, production_client
    old = proposal(session, c)
    advance_note(session, c, old)
    count = 2000
    while len(public.canonical(old.model_copy(update={"instructions": "🧪" * count}).public())) > 8192:
        count -= 1
    legal = old.model_copy(update={"instructions": "🧪" * count})
    body = public.canonical(envelope(c, "propose", legal).public())
    assert 8192 < len(body) <= 16384
    root = f"/workspaces/{c['wid']}/membership-work/retire"
    h = headers(c) | {"Content-Type": "application/json"}
    accepted = client.post(root, headers=h, content=body)
    assert accepted.status_code == 200 and accepted.json()["outcome"] == "retired", accepted.text
    oversized = old.model_copy(update={"instructions": "🧪" * 2000,
                                     "idempotency_key": "oversize-" + str(uuid4())})
    assert len(public.canonical(oversized.public())) > 8192
    for raw in (public.canonical(envelope(c, "propose", oversized).public()), b" " * 16385):
        response = client.post(root, headers=h, content=raw)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "invalid_membership_request"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["access-control-allow-origin"] == h["Origin"]


@pytest.mark.parametrize("mode", ["missing", "wrong", "duplicate", "query", "other_route"])
def test_main_app_rejects_bad_contract_before_admission(production_client, session, vendor_case, mode):
    c, client = vendor_case, production_client
    path = f"/workspaces/{c['wid']}/membership-work/retire"
    h = headers(c)
    if mode == "missing":
        h.pop("X-Cosmas-Membership-Contract")
    elif mode == "wrong":
        h["X-Cosmas-Membership-Contract"] = "2"
    elif mode == "query":
        path += "?unexpected=1"
    elif mode == "other_route":
        path = "/queue"
    values = list(h.items())
    if mode == "duplicate":
        values.append(("X-Cosmas-Membership-Contract", "1"))
    response = client.post(path, headers=values, json={})
    assert response.status_code == 426
    assert response.json()["error"]["code"] == "membership_contract_required"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == h["Origin"]
    assert session.scalar(select(MembershipCommandRetirement.id).where(
        MembershipCommandRetirement.workspace_id == c["wid"])) is None


def test_main_app_retirement_preflight_origin_and_no_authentication(production_client, vendor_case):
    client = production_client

    def no_identity():
        raise AssertionError("Preflight must not authenticate")

    client.app.dependency_overrides[api._identity] = no_identity
    h = {"Origin": api.settings.allowed_origins[0], "Access-Control-Request-Method": "POST",
         "Access-Control-Request-Headers": "authorization,content-type,x-cosmas-membership-contract"}
    path = f"/workspaces/{vendor_case['wid']}/membership-work/retire"
    allowed = client.options(path, headers=h)
    assert allowed.status_code == 200 and allowed.headers["access-control-allow-origin"] == h["Origin"]
    denied = client.options(path, headers=h | {"Origin": "https://unapproved.invalid"})
    assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers


def test_retired_ticket_proof_stays_owner_private_and_off_generic_routes(
    production_client, session, vendor_case, other_humans,
):
    c, client = vendor_case, production_client
    root = f"/workspaces/{c['wid']}/membership-work"
    h = headers(c)
    old = proposal(session, c, instructions="Invented retirement private sentinel")
    created = client.post(root, headers=h, json=old.public()).json()
    tid = created["effect"]["ticket_id"]
    detail = client.get(root + "/" + tid, headers=h).json()
    decision = schema.Decision(**bound(detail), review_sha256=detail["review_sha256"],
                               choice="approve", reviewed_patient=True, reviewed_local_only_authority=True)
    request = envelope(c, "decide", decision)
    advance_note(session, c, old)
    response = client.post(root + "/retire", headers=h, json=request.public())
    assert response.status_code == 200 and response.json()["outcome"] == "retired", response.text
    proof = response.json()
    query = {"command_kind": "decide", "idempotency_key": decision.idempotency_key,
             "request_sha256": request.request_sha256}
    for actor in [c["actor"], *other_humans]:
        generic = identity(c, actor)
        for path in ("/queue", "/practice-work"):
            text = client.get(path, headers=generic).text
            assert tid not in text and proof["retirement"]["receipt_id"] not in text
            assert "private sentinel" not in text
        assert client.get(f"/tickets/{tid}/timeline", headers=generic).status_code == 403
        for action, body in (("edit", {"body": "Forbidden"}), ("decide", {"kind": "approve"}), ("close", {})):
            assert client.post(f"/tickets/{tid}/{action}", headers=generic, json=body).status_code == 403
        if actor != c["actor"]:
            private = headers(c, actor)
            for endpoint, body in (("retire", request.public()), ("resolve", query)):
                denied = client.post(root + "/" + endpoint, headers=private, json=body)
                assert denied.status_code == 404 and proof["retirement"]["receipt_id"] not in denied.text
            assert client.get(root + "/" + tid + "/history", headers=private).status_code == 404
    assert session.get(Ticket, tid).state == "pending_approval"
    assert session.scalar(select(Operation.id).where(Operation.ticket_id == tid)) is None
