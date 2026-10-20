"""Six signed full-product specialist graphs with invented Scribe custody and model I/O."""

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
from tests.unit.test_core_scribe_bridge import reviewed_fixture

from cosmas_os.adapters.gpt41 import ENDPOINT, _context
from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import model_work as work
from cosmas_os.application import note_review as notes
from cosmas_os.application import provider_team as team
from cosmas_os.application import scribe_source
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.models import (
    AppointmentObservation,
    AuditEvent,
    ExternalIdentity,
    ModelWorkAdmission,
    PatientLink,
)

NODE = Path(shutil.which("node") or "node")
REPO = Path(__file__).resolve().parents[2]


def test_actual_signed_multi_specialist_ui_completes_six_revision_and_acceptance_graphs(
    engine, monkeypatch, tmp_path
):
    assert NODE.is_file()
    configuration = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue] -- BaseSettings runtime option.
        workspace_enabled=True,
        workspace_authenticated_enabled=True,
        auth_mode="clerk_jwt",
        synth_seed=False,
        database_url=str(engine.url.render_as_string(hide_password=False)),
        clerk_issuer="https://multi.example.invalid",
        clerk_jwks_url="https://multi.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-multi",
        clerk_organization_id="org_multi",
        clerk_authorized_parties="http://localhost:5173",
        cors_allowed_origins="http://localhost:5173",
    )
    monkeypatch.setattr(api, "settings", configuration)
    runtime = work.team.runtime_settings
    for name in (
        "workspace_enabled",
        "workspace_authenticated_enabled",
        "auth_mode",
        "synth_seed",
        "database_url",
        "clerk_issuer",
        "clerk_jwks_url",
        "clerk_audience",
        "clerk_organization_id",
        "clerk_authorized_parties",
        "cors_allowed_origins",
    ):
        monkeypatch.setattr(runtime, name, getattr(configuration, name))
    monkeypatch.setattr(runtime, "workspace_llm_backend", "azure_gpt41")
    monkeypatch.setattr(runtime, "workspace_llm_api_key", SecretStr("invented-no-network"))
    monkeypatch.setattr(runtime, "workspace_agent_tools_enabled", True)

    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_keys(self, *, refresh):
            return [SimpleNamespace(key_id="synthetic-multi", key=signing.public_key())]

    verifier = ClerkTokenVerifier(configuration, jwks_client=Keys(), start_background_refresh=False)
    monkeypatch.setattr(api, "_clerk_verifier", lambda: verifier)

    def sessions():
        with Session(engine) as session:
            yield session

    api.app.dependency_overrides[api.get_session] = sessions
    client = TestClient(api.app)

    cases = {}
    rounds = []
    reads = []
    dispatches = []
    lock = threading.Lock()
    parallel_barrier = None
    original = work.dispatch_claim

    def provider_response(content=None, calls=None):
        return {
            "model": "gpt-4.1",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [
                {
                    "finish_reason": "tool_calls" if calls else "stop",
                    "message": {
                        "role": "assistant",
                        "content": None if content is None else json.dumps(content),
                        "tool_calls": calls,
                    }
                    if calls
                    else {"role": "assistant", "content": json.dumps(content)},
                }
            ],
        }

    def dispatch(claim):
        context = _context(claim.envelope["context"])
        selection = claim.envelope["tool_selection"]
        started = time.monotonic()
        assert claim.envelope["contract"] == (
            "cosmas-gpt41-prepared.v7" if context.role == "research" else "cosmas-gpt41-prepared.v6")
        packet_sources = [
            p for p in context.sources if p.label.startswith("Reviewed Scribe snapshot ·")
        ]
        assert len(packet_sources) == 1 and len(packet_sources[0].content) > 1000
        delivered = json.loads(claim.envelope["body"]["messages"][1]["content"])["sources"]
        assert (
            next(p["text"] for p in delivered if p["source_id"] == packet_sources[0].entry_id)
            == packet_sources[0].content
        )

        def provider(request):
            body = json.loads(request.content)
            assert (
                str(request.url) == ENDPOINT
                and body["model"] == "gpt-4.1"
                and body["store"] is False
            )
            tool_messages = [m for m in body["messages"] if m["role"] == "tool"]
            with lock:
                rounds.append(
                    {
                        "admission_id": claim.admission_id,
                        "workspace_id": claim.workspace_id,
                        "role": context.role,
                        "started_s": time.monotonic(),
                        "tool_messages": len(tool_messages),
                        "request_bytes": len(request.content),
                    }
                )
            if not tool_messages:
                calls = []
                if "Collect the revised" in context.question:
                    by_role = {}
                    for p in sorted(
                        selection["teammate_drafts"], key=lambda p: p["revision"], reverse=True
                    ):
                        by_role.setdefault(p["role"], p)
                    selected = list(by_role.values())
                    assert len(selected) == 4
                    for i, p in enumerate(selected):
                        calls.append(
                            {
                                "id": "draft_" + str(i),
                                "type": "function",
                                "function": {
                                    "name": "read_saved_teammate_draft",
                                    "arguments": json.dumps(
                                        {k: p[k] for k in ("entry_id", "revision", "sha256")}
                                    ),
                                },
                            }
                        )
                else:
                    selected = [p for p in selection["sources"] if p["kind"] == "evidence"]
                    assert len(selected) == 2
                    for i, p in enumerate(selected):
                        calls.append(
                            {
                                "id": "source_" + str(i),
                                "type": "function",
                                "function": {
                                    "name": "read_selected_source",
                                    "arguments": json.dumps(
                                        {k: p[k] for k in ("entry_id", "revision", "sha256")}
                                    ),
                                },
                            }
                        )
                    if selection["teammate_drafts"]:
                        p = max(selection["teammate_drafts"], key=lambda p: p["revision"])
                        calls.append(
                            {
                                "id": "origin",
                                "type": "function",
                                "function": {
                                    "name": "read_saved_teammate_draft",
                                    "arguments": json.dumps(
                                        {k: p[k] for k in ("entry_id", "revision", "sha256")}
                                    ),
                                },
                            }
                        )
                if (
                    parallel_barrier is not None
                    and context.draft_only
                    and "Human-requested revision" not in context.question
                ):
                    parallel_barrier.wait(timeout=12)
                return httpx.Response(200, json=provider_response(calls=calls))
            for m in tool_messages:
                value = json.loads(m["content"])
                r = value["receipt"]
                assert (
                    r["actor_agent_id"] != r["initiated_by_human_id"] == claim.owner
                    and r["admission_id"] == claim.admission_id
                )
                if value["tool"] == "read_selected_source":
                    assert (
                        hashlib.sha256(value["data"]["content"].encode()).hexdigest()
                        == value["data"]["sha256"]
                    )
                with lock:
                    reads.append(
                        {
                            "admission_id": claim.admission_id,
                            "workspace_id": claim.workspace_id,
                            "role": context.role,
                            "receipt": r,
                            "tool": value["tool"],
                        }
                    )
            feedback = ""
            if "Human-requested revision of the prior private draft\n" in context.question:
                feedback = json.loads(
                    context.question.split(
                        "Human-requested revision of the prior private draft\n", 1
                    )[1].split("\nTreat the quoted prior draft", 1)[0]
                )["feedback"]
            if context.role == "chief":
                targets = {p["role"]: p["address"] for p in context.handoff_targets}
                recipients = (
                    []
                    if "Collect the revised" in context.question
                    else ["scribe"]
                    if "Ask Scribe only" in context.question
                    else ["research", "visit_prep", "follow_up"]
                )
                content = {
                    "answer": "Invented preparation: retained missing diagnosis, DOB and trial eligibility; private drafts require human review.",
                    "source_ids": [p.entry_id for p in context.sources],
                    "handoffs": [
                        {
                            "role": targets[role],
                            "intended_role": role,
                            "brief": "Prepare an independent "
                            + role
                            + " draft from the exact saved Scribe transcript and summary; preserve unknown heart history and do not send or book.",
                            "requirements": REQUIREMENTS,
                        }
                        for role in recipients
                    ],
                }
            elif context.role == "scribe":
                content = {
                    "excerpts": [
                        {"source_id": p.entry_id, "quote": p.content[:1000]}
                        for p in context.sources
                        if p.kind == "evidence"
                    ],
                    "needs_from_clinician": ["Confirm diagnosis, medications and missing DOB."]
                    + ([feedback] if feedback else []),
                }
            else:
                content = {
                    "answer": context.role
                    + " invented private draft. "
                    + ("Applied requested edit: " + feedback + ". " if feedback else "")
                    + "Provider must confirm heart history, medications, responsible owner and due date. Trial eligibility unknown; no public search, booking or delivery occurred.",
                    "source_ids": [p.entry_id for p in context.sources],
                }
            if context.role == "chief" and claim.envelope["baseline"]["flags"]["work_status"]:
                content["intent"] = "conversation"
            return httpx.Response(200, json=provider_response(content=content))

        result = original(
            claim, session_factory=lambda: Session(engine), transport=httpx.MockTransport(provider)
        )
        with lock:
            dispatches.append(
                {
                    "admission_id": claim.admission_id,
                    "workspace_id": claim.workspace_id,
                    "role": context.role,
                    "started_s": started,
                    "ended_s": time.monotonic(),
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            )
        return result

    monkeypatch.setattr(work, "dispatch_claim", dispatch)

    def current(case):
        with Session(engine) as s:
            return work.project_workspace(s, ws.read(s, case["box"], case["owner"], case["wid"]))

    def inspect(case):
        with Session(engine) as s:
            admissions = list(
                s.scalars(
                    select(ModelWorkAdmission).where(ModelWorkAdmission.workspace_id == case["wid"])
                )
            )
            events = list(
                s.scalars(
                    select(AuditEvent).where(
                        AuditEvent.box_id == case["box"],
                        AuditEvent.event_type == "workspace.agent_tool_read",
                    )
                )
            )
            return {
                "workspace": current(case),
                "admissions": [
                    {
                        "id": p.id,
                        "role": p.prepared_envelope["context"]["role"],
                        "kind": p.kind,
                        "state": p.state,
                        "source_sha256": p.source_sha256,
                        "envelope_sha256": p.envelope_sha256,
                        "agent_id": p.agent_id,
                        "owner_id": p.owner_id,
                    }
                    for p in admissions
                ],
                "tool_receipts": [
                    {
                        "actor_id": p.actor_principal_id,
                        "human_id": p.initiated_by_principal_id,
                        "detail": p.detail,
                    }
                    for p in events
                ],
                "dispatches": [p for p in dispatches if p["workspace_id"] == case["wid"]],
            }

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value):
            raw = json.dumps(value).encode()
            self.send_response(status)
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
                    persona = q["persona"][0]
                    iteration = q["round"][0]
                    assert persona in {
                        "physician",
                        "nurse_practitioner",
                        "physician_assistant",
                    } and iteration in {"1", "2"}
                    with Session(engine) as s:
                        seed = svc.provision_box(
                            svc.Container(s), "Invented multi-specialist " + persona
                        )
                        box, owner = seed["box_id"], seed["owner_id"]
                        subject = str(uuid4())
                        account = ExternalIdentity(
                            box_id=box,
                            principal_id=owner,
                            issuer=api.settings.clerk_issuer,
                            subject=subject,
                            organization_id="org_multi",
                            reviewed_by="Invented owner",
                            evidence_ref="test:multi-synthetic",
                        )
                        s.add(account)
                        s.commit()
                        conf = team.starter_configuration(box, owner)
                        version = team.save(
                            s, box, owner, expected=0, key="multi-team", configuration=conf
                        )
                        link = PatientLink(
                            box_id=box,
                            source_pair_key=str(uuid4()),
                            label="Invented Shawn " + persona + " " + iteration,
                            state="confirmed",
                            confirmed_by_principal_id=owner,
                            attested_at=datetime.now(UTC),
                        )
                        s.add(link)
                        s.flush()
                        appt = AppointmentObservation(
                            box_id=box,
                            patient_link_id=link.id,
                            external_id=str(uuid4()),
                            source="synthetic",
                            start_at=datetime.now(UTC),
                            patient_label=link.label,
                        )
                        s.add(appt)
                        s.commit()
                        w = ws.create(
                            s, box, owner, appt.id, "multi-create", initial_synthetic_source=False
                        )
                        w = ws.append(
                            s,
                            box,
                            owner,
                            w["id"],
                            expected=w["revision"],
                            key="source-notebook",
                            kind="scratchpad",
                            content="Invented visit notebook. DOB unavailable. Please preserve patient-reported uncertainty.",
                        )["workspace"]
                        transcript = (
                            "INVENTED source transcript. Shawn reports heart issues; diagnosis, event date, medication list and DOB are unavailable. Stem-cell clinical-trial eligibility is unknown. No treatment, referral, sending or booking was chosen. "
                            * 12
                        )
                        view = reviewed_fixture(transcript)
                        selected = scribe_source.selection(view)
                        assert selected is not None
                        packet = scribe_source.save_snapshot(
                            s,
                            box=box,
                            owner=owner,
                            workspace_id=w["id"],
                            expected=w["revision"],
                            key="reviewed-scribe-packet",
                            selected=selected,
                            checked=SimpleNamespace(review=view),
                        )
                        assert len(packet["entries"]) == 1
                        w = packet["workspace"]
                        w = ws.append(
                            s,
                            box,
                            owner,
                            w["id"],
                            expected=w["revision"],
                            key="invented-summary",
                            kind="evidence",
                            source_label="Invented Scribe summary",
                            content="SYNTHETIC Scribe summary. Prepare questions, research-evidence gaps and an administrative follow-up draft. Trial eligibility unknown. No referral, message, booking or public search occurred.",
                        )["workspace"]
                        n = notes.save(
                            s,
                            box,
                            owner,
                            w["id"],
                            expected=w["revision"],
                            key="preserved-note",
                            base_note_id=None,
                            source_reply_id=None,
                            content="INVENTED existing clinician note. Must stay unchanged while private specialists prepare drafts.",
                        )
                        monkeypatch.setattr(configuration, "beta_box_id", box)
                        monkeypatch.setattr(runtime, "beta_box_id", box)
                        assert api.settings.workspace_available, (
                            api.settings.runtime_configuration_errors()
                        )
                        case = {
                            "box": box,
                            "owner": owner,
                            "wid": w["id"],
                            "persona": persona,
                            "round": iteration,
                        }
                        cases[w["id"]] = case
                    now = datetime.now(UTC)
                    token = jwt.encode(
                        dict(
                            sub=subject,
                            iss=api.settings.clerk_issuer,
                            aud="cosmas-multi",
                            sid="synthetic-multi",
                            azp="http://localhost:5173",
                            org_id="org_multi",
                            iat=now,
                            nbf=now,
                            exp=now + timedelta(minutes=20),
                        ),
                        signing,
                        algorithm="RS256",
                        headers={"kid": "synthetic-multi"},
                    )
                    return self.respond(
                        200,
                        {
                            "workspace": current(case),
                            "token": token,
                            "team_revision": version["revision"],
                            "clinical_note": n,
                        },
                    )
                if parsed.path == "/lab/inspect":
                    return self.respond(
                        200, inspect(cases[parse_qs(parsed.query)["workspace_id"][0]])
                    )
                response = client.get(self.path, headers=dict(self.headers))
                return self.respond(response.status_code, response.json())
            except Exception as error:
                import traceback

                traceback.print_exc()
                return self.respond(500, {"detail": type(error).__name__ + ": " + str(error)})

        def do_POST(self):
            nonlocal parallel_barrier
            try:
                size = int(self.headers.get("Content-Length", "0"))
                assert 0 <= size <= 12288
                body = self.rfile.read(size)
                if self.path == "/lab/work":
                    value = json.loads(body)
                    case = cases[value["workspace_id"]]
                    with Session(engine) as s:
                        reserved = list(
                            s.scalars(
                                select(ModelWorkAdmission).where(
                                    ModelWorkAdmission.workspace_id == case["wid"],
                                    ModelWorkAdmission.kind == "private_handoff",
                                    ModelWorkAdmission.state == "reserved",
                                )
                            )
                        )
                    assert len(reserved) in {1, 3}, len(reserved)
                    parallel_barrier = threading.Barrier(3) if len(reserved) == 3 else None
                    with ThreadPoolExecutor(max_workers=len(reserved)) as pool:
                        outcomes = list(
                            pool.map(
                                lambda _: work.process_next(
                                    lambda: Session(engine), dispatch=dispatch
                                ),
                                reserved,
                            )
                        )
                    parallel_barrier = None
                    assert all(outcomes)
                    return self.respond(200, inspect(case))
                response = client.post(self.path, headers=dict(self.headers), content=body)
                return self.respond(response.status_code, response.json())
            except Exception as error:
                parallel_barrier = None
                import traceback

                traceback.print_exc()
                return self.respond(500, {"detail": type(error).__name__ + ": " + str(error)})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report_root = Path(os.environ.get("COSMAS_MULTI_SPECIALIST_EVIDENCE_DIR", str(tmp_path)))
    report_root.mkdir(parents=True, exist_ok=True)
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR") if k in os.environ}
    env.update(
        COSMAS_MULTI_LAB_URL=f"http://127.0.0.1:{server.server_port}",
        COSMAS_MULTI_LAB_REPORT=str(report_root / "ui-server-lab.json"),
    )
    try:
        result = subprocess.run(
            [
                str(NODE),
                "node_modules/vitest/vitest.mjs",
                "run",
                "src/MultiSpecialistServerLab.test.tsx",
                "--maxWorkers=1",
            ],
            cwd=REPO / "web",
            env=env,
            text=True,
            capture_output=True,
            timeout=900,
        )
        (report_root / "vitest.log").write_text(result.stdout + result.stderr)
        report = {
            "synthetic_only": True,
            "cases": [inspect(case) for case in cases.values()],
            "rounds": rounds,
            "reads": reads,
            "dispatches": dispatches,
            "vitest_returncode": result.returncode,
        }
        (report_root / "backend-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads((report_root / "ui-server-lab.json").read_text())
        assert evidence["total"] == evidence["completed"] == 6
        assert (
            len(cases) == 6 and len(dispatches) == 66 and len(rounds) == 132 and len(reads) == 150
        )
        for case in report["cases"]:
            assert len(case["admissions"]) == 11 and all(
                p["state"] == "completed" for p in case["admissions"]
            )
            assert len(case["tool_receipts"]) == 25
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        client.close()
        api.app.dependency_overrides.clear()
