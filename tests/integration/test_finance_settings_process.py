"""Signed OS + PostgreSQL + independent socket receiver; synthetic service evidence."""

import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration.test_finance_settings import (
    activation,
    customer_request,
)
from tests.integration.test_finance_settings import (
    bound as setup_bound,
)
from tests.integration.test_finance_work import bound, finance_case, proposal
from tests.integration.test_vendor_work import vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import finance_setup_schemas as schema
from cosmas_os.application import services
from cosmas_os.config import settings
from cosmas_os.finance_setup_models import FinanceSetupReceipt, FinanceSetupRevision
from cosmas_os.models import EncounterWorkspace, ExternalIdentity


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.025)
    raise AssertionError("Owned process did not reach the expected checkpoint")


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def settings_processes(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    subject = "user_w36" + uuid4().hex
    with Session(engine, expire_on_commit=False) as s:
        seeded = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented W36 process practice",
        )
        c = finance_case.__wrapped__(s, vendor_case.__wrapped__(s, seeded))
        s.add(
            ExternalIdentity(
                box_id=c["box"],
                principal_id=c["actor"],
                provider="clerk",
                issuer="https://clerk.example.invalid",
                subject=subject,
                organization_id="org_invented",
                reviewed_by="Invented reviewer",
                evidence_ref="local:w36-process",
            )
        )
        c["patient_id"] = s.get(EncounterWorkspace, c["wid"]).patient_link_id
        s.commit()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (tmp_path / "public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    config = {
        "root": str(tmp_path),
        "os_port": unused_port(),
        "receiver_port": unused_port(),
        "connection_id": c["finance_connection"]["id"],
        "event_route": str(uuid4()),
        "installation": c["private_selection"].model_dump(mode="json"),
    }
    config["receiver_origin"] = "http://127.0.0.1:" + str(config["receiver_port"])
    path = tmp_path / "configuration.json"
    path.write_text(json.dumps(config))
    env = {
        **os.environ,
        "WORKSPACE_ENABLED": "true",
        "VENDOR_WORK_ENABLED": "true",
        "VENDOR_IO_ENABLED": "true",
        "VENDOR_EVENTS_ENABLED": "true",
        "WORKSPACE_AUTHENTICATED_ENABLED": "true",
        "AUTH_MODE": "clerk_jwt",
        "SYNTH_SEED": "false",
        "WORKSPACE_ROUTINES_ENABLED": "false",
        "CLERK_ISSUER": "https://clerk.example.invalid",
        "CLERK_JWKS_URL": "https://clerk.example.invalid/.well-known/jwks.json",
        "CLERK_AUDIENCE": "cosmas-workspace-local",
        "CLERK_ORGANIZATION_ID": "org_invented",
        "CLERK_AUTHORIZED_PARTIES": "http://localhost:5173",
        "CORS_ALLOWED_ORIGINS": "http://localhost:5173",
        "BETA_BOX_ID": c["box"],
    }
    children, logs = [], []
    harness = Path(__file__).parents[1] / "helpers/finance_settings_process_server.py"

    def start(role):
        log = (tmp_path / f"{role}-{len(children)}.log").open("xb")
        child = subprocess.Popen(
            [sys.executable, str(harness), role, str(path)], env=env, stdout=log, stderr=log
        )
        children.append(child)
        logs.append(log)
        origin = "http://127.0.0.1:" + str(config["os_port" if role == "os" else "receiver_port"])

        def healthy():
            assert child.poll() is None, (tmp_path, role, child.returncode)
            try:
                return (
                    httpx.get(origin + "/health", timeout=0.25, trust_env=False).status_code == 200
                )
            except httpx.HTTPError:
                return False

        wait_for(healthy)
        return child

    def token(**extra):
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": subject,
                "iss": "https://clerk.example.invalid",
                "aud": "cosmas-workspace-local",
                "sid": "session_w36process",
                "azp": "http://localhost:5173",
                "org_id": "org_invented",
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(minutes=5),
                **extra,
            },
            key,
            algorithm="RS256",
            headers={"kid": "invented-process-key"},
        )

    client = payment_client = None
    try:
        receiver = start("receiver")
        app = start("os")
        client = httpx.Client(
            base_url="http://127.0.0.1:" + str(config["os_port"]),
            timeout=15,
            trust_env=False,
            headers={
                "Authorization": "Bearer " + token(),
                "X-Cosmas-Finance-Setup-Contract": "1",
            },
        )
        payment_client = httpx.Client(
            base_url=client.base_url,
            timeout=15,
            trust_env=False,
            headers={"Authorization": "Bearer " + token(), "X-Cosmas-Finance-Contract": "1"},
        )
        yield {
            "case": c,
            "client": client,
            "payment_client": payment_client,
            "root": tmp_path,
            "app": app,
            "receiver": receiver,
            "start": start,
            "config": config,
            "token": token,
        }
    finally:
        if client is not None:
            client.close()
        if payment_client is not None:
            payment_client.close()
        for child in children:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
        for log in logs:
            log.close()


def account_request(case):
    r = case["client"].get("/finance-setup")
    assert r.status_code == 200, r.text
    p = r.json()["installed_accounts"][0]
    return schema.AccountProposal(
        setup_id=str(uuid4()),
        expected_version=0,
        idempotency_key="process-settings-" + str(uuid4()),
        installation_id=p["installation_id"],
        installation_sha256=p["installation_sha256"],
        label="Invented process account",
        permissions=schema.Permissions(read_status=True, create_unconfirmed_intents=True),
    )


