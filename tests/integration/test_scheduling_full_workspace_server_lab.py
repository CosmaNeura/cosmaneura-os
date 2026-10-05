"""Full EncounterWorkspace -> signed OS -> signed prepared Scheduling receiver and master writer."""

import json
import os
import subprocess
import select as io_select
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from inspect import unwrap
from pathlib import Path
from threading import Lock, Thread, local
from types import SimpleNamespace
from typing import Any, TypedDict
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_scheduling_patient_setup import case as patient_case
from tests.integration import test_scheduling_patient_setup as patient_fixture_module
from tests.unit.test_hosted_workspace_config import hosted

from cosmas_os.adapters.scheduling import HttpSchedulingAvailability
from cosmas_os.adapters.scheduling_actions import HttpSchedulingAppointments
from cosmas_os.adapters.scheduling_patient_setup import HttpSchedulingPatientSetup
from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import provider_team as team
from cosmas_os.application import scheduling_patient_setup as patient_setup
from cosmas_os.application import services as svc
from cosmas_os.application import team_resources, team_setup
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    AppointmentReceipt,
    AppointmentWork,
    ExternalIdentity,
    Operation,
    SchedulingAccount,
    SchedulingPatientAccount,
)
from cosmas_os.ports import scheduling_patient_setup as patient_port_module
from cosmas_os.scheduling_login_models import SchedulingLoginCredential
from cosmas_os.scheduling_patient_models import (
    SchedulingPatientMappingReview,
    SchedulingPatientSetupRequest,
)

