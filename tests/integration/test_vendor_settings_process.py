"""Signed OS + PostgreSQL + independent socket receiver; synthetic service evidence."""

import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import Session
from tests.integration.test_vendor_work import bound, vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.application import services
from cosmas_os.config import settings
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
def setup_processes(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    subject = "user_w36" + uuid4().hex
    with Session(engine, expire_on_commit=False) as s:
        seeded = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented W36 process practice",
        )
        make = getattr(vendor_case, "__wrapped__", None)
        assert callable(make)
        c = make(s, seeded)
        assert isinstance(c, dict)
        from tests.integration.test_vendor_settings import setup_case

        make_setup = getattr(setup_case, "__wrapped__", None)
        assert callable(make_setup)
        c = make_setup(c)
        assert isinstance(c, dict)
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
        "connection_id": c["config"].id,
        "event_route": c["config"].routing["event_route_id"],
    }
    installed = next(
        item for item in c["installed"].installations.values() if item.selection.vendor == "spruce"
    )
    config["installation"] = {
        "selection": installed.selection.model_dump(mode="json"),
        "label": installed.label,
        "sender_label": installed.sender_label,
        "routing": dict(installed.routing),
        "capabilities": list(installed.capabilities),
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
    harness = Path(__file__).parents[1] / "helpers/vendor_settings_process.py"

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
            headers={"Authorization": "Bearer " + token(), "X-Cosmas-Vendor-Contract": "1"},
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


def test_signed_activation_recovers_after_death_and_installed_authority_precedes_secrets(
    setup_processes,
):
    from tests.integration.test_vendor_settings import account_request, binding, recipient_request

    from cosmas_os.api import vendor_setup_schemas as p

    f = setup_processes
    c = f["case"]
    vendor = f["client"]
    origin = str(vendor.base_url)
    headers = {"Authorization": "Bearer " + f["token"](), "X-Cosmas-Vendor-Setup-Contract": "1"}
    with httpx.Client(base_url=origin, headers=headers, trust_env=False, timeout=10) as client:
        req = account_request(c)
        first = client.post("/vendor-settings/propose_account", json=req.public())
        assert first.status_code == 200, first.text
        proposed = first.json()
        activation = p.Activation(
            **binding(proposed),
            idempotency_key="lost-activation-" + str(uuid4()),
            reviewed_account=True,
            reviewed_environment=True,
            reviewed_sender=True,
            reviewed_capabilities=True,
            confirm_local_activation=True,
        )
        with pytest.raises(httpx.HTTPError):
            client.post("/vendor-settings/activate", json=activation.public())
        wait_for(lambda: f["app"].poll() is not None)
        assert f["app"].returncode == 87
        f["start"]("os")
        scope = {"box_id": c["box"], "owner_id": c["actor"]}
        recovered = client.post(
            "/vendor-settings/resolve",
            json={
                "command_kind": "activate",
                "idempotency_key": activation.idempotency_key,
                "request_sha256": p.request_digest(scope, "activate", activation),
            },
        ).json()
        assert recovered["effect"]["state"] == "active"
        assert (
            client.post("/vendor-settings/activate", json=activation.public()).json() == recovered
        )
        recipient = recipient_request(c, recovered)
        pending = client.post("/vendor-settings/propose_recipient", json=recipient.public())
        assert pending.status_code == 200, pending.text
        approval = p.Activation(
            **binding(pending.json()),
            idempotency_key="recipient-activation-" + str(uuid4()),
            reviewed_account=True,
            reviewed_environment=True,
            reviewed_sender=True,
            reviewed_capabilities=True,
            reviewed_patient=True,
            reviewed_recipient=True,
            reviewed_permission=True,
            confirm_local_activation=True,
        )
        accepted = client.post("/vendor-settings/activate", json=approval.public())
        assert accepted.status_code == 200, accepted.text
        account_detail = client.get("/vendor-settings/" + recovered["effect"]["setup_id"]).json()
        recipient_detail = client.get(
            "/vendor-settings/" + accepted.json()["effect"]["setup_id"]
        ).json()
        root = f"/workspaces/{c['wid']}/vendor-work"
        options = vendor.get(root + "/options").json()
        connection = next(
            row
            for row in options["connections"]
            if row["id"] == account_detail["review"]["connection_version_id"]
        )
        correspondence = next(
            row
            for row in options["correspondences"]
            if row["id"] == recipient_detail["review"]["correspondence_version_id"]
        )
        request = {
            "expected_workspace_revision": 3,
            "proposed_operation_id": str(uuid4()),
            "idempotency_key": "managed-delivery-" + str(uuid4()),
            "action": "spruce_secure_message",
            "connection": {k: connection[k] for k in ("id", "revision", "public_sha256")},
            "correspondence": {k: correspondence[k] for k in ("id", "revision", "public_sha256")},
            "source": c["source"],
            "due_date": "2026-10-01",
            "expected_outcome": "Invented reviewed message receipt",
            "share_to_practice": False,
            "message": "Invented managed message",
        }

        def prepare(body):
            posted = vendor.post(root, json=body)
            assert posted.status_code == 200, posted.text
            path = root + "/" + posted.json()["effect"]["ticket_id"]
            d = vendor.get(path).json()
            review = vendor.post(
                path + "/decide", json=bound(d, review_sha256=d["review_sha256"], choice="approve")
            )
            assert review.status_code == 200, review.text
            return path, vendor.get(path).json()

        path, d = prepare(request)
        assert (
            lines(f["root"] / "credentials.jsonl") == []
            and lines(f["root"] / "receiver.jsonl") == []
        )
        submitted = vendor.post(path + "/submit", json=bound(d))
        assert submitted.status_code == 200, submitted.text
        assert (
            len(lines(f["root"] / "credentials.jsonl")) == 1
            and len(lines(f["root"] / "receiver.jsonl")) == 1
        )
        # A newly approved request still cannot resolve a secret after the exact
        # installed descriptor disappears. The integrated route rejects before
        # spending its once-ever claim; the recorded earlier send stays immutable.
        second = {
            **request,
            "proposed_operation_id": str(uuid4()),
            "idempotency_key": "managed-denied-" + str(uuid4()),
        }
        denied_path, d = prepare(second)
        (f["root"] / "installation-unavailable").write_text("Intentional local registry loss")
        denied = vendor.post(denied_path + "/submit", json=bound(d))
        assert denied.status_code == 409, denied.text
        assert denied.json()["error"]["code"] == "vendor_selection_changed"
        assert (
            len(lines(f["root"] / "credentials.jsonl")) == 1
            and len(lines(f["root"] / "receiver.jsonl")) == 1
        )
        final = vendor.get(denied_path).json()
        assert final["summary"]["submit_claimed"] is False
        assert final["availability"]["submit"] == {
            "allowed": False, "reason": "selection_changed"
        }
        disabled_options = vendor.get(root + "/options").json()
        assert next(
            item for item in disabled_options["connections"] if item["id"] == connection["id"]
        )["availability"] == "disabled"
        unavailable = client.get("/vendor-settings/" + recovered["effect"]["setup_id"]).json()
        assert unavailable["summary"]["usable_locally"] is False
        (f["root"] / "actual-vendor-settings-process.json").write_text(
            json.dumps(
                {
                    "account_request": req.public(),
                    "proposal_receipt": proposed,
                    "activation_request": activation.public(),
                    "activation_receipt": recovered,
                    "recipient_request": recipient.public(),
                    "recipient_proposal_receipt": pending.json(),
                    "recipient_activation_request": approval.public(),
                    "recipient_activation_receipt": accepted.json(),
                    "account_detail": account_detail,
                    "recipient_detail": recipient_detail,
                    "history": client.get(
                        "/vendor-settings/" + accepted.json()["effect"]["setup_id"] + "/history"
                    ).json(),
                    "delivery_receipt": submitted.json(),
                    "missing_installation_delivery": final,
                    "missing_installation_account": unavailable,
                    "missing_installation_options": disabled_options,
                    "missing_installation_rejection": denied.json(),
                },
                indent=2,
            )
        )
