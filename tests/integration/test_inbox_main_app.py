"""Inbox registration, privacy and negotiation through the real application."""

import pytest
from sqlalchemy import func, select
from tests.integration.test_inbox_work import ON, ingest, review
from tests.integration.test_inbox_work import inbox_case as inbox_case
from tests.integration.test_membership_privacy import identity
from tests.integration.test_membership_privacy import other_humans as other_humans
from tests.integration.test_membership_privacy import (
    production_client as production_client,
)
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.api import app as api
from cosmas_os.application import inbox_work as flow
from cosmas_os.inbox_models import InboxEvent
from cosmas_os.models import AuditEvent, Operation, Ticket


def headers(c, actor=None):
    return identity(c, actor) | {
        "X-Cosmas-Inbox-Contract": "1",
        "Origin": api.settings.allowed_origins[0],
    }


def test_main_app_inbox_defaults_have_no_read_authority(production_client, inbox_case):
    assert api._inbox_policy().enabled is False
    assert api._inbox_registry()().grants == {}
    paths = [r for r in api.app.routes if getattr(r, "path", "") == "/inbox"]
    assert len(paths) == 1 and getattr(paths[0], "methods", None) == {"GET"}
    response = production_client.get("/inbox", headers=headers(inbox_case))
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False and response.json()["items"] == []


def test_main_app_exact_receipt_survives_disabled_policy_and_empty_registry(
    production_client,
    session,
    inbox_case,
    other_humans,
):
    client, c = production_client, inbox_case
    iid = ingest(session, c)["item_id"]
    receipt = review(session, c, iid)
    source = flow.detail(session, c["box"], c["actor"], iid, registry=c["registry"], policy=ON)[
        "source"
    ]
    before = [
        session.scalar(select(func.count()).select_from(t))
        for t in (Ticket, Operation, AuditEvent, InboxEvent)
    ]
    query = {
        "item_id": iid,
        "command_kind": "review",
        "idempotency_key": receipt["idempotency_key"],
        "request_sha256": receipt["request_sha256"],
    }
    h = headers(c)
    response = client.post("/inbox/resolve", headers=h, json=query)
    assert response.status_code == 200 and response.json() == receipt, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == h["Origin"]
    assert len(response.content) <= 8192
    for path in (
        f"/inbox/{iid}",
        f"/inbox/{iid}/history",
        f"/inbox/{iid}/sources/{source['source_id']}",
    ):
        owner = client.get(path, headers=h)
        assert owner.status_code == 200, owner.text
        for actor in other_humans:
            denied = client.get(path, headers=headers(c, actor))
            assert denied.status_code == 404
            assert iid not in denied.text and "invented_contact" not in denied.text
    for actor in other_humans:
        assert (
            client.post("/inbox/resolve", headers=headers(c, actor), json=query).status_code == 404
        )
    for actor in [c["actor"], *other_humans]:
        for path in ("/queue", "/practice-work"):
            text = client.get(path, headers=identity(c, actor)).text
            assert iid not in text and receipt["receipt_id"] not in text
    assert [
        session.scalar(select(func.count()).select_from(t))
        for t in (Ticket, Operation, AuditEvent, InboxEvent)
    ] == before