NODE = Path("/Users/jw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
REPO = Path(__file__).resolve().parents[2]
ORIGIN = "https://workspace.example.invalid"


class SignedWriterReceiver:
    """Closed stdio substitute for HTTPS transport; actual service handlers and SQL.

    Patient projection writes use the retained signed master writer and its own
    restricted LOGIN. The service, staff/grant binding and Google I/O are local
    invented fixtures, and this protocol exposes no booking/write route.
    """

    def __init__(self, output):
        root = Path(os.environ["COSMAS_SCHEDULING_PACKET_ROOT"]).resolve()
        interpreter = Path(os.environ["PROPOSAL_RECEIVER_PYTHON"])
        assert interpreter.is_file() and (root / "bootstrap-contract/writer_receiver_stdio_bridge.py").is_file()
        environment = {"PATH": "/usr/bin:/bin", "HOME": "/private/tmp", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": ":".join(str(root / path) for path in ("receiver/services/api/src", "receiver/tests", "bootstrap-contract")),
            "PROPOSAL_RECEIVER_TEST_DATABASE_URL": os.environ["PROPOSAL_RECEIVER_TEST_DATABASE_URL"],
            "COSMANEURA_SCHEDULING_ALLOW_INSECURE_LOCAL_HEADER": "true",
            "COSMANEURA_SCHEDULING_DEPLOYMENT_PROFILE": "development"}
        self.lock, self.closed = Lock(), False
        self.stderr = (output / "receiver-stderr.log").open("w")
        self.process = subprocess.Popen([str(interpreter), str(root / "bootstrap-contract/writer_receiver_stdio_bridge.py")],
            cwd=root / "receiver", env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.stderr, text=True, bufsize=1)
        try:
            ready = self.read(timeout=90)
            assert ready.get("ready") is True
            self.practice, self.actor, self.patient, self.token = (ready[n] for n in ("practice", "actor", "patient", "token"))
            self.remote_appointment = ready["remote_appointment"]
            self.resources = {"practitioner_id": ready["practitioner"], "location_id": ready["location"], "appointment_type_id": ready["appointment_type"]}
        except BaseException:
            self.process.kill(); self.process.wait(timeout=5); self.stderr.close()
            raise

    def read(self, timeout=30):
        assert self.process.stdout is not None
        if not io_select.select([self.process.stdout], [], [], timeout)[0]:
            raise RuntimeError("bounded receiver protocol timeout")
        raw = self.process.stdout.readline(1048577)
        if not raw or len(raw.encode()) > 1048576:
            raise RuntimeError("bounded receiver protocol failed")
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("failed"):
            raise RuntimeError("receiver fixed protocol failed: " + str(value.get("error_type", "invalid response")))
        return value

    def call(self, value):
        with self.lock:
            assert self.process.stdin is not None
            self.process.stdin.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
            return self.read()

    def close(self):
        try:
            if self.process.poll() is None:
                assert self.call({"action": "close"}) == {"closed": True}
                assert self.process.wait(timeout=15) == 0
            self.closed = self.process.returncode == 0
        finally:
            if self.process.poll() is None:
                self.process.kill(); self.process.wait(timeout=5)
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe is not None: pipe.close()
            self.stderr.close()


class OperationEvidence(TypedDict):
    id: str
    started: bool
    attempt_count: int
    external_reference: str | None


class CaseEvidence(TypedDict):
    workspace: dict[str, Any]
    receiver_calls: int
    availability_calls: int
    receiver_writes: int
    mapping_reviews: int
    setup_requests: int
    proposal_count: int
    appointment_receipts: int
    operations: list[OperationEvidence]
    diagnostics: list[dict[str, Any]]
    receiver_ledger: dict[str, Any]
    master_writer: dict[str, Any]
    mapping_patient_id: str | None


def test_full_workspace_signed_writer_patient_proposals_and_encrypted_recovery(engine, monkeypatch, tmp_path):
    """Full interface, real consumer/receiver SQL; synthetic identity, HTTPS and Google substitutes."""
    if not all(os.environ.get(name) for name in ("COSMAS_SCHEDULING_PACKET_ROOT", "PROPOSAL_RECEIVER_PYTHON", "PROPOSAL_RECEIVER_TEST_DATABASE_URL")):
        pytest.skip("requires the explicit owned synthetic Scheduling source packet and receiver database")
    configuration = hosted(workspace_scheduling_enabled=True, workspace_appointments_enabled=True,
        workspace_scheduling_login_enabled=True, workspace_scheduling_patient_setup_enabled=True,
        workspace_team_setup_enabled=True, workspace_draft_recovery_required=True)
    configuration.validate_runtime_configuration()
    monkeypatch.setattr(api, "settings", configuration)
    monkeypatch.setattr(team, "runtime_settings", configuration)
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_keys(self, *, refresh):
            return [SimpleNamespace(key_id="patient-ui", key=signing.public_key())]

    verifier = ClerkTokenVerifier(configuration, jwks_client=Keys(), start_background_refresh=False)
    monkeypatch.setattr(api, "_clerk_verifier", lambda: verifier)
    request_local = local()

    def sessions():
        with Session(engine) as s:
            request_local.session = s
            try:
                yield s
            finally:
                request_local.session = None

    api.app.dependency_overrides[api.get_session] = sessions
    cases, ports = {}, []
    active_case = None
    stack = ExitStack()
    output = Path(os.environ.get("COSMAS_SCHEDULING_FULL_UI_EVIDENCE_DIR", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)

    receiver = SignedWriterReceiver(output)
    stack.callback(receiver.close)
    initial_contract = receiver.call({"action": "handler_contract"})
    assert initial_contract["lookups"] == initial_contract["verifications"] == 0
    assert all(value >= 400 for key, value in initial_contract.items() if key not in {"lookups", "verifications"})
    (output / "receiver-contract.json").write_text(json.dumps({"handler_contract": initial_contract,
        "openapi": receiver.call({"action": "schema_inspect"}), "master_writer": receiver.call({"action": "master_inspect"})}, indent=2) + "\n")

    def record_failure(f, boundary, error):
        chain, item = [], error
        for _ in range(6):
            if item is None:
                break
            chain.append({"type": type(item).__name__, "reason": str(item)[:400]})
            item = item.__cause__ or item.__context__
        f.diagnostics.append({"boundary": boundary, "chain": chain})
        (output / "backend-progress.json").write_text(json.dumps({"synthetic_only": True,
            "cases": [{"workspace_id": value.wid, "diagnostics": value.diagnostics} for value in cases.values()]}, indent=2)+"\n")

    def observe_service(operation):
        def invoke(*args, **kwargs):
            try:
                return operation(*args, **kwargs)
            except Exception as error:
                if active_case is not None:
                    record_failure(active_case, "actual_service_" + operation.__name__, error)
                raise
        return invoke

    monkeypatch.setattr(patient_setup, "preview", observe_service(patient_setup.preview))
    monkeypatch.setattr(patient_setup, "confirm", observe_service(patient_setup.confirm))

    def patient_port():
        assert active_case is not None
        return active_case.port

    def availability_port():
        assert active_case is not None
        return active_case.availability

    # Route the actual fixed-origin adapters into the retained signed service.
    monkeypatch.setattr(patient_port_module, "build_scheduling_patient_setup", patient_port)
    api.app.dependency_overrides[api._scheduling_connection] = availability_port
    api.app.dependency_overrides[api._appointment_connection] = lambda: active_case.appointments
    client = TestClient(api.app)

    def inspect(f) -> CaseEvidence:
        with Session(engine) as s:
            current = ws.read(s, f.box, f.owner, f.wid)
            rows = list(s.scalars(select(Operation).where(Operation.box_id == f.box)))
            return CaseEvidence(workspace=current, receiver_calls=len(f.port.calls), availability_calls=len(f.availability_reads),
                receiver_writes=0, mapping_reviews=int(s.scalar(select(func.count()).select_from(SchedulingPatientMappingReview)
                    .where(SchedulingPatientMappingReview.workspace_id == f.wid)) or 0),
                setup_requests=int(s.scalar(select(func.count()).select_from(SchedulingPatientSetupRequest)
                    .where(SchedulingPatientSetupRequest.workspace_id == f.wid)) or 0),
                proposal_count=int(s.scalar(select(func.count()).select_from(AppointmentWork).where(AppointmentWork.workspace_id == f.wid)) or 0),
                appointment_receipts=int(s.scalar(select(func.count()).select_from(AppointmentReceipt).where(AppointmentReceipt.box_id == f.box)) or 0),
                operations=[OperationEvidence(id=r.id, started=r.started_at is not None, attempt_count=r.attempt_count,
                    external_reference=r.external_reference) for r in rows], diagnostics=f.diagnostics,
                receiver_ledger=receiver.call({"action": "inspect"}), master_writer=receiver.call({"action": "master_inspect"}),
                mapping_patient_id=s.scalar(select(SchedulingPatientAccount.patient_id).where(SchedulingPatientAccount.box_id == f.box)))

    def create_case(persona, iteration):
        nonlocal active_case
        s = stack.enter_context(Session(engine))
        seed = svc.provision_box(svc.Container(s), "Invented patient UI " + persona)
        # Reuse the reviewed invented note and personal-custody fixture. Replace
        # its response fixture entirely with actual signed receiver handlers.
        def selected_account(**values):
            values.update(practice_id=receiver.practice, actor_id=receiver.actor, **receiver.resources)
            return SchedulingAccount(**values)
        with monkeypatch.context() as initial_account:
            initial_account.setattr(patient_fixture_module, "SchedulingAccount", selected_account)
            f = stack.enter_context(contextmanager(unwrap(patient_case))(s, seed, monkeypatch))
        f.diagnostics, f.availability_reads = [], []

        def exchange(request):
            current_session = getattr(request_local, "session", None)
            assert current_session is None or not current_session.in_transaction()
            assert request.url.host == "prepared-scheduling.example.invalid" and "cookie" not in request.headers
            patient = request.url.path.startswith("/v1/companion/patient-correspondence/")
            if patient:
                assert request.method == "POST" and not request.url.query
                f.port.calls.append(request.url.path.rsplit("/", 1)[-1])
            else:
                assert request.method == "GET" and "appointment-operations" not in str(request.url)
                f.availability_reads.append("availability" if request.url.path.endswith("/availability/verified") else "appointment")
            result = receiver.call({"action": "exchange", "method": request.method,
                "path": request.url.raw_path.decode(), "headers": dict(request.headers), "content": request.content.decode()})
            return httpx.Response(result["status"], content=result["content"].encode(), headers=result["headers"])

        adapter = HttpSchedulingPatientSetup("https://prepared-scheduling.example.invalid", lambda _: SecretStr(receiver.token),
            enabled=lambda: True, transport=httpx.MockTransport(exchange))
        f.port = SimpleNamespace(calls=[], patient_id=receiver.patient, preview=adapter.preview, verify=adapter.verify)
        ports.append(adapter)
        identity = s.get(ExternalIdentity, f.identity)
        assert identity is not None
        # Hosted practice admission intentionally requires a Clerk user subject;
        # use the actual reviewed fixture binding with an invented valid subject.
        identity.subject = "user_" + str(uuid4())
        s.commit()
        configuration.clerk_issuer = identity.issuer
        configuration.clerk_jwks_url = identity.issuer + "/.well-known/jwks.json"
        configuration.beta_box_id = f.box
        configuration.validate_runtime_configuration()
        f.configuration, f.persona, f.iteration = configuration, persona, iteration
        account = s.get(SchedulingAccount, f.account)
        assert account is not None
        assert account.practice_id == receiver.practice and account.actor_id == receiver.actor
        assert all(getattr(account, key) == value for key, value in receiver.resources.items())
        appointment = s.get(AppointmentObservation, f.before["appointment_id"])
        assert appointment is not None
        appointment.source, appointment.external_id = "cosmas_scheduling", receiver.remote_appointment
        s.commit()
        subject, issuer = identity.subject, identity.issuer
        selected = team.default_configuration()
        follow = next(bot for bot in selected["bots"] if bot["role"] == "follow_up")
        follow["resources"] = {"version": 1, "allowed": [{"purpose": "scheduling_context",
            "resource_ref": team_resources.reference(f.box, f.owner, f.identity, "scheduling_context", account)}]}
        rehearsal = team_setup.rehearsal(s, f.box, f.owner, f.identity, expected=0, configuration=selected, contract=4)
        team.save(s, f.box, f.owner, expected=0, key=str(uuid4()), configuration=selected,
            setup_review=rehearsal["setup_review"], external_identity_id=f.identity, team_contract=4)
        s.commit()
        f.before = ws.read(s, f.box, f.owner, f.wid)
        s.commit()
        f.availability = HttpSchedulingAvailability("https://prepared-scheduling.example.invalid",
            lambda _: SecretStr(receiver.token), transport=httpx.MockTransport(exchange))
        f.appointments = HttpSchedulingAppointments("https://prepared-scheduling.example.invalid",
            lambda _: SecretStr(receiver.token), execution_allowed=lambda: False, transport=httpx.MockTransport(exchange))
        ports.extend([f.availability, f.appointments])
        cases[f.wid], active_case = f, f
        now = datetime.now(UTC)
        token = jwt.encode(dict(sub=subject, iss=issuer, aud=configuration.clerk_audience,
            sid="invented-patient-ui", azp=ORIGIN, org_id="org_invented", iat=now, nbf=now,
            exp=now+timedelta(minutes=10)), signing, algorithm="RS256", headers={"kid": "patient-ui"})
        s.commit()
        assert not s.in_transaction()
        return dict(token=token, workspace=f.before, dob=None)

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value, headers=None):
            raw = json.dumps(value).encode()
            self.send_response(status)
            for name, value in (headers or {}).items():
                if name.lower() not in {"content-length", "content-encoding", "content-type"}:
                    self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            try:
                parsed = urlsplit(self.path)
                if parsed.path == "/lab/case":
                    q = parse_qs(parsed.query)
                    persona, iteration = q["persona"][0], q["round"][0]
                    assert persona in {"physician", "nurse_practitioner", "physician_assistant"}
                    assert iteration in {"1", "2", "lost_confirmation", "reconnect", "lost_proposal", "source_revoke", "same_name"}
                    return self.respond(200, create_case(persona, iteration))
                if parsed.path == "/lab/inspect":
                    return self.respond(200, inspect(cases[parse_qs(parsed.query)["workspace_id"][0]]))
                r = client.get(self.path, headers=dict(self.headers))
                return self.respond(r.status_code, r.json(), r.headers)
            except Exception as error:
                import traceback
                traceback.print_exc()
                return self.respond(500, {"detail": type(error).__name__ + ": " + str(error)})

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                assert 0 <= size <= 16384
                body = self.rfile.read(size)
                if self.path == "/lab/master":
                    command = json.loads(body)
                    assert set(command) == {"workspace_id", "operation"} and command["operation"] in {"revoke", "restore", "same_name"}
                    receiver.call({"action": "master_change", "operation": command["operation"]})
                    return self.respond(200, inspect(cases[command["workspace_id"]]))
                if self.path == "/lab/reconnect":
                    f = cases[json.loads(body)["workspace_id"]]
                    with Session(engine) as s:
                        credential = s.get(SchedulingLoginCredential, f.account)
                        assert credential is not None
                        credential.connected_at = datetime.now(UTC)
                        f.connected = credential.connected_at
                        s.commit()
                    return self.respond(200, inspect(f))
                r = client.post(self.path, headers=dict(self.headers), content=body)
                return self.respond(r.status_code, r.json(), r.headers)
            except Exception as error:
                import traceback
                traceback.print_exc()
                return self.respond(500, {"detail": type(error).__name__ + ": " + str(error)})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR") if k in os.environ}
    env.update(COSMAS_SCHEDULING_FULL_LAB_URL=f"http://127.0.0.1:{server.server_port}",
        COSMAS_SCHEDULING_FULL_LAB_REPORT=str(output / "ui-server-lab.json"))
    try:
        command = [str(NODE), "node_modules/vitest/vitest.mjs", "run", "src/SchedulingFullWorkspaceServerLab.test.tsx", "--maxWorkers=1"]
        selected_test = os.environ.get("COSMAS_SCHEDULING_FULL_LAB_TEST_NAME")
        if selected_test:
            command.extend(["-t", selected_test])
        result = subprocess.run(command, cwd=REPO / "web", env=env, text=True, capture_output=True, timeout=300)
        (output / "vitest.log").write_text(result.stdout+result.stderr)
        (output / "backend-evidence.json").write_text(json.dumps({"synthetic_only": True,
            "cases": [inspect(f) for f in cases.values()], "vitest_returncode": result.returncode}, indent=2)+"\n")
        assert result.returncode == 0, result.stdout+result.stderr
        report = json.loads((output / "ui-server-lab.json").read_text())
        assert report["completed"] == report["total"] == (1 if selected_test else 11)
        for f in cases.values():
            result = inspect(f)
            assert result["workspace"]["note"] == f.before["note"]
            assert result["workspace"]["entries"] == f.before["entries"]
            assert result["workspace"]["revision"] == f.before["revision"]
            if f.iteration == "source_revoke":
                assert result["mapping_reviews"] == 0 and result["setup_requests"] == result["receiver_calls"] == 2
            else:
                assert result["mapping_reviews"] == 1 and result["setup_requests"] == 2
                assert result["receiver_calls"] == 2
            assert result["receiver_writes"] == result["appointment_receipts"] == 0
            assert result["receiver_ledger"]["appointment_operations"] == result["receiver_ledger"]["calendar_jobs"] == 0
            assert result["master_writer"]["direct_identity_fixture_writes"] == 0
            assert all(not r["started"] and r["attempt_count"] == 0 and r["external_reference"] is None for r in result["operations"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        client.close()
        for port in ports:
            port.close()
        api.app.dependency_overrides.pop(api.get_session, None)
        api.app.dependency_overrides.pop(api._scheduling_connection, None)
        api.app.dependency_overrides.pop(api._appointment_connection, None)
        stack.close()
        (output / "receiver-cleanup.json").write_text(json.dumps({"process_closed": receiver.closed,
            "process_returncode": receiver.process.returncode, "server_thread_stopped": not thread.is_alive()}, indent=2) + "\n")
