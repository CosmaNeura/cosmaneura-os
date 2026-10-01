"""Run `python -m lab.runner --help` from the repository root."""

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from lab.application import OwnedPostgres
from lab.cases import CASES, CLINIC, WORKFLOW_TESTS, Case
from lab.store import Store

REPO = Path(__file__).resolve().parents[1]


def case_catalog():
    from lab.bot_capabilities import CASES as BOT_CASES
    from lab.fax_teams import CASES as FAX_CASES
    from lab.inbound_workflow import INBOUND
    from lab.journey import INPUTS
    from lab.review_process import INPUTS as REVIEW_INPUTS

    return {**CASES, **FAX_CASES, **BOT_CASES,
        "review_loops": Case("review_loops", "Provider, nurse and PA review and revision loops",
        "Review exact saved materials, request changes, and verify revised material with traceable test sign-off.",
        "SYNTHETIC clinical review workflow", (), inputs=REVIEW_INPUTS),
        "clinic": CLINIC, "inbound": INBOUND, "connectors": Case("connectors", "Email, calendar and fax fault laboratory",
        "Exercise actual adapters and durable OAuth against synthetic providers.", "SYNTHETIC connector clinic", ()),
        "journey": Case("journey", "Chief prepares and verifies encounter handoffs",
        "Decompose intake, Session Prep and Scribe outputs into accountable private draft handoffs.",
        "Synthetic connected encounter", (), inputs=INPUTS)}


def case_checks(key):
    if key == "bot_research":
        return ["tests/unit/test_research.py", "tests/unit/test_research_transport.py", "tests/unit/test_research_analysis.py",
                "tests/integration/test_research_runtime_privileges.py"]
    if key == "bot_documentation":
        return ["tests/unit/test_documentation_review.py", "tests/integration/test_scribe_source_bridge.py",
                "tests/integration/test_note_review.py"]
    if key == "bot_operations":
        return ["tests/unit/test_operations_status.py", "tests/integration/test_follow_up.py",
                "tests/integration/test_appointment_execution.py", "tests/integration/test_membership_work.py",
                "tests/integration/test_finance_work.py", "tests/integration/test_inbox_work.py"]
    if key == "review_loops":
        return ["tests/integration/test_workspace_handoffs.py", "tests/integration/test_note_review.py",
                "tests/unit/test_research_analysis.py"]
    if key.startswith("fax_"):
        return ["tests/integration/test_fax_provider_teams.py", "tests/integration/test_vendor_settings.py",
                "tests/unit/test_vendor_installation_routing.py"]
    if key == "inbound":
        return ["tests/integration/test_lab_inbound.py"]
    if key == "clinic":
        return ["tests/integration/test_workspace_handoffs.py", "tests/integration/test_follow_up.py",
                "tests/integration/test_vendor_work.py", "tests/integration/test_vendor_artifact_ledger.py"]
    if key == "connectors":
        return ["tests/unit/test_personal_connection_failure.py", "tests/unit/test_documo_delivery_status.py"]
    return ["tests/integration/test_workspace_handoffs.py"] if key == "journey" else WORKFLOW_TESTS[key]


def run_owned_child(command, *, env, log, timeout, cwd=REPO):
    """Stop only our worker process group before closing its database on cancel."""
    child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                             stderr=subprocess.STDOUT, start_new_session=True)
    try:
        return child.wait(timeout=timeout)
    finally:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if child.poll() is not None:
                break
            os.killpg(child.pid, sig)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                continue


def write_report(root, report):
    from lab.report import render

    target = root / "report.json"
    temporary = root / "report.next.json"
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(target)
    render(root, report)


