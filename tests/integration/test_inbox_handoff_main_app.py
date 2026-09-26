"""Inbox-to-F8 privacy, accountability and recovery through the installed main app."""

import json
from itertools import product
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from tests.integration.test_inbox_handoff import ON
from tests.integration.test_inbox_handoff import case as case
from tests.integration.test_inbox_work import inbox_case as inbox_case
from tests.integration.test_inbox_work import ingest, snapshot
from tests.integration.test_membership_privacy import identity
from tests.integration.test_membership_privacy import other_humans as other_humans
from tests.integration.test_membership_privacy import (
    production_client as production_client,
)
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.api import app as api
from cosmas_os.api import inbox_handoff_schemas as p
from cosmas_os.api.vendor_work_schemas import canonical, public_digest
from cosmas_os.application import inbox_handoff as flow
from cosmas_os.application import inbox_work as inbox
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.inbox_handoff_models import InboxHandoffReceipt
from cosmas_os.inbox_models import InboxEvent
from cosmas_os.models import (
    AuditEvent,
    EncounterWorkspace,
    FollowUpReceipt,
    Operation,
    Ticket,
    WorkHandoff,
)


def headers(c, actor=None):
    return identity(c, actor) | {
        "X-Cosmas-Inbox-Handoff-Contract": "1",
        "Origin": api.settings.allowed_origins[0],
    }


def response(value, model=None, *, status=200, maximum=16384):
    assert value.status_code == status, value.text
    assert value.headers["cache-control"] == "no-store"
    assert value.headers["access-control-allow-origin"] == api.settings.allowed_origins[0]
    assert len(value.content) <= maximum
    body = value.json()
    if model is not None:
        assert model.model_validate(body).public() == body
    if model is p.Response:
        unsigned = {key: item for key, item in body.items() if key != "receipt_sha256"}
        assert body["receipt_sha256"] == public_digest("cosmas-inbox-handoff-receipt.v1", unsigned)
    return body


def failure(value, status, code):
    assert response(value, status=status) == {"contract_version": 1, "error": {"code": code}}


def counts(session, c):
    return {
        model.__tablename__: session.scalar(
            select(func.count()).select_from(model).where(model.box_id == c["box"])
        )
        for model in (
            Ticket,
            Operation,
            AuditEvent,
            FollowUpReceipt,
            WorkHandoff,
            InboxEvent,
            InboxHandoffReceipt,
        )
    }


@pytest.fixture
def handoff_client(production_client, case):
    production_client.app.dependency_overrides[api._inbox_handoff_policy] = lambda: ON
    production_client.app.dependency_overrides[api._inbox_registry] = lambda: case["registry"]
    return production_client


def propose(client, c):
    return response(
        client.post(
            f"/workspaces/{c['wid']}/inbox-handoffs/propose",
            headers=headers(c),
            json=c["q"].public(),
        ),
        p.Response,
    )


def detail(client, c, tid, actor=None):
    return response(
        client.get(f"/inbox-handoffs/{tid}", headers=headers(c, actor)),
        p.Detail,
        maximum=65536,
    )


def command(client, c, tid, command_kind, actor=None, **values):
    current = detail(client, c, tid, actor)
    q = p.COMMANDS[command_kind].model_validate(
        {
            "ticket_id": tid,
            "expected_version": current["version"],
            "revision_id": current["revision_id"],
            "payload_hash": current["payload_hash"],
            "idempotency_key": command_kind + "-" + str(uuid4()),
            **values,
        }
    )
    value = response(
        client.post(
            f"/inbox-handoffs/{tid}/{command_kind}", headers=headers(c, actor), json=q.public()
        ),
        p.Response,
    )
    assert value["request_sha256"] == public_digest(
        "cosmas-inbox-handoff-request.v1",
        {"scope": value["scope"], "command_kind": command_kind, "request": q.public()},
    )
    return value, q


