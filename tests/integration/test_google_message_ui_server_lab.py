"""Mounted email-to-Chief work through signed APIs and actual DB/tool services."""

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration.test_google_message import InventedGoogle

from cosmas_os.adapters.gpt41 import _context
from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import google_calendar as calendars
from cosmas_os.application import google_message as messages
from cosmas_os.application import model_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team_service
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.google_connection_models import GoogleConnectionCredential
from cosmas_os.models import (
    AppointmentObservation,
    ExternalIdentity,
    ModelWorkAdmission,
    PatientLink,
)
from cosmas_os.ports.google_calendar import (
    GoogleCalendarAccount,
    GoogleCalendarBinding,
    GoogleCalendarEvent,
    GoogleCalendarObservation,
    GoogleCalendarRead,
)

NODE = Path("/Users/jw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
REPO = Path(__file__).resolve().parents[2]


def test_actual_signed_email_ui_runs_six_source_chief_revision_acceptance_loops(
    engine, monkeypatch, tmp_path
):
    run_signed_selected_source_ui_lab(engine, monkeypatch, tmp_path)


def run_signed_selected_source_ui_lab(engine, monkeypatch, tmp_path, *, source_kind="email", full_workspace=False):
    assert source_kind in {"email", "calendar"}
    calendar_lab = source_kind == "calendar"
    assert NODE.is_file()
    with Session(engine) as session:
        seed = svc.provision_box(svc.Container(session), "Invented email UI practice")
        box, owner = seed["box_id"], seed["owner_id"]
        issuer = f"https://clerk-{uuid4().hex}.example.invalid"
        account = ExternalIdentity(
            box_id=box,
            principal_id=owner,
            issuer=issuer,
            subject="invented-email-owner",
            organization_id="org_invented",
            reviewed_by="Invented owner",
            evidence_ref="test:synthetic-signed-ui",
        )
        session.add(account)
        session.flush()
        connected = datetime.now(UTC)
        session.add(
            GoogleConnectionCredential(
                account_id=account.id,
                binding_digest="a" * 64,
                status="ready",
                sealed=b"i" * 40,
                connected_at=connected,
                expires_at=connected + timedelta(hours=1),
            )
        )
        account_id = account.id
        session.commit()
        team_snapshot = team_service.save(
            session,
            box,
            owner,
            expected=0,
            key="ui-team",
            configuration=team_service.default_configuration(),
        )
    configuration = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue] -- BaseSettings runtime option.
        workspace_enabled=True,
        workspace_authenticated_enabled=True,
        auth_mode="clerk_jwt",
        synth_seed=False,
        clerk_issuer=issuer,
        clerk_jwks_url=issuer + "/.well-known/jwks.json",
        clerk_audience="cosmas-email-ui",
        clerk_organization_id="org_invented",
        clerk_authorized_parties="http://localhost:5173",
        beta_box_id=box,
        cors_allowed_origins="http://localhost:5173",
        workspace_google_connection_enabled=True,
        workspace_google_message_enabled=True,
        workspace_google_calendar_enabled=calendar_lab,
    )
    assert configuration.runtime_configuration_errors() == []
    monkeypatch.setattr(api, "settings", configuration)
    runtime = work.team.runtime_settings
    for key, value in {
        "workspace_enabled": True,
        "workspace_authenticated_enabled": True,
        "auth_mode": "clerk_jwt",
        "synth_seed": False,
        "clerk_issuer": issuer,
        "clerk_jwks_url": issuer + "/.well-known/jwks.json",
        "clerk_audience": configuration.clerk_audience,
        "clerk_organization_id": "org_invented",
        "clerk_authorized_parties": "http://localhost:5173",
        "beta_box_id": box,
        "workspace_google_connection_enabled": True,
        "workspace_google_message_enabled": True,
        "workspace_google_calendar_enabled": calendar_lab,
        "workspace_llm_backend": "azure_gpt41",
        "workspace_llm_api_key": SecretStr("invented-model-no-network"),
        "workspace_agent_tools_enabled": True,
    }.items():
        monkeypatch.setattr(runtime, key, value)
    assert runtime.workspace_llm_available and runtime.workspace_google_message_available
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class LocalJwks:
        def get_signing_keys(self, *, refresh):
            return [SimpleNamespace(key_id="invented-ui-key", key=signing_key.public_key())]

    verifier = ClerkTokenVerifier(
        configuration, jwks_client=LocalJwks(), start_background_refresh=False
    )
    monkeypatch.setattr(api, "_clerk_verifier", lambda: verifier)

    def token():
        now = datetime.now(UTC)
        return jwt.encode(
            dict(
                sub="invented-email-owner",
                iss=issuer,
                aud=configuration.clerk_audience,
                sid="invented-ui-session",
                azp="http://localhost:5173",
                org_id="org_invented",
                iat=now,
                nbf=now,
                exp=now + timedelta(minutes=10),
            ),
            signing_key,
            algorithm="RS256",
            headers={"kid": "invented-ui-key"},
        )

    class Google:
        def __init__(self):
            self.calls = []

        def message_binding(self, identity, *, require_full=False, session=None):
            assert session is not None
            credential = session.get(GoogleConnectionCredential, account_id, populate_existing=True)
            if (credential is None or credential.status != "ready" or credential.sealed is None
                    or credential.expires_at <= datetime.now(UTC)):
                raise ws.WorkspaceError("google_message_grant_unavailable")
            return InventedGoogle(session, account_id, connected).message_binding(
                identity, require_full=require_full, session=session
            )

        def message_status(self, identity, *, session=None):
            self.message_binding(identity, session=session)
            return dict(
                contract_version=1,
                state="connected",
                full_mail_read=True,
                account={"label": "Invented UI account", "email": "owner@example.invalid"},
            )

        def status(self, identity, *, include_capabilities=False):
            with Session(engine) as session:
                credential = session.get(GoogleConnectionCredential, account_id, populate_existing=True)
                ready = credential is not None and credential.status == "ready" and credential.sealed is not None
            value = dict(state="connected" if ready else "sign_in_required",
                         account=dict(label="Invented UI account", email="owner@example.invalid") if ready else None,
                         connected_at=connected.isoformat() if ready else None)
            if include_capabilities:
                value["capabilities"] = dict(mail=ready, calendar=ready and calendar_lab)
            return value

        def mail(self, identity):
            self.calls.append("list")
            now = datetime.now(UTC).isoformat()
            return dict(
                kind="mail",
                account={"label": "Invented UI account", "email": "owner@example.invalid"},
                items=[
                    dict(
                        id="invented-ui-message",
                        subject="Invented visit follow-up",
                        sender="sender@example.invalid",
                        received_at=now,
                        is_read=False,
                    )
                ],
                more=False,
                observed_at=now,
            )

        def read_message(self, identity, selection):
            self.calls.append("read")
            with Session(engine) as session:
                port = InventedGoogle(session, account_id, connected)
                port.text = "Subject: Invented visit follow-up\nFrom: sender@example.invalid\n\nInvented administrative request: please prepare follow-up work. Heart history and trial eligibility are unconfirmed. DOB unavailable. No sending or clinical decision requested."
                return port.read_message(identity, selection)

        def calendar_binding(self, identity, *, session=None):
            assert session is not None
            credential = session.get(GoogleConnectionCredential, account_id, populate_existing=True)
            if (credential is None or credential.status != "ready" or credential.sealed is None
                    or credential.expires_at <= datetime.now(UTC)):
                raise ws.WorkspaceError("google_calendar_grant_unavailable")
            assert identity.external_identity_id == account_id
            return GoogleCalendarBinding(account_id=account_id, binding_digest="a" * 64,
                                         connected_at=connected, grant_sha256="d" * 64)

        def calendar_status(self, identity, *, session=None):
            self.calendar_binding(identity, session=session)
            return dict(contract_version=1, state="connected", calendar_read=True,
                        account={"label": "Invented UI account", "email": "owner@example.invalid"})

        def calendar_observation(self, identity, *, window):
            self.calls.append("calendar")
            now = datetime.now(UTC)
            day = (now + timedelta(days=3)).date()
            observation = GoogleCalendarObservation(kind="calendar",
                account=GoogleCalendarAccount(label="Invented UI account", email="owner@example.invalid"),
                items=(
                    GoogleCalendarEvent(id="invented-timed", subject="Invented visit follow-up",
                        starts_at=(now + timedelta(hours=2)).isoformat(),
                        ends_at=(now + timedelta(hours=3)).isoformat(), all_day=False, cancelled=False),
                    GoogleCalendarEvent(id="invented-allday", subject="Invented all-day follow-up",
                        starts_at=day.isoformat(), ends_at=(day + timedelta(days=1)).isoformat(),
                        all_day=True, cancelled=False),
                    GoogleCalendarEvent(id="invented-cancelled", subject="Invented cancelled follow-up",
                        starts_at=(now + timedelta(hours=4)).isoformat(),
                        ends_at=(now + timedelta(hours=5)).isoformat(), all_day=False, cancelled=True),
                ), more=True, observed_at=now, window=window)
            with Session(engine) as session:
                return GoogleCalendarRead(observation=observation,
                    custody=self.calendar_binding(identity, session=session))

    google = Google()
    monkeypatch.setattr(api.app.state, "google_connection", google, raising=False)
    original_dispatch = work.dispatch_claim
    rounds = []
    cases = {}

    def dispatch(claim):
        context = _context(claim.envelope["context"])
        prefix = "Google calendar:" if calendar_lab else "Google message:"
        source = next(p for p in context.sources if p.label.startswith(prefix))

        def provider(request):
            body = json.loads(request.content)
            assert body["store"] is False and body["model"] == "gpt-4.1"
            rounds.append(
                dict(
                    admission_id=claim.admission_id,
                    role=context.role,
                    source_entry_id=source.entry_id,
                )
            )
            if not any(m["role"] == "tool" for m in body["messages"]):
                handle = next(
                    p
                    for p in claim.envelope["tool_selection"]["sources"]
                    if p["entry_id"] == source.entry_id
                )
                value = dict(
                    model="gpt-4.1",
                    usage={"prompt_tokens": 100, "completion_tokens": 20},
                    choices=[
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "read_google",
                                        "type": "function",
                                        "function": {
                                            "name": "read_selected_source",
                                            "arguments": json.dumps(
                                                {
                                                    k: handle[k]
                                                    for k in ("entry_id", "revision", "sha256")
                                                }
                                            ),
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                )
            else:
                tool = json.loads(
                    next(m["content"] for m in body["messages"] if m["role"] == "tool")
                )
                assert (
                    tool["data"]["content"] == source.content
                    and tool["receipt"]["actor_agent_id"] != owner
                )
                if context.role == "chief":
                    content = {
                        "answer": "Preparing a private draft from the human-reviewed " + source_kind + ".",
                        "source_ids": [source.entry_id],
                        "handoffs": [
                            {
                                "role": "scribe",
                                "intended_role": "scribe",
                                "brief": "Organize a private follow-up draft from the reviewed " + source_kind + "; keep uncertainty explicit.",
                                "requirements": REQUIREMENTS,
                            }
                        ],
                    }
                    if claim.envelope["baseline"]["flags"]["work_status"]:
                        content["intent"] = "conversation"
                else:
                    needs = ["Who owns the next step and when should the clinician review it?"]
                    marker = "Human-requested revision of the prior private draft\n"
                    if marker in context.question:
                        metadata = json.loads(
                            context.question.split(marker, 1)[1].split(
                                "\nTreat the quoted prior draft", 1
                            )[0]
                        )
                        needs.append(metadata["feedback"])
                    content = {
                        "excerpts": [{"source_id": source.entry_id, "quote": source.content}],
                        "needs_from_clinician": needs,
                    }
                value = dict(
                    model="gpt-4.1",
                    usage={"prompt_tokens": 150, "completion_tokens": 30},
                    choices=[
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": json.dumps(content)},
                        }
                    ],
                )
            return httpx.Response(200, json=value)

        return original_dispatch(
            claim, session_factory=lambda: Session(engine), transport=httpx.MockTransport(provider)
        )

    monkeypatch.setattr(work, "dispatch_claim", dispatch)

    def sessions():
        with Session(engine) as session:
            yield session

    api.app.dependency_overrides[api.get_session] = sessions
    client = TestClient(api.app)

    def current(case):
        with Session(engine) as session:
            return work.project_workspace(session, ws.read(session, box, owner, case["wid"]))

    def inspect_case(case):
        counters = dict(provider_calls=len(google.calls), model_rounds=len(rounds))
        if "revoked_counts" in case:
            case.setdefault("inspection_counts", []).append(counters)
        return {**counters, "workspace": current(case)}

    def run_tasks(case, hid=None):
        for _ in range(3):
            with Session(engine) as session:
                candidates = list(
                    session.scalars(
                        select(ModelWorkAdmission)
                        .where(
                            ModelWorkAdmission.workspace_id == case["wid"],
                            ModelWorkAdmission.state == "reserved",
                        )
                        .order_by(ModelWorkAdmission.admitted_at)
                    )
                )
                if not candidates:
                    break
                row = candidates[0]
                if hid is not None:
                    snapshot = ws.read(session, box, owner, case["wid"])
                    target = next(h for h in snapshot["handoffs"] if h["id"] == hid)
                    row = next(
                        r for r in candidates if r.handoff_attempt_id == target["attempt_id"]
                    )
                claim = work.claim(session, box, owner, row.id)
            assert claim is not None
            result = dispatch(claim)
            with Session(engine) as session:
                work.settle(session, claim, result)
            if hid is not None:
                break
        snapshot = current(case)
        with Session(engine) as session:
            diagnostics = [
                dict(
                    kind=row.kind,
                    state=row.state,
                    reason=row.reason,
                    handoff_attempt_id=row.handoff_attempt_id,
                )
                for row in session.scalars(
                    select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == case["wid"])
                )
            ]
        case["diagnostics"] = diagnostics
        assert snapshot["handoffs"] and any(
            h["status"] == "completed" for h in snapshot["handoffs"]
        ), diagnostics
        return snapshot

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value):
            raw = json.dumps(value).encode()
            self.send_response(status)
            for k, v in {
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "Content-Length": str(len(raw)),
            }.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def worker_diagnostic(self, case, error):
            with Session(engine) as session:
                admissions = [dict(kind=row.kind, state=row.state, reason=row.reason)
                    for row in session.scalars(select(ModelWorkAdmission).where(
                        ModelWorkAdmission.workspace_id == case["wid"],
                        ModelWorkAdmission.box_id == box, ModelWorkAdmission.owner_id == owner,
                    ))]
            diagnostic = dict(detail="synthetic_worker_failed", error_type=type(error).__name__,
                              case_round=case["round"], diagnostics=admissions)
            case["worker_failure"] = diagnostic
            return diagnostic

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/lab/case":
                params = parse_qs(parsed.query)
                persona, iteration = params.get("persona", [""])[0], params.get("round", [""])[0]
                if persona not in {
                    "physician",
                    "nurse_practitioner",
                    "physician_assistant",
                } or iteration not in {"1", "2", "masked_source", "masked_handoff", "masked_revised_handoff", "revoked_accepted"} or (
                    (iteration.startswith("masked_") or iteration == "revoked_accepted") and persona != "physician"
                ):
                    return self.respond(422, {"detail": "invalid invented case"})
                with Session(engine) as session:
                    if (iteration.startswith("masked_") or iteration == "revoked_accepted"):
                        # Explicit invented fixture setup between terminal episodes only.
                        # This never runs during reconciliation of a lost review reply.
                        credential = session.get(GoogleConnectionCredential, account_id)
                        assert credential is not None
                        credential.status, credential.sealed = "ready", b"i" * 40
                        credential.expires_at = datetime.now(UTC) + timedelta(hours=1)
                    link = PatientLink(
                        box_id=box,
                        source_pair_key="ui-email:" + str(uuid4()),
                        label=(f"Invented {source_kind} visit {persona} {iteration}" if full_workspace else "Invented email visit"),
                        state="confirmed",
                        confirmed_by_principal_id=owner,
                        attested_at=datetime.now(UTC),
                    )
                    session.add(link)
                    session.flush()
                    appointment = AppointmentObservation(
                        box_id=box,
                        patient_link_id=link.id,
                        external_id=str(uuid4()),
                        source="synthetic",
                        start_at=datetime.now(UTC),
                        patient_label=link.label,
                    )
                    session.add(appointment)
                    session.commit()
                    initial = ws.create(
                        session, box, owner, appointment.id, "ui-email-workspace:" + str(uuid4())
                    )
                    saved = notes.save(
                        session,
                        box,
                        owner,
                        initial["id"],
                        expected=1,
                        key="existing-clinical-note",
                        base_note_id=None,
                        source_reply_id=None,
                        content="Invented previously reviewed clinical note; leave this note unchanged.",
                    )["workspace"]
                    n = saved["note"]["latest"]
                    reviewed = notes.review(
                        session,
                        box,
                        owner,
                        initial["id"],
                        n["id"],
                        expected=saved["revision"],
                        key="existing-note-review",
                        content_hash=n["content_hash"],
                        source_hash=n["source_fingerprint"],
                    )["workspace"]
                    case = {
                        "wid": initial["id"],
                        "note": reviewed["note"],
                        "persona": persona,
                        "round": iteration,
                    }
                    if calendar_lab:
                        # Prior reviewed email is independently retained evidence, never
                        # re-read by the calendar action or silently imported into the note.
                        existing = messages.list_observed(session, box, owner, account_id,
                            key="prior-email-list:" + str(uuid4()), port=google)
                        selected = messages.read_selected(session, box, owner, account_id,
                            key="prior-email-read:" + str(uuid4()), observation_id=existing["read_id"],
                            observation_sha256=existing["source_sha256"], message_id="invented-ui-message",
                            thread_id=None, port=google)
                        messages.select_review(session, box, owner, initial["id"],
                            expected=reviewed["revision"], key="prior-email-review:" + str(uuid4()),
                            read_id=selected["read_id"], source_sha256=selected["source_sha256"],
                            patient_link_id=link.id, reviewed_patient=True, reviewed_exact_message=True,
                            reviewed_untrusted_source=True, port=google, external_identity_id=account_id)
                        case["prior_email"] = current(case)["entries"][-1]
                    cases[initial["id"]] = case
                return self.respond(
                    200,
                    {
                        "scope": {"box_id": box, "actor_id": owner},
                        "workspace": current(case),
                        "team_revision": team_snapshot["revision"],
                        "clinical_note": case["note"],
                        "token": token(),
                    },
                )
            if parsed.path == "/lab/inspect":
                params = parse_qs(parsed.query)
                if set(params) != {"workspace_id"} or len(params["workspace_id"]) != 1:
                    return self.respond(422, {"detail": "invalid invented case"})
                case = cases.get(params["workspace_id"][0])
                if case is None:
                    return self.respond(404, {"detail": "invented case unavailable"})
                return self.respond(200, inspect_case(case))
            response = client.get(self.path, headers=dict(self.headers))
            return self.respond(response.status_code, response.json())

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            assert 0 <= length <= 65536
            body = self.rfile.read(length)
            if self.path == "/lab/revoke":
                value = json.loads(body)
                if not isinstance(value, dict) or set(value) != {"workspace_id"}:
                    return self.respond(422, {"detail": "invalid invented case"})
                case = cases.get(value["workspace_id"])
                if case is None or not (case["round"].startswith("masked_") or case["round"] == "revoked_accepted"):
                    return self.respond(404, {"detail": "invented terminal case unavailable"})
                before_revoke = current(case)
                with Session(engine) as session:
                    credential = session.get(GoogleConnectionCredential, account_id)
                    assert credential is not None and credential.status == "ready"
                    credential.status, credential.sealed = "disconnected", None
                    session.commit()
                case["revoked_counts"] = dict(provider_calls=len(google.calls), model_rounds=len(rounds))
                masked = inspect_case(case)
                for previous in before_revoke.get("handoffs", []):
                    selected = next(h for h in masked["workspace"]["handoffs"] if h["id"] == previous["id"])
                    assert selected["result_sha256"] == previous["result_sha256"]
                    assert selected["task_brief_unavailable"] is True
                    assert "task_brief" not in selected and "completion_evidence" not in selected
                    assert selected["review_status"] == "stale"
                    result = next(e for e in masked["workspace"]["entries"] if e["id"] == selected["result_entry_id"])
                    assert result["content"] == "" and result["reply"] is None
                    if previous.get("review", {}).get("feedback"):
                        assert previous["review"]["feedback"] not in str(masked)
                return self.respond(200, masked)
            if self.path == "/lab/work":
                value = json.loads(body)
                assert set(value) <= {"workspace_id", "handoff_id"}
                case = cases[value["workspace_id"]]
                try:
                    return self.respond(
                        200, {"workspace": run_tasks(case, value.get("handoff_id"))}
                    )
                except Exception as error:
                    return self.respond(
                        500, self.worker_diagnostic(case, error),
                    )
            response = client.post(self.path, headers=dict(self.headers), content=body)
            return self.respond(response.status_code, response.json())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report_root = Path(os.environ.get("COSMAS_OPERATIONAL_EVIDENCE_DIR", str(tmp_path)))
    report_root.mkdir(parents=True, exist_ok=True)
    report = report_root / (("google-calendar-full-workspace.json" if calendar_lab else "google-message-full-workspace.json") if full_workspace else ("google-calendar-ui-server-lab.json" if calendar_lab else "google-message-ui-server-lab.json"))
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR") if k in os.environ}
    env.update(
        **{("COSMAS_GOOGLE_FULL_LAB_URL" if full_workspace else "COSMAS_GOOGLE_CALENDAR_LAB_URL" if calendar_lab else "COSMAS_GOOGLE_MESSAGE_LAB_URL"):
           f"http://127.0.0.1:{server.server_port}"},
        **{("COSMAS_GOOGLE_FULL_LAB_REPORT" if full_workspace else "COSMAS_GOOGLE_CALENDAR_LAB_REPORT" if calendar_lab else "COSMAS_GOOGLE_MESSAGE_LAB_REPORT"): str(report)},
        COSMAS_GOOGLE_FULL_LAB_KIND=source_kind,
    )

    def close_reserved_lab_work():
        # Failed UI assertions must not leave committed lab work in the global
        # worker queue. Revocation and the real claim fence close only these
        # invented workspaces, without dispatching or changing admission state
        # directly. Keep the binding reader and runtime fixture alive here.
        before_io = (len(google.calls), len(rounds))
        with Session(engine) as session:
            credential = session.get(GoogleConnectionCredential, account_id)
            assert credential is not None
            credential.status, credential.sealed = "disconnected", None
            session.commit()
            reserved = list(session.scalars(select(ModelWorkAdmission.id).where(
                ModelWorkAdmission.box_id == box,
                ModelWorkAdmission.owner_id == owner,
                ModelWorkAdmission.workspace_id.in_(list(cases)),
                ModelWorkAdmission.state == "reserved",
            )))
        for admission_id in reserved:
            with Session(engine) as session:
                assert work.claim(session, box, owner, admission_id) is None
                row = session.get(ModelWorkAdmission, admission_id)
                assert row is not None and row.state in {"failed", "abandoned"}
        assert (len(google.calls), len(rounds)) == before_io

    try:
        with messages.install_binding_reader(
            lambda s, a, full: google.message_binding(
                messages._scoped_identity(a), require_full=full, session=s
            )
        ), calendars.install_binding_reader(lambda s, a: google.calendar_binding(
            calendars._scoped_identity(a), session=s)):
            original_error = None
            try:
                result = subprocess.run(
                    [
                        str(NODE),
                        "node_modules/vitest/vitest.mjs",
                        "run",
                        "src/GoogleFullWorkspaceServerLab.test.tsx" if full_workspace else "src/GoogleCalendarServerLab.test.tsx" if calendar_lab else "src/GoogleMessageServerLab.test.tsx",
                        "--maxWorkers=1",
                    ],
                    cwd=REPO / "web",
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                assert result.returncode == 0, result.stdout + result.stderr
                evidence = json.loads(report.read_text())
                assert len(evidence["episodes"]) == 6 and all(e["passed"] for e in evidence["episodes"])
                assert len(evidence["recovery_episodes"]) == (4 if full_workspace else 2) and all(
                    e["passed"] for e in evidence["recovery_episodes"]
                )
                expected_calls = ["list", "read", "calendar"] * (10 if full_workspace else 8) if calendar_lab else ["list", "read"] * (10 if full_workspace else 8)
                assert len(cases) == (10 if full_workspace else 8) and len(rounds) == (52 if full_workspace else 40) and google.calls == expected_calls
                for case in cases.values():
                    assert current(case)["note"] == case["note"]
                    if case["round"].startswith("masked_") or case["round"] == "revoked_accepted":
                        assert case["inspection_counts"] and all(
                            counter == case["revoked_counts"] for counter in case["inspection_counts"]
                        )
                with Session(engine) as session:
                    credential = session.get(GoogleConnectionCredential, account_id)
                    assert credential is not None and credential.status == "disconnected" and credential.sealed is None
                    assert not list(session.scalars(select(ModelWorkAdmission.id).where(
                        ModelWorkAdmission.box_id == box,
                        ModelWorkAdmission.owner_id == owner,
                        ModelWorkAdmission.workspace_id.in_(list(cases)),
                        ModelWorkAdmission.state.in_({"reserved", "running"}),
                    )))
            except BaseException as error:
                original_error = error
                raise
            finally:
                try:
                    close_reserved_lab_work()
                except Exception as error:
                    if original_error is None:
                        raise
                    original_error.add_note(
                        f"Invented lab reservation cleanup failed: {type(error).__name__}"
                    )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        client.close()
        api.app.dependency_overrides.clear()
