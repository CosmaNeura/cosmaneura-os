"""Private composition checks with invented Stripe HTTP and real Clerk verifier.

These fixtures do not qualify hosted services or a customer's workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import Context
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4, uuid5

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from tests.enrollment.clock_harness import ProviderDouble, signed_event

from cosmas_os.adapters.enrollment_admission import (
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
from cosmas_os.enrollment.auth import ClerkEnrollmentVerifier
from cosmas_os.enrollment.domain import (
    BAA_DOC_ID,
    BAA_SHA256,
    BAA_VERSION,
    EnrollmentError,
)
from cosmas_os.enrollment.migration import upgrade
from cosmas_os.enrollment.models import Practice, StripeInbox
from cosmas_os.enrollment.private_clock_lab import (
    BOX_NAMESPACE,
    ClockLabBinding,
    PostgresClockJournal,
    create_clock_lab_app,
    prepare_clock_binding,
)
from cosmas_os.enrollment.service import EnrollmentService
from cosmas_os.enrollment.stripe import StripeCommerce
from cosmas_os.enrollment.synthetic import synthetic_settings


class Provider(ProviderDouble):
    def __init__(self, settings):
        super().__init__(settings)
        self.reads = []
        self.async_advance = False

    def request(self, request):
        self.reads.append((request.method, request.url.path))
        if request.url.path == "/v1/subscriptions":
            return httpx.Response(
                200, json={"data": list(self.subscriptions.values()), "has_more": False}
            )
        response = super().request(request)
        if request.url.path.endswith("/advance") and self.async_advance:
            self.clock["status"] = "advancing"
        return response


@pytest.fixture
def lab(tmp_path, postgres_journal):
    tmp_path.chmod(0o700)
    settings = synthetic_settings()
    settings.public_app_origin = "https://onboarding.staging.cosmas.ai"
    settings.allowed_origins = settings.clerk_authorized_parties = [settings.public_app_origin]
    settings.allowed_workspace_origins = ["https://practice-a.staging.cosmas.ai"]
    settings.clerk_issuer = "https://example-instance.clerk.accounts.dev"
    settings.clerk_publishable_key = (
        "pk_test_"
        + __import__("base64").b64encode(b"example-instance.clerk.accounts.dev$").decode()
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    evidence = {"banned": False, "membership": True, "session_active": True}

    def clerk(request):
        assert request.url.host == "api.clerk.com"
        if "/sessions/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "id": "sess_example",
                    "user_id": "user_example",
                    "status": "active" if evidence["session_active"] else "revoked",
                },
            )
        if "/memberships" in request.url.path:
            org = request.url.path.split("/")[3]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "public_user_data": {"user_id": "user_example"},
                            "organization": {"id": org},
                        }
                    ]
                    if evidence["membership"]
                    else []
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "user_example",
                "banned": evidence["banned"],
                "primary_email_address_id": "email_example",
                "first_name": "Example",
                "last_name": "Owner",
                "email_addresses": [
                    {
                        "id": "email_example",
                        "email_address": "owner@example.invalid",
                        "verification": {"status": "verified"},
                    }
                ],
            },
        )

    class Keys:
        def get_signing_keys(self, refresh):
            return [SimpleNamespace(key_id="key_example", key=key.public_key())]

    def token(changes=None):
        stamp = int(time.time())
        claims = {
            "iss": settings.clerk_issuer,
            "sub": "user_example",
            "sid": "sess_example",
            "azp": settings.public_app_origin,
            "iat": stamp,
            "nbf": stamp,
            "exp": stamp + 3600,
        }
        claims.update(changes or {})
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key_example"})

    clerk_client = httpx.Client(transport=httpx.MockTransport(clerk))
    provider = Provider(settings)
    stripe_client = httpx.Client(transport=httpx.MockTransport(provider.request))
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "enrollment.sqlite"),
        connect_args={"check_same_thread": False},
    )
    upgrade(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    verifier = ClerkEnrollmentVerifier(settings, client=clerk_client, jwks_client=Keys())
    identity = verifier.verify(token())
    service = EnrollmentService(sessions, settings, StripeCommerce(settings, client=stripe_client))
    state = service.profile(
        identity,
        "profile",
        {"expected_revision": 0, "display_name": "Example Owner", "title": "Owner"},
    )
    state = service.practice(
        identity,
        "practice",
        {
            "expected_revision": state["revision"],
            "legal_name": "Example Clinic LLC",
            "display_name": "Example Clinic",
            "address_line1": "123 Example Road",
            "address_line2": "",
            "city": "Example City",
            "region": "NY",
            "postal_code": "10001",
            "country": "US",
            "administrative_email": "office@example.invalid",
            "human_seats": 2,
            "covered_entity": True,
        },
    )
    service.accept(
        identity,
        "baa",
        {
            "expected_revision": state["revision"],
            "doc_id": BAA_DOC_ID,
            "version": BAA_VERSION,
            "sha256": BAA_SHA256,
            "signature_name": "Example Owner",
            "signature_title": "Owner",
            "authority_confirmed": True,
            "accepted": True,
        },
    )
    practice_id = state["practice"]["id"]
    box_id = str(uuid5(BOX_NAMESPACE, practice_id))
    service.record_workspace(
        practice_id,
        box_id=box_id,
        organization_id="org_example",
        url="https://practice-a.staging.cosmas.ai/chief",
        status="provisioning",
        proof_sha256="a" * 64,
        workspace_api_origin="https://api.practice-a.staging.cosmas.ai",
        source_commit="a" * 40,
        image_sha256="b" * 64,
    )
    binding = ClockLabBinding(
        synthetic_only=True,
        practice_id=practice_id,
        box_id=box_id,
        organization_id="org_example",
        owner_subject="user_example",
        issuer=settings.clerk_issuer,
        app_origin=settings.public_app_origin,
        api_origin="https://enrollment-clock.staging.cosmas.ai",
        workspace_url="https://practice-a.staging.cosmas.ai/chief",
        workspace_api_origin="https://api.practice-a.staging.cosmas.ai",
        source_commit="a" * 40,
        image_sha256="b" * 64,
        stripe_account_id=settings.stripe_account_id,
        stripe_base_price_id=settings.stripe_base_price_id,
        stripe_additional_price_id=settings.stripe_additional_price_id,
        stripe_portal_configuration_id=settings.stripe_portal_configuration_id,
        stripe_api_version=settings.stripe_api_version,
        customer_id=provider.customer["id"],
        clock_id=provider.clock["id"],
        initial_frozen_time=provider.clock["frozen_time"],
        journal_host=postgres_journal.engine.url.host,
        journal_port=postgres_journal.engine.url.port,
        journal_database="cosmabot_enrollment_clock_lab",
    )
    paths = {"binding_path": tmp_path / "binding.json"}
    ports = {"stripe_client": stripe_client, "clerk_client": clerk_client, "jwks_client": Keys()}
    prepare_clock_binding(
        settings,
        engine,
        binding.model_dump(),
        **paths,
        **ports,
        journal_engine=postgres_journal.engine,
    )

    def factory(**changes):
        return create_clock_lab_app(
            changes.pop("settings", settings),
            engine=engine,
            **paths,
            **{
                **ports,
                "journal": PostgresClockJournal(postgres_journal.engine, binding),
                **changes,
            },
        )

    app = factory()
    with TestClient(app) as client:
        yield SimpleNamespace(
            settings=settings,
            engine=engine,
            sessions=sessions,
            provider=provider,
            binding=binding,
            app=app,
            client=client,
            service=app.state.enrollment_service,
            commerce=app.state.private_clock_commerce,
            paths=paths,
            ports=ports,
            factory=factory,
            evidence=evidence,
            token=token,
            identity=identity,
            headers={"Authorization": "Bearer " + token()},
        )
    clerk_client.close()
    stripe_client.close()
    engine.dispose()


def start_trial(lab):
    """Unit registry fixture only; actual runtime setup is a separate PG check."""
    b = lab.binding
    lab.service.record_workspace(
        b.practice_id,
        box_id=b.box_id,
        organization_id=b.organization_id,
        url=b.workspace_url,
        status="ready",
        proof_sha256="c" * 64,
    )
    revision = lab.client.get("/enrollment/v1/status", headers=lab.headers).json()["revision"]
    response = lab.client.post(
        "/enrollment/v1/checkout",
        headers={**lab.headers, "Idempotency-Key": "unit-checkout"},
        json={"expected_revision": revision},
    )
    assert response.status_code == 200, response.text
    session = next(iter(lab.provider.sessions))
    lab.provider.complete(session)
    revision = lab.client.get("/enrollment/v1/status", headers=lab.headers).json()["revision"]
    response = lab.client.post(
        "/enrollment/v1/recover",
        headers={**lab.headers, "Idempotency-Key": "unit-recover"},
        json={"expected_revision": revision},
    )
    assert response.status_code == 200, response.text
    return session


def test_prepare_and_factory_require_single_scope_and_no_public_clock_inputs(lab):
    assert isinstance(lab.app.state.enrollment_service, EnrollmentService)
    assert isinstance(lab.commerce, StripeCommerce)
    assert not any("clock" in route.path or "/lab/" in route.path for route in lab.app.routes)
    for changes in [
        {"sub": "user_other"},
        {"org_id": "org_other"},
        {"aud": "unexpected"},
        {"exp": int(time.time()) - 60},
    ]:
        lab.provider.reads.clear()
        response = lab.client.get(
            "/enrollment/v1/status", headers={"Authorization": "Bearer " + lab.token(changes)}
        )
        assert response.status_code in (401, 403)
        assert response.headers["cache-control"] == "no-store"
        assert not lab.provider.reads
    assert (
        lab.client.post("/enrollment/v1/practice", headers=lab.headers, json={}).status_code == 503
    )
    response = lab.client.post(
        "/enrollment/v1/checkout",
        headers={**lab.headers, "Idempotency-Key": "bad-body"},
        json={"expected_revision": 0, "customer_id": "cus_other", "frozen_time": 1},
    )
    assert response.status_code == 422


def test_interrupted_preparation_replays_same_binding_without_resetting_journal(lab, postgres_journal, tmp_path):
    binding = lab.binding.model_copy(update={"customer_id": "cus_interruptedexample"})
    lab.provider.customer["id"] = binding.customer_id
    path = tmp_path / "interrupted-binding.json"

    def prepare():
        prepare_clock_binding(
            lab.settings, lab.engine, binding.model_dump(), binding_path=path,
            journal_engine=postgres_journal.engine, **lab.ports,
        )

    def interrupt_insert(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO private_stripe_clock_journal"):
            raise RuntimeError("Synthetic journal-write interruption")

    event.listen(postgres_journal.engine, "before_cursor_execute", interrupt_insert)
    try:
        with pytest.raises(RuntimeError, match="Synthetic journal-write interruption"):
            prepare()
    finally:
        event.remove(postgres_journal.engine, "before_cursor_execute", interrupt_insert)

    assert json.loads(path.read_text()) == binding.model_dump()
    with postgres_journal.engine.connect() as connection:
        assert connection.execute(text(
            "SELECT count(*) FROM private_stripe_clock_journal WHERE binding_sha256=:binding"
        ), {"binding": binding.sha256}).scalar_one() == 0
    prepare()
    journal = PostgresClockJournal(postgres_journal.engine, binding)
    initial = journal.read()
    assert initial["subscription_id"] is None and initial["high_water"] == binding.initial_frozen_time

    path.write_text(json.dumps(binding.model_dump(), indent=2))
    equivalent = path.read_bytes()
    prepare()
    assert path.read_bytes() == equivalent and journal.read() == initial

    stamp = binding.initial_frozen_time
    journal.subscription({"id": "sub_preservedexample", "trial_start": stamp, "trial_end": stamp + 14 * 86400})
    journal.observe(stamp + 1)
    journal.target("before")
    preserved = journal.read()
    assert PostgresClockJournal.prepare_database(postgres_journal.engine, binding).read() == preserved

    path.write_text(json.dumps({**binding.model_dump(), "owner_subject": "user_other"}))
    foreign = path.read_bytes()
    with pytest.raises(EnrollmentError):
        prepare()
    assert path.read_bytes() == foreign and journal.read() == preserved


def test_exact_account_origin_cors_on_direct_roster_denial_and_preflight(lab):
    for origin, allowed in [
        (lab.binding.app_origin, True),
        ("https://foreign.staging.cosmas.ai", False),
    ]:
        for path, token in [
            ("practices", lab.token()),
            ("status", lab.token({"sub": "user_other"})),
        ]:
            response = lab.client.get(
                "/enrollment/v1/" + path,
                headers={"Origin": origin, "Authorization": "Bearer " + token},
            )
            assert response.status_code == (200 if path == "practices" else 403)
            assert response.headers.get("access-control-allow-origin") == (
                lab.binding.app_origin if allowed else None
            )
            assert response.headers["cache-control"] == "no-store"
            if allowed:
                assert "origin" in response.headers["vary"].lower()
        preflight = lab.client.options(
            "/enrollment/v1/checkout",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type, X-Cosmas-Enrollment-Contract",
            },
        )
        assert preflight.status_code == (200 if allowed else 400)
        assert preflight.headers.get("access-control-allow-origin") == (
            lab.binding.app_origin if allowed else None
        )


def test_no_trial_starts_while_actual_setup_is_pending(lab):
    revision = lab.client.get("/enrollment/v1/status", headers=lab.headers).json()["revision"]
    response = lab.client.post(
        "/enrollment/v1/checkout",
        headers={**lab.headers, "Idempotency-Key": "pending"},
        json={"expected_revision": revision},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "enrollment_activation_pending"
    assert not lab.provider.sessions and not lab.provider.subscriptions


def test_factory_rejects_production_foreign_binding_and_unqualified_file_custody(lab):
    with pytest.raises(EnrollmentError):
        lab.factory(settings=lab.settings.model_copy(update={"data_mode": "production"}))
    with pytest.raises(EnrollmentError, match="private qualification"):
        lab.factory(journal=None)
    changed = lab.binding.model_dump()
    changed["organization_id"] = "org_other"
    lab.paths["binding_path"].write_text(json.dumps(changed))
    lab.paths["binding_path"].chmod(0o600)
    with pytest.raises(EnrollmentError):
        lab.factory()


def test_ready_clock_high_water_survives_unready_outage_and_restart(lab):
    stamp = lab.commerce.now().timestamp()
    lab.provider.clock["frozen_time"] += 20
    assert lab.commerce.now().timestamp() == stamp + 20
    lab.provider.clock["status"] = "advancing"
    with pytest.raises(EnrollmentError):
        lab.commerce.now()
    lab.provider.clock.update(status="ready", frozen_time=int(stamp))
    with pytest.raises(EnrollmentError):
        lab.factory()
    lab.provider.clock["frozen_time"] = int(stamp) + 20
    assert lab.factory().state.private_clock_commerce.now().timestamp() == stamp + 20
    lab.provider.fail_reads = True
    with pytest.raises(EnrollmentError):
        lab.commerce.now()
    lab.provider.fail_reads = False
    assert lab.commerce.now().timestamp() == stamp + 20


def test_original_trial_and_pending_advance_survive_restart_without_retrial(lab):
    start_trial(lab)
    trial = lab.commerce.journal.read()
    assert trial["trial_end"] - trial["trial_start"] == 14 * 86400
    lab.provider.async_advance = True
    assert lab.commerce.advance("before")["state"] == "pending"
    with pytest.raises(EnrollmentError):
        lab.commerce.now()
    lab.provider.clock["status"] = "ready"
    resumed = lab.factory().state.private_clock_commerce
    assert resumed.now().timestamp() == trial["trial_end"] - 1
    assert resumed.journal.read()["pending_target"] is None
    lab.provider.async_advance = False
    assert resumed.advance("expiry")["state"] == "ready"
    assert resumed.now().timestamp() == trial["trial_end"]
    with pytest.raises(EnrollmentError):
        resumed.advance("before")
    subscription = next(iter(lab.provider.subscriptions.values()))
    subscription["trial_end"] += 1
    with pytest.raises(EnrollmentError):
        resumed.retrieve_subscription(subscription["id"])
    assert len(lab.provider.subscriptions) == 1 and lab.provider.checkout_count == 1


def test_signed_events_are_scoped_and_durable_while_clock_advances(lab):
    start_trial(lab)
    sub = next(iter(lab.provider.subscriptions.values()))
    lab.provider.clock["status"] = "advancing"
    raw, signature = signed_event(
        lab.commerce, "customer.subscription.updated", sub, "evt_labupdate"
    )
    response = lab.client.post(
        "/enrollment/v1/webhooks/stripe", content=raw, headers={"Stripe-Signature": signature}
    )
    assert response.status_code == 200, response.text
    with lab.sessions() as session:
        assert session.get(StripeInbox, "evt_labupdate") is not None
        assert session.get(Practice, lab.binding.practice_id).billing_verified_at is None
    raw, signature = signed_event(
        lab.commerce,
        "customer.subscription.updated",
        {**sub, "customer": "cus_other"},
        "evt_foreign",
    )
    response = lab.client.post(
        "/enrollment/v1/webhooks/stripe", content=raw, headers={"Stripe-Signature": signature}
    )
    assert response.status_code == 503
    with lab.sessions() as session:
        assert session.get(StripeInbox, "evt_foreign") is None


def test_canonical_cancel_at_expiry_prevents_first_charge(lab):
    start_trial(lab)
    sub = next(iter(lab.provider.subscriptions.values()))
    sub["cancel_at_period_end"] = True
    assert lab.commerce.advance("expiry")["state"] == "ready"
    assert sub["status"] == "canceled" and lab.provider.charge_count == 0
    lab.service.reconcile_subscriptions()
    assert not lab.service._entitled(next_practice(lab))
    assert not lab.provider.invoices
    assert lab.provider.checkout_count == 1


def test_canonical_same_invoice_failure_recovery_keeps_original_trial(lab):
    start_trial(lab)
    original = lab.commerce.journal.read()
    lab.provider.transition = "failure"
    assert lab.commerce.advance("expiry")["state"] == "ready"
    raw, signature = signed_event(
        lab.commerce,
        "invoice.payment_failed",
        lab.provider.invoices["in_syntheticm3"],
        "evt_labfailure",
    )
    assert (
        lab.client.post(
            "/enrollment/v1/webhooks/stripe", content=raw, headers={"Stripe-Signature": signature}
        ).status_code
        == 200
    )
    lab.service.reconcile_subscriptions()
    assert not lab.service._entitled(next_practice(lab))
    lab.provider.pay_same_invoice()
    lab.service.reconcile_subscriptions()
    assert lab.service._entitled(next_practice(lab))
    lab.service.reconcile_subscriptions()
    assert lab.commerce.journal.read()["trial_start"] == original["trial_start"]
    assert lab.commerce.journal.read()["trial_end"] == original["trial_end"]
    assert lab.provider.charge_count == 1 and lab.provider.checkout_count == 1


def runtime_adapter(lab):
    b = lab.binding
    key = derive_runtime_admission_key(
        lab.settings.runtime_admission_secret.get_secret_value(),
        b.practice_id,
        b.box_id,
        b.organization_id,
    )
    runtime = Settings(
        _env_file=None,
        cosmas_env="early_adopter_beta",
        data_mode="synthetic",
        auth_mode="clerk_jwt",  # pyright: ignore[reportCallIssue]
        workspace_enrollment_managed=True,
        workspace_enrollment_practice_id=b.practice_id,
        beta_box_id=b.box_id,
        clerk_issuer=b.issuer,
        clerk_organization_id=b.organization_id,
        clerk_session_policy="enrollment_default",
        clerk_audience="",
        workspace_enrollment_api_origin=b.api_origin,
        workspace_enrollment_origin_allowlist=b.api_origin + "," + b.app_origin,
        workspace_enrollment_admission_secret=SecretStr(key),
        workspace_enrollment_account_origin=b.app_origin,
    )

    def transport(request):
        response = Context().run(
            lab.client.post,
            request.url.path,
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=dict(response.headers)
        )

    return EnrollmentAdmissionAdapter(
        runtime, client=httpx.Client(transport=httpx.MockTransport(transport))
    ), key


@pytest.mark.parametrize("point", ["expiry", "after"])
def test_signed_registered_runtime_and_worker_admission_cutoff_keeps_wall_security_time(lab, point):
    start_trial(lab)
    adapter, key = runtime_adapter(lab)
    token = lab.token(
        {
            "org_id": lab.binding.organization_id,
            "azp": lab.binding.workspace_url.removesuffix("/chief"),
        }
    )
    lab.commerce.advance("before")
    assert adapter.authorize(token, lab.binding.owner_subject)["enforced"]
    assert adapter.authorize(
        "",
        lab.binding.owner_subject,
        purpose="worker",
        operation_id=str(uuid4()),
        approval_sha256="a" * 64,
    )["enforced"]
    stamp = int(time.time()) - 60
    request = AdmissionRequest(
        practice_id=lab.binding.practice_id,
        box_id=lab.binding.box_id,
        organization_id=lab.binding.organization_id,
        issuer=lab.binding.issuer,
        subject=lab.binding.owner_subject,
        purpose="workspace",
        nonce=str(uuid4()),
        issued_at=stamp,
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
    )
    raw = encode(request.model_dump())
    response = lab.client.post(
        "/enrollment/v1/runtime/admission",
        content=raw,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            ADMISSION_HEADER: signature(key, raw, direction="request", nonce=request.nonce),
        },
    )
    assert response.status_code == 401
    lab.commerce.advance(point)
    with pytest.raises(RuntimeAdmissionError):
        adapter.authorize(token, lab.binding.owner_subject)
    with pytest.raises(RuntimeAdmissionError):
        adapter.authorize(
            "",
            lab.binding.owner_subject,
            purpose="worker",
            operation_id=str(uuid4()),
            approval_sha256="a" * 64,
        )
    adapter.client.close()


def test_scope_guard_rejects_foreign_signed_runtime_before_clock_reads(lab):
    adapter, key = runtime_adapter(lab)
    request = AdmissionRequest(
        practice_id=str(uuid4()),
        box_id=lab.binding.box_id,
        organization_id="org_other",
        issuer=lab.binding.issuer,
        subject=lab.binding.owner_subject,
        purpose="workspace",
        nonce=str(uuid4()),
        issued_at=int(time.time()),
        token_sha256=hashlib.sha256(lab.token().encode()).hexdigest(),
    )
    raw = encode(request.model_dump())
    lab.provider.reads.clear()
    response = lab.client.post(
        "/enrollment/v1/runtime/admission",
        content=raw,
        headers={
            "Authorization": "Bearer " + lab.token(),
            "Content-Type": "application/json",
            ADMISSION_HEADER: signature(key, raw, direction="request", nonce=request.nonce),
        },
    )
    assert response.status_code == 503 and not lab.provider.reads
    adapter.client.close()


@pytest.fixture(scope="module")
def postgres_journal():
    """Always create this test's own loopback cluster; never use ambient DBs."""
    pg = Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
    with tempfile.TemporaryDirectory(
        prefix="private-clock-journal-pg-", dir="/private/tmp"
    ) as folder:
        work = Path(folder)
        password = "synthetic-private-clock-journal-only"
        (work / "password").write_text(password)
        (work / "password").chmod(0o600)
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        env = {**os.environ, "PGPASSWORD": password}

        def quiet(args):
            subprocess.run(
                args,
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
            )

        quiet(
            [
                str(pg / "initdb"),
                "-D",
                str(work / "data"),
                "-U",
                "clock_journal",
                "--pwfile",
                str(work / "password"),
                "--auth-local=trust",
                "--auth-host=scram-sha-256",
            ]
        )
        start = [
            str(pg / "pg_ctl"),
            "-D",
            str(work / "data"),
            "-l",
            str(work / "postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {port} -k {work}",
            "-w",
            "start",
        ]
        stop = [str(pg / "pg_ctl"), "-D", str(work / "data"), "-w", "stop", "-m", "fast"]
        quiet(start)
        engine = None
        try:
            quiet(
                [
                    str(pg / "createdb"),
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(port),
                    "-U",
                    "clock_journal",
                    "cosmabot_enrollment_clock_lab",
                ]
            )
            engine = create_engine(
                f"postgresql+psycopg://clock_journal:{password}@127.0.0.1:{port}/cosmabot_enrollment_clock_lab",
                hide_parameters=True,
                pool_pre_ping=True,
            )

            def restart():
                engine.dispose()
                quiet(stop)
                quiet(start)

            yield SimpleNamespace(engine=engine, restart=restart)
        finally:
            if engine is not None:
                engine.dispose()
            quiet(stop)


def test_postgres_journal_process_restart_and_pending_target_are_durable(lab, postgres_journal):
    journal = PostgresClockJournal(postgres_journal.engine, lab.binding)
    stamp = lab.binding.initial_frozen_time
    journal.subscription(
        {"id": "sub_durableexample", "trial_start": stamp, "trial_end": stamp + 14 * 86400}
    )
    target = journal.target("before")
    postgres_journal.restart()
    recovered = PostgresClockJournal(postgres_journal.engine, lab.binding)
    assert recovered.read()["pending_target"] == target
    with pytest.raises(EnrollmentError):
        recovered.observe(stamp)
    recovered.observe(target)
    assert recovered.read()["high_water"] == target and recovered.read()["pending_target"] is None
    with pytest.raises(EnrollmentError):
        recovered.subscription(
            {"id": "sub_other", "trial_start": stamp, "trial_end": stamp + 14 * 86400}
        )


def test_postgres_row_locks_prevent_cross_instance_rewind(lab, postgres_journal):
    first = PostgresClockJournal(postgres_journal.engine, lab.binding)
    second = PostgresClockJournal(postgres_journal.engine, lab.binding)
    stamp = lab.binding.initial_frozen_time

    def observe(pair):
        journal, target = pair
        try:
            journal.observe(target)
        except EnrollmentError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(observe, [(first, stamp + 10), (second, stamp + 20)]))
    assert (
        PostgresClockJournal(postgres_journal.engine, lab.binding).read()["high_water"]
        == stamp + 20
    )


def test_factory_uses_dedicated_postgres_journal_and_rejects_foreign_store(lab, postgres_journal):
    journal = PostgresClockJournal(postgres_journal.engine, lab.binding)
    app = lab.factory(journal=journal)
    assert app.state.private_clock_commerce.journal is journal
    foreign = create_engine(postgres_journal.engine.url.set(database="postgres"))
    try:
        with pytest.raises(EnrollmentError):
            PostgresClockJournal.prepare_database(foreign, lab.binding)
    finally:
        foreign.dispose()


def next_practice(lab):
    with lab.sessions() as session:
        return session.get(Practice, lab.binding.practice_id)


def test_registry_scope_changes_deny_before_provider_clock_reads(lab):
    lab.provider.reads.clear()
    with lab.sessions.begin() as session:
        session.get(Practice, lab.binding.practice_id).organization_id = "org_changed"
    response = lab.client.get("/enrollment/v1/status", headers=lab.headers)
    assert response.status_code == 503 and not lab.provider.reads
    assert lab.client.get("/health").status_code == 200
    assert lab.client.get("/operational-ready").status_code == 200
