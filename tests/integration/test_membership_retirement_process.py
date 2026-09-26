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
from tests.integration.test_membership_retirement import advance_note
from tests.integration.test_membership_work import proposal
from tests.integration.test_vendor_process import unused_port, wait_for
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import membership_work_schemas as p
from cosmas_os.application import services
from cosmas_os.membership_models import MembershipCommandRetirement, MembershipReceipt
from cosmas_os.models import ExternalIdentity, Operation


def test_signed_retirement_loss_and_actual_renderer_recovery(engine, tmp_path):
    if not os.environ.get("MEMBERSHIP_RETIREMENT_RENDERER"):
        pytest.skip("Configure the frozen owned real-renderer harness for this signed process test")
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
        advance_note(s, c, request)
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
            "exp": now + timedelta(minutes=10),
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
        first = start("retire")
        with httpx.Client(
            base_url=origin,
            timeout=10,
            trust_env=False,
            headers={"Authorization": "Bearer " + token, "X-Cosmas-Membership-Contract": "1"},
        ) as client:
            root = f"/workspaces/{c['wid']}/membership-work"
            scope = {"box_id": c["box"], "owner_id": c["actor"], "workspace_id": c["wid"]}
            rejected = client.post(root, json=request.public())
            assert (
                rejected.status_code == 409
                and rejected.json()["error"]["code"] == "membership_source_changed"
            )
            query = {
                "command_kind": "propose",
                "idempotency_key": request.idempotency_key,
                "request_sha256": p.request_digest("propose", scope, request),
            }
            missing = client.post(root + "/resolve", json=query).json()
            assert missing["outcome"] == "not_found"
            renderer = Path(os.environ["MEMBERSHIP_RETIREMENT_RENDERER"])
            configuration = tmp_path / "renderer-input.json"
            configuration.write_text(
                json.dumps(
                    {
                        "origin": origin,
                        "scope": scope,
                        "token": token,
                        "original": request.public(),
                        "missing": missing,
                        "journal": str(tmp_path / "renderer-journal.json"),
                    }
                )
            )

            def run_renderer(stage):
                with (tmp_path / ("renderer-" + stage + ".log")).open("xb") as log:
                    completed = subprocess.run(
                        [
                            "/opt/homebrew/bin/pnpm",
                            "exec",
                            "vitest",
                            "run",
                            "src/live-membership-retirement.test.tsx",
                        ],
                        cwd=renderer,
                        env={
                            **env,
                            "MEMBERSHIP_RETIREMENT_INPUT": str(configuration),
                            "MEMBERSHIP_RETIREMENT_STAGE": stage,
                        },
                        stdout=log,
                        stderr=log,
                        timeout=60,
                    )
                assert completed.returncode == 0, (
                    tmp_path / ("renderer-" + stage + ".log")
                ).read_text()

            run_renderer("loss")
            wait_for(lambda: first.poll() is not None)
            assert first.returncode == 87
            retained = json.loads((tmp_path / "renderer-journal.json").read_text())
            assert (
                retained["pending"]["request"] == request.public()
                and retained["receipt"]["outcome"] == "not_found"
            )
            start()
            run_renderer("recovery")
            final = json.loads((tmp_path / "renderer-journal.json").read_text())
            assert final["receipt"]["outcome"] == "recorded" and len(final["history"]) == 1
            previous = final["history"][0]
            assert (
                previous["operation"]["request"] == request.public()
                and previous["receipt"]["outcome"] == "retired"
            )
            assert client.post(root + "/resolve", json=query).json() == previous["receipt"]
            assert client.post(root, json=request.public()).json() == previous["receipt"]
            tid = final["receipt"]["effect"]["ticket_id"]
            with Session(engine) as s:
                assert s.scalar(select(Operation.id).where(Operation.ticket_id == tid)) is None
                receipts = list(
                    s.scalars(
                        select(MembershipReceipt).where(MembershipReceipt.workspace_id == c["wid"])
                    )
                )
                retirements = list(
                    s.scalars(
                        select(MembershipCommandRetirement).where(
                            MembershipCommandRetirement.workspace_id == c["wid"]
                        )
                    )
                )
                assert len(receipts) == len(retirements) == 1
            (tmp_path / "actual-membership-retirement-process.json").write_text(
                json.dumps(
                    {
                        "original": request.public(),
                        "rejection": rejected.json(),
                        "initial_missing": missing,
                        "retained_after_process_loss": retained,
                        "recovered_and_fresh_record": final,
                        "late_original": client.post(root, json=request.public()).json(),
                        "api_exit_after_committed_retirement": 87,
                        "retirements": 1,
                        "recorded_fresh_proposals": 1,
                        "external_operations_created": 0,
                    },
                    indent=2,
                )
                + "\n"
            )
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
        for log in logs:
            log.close()