@pytest.mark.parametrize("mode", ["missing", "wrong", "duplicate", "query", "other_route"])
def test_main_app_inbox_contract_is_private_and_cors_wraps_errors(
    production_client,
    session,
    inbox_case,
    mode,
):
    c, client = inbox_case, production_client
    path, h = "/inbox", headers(c)
    if mode == "missing":
        h.pop("X-Cosmas-Inbox-Contract")
    elif mode == "wrong":
        h["X-Cosmas-Inbox-Contract"] = "2"
    elif mode == "query":
        path += "?unexpected=1"
    elif mode == "other_route":
        path = "/queue"
    values = list(h.items())
    if mode == "duplicate":
        values.append(("X-Cosmas-Inbox-Contract", "1"))
    before = session.scalar(select(func.count()).select_from(InboxEvent))
    response = client.get(path, headers=values)
    assert (
        response.status_code == 426
        and response.json()["error"]["code"] == "inbox_contract_required"
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == h["Origin"]
    assert session.scalar(select(func.count()).select_from(InboxEvent)) == before


def test_main_app_inbox_preflight_never_authenticates(production_client):
    client = production_client

    def deny_auth():
        raise AssertionError("Preflight must not authenticate")

    client.app.dependency_overrides[api._identity] = deny_auth
    h = {
        "Origin": api.settings.allowed_origins[0],
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,x-cosmas-inbox-contract",
    }
    response = client.options("/inbox", headers=h)
    assert (
        response.status_code == 200
        and response.headers["access-control-allow-origin"] == h["Origin"]
    )
    denied = client.options("/inbox", headers=h | {"Origin": "https://unapproved.invalid"})
    assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers


def test_main_app_inbox_rejects_oversized_command_without_admission(
    production_client,
    session,
    inbox_case,
):
    c, client = inbox_case, production_client
    iid = ingest(session, c)["item_id"]
    client.app.dependency_overrides[api._inbox_policy] = lambda: ON
    client.app.dependency_overrides[api._inbox_registry] = lambda: c["registry"]
    before = session.scalar(select(func.count()).select_from(InboxEvent))
    response = client.post(
        f"/inbox/{iid}/triage",
        headers=headers(c) | {"Content-Type": "application/json"},
        content=b" " * 8193,
    )
    assert (
        response.status_code == 413 and response.json()["error"]["code"] == "invalid_inbox_request"
    )
    assert response.headers["access-control-allow-origin"] == headers(c)["Origin"]
    assert session.scalar(select(func.count()).select_from(InboxEvent)) == before


def test_main_app_review_options_default_off_and_current_owner_scope(
    production_client,
    session,
    inbox_case,
    other_humans,
):
    c, client = inbox_case, production_client
    iid = ingest(session, c)["item_id"]
    path = f"/inbox/{iid}/review-options"
    h = headers(c)
    before = session.scalar(select(func.count()).select_from(InboxEvent))
    disabled = client.get(path, headers=h)
    assert (
        disabled.status_code == 403 and disabled.json()["error"]["code"] == "inbox_feature_disabled"
    )
    client.app.dependency_overrides[api._inbox_policy] = lambda: ON
    client.app.dependency_overrides[api._inbox_registry] = lambda: c["registry"]
    response = client.get(path, headers=h)
    assert response.status_code == 200, response.text
    assert [v["workspace_id"] for v in response.json()["choices"]] == [c["wid"]]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == h["Origin"]
    assert len(response.content) <= 131072
    for actor in other_humans:
        denied = client.get(path, headers=headers(c, actor))
        assert denied.status_code == 404
        assert c["wid"] not in denied.text and iid not in denied.text
    assert session.scalar(select(func.count()).select_from(InboxEvent)) == before


@pytest.mark.parametrize("mode", ["missing", "duplicate", "wrong", "query"])
def test_main_app_review_options_share_exact_inbox_boundary(production_client, inbox_case, mode):
    c, client = inbox_case, production_client
    path = f"/inbox/{c['grant'].grant_id}/review-options"
    h = headers(c)
    if mode == "missing":
        h.pop("X-Cosmas-Inbox-Contract")
    elif mode == "wrong":
        h["X-Cosmas-Inbox-Contract"] = "2"
    elif mode == "query":
        path += "?unexpected=1"
    values = list(h.items())
    if mode == "duplicate":
        values.append(("X-Cosmas-Inbox-Contract", "1"))
    response = client.get(path, headers=values)
    assert (
        response.status_code == 426
        and response.json()["error"]["code"] == "inbox_contract_required"
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == h["Origin"]
