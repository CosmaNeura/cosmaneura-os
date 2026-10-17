"""Actual guarded logical restore of invented personal patient custody.

No Azure/PITR, live receiver, worker activation, external blobs or device storage
is qualified. The guard owns the loopback cluster; this test owns one fresh clone.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration import test_scheduling_patient_setup as shared

from cosmas_os.application import scheduling_patient_setup as setup
from cosmas_os.application import services, workspace
from cosmas_os.application.workspace_fingerprint import fingerprint_workspace_database
from cosmas_os.models import AppointmentObservation, Operation, SchedulingPatientAccount
from cosmas_os.ports.scheduling_patient_setup import PatientVerification, patient_digest
from cosmas_os.scheduling_patient_models import (
    SchedulingPatientMappingReview,
    SchedulingPatientSetupRequest,
    SchedulingPatientSetupSnapshot,
)

PATIENT_TABLES = (
    "scheduling_patient_accounts", "scheduling_patient_setup_requests",
    "scheduling_patient_setup_snapshots", "scheduling_patient_mapping_reviews",
)
FRESH_SNAPSHOT = """
import os, sys
sys.path.insert(0, sys.argv[1])
from cosmas_os.application.workspace_fingerprint import fingerprint_workspace_database
assert 'cosmas_os.api.app' not in sys.modules
print(fingerprint_workspace_database(os.environ['DATABASE_URL'], cosmas_env='synth_os',
    data_mode='synthetic', require_verify_full=False).sanitized_json())
