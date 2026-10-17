"""Signed, mounted patient correspondence and hosted proposal UI, synthetic only."""

import json
import os
import shutil
import subprocess
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from inspect import unwrap
from pathlib import Path
from threading import Thread, local
from types import SimpleNamespace
from typing import Any, TypedDict
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_scheduling_patient_setup import case as patient_case
from tests.unit.test_hosted_workspace_config import hosted

from cosmas_os.adapters.scheduling import HttpSchedulingAvailability
from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import provider_team as team
from cosmas_os.application import scheduling_patient_setup as patient_setup
from cosmas_os.application import services as svc
from cosmas_os.application import team_resources, team_setup
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentReceipt,
    AppointmentWork,
    ExternalIdentity,
    Operation,
    SchedulingAccount,
)
from cosmas_os.ports import scheduling_patient_setup as patient_port_module
from cosmas_os.ports.scheduling_actions import build_scheduling_appointments
from cosmas_os.scheduling_login_models import SchedulingLoginCredential
from cosmas_os.scheduling_patient_models import (
    SchedulingPatientMappingReview,
    SchedulingPatientSetupRequest,
)

NODE = Path(shutil.which("node") or "node")
REPO = Path(__file__).resolve().parents[2]
ORIGIN = "https://workspace.example.invalid"


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


def test_signed_patient_setup_ui_and_unsubmitted_hosted_proposals(engine, monkeypatch, tmp_path):
    """Actual product auth/routes/DB/React/crypto; only receiver identities and I/O are invented."""
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
    output = Path(os.environ.get("COSMAS_PATIENT_UI_EVIDENCE_DIR", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)

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

    # Patient routes invoke the captured factory directly, not Depends. Inject
    # the invented receiver at that explicit factory, as a test-only boundary.
    monkeypatch.setattr(patient_port_module, "build_scheduling_patient_setup", patient_port)
    api.app.dependency_overrides[api._scheduling_connection] = availability_port
    api.app.dependency_overrides[api._appointment_connection] = build_scheduling_appointments
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
                    external_reference=r.external_reference) for r in rows], diagnostics=f.diagnostics)

    def create_case(persona, iteration):
        nonlocal active_case
        s = stack.enter_context(Session(engine))
        seed = svc.provision_box(svc.Container(s), "Invented patient UI " + persona)
        # Reuse the real custody fixture's invented receiver and reviewed note,
        # using an independently committed Session so HTTP requests see it.
        f = stack.enter_context(contextmanager(unwrap(patient_case))(s, seed, monkeypatch))
        f.diagnostics = []
        invented = f.port

        class ObservedReceiver:
            calls = invented.calls

            def preview(self, *args):
                try:
                    return invented.preview(*args)
                except Exception as error:
                    record_failure(f, "invented_receiver_preview", error)
                    raise

            def verify(self, *args):
                try:
                    return invented.verify(*args)
                except Exception as error:
                    record_failure(f, "invented_receiver_verify", error)
                    raise

        f.port = ObservedReceiver()
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
        account_values = {k: getattr(account, k) for k in ("practice_id", "actor_id", "practitioner_id", "location_id", "appointment_type_id")}
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
        f.availability_reads = []
        f.slot = None
        connection_id = str(uuid4())

        def respond(request):
            assert request.method == "GET" and request.url.host == "scheduling.example.invalid"
            assert request.url.path.endswith("/availability/verified") and "appointment-operations" not in str(request.url)
            current_session = getattr(request_local, "session", None)
            assert current_session is None or not current_session.in_transaction()
            f.availability_reads.append(request.url.path)
            now = datetime.now(UTC)
            starts = datetime.fromisoformat(request.url.params["from"])
            ends = datetime.fromisoformat(request.url.params["to"])
            slot_start = starts if ends - starts <= timedelta(hours=1) else starts + timedelta(days=2, hours=10)
            slot_end = ends if ends - starts <= timedelta(hours=1) else slot_start + timedelta(minutes=30)
            if f.slot is None:
                f.slot = {"starts_at": slot_start.isoformat(), "ends_at": slot_end.isoformat()}
            value = dict(contract_version="1", request_nonce=request.url.params["requestNonce"],
                practice_id=account_values["practice_id"], actor_id=account_values["actor_id"], practitioner_id=account_values["practitioner_id"],
                location_id=account_values["location_id"], appointment_type_id=account_values["appointment_type_id"],
                range_start=starts.isoformat(), range_end=ends.isoformat(),
                google=dict(provider="google", calendar_id="primary", connection_id=connection_id,
                    connected_at=(now-timedelta(days=1)).isoformat(), checked_at=now.isoformat()),
                slots=[dict(starts_at=slot_start.isoformat(), ends_at=slot_end.isoformat())])
            return httpx.Response(200, json=value, headers={"Content-Type": "application/json", "Cache-Control": "no-store"})

        f.availability = HttpSchedulingAvailability("https://scheduling.example.invalid",
            lambda _selection: SecretStr("invented-qualified-read-only-staff-token"), transport=httpx.MockTransport(respond))
        ports.append(f.availability)
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
                    assert iteration in {"1", "2", "lost_confirmation", "reconnect"}
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
    env.update(COSMAS_PATIENT_LAB_URL=f"http://127.0.0.1:{server.server_port}",
        COSMAS_PATIENT_LAB_REPORT=str(output / "ui-server-lab.json"))
    try:
        command = [str(NODE), "node_modules/vitest/vitest.mjs", "run", "src/SchedulingPatientUiServerLab.test.tsx", "--maxWorkers=1"]
        selected_test = os.environ.get("COSMAS_PATIENT_LAB_TEST_NAME")
        if selected_test:
            command.extend(["-t", selected_test])
        result = subprocess.run(command, cwd=REPO / "web", env=env, text=True, capture_output=True, timeout=300)
        (output / "vitest.log").write_text(result.stdout+result.stderr)
        (output / "backend-evidence.json").write_text(json.dumps({"synthetic_only": True,
            "cases": [inspect(f) for f in cases.values()], "vitest_returncode": result.returncode}, indent=2)+"\n")
        assert result.returncode == 0, result.stdout+result.stderr
        report = json.loads((output / "ui-server-lab.json").read_text())
        assert report["completed"] == report["total"] == (1 if selected_test else 8)
        for f in cases.values():
            result = inspect(f)
            assert result["workspace"]["note"] == f.before["note"]
            assert result["workspace"]["entries"] == f.before["entries"]
            assert result["workspace"]["revision"] == f.before["revision"]
            assert result["mapping_reviews"] == 1 and result["setup_requests"] == 2
            assert result["receiver_calls"] == 2 and result["receiver_writes"] == result["appointment_receipts"] == 0
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