def accept(client, c):
    proposal = propose(client, c)
    tid = proposal["effect"]["ticket_id"]
    publication, _ = command(
        client, c, tid, "decide", choice="approve", publish_selected_context=True
    )
    offer, _ = command(client, c, tid, "handoff", kind="offer", recipient_id=c["staff"])
    acceptance, _ = command(
        client,
        c,
        tid,
        "handoff",
        actor=c["staff"],
        kind="accept",
        offer_id=offer["effect"]["effect_id"],
    )
    assert publication["outcome"] == acceptance["outcome"] == "recorded"
    return tid, proposal


def assert_no_private_source(value, c):
    text = json.dumps(value)
    assert all(
        secret not in text
        for secret in (
            "PRIVATE:",
            "transmit passwords",
            "spruce://",
            "invented_contact",
            c["wid"],
            c["iid"],
            c["q"].source_id,
            c["q"].review_receipt_id,
            str(c["grant"].grant_id),
        )
    )
    assert "private_source" not in value


def test_main_app_handoff_default_off_and_exact_registered_routes(production_client, session, case):
    c = case
    assert flow.DEFAULT_POLICY.enabled is False
    assert api._inbox_handoff_policy().enabled is False
    assert api._inbox_registry()().grants == {}
    for path, methods in (
        ("/inbox-handoffs", {"GET"}),
        ("/inbox-handoffs/{ticket_id}", {"GET"}),
        ("/workspaces/{workspace_id}/inbox-handoffs/{kind}", {"POST"}),
        ("/inbox-handoffs/{ticket_id}/{kind}", {"POST"}),
    ):
        installed = [route for route in api.app.routes if getattr(route, "path", "") == path]
        assert len(installed) == 1 and installed[0].methods == methods
    catalog = response(
        production_client.get("/inbox-handoffs", headers=headers(c)),
        p.Catalog,
        maximum=131072,
    )
    assert catalog["items"] == []
    before = counts(session, c)
    rejected = propose(production_client, c)
    assert rejected["outcome"] == "rejected" and rejected["rejection"] == "feature_disabled"
    assert rejected["effect"] is None
    before["inbox_handoff_receipts"] += 1
    assert counts(session, c) == before


def test_main_app_handoff_requires_workspace_inbox_and_handoff_flags(monkeypatch):
    assert api.settings.workspace_available
    for workspace_enabled, inbox_enabled, handoff_enabled in product((False, True), repeat=3):
        monkeypatch.setattr(api.settings, "workspace_enabled", workspace_enabled)
        monkeypatch.setattr(api.settings, "inbox_work_enabled", inbox_enabled)
        monkeypatch.setattr(api.settings, "inbox_handoff_enabled", handoff_enabled)
        assert api._inbox_handoff_policy().enabled is (
            workspace_enabled and inbox_enabled and handoff_enabled
        )


def test_main_app_enabled_handoff_cannot_infer_inbound_grant(production_client, session, case):
    c = case
    production_client.app.dependency_overrides[api._inbox_handoff_policy] = lambda: ON
    assert api._inbox_registry()().grants == {}
    before = counts(session, c)
    rejected = propose(production_client, c)
    assert rejected["outcome"] == "rejected" and rejected["rejection"] == "authority_changed"
    before["inbox_handoff_receipts"] += 1
    assert counts(session, c) == before


def test_main_app_exact_handoff_header_query_and_route_boundary(production_client, session, case):
    c = case
    before = counts(session, c)
    for mode in ("missing", "wrong", "duplicate", "query", "other_route"):
        path, h = "/inbox-handoffs", headers(c)
        if mode == "missing":
            h.pop("X-Cosmas-Inbox-Handoff-Contract")
        elif mode == "wrong":
            h["X-Cosmas-Inbox-Handoff-Contract"] = "2"
        elif mode == "query":
            path += "?unexpected=1"
        elif mode == "other_route":
            path = "/queue"
        values = list(h.items())
        if mode == "duplicate":
            values.append(("X-Cosmas-Inbox-Handoff-Contract", "1"))
        failure(production_client.get(path, headers=values), 426, "inbox_handoff_contract_required")
    assert counts(session, c) == before


