"""Private source qualification; invented provider/Clerk, real managed API code."""
from __future__ import annotations

import hashlib
import os
import time
from contextvars import Context
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool
from tests.enrollment.clock_harness import ClockBoundStripeCommerce, ProviderDouble, signed_event

from cosmas_os.adapters.enrollment_admission import ACCESS_REQUIRED, EnrollmentAdmissionAdapter
from cosmas_os.config import Settings
from cosmas_os.enrollment.admission import derive_runtime_admission_key
from cosmas_os.enrollment.api import create_app
from cosmas_os.enrollment.domain import EnrollmentError
from cosmas_os.enrollment.migration import upgrade
from cosmas_os.enrollment.models import CheckoutAttempt, EnrollmentBase, Practice
from cosmas_os.enrollment.service import EnrollmentService
from cosmas_os.enrollment.synthetic import (
    SyntheticIdentities,
    SyntheticWorkspaceConfirmer,
    synthetic_settings,
)

# Runtime fixtures load only for the persisted runtime cases. The private
# control app never installs a customer clock/date override route.
PG = os.environ.get("ENROLLMENT_RUNTIME_TEST_DATABASE_URL", "")
needs_pg = pytest.mark.skipif(not PG, reason="Dedicated private runtime PostgreSQL is required")


@pytest.fixture
def runtime_engine():
    from tests.enrollment.test_runtime_workspace import runtime_engine as fixture
    yield from fixture._get_wrapped_function()()


@pytest.fixture
def runtime_case(admission_case, monkeypatch, runtime_engine):
    from tests.enrollment.test_runtime_workspace import runtime_case as fixture
    yield from fixture._get_wrapped_function()(admission_case, monkeypatch, runtime_engine)


@pytest.fixture
def admission_case():
    settings = synthetic_settings()
    url = os.environ.get("ENROLLMENT_TEST_DATABASE_URL")
    engine = create_engine(url, pool_pre_ping=True) if url else create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url:
        assert engine.url.host == "127.0.0.1" and engine.url.database == "enrollment_synthetic"
    else:
        event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    upgrade(engine)
    if url:
        with engine.begin() as connection:
            tables = ",".join(engine.dialect.identifier_preparer.format_table(t) for t in EnrollmentBase.metadata.sorted_tables)
            connection.exec_driver_sql("TRUNCATE TABLE " + tables + " RESTART IDENTITY CASCADE")
    identities = SyntheticIdentities(settings)
    provider = ProviderDouble(settings)
    commerce = ClockBoundStripeCommerce(settings, provider)
    app = create_app(settings, engine=engine, verifier=identities, commerce=commerce,
        workspace_confirmer=SyntheticWorkspaceConfirmer(identities))
    service = app.state.enrollment_service
    commerce.install(service)
    app.state.synthetic_identities = identities
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + identities.token("owner-a")}
        def write(path, body, method="POST", key=None):
            revision = client.get("/enrollment/v1/status", headers=headers).json()["revision"]
            result = client.request(method, "/enrollment/v1" + path, headers={**headers, "Idempotency-Key": key or str(uuid4())},
                json={"expected_revision": revision, **body})
            assert result.status_code == 200, result.text
            return result.json()
        write("/profile", {"display_name": "Alex Example", "title": "Owner"}, "PUT")
        state = write("/practice", {"legal_name": "Example Clinic LLC", "display_name": "Example Clinic", "address_line1": "123 Example Street",
            "city": "Example City", "region": "NY", "postal_code": "10001", "administrative_email": "office@example.invalid", "human_seats": 2, "covered_entity": True}, "PUT")
        document = client.get("/enrollment/v1/baa/current", headers=headers).json()
        write("/baa/accept", {"doc_id": document["doc_id"], "version": document["version"], "sha256": document["sha256"],
            "signature_name": "Alex Example", "signature_title": "Owner", "authority_confirmed": True, "accepted": True})
        practice_id = state["practice"]["id"]
        box_id = str(uuid5(NAMESPACE_URL, practice_id))
        org = "org_synthetic" + practice_id.replace("-", "")
        service.record_workspace(practice_id, box_id=box_id, organization_id=org, url=settings.public_app_origin + "/chief",
            status="provisioning", proof_sha256="a" * 64, workspace_api_origin="https://api.example.invalid", source_commit="a" * 40, image_sha256="b" * 64)
        token = identities.token("owner-a", org)
        master = settings.runtime_admission_secret.get_secret_value()
        key = derive_runtime_admission_key(master, practice_id, box_id, org)
        runtime = Settings(_env_file=None, cosmas_env="early_adopter_beta", data_mode="synthetic", auth_mode="clerk_jwt",  # pyright: ignore[reportCallIssue]
            workspace_enrollment_managed=True, workspace_enrollment_practice_id=practice_id, beta_box_id=box_id,
            clerk_issuer=settings.clerk_issuer, clerk_organization_id=org, clerk_session_policy="enrollment_default", clerk_audience="",
            workspace_enrollment_api_origin="https://enrollment.example.invalid", workspace_enrollment_origin_allowlist="https://enrollment.example.invalid,https://app.example.invalid",
            workspace_enrollment_admission_secret=SecretStr(key), workspace_enrollment_account_origin=settings.public_app_origin)
        responses = []
        def transport(request):
            result = Context().run(client.post, request.url.path, content=request.content, headers=dict(request.headers))
            responses.append(result)
            return httpx.Response(result.status_code, content=result.content, headers=dict(result.headers))
        adapter = EnrollmentAdmissionAdapter(runtime, client=httpx.Client(transport=httpx.MockTransport(transport)))
        yield SimpleNamespace(app=app, client=client, token=token, write=write, runtime=runtime, adapter=adapter, provider=provider,
            commerce=commerce, service=service, key=key, master=master, practice_id=practice_id, box_id=box_id, org=org,
            issuer=settings.clerk_issuer, headers=headers, transport=transport, responses=responses)
    commerce.client.close()


