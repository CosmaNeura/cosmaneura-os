"""Signed OS + PostgreSQL + independent socket receiver; synthetic service evidence."""

import hmac
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
from tests.integration.test_finance_work import bound, finance_case, proposal
from tests.integration.test_vendor_work import vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.adapters.vendor_connectors.transport import STRIPE_VERSION
from cosmas_os.application import services
from cosmas_os.config import settings
from cosmas_os.finance_models import FinanceEventCandidate, FinanceSubmitClaim
from cosmas_os.models import ExternalIdentity


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
def processes(engine, tmp_path, monkeypatch):
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
    harness = Path(__file__).parents[1] / "helpers/finance_process_server.py"

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

    client = None
    try:
        receiver = start("receiver")
        app = start("os")
        client = httpx.Client(
            base_url="http://127.0.0.1:" + str(config["os_port"]),
            timeout=15,
            trust_env=False,
            headers={"Authorization": "Bearer " + token(), "X-Cosmas-Finance-Contract": "1"},
        )
        yield {
            "case": c,
            "client": client,
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


def prepare(case):
    http, c = case["client"], case["case"]
    url = f"/workspaces/{c['wid']}/finance-work"
    created = http.post(url, json=proposal(c).public())
    assert created.status_code == 200, created.text
    tid = created.json()["effect"]["ticket_id"]
    url += "/" + tid
    d = http.get(url).json()
    approved = http.post(
        url + "/decide", json=bound(d, review_sha256=d["review_sha256"], choice="approve")
    )
    assert approved.status_code == 200, approved.text
    assert lines(case["root"] / "receiver.jsonl") == []
    assert lines(case["root"] / "credentials.jsonl") == []
    return url, http.get(url).json()


def test_signed_stripe_socket_once_read_candidate_and_exact_financial_verification(
    processes, engine
):
    case = processes
    http = case["client"]
    url, detail = prepare(case)
    request = bound(detail)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: http.post(url + "/submit", json=request), range(2)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert results[0].json()["effect"] == results[1].json()["effect"]
    sent = lines(case["root"] / "receiver.jsonl")
    assert len(sent) == 1 and sent[0]["method"] == "POST" and sent[0]["invented_auth_matches"]
    assert sent[0]["path"] == "/v1/payment_intents" and sent[0]["version"] == STRIPE_VERSION
    operation = detail["summary"]["operation_id"]
    assert sent[0]["operation"] == operation
    assert sent[0]["body"] == {
        "amount": ["12500"],
        "currency": ["usd"],
        "customer": ["cus_Invented"],
        "confirm": ["false"],
        "payment_method_types[]": ["card"],
        "metadata[cosmas_operation_id]": [operation],
    }
    current = http.get(url).json()
    assert current["summary"]["creation"] == "accepted"
    assert (
        current["summary"]["payment_state"] == "not_observed"
        and current["summary"]["state"] == "approved"
    )
    assert http.post(url + "/submit", json=bound(current)).status_code == 409
    raw = json.dumps(
        {
            "id": "evt_Invented",
            "object": "event",
            "type": "payment_intent.succeeded",
            "api_version": STRIPE_VERSION,
            "livemode": False,
            "data": {
                "object": {
                    "object": "payment_intent",
                    "id": "pi_" + operation.replace("-", ""),
                    "livemode": False,
                    "client_secret": "never-expose-this-secret",
                }
            },
        }
    ).encode()
    timestamp = str(int(time.time()))
    signature = hmac.digest(
        b"invented-process-webhook", timestamp.encode() + b"." + raw, "sha256"
    ).hex()
    event_url = (
        str(http.base_url).rstrip("/") + "/finance-events/stripe/" + case["config"]["event_route"]
    )
    signed = {"Stripe-Signature": "t=" + timestamp + ",v1=" + signature}
    for _ in range(2):
        callback = httpx.post(event_url, content=raw, headers=signed, trust_env=False)
        assert callback.status_code == 200, callback.text
    assert http.get(url).json()["summary"] == current["summary"]
    assert len(lines(case["root"] / "receiver.jsonl")) == 1
    with Session(engine) as s:
        candidates = list(
            s.scalars(
                select(FinanceEventCandidate).where(
                    FinanceEventCandidate.connection_version_id == case["config"]["connection_id"]
                )
            )
        )
        assert len(candidates) == 1 and set(candidates[0].correlation) == {
            "event_type",
            "event_id",
            "object_id",
        }
    assert (
        httpx.post(event_url, content=raw + b" ", headers=signed, trust_env=False).status_code
        == 400
    )
    observed = http.post(url + "/reconcile", json=bound(current))
    assert observed.status_code == 200, observed.text
    current = http.get(url).json()
    assert (
        current["summary"]["payment_state"] == "succeeded"
        and current["summary"]["state"] == "approved"
    )
    result = http.post(
        url + "/result",
        json=bound(
            current,
            observation_head=current["summary"]["observation_head"],
            evidence_sha256=current["summary"]["evidence_sha256"],
            disposition="reported_paid",
            evidence="Invented financial reviewer matched the complete payment.",
        ),
    )
    assert result.status_code == 200, result.text
    current = http.get(url).json()
    verified = http.post(
        url + "/verify",
        json=bound(
            current,
            result_receipt_id=result.json()["effect"]["receipt_id"],
            result_receipt_sha256=result.json()["receipt_sha256"],
            observation_head=current["summary"]["observation_head"],
            evidence_sha256=current["summary"]["evidence_sha256"],
            reviewed_result=True,
            reviewed_observations=True,
            outcome_confirmed=True,
            reviewed_conflicting_evidence=False,
        ),
    )
    assert verified.status_code == 200, verified.text
    final = http.get(url)
    assert final.json()["summary"]["verification"] == "verified"
    assert all(
        value not in final.text
        for value in ["cus_Invented", "never-expose-this-secret", "sk_test", "pi_"]
    )
    assert [r["method"] for r in lines(case["root"] / "receiver.jsonl")] == ["POST", "GET"]
    invalid = http.get(
        url, headers={"Authorization": "Bearer " + case["token"](org_id="wrong_org")}
    )
    assert invalid.status_code == 403
    (case["root"] / "actual-finance-process-fixtures.json").write_text(
        json.dumps(
            {
                "submitted_detail": detail,
                "paid_detail": current,
                "verified_detail": final.json(),
                "result_receipt": result.json(),
                "verify_receipt": verified.json(),
            },
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize("checkpoint", ["credentials", "response"])
def test_process_loss_preserves_one_forever_claim_and_never_resends(processes, engine, checkpoint):
    case = processes
    http = case["client"]
    url, detail = prepare(case)
    request = bound(detail)
    hold = case["root"] / ("hold-credentials" if checkpoint == "credentials" else "hold-response")
    hold.touch()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(http.post, url + "/submit", json=request)
        evidence = case["root"] / (
            "credentials.jsonl" if checkpoint == "credentials" else "receiver.jsonl"
        )
        wait_for(lambda: len(lines(evidence)) == 1)
        case["app"].kill()
        case["app"].wait(timeout=3)
        with pytest.raises(httpx.HTTPError):
            pending.result(timeout=3)
    hold.unlink()
    case["start"]("os")
    replay = http.post(url + "/submit", json=request)
    assert replay.status_code == 200 and replay.json()["effect"]["effect"] == "submit_claimed"
    current = http.get(url).json()
    assert current["summary"]["submit_claimed"] and current["summary"]["state"] == "approved"
    assert http.post(url + "/submit", json=bound(current)).status_code == 409
    assert len(lines(case["root"] / "receiver.jsonl")) == (0 if checkpoint == "credentials" else 1)
    assert len(lines(case["root"] / "credentials.jsonl")) == 1
    with Session(engine) as s:
        claim = s.scalar(
            select(FinanceSubmitClaim).where(
                FinanceSubmitClaim.operation_id == detail["summary"]["operation_id"]
            )
        )
        assert (
            claim is not None
            and claim.completed_at is None
            and claim.dispatch == "invocation_started"
        )