def test_main_app_handoff_methods_and_unknown_commands_fail_closed(handoff_client, session, case):
    client, c = handoff_client, case
    before = counts(session, c)
    for method, path in (
        ("POST", "/inbox-handoffs"),
        ("PUT", "/inbox-handoffs"),
        ("GET", f"/workspaces/{c['wid']}/inbox-handoffs/propose"),
        ("DELETE", f"/inbox-handoffs/{uuid4()}"),
    ):
        failure(
            client.request(method, path, headers=headers(c), follow_redirects=False),
            405,
            "inbox_handoff_unavailable",
        )
    for path in (
        f"/workspaces/{c['wid']}/inbox-handoffs/publish",
        f"/inbox-handoffs/{uuid4()}/reply",
    ):
        failure(client.post(path, headers=headers(c), json={}), 400, "invalid_inbox_handoff")
    failure(
        client.get("/inbox-handoffs/not-a-uuid", headers=headers(c)),
        422,
        "inbox_handoff_unavailable",
    )
    assert counts(session, c) == before


def test_main_app_handoff_rejects_duplicate_unknown_null_and_encoded_input(
    handoff_client,
    session,
    case,
):
    client, c = handoff_client, case
    path = f"/workspaces/{c['wid']}/inbox-handoffs/propose"
    raw = canonical(c["q"].public())
    h = headers(c) | {"Content-Type": "application/json"}
    before = counts(session, c)
    for body, request_headers in (
        (b'{"reviewed_minimum_context":true,' + raw[1:], h),
        (canonical(c["q"].public() | {"raw_message": "PRIVATE: forbidden input"}), h),
        (canonical(c["q"].public() | {"selected_context": None}), h),
        (raw, h | {"Content-Type": "text/plain"}),
        (raw, h | {"Content-Encoding": "gzip"}),
        (raw, [*h.items(), ("Content-Type", "application/json")]),
    ):
        failure(
            client.post(path, headers=request_headers, content=body), 400, "invalid_inbox_handoff"
        )
    assert counts(session, c) == before


def test_main_app_handoff_enforces_inclusive_8kib_post_cap(handoff_client, session, case):
    client, c = handoff_client, case
    path = f"/workspaces/{c['wid']}/inbox-handoffs/propose"
    raw = canonical(c["q"].public())
    assert len(raw) < 8192
    exact = raw + b" " * (8192 - len(raw))
    multibyte = canonical(c["q"].public() | {"instructions": "🧪" * 2000})
    assert len(multibyte) > 8192
    h = headers(c) | {"Content-Type": "application/json"}
    before = counts(session, c)
    for oversized in (exact + b" ", multibyte):
        failure(client.post(path, headers=h, content=oversized), 413, "invalid_inbox_handoff")
    assert counts(session, c) == before
    recorded = response(client.post(path, headers=h, content=exact), p.Response)
    assert recorded["outcome"] == "recorded"
    after = counts(session, c)
    assert response(client.post(path, headers=h, content=exact), p.Response) == recorded
    assert counts(session, c) == after


def test_main_app_handoff_preflight_never_authenticates_and_denies_unknown_origin(
    production_client,
    case,
):
    def no_identity():
        raise AssertionError("Preflight must not authenticate")

    production_client.app.dependency_overrides[api._identity] = no_identity
    for method, path in (
        ("GET", "/inbox-handoffs"),
        ("POST", f"/workspaces/{case['wid']}/inbox-handoffs/propose"),
    ):
        h = {
            "Origin": api.settings.allowed_origins[0],
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type,x-cosmas-inbox-handoff-contract",
        }
        allowed = production_client.options(path, headers=h)
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == h["Origin"]
        assert (
            "x-cosmas-inbox-handoff-contract"
            in allowed.headers["access-control-allow-headers"].lower()
        )
        denied = production_client.options(
            path, headers=h | {"Origin": "https://unapproved.invalid"}
        )
        assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers


