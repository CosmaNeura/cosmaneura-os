from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from cosmas_os.enrollment.api import create_app
from cosmas_os.enrollment.config import EnrollmentSettings
from cosmas_os.enrollment.domain import (
    BAA_DOC_ID,
    BAA_SHA256,
    BAA_VERSION,
    EnrollmentError,
    document,
)
from cosmas_os.enrollment.migration import schema_ready, upgrade
from cosmas_os.enrollment.models import (
    Acceptance,
    CheckoutAttempt,
    Command,
    Membership,
    Practice,
    StripeInbox,
)
from cosmas_os.enrollment.synthetic import create_synthetic_app
from cosmas_os.enrollment.workspace import WorkspaceConfirmationResult


@pytest.fixture
def lab():
    app = create_synthetic_app()
    with TestClient(app) as client:
        yield app, client


def signed(client, user="owner-a"):
    return {"Authorization": "Bearer " + client.post("/lab/session", json={"user": user}).json()["token"]}


def status(client, headers):
    response = client.get("/enrollment/v1/status", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def mutate(client, headers, path, body, method="POST", key=None):
    body = {"expected_revision": status(client, headers)["revision"], **body}
    return client.request(method, "/enrollment/v1" + path, headers={**headers, "Idempotency-Key": key or str(uuid4())}, json=body)


def enrolled(client, headers, humans=1, covered=True):
    assert mutate(client, headers, "/profile", {"display_name": "Alex Example", "title": "Practice owner"}, "PUT").status_code == 200
    response = mutate(client, headers, "/practice", {"legal_name": "Example Practice LLC", "display_name": "Example Practice",
        "address_line1": "123 Example Street", "address_line2": "", "city": "Example City", "region": "NY",
        "postal_code": "10001", "country": "US", "administrative_email": "office@example.invalid", "human_seats": humans,
        "covered_entity": covered}, "PUT")
    assert response.status_code == 200, response.text
    return response.json()


def accepted(client, headers, humans=1):
    enrolled(client, headers, humans)
    response = mutate(client, headers, "/baa/accept", {"doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256,
        "signature_name": "Alex Example", "signature_title": "Practice owner", "authority_confirmed": True, "accepted": True})
    assert response.status_code == 200, response.text
    return response.json()


def ready_checkout(client, headers, humans=1):
    state = accepted(client, headers, humans)
    assert client.post("/lab/qualify", json={"practice_id": state["practice"]["id"]}).status_code == 200
    response = mutate(client, headers, "/checkout", {})
    assert response.status_code == 200, response.text
    return response.json()


def test_unconfigured_production_never_accepts_registration_or_claims_readiness():
    with TestClient(create_app(EnrollmentSettings(data_mode="production"))) as client:
        config = client.get("/enrollment/v1/config").json()
        assert config["enabled"] is False
        assert config["auth_configured"] is False
        assert config["billing_configured"] is False
        assert config["activation_available"] is False
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert client.get("/enrollment/v1/status", headers={"Authorization": "Bearer fake"}).status_code == 503
        assert all("secret" not in k for k in config)
        assert client.get("/enrollment/v1/config").headers["cache-control"] == "no-store"
        assert client.get("/enrollment/v1/status").headers["cache-control"] == "no-store"


def test_actual_transport_contract_cors_and_no_store(lab):
    _, client = lab
    response = client.get("/enrollment/v1/config", headers={"X-Cosmas-Enrollment-Contract": "enrollment.v1"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    wrong = client.get("/enrollment/v1/config", headers={"X-Cosmas-Enrollment-Contract": "other"})
    assert wrong.status_code == 409 and wrong.headers["cache-control"] == "no-store"
    cors = client.options("/enrollment/v1/profile", headers={"Origin": "https://app.example.invalid",
        "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "authorization,x-cosmas-enrollment-contract,idempotency-key,content-type"})
    assert cors.status_code == 200
    assert "x-cosmas-enrollment-contract" in cors.headers["access-control-allow-headers"].lower()


def test_saved_progress_two_practice_isolation_and_exact_retry(lab):
    app, client = lab
    owner, other = signed(client), signed(client, "owner-b")
    first = enrolled(client, owner)
    assert first["stage"] == "agreement"
    assert status(client, signed(client))["practice"]["id"] == first["practice"]["id"]
    assert status(client, other)["practice"] is None
    second = enrolled(client, other)
    assert second["practice"]["id"] != first["practice"]["id"]
    assert first["workspace"]["box_id"] is None
    key, body = str(uuid4()), {"expected_revision": first["revision"], "display_name": "Alex Example", "title": "Owner"}
    response = client.put("/enrollment/v1/profile", headers={**owner, "Idempotency-Key": key}, json=body)
    replay = client.put("/enrollment/v1/profile", headers={**owner, "Idempotency-Key": key}, json=body)
    assert response.status_code == replay.status_code == 200
    assert response.json() == replay.json()
    conflict = client.put("/enrollment/v1/profile", headers={**owner, "Idempotency-Key": key}, json={**body, "title": "Different"})
    assert conflict.status_code == 409
    with app.state.enrollment_service.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Practice)) == 2


def test_immutable_document_receipt_stale_version_and_unchecked_authority(lab):
    app, client = lab
    owner = signed(client)
    enrolled(client, owner)
    body = {"doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256,
            "signature_name": "Alex Example", "signature_title": "Owner", "authority_confirmed": True, "accepted": True}
    assert mutate(client, owner, "/baa/accept", {**body, "sha256": "b" * 64}).status_code == 409
    assert mutate(client, owner, "/baa/accept", {**body, "authority_confirmed": False}).status_code == 422
    assert mutate(client, owner, "/baa/accept", body).status_code == 200
    receipt = client.get("/enrollment/v1/baa/receipt", headers=owner).json()
    assert receipt["document"]["sha256"] == BAA_SHA256
    assert receipt["receipt"]["accepted_by_email"] == "owner-a@example.invalid"
    assert receipt["receipt"]["covered_entity_legal_name"] == "Example Practice LLC"
    assert "CosmaNeura Inc., a Delaware corporation" in document()["html"]
    assert mutate(client, owner, "/baa/accept", body).status_code == 200
    with app.state.enrollment_service.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Acceptance)) == 1
        with pytest.raises(IntegrityError):
            session.execute(text("UPDATE enrollment_baa_acceptances SET signer_name='Changed'"))
        session.rollback()
        with pytest.raises(IntegrityError):
            session.execute(text("DELETE FROM enrollment_baa_acceptances"))


@pytest.mark.parametrize(("humans", "total"), [(1, 30000), (2, 40000), (10, 120000), (11, None)])
def test_human_pricing_includes_owner_admin_staff_and_negotiated_upper_bound(lab, humans, total):
    _, client = lab
    owner = signed(client)
    state = accepted(client, owner, humans)
    assert state["quote"]["monthly_total_cents"] == total
    assert state["quote"]["human_seats"] == humans
    assert state["quote"]["due_today_cents"] == 0
    if humans > 10:
        assert state["stage"] == "negotiated"
        assert mutate(client, owner, "/checkout", {}).status_code == 409


def test_activation_pending_does_not_create_checkout_or_start_trial(lab):
    app, client = lab
    owner = signed(client)
    state = accepted(client, owner)
    assert state["stage"] == "activation_pending"
    assert state["billing"]["trial_ends_at"] is None
    assert mutate(client, owner, "/checkout", {}).status_code == 409
    assert app.state.synthetic_commerce.create_count == 0
    assert client.post("/enrollment/v1/ready", headers=owner, json={}).status_code == 404
    assert mutate(client, owner, "/checkout", {"workspace_status": "ready"}).status_code == 422


def test_lost_checkout_reply_reuses_durable_frozen_attempt(lab):
    app, client = lab
    owner = signed(client)
    state = accepted(client, owner, 2)
    client.post("/lab/qualify", json={"practice_id": state["practice"]["id"]})
    app.state.synthetic_commerce.lose_next_reply = True
    response = mutate(client, owner, "/checkout", {})
    assert response.status_code == 503
    assert status(client, owner)["billing"]["trial_ends_at"] is None
    resumed = mutate(client, owner, "/checkout", {}).json()
    assert resumed["status"] == "open"
    assert resumed["url"].startswith("https://checkout.stripe.com/")
    assert app.state.synthetic_commerce.create_count == 1
    with app.state.enrollment_service.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CheckoutAttempt)) == 1