def post(case, kind, request):
    r = case["client"].post("/finance-setup/" + kind, json=request.public())
    assert r.status_code == 200, r.text
    return r.json()


def detail(case, sid):
    r = case["client"].get("/finance-setup/" + sid)
    assert r.status_code == 200, r.text
    return r.json()


def ready(case, activate_customer=True):
    request = account_request(case)
    post(case, "propose_account", request)
    post(case, "activate", activation(detail(case, request.setup_id)))
    a = detail(case, request.setup_id)
    request = customer_request(case["case"], a, customer_id="cus_Invented")
    post(case, "propose_customer", request)
    if activate_customer:
        post(case, "activate", activation(detail(case, request.setup_id)))
    return a, detail(case, request.setup_id)


@pytest.mark.parametrize("stage", ["account_proposal", "customer_activation"])
def test_actual_signed_settings_response_loss_and_restart_recover_exact_admission(
    settings_processes, engine, stage
):
    case = settings_processes
    if stage == "account_proposal":
        kind, request = "propose_account", account_request(case)
    else:
        _, d = ready(case, activate_customer=False)
        kind, request = "activate", activation(d)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            case["client"].post,
            "/finance-setup/" + kind,
            json=request.public(),
            headers={"X-Invented-Drop-Reply": "1"},
        )
        wait_for(lambda: len(lines(case["root"] / "committed-settings.jsonl")) == 1)
        case["app"].kill()
        case["app"].wait(timeout=3)
        with pytest.raises(httpx.HTTPError):
            pending.result(timeout=3)
    case["start"]("os")
    digest = schema.request_digest(
        {"box_id": case["case"]["box"], "owner_id": case["case"]["actor"]}, kind, request
    )
    recovered = case["client"].post(
        "/finance-setup/resolve",
        json={
            "command_kind": kind,
            "idempotency_key": request.idempotency_key,
            "request_sha256": digest,
        },
    )
    assert recovered.status_code == 200 and recovered.json()["outcome"] == "recorded", (
        recovered.text
    )
    assert post(case, kind, request) == recovered.json()
    current = detail(case, request.setup_id)
    assert current["summary"]["state"] == (
        "pending_review" if stage == "account_proposal" else "active"
    )
    assert lines(case["root"] / "receiver.jsonl") == []
    assert lines(case["root"] / "credentials.jsonl") == []
    with Session(engine) as s:
        rows = list(
            s.scalars(
                select(FinanceSetupReceipt).where(
                    FinanceSetupReceipt.owner_id == case["case"]["actor"],
                    FinanceSetupReceipt.idempotency_key == request.idempotency_key,
                )
            )
        )
        assert len(rows) == 1
        revisions = list(
            s.scalars(
                select(FinanceSetupRevision).where(
                    FinanceSetupRevision.setup_id == request.setup_id
                )
            )
        )
        assert len(revisions) == 1
    (case["root"] / "actual-settings-process-recovery.json").write_text(
        json.dumps(
            {
                "stage": stage,
                "request": request.public(),
                "receipt": recovered.json(),
                "detail": current,
            },
            indent=2,
        )
        + "\n"
    )


def test_actual_settings_activation_feeds_one_payment_creation_and_disable_blocks_next(
    settings_processes,
):
    case = settings_processes
    http, c = case["payment_client"], case["case"]
    a, m = ready(case)
    url = f"/workspaces/{c['wid']}/finance-work"
    options = http.get(url + "/options").json()
    connection = next(
        row for row in options["connections"] if row["id"] == a["review"]["connection_version_id"]
    )
    customer = next(
        row for row in options["customers"] if row["id"] == m["review"]["customer_version_id"]
    )

    def approved():
        request = proposal(
            c,
            connection={key: connection[key] for key in ("id", "revision", "public_sha256")},
            customer={key: customer[key] for key in ("id", "revision", "public_sha256")},
        )
        response = http.post(url, json=request.public())
        assert response.status_code == 200, response.text
        task = url + "/" + response.json()["effect"]["ticket_id"]
        d = http.get(task).json()
        decision = http.post(
            task + "/decide", json=bound(d, review_sha256=d["review_sha256"], choice="approve")
        )
        assert decision.status_code == 200, decision.text
        return task, http.get(task).json()

    task, d = approved()
    response = http.post(task + "/submit", json=bound(d))
    assert response.status_code == 200, response.text
    sent = http.get(task).json()
    assert (
        sent["summary"]["creation"] == "accepted"
        and sent["summary"]["payment_state"] == "not_observed"
    )
    assert len(lines(case["root"] / "receiver.jsonl")) == 1
    assert len(lines(case["root"] / "credentials.jsonl")) == 1
    blocked, before = approved()
    post(case, "disable", schema.Disable(**setup_bound(m), confirm_disable=True))
    denied = http.post(blocked + "/submit", json=bound(before))
    assert (
        denied.status_code == 409 and denied.json()["error"]["code"] == "finance_selection_changed"
    ), denied.text
    assert len(lines(case["root"] / "receiver.jsonl")) == 1
    assert len(lines(case["root"] / "credentials.jsonl")) == 1
    (case["root"] / "actual-settings-payment-process.json").write_text(
        json.dumps(
            {
                "account": a,
                "customer": m,
                "created": sent,
                "disabled": detail(case, m["summary"]["setup_id"]),
                "next_payment_denied": denied.json(),
                "effects": lines(case["root"] / "receiver.jsonl"),
            },
            indent=2,
        )
        + "\n"
    )
