"""Owned loopback PostgreSQL role/RLS/restart checks; no Azure/vendor transport."""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid5

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from cosmas_os.enrollment.domain import EnrollmentError
from cosmas_os.enrollment.private_clock_lab import ClockLabBinding, PostgresClockJournal

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))


def load(name):
    spec = importlib.util.spec_from_file_location(f"private_clock_{name}", SOURCE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


db, prep = load("database"), load("prepare")


def binding(slot, host, port):
    practice = f"00000000-0000-4000-8000-00000000000{1 if slot == 'a' else 2}"
    return ClockLabBinding(synthetic_only=True, practice_id=practice,
        box_id=str(uuid5(UUID("f17d7eec-39ee-5d1e-8071-0d94453d91bd"), practice)), organization_id=f"org_example{slot}", owner_subject=f"user_example{slot}",
        issuer="https://example.clerk.accounts.dev", app_origin="https://onboarding.staging.cosmas.ai",
        api_origin=f"https://clock-{slot}.staging.cosmas.ai", workspace_url=f"https://practice-{slot}.staging.cosmas.ai/chief",
        workspace_api_origin=f"https://api.practice-{slot}.staging.cosmas.ai", source_commit="a"*40, image_sha256="b"*64,
        stripe_account_id="acct_example", stripe_base_price_id="price_examplebase", stripe_additional_price_id="price_exampleadditional",
        stripe_portal_configuration_id="bpc_example", stripe_api_version="2025-09-30.clover", customer_id=f"cus_example{slot}",
        clock_id=f"clock_example{slot}", initial_frozen_time=1700000000, journal_host=host, journal_port=port, journal_database=db.DATABASE)


@pytest.fixture
def journal_server(tmp_path):
    pg = Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    work = tmp_path / "pg"
    work.mkdir(mode=0o700)
    password = work / "password"
    password.write_text("synthetic-private-clock-test-only")
    password.chmod(0o600)
    data = work / "data"
    subprocess.run([str(pg / "initdb"), "-D", str(data), "-U", "rehearsal", "--pwfile", str(password), "--auth-local=trust", "--auth-host=scram-sha-256"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    subprocess.run([str(pg / "pg_ctl"), "-D", str(data), "-l", str(work / "server.log"), "-o", f"-h 127.0.0.1 -p {port} -k /private/tmp", "-w", "start"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    root = create_engine(URL.create("postgresql+psycopg", username="rehearsal", password=password.read_text(), host="127.0.0.1", port=port, database="postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True)
    engines = {}
    try:
        with root.connect() as c:
            c.execute(text("CREATE ROLE clock_bootstrap LOGIN NOSUPERUSER CREATEDB CREATEROLE PASSWORD 'synthetic-bootstrap-only'"))
            c.execute(text(f"CREATE DATABASE {db.DATABASE} OWNER clock_bootstrap"))
            # Mirrors the Azure administrator's ownership of these initial system DBs.
            c.execute(text("ALTER DATABASE postgres OWNER TO clock_bootstrap"))
            c.execute(text("ALTER DATABASE template1 OWNER TO clock_bootstrap"))
            c.execute(text("CREATE DATABASE azure_maintenance"))
            c.execute(text("CREATE DATABASE azure_sys"))
        for role, login in db.LOGINS.items():
            pw = "synthetic-bootstrap-only" if role == "admin" else f"synthetic-{role}-only"
            engines[role] = create_engine(URL.create("postgresql+psycopg", username=login, password=pw, host="127.0.0.1", port=port, database=db.DATABASE), hide_parameters=True)
        bindings = {s: binding(s, "127.0.0.1", port) for s in ("a", "b")}
        yield engines, bindings, root
    finally:
        for engine in [root, *engines.values()]:
            engine.dispose()
        subprocess.run([str(pg / "pg_ctl"), "-D", str(data), "-w", "stop", "-m", "fast"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def test_two_roles_enforce_own_binding_and_immutable_restart(journal_server):
    engines, bindings, _ = journal_server
    db.bootstrap(engines, bindings)
    a = PostgresClockJournal(engines["a"], bindings["a"])
    b = PostgresClockJournal(engines["b"], bindings["b"])
    a.subscription({"id": "sub_examplea", "trial_start": 1700000000, "trial_end": 1701209600})
    a.target("before")
    # Check + repeated bootstrap preserve a pending target and the original trial.
    db.check(engines, bindings)
    db.bootstrap(engines, bindings)
    assert PostgresClockJournal(engines["a"], bindings["a"]).read()["pending_target"] == 1701209599
    a.observe(1701209599)
    assert b.read()["high_water"] == 1700000000
    with engines["b"].begin() as c:
        assert c.execute(text(f"UPDATE {db.TABLE} SET state=state WHERE binding_sha256=:hash"), {"hash": bindings["a"].sha256}).rowcount == 0
    bad = a.read()
    for mutation in ({"high_water": 1700000000}, {"trial_end": 1701209601}, {"binding_sha256": bindings["b"].sha256}):
        with pytest.raises(DBAPIError), engines["a"].begin() as c:
            c.execute(text(f"UPDATE {db.TABLE} SET state=CAST(:state AS json)"), {"state": json.dumps({**bad, **mutation})})
    for statement in (f"DELETE FROM {db.TABLE}", f"TRUNCATE {db.TABLE}", f"INSERT INTO {db.TABLE} SELECT * FROM {db.TABLE}", "CREATE TABLE unauthorized (id integer)"):
        with pytest.raises(DBAPIError), engines["a"].begin() as c:
            c.execute(text(statement))
    with pytest.raises(DBAPIError), engines["a"].begin() as c:
        c.execute(text("SET ROLE clock_journal_b"))
    with pytest.raises(EnrollmentError):
        PostgresClockJournal(engines["a"], bindings["b"])
    assert a.read()["high_water"] == 1701209599


def test_foreign_user_database_denies_before_bootstrap(journal_server):
    engines, bindings, root = journal_server
    with root.connect() as c:
        c.execute(text("CREATE DATABASE unrelated_customer"))
    with pytest.raises(ValueError, match="unrelated server"):
        db.bootstrap(engines, bindings)
    with engines["admin"].connect() as c:
        assert c.execute(text("SELECT count(*) FROM pg_roles WHERE rolname='clock_journal_a'")).scalar_one() == 0


def test_protected_prepare_snapshot_job_revision_and_no_secret_values(tmp_path):
    f = tmp_path / "foundation.json"
    f.write_bytes((SOURCE / "tests/foundation.json").read_bytes())
    f.chmod(0o600)
    values = {"subscription_id": json.loads(f.read_text())["subscription_id"], "tenant_id": json.loads(f.read_text())["tenant_id"],
        "resource_name_suffix": "mock1234", "foundation_file": str(f)}
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(values))
    inputs.chmod(0o600)
    directory = tmp_path / "operator"
    assert not prep.prepare(inputs, directory)["applied"]
    assert os.stat(directory / "admin.password").st_mode & 0o777 == 0o600
    assert "postgres_admin_password" not in (directory / "inputs.tfvars.json").read_text()
    assert json.loads((directory / "inputs.tfvars.json").read_text())["binding_sha256"] == {}
    assert prep.child_environment(directory)["TF_VAR_postgres_admin_password"]
    config = tmp_path / "job.json"
    config.write_text(json.dumps({"operation": "check", "create_job": False, "image": "", "secret_references": {}, "runtime_principal_ids": {}}))
    config.chmod(0o600)
    key = (directory / "encryption.passphrase").read_bytes()
    assert prep.configure_job(directory, config)["revision"] == 1
    config.write_text(json.dumps({"operation": "check", "create_job": False, "image": "", "secret_references": {}, "runtime_principal_ids": {}, "binding_sha256": {"a": "a"*64, "b": "b"*64}}))
    assert prep.configure_job(directory, config)["revision"] == 2
    config.write_text(json.dumps({"operation": "check", "create_job": False, "image": "", "secret_references": {}, "runtime_principal_ids": {}, "binding_sha256": {}}))
    with pytest.raises(ValueError, match="frozen"):
        prep.configure_job(directory, config)
    assert (directory / "encryption.passphrase").read_bytes() == key
    prep.child_environment(directory)
    injected = directory / "module/injected.auto.tfvars.json"
    injected.write_text('{"create_job":true}')
    with pytest.raises(ValueError, match="unreviewed snapshot"):
        prep.child_environment(directory)
    injected.unlink()
    (directory / "module/database.py").write_text("tampered source")
    with pytest.raises(ValueError, match="source changed"):
        prep.child_environment(directory)


def test_binding_hash_and_seeder_scope_reject_foreign_inputs():
    host = "psql-cbot-clock-stg-mock1234.postgres.database.azure.com"
    bindings = {s: binding(s, host, 5432) for s in ("a", "b")}
    raw = json.dumps({"contract_version": "enrollment-private-clock-setup.v1", "synthetic_only": True, "bindings": {s: b.model_dump() for s, b in bindings.items()}})
    hashes = {s: b.sha256 for s, b in bindings.items()}
    assert set(db.input_bindings(raw, host, hashes)) == {"a", "b"}
    with pytest.raises(ValueError):
        db.input_bindings(raw, "another.postgres.database.azure.com", hashes)
    with pytest.raises(ValueError):
        db.input_bindings(raw, host, {"a": hashes["b"], "b": hashes["a"]})
    seeder = load("seed_secret")
    with pytest.raises(ValueError):
        seeder.seed({}, "enrollment-database-url", Path("/unused"), Path("/unused"))