def test_main_app_unpublished_handoff_and_workspace_proofs_remain_owner_private(
    handoff_client,
    session,
    case,
):
    client, c = handoff_client, case
    receipt = propose(client, c)
    tid = receipt["effect"]["ticket_id"]
    owner = detail(client, c, tid)
    assert owner["private_source"]["item_id"] == c["iid"]
    assert owner["instructions"] == c["q"].instructions and not owner["publication_active"]
    query = {key: receipt[key] for key in ("command_kind", "idempotency_key", "request_sha256")}
    before = counts(session, c)
    for actor in (c["staff"], c["peer"]):
        h = headers(c, actor)
        catalog = response(client.get("/inbox-handoffs", headers=h), p.Catalog, maximum=131072)
        assert catalog["items"] == []
        for value in (
            client.get(f"/inbox-handoffs/{tid}", headers=h),
            client.post(f"/inbox-handoffs/{tid}/resolve", headers=h, json=query),
            client.post(f"/workspaces/{c['wid']}/inbox-handoffs/resolve", headers=h, json=query),
            client.post(
                f"/workspaces/{c['wid']}/inbox-handoffs/propose", headers=h, json=c["q"].public()
            ),
        ):
            failure(value, 404, "inbox_handoff_unavailable")
            assert tid not in value.text and receipt["receipt_id"] not in value.text
            assert_no_private_source(value.json(), c)
    assert counts(session, c) == before


def test_main_app_owner_publication_offer_staff_result_and_owner_verification(
    handoff_client,
    session,
    case,
):
    client, c = handoff_client, case
    tid = propose(client, c)["effect"]["ticket_id"]
    publication, _ = command(
        client, c, tid, "decide", choice="approve", publish_selected_context=True
    )
    assert publication["effect"]["state"] == "approved"
    offer, _ = command(client, c, tid, "handoff", kind="offer", recipient_id=c["staff"])
    offered = detail(client, c, tid, c["staff"])
    assert offered["responsible_id"] == c["actor"] and offered["publication_active"]
    assert offered["instructions"] == c["q"].instructions
    assert offered["selected_context"] == c["q"].selected_context
    assert_no_private_source(offered, c)
    premature, _ = command(
        client,
        c,
        tid,
        "result",
        actor=c["staff"],
        evidence="Not accepted yet",
        no_external_action_claimed=True,
    )
    assert (
        premature["outcome"] == "rejected" and premature["rejection"] == "responsibility_required"
    )
    accepted, _ = command(
        client,
        c,
        tid,
        "handoff",
        actor=c["staff"],
        kind="accept",
        offer_id=offer["effect"]["effect_id"],
    )
    assert accepted["outcome"] == "recorded"
    assert detail(client, c, tid, c["staff"])["responsible_id"] == c["staff"]
    result, _ = command(
        client,
        c,
        tid,
        "result",
        actor=c["staff"],
        evidence="Reviewed the administrative question locally; no outbound message.",
        no_external_action_claimed=True,
    )
    assert result["effect"]["state"] == "approved"
    current = detail(client, c, tid, c["staff"])
    verification = {
        "result_receipt_id": current["result"]["receipt_id"],
        "result_request_sha256": current["result"]["request_sha256"],
        "reviewed_current_source": True,
        "reviewed_result": True,
        "local_handoff_only": True,
    }
    denied_request = p.Verify(
        ticket_id=tid,
        expected_version=current["version"],
        revision_id=current["revision_id"],
        payload_hash=current["payload_hash"],
        idempotency_key="staff-verify-" + str(uuid4()),
        **verification,
    )
    failure(
        client.post(
            f"/inbox-handoffs/{tid}/verify",
            headers=headers(c, c["staff"]),
            json=denied_request.public(),
        ),
        404,
        "inbox_handoff_unavailable",
    )
    verified, _ = command(client, c, tid, "verify", **verification)
    assert verified["effect"]["state"] == "closed"
    final = detail(client, c, tid, c["staff"])
    assert final["verified_current"] and final["external_action_performed"] is False
    assert_no_private_source(final, c)
    assert session.get(EncounterWorkspace, c["wid"]).revision == 3
    operations = list(session.scalars(select(Operation).where(Operation.ticket_id == tid)))
    assert len(operations) == 1 and operations[0].adapter == flow.ADAPTER
    assert (
        session.scalar(
            select(func.count()).select_from(WorkHandoff).where(WorkHandoff.ticket_id == tid)
        )
        == 2
    )


