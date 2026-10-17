"""Mounted manual fax passage review against the registered signed product API.

Image acquisition is a previously approved fixture action through real F8,
vendor adapter, and bounded PDF process. The UI then reviews that actual PDF's
invented text; only vendor HTTP/credentials and browser storage are synthetic.
"""

import hashlib
import io
import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pypdf
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration import test_efax_inbound_source_api as source_fixture

from cosmas_os.efax_inbound_models import EFaxInboundInvocation, EFaxInboundOutcome
from cosmas_os.efax_source_models import EFaxInboundSourceReview
from cosmas_os.models import Operation
from cosmas_os.ports.vendor_connectors import digest

managed_case = source_fixture.managed_case
efax_http = source_fixture.efax_http
source_http = source_fixture.source_http
NODE = Path(shutil.which("node") or "node")
REPO = Path(__file__).resolve().parents[2]


def invented_pdf(persona, iteration):
    lines = [f"Invented {persona} fax review round {iteration}.",
        "Patient-reported cardiac history is uncertain. No reported chest pain today.",
        "Medication is spelled M-E-T-O-P-R-O-L-O-L. DOB and trial eligibility unknown."]
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
        DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    content = DecodedStreamObject()
    body = "BT /F1 10 Tf 40 740 Td " + " 0 -16 Td ".join(
        "(" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj" for line in lines) + " ET"
    content.set_data(body.encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    out = io.BytesIO()
    writer.write(out)
    document, passage = out.getvalue(), "\n".join(lines)
    # Independent from the UI/source service and from the bounded worker: this
    # fixture passage actually occurs in the acquired document; it is not OCR.
    assert pypdf.PdfReader(io.BytesIO(document)).pages[0].extract_text().strip() == passage
    return document, passage


def test_six_signed_manual_passage_reviews_with_exact_encrypted_restart_recovery(
    source_http, tmp_path
):
    f = source_http
    output = tmp_path / "signed-efax-source-ui"
    output.mkdir()
    cases = {}
    holder = SimpleNamespace(client=None, active=None, restarts=0)
    request_lock = Lock()

    def start():
        if holder.client is not None:
            holder.client.__exit__(None, None, None)
        holder.client = f.case.start(f.profile)
        holder.client.__enter__()

    def read_workspace():
        return source_fixture.read(f, holder.client)

    def inspect(episode):
        with Session(f.case.engine) as session:
            operation = session.get(Operation, episode.operation_id)
            outcome = session.get(EFaxInboundOutcome, episode.operation_id)
            invocation = session.get(EFaxInboundInvocation, episode.operation_id)
            reviews = list(session.scalars(select(EFaxInboundSourceReview).where(
                EFaxInboundSourceReview.workspace_id == f.wid,
                EFaxInboundSourceReview.operation_id == episode.operation_id)))
            end = episode.provider_after if episode.provider_after is not None else len(f.wire)
            return {"case_id": episode.id, "workspace": episode.workspace_after or read_workspace(),
                "case_provider_calls": end - episode.provider_before,
                "image_calls": sum(row["path"].endswith("/image") for row in f.wire[episode.provider_before:end]),
                "review_count": len(reviews), "restarts": holder.restarts,
                "source": None if not reviews else {"review_id": reviews[0].id,
                    "entry_id": reviews[0].entry_id, "request_sha256": reviews[0].request_sha256,
                    "document_sha256": reviews[0].document_sha256,
                    "content_sha256": reviews[0].content_sha256, "source_sha256": reviews[0].source_sha256,
                    "patient_link_id": reviews[0].patient_link_id},
                "operation": None if operation is None or outcome is None else {
                    "id": operation.id, "status": operation.status, "attempt_count": operation.attempt_count,
                    "invocation": invocation is not None, "outcome": outcome.state,
                    "document_sha256": hashlib.sha256(outcome.document).hexdigest()
                        if outcome.document is not None else None, "pages": outcome.pages}}

    def validate_episode(episode):
        observed = inspect(episode)
        assert observed["case_provider_calls"] == 2 and observed["image_calls"] == 1
        assert observed["review_count"] == 1
        workspace = observed["workspace"]
        assert workspace["note"] == episode.before["note"]
        existing = {entry["id"]: entry for entry in episode.before["entries"]}
        assert {entry["id"]: entry for entry in workspace["entries"] if entry["id"] in existing} == existing
        new = [entry for entry in workspace["entries"] if entry["id"] not in existing]
        assert len(new) == 1 and new[0]["kind"] == "efax_inbound_source"
        assert (new[0]["content"], new[0]["fax_source_state"]) == (episode.passage, "current")
        assert observed["source"]["entry_id"] == new[0]["id"]
        assert observed["source"]["content_sha256"] == hashlib.sha256(episode.passage.encode()).hexdigest()
        assert observed["source"]["document_sha256"] == episode.document_sha256
        assert observed["source"]["patient_link_id"] is not None
        assert observed["operation"] == {"id": episode.operation_id, "status": "succeeded",
            "attempt_count": 1, "invocation": True, "outcome": "acquired",
            "document_sha256": episode.document_sha256, "pages": 1}
        return observed

    def create_case(persona, iteration):
        if holder.active is not None:
            holder.active.provider_after = len(f.wire)
            completed = validate_episode(holder.active)
            holder.active.workspace_after = completed["workspace"]
        f.fax_id = str(uuid4())
        f.operation_id = None
        f.pdf, passage = invented_pdf(persona, iteration)
        before = read_workspace()
        provider_before = len(f.wire)
        signed = source_fixture.signed_fixture
        _, observed = signed.observe(f, holder.client)
        item = observed["snapshot"]["items"][0]
        proposed = signed.result(holder.client.post("/efax-inbound/propose", headers=f.headers(), json={
            "idempotency_key": signed.key(), "grant_id": f.grant_id,
            "observation_id": observed["observation_id"], "observation_sha256": observed["source_sha256"],
            "fax_id": item["fax_id"], "fax_sha256": digest("cosmas-efax-inbound-fax.v1", item)}))
        approved = signed.result(holder.client.post("/efax-inbound/decide", headers=f.headers(), json={
            "idempotency_key": signed.key(), "ticket_id": proposed["ticket_id"],
            "revision_id": proposed["revision_id"], "expected_version": proposed["version"],
            "choice": "approve", "reviewed_mark_read": True}))
        assert approved["state"] == "approved" and len(f.wire) - provider_before == 1
        with Session(f.case.engine) as session:
            operation = session.scalar(select(Operation).where(Operation.ticket_id == proposed["ticket_id"]))
            assert operation is not None and operation.status == "pending" and operation.attempt_count == 0
            f.operation_id = operation.id
        acquisition_request = {"idempotency_key": signed.key(), "ticket_id": proposed["ticket_id"],
            "revision_id": proposed["revision_id"], "expected_version": approved["version"],
            "approval_sha256": approved["approval_sha256"]}
        acquired = source_fixture.signed_fixture.result(holder.client.post(
            "/efax-inbound/acquire", headers=f.headers(), json=acquisition_request))
        assert acquired["state"] == "acquired" and acquired["content_available"] is True
        assert len(f.wire) - provider_before == 2
        assert acquired["document"] == {"sha256": hashlib.sha256(f.pdf).hexdigest(),
            "byte_length": len(f.pdf), "pages": 1}
        episode = SimpleNamespace(id=str(uuid4()), persona=persona, iteration=iteration,
            operation_id=acquired["operation_id"], provider_before=provider_before,
            provider_after=None, workspace_after=None, before=before, passage=passage,
            document_sha256=hashlib.sha256(f.pdf).hexdigest())
        holder.active = episode
        cases[episode.id] = episode
        # Recover the real acquisition command for later DB-only current-document
        # rechecks; never create an alternative operation or repeat image GET.
        account_response = holder.client.get("/provider-team/identity", headers={
            "Authorization": f.headers()["Authorization"], "X-Cosmas-Team-Contract": "2", "X-Cosmas-Draft-Recovery": "2"})
        assert account_response.status_code == 200, account_response.text
        return {"case_id": episode.id, "token": f.headers()["Authorization"].removeprefix("Bearer "),
            "workspace": before, "account": account_response.json(), "passage": passage,
            "visit": {"id": f.wid, "label": before["label"], "revision": before["revision"]},
            "offered": {"operation_id": episode.operation_id, "document_sha256": episode.document_sha256,
                "pages": 1, "label": "Invented acquired " + persona + " fax"},
            "acquisition": {"kind": "acquire", "request": acquisition_request}}

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, data, headers=None):
            raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=True).encode()
            self.send_response(status)
            for name, value in (headers or {}).items():
                if name.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}:
                    self.send_header(name, value)
            if not headers or "content-type" not in headers:
                self.send_header("Content-Type", "application/json")
            if not headers or "cache-control" not in headers:
                self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def dispatch(self):
            with request_lock:
                try:
                    parsed = urlsplit(self.path)
                    if self.command == "GET" and parsed.path == "/lab/case":
                        query = parse_qs(parsed.query)
                        persona, iteration = query["persona"][0], query["round"][0]
                        assert persona in {"physician", "nurse_practitioner", "physician_assistant"} and iteration in {"1", "2"}
                        return self.respond(200, create_case(persona, iteration))
                    if self.command == "GET" and parsed.path == "/lab/inspect":
                        return self.respond(200, inspect(cases[parse_qs(parsed.query)["case_id"][0]]))
                    if self.command == "POST" and parsed.path == "/lab/restart":
                        size = int(self.headers.get("Content-Length", "0"))
                        assert 0 < size <= 1024
                        body = json.loads(self.rfile.read(size))
                        assert set(body) == {"case_id"} and cases[body["case_id"]] is holder.active
                        start()
                        holder.restarts += 1
                        return self.respond(200, inspect(holder.active))
                    assert holder.active is not None and not parsed.query
                    allowed = {"/provider-team/identity", "/workspaces/" + f.wid,
                        f.path, f.path + "/resolve", "/efax-inbound/resolve"}
                    assert parsed.path in allowed
                    headers = {name: value for name, value in self.headers.items() if name.lower() in {
                        "authorization", "x-cosmas-draft-recovery", "x-cosmas-efax-inbound",
                        "x-cosmas-team-contract", "x-cosmas-model-contract", "accept", "content-type"}}
                    if parsed.path == "/provider-team/identity":
                        assert self.command == "GET" and self.headers.get("X-Cosmas-Team-Contract") == "2"
                        assert self.headers.get("X-Cosmas-EFax-Inbound") is None
                    elif parsed.path == "/workspaces/" + f.wid:
                        assert self.command == "GET" and self.headers.get("X-Cosmas-Model-Contract") == "1"
                    else:
                        assert self.command == "POST" and self.headers.get("X-Cosmas-EFax-Inbound") == "1"
                    if self.command == "GET":
                        response = holder.client.get(self.path, headers=headers)
                    else:
                        size = int(self.headers.get("Content-Length", "0"))
                        assert 0 < size <= (65536 if parsed.path == f.path else 2048)
                        body = self.rfile.read(size)
                        response = holder.client.post(self.path, headers=headers, content=body)
                    return self.respond(response.status_code, response.content, response.headers)
                except Exception as error:
                    return self.respond(500, {"error": {"code": "efax_inbound_lab_failure"},
                        "diagnostic": type(error).__name__ + ": " + str(error)[:500]})

        do_GET = dispatch
        do_POST = dispatch

    start()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {name: os.environ[name] for name in ("PATH", "TMPDIR") if name in os.environ}
    env.update(COSMAS_EFAX_SOURCE_LAB_URL=f"http://127.0.0.1:{server.server_port}",
        COSMAS_EFAX_SOURCE_LAB_REPORT=str(output / "ui-server-lab.json"))
    try:
        completed = subprocess.run([str(NODE), "node_modules/vitest/vitest.mjs", "run",
            "src/EFaxSourceReview.signed-api.test.tsx", "--maxWorkers=1"], cwd=REPO / "web", env=env,
            text=True, capture_output=True, timeout=300)
        (output / "vitest.log").write_text(completed.stdout + completed.stderr)
        observations = [inspect(episode) for episode in cases.values()]
        (output / "backend-evidence.json").write_text(json.dumps({"synthetic_only": True,
            "cases": observations, "provider_wire": f.wire, "credential_calls": len(f.credentials),
            "dependency_overrides": 0, "parser": "actual bounded pypdf process",
            "returncode": completed.returncode}, indent=2) + "\n")
        assert completed.returncode == 0, completed.stdout + completed.stderr
        report = json.loads((output / "ui-server-lab.json").read_text())
        assert report["completed"] == report["total"] == len(observations) == 6
        assert len(f.wire) == len(f.credentials) == 12 and holder.restarts == 6
        for episode in cases.values():
            validate_episode(episode)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if holder.client is not None:
            holder.client.__exit__(None, None, None)