def test_redirect_is_not_proof_full_fourteen_days_and_no_second_trial(lab):
    app, client = lab
    owner = signed(client)
    ready_checkout(client, owner)
    commerce = app.state.synthetic_commerce
    session_id = next(iter(commerce.sessions))
    commerce.complete(session_id)
    assert status(client, owner)["stage"] == "finishing_setup"
    assert status(client, owner)["workspace"]["url"] is None
    recovered = mutate(client, owner, "/recover", {})
    assert recovered.status_code == 200, recovered.text
    state = recovered.json()
    assert state["stage"] == "ready"
    assert state["workspace"]["organization_id"].startswith("org_synthetic")
    assert state["workspace"]["url"] == "https://app.example.invalid/chief"
    sub = next(iter(commerce.subscriptions.values()))
    assert sub["trial_end"] - sub["trial_start"] == 14 * 86400
    sub["status"], sub["cancel_at_period_end"] = "canceled", True
    assert mutate(client, owner, "/recover", {}).json()["stage"] == "canceled"
    assert mutate(client, owner, "/checkout", {}).status_code == 409
    assert commerce.create_count == 1
    assert mutate(client, owner, "/portal", {}).json()["url"].startswith("https://billing.stripe.com/")


def test_expired_provider_session_rotates_only_after_confirmation(lab):
    app, client = lab
    owner = signed(client)
    ready_checkout(client, owner)
    commerce = app.state.synthetic_commerce
    checkout = next(iter(commerce.sessions.values()))
    checkout["status"] = "expired"
    assert mutate(client, owner, "/recover", {}).json()["billing"]["status"] == "none"
    assert mutate(client, owner, "/checkout", {}).status_code == 200
    assert commerce.create_count == 2