def source_record():
    files = (sorted((REPO / "lab").rglob("*.py")) + sorted((REPO / "lab/provider-lessons").glob("*.json"))
             + sorted((REPO / "lab/bot-lessons").glob("*.json"))
             + sorted((REPO / "docs/validation").glob("*-api-reference.json"))
             + sorted((REPO / "src/cosmas_os").rglob("*.py")))
    hashes = {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    return {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
            "source_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(), "files": hashes}


def worker(args):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from lab.application import Application
    from lab.engine import AzureModel, Budget, World
    from lab.evaluate import VERSION, grade

    root = args.output
    store = Store(root)
    budget = Budget(calls=args.max_calls, tokens=args.max_tokens, seconds=args.max_seconds)
    model = AzureModel(budget) if args.mode == "azure" else None
    database = make_url(os.environ["DATABASE_URL"])
    pid_file = root / "postgres/postmaster.pid"
    if (database.drivername != "postgresql+psycopg" or database.host != "127.0.0.1"
            or database.username != "cosmabot_lab" or database.database != "w1a_agent_lab"
            or database.query or not pid_file.is_file()
            or str(database.port) != pid_file.read_text().splitlines()[3]):
        raise ValueError("Lab requires the exact owned loopback PostgreSQL cluster")
    engine = create_engine(database, pool_size=6, max_overflow=0)
    # Run the actual schema and SQL guards against the verified owned cluster.
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(REPO / "alembic.ini")), "head")
    report = {"schema": "cosmabot-agent-lab.v1", "started_at": datetime.now(UTC).isoformat(),
              "status": "running", "mode": args.mode, "synthetic_only": True,
              "model": model.name if model else "deterministic-replay-no-model",
              "concurrency": args.concurrency, "fault": args.fault, "schema_setup": "alembic-upgrade-head",
              "journey_input_mode": args.journey_inputs,
              "budget": {"max_calls": args.max_calls, "max_tokens": args.max_tokens, "max_seconds": args.max_seconds},
              "source": source_record(), "episodes": [], "coverage": [],
              "limits": ["Tool runner is local lab code; the deployed chat adapter remains text-only.",
                         "Artifacts are evaluation records, not a second clinical record or approval queue.",
                         "Human-only steps use a separate scripted synthetic provider.",
                         "Agent episodes use typed notes; physical recording acceptance is tracked separately.",
                         "Vendor endpoints are synthetic. No real deliveries, bookings, payments or live account reads.",
                         "Outcome text checks are regression heuristics, not clinical quality certification."]}
    report["limits"].append("Journey uses three invented intake, Session Prep and Scribe output fixtures. "
        "Chief creates actual private draft assignments; saved drafts still require human review. "
        "This does not generate those inputs through live intake or recording services.")
    selected = list(case_catalog()) if args.cases == "all" else args.cases.split(",")
    report["expected_episode_count"] = len(selected) * args.repeat
    report["grading"] = {"version": VERSION}
    write_report(root, report)
    try:
        for repeat in range(args.repeat):
            for key in selected:
                case = case_catalog()[key]
                episode = f"{key}-{repeat + 1}"
                started = time.monotonic()
                app = Application(engine, case, lambda role, kind, episode=episode, **v: store.event(episode, role, kind, **v))
                if key == "clinic":
                    from lab.clinic import run_clinic

                    result = run_clinic(app, store, episode, model, args.fault, args.concurrency)
                elif key == "connectors":
                    from lab.connector_checks import run_connectors

                    result = run_connectors(app, store, episode)
                elif key.startswith("fax_"):
                    from lab.fax_teams import run_provider

                    result = run_provider(app, store, episode, key.removeprefix("fax_"))
                elif key.startswith("bot_"):
                    from lab.bot_capabilities import run_capabilities

                    result = run_capabilities(app, store, episode, key.removeprefix("bot_"))
                elif key == "review_loops":
                    from lab.review_process import run_reviews

                    result = run_reviews(app, store, episode, model, concurrency=args.concurrency)
                elif key == "inbound":
                    from lab.inbound_workflow import run_inbound

                    result = run_inbound(app, store, episode)
                elif key == "journey":
                    from lab.journey import run_journey

                    result = run_journey(app, store, episode, model, args.fault,
                                         concurrency=args.concurrency, input_mode=args.journey_inputs)
                else:
                    world = World(store, episode, case, app, model, concurrency=args.concurrency, fault=args.fault)
                    world.run_agent("chief")
                    artifacts = []
                    for role in ("chief", "visit_prep", "scribe", "research", "follow_up"):
                        try:
                            artifacts.append(store.read(episode, role, role))
                        except Exception:
                            pass
                    final = next((a for a in artifacts if a["role"] == "follow_up"), None)
                    text = final["body"].lower() if final else ""
                    checks = {
                        "five_attributed_artifacts": len(artifacts) == 5,
                        "no_agent_failures": not world.failures,
                        "follow_up_consumed_three_exact_artifacts": bool(final and len(final["dependencies"]) == 3),
                        **grade(case, text),
                    }
                    application_result = {"status": "drafts_only", "external_effects": 0}
                    if case.deliver and all(checks.values()):
                        try:
                            application_result = app.exercise_follow_up(next(a for a in artifacts if a["role"] == "scribe"), final)
                            checks["real_f8_loop"] = application_result["status"] == "closed"
                        except Exception as error:
                            checks["real_f8_loop"] = False
                            application_result = {"status": "failed", "error": type(error).__name__}
                            store.event(episode, "simulated_provider", "application_failure", error=type(error).__name__)
                    result = {"id": episode, "case": key, "title": case.title,
                              "passed": all(checks.values()), "checks": checks,
                              "duration_ms": round((time.monotonic() - started) * 1000),
                              "tool_calls": world.tool_count, "failures": world.failures,
                              "artifacts": artifacts, "application": application_result}
                report["episodes"].append(result)
                from lab.bot_capabilities import aggregate_lessons

                report["bot_lessons"] = aggregate_lessons(report["episodes"])
                report["usage"] = {"model_calls": budget.calls, "tokens": budget.tokens}
                report["coverage"] = [{"case": k, "title": c.title,
                    "agent_episodes": sum(e["case"] == k for e in report["episodes"]),
                    "agent_passes": sum(e["case"] == k and e["passed"] for e in report["episodes"]),
                    "application_contracts": "not_run", "selectors": case_checks(k)} for k, c in case_catalog().items()]
                write_report(root, report)
                print(f"{episode}: {'PASS' if result['passed'] else 'FAIL'}; {result['tool_calls']} tools; {result['duration_ms']} ms", flush=True)
    finally:
        engine.dispose()
        if model:
            model.close()
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["status"] = "passed" if len(report["episodes"]) == len(selected) * args.repeat and all(e["passed"] for e in report["episodes"]) else "failed"
        write_report(root, report)
    return 0 if report["status"] == "passed" else 1


