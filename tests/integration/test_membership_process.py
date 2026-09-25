"""Actual signed HTTP recovery after two API process deaths; no service connection."""

import json
import os
import subprocess
import sys
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
from tests.integration.test_membership_work import bound, proposal
from tests.integration.test_vendor_process import unused_port, wait_for
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import membership_work_schemas as p
from cosmas_os.application import services
from cosmas_os.models import ExternalIdentity, Operation


def test_signed_membership_proposal_and_completion_survive_lost_responses(engine, tmp_path):
    subject = "user_membership_" + uuid4().hex
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented membership restart practice",
        )
        factory = getattr(vendor_case, "__wrapped__", None)
        assert callable(factory)
        c = factory(s, seed)
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
                evidence_ref="local:membership-process",
            )
        )
        request = proposal(s, c)
        s.commit()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (tmp_path / "public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    port, children, logs = unused_port(), [], []
    config = tmp_path / "configuration.json"
    env = {
        **os.environ,
        "WORKSPACE_ENABLED": "true",
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
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": subject,
            "iss": "https://clerk.example.invalid",
            "aud": "cosmas-workspace-local",
            "sid": "session_invented_membership",
            "azp": "http://localhost:5173",
            "org_id": "org_invented",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
        },
        key,
        algorithm="RS256",
        headers={"kid": "invented-membership-key"},
    )
    origin = "http://127.0.0.1:" + str(port)

    def start(loss=None):
        config.write_text(json.dumps({"port": port, "lose_kind": loss}))
        log = (tmp_path / ("process-" + str(len(children)) + ".log")).open("xb")
        logs.append(log)
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).parents[1] / "helpers/membership_process.py"),
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
        first = start("propose")
        with httpx.Client(
            base_url=origin,
            timeout=10,
            trust_env=False,
            headers={"Authorization": "Bearer " + token, "X-Cosmas-Membership-Contract": "1"},
        ) as client:
            root = f"/workspaces/{c['wid']}/membership-work"
            assert client.get(root + "/options").status_code == 200
            with pytest.raises(httpx.HTTPError):
                client.post(root, json=request.public())
            wait_for(lambda: first.poll() is not None)
            assert first.returncode == 87
            second = start("verify")
            scope = {"box_id": c["box"], "owner_id": c["actor"], "workspace_id": c["wid"]}
            resolve = {
                "command_kind": "propose",
                "idempotency_key": request.idempotency_key,
                "request_sha256": p.request_digest("propose", scope, request),
            }
            receipt = client.post(root + "/resolve", json=resolve).json()
            assert receipt["outcome"] == "recorded"
            assert client.post(root, json=request.public()).json() == receipt
            tid = receipt["effect"]["ticket_id"]
            path = root + "/" + tid
            d = client.get(path).json()
            decision = p.Decision(
                **bound(d),
                review_sha256=d["review_sha256"],
                choice="approve",
                reviewed_patient=True,
                reviewed_local_only_authority=True,
            )
            assert client.post(path + "/decide", json=decision.public()).status_code == 200
            d = client.get(path).json()
            result = p.Result(
                **bound(d),
                disposition="local_preparation_ready",
                evidence="Invented local information checked; no enrollment or payment established.",
            )
            assert client.post(path + "/result", json=result.public()).status_code == 200
            d = client.get(path).json()
            verify = p.Verify(
                **bound(d),
                result_receipt_id=d["latest_result"]["receipt_id"],
                result_receipt_sha256=d["latest_result"]["receipt_sha256"],
                evidence_classification="local_unreconciled",
                reviewed_patient=True,
                reviewed_result=True,
                reviewed_evidence_limits=True,
                confirm_review_completion=True,
            )
            with pytest.raises(httpx.HTTPError):
                client.post(path + "/verify", json=verify.public())
            wait_for(lambda: second.poll() is not None)
            assert second.returncode == 87
            start()
            resolved = client.post(
                root + "/resolve",
                json={
                    "command_kind": "verify",
                    "idempotency_key": verify.idempotency_key,
                    "request_sha256": p.request_digest("verify", scope, verify),
                },
            ).json()
            assert resolved["effect"]["effect"] == "review_verified"
            assert client.post(path + "/verify", json=verify.public()).json() == resolved
            d = client.get(path).json()
            assert (
                d["summary"]["state"] == "closed"
                and d["summary"]["external_service_verified"] is False
            )
            history = client.get(path + "/history").json()
            assert len(history["items"]) == 4
            with Session(engine) as s:
                assert s.scalar(select(Operation.id).where(Operation.ticket_id == tid)) is None
            (tmp_path / "actual-membership-process.json").write_text(
                json.dumps(
                    {
                        "proposal_request": request.public(),
                        "proposal_receipt": receipt,
                        "verify_request": verify.public(),
                        "verify_receipt": resolved,
                        "detail": d,
                        "history": history,
                    },
                    indent=2,
                )
            )
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
        for log in logs:
            log.close()