def test_unknown_provider_outcome_after_idempotency_window_requires_operator(lab):
    app, client = lab
    owner = signed(client)
    state = accepted(client, owner)
    client.post("/lab/qualify", json={"practice_id": state["practice"]["id"]})
    app.state.synthetic_commerce.lose_next_reply = True
    assert mutate(client, owner, "/checkout", {}).status_code == 503
    with app.state.enrollment_service.sessions.begin() as session:
        attempt = session.scalar(select(CheckoutAttempt))
        attempt.created_at = datetime.now(UTC) - timedelta(hours=25)
    recovery = mutate(client, owner, "/checkout", {}).json()
    assert recovery["url"] is None
    assert recovery["status"] == "pending"
    assert "support" in recovery["action_required"]
    assert app.state.synthetic_commerce.create_count == 1


def test_signed_durable_inbox_duplicate_lost_worker_and_payment_failure(lab):
    app, client = lab
    owner = signed(client)
    ready_checkout(client, owner, 2)
    commerce, service = app.state.synthetic_commerce, app.state.enrollment_service
    checkout = next(iter(commerce.sessions.values()))
    commerce.complete(checkout["id"])
    raw, signature = commerce.signed_event("checkout.session.completed", checkout, "evt_example_complete")
    assert client.post("/enrollment/v1/webhooks/stripe", content=raw, headers={"Stripe-Signature": "invalid"}).status_code == 401
    for _ in range(2):
        response = client.post("/enrollment/v1/webhooks/stripe", content=raw, headers={"Stripe-Signature": signature})
        assert response.status_code == 200, response.text
    with service.sessions() as session:
        assert session.scalar(select(func.count()).select_from(StripeInbox)) == 1
        assert session.scalar(select(StripeInbox)).state == "pending"
    assert status(client, owner)["workspace"]["url"] is None
    assert service.reconcile_pending() == {"processed": 1, "pending": 0}
    assert status(client, owner)["stage"] == "ready"
    sub = next(iter(commerce.subscriptions.values()))
    raw, signature = commerce.signed_event("invoice.payment_failed", {"id": "in_synthetic", "subscription": sub["id"], "customer": sub["customer"]}, "evt_example_failed")
    assert client.post("/enrollment/v1/webhooks/stripe", content=raw, headers={"Stripe-Signature": signature}).status_code == 200
    assert status(client, owner)["workspace"]["url"] is None
    commerce.fail_reads = True
    assert service.reconcile_pending() == {"processed": 0, "pending": 1}
    with service.sessions() as session:
        failed = session.get(StripeInbox, "evt_example_failed")
        assert failed.attempts == 1 and failed.error_code == "stripe_unavailable"
        assert "email" not in json.dumps(failed.payload)