def test_main_app_generic_shared_and_other_provider_paths_withhold_handoff_content(
    handoff_client,
    session,
    case,
    other_humans,
):
    client, c = handoff_client, case
    tid, _ = accept(client, c)
    current = detail(client, c, tid)
    before = counts(session, c)
    for actor in (c["actor"], c["staff"], *other_humans):
        h = identity(c, actor) | {"Origin": api.settings.allowed_origins[0]}
        for path in ("/queue", "/practice-work"):
            generic = client.get(path, headers=h)
            assert generic.status_code == 200, generic.text
            assert tid not in generic.text and c["q"].instructions not in generic.text
        audit = client.get(f"/tickets/{tid}/timeline", headers=h)
        assert audit.status_code == 403 and c["q"].selected_context not in audit.text
        for kind, body in (
            ("edit", {"body": "Forbidden"}),
            ("decide", {"kind": "approve"}),
            ("close", {}),
        ):
            denied = client.post(f"/tickets/{tid}/{kind}", headers=h, json=body)
            assert denied.status_code == 403 and c["q"].instructions not in denied.text
        unversioned = client.get(f"/practice-work/{tid}", headers=h)
        assert unversioned.status_code == 426
        assert unversioned.json() == {"detail": "inbox_handoff_contract_required"}
    for actor in (c["actor"], c["staff"]):
        h = identity(c, actor)
        bound = {key: current[key] for key in ("revision_id", "payload_hash")}
        bound |= {
            "expected_version": current["version"],
            "idempotency_key": "legacy-" + str(uuid4()),
        }
        for suffix, body in (
            ("handoffs", bound | {"kind": "offer", "recipient_id": c["peer"]}),
            ("complete", bound | {"evidence": "Forbidden legacy result"}),
        ):
            denied = client.post(f"/practice-work/{tid}/{suffix}", headers=h, json=body)
            assert denied.status_code == 426
            assert denied.json() == {"detail": "inbox_handoff_contract_required"}
    original = session.get(EncounterWorkspace, c["wid"])
    for actor in other_humans:
        h = identity(c, actor) | {"Origin": api.settings.allowed_origins[0]}
        created = client.post(
            "/workspaces",
            headers=h,
            json={
                "appointment_id": original.appointment_id,
                "idempotency_key": "other-incoming-workspace-" + str(uuid4()),
            },
        )
        assert created.status_code == 200, created.text
        before["audit_events"] += 1  # The explicitly created private workspace has its own audit.
        theirs = created.json()
        assert tid not in created.text and c["q"].instructions not in created.text
        denied = client.post(
            f"/workspaces/{theirs['id']}/work-links",
            headers=h,
            json={
                "ticket_id": tid,
                "expected_revision": 1,
                "idempotency_key": "forbidden-incoming-link-" + str(uuid4()),
            },
        )
        assert denied.status_code == 404 and denied.json() == {"detail": "work_unavailable"}
        failure(
            client.get(f"/inbox-handoffs/{tid}", headers=headers(c, actor)),
            404,
            "inbox_handoff_unavailable",
        )
    assert counts(session, c) == before


