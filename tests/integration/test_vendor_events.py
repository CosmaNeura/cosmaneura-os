"""Real PostgreSQL candidate custody with exact signed raw HTTP inputs."""

import base64
import hmac
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.integration.test_vendor_work import (  # noqa: F401
    acceptance,
    approved,
    bound,
    call,
    gates,
    immediate,
)
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.api import app as api
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_events as events
from cosmas_os.application import vendor_execution as execution
from cosmas_os.application import vendor_work as work
from cosmas_os.config import settings
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.vendor_models import (
    VendorConnectionVersion,
    VendorEventCandidate,
    VendorProviderObservation,
)

SECRET = b"invented-local-webhook-secret"


def route(case):
    c = case["config"]
    return events.EventRoute(c.routing["event_route_id"], c.id, c.vendor, SECRET)


def raw_event(request="invented_request", item="invented_item"):
    return json.dumps(
        {
            "object": "event",
            "type": "conversationItem.created",
            "eventTime": "2026-09-21T00:00:00Z",
            "data": {"object": {"id": item, "requestId": request}},
        },
        separators=(",", ":"),
    ).encode()


def signature(raw):
    return base64.b64encode(hmac.digest(SECRET, raw, "sha256")).decode()


def count(s, model, c):
    return s.scalar(select(func.count()).select_from(model).where(model.owner_id == c["actor"]))


def test_signed_exact_correlation_only_enables_explicit_read_and_deduplicates(
    session, vendor_case, monkeypatch
):
    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    monkeypatch.setattr(settings, "vendor_events_enabled", True)
    tid, detail = approved(session, c)
    _, invocation = call(
        session, c, execution.claim_submit, tid, public.BoundCommand(**bound(detail))
    )
    execution.mark_invocation(session, invocation)
    execution.settle(session, invocation, observation=acceptance(invocation))
    before = count(session, VendorProviderObservation, c)
    body = raw_event()
    assert events.ingest(session, route(c), body, signature=signature(body)) == {"received": True}
    immediate(session)
    assert count(session, VendorEventCandidate, c) == 1
    assert count(session, VendorProviderObservation, c) == before + 1
    result = call(session, c, work.detail, tid)
    assert result["summary"]["transport"] == "pending"
    assert result["summary"]["state"] != "closed"
    _, read = call(session, c, execution.claim_read, tid, public.BoundCommand(**bound(result)))
    assert read.reference.kind == "conversation_item" and read.reference.value == "invented_item"
    assert events.ingest(session, route(c), body, signature=signature(body)) == {"received": True}
    assert count(session, VendorEventCandidate, c) == 1
    assert count(session, VendorProviderObservation, c) == before + 1


def test_signed_unmatched_request_does_not_invent_a_read_reference(
    session, vendor_case, monkeypatch
):
    monkeypatch.setattr(settings, "vendor_events_enabled", True)
    body = raw_event(request="unrelated_request")
    events.ingest(session, route(vendor_case), body, signature=signature(body))
    immediate(session)
    assert count(session, VendorEventCandidate, vendor_case) == 1
    assert count(session, VendorProviderObservation, vendor_case) == 0
    stored = session.scalar(
        select(VendorEventCandidate).where(VendorEventCandidate.owner_id == vendor_case["actor"])
    )
    assert set(stored.correlation) <= {"event_type", "object_id", "request_id", "event_id"}
    assert "eventTime" not in stored.correlation


@pytest.mark.parametrize(
    "vendor,body",
    [
        ("srfax", b"FaxDetailsID=123&SentStatus=Sent"),
        ("documo", b'{"messageId":"11111111-1111-4111-8111-111111111111","status":"delivered"}'),
    ],
)
def test_unsigned_hints_store_candidate_without_transport_or_reference(
    session, vendor_case, monkeypatch, vendor, body
):
    monkeypatch.setattr(settings, "vendor_events_enabled", True)
    old = vendor_case["config"]
    cid, route_id = str(uuid4()), str(uuid4())
    selection = private.ConnectionSelection.model_validate(
        {
            **old.private_selection,
            "vendor": vendor,
            "connection_id": cid,
            "remote_account_id": "123456" if vendor == "srfax" else str(uuid4()),
        }
    )
    view = {**old.public_view, "id": cid, "vendor": vendor, "actions": [vendor + "_fax"]}
    view.pop("public_sha256")
    view["public_sha256"] = public.public_digest("cosmas-vendor-public-selection.v1", view)
    config = VendorConnectionVersion(
        id=cid,
        family_id=str(uuid4()),
        revision=1,
        box_id=old.box_id,
        owner_id=old.owner_id,
        vendor=vendor,
        environment=old.environment,
        private_selection=selection.model_dump(mode="json"),
        routing={"event_route_id": route_id},
        private_sha256=selection.commitment(),
        public_view=view,
        public_sha256=view["public_sha256"],
        reviewed_by=old.reviewed_by,
        reviewed_at=old.reviewed_at,
        write_enabled=False,
        read_enabled=False,
    )
    session.add(config)
    session.commit()
    configured = events.EventRoute(route_id, cid, vendor)
    events.ingest(session, configured, body)
    immediate(session)
    assert count(session, VendorEventCandidate, vendor_case) == 1
    assert count(session, VendorProviderObservation, vendor_case) == 0
    assert (
        session.scalar(
            select(VendorEventCandidate).where(VendorEventCandidate.connection_version_id == cid)
        ).authenticity
        == "untrusted_hint"
    )


def test_callback_http_exact_raw_signature_default_off_and_body_limit(
    session, vendor_case, monkeypatch
):
    c = vendor_case
    configured = route(c)
    url = "/vendor-events/spruce/" + configured.route_id
    api.app.dependency_overrides[api.get_session] = lambda: session
    api.app.dependency_overrides[api._vendor_event_routes] = lambda: (
        lambda family, rid: (
            configured if (family, rid) == (configured.vendor, configured.route_id) else None
        )
    )
    try:
        with TestClient(api.app) as client:
            body = raw_event()
            h = {"X-Spruce-Signature": signature(body)}
            assert client.post(url, content=body, headers=h).status_code == 404
            monkeypatch.setattr(settings, "vendor_events_enabled", True)
            assert client.post(url, content=body + b" ", headers=h).status_code == 400
            assert (
                client.post(url, content=body, headers=[*h.items(), *h.items()]).status_code == 400
            )
            assert (
                client.post(
                    url, content=b"x" * 1048577, headers={**h, "Content-Length": "1"}
                ).status_code
                == 413
            )
            response = client.post(url, content=body, headers=h)
            assert response.status_code == 200 and response.json() == {"received": True}
            assert len(response.content) < 1024 and response.headers["cache-control"] == "no-store"
            assert client.post(url, content=body, headers=h).json() == {"received": True}
            assert (
                client.post(
                    url, content=body, headers={**h, "X-Cosmas-Vendor-Contract": "1"}
                ).status_code
                == 426
            )
            assert client.post(url + "?key=forbidden", content=body, headers=h).status_code == 400
        assert count(session, VendorEventCandidate, c) == 1
        assert count(session, VendorProviderObservation, c) == 0
    finally:
        api.app.dependency_overrides.clear()