@pytest.mark.parametrize("change", ["trial", "price", "practice", "customer"])
def test_authoritative_binding_price_and_trial_failure_never_grants_access(lab, change):
    app, client = lab
    owner = signed(client)
    ready_checkout(client, owner)
    commerce = app.state.synthetic_commerce
    checkout = next(iter(commerce.sessions.values()))
    commerce.complete(checkout["id"])
    sub = next(iter(commerce.subscriptions.values()))
    if change == "trial":
        sub["trial_end"] += 1
    elif change == "price":
        sub["items"]["data"][0]["price"]["unit_amount"] = 8900
    elif change == "practice":
        sub["metadata"]["practice_id"] = str(uuid4())
    else:
        sub["customer"] = "cus_wrong"
    assert mutate(client, owner, "/recover", {}).status_code == 503
    assert status(client, owner)["workspace"]["url"] is None


def test_owner_invitation_mixed_email_signer_recovery_and_live_membership(lab):
    app, client = lab
    owner, staff = signed(client), signed(client, "staff-a")
    state = enrolled(client, owner, 2)
    response = mutate(client, owner, "/invitations", {"email": "staff-a@example.invalid", "role": "staff", "can_sign": False})
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    assert mutate(client, signed(client, "owner-b"), "/join", {"token": token}).status_code == 403
    joined = mutate(client, staff, "/join", {"token": token})
    assert joined.status_code == 200, joined.text
    assert joined.json()["practice"]["id"] == state["practice"]["id"]
    body = {"doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256,
            "signature_name": "Casey Example", "signature_title": "Staff", "authority_confirmed": True, "accepted": True}
    denied = mutate(client, staff, "/baa/accept", body)
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "enrollment_signer_required"
    assert mutate(client, owner, "/invitations", {"email": "signer-a@example.invalid", "role": "admin", "can_sign": True}).status_code == 409
    assert mutate(client, owner, "/baa/accept", body).status_code == 200
    assert client.get("/enrollment/v1/baa/receipt", headers=staff).status_code == 200
    assert mutate(client, staff, "/checkout", {}).status_code == 403
    with app.state.enrollment_service.sessions.begin() as session:
        member = session.scalar(select(Membership).where(Membership.role == "staff"))
        member.active = False
    assert client.get("/enrollment/v1/status", headers=staff).status_code == 409


def test_noncovered_practice_cannot_make_inaccurate_baa_assertion(lab):
    _, client = lab
    owner = signed(client)
    state = enrolled(client, owner, covered=False)
    assert state["practice"]["covered_entity"] is False
    response = mutate(client, owner, "/baa/accept", {"doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256,
        "signature_name": "Alex Example", "signature_title": "Owner", "authority_confirmed": True, "accepted": True})
    assert response.status_code == 409


