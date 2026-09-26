"""Real signed HTTP and PostgreSQL sessions across a lost response and restart."""

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_portal_setup import activation, bound
from tests.integration.test_portal_setup import case as portal_case
from tests.integration.test_vendor_process import unused_port, wait_for

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import portal_setup_schemas as p
from cosmas_os.application import services
from cosmas_os.config import settings
from cosmas_os.models import ExternalIdentity
from cosmas_os.portal_models import PortalSetupReceipt


def test_signed_portal_commands_recover_exactly_after_process_loses_committed_response(
    engine, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setitem(settings.__dict__, "portal_setup_enabled", True)
    subject = "user_portal_" + uuid4().hex
    with Session(engine, expire_on_commit=False) as s:
        seeded = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented portal process practice",
        )
        c = cast(Any, portal_case).__wrapped__(s, seeded)
        s.add(
            ExternalIdentity(
                box_id=c["box"],
                principal_id=c["owner"],
                provider="clerk",
                issuer="https://clerk.example.invalid",
                subject=subject,
                organization_id="org_invented",
                reviewed_by="Invented reviewer",
                evidence_ref="local:portal-process",
            )
        )
        s.commit()
    chosen = next(iter(c["catalog"].installations.values())).selection
    config = {"port": unused_port(), "selection": chosen.model_dump(mode="json")}
    (tmp_path / "configuration.json").write_text(json.dumps(config))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (tmp_path / "public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parents[2]),
        "WORKSPACE_ENABLED": "true",
        "WORKSPACE_AUTHENTICATED_ENABLED": "true",
        "AUTH_MODE": "clerk_jwt",
        "SYNTH_SEED": "false",
        "CLERK_ISSUER": "https://clerk.example.invalid",
        "CLERK_JWKS_URL": "https://clerk.example.invalid/.well-known/jwks.json",
        "CLERK_AUDIENCE": "cosmas-workspace-local",
        "CLERK_ORGANIZATION_ID": "org_invented",
        "CLERK_AUTHORIZED_PARTIES": "http://localhost:5173",
        "CORS_ALLOWED_ORIGINS": "http://localhost:5173",
        "BETA_BOX_ID": c["box"],
        "WORKSPACE_ROUTINES_ENABLED": "false",
    }
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "iss": "https://clerk.example.invalid",
        "aud": "cosmas-workspace-local",
        "sid": "session_invented_portal",
        "azp": "http://localhost:5173",
        "org_id": "org_invented",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "invented-portal-process"})
    children = []
    logs = []
    origin = "http://127.0.0.1:" + str(config["port"])

    def start():
        log = (tmp_path / f"process-{len(children)}.log").open("xb")
        logs.append(log)
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).parents[1] / "helpers/portal_setup_process.py"),
                str(tmp_path),
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        children.append(child)

        def ready():
            assert child.poll() is None, (tmp_path, child.returncode)
            try:
                return (
                    httpx.get(origin + "/health", timeout=0.25, trust_env=False).status_code == 200
                )
            except httpx.HTTPError:
                return False

        wait_for(ready)
        return child

    try:
        first_process = start()
        with httpx.Client(
            base_url=origin,
            timeout=10,
            trust_env=False,
            headers={"Authorization": "Bearer " + token, "X-Cosmas-Portal-Contract": "1"},
        ) as client:
            assert client.get("/portal-setup").status_code == 200
            bad = jwt.encode(
                {**claims, "iss": "https://wrong.example.invalid"},
                key,
                algorithm="RS256",
                headers={"kid": "invented-portal-process"},
            )
            assert (
                client.get("/portal-setup", headers={"Authorization": "Bearer " + bad}).status_code
                == 401
            )
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(
                    pool.map(
                        lambda _: client.post("/portal-setup/propose", json=c["request"].public()),
                        range(2),
                    )
                )
            assert all(r.status_code == 200 for r in replies), [r.text for r in replies]
            assert replies[0].json() == replies[1].json()
            proposed = replies[0].json()
            d = client.get("/portal-setup/" + c["request"].connection_id).json()
            fixture = {
                "proposal": c["request"].public(),
                "proposal_receipt": proposed,
                "detail_pending": d,
                "catalog_pending": client.get("/portal-setup").json(),
            }
            request = activation(d)
            raw = json.dumps(request.public(), separators=(",", ":")).encode()
            (tmp_path / "fault.json").write_text(
                json.dumps(
                    {
                        "path": "/portal-setup/activate",
                        "body_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )
            )
            try:
                client.post(
                    "/portal-setup/activate",
                    content=raw,
                    headers={"Content-Type": "application/json"},
                )
            except httpx.HTTPError:
                pass
            else:
                raise AssertionError("Exact committed-response fault did not fire")
            wait_for(lambda: first_process.poll() == 77)
            with Session(engine) as s:
                assert (
                    s.scalar(
                        select(func.count())
                        .select_from(PortalSetupReceipt)
                        .where(PortalSetupReceipt.connection_id == request.connection_id)
                    )
                    == 2
                )
            start()
            resolve = {
                "command_kind": "activate",
                "idempotency_key": request.idempotency_key,
                "request_sha256": __import__(
                    "cosmas_os.application.portal_setup", fromlist=["request_digest"]
                ).request_digest(c["box"], c["owner"], "activate", request),
            }
            recovered = client.post("/portal-setup/resolve", json=resolve)
            assert recovered.status_code == 200 and recovered.json()["effect"]["state"] == "active"
            assert (
                client.post("/portal-setup/activate", json=request.public()).json()
                == recovered.json()
            )
            d = client.get("/portal-setup/" + request.connection_id).json()
            assert d["usable_locally"]
            fixture.update(
                activation=request.public(), activation_receipt=recovered.json(), detail_active=d
            )
            for kind, model, flag in [
                ("disable", p.Disable, "confirm_disable"),
                ("revoke", p.Revoke, "confirm_revoke"),
            ]:
                response = client.post(
                    "/portal-setup/" + kind, json=model(**bound(d), **{flag: True}).public()
                )
                assert response.status_code == 200, response.text
                d = client.get("/portal-setup/" + request.connection_id).json()
            assert d["state"] == "revoked" and not d["usable_locally"]
            assert client.post("/portal-setup/resolve", json=resolve).json() == recovered.json()
            history = client.get("/portal-setup/" + request.connection_id + "/history").json()
            assert [r["effect"]["version"] for r in history["receipts"]] == [1, 2, 3, 4]
            assert client.get("/health").json()["portal_calls"] == 0
            fixture["history"] = history
            (tmp_path / "public-http-fixture.json").write_text(json.dumps(fixture, indent=2) + "\n")
    finally:
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
