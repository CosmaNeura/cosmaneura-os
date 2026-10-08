"""Real signed private metadata, exact lost-reply recovery and patient-link guards."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from tests.integration.test_private_workspace_drafts import appointment
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.api import app as api
from cosmas_os.application import provider_team
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import new_capture_session
from cosmas_os.models import PatientLink, WorkspaceAppointmentLink
from cosmas_os.private_recording_models import (
    PrivateRecording,
    PrivateRecordingFinish,
    PrivateRecordingLink,
)

signed_workspace = _signed_workspace


@pytest.fixture
def recording(signed_workspace, session):
    f = signed_workspace
    draft = ws.create_private_draft(session, f.box, f.actor, "Invented private audio", "private-audio-notebook")
    provider_team.save(session, f.box, f.actor, expected=0, key="private-audio-team",
        configuration=provider_team.starter_configuration(f.box, f.actor))
    now = datetime.now(UTC) - timedelta(seconds=2)
    body = {"idempotency_key": str(uuid4()), "local_recording_id": str(uuid4()),
        "expected_workspace_revision": draft["revision"], "bot": {"address": "scribe", "team_revision": 1},
        "started_at": now.isoformat(), "consent": {"modality": "in_person", "participant_regions": [],
        "method": "verbal_attestation", "all_parties_consented": True, "granted_at": now.isoformat()}}
    previous = api.app.dependency_overrides[api.get_session]
    factory = sessionmaker(bind=session.get_bind(), autoflush=False)
    def owned_session():
        with new_capture_session(factory) as current:
            yield current
    api.app.dependency_overrides[api.get_session] = owned_session
    try:
        yield f, draft, body
    finally:
        api.app.dependency_overrides[api.get_session] = previous


def headers(f):
    return {"Authorization": "Bearer " + f.token(), "X-Cosmas-Private-Recording": "1"}


def base(draft):
    return f"/workspaces/{draft['id']}/private-recordings"


def post(f, path, body):
    return f.client.post(path, headers=headers(f), json=body)


def attached(recording):
    f, draft, body = recording
    response = post(f, base(draft), body)
    assert response.status_code == 200, response.text
    return f, draft, body, response.json()


def finish_body():
    return {"idempotency_key": str(uuid4()), "capture_state": "finished",
        "manifest_sha256": "a" * 64, "chunks": 1, "frames": 16000,
        "ended_at": datetime.now(UTC).isoformat()}


def test_attach_after_local_start_and_lost_reply_resolve_exact(recording, session):
    f, draft, body, row = attached(recording)
    assert row["state"] == "unfinished" and row["custody"] == "local_device_metadata"
    assert row["local_recording_id"] == body["local_recording_id"] and row["recording_id"] != body["local_recording_id"]
    assert row["audio_uploaded"] is False and row["upstream_capture_admitted"] is False
    assert post(f, base(draft), body).json() == row
    resolved = post(f, base(draft) + "/resolve", body)
    assert resolved.status_code == 200 and resolved.json() == {"outcome": "saved", "recording": row}
    assert session.scalar(select(func.count()).select_from(PrivateRecording)) == 1
    assert post(f, base(draft), {**body, "expected_workspace_revision": 2}).status_code == 409
    assert post(f, base(draft), {**body, "idempotency_key": str(uuid4())}).status_code == 409


def test_desktop_closed_proxy_posts_canonical_metadata_to_actual_signed_asgi(recording, session):
    import json
    import shutil
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pathlib import Path

    from cosmas_os.application.private_recording import digest
    from cosmas_os.ports.private_recording import AttachRecording

    f, draft, body = recording
    command = AttachRecording.model_validate(body)
    wire = command.model_dump(mode="json")
    expected = digest("attach", command)
    token = f.token()
    received = []
    class Bridge(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            received.append({"path": self.path, "contract": self.headers.get("X-Cosmas-Private-Recording"),
                "wire": json.loads(raw), "authorization_bound": self.headers.get("Authorization") == "Bearer " + token})
            response = f.client.post(self.path, content=raw, headers={
                "Authorization": self.headers["Authorization"], "Content-Type": "application/json",
                "X-Cosmas-Private-Recording": self.headers["X-Cosmas-Private-Recording"],
                "X-Cosmas-Draft-Recovery": "2"})
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)
        def log_message(self, *_):
            pass
    server = HTTPServer(("127.0.0.1", 0), Bridge)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = """
      import {proxyAuthenticatedWorkspaceRequest} from './clients/desktop/workspace-auth-proxy.mjs';
      let input='';for await(const part of process.stdin)input+=part;const v=JSON.parse(input);
      const ready={phase:'ready',revision:v.revision,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
      let tokens=0,calls=0;const auth={getState:async()=>ready,snapshot:()=>ready,subscribe:()=>()=>{},getToken:async()=>{tokens++;return v.token;}};
      const request=new Request('app://cosmas/api'+v.path,{method:'POST',body:JSON.stringify(v.body),headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':v.revision,'X-Cosmas-Private-Recording':'1','X-Cosmas-Draft-Recovery':'2'}});
      const response=await proxyAuthenticatedWorkspaceRequest(request,auth,async(url,options)=>{calls++;if(url!=='http://127.0.0.1:8046'+v.path)throw Error('unexpected endpoint');return fetch(v.loopback+v.path,options);});
      const body=await response.json();process.stdout.write(JSON.stringify({status:response.status,body,tokens,calls}));
    """
    try:
        node = shutil.which("node")
        if node is None:
            pytest.fail("Node is required to qualify the actual desktop proxy")
        result = subprocess.run([node, "--input-type=module", "-e", script],
            cwd=Path(__file__).parents[2], input=json.dumps({"token": token, "path": base(draft),
                "body": wire, "revision": str(uuid4()), "loopback": "http://127.0.0.1:" + str(server.server_port)}),
            text=True, capture_output=True, timeout=20, check=True)
        reply = json.loads(result.stdout)
        assert reply["status"] == 200 and reply["tokens"] == reply["calls"] == 1
        assert reply["body"]["attach_sha256"] == expected
        assert reply["body"]["audio_uploaded"] is False
        assert received == [{"path": base(draft), "contract": "1", "wire": wire, "authorization_bound": True}]
        assert session.scalar(select(func.count()).select_from(PrivateRecording)) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_wrong_owner_workspace_and_revoked_identity_withhold(recording, session):
    f, draft, body, row = attached(recording)
    assert f.client.get(base(draft) + "/" + row["recording_id"], headers=headers(f)).status_code == 200
    assert f.client.get(f"/workspaces/{f.workspace['id']}/private-recordings/{row['recording_id']}", headers=headers(f)).status_code in {404, 409}
    f.binding.active = False
    session.commit()
    assert f.client.get(base(draft) + "/" + row["recording_id"], headers=headers(f)).status_code == 403
    assert post(f, base(draft), body).status_code == 403


def test_finish_exact_replay_and_changed_manifest_refusal(recording, session):
    f, draft, _, row = attached(recording)
    path = base(draft) + "/" + row["recording_id"]
    body = finish_body()
    response = post(f, path + "/finish", body)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "finished"
    assert post(f, path + "/finish", body).json() == response.json()
    assert post(f, path + "/finish", {**body, "manifest_sha256": "b" * 64}).status_code == 409
    assert session.scalar(select(func.count()).select_from(PrivateRecordingFinish)) == 1


def test_unknown_remains_explicit_and_never_becomes_linked(recording, session):
    f, draft, _, row = attached(recording)
    path = base(draft) + "/" + row["recording_id"]
    unknown = {"idempotency_key": str(uuid4()), "capture_state": "unknown"}
    response = post(f, path + "/finish", unknown)
    assert response.status_code == 200 and response.json()["state"] == "unknown"
    assert response.json()["finish"]["manifest_sha256"] is None
    a = appointment(session, f)
    linked = ws.link_appointment(session, f.box, f.actor, draft["id"], expected=1,
        key="unknown-private-audio-link", appointment=a.id, confirmed=True)
    assert post(f, path + "/link", {"idempotency_key": str(uuid4()),
        "expected_workspace_revision": 2, "workspace_link_receipt_id": linked["link_receipt_id"]}).status_code == 409
    assert session.scalar(select(func.count()).select_from(PrivateRecordingLink)) == 0


def test_link_uses_exact_reviewed_appointment_receipt_and_preserves_origin(recording, session):
    f, draft, _, row = attached(recording)
    path = base(draft) + "/" + row["recording_id"]
    assert post(f, path + "/finish", finish_body()).status_code == 200
    wrong = {"idempotency_key": str(uuid4()), "expected_workspace_revision": 1,
             "workspace_link_receipt_id": str(uuid4())}
    assert post(f, path + "/link", wrong).status_code == 409
    a = appointment(session, f)
    linked = ws.link_appointment(session, f.box, f.actor, draft["id"], expected=1,
        key="private-recording-appointment-link", appointment=a.id, confirmed=True)
    command = {"idempotency_key": str(uuid4()), "expected_workspace_revision": 2,
               "workspace_link_receipt_id": linked["link_receipt_id"]}
    response = post(f, path + "/link", command)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "linked_metadata" and response.json()["upstream_capture_admitted"] is False
    assert response.json()["attach_sha256"] == row["attach_sha256"]
    assert post(f, path + "/link", command).json() == response.json()
    assert session.scalar(select(func.count()).select_from(WorkspaceAppointmentLink)) == 1
    assert session.scalar(select(func.count()).select_from(PrivateRecordingLink)) == 1
    patient = session.get(PatientLink, a.patient_link_id)
    patient.revoked_at = datetime.now(UTC)
    session.commit()
    assert f.client.get(path, headers=headers(f)).status_code == 404


def test_team_change_cannot_reuse_old_recording_scope(recording, session):
    f, draft, _, row = attached(recording)
    provider_team.save(session, f.box, f.actor, expected=1, key="private-audio-team-revision",
        configuration=provider_team.starter_configuration(f.box, f.actor))
    assert f.client.get(base(draft) + "/" + row["recording_id"], headers=headers(f)).status_code == 409


def test_sql_finish_null_outcome_is_rejected(recording, session):
    _, _, _, row = attached(recording)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("INSERT INTO private_recording_finishes "
            "(id, recording_id, request_key, request_sha256, capture_state, manifest_sha256, request) "
            "VALUES (:id, :recording, :key, :sha, 'finished', :sha, '{}'::jsonb)"),
            {"id": str(uuid4()), "recording": row["recording_id"], "key": str(uuid4()), "sha": "a" * 64})


def test_missing_contract_and_client_patient_authority_refused(recording):
    f, draft, body = recording
    assert f.client.post(base(draft), headers={"Authorization": "Bearer " + f.token()}, json=body).status_code == 426
    assert post(f, base(draft), {**body, "patient_id": str(uuid4())}).status_code == 422
    assert post(f, base(draft), {**body, "wrapped_dek": "secret"}).status_code == 422


def test_missing_identity_cannot_take_over_local_recording(recording, session):
    f, draft, body, row = attached(recording)
    from cosmas_os.application import private_recording
    with pytest.raises(ws.WorkspaceError, match="private_recording_access_denied"):
        private_recording.read(session, f.box, f.actor, draft["id"], row["recording_id"], external=str(uuid4()))
    assert post(f, base(draft), {**body, "bot": {"address": "chief", "team_revision": 1},
        "idempotency_key": str(uuid4()), "local_recording_id": str(uuid4())}).status_code == 409


def test_resolve_not_found_before_attach_and_interrupted_finish(recording):
    f, draft, body = recording
    result = post(f, base(draft) + "/resolve", body)
    assert result.status_code == 200 and result.json() == {"outcome": "not_found", "recording": None}
    row = post(f, base(draft), body).json()
    finished = post(f, base(draft) + "/" + row["recording_id"] + "/finish",
        {**finish_body(), "capture_state": "interrupted"})
    assert finished.status_code == 200 and finished.json()["state"] == "interrupted"


def test_new_migration_installs_all_immutable_receipts_and_refuses_erasure(recording, session):
    import importlib.util
    from pathlib import Path

    from sqlalchemy.exc import DBAPIError

    f, draft, _, row = attached(recording)
    path = base(draft) + "/" + row["recording_id"]
    assert post(f, path + "/finish", finish_body()).status_code == 200
    a = appointment(session, f)
    linked = ws.link_appointment(session, f.box, f.actor, draft["id"], expected=1,
        key="immutable-private-audio-link", appointment=a.id, confirmed=True)
    assert post(f, path + "/link", {"idempotency_key": str(uuid4()),
        "expected_workspace_revision": 2, "workspace_link_receipt_id": linked["link_receipt_id"]}).status_code == 200
    connection = session.connection()
    name = "private_recording_migration"
    file = Path(__file__).parents[2] / "migrations/versions/f96b1c4d2357_private_recordings.py"
    spec = importlib.util.spec_from_file_location(name, file)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    installed = []
    class Operations:
        def execute(self, statement):
            calls.append(statement)
            if statement.startswith("CREATE TRIGGER"):
                name = statement.split()[2]
                if not connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname=:name)"), {"name": name}):
                    connection.execute(text(statement))
                    installed.append(name)
        def get_bind(self):
            return session.connection()
    module.__dict__["op"] = Operations()
    try:
        module.upgrade()
        assert len([call for call in calls if "CREATE TABLE" in call]) == 3
        for table in ("private_recordings", "private_recording_finishes", "private_recording_links"):
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(text("DELETE FROM " + table))
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(text("UPDATE " + table + " SET request_sha256=repeat('b',64)"))
        with pytest.raises(RuntimeError, match="cannot be erased"):
            module.downgrade()
    finally:
        for table in ("private_recordings", "private_recording_finishes", "private_recording_links"):
            if table + "_immutable" in installed:
                connection.execute(text("DROP TRIGGER " + table + "_immutable ON " + table))
