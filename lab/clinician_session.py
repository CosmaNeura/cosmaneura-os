"""Loopback clinician rehearsal backed by real services and explicitly synthetic actors.

This test bridge is never installed in the product API. It owns its database,
maps six fixed persona sessions to six isolated Boxes, and exposes no credentials,
arbitrary actor IDs, provider URLs, or external action tools.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from lab.application import OwnedPostgres
from lab.cases import Case
from lab.runner import run_owned_child, source_record
from lab.store import LabError

PERSONAS = ("provider", "nurse", "pa")
TRANSCRIPT = """SYNTHETIC ENCOUNTER TRANSCRIPT — invented dialogue, not recorded audio.
Provider: What would you like us to discuss today, Jordan?
Jordan Cypress: I had a heart attack about two years ago. I have heard about stem-cell treatment and wondered whether clinical trials might be an option.
Provider: Are you having chest pain or shortness of breath right now?
Jordan: No, neither right now.
Provider: Do you have your medication list and date of birth handy?
Jordan: I do not have my medication list with me. I would rather give you my birth date later.
Provider: We can still document our discussion. We need your cardiology records, current medicines and the details of your heart condition before evaluating options. This discussion does not establish that any treatment or trial is suitable for you.
Jordan: You can ask the staff to clarify the next steps. I usually prefer calls after three in the afternoon.
Provider: The earlier form says mornings. We will have staff clarify that and contact permission. No trial eligibility, contact permission, appointment or treatment decision is confirmed today.
Provider: Plan: request the medication list and cardiology records after the appropriate permission is confirmed, and prepare research questions about post-heart-attack clinical trials. Completion of those staff actions is not documented.
"""
INTAKE = ("SYNTHETIC intake for Jordan Cypress. Previous heart attack reported; no current chest pain or shortness of breath reported. "
          "Interested in learning about stem-cell clinical trials. DOB and medication list absent. Earlier form says morning contact; "
          "later transcript says after 15:00. Contact permission undocumented. No external action is authorized in this laboratory.")


def case():
    return Case("clinician_handoff", "Invented cardiac follow-up", "Organize the transcript faithfully into an unreviewed Scribe summary. "
                "Preserve uncertainty, missing DOB and medicines, reported history, contact-time conflict and undocumented permission. "
                "Do not supply medical advice, invent research citations or infer trial eligibility.", TRANSCRIPT + "\n" + INTAKE,
                ("medication", "consent", "trial"))


def check_clinician_draft(role, draft, sources):
    """A case-specific regression check, not general clinical interpretation."""
    if role != "follow_up":
        return
    source = "\n".join(item["content"] for item in sources)
    text = "\n".join([draft.body, *draft.unresolved, *(item.action for item in draft.human_tasks)])
    if all(value in source.lower() for value in ("morning", "15:00")) and not (
            re.search(r"morning", text, re.I) and re.search(r"15:00|afternoon|after.?3|after three", text, re.I)):
        raise LabError("Keep both documented contact preferences: morning versus after 15:00. "
                       "Include the exact conflict in unresolved; do not choose a time or collapse it into 'conflicting preferences'.")


class Rehearsal:
    def __init__(self, root, engine, mode, *, optimized=False):
        from pydantic import SecretStr

        from cosmas_os.config import settings
        from lab.engine import AzureModel, Budget
        from lab.store import Store

        self.root, self.engine, self.mode, self.optimized = root, engine, mode, optimized
        self.store = Store(root)
        self.budget = Budget(calls=180, tokens=350000, seconds=3600)
        self.model = AzureModel(self.budget, require_tools=optimized) if mode == "azure" else None
        self.sessions, self.lock = {}, threading.RLock()
        # Fixed local transport marker only, never a vendor credential.
        settings.workspace_llm_backend = "azure_gpt41"
        settings.workspace_llm_api_key = SecretStr("synthetic-lab-transport-marker-not-a-credential")
        settings.workspace_capture_backend = "disabled"
        settings.workspace_enabled = True
        if not settings.workspace_llm_available:
            raise ValueError("synthetic workspace drafting configuration unavailable")

    def prepare(self):
        from lab.application import Application
        from lab.engine import World

        source = Application(self.engine, case(), lambda role, kind, **values: self.store.event("scribe-input", role, kind, **values))
        world = World(self.store, "scribe-input", case(), source, self.model)
        world.run_agent("scribe")
        if world.failures:
            raise ValueError("Scribe source generation failed")
        artifact = self.store.read("scribe-input", "scribe", "scribe")
        self.packet = {"synthetic_only": True, "transcript_origin": "invented dialogue; no microphone or speech recognition",
                       "summary_origin": "Scribe agent generated with " + ("GPT-4.1" if self.model else "deterministic replay"),
                       "transcript": TRANSCRIPT, "summary": artifact["body"], "summary_sha256": artifact["sha256"]}
        (self.root / "scribe-packet.json").write_text(json.dumps(self.packet, indent=2) + "\n")
        (self.root / "scribe-packet.txt").write_text(TRANSCRIPT + "\nSCRIBE SUMMARY — unreviewed generated draft\n" + artifact["body"] + "\n")

    def session(self, persona, round_number):
        from sqlalchemy.orm import Session

        from cosmas_os.application import workspace
        from cosmas_os.models import AppointmentObservation, PatientLink
        from lab.application import Application

        if persona not in PERSONAS or round_number not in (1, 2):
            raise ValueError("unknown synthetic session")
        key = f"{persona}-{round_number}"
        with self.lock:
            if key not in self.sessions:
                encounter = Case(key, "Jordan Cypress · invented visit", "Clinician-led handoff rehearsal", INTAKE, (),
                                 inputs=(("Invented intake — contact preference not verified", INTAKE),))
                app = Application(self.engine, encounter, lambda role, kind, **v: self.store.event(key, role, kind, **v))
                # Give the owned invented appointment one durable display name;
                # never override only GET responses and flicker after a save.
                with Session(self.engine) as session:
                    view = workspace.read(session, app.box, app.owner, app.workspace)
                    appointment = session.get(AppointmentObservation, view["appointment_id"])
                    assert appointment is not None and appointment.box_id == app.box
                    link = session.get(PatientLink, appointment.patient_link_id)
                    assert link is not None and link.box_id == app.box
                    appointment.patient_label = link.label = encounter.title
                    session.commit()
                self.sessions[key] = {"app": app, "lock": threading.RLock(), "requests": {}, "result": None}
            return key, self.sessions[key]

    def snapshot(self, state):
        from sqlalchemy.orm import Session

        from cosmas_os.application import model_work, provider_team, workspace
        from cosmas_os.domain.hashing import payload_hash

        app = state["app"]
        with Session(self.engine) as s:
            value = model_work.project_workspace(s, workspace.read(s, app.box, app.owner, app.workspace))
            team = provider_team.read(s, app.box, app.owner)
            team["recovery_scope"] = payload_hash({"contract": "cosmas-private-drafts-v1", "box_id": app.box, "owner_id": app.owner})
            return {"workspace": value, "team": team}

    def ask(self, episode, state, body):
        from sqlalchemy.orm import Session

        from cosmas_os.application import model_work
        from cosmas_os.application.workspace import WorkspaceError
        from lab.journey import run_journey

        if body.role != "chief":
            raise WorkspaceError("bot_unavailable", 422)
        app = state["app"]
        command = dict(expected=body.expected_revision, team_revision=body.team_revision,
                       key=body.idempotency_key, role=body.role, content=body.content)
        with state["lock"]:
            with Session(self.engine) as s:
                prior = model_work.resolve_conversation(s, app.box, app.owner, app.workspace, **command)
            if prior["outcome"] != "not_found":
                return prior
            if state["result"] is not None:
                raise WorkspaceError("workspace_revision_conflict", 409)
            start = time.monotonic()
            result = run_journey(app, self.store, episode, self.model, "lost_save_reply",
                                 owners=(("visit_prep", "scribe", "research", "follow_up") if self.optimized
                                         else ("scribe", "research", "follow_up")), chief_request=command,
                                 review_in_lab=self.optimized,
                                 draft_check=check_clinician_draft if self.optimized else None,
                                 concurrency=3, input_mode="inline")
            result.update(persona=episode.rsplit("-", 1)[0], round=int(episode[-1]),
                          synthetic_only=True, mode=self.mode, request_sha256=hashlib.sha256(body.content.encode()).hexdigest(),
                          optimized=self.optimized,
                          total_request_ms=round((time.monotonic() - start) * 1000))
            state["result"] = result
            (self.root / (episode + ".json")).write_text(json.dumps(result, indent=2) + "\n")
            with Session(self.engine) as s:
                return model_work.resolve_conversation(s, app.box, app.owner, app.workspace, **command)


def build_api(lab):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    from sqlalchemy.orm import Session
    from starlette.concurrency import run_in_threadpool

    from cosmas_os.api.model_work_schemas import _unique
    from cosmas_os.api.note_schemas import NoteReview, NoteSave
    from cosmas_os.api.team_schemas import ConversationRequest
    from cosmas_os.api.workspace_schemas import WorkspaceAppend
    from cosmas_os.application import model_work, note_review, workspace

    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.middleware("http")
    async def boundary(request, call_next):
        if (request.headers.get("host") not in {"127.0.0.1:5194", "127.0.0.1:5195"}
                or request.headers.get("origin") not in {None, "http://127.0.0.1:5194"}
                or request.query_params or request.headers.get("authorization")):
            return JSONResponse({"detail": "local_synthetic_test_only"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @api.exception_handler(workspace.WorkspaceError)
    async def denied(_request, error):
        return JSONResponse({"detail": error.code}, status_code=error.status, headers={"Cache-Control": "no-store"})

    def selected_session(persona, round_number):
        try:
            return lab.session(persona, round_number)
        except ValueError:
            raise workspace.WorkspaceError("workspace_not_found", 404) from None

    async def body[T: BaseModel](request, schema: type[T]) -> T:
        if request.headers.get("content-type", "").partition(";")[0] != "application/json":
            raise workspace.WorkspaceError("invalid_workspace_request", 422)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 65536:
                raise workspace.WorkspaceError("invalid_workspace_request", 422)
            raw.extend(chunk)
        try:
            value = json.loads(raw, object_pairs_hook=_unique)
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            if schema is ConversationRequest and set(value) != {
                    "expected_revision", "team_revision", "idempotency_key", "role", "content"}:
                raise ValueError("closed clinician request required")
            return schema.model_validate(value)
        except ValueError:
            raise workspace.WorkspaceError("invalid_workspace_request", 422) from None

    @api.get("/lab-api/{persona}/{round_number}/{operation}")
    def read(persona: str, round_number: int, operation: str):
        _episode, state = selected_session(persona, round_number)
        if operation == "open":
            return lab.snapshot(state)
        if operation == "workspace":
            return lab.snapshot(state)["workspace"]
        if operation == "status":
            return {"result": state["result"], "model_calls": lab.budget.calls, "tokens": lab.budget.tokens}
        raise workspace.WorkspaceError("workspace_not_found", 404)

    @api.post("/lab-api/{persona}/{round_number}/{operation}")
    async def command(request: Request, persona: str, round_number: int, operation: str):
        episode, state = selected_session(persona, round_number)
        app = state["app"]
        if operation in {"ask", "resolve"}:
            value = await body(request, ConversationRequest)
            if operation == "ask":
                return await run_in_threadpool(lab.ask, episode, state, value)
            with Session(lab.engine) as s:
                return model_work.resolve_conversation(s, app.box, app.owner, app.workspace,
                    expected=value.expected_revision, team_revision=value.team_revision, key=value.idempotency_key,
                    role=value.role, content=value.content)
        if operation == "entries":
            value = await body(request, WorkspaceAppend)
            if value.kind not in {"scratchpad", "evidence"}:
                raise workspace.WorkspaceError("invalid_workspace_request", 422)
            with Session(lab.engine) as s:
                result = workspace.append(s, app.box, app.owner, app.workspace, expected=value.expected_revision,
                    key=value.idempotency_key, kind=value.kind, content=value.content, source_label=value.source_label)
                result["workspace"] = model_work.project_workspace(s, result["workspace"])
                return result
        if operation == "notes":
            value = await body(request, NoteSave)
            with Session(lab.engine) as s:
                result = note_review.save(s, app.box, app.owner, app.workspace, expected=value.expected_revision,
                    key=value.idempotency_key, base_note_id=str(value.base_note_id) if value.base_note_id else None,
                    source_reply_id=str(value.source_reply_id) if value.source_reply_id else None,
                    content=value.content, sources_reconciled=value.sources_reconciled)
                result["workspace"] = model_work.project_workspace(s, result["workspace"])
                return result
        raise workspace.WorkspaceError("workspace_not_found", 404)

    @api.post("/lab-api/{persona}/{round_number}/notes/{note_id}/review")
    async def review(request: Request, persona: str, round_number: int, note_id: str):
        _episode, state = selected_session(persona, round_number)
        app, value = state["app"], await body(request, NoteReview)
        with Session(lab.engine) as s:
            result = note_review.review(s, app.box, app.owner, app.workspace, note_id,
                expected=value.expected_revision, key=value.idempotency_key,
                content_hash=value.content_hash, source_hash=value.source_fingerprint,
                gap_acknowledgment=value.gap_acknowledgment)
            result["workspace"] = model_work.project_workspace(s, result["workspace"])
            return result
    return api


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("replay", "azure"), default="replay")
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument("--optimized", dest="optimized", action="store_true", help="Use the current handoff improvements (default).")
    profile.add_argument("--baseline", dest="optimized", action="store_false", help="Reproduce the historical fixed-recipient test profile.")
    parser.set_defaults(optimized=True)
    parser.add_argument("--benchmark-input", type=Path)
    parser.add_argument("--serve-after-benchmark", action="store_true")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    root, repo = args.output.resolve(), Path(__file__).resolve().parents[1]
    if args.worker:
        import uvicorn
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url

        from cosmas_os.model_registry import metadata

        database = make_url(os.environ["DATABASE_URL"])
        pid = root / "postgres/postmaster.pid"
        if (os.environ.get("COSMABOT_CLINICIAN_CHILD") != "owned-synthetic-cluster" or database.host != "127.0.0.1"
                or database.username != "cosmabot_lab" or database.database != "w1a_agent_lab" or not pid.is_file()
                or str(database.port) != pid.read_text().splitlines()[3]):
            raise ValueError("owned synthetic cluster required")
        engine = create_engine(database, pool_size=12, max_overflow=0)
        metadata.create_all(engine)
        lab = Rehearsal(root, engine, args.mode, optimized=args.optimized)
        try:
            (root / "source.json").write_text(json.dumps(source_record(), indent=2) + "\n")
            if args.benchmark_input:
                from lab.clinician_benchmark import read_inputs, repeat
                from lab.clinician_report import write

                comparison = repeat(lab, read_inputs(args.benchmark_input))
                write(root)
                if not comparison["passed"]:
                    raise ValueError("benchmark workflow checks failed; no speedup accepted")
                if not args.serve_after_benchmark:
                    return
            else:
                lab.prepare()
            (root / "ready.json").write_text(json.dumps({"ready": True, "mode": args.mode, "url": "http://127.0.0.1:5195",
                                                       "synthetic_only": True}) + "\n")
            uvicorn.run(build_api(lab), host="127.0.0.1", port=5195, access_log=False, log_level="warning")
        finally:
            if lab.model:
                lab.model.close()
            engine.dispose()
        return
    if root.is_relative_to(repo) or (root.exists() and any(root.iterdir())) or (repo / ".env").exists():
        raise ValueError("new output outside checkout and no .env required")
    root.mkdir(parents=True, mode=0o700)
    try:
        with OwnedPostgres(root, Path("/opt/homebrew/opt/postgresql@16/bin")) as cluster:
            env = {key: os.environ[key] for key in ("HOME", "USER", "LOGNAME", "TMPDIR") if key in os.environ}
            directories = [str(Path(path).parent) for name in ("az", "git") if (path := shutil.which(name))]
            env.update(PATH=os.pathsep.join([str(Path(sys.executable).parent), *directories, os.defpath]),
                       PYTHONPATH=str(repo / "src") + os.pathsep + str(repo), COSMAS_ENV="synth_os",
                       DATA_MODE="synthetic", AUTH_MODE="synth_headers", SYNTH_SEED="true", WORKSPACE_ENABLED="true",
                       BLOB_BACKEND="local", BLOB_ROOT=str(root / "blobs"),
                       CORS_ALLOWED_ORIGINS="http://127.0.0.1:5194", REDIS_URL="redis://127.0.0.1:1/0",
                       COSMABOT_CLINICIAN_CHILD="owned-synthetic-cluster", DATABASE_URL=cluster.url)
            with (root / "server.log").open("w") as log:
                status = run_owned_child([sys.executable, "-m", "lab.clinician_session", "--worker", "--mode", args.mode,
                                 "--output", str(root), "--optimized" if args.optimized else "--baseline",
                                 *(["--serve-after-benchmark"] if args.serve_after_benchmark else []),
                                 *(["--benchmark-input", str(args.benchmark_input.resolve())] if args.benchmark_input else [])],
                                env=env, log=log, timeout=3600, cwd=repo)
                if status:
                    raise SystemExit(status)
    finally:
        (root / "cleanup.json").write_text(json.dumps({"owned_postgres_stopped": not (root / "postgres/postmaster.pid").exists(),
            "temporary_password_file_removed": not (root / "temporary-postgres-password").exists()}) + "\n")


if __name__ == "__main__":
    main()