def publish(c, kind, obj, identity):
    raw, signature = signed_event(c.commerce, kind, obj, identity)
    result = c.client.post("/enrollment/v1/webhooks/stripe", content=raw, headers={"Stripe-Signature": signature})
    assert result.status_code == 200, result.text
    return raw, signature


def activate(f):
    from tests.enrollment.test_runtime_workspace import complete_setup
    c = f.control
    complete_setup(f)
    response = f.client.get("/practice-access/enrollment-qualification", headers=f.headers)
    assert response.status_code == 200 and response.json()["initial_setup_complete"] is True
    assert response.json()["enrollment_admission"] == {"contract_version": "cosmas-enrollment-admission.v1", "enforced": True,
        "practice_id": c.practice_id, "purpose": "qualification"}
    c.service.record_workspace(c.practice_id, box_id=c.box_id, organization_id=c.org,
        url="https://app.example.invalid/chief", proof_sha256=hashlib.sha256(response.content).hexdigest())
    checkout = c.write("/checkout", {})
    assert checkout["status"] == "open" and c.provider.charge_count == 0
    session_id = next(iter(c.provider.sessions))
    c.provider.complete(session_id)
    publish(c, "checkout.session.completed", c.provider.sessions[session_id], "evt_syntheticm3checkout")
    c.service.reconcile_pending()
    assert f.client.get("/workspaces", headers=f.headers).status_code == 200
    with c.service.sessions() as session:
        practice = session.get(Practice, c.practice_id)
        return practice.trial_started_at, practice.trial_ends_at, practice.stripe_customer_id, practice.stripe_subscription_id


def original(c):
    with c.service.sessions() as session:
        practice = session.get(Practice, c.practice_id)
        assert session.scalar(select(CheckoutAttempt).where(CheckoutAttempt.practice_id == c.practice_id)).state == "complete"
        return practice.trial_started_at, practice.trial_ends_at, practice.stripe_customer_id, practice.stripe_subscription_id


@needs_pg
@pytest.mark.parametrize("point", ["expiry", "after"])
def test_original_exact_fourteen_days_runtime_and_worker_cutoff(runtime_case, point):
    from datetime import UTC
    f, c = runtime_case, runtime_case.control
    saved = activate(f)
    assert (saved[1].astimezone(UTC) - saved[0].astimezone(UTC)).total_seconds() == 14 * 86400
    c.commerce.advance("before")
    assert f.client.get("/workspaces", headers=f.headers).status_code == 200
    proof = c.responses[-1].json()
    assert int(time.time()) - 1 <= proof["issued_at"] <= int(time.time())
    assert 0 < proof["expires_at"] - proof["issued_at"] <= 1
    c.adapter.authorize("", "user_synthetic_owner-a", purpose="worker", operation_id=str(uuid4()), approval_sha256="a" * 64)
    c.commerce.advance(point)
    denied = f.client.get("/workspaces", headers=f.headers)
    assert denied.status_code == 403 and denied.json()["detail"] == ACCESS_REQUIRED
    assert c.responses[-1].json()["reason"] == "billing_required"
    from cosmas_os.adapters.enrollment_admission import RuntimeAdmissionError
    with pytest.raises(RuntimeAdmissionError):
        c.adapter.authorize("", "user_synthetic_owner-a", purpose="worker", operation_id=str(uuid4()), approval_sha256="a" * 64)
    assert c.client.get("/enrollment/v1/status", headers=c.headers).json()["stage"] == "payment_action_required"
    assert original(c) == saved and c.provider.checkout_count == 1


