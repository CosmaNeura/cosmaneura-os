"""Synthetic staging self-serve trial activation; production stays closed."""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from cosmas_os.enrollment.config import EnrollmentSettings
from cosmas_os.enrollment.domain import BAA_DOC_ID, BAA_SHA256, BAA_VERSION
from cosmas_os.enrollment.environments import HOSTING_ENVIRONMENTS
from cosmas_os.enrollment.synthetic import create_synthetic_app, synthetic_settings

STAGING_APP = HOSTING_ENVIRONMENTS["staging"].app_origin


def _staging_settings(**overrides) -> EnrollmentSettings:
    settings = synthetic_settings()
    settings.public_app_origin = STAGING_APP
    settings.allowed_origins = [STAGING_APP]
    settings.clerk_authorized_parties = [STAGING_APP]
    settings.activation_available = False
    settings.stripe_acquisition_enabled = False
    settings.workspace_allocation_enabled = True
    settings.provisioning_enabled = True
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def test_synthetic_staging_self_serve_admits_without_activation_env_flags():
    settings = _staging_settings()
    value = settings.public_config(database_ready=True, auth_ready=True, stripe_verified=True)
    assert value["activation_available"] is True
    assert value["checkout_recovery_available"] is True
    assert value["activation_blockers"] == []
    assert value["data_mode"] == "synthetic"


def test_lab_fixture_origin_does_not_admit_without_activation_flags():
    settings = synthetic_settings()
    settings.activation_available = False
    settings.stripe_acquisition_enabled = False
    settings.workspace_allocation_enabled = True
    settings.provisioning_enabled = True
    assert settings.synthetic_staging_host() is False
    value = settings.public_config(database_ready=True, auth_ready=True, stripe_verified=True)
    assert value["activation_available"] is False
    assert value["checkout_recovery_available"] is False
    assert any("ACTIVATION_AVAILABLE" in item for item in value["activation_blockers"])


def test_synthetic_without_allocation_stays_closed_when_flags_false():
    settings = _staging_settings(workspace_allocation_enabled=False)
    value = settings.public_config(database_ready=True, auth_ready=True, stripe_verified=True)
    assert value["activation_available"] is False
    assert value["checkout_recovery_available"] is False
    assert any("allocation" in item.lower() for item in value["activation_blockers"])


def test_production_never_uses_synthetic_self_serve_admit():
    settings = EnrollmentSettings(
        enabled=True,
        data_mode="production",
        production_qualified=True,
        database_url=SecretStr("postgresql+psycopg://enrollment:x@127.0.0.1/enrollment"),
        public_app_origin="https://app.cosmas.ai",
        allowed_origins=["https://app.cosmas.ai"],
        clerk_publishable_key="pk_live_synthetic",
        clerk_secret_key=SecretStr("sk_live_synthetic"),
        clerk_issuer="https://clerk.cosmas.ai",
        clerk_authorized_parties=["https://app.cosmas.ai"],
        clerk_methods_verified=True,
        stripe_integration_enabled=True,
        stripe_acquisition_enabled=False,
        stripe_secret_key=SecretStr("sk_live_synthetic"),
        stripe_account_id="acct_synthetic",
        stripe_base_price_id="price_syntheticbase",
        stripe_portal_configuration_id="bpc_synthetic",
        stripe_webhook_secret=SecretStr("whsec_synthetic"),
        stripe_live_mode=True,
        commercial_terms_verified=True,
        activation_available=False,
        provisioning_enabled=True,
        workspace_allocation_enabled=True,
        invitation_secret=SecretStr("production-invitation-key-never-synthetic"),
        runtime_admission_secret=SecretStr("production-control-admission-master-never-synthetic"),
    )
    assert settings.synthetic_staging_self_serve_ready(
        billing=True, registration_blockers=[], workspace_confirmation_configured=True
    ) is False
    value = settings.public_config(database_ready=True, auth_ready=True, stripe_verified=True)
    assert value["activation_available"] is False