def test_stale_billing_staff_refresh_requires_member_sync_and_fails_closed(lab):
    app, client = lab
    owner, staff = signed(client), signed(client, "staff-a")
    ready_checkout(client, owner, 2)
    checkout = next(iter(app.state.synthetic_commerce.sessions.values()))
    client.post("/lab/checkout/complete", json={"session_id": checkout["id"]})
    invite = mutate(client, owner, "/invitations", {"email": "staff-a@example.invalid", "role": "staff", "can_sign": False}).json()
    joined = mutate(client, staff, "/join", {"token": invite["token"]}).json()
    assert joined["stage"] == "finishing_setup" and joined["workspace"]["url"] is None
    service = app.state.enrollment_service
    service.record_membership_ready(joined["practice"]["id"], issuer="https://enrollment.example.invalid",
        subject="user_synthetic_staff-a", organization_id=joined["workspace"]["organization_id"], proof_sha256="b" * 64)
    with service.sessions.begin() as session:
        practice = session.get(Practice, joined["practice"]["id"])
        practice.billing_verified_at = datetime.now(UTC) - timedelta(minutes=10)
    assert status(client, staff)["stage"] == "ready"
    with service.sessions.begin() as session:
        practice = session.get(Practice, joined["practice"]["id"])
        practice.billing_verified_at = datetime.now(UTC) - timedelta(minutes=10)
    app.state.synthetic_commerce.fail_reads = True
    assert status(client, staff)["workspace"]["url"] is None
    assert mutate(client, staff, "/portal", {}).status_code == 403


def test_paid_invoice_authority_restores_failed_payment_without_restarting_trial(lab):
    app, client = lab
    owner = signed(client)
    ready_checkout(client, owner)
    commerce, service = app.state.synthetic_commerce, app.state.enrollment_service
    checkout = next(iter(commerce.sessions.values()))
    client.post("/lab/checkout/complete", json={"session_id": checkout["id"]})
    original_end = status(client, owner)["billing"]["trial_ends_at"]
    sub = next(iter(commerce.subscriptions.values()))
    invoice = {"id": "in_example_recovery", "subscription": sub["id"], "customer": sub["customer"]}
    raw, signature = commerce.signed_event("invoice.payment_failed", invoice, "evt_example_failed_recovery")
    service.ingest(raw, signature)
    assert status(client, owner)["workspace"]["url"] is None
    assert service.reconcile_pending()["processed"] == 1
    assert status(client, owner)["workspace"]["url"] is None
    raw, signature = commerce.signed_event("invoice.paid", invoice, "evt_example_paid_recovery", created=int(time.time()) + 1)
    service.ingest(raw, signature)
    assert service.reconcile_pending()["processed"] == 1
    assert status(client, owner)["stage"] == "ready"
    assert status(client, owner)["billing"]["trial_ends_at"] == original_end


def test_seat_shrink_and_join_recheck_cannot_bypass_reserved_human_seats(lab):
    app, client = lab
    owner, staff = signed(client), signed(client, "staff-a")
    enrolled(client, owner, 2)
    invite = mutate(client, owner, "/invitations", {"email": "staff-a@example.invalid", "role": "staff", "can_sign": False}).json()
    shrink = mutate(client, owner, "/practice", {"legal_name": "Example Practice LLC", "display_name": "Example Practice",
        "address_line1": "123 Example Street", "address_line2": "", "city": "Example City", "region": "NY", "postal_code": "10001",
        "country": "US", "administrative_email": "office@example.invalid", "human_seats": 1, "covered_entity": True}, "PUT")
    assert shrink.status_code == 409 and shrink.json()["detail"]["code"] == "enrollment_human_seat_limit"
    # Rehearse an earlier inconsistent row: join still checks purchased capacity.
    with app.state.enrollment_service.sessions.begin() as session:
        practice = session.scalar(select(Practice))
        practice.human_seats = 1
    assert mutate(client, staff, "/join", {"token": invite["token"]}).status_code == 409