@needs_pg
def test_trial_cancel_before_expiry_prevents_synthetic_first_charge_and_direct_access(runtime_case):
    f, c = runtime_case, runtime_case.control
    saved = activate(f)
    sub = c.provider.subscriptions[saved[3]]
    sub["cancel_at_period_end"] = True
    publish(c, "customer.subscription.updated", sub, "evt_syntheticm3cancel")
    c.commerce.advance("before")
    assert f.client.get("/workspaces", headers=f.headers).status_code == 200
    c.commerce.advance("expiry")
    publish(c, "customer.subscription.deleted", sub, "evt_syntheticm3deleted")
    assert f.client.get("/workspaces", headers=f.headers).status_code == 403
    c.service.reconcile_pending()
    c.write("/recover", {})
    c.write("/recover", {})
    assert original(c) == saved and c.provider.checkout_count == 1
    assert c.provider.charge_count == 0 and not c.provider.invoices


@needs_pg
def test_same_invoice_failure_recovery_duplicates_and_provider_outage(runtime_case):
    f, c = runtime_case, runtime_case.control
    saved = activate(f)
    c.provider.transition = "failure"
    c.commerce.advance("expiry")
    invoice = c.provider.invoices["in_syntheticm3"]
    raw, signature = publish(c, "invoice.payment_failed", invoice, "evt_syntheticm3failed")
    assert f.client.get("/workspaces", headers=f.headers).status_code == 403
    c.service.reconcile_pending()
    c.provider.fail_reads = True
    denied = f.client.get("/workspaces", headers=f.headers)
    assert denied.status_code in (403, 503)
    c.provider.fail_reads = False
    other_invoice = {**invoice, "id": "in_syntheticother", "paid": True, "status": "paid"}
    c.provider.invoices["in_syntheticother"] = other_invoice
    publish(c, "invoice.paid", other_invoice, "evt_syntheticm3otherinvoice")
    c.service.reconcile_pending()
    c.write("/recover", {})
    assert f.client.get("/workspaces", headers=f.headers).status_code == 403
    c.provider.pay_same_invoice()
    response = f.client.get("/workspaces", headers=f.headers)
    with c.service.sessions() as session:
        practice = session.get(Practice, c.practice_id)
        assert practice.payment_failure_invoice_id == "in_syntheticm3"
    assert response.status_code == 403  # Fresh failed-payment hold awaits canonical recovery.
    publish(c, "invoice.paid", invoice, "evt_syntheticm3paid")
    c.write("/recover", {})
    assert f.client.get("/workspaces", headers=f.headers).status_code == 200
    assert c.client.post("/enrollment/v1/webhooks/stripe", content=raw, headers={"Stripe-Signature": signature}).status_code == 200
    c.service.reconcile_pending()
    c.write("/recover", {})
    c.write("/recover", {})
    assert f.client.get("/workspaces", headers=f.headers).status_code == 200
    assert original(c) == saved and c.provider.checkout_count == c.provider.charge_count == 1


def test_period_port_unavailable_clock_binding_and_production_rejection(admission_case):
    c = admission_case
    assert not c.provider.sessions
    assert c.client.post("/enrollment/v1/clock", json={"now": "synthetic"}).status_code == 404
    c.provider.clock["status"] = "advancing"
    with pytest.raises(EnrollmentError):
        c.commerce.refresh_clock()
    with pytest.raises(EnrollmentError):
        c.commerce.now()
    c.provider.clock["status"] = "ready"
    c.commerce.refresh_clock()
    settings = c.app.state.enrollment_settings.model_copy(update={"data_mode": "production"})
    with pytest.raises(ValueError):
        EnrollmentService(c.service.sessions, settings, c.commerce, period_time=c.commerce)
    with pytest.raises(ValueError):
        ClockBoundStripeCommerce(settings, c.provider)
    assert c.client.get("/enrollment/v1/status", headers=c.headers).json()["stage"] == "activation_pending"


@pytest.mark.parametrize("outage", ["unready", "read_failure"])
def test_clock_recovery_retains_last_qualified_time(admission_case, outage):
    c = admission_case
    qualified = c.provider.clock["frozen_time"] + 60
    c.provider.clock["frozen_time"] = qualified
    c.commerce.refresh_clock()
    assert c.commerce.now().timestamp() == qualified
    if outage == "unready":
        c.provider.clock["status"] = "advancing"
    else:
        c.provider.fail_reads = True
    with pytest.raises(EnrollmentError):
        c.commerce.refresh_clock()
    with pytest.raises(EnrollmentError):
        c.commerce.now()
    c.provider.clock.update(status="ready", frozen_time=qualified - 1)
    c.provider.fail_reads = False
    with pytest.raises(EnrollmentError):
        c.commerce.refresh_clock()
    with pytest.raises(EnrollmentError):
        c.commerce.now()
    c.provider.clock["frozen_time"] = qualified
    c.commerce.refresh_clock()
    assert c.commerce.now().timestamp() == qualified
    c.provider.clock["frozen_time"] = qualified + 1
    c.commerce.refresh_clock()
    assert c.commerce.now().timestamp() == qualified + 1