def contracts(args):
    selected = list(case_catalog()) if args.cases == "all" else args.cases.split(",")
    paths = list(dict.fromkeys(path for key in selected for path in case_checks(key)))
    evidence = args.output / "application-checks"
    command = [sys.executable, str(REPO / "scripts/check-backend-local.py"), "--profile", "workspace",
               "--postgres-bin", str(args.postgres_bin), "--evidence-dir", str(evidence), *paths]
    # Check runner provides its own clean environment and separate owned PostgreSQL.
    with (args.output / "application-checks.log").open("w") as stream:
        result = subprocess.run(command, cwd=REPO, stdout=stream, stderr=subprocess.STDOUT, timeout=1200)
    report = json.loads((args.output / "report.json").read_text())
    report["application_checks"] = {"exit_code": result.returncode, "paths": paths,
                                     "evidence": str(evidence), "evidence_level": "existing application contracts with synthetic provider ports"}
    for row in report["coverage"]:
        if row["case"] in selected:
            row["application_contracts"] = "passed" if result.returncode == 0 else "failed; inspect application-checks"
    if result.returncode:
        report["status"] = "failed"
    write_report(args.output, report)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Local synthetic CosmaBot agent lab. Real model tools, saved handoffs, and application checks.")
    parser.add_argument("--mode", choices=("azure", "replay"), default="replay")
    parser.add_argument("--cases", default="all", help="all, or comma-separated case keys: " + ",".join(case_catalog()))
    parser.add_argument("--repeat", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--concurrency", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--journey-inputs", choices=("tool", "inline"), default="inline",
                        help="Deliver admitted journey inputs upfront with exact acknowledgment, or fetch by tool for comparison")
    parser.add_argument("--fault", choices=("none", "read_timeout", "lost_save_reply"), default="none")
    parser.add_argument("--checks", action="store_true", help="Also execute existing application workflow regression suites")
    parser.add_argument("--capture-checks", action="store_true", help="Also qualify actual recorder, encrypted queue and Swift audio code with generated signals")
    parser.add_argument("--capture-stress-checks", action="store_true", help="Include recorder checks plus full one-hour capture and three-hour native PCM endurance (about 15 minutes)")
    parser.add_argument("--output", type=Path, help="New output directory outside repository; default is a new temporary directory")
    parser.add_argument("--postgres-bin", type=Path, default=Path("/opt/homebrew/opt/postgresql@16/bin"))
    parser.add_argument("--max-calls", type=int, default=250)
    parser.add_argument("--max-tokens", type=int, default=300000)
    parser.add_argument("--max-seconds", type=int, default=1800)
    parser.add_argument("--serve", action="store_true", help="Serve the finished dashboard read-only on loopback")
    parser.add_argument("--port", type=int, default=5190)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if any(k not in case_catalog() for k in args.cases.split(",")) and args.cases != "all":
        parser.error("Unknown case")
    if not 1 <= args.max_calls <= 500 or not 1 <= args.max_tokens <= 500000 or not 1 <= args.max_seconds <= 3600:
        parser.error("Budget out of bounds: calls<=500, tokens<=500000, seconds<=3600")
    if args.worker:
        if os.environ.get("COSMABOT_LAB_CHILD") != "owned-synthetic-cluster":
            parser.error("Worker must be started by the lab launcher")
        return worker(args)
    if (REPO / ".env").exists():
        parser.error("Use a checkout without .env")
    args.output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix="cosmabot-agent-lab-"))
    if args.output.is_relative_to(REPO):
        parser.error("Keep outputs outside the repository")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use a new empty output directory")
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.chmod(0o700)
    if not all((args.postgres_bin / name).is_file() for name in ("initdb", "pg_ctl", "createdb")):
        parser.error("PostgreSQL tools unavailable; provide --postgres-bin")
    print(f"Lab output: {args.output}", flush=True)
    command = [sys.executable, "-m", "lab.runner", "--worker", "--mode", args.mode, "--cases", args.cases,
               "--repeat", str(args.repeat), "--concurrency", str(args.concurrency), "--fault", args.fault,
               "--journey-inputs", args.journey_inputs,
               "--output", str(args.output), "--max-calls", str(args.max_calls),
               "--max-tokens", str(args.max_tokens), "--max-seconds", str(args.max_seconds)]
    cleanup = False
    try:
        with OwnedPostgres(args.output, args.postgres_bin) as cluster:
            env = {name: os.environ[name] for name in ("HOME", "USER", "LOGNAME", "TMPDIR") if name in os.environ}
            tool_dirs = [str(Path(found).parent) for tool in ("az", "git") if (found := shutil.which(tool))]
            env.update(PATH=os.pathsep.join([str(Path(sys.executable).parent), *tool_dirs, os.defpath]),
                PYTHONPATH=str(REPO / "src") + os.pathsep + str(REPO), PYTHONDONTWRITEBYTECODE="1",
                DATABASE_URL=cluster.url, COSMABOT_LAB_CHILD="owned-synthetic-cluster", COSMAS_ENV="synth_os",
                DATA_MODE="synthetic", AUTH_MODE="synth_headers", SYNTH_SEED="true", WORKSPACE_ENABLED="true",
                BLOB_BACKEND="local", BLOB_ROOT=str(args.output / "blobs"),
                CORS_ALLOWED_ORIGINS="http://127.0.0.1:5173", REDIS_URL="redis://127.0.0.1:1/0",
                WORKSPACE_LLM_BACKEND="disabled", LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")
            with (args.output / "runner.log").open("w") as log:
                code = run_owned_child(command, env=env, log=log, timeout=args.max_seconds + 90)
        cleanup = True
    finally:
        cleanup = not (args.output / "postgres/postmaster.pid").exists()
        (args.output / "cleanup.json").write_text(json.dumps({"owned_postgres_stopped": cleanup,
             "temporary_password_file_removed": not (args.output / "temporary-postgres-password").exists()}))
    if args.checks and (args.output / "report.json").exists():
        code = contracts(args) or code
    if (args.capture_checks or args.capture_stress_checks) and (args.output / "report.json").exists():
        from lab.capture_checks import run_capture_checks

        code = run_capture_checks(args) or code
    print((args.output / "runner.log").read_text(), end="", flush=True)
    print(f"Dashboard: {args.output / 'report.html'}", flush=True)
    if args.serve:
        from lab.report import serve

        serve(args.output, args.port)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