def test_delayed_event_cannot_restore_canceled_subscription(lab):
    app, client = lab
    owner = signed(client)
    ready_checkout(client, owner)
    commerce, service = app.state.synthetic_commerce, app.state.enrollment_service
    checkout = next(iter(commerce.sessions.values()))
    client.post("/lab/checkout/complete", json={"session_id": checkout["id"]})
    sub = next(iter(commerce.subscriptions.values()))
    timestamp = int(time.time())
    stale_payload = json.loads(json.dumps(sub))
    sub["status"] = "canceled"
    raw, signature = commerce.signed_event("customer.subscription.deleted", sub, "evt_example_new_canceled", created=timestamp + 2)
    service.ingest(raw, signature)
    assert service.reconcile_pending()["processed"] == 1
    raw, signature = commerce.signed_event("customer.subscription.updated", stale_payload, "evt_example_old_active", created=timestamp)
    service.ingest(raw, signature)
    assert service.reconcile_pending()["processed"] == 1
    assert status(client, owner)["stage"] == "canceled"
    assert status(client, owner)["workspace"]["url"] is None


def test_multi_practice_selection_preserves_memberships_and_enforces_scope(lab):
    _, client = lab
    owner_a, owner_b, staff = signed(client), signed(client, "owner-b"), signed(client, "staff-a")
    a = enrolled(client, owner_a, 2)
    b = enrolled(client, owner_b, 2)
    for owner in (owner_a, owner_b):
        invitation = mutate(client, owner, "/invitations", {"email": "staff-a@example.invalid", "role": "staff", "can_sign": False}).json()
        assert mutate(client, staff, "/join", {"token": invitation["token"]}).status_code == 200
    practices = client.get("/enrollment/v1/practices", headers=staff).json()
    assert len(practices["practices"]) == 2
    assert practices["active_practice_id"] == b["practice"]["id"]
    assert mutate(client, staff, "/select-practice", {"practice_id": a["practice"]["id"]}).json()["practice"]["id"] == a["practice"]["id"]
    assert mutate(client, owner_a, "/select-practice", {"practice_id": b["practice"]["id"]}).status_code == 403


def test_workspace_confirmation_requires_same_human_and_second_scoped_proof(lab):
    app, client = lab
    owner, staff = signed(client), signed(client, "staff-a")
    ready_checkout(client, owner, 2)
    checkout = next(iter(app.state.synthetic_commerce.sessions.values()))
    client.post("/lab/checkout/complete", json={"session_id": checkout["id"]})
    trial_end = status(client, owner)["billing"]["trial_ends_at"]
    invitation = mutate(client, owner, "/invitations", {"email": "staff-a@example.invalid", "role": "staff", "can_sign": False}).json()
    joined = mutate(client, staff, "/join", {"token": invitation["token"]}).json()
    assert joined["stage"] == "finishing_setup"
    owner_token = client.post("/lab/session", json={"user": "owner-a"}).json()["token"]
    assert mutate(client, staff, "/workspace/confirm", {"workspace_token": owner_token}).status_code == 403
    token = client.post("/lab/session", json={"user": "staff-a"}).json()["token"]
    first = mutate(client, staff, "/workspace/confirm", {"workspace_token": token})
    assert first.status_code == 200, first.text
    assert first.json()["workspace"]["url"] is None
    assert "membership is prepared" in first.json()["action_required"]
    scoped = client.post("/lab/session", json={"user": "staff-a", "organization_id": joined["workspace"]["organization_id"]}).json()["token"]
    confirmed = mutate(client, staff, "/workspace/confirm", {"workspace_token": scoped})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["stage"] == "ready"
    assert confirmed.json()["billing"]["trial_ends_at"] == trial_end
    with app.state.enrollment_service.sessions() as session:
        for command in session.scalars(select(Command).where(Command.operation == "workspace_confirm")):
            assert token not in json.dumps(command.response)
            assert scoped not in json.dumps(command.response)
            assert owner_token not in json.dumps(command.response)
    invalid = mutate(client, staff, "/workspace/confirm", {"workspace_token": "private-fixture-value" * 1000})
    assert invalid.status_code == 422
    assert "private-fixture-value" not in invalid.text
    assert mutate(client, staff, "/workspace/confirm", {"workspace_token": scoped, "workspace_url": "https://elsewhere.invalid"}).status_code == 422


