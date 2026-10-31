"""Real signed HTTP admission adapter; provider/Clerk fixtures are explicitly synthetic."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from contextvars import Context
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select

from cosmas_os.adapters.enrollment_admission import (
    ACCESS_REQUIRED,
    ADMISSION_UNAVAILABLE,
    EnrollmentAdmissionAdapter,
    RuntimeAdmissionError,
)
from cosmas_os.config import Settings
from cosmas_os.enrollment.admission import (
    ADMISSION_HEADER,
    AdmissionRequest,
    derive_runtime_admission_key,
    encode,
    signature,
)
from cosmas_os.enrollment.models import Account, EnrollmentBase, Membership, Practice
from cosmas_os.enrollment.synthetic import create_synthetic_app


def body_for(case, *, purpose: Literal["workspace", "qualification", "worker"] = "workspace", subject=None):
    token = case.token
    return AdmissionRequest(practice_id=case.practice_id, box_id=case.box_id, organization_id=case.org,
        issuer=case.issuer, subject=subject or "user_synthetic_owner-a", purpose=purpose, nonce=str(uuid4()), issued_at=int(time.time()),
        token_sha256=hashlib.sha256(token.encode()).hexdigest())


@pytest.fixture
def admission_case(request):
    engine = None
    if request.module.__name__.endswith("test_runtime_workspace"):
        url = os.environ["ENROLLMENT_TEST_DATABASE_URL"]
        engine = create_engine(url, pool_pre_ping=True)
        assert engine.url.host == "127.0.0.1" and engine.url.database == "enrollment_synthetic"
    app = create_synthetic_app(engine=engine)
    if engine is not None:
        with engine.begin() as connection:
            tables = ",".join(engine.dialect.identifier_preparer.format_table(t) for t in EnrollmentBase.metadata.sorted_tables)
            connection.exec_driver_sql("TRUNCATE TABLE " + tables + " RESTART IDENTITY CASCADE")
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + client.post("/lab/session", json={"user": "owner-a"}).json()["token"]}
        def write(path, body, method="POST"):
            revision = client.get("/enrollment/v1/status", headers=headers).json()["revision"]
            result = client.request(method, "/enrollment/v1" + path, headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"expected_revision": revision, **body})
            assert result.status_code == 200, result.text
            return result.json()
        write("/profile", {"display_name": "Alex Example", "title": "Owner"}, "PUT")
        state = write("/practice", {"legal_name": "Example Clinic LLC", "display_name": "Example Clinic", "address_line1": "123 Example Street",
            "city": "Example City", "region": "NY", "postal_code": "10001", "administrative_email": "office@example.invalid", "human_seats": 2, "covered_entity": True}, "PUT")
        document = client.get("/enrollment/v1/baa/current", headers=headers).json()
        write("/baa/accept", {"doc_id": document["doc_id"], "version": document["version"], "sha256": document["sha256"],
            "signature_name": "Alex Example", "signature_title": "Owner", "authority_confirmed": True, "accepted": True})
        client.post("/lab/qualify", json={"practice_id": state["practice"]["id"]})
        current = client.get("/enrollment/v1/status", headers=headers).json()
        practice_id, box_id, org = current["practice"]["id"], current["workspace"]["box_id"], current["workspace"]["organization_id"]
        token = client.post("/lab/session", json={"user": "owner-a", "organization_id": org}).json()["token"]
        master = app.state.enrollment_settings.runtime_admission_secret.get_secret_value()
        key = derive_runtime_admission_key(master, practice_id, box_id, org)
        runtime = Settings(_env_file=None, cosmas_env="early_adopter_beta", data_mode="synthetic", auth_mode="clerk_jwt",  # pyright: ignore[reportCallIssue]
            workspace_enrollment_managed=True, workspace_enrollment_practice_id=practice_id, beta_box_id=box_id,
            clerk_issuer=app.state.enrollment_settings.clerk_issuer, clerk_organization_id=org, clerk_session_policy="enrollment_default", clerk_audience="",
            workspace_enrollment_api_origin="https://enrollment.example.invalid", workspace_enrollment_origin_allowlist="https://enrollment.example.invalid,https://app.example.invalid",
            workspace_enrollment_admission_secret=SecretStr(key), workspace_enrollment_account_origin="https://app.example.invalid")
        def transport(request):
            # An actual HTTPS server has its own execution context. Do not carry
            # the runtime's PostgreSQL-only capture budget into the control app.
            result = Context().run(client.post, request.url.path, content=request.content, headers=dict(request.headers))
            return httpx.Response(result.status_code, content=result.content, headers=dict(result.headers))
        adapter = EnrollmentAdmissionAdapter(runtime, client=httpx.Client(transport=httpx.MockTransport(transport)))
        case = SimpleNamespace(app=app, client=client, token=token, write=write, runtime=runtime, adapter=adapter,
            key=key, master=master, practice_id=practice_id, box_id=box_id, org=org, issuer=runtime.clerk_issuer,
            headers=headers, transport=transport)
        yield case


def activate(case):
    checkout = case.write("/checkout", {})
    session_id = next(iter(case.app.state.synthetic_commerce.sessions))
    assert checkout["status"] == "open"
    assert case.client.post("/lab/checkout/complete", json={"session_id": session_id}).status_code == 200


def test_setup_proof_before_checkout_then_bound_runtime_and_worker_access(admission_case):
    c = admission_case
    assert c.adapter.authorize(c.token, "user_synthetic_owner-a", purpose="qualification")["purpose"] == "qualification"
    assert not c.app.state.synthetic_commerce.sessions
    with pytest.raises(RuntimeAdmissionError) as denied:
        c.adapter.authorize(c.token, "user_synthetic_owner-a")
    assert denied.value.code == ACCESS_REQUIRED
    activate(c)
    assert c.adapter.authorize(c.token, "user_synthetic_owner-a")["enforced"] is True
    assert c.adapter.authorize("", "user_synthetic_owner-a", purpose="worker", operation_id=str(uuid4()), approval_sha256="a" * 64)["purpose"] == "worker"
    with pytest.raises(RuntimeAdmissionError):
        c.adapter.authorize("", "user_synthetic_staff-a", purpose="worker", operation_id=str(uuid4()), approval_sha256="a" * 64)
    with c.app.state.enrollment_service.sessions.begin() as session:
        owner = session.scalar(select(Account).where(Account.subject == "user_synthetic_owner-a"))
        owner.active_practice_id = None
    assert c.adapter.authorize(c.token, "user_synthetic_owner-a")["enforced"] is True


@pytest.mark.parametrize("state", ["canceled", "unpaid", "past_due", "revoked", "stale"])
def test_runtime_and_worker_fail_closed_and_recover(admission_case, state):
    c = admission_case
    activate(c)
    with c.app.state.enrollment_service.sessions.begin() as session:
        practice = session.get(Practice, c.practice_id)
        member = session.scalar(select(Membership).where(Membership.practice_id == c.practice_id, Membership.role == "owner"))
        if state == "revoked":
            member.active = False
        elif state == "stale":
            practice.billing_verified_at = datetime.now(UTC) - timedelta(minutes=6)
            c.app.state.synthetic_commerce.fail_reads = True
        else:
            practice.subscription_status = state
    for worker in (False, True):
        kwargs = {"purpose": "worker", "operation_id": str(uuid4()), "approval_sha256": "a" * 64} if worker else {}
        with pytest.raises(RuntimeAdmissionError) as denied:
            c.adapter.authorize("" if worker else c.token, "user_synthetic_owner-a", **kwargs)
        assert denied.value.code == ACCESS_REQUIRED
    c.app.state.synthetic_commerce.fail_reads = False
    with c.app.state.enrollment_service.sessions.begin() as session:
        practice = session.get(Practice, c.practice_id)
        member = session.scalar(select(Membership).where(Membership.practice_id == c.practice_id, Membership.role == "owner"))
        member.active = True
        practice.subscription_status = "trialing"
        practice.billing_verified_at = datetime.now(UTC)
    assert c.adapter.authorize(c.token, "user_synthetic_owner-a")["enforced"]


def test_exact_derived_scope_signature_nonce_mode_and_bound_human(admission_case):
    c = admission_case
    activate(c)
    assert derive_runtime_admission_key(c.master, str(uuid4()), c.box_id, c.org) != c.key
    body = body_for(c)
    raw = encode(body.model_dump())
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + c.token,
               ADMISSION_HEADER: signature(c.key, raw, direction="request", nonce=body.nonce)}
    assert c.client.post("/enrollment/v1/runtime/admission", content=raw, headers=headers).status_code == 200
    for changed in (raw.replace(c.box_id.encode(), str(uuid4()).encode()), raw.replace(body.nonce.encode(), str(uuid4()).encode())):
        assert c.client.post("/enrollment/v1/runtime/admission", content=changed, headers=headers).status_code == 401
    response = c.client.post("/enrollment/v1/runtime/admission", content=raw, headers={**headers, "Authorization": "Bearer another-private-token"})
    assert response.status_code == 401 and "another-private-token" not in response.text
    wrong = body_for(c, subject="user_synthetic_staff-a")
    raw = encode(wrong.model_dump())
    response = c.client.post("/enrollment/v1/runtime/admission", content=raw, headers={**headers,
        ADMISSION_HEADER: signature(c.key, raw, direction="request", nonce=wrong.nonce)})
    assert response.json()["decision"] == "deny"
    assert c.client.post("/enrollment/v1/runtime/admission", content=b'{"nonce":"first","nonce":"second"}', headers=headers).status_code == 422


@pytest.mark.parametrize("revocation", ["banned", "org_removed"])
def test_worker_live_clerk_revocation_denies_active_registry_and_recovers(admission_case, revocation):
    c = admission_case
    activate(c)
    identities = c.app.state.synthetic_identities
    if revocation == "banned":
        identities.blocked_users.add("user_synthetic_owner-a")
    else:
        identities.removed_memberships.add(("user_synthetic_owner-a", c.org))
    with pytest.raises(RuntimeAdmissionError) as denied:
        c.adapter.authorize("", "user_synthetic_owner-a", purpose="worker", operation_id=str(uuid4()), approval_sha256="a" * 64)
    assert denied.value.code == ACCESS_REQUIRED
    identities.blocked_users.clear()
    identities.removed_memberships.clear()
    assert c.adapter.authorize("", "user_synthetic_owner-a", purpose="worker", operation_id=str(uuid4()), approval_sha256="a" * 64)["enforced"]


def test_overlong_provider_prefill_remains_correctable_and_saved_runtime_names_are_bounded(admission_case):
    c = admission_case
    c.app.state.synthetic_identities.users["owner-b"] = ("owner-b@example.invalid", "B" * 160)
    token = c.client.post("/lab/session", json={"user": "owner-b"}).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    state = c.client.get("/enrollment/v1/status", headers=headers).json()
    assert state["stage"] == "account" and state["profile"]["display_name"] == "B" * 160
    for name in ("B" * 121, "Example\tName", "Example\nName", "Example\x7fName"):
        result = c.client.put("/enrollment/v1/profile", headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"expected_revision": state["revision"], "display_name": name, "title": "Owner"})
        assert result.status_code == 422
    saved = c.client.put("/enrollment/v1/profile", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_revision": state["revision"], "display_name": "B" * 120, "title": "Owner"})
    assert saved.status_code == 200 and len(saved.json()["profile"]["display_name"]) == 120


@pytest.mark.parametrize("fault", ["outage", "signature", "scope", "expired"])
def test_owned_adapter_does_not_accept_unverified_or_old_response(admission_case, fault):
    c = admission_case
    activate(c)
    def faulty(request):
        if fault == "outage":
            raise httpx.ReadTimeout("invented outage")
        response = c.transport(request)
        value = response.json()
        if fault == "signature":
            response.headers[ADMISSION_HEADER] = "0" * 64
            return response
        if fault == "scope":
            value["box_id"] = str(uuid4())
        else:
            value["expires_at"] = int(time.time()) - 1
        raw = encode(value)
        nonce = json.loads(request.content)["nonce"]
        return httpx.Response(200, content=raw, headers={"Content-Type": "application/json", "Cache-Control": "no-store",
            ADMISSION_HEADER: signature(c.key, raw, direction="response", nonce=nonce)})
    adapter = EnrollmentAdmissionAdapter(c.runtime, client=httpx.Client(transport=httpx.MockTransport(faulty)))
    with pytest.raises(RuntimeAdmissionError) as failed:
        adapter.authorize(c.token, "user_synthetic_owner-a")
    assert failed.value.code == ADMISSION_UNAVAILABLE
    assert c.adapter.authorize(c.token, "user_synthetic_owner-a")["enforced"]


def test_default_session_requires_complete_managed_configuration_and_empty_audience(admission_case):
    c = admission_case
    assert c.runtime.clerk_session_configuration_errors() == []
    c.runtime.clerk_audience = "unexpected"
    assert c.runtime.clerk_session_configuration_errors()
    c.runtime.clerk_audience = ""
    c.runtime.workspace_enrollment_managed = False
    assert c.runtime.clerk_session_configuration_errors()
    assert c.runtime.enrollment_recovery_url is None


@pytest.mark.parametrize("kind", ["customer.subscription.deleted", "customer.subscription.updated"])
def test_signed_subscription_event_invalidates_admission_before_reconciliation(admission_case, kind):
    c = admission_case
    activate(c)
    commerce = c.app.state.synthetic_commerce
    sub = next(iter(commerce.subscriptions.values()))
    if kind.endswith("deleted"):
        sub["status"] = "canceled"
    raw, header = commerce.signed_event(kind, sub, "evt_admission_invalidation", created=int(time.time()) - 10)
    assert c.client.post("/enrollment/v1/webhooks/stripe", content=raw, headers={"Stripe-Signature": header}).status_code == 200
    with c.app.state.enrollment_service.sessions() as session:
        assert session.get(Practice, c.practice_id).billing_verified_at is None
    commerce.fail_reads = True
    for worker in (False, True):
        with pytest.raises(RuntimeAdmissionError):
            c.adapter.authorize("" if worker else c.token, "user_synthetic_owner-a", **(
                {"purpose": "worker", "operation_id": str(uuid4()), "approval_sha256": "a" * 64} if worker else {}))
    commerce.fail_reads = False
    if kind.endswith("deleted"):
        with pytest.raises(RuntimeAdmissionError):
            c.adapter.authorize(c.token, "user_synthetic_owner-a")
    else:
        assert c.adapter.authorize(c.token, "user_synthetic_owner-a")["enforced"]


@pytest.mark.parametrize("interrupted", [True, False])
def test_runtime_admission_stream_has_total_budget_and_redacted_no_store(admission_case, monkeypatch, interrupted):
    from cosmas_os.enrollment import api
    c = admission_case
    monkeypatch.setattr(api, "ADMISSION_BODY_TIMEOUT_SECONDS", 0.01)
    async def exercise():
        sent = []
        completed = False
        async def receive():
            if interrupted or completed:
                return {"type": "http.disconnect"}
            await asyncio.sleep(1)
            return {"type": "http.request", "body": b"private-token-never-returned", "more_body": True}
        async def send(message):
            nonlocal completed
            sent.append(message)
            if message["type"] == "http.response.start":
                completed = True
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "scheme": "http",
            "method": "POST", "path": "/enrollment/v1/runtime/admission", "raw_path": b"/enrollment/v1/runtime/admission",
            "query_string": b"", "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                (b"authorization", b"Bearer private-token-never-returned"), (b"x-cosmas-enrollment-signature", b"invalid")],
            "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
        await c.app(scope, receive, send)
        start = next(v for v in sent if v["type"] == "http.response.start")
        assert start["status"] == 408
        assert (b"cache-control", b"no-store") in start["headers"]
        assert "private-token-never-returned" not in str(sent)
    asyncio.run(exercise())
