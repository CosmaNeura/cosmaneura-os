"""Real two-GET ingress, signed HTTP, PostgreSQL and three intentional process losses."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_inbox_work import ON, inbox_case
from tests.integration.test_vendor_process import unused_port, wait_for
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case
from tests.unit.test_spruce_inbox import PRIVATE_TEXT, responses

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.adapters.vendor_connectors.spruce_inbox import (
    SPRUCE_INBOX_ORIGIN,
    SpruceInboxConnector,
)
from cosmas_os.adapters.vendor_connectors.transport import Credential
from cosmas_os.api import inbox_work_schemas as p
from cosmas_os.application import inbox_work as flow
from cosmas_os.application import services
from cosmas_os.inbox_models import InboxEvent, InboxItem, InboxSource
from cosmas_os.models import AuditEvent, ExternalIdentity, Operation, Principal, Ticket


def test_actual_ingress_signed_commands_and_negative_proof_survive_process_loss(
    engine, tmp_path, monkeypatch
):
    subjects = {name: "user_inbox_" + uuid4().hex for name in ("owner", "staff", "peer")}
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented inbound restart practice",
        )
        vendor_factory = getattr(vendor_case, "__wrapped__", None)
        inbox_factory = getattr(inbox_case, "__wrapped__", None)
        assert callable(vendor_factory) and callable(inbox_factory)
        c = inbox_factory(s, vendor_factory(s, seed))
        assert isinstance(c, dict)
        actors = {"owner": c["actor"]}
        for name in ("staff", "peer"):
            actor = Principal(
                box_id=c["box"],
                principal_type="human",
                state="active",
                is_owner=name == "peer",
                display_name="Invented Inbox " + name,
            )
            s.add(actor)
            s.flush()
            actors[name] = actor.id
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
                    evidence_ref="local:inbox-process",
                )
            )
        s.commit()
        before = {
            model.__name__: s.scalar(
                select(func.count()).select_from(model).where(model.box_id == c["box"])
            )
            for model in (Ticket, Operation, AuditEvent)
        }

    binding = c["grant"].binding
    payloads = responses()
    item, parent = payloads[0]["conversationItem"], payloads[1]["conversation"]
    item.update(
        id=binding.item_id,
        conversationId=binding.conversation_id,
        createdAt=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        modifiedAt=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )
    item["author"]["id"] = binding.contact_id
    parent.update(
        id=binding.conversation_id, externalParticipants=[{"contact": binding.contact_id}]
    )
    parent["internalEndpoint"]["rawValue"] = binding.secure_endpoint_raw_value
    paths = [
        "/v1/conversationItems/" + binding.item_id,
        "/v1/conversations/" + binding.conversation_id,
    ]
    calls, checkpoints = [], []

    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append({"method": "GET", "path": self.path})
            assert self.path in paths and len(calls) <= 2
            assert self.headers["Authorization"] == "Bearer invented-inbox-token"
            data = json.dumps(payloads[paths.index(self.path)]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    receiver = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    api_port, receiver_port = unused_port(), receiver.server_port
    allowed = {("127.0.0.1", api_port), ("127.0.0.1", receiver_port), ("127.0.0.1", 55479)}
    old_connect, old_connect_ex, old_dns = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.getaddrinfo,
    )

    def guard(sock, address):
        if sock.family != socket.AF_UNIX and (
            not isinstance(address, tuple) or address[:2] not in allowed
        ):
            raise PermissionError("Only this test's database and two listeners are authorized")

    def connect(sock, address):
        guard(sock, address)
        return old_connect(sock, address)

    def connect_ex(sock, address):
        guard(sock, address)
        return old_connect_ex(sock, address)

    def dns(host, port, *args, **kwargs):
        if (host, port) not in allowed and (
            host.decode() if isinstance(host, bytes) else host,
            port,
        ) not in allowed:
            raise PermissionError("Only owned loopback DNS is authorized")
        return old_dns(host, port, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()

    class LocalTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport(retries=0)

        async def handle_async_request(self, request):
            assert request.method == "GET" and str(request.url).startswith(
                SPRUCE_INBOX_ORIGIN + "/"
            )
            assert request.url.path in paths and not request.url.query and not request.content
            local = request.url.copy_with(scheme="http", host="127.0.0.1", port=receiver_port)
            return await self.inner.handle_async_request(
                httpx.Request("GET", local, headers=request.headers)
            )

        async def aclose(self):
            await self.inner.aclose()

    async def credentials(selection):
        assert selection == binding.selection
        return Credential(
            selection_sha256=selection.commitment(),
            credential_ref=str(selection.credential_ref),
            secret=SecretStr("invented-inbox-token"),
        )

    async def authorize(selected):
        assert selected == binding
        with Session(engine) as s:
            checkpoints.append(len(calls))
            return flow.authorize_read(s, c["grant"], registry=c["registry"], policy=ON)

    children, logs = [], []
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (tmp_path / "public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
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
    tokens = {
        name: jwt.encode(
            {
                "sub": subject,
                "iss": "https://clerk.example.invalid",
                "aud": "cosmas-workspace-local",
                "sid": "session_invented_inbox",
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
        for name, subject in subjects.items()
    }
    origin = "http://127.0.0.1:" + str(api_port)

    def start(loss=None, *, enabled=True, registry_removed=False):
        (tmp_path / "configuration.json").write_text(
            json.dumps(
                {
                    "port": api_port,
                    "lose_kind": loss,
                    "grant": c["grant"].model_dump(mode="json"),
                    "enabled": enabled,
                    "registry_removed": registry_removed,
                }
            )
        )
        log = (tmp_path / ("process-" + str(len(children)) + ".log")).open("xb")
        logs.append(log)
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).parents[1] / "helpers/inbox_process.py"),
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
        connector = SpruceInboxConnector(
            binding.selection,
            credentials,
            enabled=True,
            authorize=authorize,
            transport=LocalTransport(),
        )
        value = asyncio.run(connector.read(binding))
        assert value.text == PRIVATE_TEXT and checkpoints == [0, 0, 1, 2]
        with Session(engine) as s:
            admitted = flow.ingest(
                s, c["grant"], value, "actual-owned-two-get-read", registry=c["registry"], policy=ON
            )
        iid = admitted["item_id"]
        path = "/inbox/" + iid
        scope = {"box_id": c["box"], "owner_id": c["actor"]}
        first = start("triage")
        with httpx.Client(
            base_url=origin,
            timeout=10,
            trust_env=False,
            headers={"Authorization": "Bearer " + tokens["owner"], "X-Cosmas-Inbox-Contract": "1"},
        ) as client:

            def get():
                response = client.get(path)
                assert response.status_code == 200, response.text
                return p.Detail.model_validate(response.json()).public()

            def bound(d):
                summary = d["summary"]
                return {
                    "item_id": iid,
                    "expected_version": summary["version"],
                    "source_id": summary["source_id"],
                    "source_sha256": summary["source_sha256"],
                    "idempotency_key": "actual-human-" + uuid4().hex,
                }

            def resolve(kind, request):
                q = p.Resolve(
                    item_id=iid,
                    command_kind=kind,
                    idempotency_key=request.idempotency_key,
                    request_sha256=p.request_digest(kind, scope, request),
                )
                response = client.post("/inbox/resolve", json=q.public())
                assert response.status_code == 200, response.text
                return p.Receipt.model_validate(response.json()).public()

            initial = get()
            rejected_request = p.Triage(
                **bound(initial),
                classification="administrative_review",
                due_date="2026-10-01",
                instructions="Invented classification before required patient review.",
                human_disposition_required=True,
            )
            with pytest.raises(httpx.HTTPError):
                client.post(path + "/triage", json=rejected_request.public())
            wait_for(lambda: first.poll() is not None)
            assert first.returncode == 87
            second = start("review")
            rejected = resolve("triage", rejected_request)
            assert (
                rejected["outcome"] == "rejected"
                and rejected["rejection"] == "inbox_review_required"
            )
            review_request = p.Review(
                **bound(get()),
                workspace_id=c["wid"],
                expected_workspace_revision=3,
                patient_link_id=str(binding.patient_link_id),
                reviewed_patient=True,
                reviewed_exact_thread=True,
                reviewed_untrusted_source=True,
            )
            with pytest.raises(httpx.HTTPError):
                client.post(path + "/review", json=review_request.public())
            wait_for(lambda: second.poll() is not None)
            assert second.returncode == 87
            third = start("verify")
            reviewed = resolve("review", review_request)
            assert reviewed["outcome"] == "recorded"
            assert client.post(path + "/review", json=review_request.public()).json() == reviewed
            assert client.post(path + "/triage", json=rejected_request.public()).json() == rejected
            t = p.Triage(
                **bound(get()),
                classification="administrative_review",
                due_date="2026-10-01",
                instructions="Owner will review this invented administrative message locally.",
                human_disposition_required=True,
            )
            tr = client.post(path + "/triage", json=t.public())
            assert tr.status_code == 200 and tr.json()["outcome"] == "recorded", tr.text
            rrq = p.Result(
                **bound(get()),
                triage_receipt_id=tr.json()["receipt_id"],
                triage_receipt_sha256=tr.json()["receipt_sha256"],
                disposition="local_review_complete",
                evidence="Invented source and administrative review checked; no reply sent.",
                no_external_action_claimed=True,
            )
            rr = client.post(path + "/result", json=rrq.public())
            assert rr.status_code == 200 and rr.json()["outcome"] == "recorded", rr.text
            verify_request = p.Verify(
                **bound(get()),
                result_receipt_id=rr.json()["receipt_id"],
                result_receipt_sha256=rr.json()["receipt_sha256"],
                reviewed_patient=True,
                reviewed_exact_source=True,
                reviewed_human_result=True,
                confirm_local_review_only=True,
            )
            with pytest.raises(httpx.HTTPError):
                client.post(path + "/verify", json=verify_request.public())
            wait_for(lambda: third.poll() is not None)
            assert third.returncode == 87
            final = start()
            verified = resolve("verify", verify_request)
            assert verified["outcome"] == "recorded"
            assert client.post(path + "/verify", json=verify_request.public()).json() == verified
            closed = get()
            assert closed["summary"]["state"] == "closed_local_review"
            assert closed["summary"]["handoff_available"] is False
            history = client.get(path + "/history").json()
            assert len(history["commands"]) == 5 and len(history["reads"]) == 1
            assert p.History.model_validate(history).public() == history
            catalog = client.get("/inbox").json()
            for name in ("staff", "peer"):
                private_headers = {"Authorization": "Bearer " + tokens[name]}
                for suffix in ("", "/history", "/sources/" + initial["summary"]["source_id"]):
                    denied = client.get(path + suffix, headers=private_headers)
                    assert denied.status_code == 404 and PRIVATE_TEXT not in denied.text
                denied = client.post(
                    "/inbox/resolve",
                    headers=private_headers,
                    json=p.Resolve(
                        item_id=iid,
                        command_kind="verify",
                        idempotency_key=verify_request.idempotency_key,
                        request_sha256=p.request_digest("verify", scope, verify_request),
                    ).public(),
                )
                assert denied.status_code == 404
            assert (
                client.post(path + "/ingest", json=value.model_dump(mode="json")).status_code == 400
            )
            assert client.get(path, headers={"X-Cosmas-Inbox-Contract": "2"}).status_code == 426
            final.terminate()
            final.wait(timeout=5)
            start(enabled=False, registry_removed=True)
            unavailable = get()
            assert unavailable["summary"]["binding_current"] is False
            assert not any(
                unavailable["availability"][x] for x in ("review", "triage", "result", "verify")
            )
            for kind, request, receipt in (
                ("triage", rejected_request, rejected),
                ("review", review_request, reviewed),
                ("verify", verify_request, verified),
            ):
                assert resolve(kind, request) == receipt
                assert client.post(path + "/" + kind, json=request.public()).json() == receipt
            assert calls == [{"method": "GET", "path": x} for x in paths]
            with Session(engine) as s:
                assert {
                    model.__name__: s.scalar(
                        select(func.count()).select_from(model).where(model.box_id == c["box"])
                    )
                    for model in (Ticket, Operation, AuditEvent)
                } == before
                assert (
                    s.scalar(
                        select(func.count())
                        .select_from(InboxSource)
                        .where(InboxSource.item_id == iid)
                    )
                    == 1
                )
                assert (
                    s.scalar(
                        select(func.count())
                        .select_from(InboxEvent)
                        .where(InboxEvent.item_id == iid)
                    )
                    == 6
                )
                stored_item = s.get(InboxItem, iid)
                assert stored_item is not None and stored_item.version == 6
            exported = {
                "initial": initial,
                "catalog": catalog,
                "rejected_request": rejected_request.public(),
                "rejected_receipt": rejected,
                "review_request": review_request.public(),
                "review_receipt": reviewed,
                "triage_request": t.public(),
                "triage_receipt": tr.json(),
                "result_request": rrq.public(),
                "result_receipt": rr.json(),
                "verify_request": verify_request.public(),
                "verify_receipt": verified,
                "closed": closed,
                "unavailable": unavailable,
                "history": history,
                "read_calls": calls,
                "read_authority_checkpoints": checkpoints,
            }
            (tmp_path / "actual-inbox-process.json").write_text(json.dumps(exported, indent=2))
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
        for log in logs:
            log.close()
        receiver.shutdown()
        receiver.server_close()
        thread.join(timeout=5)
