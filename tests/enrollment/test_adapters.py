from __future__ import annotations

import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from cosmas_os.enrollment.auth import ClerkEnrollmentVerifier
from cosmas_os.enrollment.domain import EnrollmentError
from cosmas_os.enrollment.stripe import StripeCommerce
from cosmas_os.enrollment.synthetic import SyntheticCommerce, synthetic_settings


@pytest.fixture
def identity_adapter():
    settings = synthetic_settings()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    evidence = {"session_status": "active", "email_verified": True, "fetches": 0, "banned": False, "membership": True}

    def transport(request):
        if "/sessions/" in request.url.path:
            return httpx.Response(200, json={"id": "sess_example", "user_id": "user_example", "status": evidence["session_status"]})
        if "/memberships" in request.url.path:
            return httpx.Response(200, json={"data": [{"public_user_data": {"user_id": "user_example"},
                "organization": {"id": "org_example"}}] if evidence["membership"] else []})
        return httpx.Response(200, json={"id": "user_example", "primary_email_address_id": "email_example",
            "banned": evidence["banned"],
            "first_name": "Example", "last_name": "Human", "email_addresses": [{"id": "email_example", "email_address": "verified@example.invalid",
                "verification": {"status": "verified" if evidence["email_verified"] else "unverified"}}]})

    class Keys:
        def get_signing_keys(self, refresh):
            evidence["fetches"] += 1
            return [SimpleNamespace(key_id="key_example", key=key.public_key())]

    verifier = ClerkEnrollmentVerifier(settings, client=httpx.Client(transport=httpx.MockTransport(transport)), jwks_client=Keys())

    def token(changes=None, remove=(), kid="key_example"):
        now = int(time.time())
        claims = {"iss": settings.clerk_issuer, "sub": "user_example", "sid": "sess_example",
                  "azp": settings.public_app_origin, "iat": now, "nbf": now, "exp": now + 300,
                  "email": "untrusted-claim@example.invalid"}
        claims.update(changes or {})
        for name in remove:
            claims.pop(name, None)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})

    return verifier, token, evidence


def test_real_shaped_default_clerk_session_has_no_audience_and_uses_live_email(identity_adapter):
    verifier, token, evidence = identity_adapter
    identity = verifier.verify(token())
    assert identity.email == "verified@example.invalid"
    assert identity.subject == "user_example" and identity.session_id == "sess_example"
    assert evidence["fetches"] == 1


def test_runtime_scoped_party_and_live_session_do_not_relax_signup(identity_adapter):
    verifier, token, evidence = identity_adapter
    workspace = "https://practice.example.invalid"
    scoped = token({"azp": workspace, "o": {"id": "org_example"}})
    with pytest.raises(EnrollmentError):
        verifier.verify(scoped)
    assert verifier.verify_scoped(scoped, "org_example", authorized_parties=[workspace]).subject == "user_example"
    with pytest.raises(EnrollmentError):
        verifier.verify_scoped(scoped, "org_other", authorized_parties=[workspace])
    with pytest.raises(EnrollmentError):
        verifier.verify_scoped(token({"org_id": "org_example"}), "org_example", authorized_parties=[workspace])
    evidence["session_status"] = "revoked"
    with pytest.raises(EnrollmentError):
        verifier.verify_scoped(scoped, "org_example", authorized_parties=[workspace])


def test_worker_live_member_checks_do_not_retain_or_require_session(identity_adapter):
    verifier, _, evidence = identity_adapter
    evidence["session_status"] = "revoked"
    assert verifier.verify_registered_member("user_example", "org_example").session_id == ""
    evidence["banned"] = True
    with pytest.raises(EnrollmentError):
        verifier.verify_registered_member("user_example", "org_example")
    evidence["banned"] = False
    evidence["membership"] = False
    with pytest.raises(EnrollmentError):
        verifier.verify_registered_member("user_example", "org_example")


@pytest.mark.parametrize("changes", [{"aud": "other-api"}, {"aud": None}, {"aud": []},
    {"azp": "https://other.example.invalid"}, {"iss": "https://other-clerk.example.invalid"},
    {"exp": int(time.time()) - 60}])
def test_wrong_clerk_claims_denied(identity_adapter, changes):
    verifier, token, _ = identity_adapter
    with pytest.raises(EnrollmentError, match="Sign in"):
        verifier.verify(token(changes))


def test_named_template_without_sid_and_unknown_kids_denied_without_fetch_storm(identity_adapter):
    verifier, token, evidence = identity_adapter
    with pytest.raises(EnrollmentError):
        verifier.verify(token(remove=["sid"]))
    for index in range(20):
        with pytest.raises(EnrollmentError):
            verifier.verify(token(kid="unknown" + str(index)))
    assert evidence["fetches"] == 1


@pytest.mark.parametrize(("field", "value"), [("session_status", "revoked"), ("email_verified", False)])
def test_revoked_session_or_unverified_primary_email_denied(identity_adapter, field, value):
    verifier, token, evidence = identity_adapter
    evidence[field] = value
    with pytest.raises(EnrollmentError):
        verifier.verify(token())