def test_virtual_period_does_not_extend_jwt_or_signed_request_time(admission_case):
    import jwt

    from cosmas_os.enrollment.admission import ADMISSION_HEADER, AdmissionRequest, encode, signature
    c = admission_case
    c.service.record_workspace(c.practice_id, box_id=c.box_id, organization_id=c.org,
        url="https://app.example.invalid/chief", proof_sha256="b" * 64)
    c.write("/checkout", {})
    session_id = next(iter(c.provider.sessions))
    c.provider.complete(session_id)
    publish(c, "checkout.session.completed", c.provider.sessions[session_id], "evt_syntheticm3security")
    c.service.reconcile_pending()
    c.commerce.advance("before")
    assert c.adapter.authorize(c.token, "user_synthetic_owner-a")["enforced"]
    claims = jwt.decode(c.token, options={"verify_signature": False})
    claims["exp"] = int(time.time()) - 60
    expired = jwt.encode(claims, c.app.state.synthetic_identities.key, algorithm="RS256", headers={"kid": "synthetic"})
    from cosmas_os.adapters.enrollment_admission import RuntimeAdmissionError
    with pytest.raises(RuntimeAdmissionError):
        c.adapter.authorize(expired, "user_synthetic_owner-a")
    body = AdmissionRequest(practice_id=c.practice_id, box_id=c.box_id, organization_id=c.org, issuer=c.issuer,
        subject="user_synthetic_owner-a", purpose="workspace", nonce=str(uuid4()), issued_at=int(time.time()) - 60,
        token_sha256=hashlib.sha256(c.token.encode()).hexdigest())
    raw = encode(body.model_dump())
    denied = c.client.post("/enrollment/v1/runtime/admission", content=raw, headers={"Content-Type": "application/json",
        "Authorization": "Bearer " + c.token, ADMISSION_HEADER: signature(c.key, raw, direction="request", nonce=body.nonce)})
    assert denied.status_code == 401


def test_clock_customer_and_original_trial_cannot_be_rebound(admission_case):
    c = admission_case
    c.service.record_workspace(c.practice_id, box_id=c.box_id, organization_id=c.org,
        url="https://app.example.invalid/chief", proof_sha256="b" * 64)
    c.write("/checkout", {})
    session_id = next(iter(c.provider.sessions))
    c.provider.complete(session_id)
    publish(c, "checkout.session.completed", c.provider.sessions[session_id], "evt_syntheticm3binding")
    c.service.reconcile_pending()
    saved = original(c)
    c.provider.customer["test_clock"] = "clock_other"
    with pytest.raises(EnrollmentError):
        c.commerce.refresh_clock()
    with pytest.raises(EnrollmentError):
        c.commerce.now()
    c.provider.customer["test_clock"] = c.commerce.clock_id
    c.commerce.refresh_clock()
    sub = c.provider.subscriptions[saved[3]]
    sub["trial_start"] += 1
    sub["trial_end"] += 1
    with pytest.raises(EnrollmentError):
        c.commerce.retrieve_subscription(saved[3])
    assert original(c) == saved
    assert c.client.post("/enrollment/v1/checkout", headers={**c.headers, "Idempotency-Key": str(uuid4())},
        json={"expected_revision": c.client.get("/enrollment/v1/status", headers=c.headers).json()["revision"],
              "customer_id": "cus_other", "trial_days": 1}).status_code == 422


def test_virtual_time_does_not_extend_wall_billing_freshness(admission_case):
    from datetime import UTC, datetime, timedelta

    from cosmas_os.adapters.enrollment_admission import RuntimeAdmissionError
    c = admission_case
    c.service.record_workspace(c.practice_id, box_id=c.box_id, organization_id=c.org,
        url="https://app.example.invalid/chief", proof_sha256="b" * 64)
    c.write("/checkout", {})
    session_id = next(iter(c.provider.sessions))
    c.provider.complete(session_id)
    publish(c, "checkout.session.completed", c.provider.sessions[session_id], "evt_syntheticm3freshness")
    c.service.reconcile_pending()
    c.commerce.advance("before")
    with c.service.sessions.begin() as session:
        session.get(Practice, c.practice_id).billing_verified_at = datetime.now(UTC) - timedelta(minutes=6)
    c.provider.fail_reads = True
    with pytest.raises(RuntimeAdmissionError):
        c.adapter.authorize(c.token, "user_synthetic_owner-a")
    c.provider.fail_reads = False
    assert c.adapter.authorize(c.token, "user_synthetic_owner-a")["enforced"]
