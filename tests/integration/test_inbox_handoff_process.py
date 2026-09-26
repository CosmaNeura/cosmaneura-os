"""Signed, independently committed F8 publication survives owned process loss."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_inbox_handoff import case
from tests.integration.test_inbox_work import inbox_case
from tests.integration.test_vendor_process import unused_port, wait_for
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import inbox_handoff_schemas as p
from cosmas_os.application import services
from cosmas_os.inbox_handoff_models import InboxHandoffReceipt
from cosmas_os.models import ExternalIdentity, FollowUpSource, Operation, WorkHandoff


def test_signed_preinvoke_and_committed_response_loss_recover_exactly_once(engine, tmp_path):
    subjects = {name: "user_incoming_" + uuid4().hex for name in ("owner", "staff", "peer")}
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "blob")),
            "Invented internal incoming handoff",
        )
        c = case.__wrapped__(s, inbox_case.__wrapped__(s, vendor_case.__wrapped__(s, seed)))
        actors = {"owner": c["actor"], "staff": c["staff"], "peer": c["peer"]}
        for name, actor in actors.items():
            s.add(
                ExternalIdentity(
                    box_id=c["box"],
                    principal_id=actor,
                    provider="clerk",
                    issuer="https://clerk.example.invalid",
                    subject=subjects[name],
                    organization_id="org_invented",
                    reviewed_by="Invented reviewer",
                    evidence_ref="local:incoming-handoff",
                )
            )
        s.commit()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (tmp_path / "public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    now = datetime.now(UTC)
    tokens = {
        name: jwt.encode(
            {
                "sub": sub,
                "iss": "https://clerk.example.invalid",
                "aud": "cosmas-workspace-local",
                "sid": "session_invented_incoming_" + name,
                "azp": "http://localhost:5173",
                "org_id": "org_invented",
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(minutes=5),
            },
            key,
            algorithm="RS256",
            headers={"kid": "invented-inbox-key"},
        )
        for name, sub in subjects.items()
    }
    port = unused_port()
    origin = f"http://127.0.0.1:{port}"
    assert port not in {8046, 8047, 8197, 8246, 8247, 8248, 8256}
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
    children = []
    logs = []
    vectors = []

    def start(before=False, loss=None):
        (tmp_path / "configuration.json").write_text(
            json.dumps(
                {
                    "port": port,
                    "lose_before": before,
                    "lose_kind": loss,
                    "grant": c["grant"].model_dump(mode="json"),
                }
            )
        )
        log = (tmp_path / f"process-{len(children)}.log").open("xb")
        logs.append(log)
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).parents[1] / "helpers/inbox_handoff_process.py"),
                str(tmp_path),
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        children.append(child)

        def ready():
            assert child.poll() is None, (child.returncode, tmp_path)
            try:
                return (
                    httpx.get(origin + "/health", timeout=0.25, trust_env=False).status_code == 200
                )
            except httpx.HTTPError:
                return False

        wait_for(ready)
        return child

    def headers(actor="owner"):
        return {"Authorization": "Bearer " + tokens[actor], "X-Cosmas-Inbox-Handoff-Contract": "1"}

    try:
        before = start(before=True)
        with httpx.Client(base_url=origin, timeout=10, trust_env=False) as client:
            private = f"/workspaces/{c['wid']}/inbox-handoffs"
            try:
                client.post(private + "/propose", json=c["q"].public(), headers=headers())
            except httpx.HTTPError:
                pass
            else:
                raise AssertionError("Expected owned preinvoke connection loss")
            assert before.wait(10) == 88
            with Session(engine) as s:
                assert (
                    s.scalar(
                        select(func.count())
                        .select_from(FollowUpSource)
                        .where(FollowUpSource.owner_id == c["actor"])
                    )
                    == 0
                )
            lost = start(loss="decide")
            with ThreadPoolExecutor(max_workers=2) as pool:
                proposals = list(
                    pool.map(
                        lambda _: client.post(
                            private + "/propose", json=c["q"].public(), headers=headers()
                        ),
                        range(2),
                    )
                )
            proposal = proposals[0]
            assert proposal.status_code == 200, proposal.text
            assert proposals[1].status_code == 200 and proposals[1].json() == proposal.json()
            value = p.Response.model_validate(proposal.json()).public()
            vectors.append(value)
            tid = value["effect"]["ticket_id"]
            path = "/inbox-handoffs/" + tid
            q = {
                "ticket_id": tid,
                "expected_version": value["effect"]["version"],
                "revision_id": value["effect"]["revision_id"],
                "payload_hash": value["effect"]["payload_hash"],
                "idempotency_key": "publish-process-once",
                "choice": "approve",
                "publish_selected_context": True,
            }
            try:
                client.post(path + "/decide", json=q, headers=headers())
            except httpx.HTTPError:
                pass
            else:
                raise AssertionError("Expected committed response loss")
            assert lost.wait(10) == 87
            with Session(engine) as s:
                assert (
                    s.scalar(
                        select(func.count())
                        .select_from(Operation)
                        .where(Operation.ticket_id == tid)
                    )
                    == 1
                )
                receipt = s.scalar(
                    select(InboxHandoffReceipt).where(
                        InboxHandoffReceipt.ticket_id == tid,
                        InboxHandoffReceipt.command_kind == "decide",
                    )
                )
                digest = receipt.request_sha256
            start()
            restored = client.post(
                path + "/resolve",
                json={
                    "command_kind": "decide",
                    "idempotency_key": q["idempotency_key"],
                    "request_sha256": digest,
                },
                headers=headers(),
            )
            assert restored.status_code == 200, restored.text
            assert (
                client.post(path + "/decide", json=q, headers=headers()).json() == restored.json()
            )
            vectors.append(restored.json())
            assert client.get(path, headers=headers("peer")).status_code == 404

            def command(command_kind, actor="owner", **extra):
                detail = client.get(path, headers=headers(actor)).json()
                req = {k: detail[k] for k in ("ticket_id", "revision_id", "payload_hash")}
                req.update(
                    expected_version=detail["version"],
                    idempotency_key=command_kind + "-" + str(uuid4()),
                    **extra,
                )
                response = client.post(path + "/" + command_kind, json=req, headers=headers(actor))
                assert response.status_code == 200, response.text
                value = p.Response.model_validate(response.json()).public()
                vectors.append(value)
                return value

            offered = command("handoff", kind="offer", recipient_id=c["staff"])
            command(
                "handoff", actor="staff", kind="accept", offer_id=offered["effect"]["effect_id"]
            )
            command(
                "result",
                actor="staff",
                evidence="Accountable local review finished.",
                no_external_action_claimed=True,
            )
            detail = client.get(path, headers=headers()).json()
            result = detail["result"]
            command(
                "verify",
                result_receipt_id=result["receipt_id"],
                result_request_sha256=result["request_sha256"],
                reviewed_current_source=True,
                reviewed_result=True,
                local_handoff_only=True,
            )
            assert client.get(path, headers=headers()).json()["verified_current"]
            with Session(engine) as s:
                assert (
                    s.scalar(
                        select(func.count())
                        .select_from(Operation)
                        .where(Operation.ticket_id == tid)
                    )
                    == 1
                )
                assert (
                    s.scalar(
                        select(func.count())
                        .select_from(WorkHandoff)
                        .where(WorkHandoff.ticket_id == tid)
                    )
                    == 2
                )
            (tmp_path / "SIGNED_PROCESS_VERIFIED.json").write_text(
                json.dumps(
                    {
                        "api_port": port,
                        "preinvoke_effects": 0,
                        "publication_operations": 1,
                        "handoffs": 2,
                        "preinvoke_exit": 88,
                        "lost_response_exit": 87,
                        "vectors": vectors,
                    },
                    indent=2,
                )
            )
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(10)
        for log in logs:
            log.close()