@pytest.fixture
def stripe_adapter():
    settings = synthetic_settings()
    observed = {"posts": [], "price_amount": 30000, "portal_update": False, "fail_post": 0}

    def transport(request):
        path = request.url.path
        if path == "/v1/account":
            return httpx.Response(200, json={"id": settings.stripe_account_id})
        if path.startswith("/v1/prices/"):
            price_id = path.split("/")[-1]
            amount = observed["price_amount"] if price_id == settings.stripe_base_price_id else 10000
            return httpx.Response(200, json={"id": price_id, "livemode": False, "active": True, "currency": "usd",
                "unit_amount": amount, "type": "recurring", "billing_scheme": "per_unit",
                "recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"}})
        if path.startswith("/v1/billing_portal/configurations/"):
            return httpx.Response(200, json={"id": settings.stripe_portal_configuration_id, "livemode": False, "active": True,
                "login_page": {"enabled": False}, "features": {"subscription_update": {"enabled": observed["portal_update"]},
                    "customer_update": {"enabled": False}, "invoice_history": {"enabled": True},
                    "payment_method_update": {"enabled": True}, "subscription_cancel": {"enabled": True, "mode": "at_period_end"}}})
        observed["posts"].append({"path": path, "data": parse_qs(request.content.decode()), "key": request.headers.get("Idempotency-Key")})
        if observed["fail_post"]:
            observed["fail_post"] -= 1
            return httpx.Response(503, text="not JSON")
        if path == "/v1/billing_portal/sessions":
            return httpx.Response(200, json={"url": "https://billing.stripe.com/p/session/example"})
        return httpx.Response(200, json={"id": "cs_example", "status": "open"})

    adapter = StripeCommerce(settings, client=httpx.Client(transport=httpx.MockTransport(transport)))
    request = {"attempt_id": "attempt-example", "practice_id": "practice-example", "human_seats": 10,
               "email": "owner@example.invalid", "customer_id": None, "base_price_id": settings.stripe_base_price_id,
               "additional_price_id": settings.stripe_additional_price_id, "account_id": settings.stripe_account_id,
               "api_version": settings.stripe_api_version, "live_mode": False, "trial_days": 14,
               "app_origin": settings.public_app_origin}
    return adapter, request, observed


def test_real_stripe_transport_freezes_approved_price_total_exact_trial_and_card(stripe_adapter):
    adapter, request, observed = stripe_adapter
    adapter.create_checkout(request, "saved-key")
    data = observed["posts"][0]["data"]
    assert data["line_items[0][quantity]"] == ["1"]
    assert data["line_items[1][quantity]"] == ["9"]
    assert data["subscription_data[trial_period_days]"] == ["14"]
    assert data["payment_method_collection"] == ["always"]
    assert data["metadata[monthly_total_cents]"] == ["120000"]
    assert data["automatic_tax[enabled]"] == ["false"]
    assert data["subscription_data[trial_settings][end_behavior][missing_payment_method]"] == ["pause"]
    assert observed["posts"][0]["key"] == "saved-key"


def test_configuration_drift_wrong_price_or_unsafe_portal_never_posts_checkout(stripe_adapter):
    adapter, request, observed = stripe_adapter
    observed["price_amount"] = 8900
    with pytest.raises(EnrollmentError):
        adapter.create_checkout(request, "saved-key")
    assert observed["posts"] == []
    observed["price_amount"], observed["portal_update"] = 30000, True
    with pytest.raises(EnrollmentError):
        adapter.create_checkout(request, "saved-key")
    assert observed["posts"] == []
    observed["portal_update"] = False
    with pytest.raises(EnrollmentError):
        adapter.create_checkout({**request, "human_seats": 11}, "saved-key")
    adapter.settings.stripe_base_price_id = "price_new"
    with pytest.raises(EnrollmentError, match="Reconcile"):
        adapter.create_checkout(request, "saved-key")


def test_retry_uses_original_key_after_malformed_error_body(stripe_adapter, monkeypatch):
    adapter, request, observed = stripe_adapter
    monkeypatch.setattr(time, "sleep", lambda _: None)
    observed["fail_post"] = 1
    adapter.create_checkout(request, "same-saved-key")
    assert [p["key"] for p in observed["posts"]] == ["same-saved-key", "same-saved-key"]
    assert observed["posts"][0]["data"] == observed["posts"][1]["data"]


def test_real_webhook_verifies_signature_mode_api_and_replay_window():
    settings = synthetic_settings()
    fake = SyntheticCommerce(settings)
    adapter = StripeCommerce(settings)
    raw, signature = fake.signed_event("invoice.paid", {"id": "in_example", "subscription": "sub_example"}, "evt_example")
    assert adapter.verify_event(raw, signature)["id"] == "evt_example"
    for changed in [raw + b" ", json.dumps({"id": "evt_tampered"}).encode()]:
        with pytest.raises(EnrollmentError):
            adapter.verify_event(changed, signature)
    with pytest.raises(EnrollmentError):
        adapter.verify_event(raw, signature.replace("t=", "t=0"))