@pytest.mark.parametrize("changed", ["destination", "role", "revoked"])
def test_workspace_confirmation_rechecks_authority_and_recovers_after_changed_binding(lab, changed):
    app, client = lab
    owner, staff = signed(client), signed(client, "staff-a")
    state = accepted(client, owner, 2)
    client.post("/lab/qualify", json={"practice_id": state["practice"]["id"]})
    invitation = mutate(client, owner, "/invitations", {"email": "staff-a@example.invalid", "role": "staff", "can_sign": False}).json()
    joined = mutate(client, staff, "/join", {"token": invitation["token"]}).json()
    service = app.state.enrollment_service
    token = client.post("/lab/session", json={"user": "staff-a", "organization_id": joined["workspace"]["organization_id"]}).json()["token"]
    identity = app.state.synthetic_identities.verify(token)

    class ChangedDuringMeasurement:
        def confirm(self, request, workspace_token):
            with service.sessions.begin() as session:
                practice = session.get(Practice, request.practice_id)
                member = session.scalar(select(Membership).where(Membership.practice_id == request.practice_id, Membership.role == "staff"))
                if changed == "destination":
                    practice.workspace_url = "https://app.example.invalid/different"
                elif changed == "role":
                    member.role = "admin"
                else:
                    member.active = False
            return WorkspaceConfirmationResult("c" * 64)

    with pytest.raises(EnrollmentError):
        service.confirm_workspace(identity, str(uuid4()), joined["revision"], token, ChangedDuringMeasurement())
    with service.sessions.begin() as session:
        member = session.scalar(select(Membership).where(Membership.practice_id == joined["practice"]["id"], Membership.role != "owner"))
        assert member is not None and member.workspace_ready is False
        member.active = True
    # A fresh command measures the current saved binding instead of the old one.
    recovered = mutate(client, staff, "/workspace/confirm", {"workspace_token": token})
    assert recovered.status_code == 200, recovered.text
    with service.sessions() as session:
        member = session.scalar(select(Membership).where(Membership.practice_id == joined["practice"]["id"], Membership.role != "owner"))
        assert member is not None and member.workspace_ready is True


def test_old_version_row_cannot_hide_missing_required_private_columns(lab):
    app, _ = lab
    engine = app.state.enrollment_service.sessions.kw["bind"]
    assert schema_ready(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE enrollment_practices DROP COLUMN workspace_api_origin"))
    assert schema_ready(engine) is False
    with pytest.raises(RuntimeError, match="explicit additive migration"):
        upgrade(engine)


def test_production_cannot_install_synthetic_workspace_confirmer():
    class FakeConfirmer:
        def confirm(self, request, workspace_token):
            return WorkspaceConfirmationResult("a" * 64)
    with pytest.raises(RuntimeError, match="real workspace confirmation port"):
        create_app(EnrollmentSettings(data_mode="production"), workspace_confirmer=FakeConfirmer())


def test_fourteen_day_expiry_has_no_grace_or_automatic_second_trial(lab, monkeypatch):
    from cosmas_os.enrollment import service as service_module
    app, client = lab
    owner = signed(client)
    ready_checkout(client, owner)
    checkout = next(iter(app.state.synthetic_commerce.sessions.values()))
    client.post("/lab/checkout/complete", json={"session_id": checkout["id"]})
    sub = next(iter(app.state.synthetic_commerce.subscriptions.values()))
    monkeypatch.setattr(service_module, "now_utc", lambda: datetime.fromtimestamp(sub["trial_end"], UTC))
    expired = status(client, owner)
    assert expired["workspace"]["url"] is None
    assert expired["stage"] == "payment_action_required"
    assert mutate(client, owner, "/checkout", {}).status_code == 409
    assert app.state.synthetic_commerce.create_count == 1