@pytest.mark.parametrize("change", ["registry", "source"])
def test_main_app_stale_shared_projection_keeps_only_accountable_attention(
    handoff_client,
    session,
    case,
    change,
):
    client, c = handoff_client, case
    tid, _ = accept(client, c)
    command(
        client,
        c,
        tid,
        "result",
        actor=c["staff"],
        evidence="Saved local result before source changes",
        no_external_action_claimed=True,
    )
    before = detail(client, c, tid, c["staff"])
    if change == "registry":
        c["registry_state"]["registry"] = inbox.InboxRegistry([])
    else:
        ingest(session, c, snapshot(c, 20, text_="PRIVATE: changed incoming source"))
    after = detail(client, c, tid, c["staff"])
    assert after["state"] == "source_unavailable" and after["requires_owner_attention"]
    assert not after["publication_active"] and not after["verified_current"]
    assert after["originator_id"] == c["actor"] and after["responsible_id"] == c["staff"]
    assert after["handoffs"] == before["handoffs"]
    assert all(
        after[key] is None
        for key in (
            "instructions",
            "selected_context",
            "due_date",
            "expected_outcome",
            "result",
        )
    )
    assert_no_private_source(after, c)
    catalog = response(
        client.get("/inbox-handoffs", headers=headers(c, c["staff"])),
        p.Catalog,
        maximum=131072,
    )
    assert len(catalog["items"]) == 1 and catalog["items"][0]["requires_owner_attention"]
    assert_no_private_source(catalog, c)
    original = counts(session, c)
    rejected, _ = command(
        client,
        c,
        tid,
        "result",
        actor=c["staff"],
        evidence="Must remain inert after authority changes",
        no_external_action_claimed=True,
    )
    assert rejected["outcome"] == "rejected"
    assert rejected["rejection"] == (
        "authority_changed" if change == "registry" else "source_changed"
    )
    original["inbox_handoff_receipts"] += 1
    assert counts(session, c) == original


def test_main_app_exact_owner_and_staff_resolve_survive_disable_and_empty_registry(
    handoff_client,
    session,
    case,
):
    client, c = handoff_client, case
    tid, proposal = accept(client, c)
    result, request = command(
        client,
        c,
        tid,
        "result",
        actor=c["staff"],
        evidence="Saved result recovered after disable",
        no_external_action_claimed=True,
    )
    client.app.dependency_overrides[api._inbox_handoff_policy] = lambda: flow.Policy()
    client.app.dependency_overrides.pop(api._inbox_registry)
    before = counts(session, c)
    for actor, receipt, root, replay_path, body in (
        (
            c["actor"],
            proposal,
            f"/workspaces/{c['wid']}/inbox-handoffs",
            f"/workspaces/{c['wid']}/inbox-handoffs/propose",
            c["q"].public(),
        ),
        (
            c["staff"],
            result,
            f"/inbox-handoffs/{tid}",
            f"/inbox-handoffs/{tid}/result",
            request.public(),
        ),
    ):
        query = {key: receipt[key] for key in ("command_kind", "idempotency_key", "request_sha256")}
        h = headers(c, actor)
        recovered = response(client.post(root + "/resolve", headers=h, json=query), p.Response)
        assert recovered == receipt
        assert response(client.post(replay_path, headers=h, json=body), p.Response) == receipt
        failure(
            client.post(root + "/resolve", headers=h, json=query | {"request_sha256": "f" * 64}),
            409,
            "inbox_handoff_idempotency_conflict",
        )
        failure(
            client.post(root + "/resolve", headers=headers(c, c["peer"]), json=query),
            404,
            "inbox_handoff_unavailable",
        )
    assert result["scope"]["kind"] == "ticket" and result["scope"]["id"] == tid
    assert_no_private_source(result, c)
    assert counts(session, c) == before


def test_main_app_handoff_reauthenticates_before_disclosure(
    handoff_client,
    session,
    case,
    monkeypatch,
):
    c = case
    before = counts(session, c)

    def revoked(**kwargs):
        raise WorkspaceError("inbox_unavailable", 403)

    monkeypatch.setattr(api, "_identity", revoked)
    failure(
        handoff_client.get("/inbox-handoffs", headers=headers(c)),
        403,
        "inbox_handoff_unavailable",
    )
    assert counts(session, c) == before