"""


def snapshot(engine: Engine):
    return fingerprint_workspace_database(engine.url.render_as_string(hide_password=False),
        cosmas_env="synth_os", data_mode="synthetic", database_engine=engine, require_verify_full=False)


def fresh_snapshot(engine: Engine, output: Path):
    result = subprocess.run([sys.executable, "-I", "-c", FRESH_SNAPSHOT,
        str(Path(__file__).resolve().parents[2] / "src")], cwd=output,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1",
             "DATABASE_URL": engine.url.render_as_string(hide_password=False)},
        capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, "fresh isolated fingerprint refused"
    return json.loads(result.stdout)


def custody(session: Session, f, saved):
    requests = session.scalars(select(SchedulingPatientSetupRequest).where(
        SchedulingPatientSetupRequest.workspace_id == f.wid).order_by(
            SchedulingPatientSetupRequest.ordinal)).all()
    assert len(requests) == 2 and [row.kind for row in requests] == ["preview", "confirm"]
    summaries = []
    for request in requests:
        snap = session.scalar(select(SchedulingPatientSetupSnapshot).where(
            SchedulingPatientSetupSnapshot.request_id == request.id))
        assert snap is not None
        assert request.request_sha256 == patient_digest("cosmas-scheduling-patient-command.v1",
            {"workspace_id": request.workspace_id, "request": request.command})
        assert request.source_context_sha256 == patient_digest("cosmas-scheduling-patient-context.v1", request.source_context)
        assert snap.payload_sha256 == patient_digest("cosmas-scheduling-patient-payload.v1", snap.payload)
        assert snap.source_sha256 == patient_digest("cosmas-scheduling-patient-source.v1", {
            "request_id": request.id, "request_sha256": request.request_sha256,
            "account_id": request.account_id, "binding_sha256": request.binding_sha256,
            "connected_at": request.connected_at.astimezone(UTC).isoformat(timespec="microseconds"),
            "grant_sha256": request.grant_sha256, "source_context_sha256": request.source_context_sha256,
            "payload_sha256": snap.payload_sha256})
        summaries.append({"request_id": request.id, "request_sha256": request.request_sha256,
            "snapshot_id": snap.id, "payload_sha256": snap.payload_sha256, "source_sha256": snap.source_sha256})
    review = session.scalar(select(SchedulingPatientMappingReview).where(
        SchedulingPatientMappingReview.request_id == saved["request_id"]))
    assert review is not None and review.reviewed_same_patient and review.reviewed_exact_identity
    mapping = session.get(SchedulingPatientAccount, review.mapping_id)
    snap = session.get(SchedulingPatientSetupSnapshot, review.snapshot_id)
    assert mapping is not None and snap is not None
    verified = PatientVerification.model_validate(snap.payload)
    assert verified.identity.birth_date is None
    assert (mapping.box_id, mapping.patient_link_id, mapping.practice_id, mapping.patient_id,
            mapping.reviewed_by, mapping.evidence_ref, mapping.reviewed_at) == (
        f.box, f.patient, str(verified.practice_id), str(verified.patient_id), f.owner,
        "scheduling-patient:v1:" + review.id, review.created_at)
    assert review.mapping_sha256 == patient_digest("cosmas-scheduling-patient-mapping.v1", {
        "review_id": review.id, "mapping_id": review.mapping_id,
        "request_id": requests[1].id, "request_sha256": requests[1].request_sha256,
        "box_id": f.box, "owner_id": f.owner, "patient_link_id": f.patient,
        "account_id": f.account, "practice_id": str(verified.practice_id),
        "patient_id": str(verified.patient_id), "identity_sha256": verified.identity.identity_sha256,
        "subject_revision": verified.identity.subject_revision})
    assert saved["mapping"] == {"mapping_id": mapping.id, "mapping_sha256": review.mapping_sha256,
        "identity_sha256": verified.identity.identity_sha256, "subject_revision": verified.identity.subject_revision}
    assert summaries[1]["source_sha256"] == saved["source_sha256"]
    assert session.scalar(select(func.count()).select_from(Operation).where(Operation.box_id == f.box)) == 0
    return {"requests": summaries, "mapping_id": mapping.id, "review_id": review.id,
        "mapping_sha256": review.mapping_sha256}


def test_committed_personal_patient_custody_survives_actual_logical_restore(engine, monkeypatch, tmp_path):
    url = engine.url
    # Fail before subprocess or CREATE DATABASE unless inside the established guard.
    assert os.environ.get("COSMAS_ENV") == "synth_os"
    assert url.drivername == "postgresql+psycopg" and url.host == "127.0.0.1"
    assert url.database == "w1a_local_checks" and url.username == "cosmas_local_checks" and url.password
    assert url.port is not None and not url.query and os.environ.get("PGPASSWORD") == url.password
    tools = {name: shutil.which(name) for name in ("pg_dump", "pg_restore")}
    assert all(tools.values()), "guard must supply pinned PostgreSQL tools"
    assert len({str(Path(cast(str, value)).resolve().parent) for value in tools.values()}) == 1
    clone = "w1a_patient_restore_" + uuid4().hex[:16]
    clone_url = url.set(database=clone)
    clone_engine = create_engine(clone_url, hide_parameters=True)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True)
    dump = tmp_path / "invented-patient-custody.dump"
    created = False
    generator = None
    commands = []
    quote = engine.dialect.identifier_preparer.quote_identifier
    report: dict[str, Any] = {"kind": "synthetic-patient-logical-restore", "passed": False,
        "azure_or_pitr_qualified": False, "external_blobs_or_devices_qualified": False,
        "live_receiver": False, "worker_activated": False}
    try:
        with Session(engine) as owned, monkeypatch.context() as patch:
            seed = services.provision_box(services.Container(owned), "Invented patient logical restore " + uuid4().hex)
            generator = cast(Any, shared.case).__wrapped__(owned, seed, patch)
            f = next(generator)
            observed = shared.preview(f)
            command = shared.confirmation(f, observed)
            saved = shared.confirm(f, command)
            assert not owned.in_transaction() and f.port.calls == ["preview", "verify"]
            assert not saved["source_withheld"] and saved["mapping"]
            with Session(engine) as check:
                expected_custody = custody(check, f, saved)
                original = workspace.read(check, f.box, f.owner, f.wid)
                assert original["note"] == f.before["note"] and original["entries"] == f.before["entries"]
                assert check.scalar(text("SELECT current_user")) == url.username
                assert check.scalar(text("SELECT pg_get_userbyid(datdba)=current_user FROM pg_database WHERE datname=current_database()")) is True
            before = snapshot(engine)
            assert set(PATIENT_TABLES) <= set(before.tables)
            assert all(cast(int, before.tables[name]["count"]) > 0 for name in PATIENT_TABLES)
            assert fresh_snapshot(engine, tmp_path) == json.loads(before.sanitized_json())
            process_env = {"PATH": os.defpath, "PGPASSWORD": url.password, "PGCONNECT_TIMEOUT": "5", "LANG": "C", "LC_ALL": "C"}
            common = ["--host", url.host, "--port", str(url.port), "--username", url.username, "--no-password"]

            def pg(name, arguments):
                argv = [cast(str, tools[name]), *common, *arguments]
                result = subprocess.run(argv, cwd=tmp_path, env=process_env,
                    capture_output=True, timeout=90, check=False)
                commands.append({"tool": name, "exit_code": result.returncode})
                assert result.returncode == 0, "guarded PostgreSQL logical copy failed"

            dump.touch(mode=0o600, exist_ok=False)
            pg("pg_dump", ["--format=custom", "--file", str(dump), url.database])
            dump.chmod(0o600)
            with admin.connect() as connection:
                assert connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=:name)"), {"name": clone}) is False
                connection.execute(text(f"CREATE DATABASE {quote(clone)} TEMPLATE template0 OWNER {quote(url.username)}"))
                created = True
            pg("pg_restore", ["--exit-on-error", "--dbname", clone, str(dump)])
            restored = snapshot(clone_engine)
            assert restored == before
            assert fresh_snapshot(clone_engine, tmp_path) == json.loads(before.sanitized_json())
            with Session(clone_engine) as restored_session:
                assert custody(restored_session, f, saved) == expected_custody
                rf = SimpleNamespace(**{**vars(f), "s": restored_session, "engine": clone_engine})
                calls = list(f.port.calls)
                assert setup.inspect(restored_session, f.box, f.owner, f.wid, f.identity,
                    request_id=saved["request_id"], configuration=f.configuration) == saved
                assert shared.confirm(rf, command) == saved and f.port.calls == calls
                current = workspace.read(restored_session, f.box, f.owner, f.wid)
                assert current["note"] == original["note"] and current["entries"] == original["entries"]
                restored_session.rollback()
            assert snapshot(clone_engine) == before, "reopen must not change stored custody"
            for table in ("scheduling_patient_setup_requests", "scheduling_patient_setup_snapshots", "scheduling_patient_mapping_reviews"):
                with clone_engine.begin() as connection, pytest.raises(DBAPIError) as refusal:
                    connection.execute(text(f"DELETE FROM {quote(table)} WHERE workspace_id=CAST(:id AS uuid)"), {"id": f.wid})
                assert getattr(refusal.value.orig, "sqlstate", None) == "23514"
            assert snapshot(clone_engine) == before
            # A changed current grant never resurrects private identity or provider work.
            f.grant = "c" * 64
            with Session(clone_engine) as restored_session:
                rf = SimpleNamespace(**{**vars(f), "s": restored_session, "engine": clone_engine})
                masked = shared.confirm(rf, command)
                assert masked["source_withheld"] and masked["mapping"] is masked["preview"] is None
                assert {k: masked[k] for k in ("request_id", "request_sha256", "source_sha256")} == {
                    k: saved[k] for k in ("request_id", "request_sha256", "source_sha256")}
                assert "Invented Jordan" not in json.dumps(masked) and f.port.calls == calls
            assert snapshot(clone_engine) == before
            # Restoring historical custody does not authorize changed live inputs.
            f.grant = "b" * 64
            with Session(clone_engine) as restored_session:
                appointment = restored_session.get(AppointmentObservation, original["appointment_id"])
                assert appointment is not None
                appointment.external_id = str(uuid4())
                restored_session.commit()
                rf = SimpleNamespace(**{**vars(f), "s": restored_session, "engine": clone_engine})
                masked = shared.confirm(rf, command)
                assert masked["source_withheld"] and masked["mapping"] is masked["preview"] is None
                assert {k: masked[k] for k in ("request_id", "request_sha256", "source_sha256")} == {
                    k: saved[k] for k in ("request_id", "request_sha256", "source_sha256")}
                assert "Invented Jordan" not in json.dumps(masked) and f.port.calls == calls
                assert custody(restored_session, f, saved) == expected_custody
                current = workspace.read(restored_session, f.box, f.owner, f.wid)
                assert current["note"] == original["note"] and current["entries"] == original["entries"]
                restored_session.rollback()
            after_source = snapshot(clone_engine)
            assert after_source.aggregate_sha256 != before.aggregate_sha256
            assert after_source.catalog == before.catalog
            assert {name for name in before.tables if after_source.tables[name] != before.tables[name]} == {
                "appointment_observations"}
            assert all(after_source.tables[name] == before.tables[name] for name in (
                *PATIENT_TABLES, "workspace_notes", "workspace_note_reviews"))
            assert fresh_snapshot(clone_engine, tmp_path) == json.loads(after_source.sanitized_json())
            # A corrupted schema guard is detectable even with identical stored rows.
            with clone_engine.begin() as connection:
                connection.execute(text("ALTER TABLE scheduling_patient_setup_requests DISABLE TRIGGER immutable_patient_setup_request"))
            changed = snapshot(clone_engine)
            assert changed.tables == after_source.tables and changed.catalog["triggers"] != after_source.catalog["triggers"]
            assert changed.aggregate_sha256 != after_source.aggregate_sha256
            report.update(passed=True, schema_revision=before.schema_revision,
                table_count=len(before.tables), patient_tables={name: before.tables[name] for name in PATIENT_TABLES},
                aggregate_sha256=before.aggregate_sha256, dump_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),
                custody_commitment_sha256=hashlib.sha256(json.dumps(expected_custody, sort_keys=True).encode()).hexdigest(),
                actual_dump_restore=True, full_catalog_and_data_equal=True, fresh_process_equal=True,
                exact_historical_replay=True, changed_grant_masked=True, changed_restored_source_masked=True,
                receiver_calls=len(f.port.calls),
                immutable_delete_refused=True, changed_guard_detected=True, clinical_note_unchanged=True)
    finally:
        try:
            if generator is not None:
                generator.close()
        finally:
            clone_engine.dispose()
            try:
                if created:
                    with admin.connect() as connection:
                        connection.execute(text(f"DROP DATABASE {quote(clone)} WITH (FORCE)"))
                        assert connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=:name)"), {"name": clone}) is False
                    report["owned_clone_dropped"] = True
            finally:
                admin.dispose()
                dump.unlink(missing_ok=True)
                report.update(commands=commands, dump_removed=not dump.exists())
                (tmp_path / "patient-logical-restore.json").write_text(json.dumps(report, indent=2) + "\n")