def test_lab_accept_does_not_auto_ready_when_origin_is_not_staging_host():
    app = create_synthetic_app()
    service = app.state.enrollment_service
    service.settings.activation_available = False
    service.settings.stripe_acquisition_enabled = False
    service.settings.workspace_allocation_enabled = True
    service.settings.provisioning_enabled = True
    assert service.settings.synthetic_staging_host() is False
    with TestClient(app) as client:
        token = client.post("/lab/session", json={"user": "owner-a"}).json()["token"]
        headers = {"Authorization": "Bearer " + token}

        def write(path, body, method="POST"):
            state = client.get("/enrollment/v1/status", headers=headers).json()
            response = client.request(
                method,
                "/enrollment/v1" + path,
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"expected_revision": state["revision"], **body},
            )
            assert response.status_code == 200, response.text
            return response.json()

        write("/profile", {"display_name": "Alex Example", "title": "Owner"}, "PUT")
        write(
            "/practice",
            {
                "legal_name": "Invented Lab Clinic LLC",
                "display_name": "Invented Lab Clinic",
                "address_line1": "123 Invented Street",
                "city": "Invented City",
                "region": "NY",
                "postal_code": "10001",
                "administrative_email": "office@example.invalid",
                "human_seats": 1,
                "covered_entity": True,
            },
            "PUT",
        )
        accepted = write(
            "/baa/accept",
            {
                "doc_id": BAA_DOC_ID,
                "version": BAA_VERSION,
                "sha256": BAA_SHA256,
                "signature_name": "Alex Example",
                "signature_title": "Owner",
                "authority_confirmed": True,
                "accepted": True,
            },
        )
        assert accepted["workspace"]["status"] == "pending"
        assert accepted["stage"] == "activation_pending"
        assert accepted["workspace"]["box_id"] is None


def test_accept_auto_readies_synthetic_staging_workspace_and_checkout_opens():
    app = create_synthetic_app()
    service = app.state.enrollment_service
    service.settings.public_app_origin = STAGING_APP
    service.settings.allowed_origins = [STAGING_APP]
    service.settings.clerk_authorized_parties = [STAGING_APP]
    service.settings.activation_available = False
    service.settings.stripe_acquisition_enabled = False
    service.settings.workspace_allocation_enabled = True
    service.settings.provisioning_enabled = True
    service.settings.allowed_workspace_origins = []
    assert service.settings.synthetic_staging_host() is True
    with TestClient(app) as client:
        token = client.post("/lab/session", json={"user": "owner-a"}).json()["token"]
        headers = {"Authorization": "Bearer " + token}

        def write(path, body, method="POST"):
            state = client.get("/enrollment/v1/status", headers=headers).json()
            response = client.request(
                method,
                "/enrollment/v1" + path,
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"expected_revision": state["revision"], **body},
            )
            assert response.status_code == 200, response.text
            return response.json()

        write("/profile", {"display_name": "Alex Example", "title": "Owner"}, "PUT")
        write(
            "/practice",
            {
                "legal_name": "Invented Staging Clinic LLC",
                "display_name": "Invented Staging Clinic",
                "address_line1": "123 Invented Street",
                "city": "Invented City",
                "region": "NY",
                "postal_code": "10001",
                "administrative_email": "office@example.invalid",
                "human_seats": 1,
                "covered_entity": True,
            },
            "PUT",
        )
        accepted = write(
            "/baa/accept",
            {
                "doc_id": BAA_DOC_ID,
                "version": BAA_VERSION,
                "sha256": BAA_SHA256,
                "signature_name": "Alex Example",
                "signature_title": "Owner",
                "authority_confirmed": True,
                "accepted": True,
            },
        )
        assert accepted["workspace"]["status"] == "ready"
        assert accepted["workspace"]["url"] is None  # not entitled until trial
        assert accepted["stage"] == "payment"
        assert accepted["billing"]["trial_ends_at"] is None
        practice_id = accepted["practice"]["id"]
        assert accepted["workspace"]["box_id"]
        assert accepted["workspace"]["organization_id"].startswith("org_synthetic")

        config = client.get("/enrollment/v1/config").json()
        assert config["activation_available"] is True
        assert config["activation_blockers"] == []

        checkout = client.post(
            "/enrollment/v1/checkout",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"expected_revision": accepted["revision"]},
        )
        assert checkout.status_code == 200, checkout.text
        body = checkout.json()
        assert body["status"] == "open"
        assert body["url"].startswith("https://checkout.stripe.com/")
        pending = client.get("/enrollment/v1/status", headers=headers).json()
        assert pending["stage"] == "finishing_setup"
        assert pending["practice"]["id"] == practice_id
