"""Always run against an owned temporary PostgreSQL cluster; no skip/remote URL."""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from cosmas_os.enrollment.domain import BAA_DOC_ID, BAA_SHA256, BAA_VERSION, HumanIdentity
from cosmas_os.enrollment.service import EnrollmentService
from cosmas_os.enrollment.synthetic import SyntheticCommerce, synthetic_settings

spec = importlib.util.spec_from_file_location("enrollment_database_admin_roles", Path(__file__).resolve().parents[1] / "database.py")
database = importlib.util.module_from_spec(spec)
spec.loader.exec_module(database)


@pytest.fixture(scope="module")
def roles():
    pg = Path(os.environ.get("ENROLLMENT_FOUNDATION_POSTGRES_BIN", subprocess.check_output(["pg_config", "--bindir"], text=True).strip()))
    with tempfile.TemporaryDirectory(prefix="enrollment-foundation-role-pg-") as directory:
        work = Path(directory)
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        password = "synthetic-foundation-role-check-only"
        (work / "password").write_text(password)
        (work / "password").chmod(0o600)
        data = work / "data"
        subprocess.run([str(pg / "initdb"), "-D", str(data), "-U", "foundation_rehearsal", "--pwfile", str(work / "password"), "--auth-local=trust", "--auth-host=scram-sha-256"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        started = False
        engines = {}
        try:
            subprocess.run([str(pg / "pg_ctl"), "-D", str(data), "-l", str(work / "postgres.log"), "-o", f"-h 127.0.0.1 -p {port} -k {work}", "-w", "start"], check=True, stdout=subprocess.DEVNULL)
            started = True
            superuser = create_engine(f"postgresql+psycopg://foundation_rehearsal:{password}@127.0.0.1:{port}/postgres", isolation_level="AUTOCOMMIT")
            with superuser.connect() as connection:
                connection.execute(text(f"CREATE ROLE enrollment_bootstrap LOGIN CREATEROLE CREATEDB PASSWORD '{password}'"))
                connection.execute(text("CREATE DATABASE cosmabot_enrollment OWNER enrollment_bootstrap"))
                connection.execute(text("ALTER DATABASE postgres OWNER TO enrollment_bootstrap"))
                connection.execute(text("ALTER DATABASE template1 OWNER TO enrollment_bootstrap"))
                # Azure-managed service databases are not owned by bootstrap.
                for name in ("azure_maintenance", "azure_sys"):
                    connection.execute(text(f"CREATE DATABASE {name}"))
                    connection.execute(text(f"REVOKE ALL ON DATABASE {name} FROM PUBLIC"))
            superuser.dispose()
            for role, login in database.LOGINS.items():
                engines[role] = create_engine(f"postgresql+psycopg://{login}:{password}@127.0.0.1:{port}/cosmabot_enrollment", hide_parameters=True)
            # Azure-like bootstrap is not superuser, unlike convenient test URLs.
            with engines["admin"].connect() as connection:
                assert connection.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")).scalar_one() is False
            database.bootstrap(engines)
            database.migrate(engines)
            yield engines
        finally:
            for engine in engines.values():
                engine.dispose()
            if started:
                subprocess.run([str(pg / "pg_ctl"), "-D", str(data), "-w", "stop", "-m", "fast"], check=True, stdout=subprocess.DEVNULL)


def test_bootstrap_migration_and_grants_are_recoverable_without_superuser(roles):
    database.bootstrap(roles)
    database.migrate(roles)
    receipt = database.check(roles)
    assert receipt["runtime_role_checked"] and receipt["immutable_receipt_checked"]
    assert receipt["grant_table_count"] == 9
    assert not receipt["restore_qualified"] and not receipt["journey_qualified"]


def test_managed_system_databases_keep_their_original_owner_and_closed_access(roles):
    with roles["admin"].connect() as connection:
        original = list(connection.execute(text("SELECT datname,datdba,datacl FROM pg_database WHERE datname IN ('azure_maintenance','azure_sys') ORDER BY datname")))
    database.bootstrap(roles)
    with roles["admin"].connect() as connection:
        assert list(connection.execute(text("SELECT datname,datdba,datacl FROM pg_database WHERE datname IN ('azure_maintenance','azure_sys') ORDER BY datname"))) == original
        assert len(original) == 2
    assert database.check(roles)["runtime_role_checked"]


def test_managed_database_public_access_reports_bounded_failure_and_preserves_authority(roles, monkeypatch, capsys):
    # Reproduce provider-default PUBLIC connectivity on this owned local
    # database only. No Azure/system database permissions are changed here.
    fixture_admin = create_engine(roles["admin"].url.set(username="foundation_rehearsal"))
    try:
        with fixture_admin.begin() as connection:
            connection.execute(text("GRANT CONNECT ON DATABASE azure_sys TO PUBLIC"))
        monkeypatch.setattr(database.sys, "argv", ["database.py", "check"])
        monkeypatch.setattr(database, "engines_from_environment", lambda operation: {"runtime": roles["runtime"]})
        assert database.main() == 1
        output = capsys.readouterr()
        assert output.out == ""
        assert json.loads(output.err) == {"error": "enrollment_database_preparation_failed", "class": "ValueError",
            "operation": "check", "stage": "check", "code": "runtime_managed_database_access"}
    finally:
        with fixture_admin.begin() as connection:
            connection.execute(text("REVOKE CONNECT ON DATABASE azure_sys FROM PUBLIC"))
        fixture_admin.dispose()
    assert database.check(roles)["runtime_role_checked"]


def test_foreign_user_database_refuses_bootstrap_and_check(roles):
    with roles["admin"].connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("CREATE DATABASE unrelated_user_database"))
    try:
        with pytest.raises(ValueError):
            database.bootstrap(roles)
        with pytest.raises(ValueError):
            database.check(roles)
    finally:
        with roles["admin"].connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text("DROP DATABASE unrelated_user_database"))


def test_restricted_runtime_supports_durable_enrollment_checkout_webhook_and_receipt(roles):
    settings = synthetic_settings()
    commerce = SyntheticCommerce(settings)
    service = EnrollmentService(sessionmaker(roles["runtime"], expire_on_commit=False), settings, commerce)
    owner = HumanIdentity(settings.clerk_issuer, "user_role_owner", "sess_role_owner", "owner@example.invalid", "Role Example")
    service.status(owner)
    state = service.profile(owner, "roles-profile", {"expected_revision": 0, "display_name": "Role Example", "title": "Owner"})
    state = service.practice(owner, "roles-practice", {"expected_revision": state["revision"], "legal_name": "Example Role Practice LLC", "display_name": "Example Practice",
        "address_line1": "123 Example Road", "address_line2": "", "city": "Example City", "region": "NY", "postal_code": "10001", "country": "US", "administrative_email": "office@example.invalid", "human_seats": 2, "covered_entity": True})
    state = service.accept(owner, "roles-accept", {"expected_revision": state["revision"], "doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256,
        "signature_name": "Role Example", "signature_title": "Owner", "authority_confirmed": True, "accepted": True})
    service.record_workspace(state["practice"]["id"], box_id=str(uuid4()), organization_id="org_rolesexample", url="https://app.example.invalid/chief", proof_sha256="a" * 64)
    body = {"expected_revision": service.status(owner)["revision"]}
    first = service.checkout(owner, "roles-checkout", body)
    assert service.checkout(owner, "roles-checkout", body) == first
    assert commerce.create_count == 1
    checkout = next(iter(commerce.sessions.values()))
    commerce.complete(checkout["id"])
    raw, signature = commerce.signed_event("checkout.session.completed", checkout, "evt_role_checkout")
    assert service.ingest(raw, signature)
    assert service.reconcile_pending()["processed"] == 1
    assert service.status(owner)["stage"] == "ready"
    assert service.receipt(owner)["document"]["sha256"] == BAA_SHA256


@pytest.mark.parametrize("statement", [
    "CREATE TABLE unauthorized_table(id integer)",
    "CREATE ROLE unauthorized_role",
    "SET ROLE enrollment_migrator",
    "ALTER ROLE enrollment_runtime CREATEDB",
    "TRUNCATE enrollment_accounts CASCADE",
    "UPDATE enrollment_baa_acceptances SET signer_name='Changed'",
    "DELETE FROM enrollment_baa_acceptances",
])
def test_runtime_cannot_change_schema_authority_or_immutable_receipts(roles, statement):
    with roles["runtime"].begin() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text(statement))
        connection.rollback()


def test_runtime_cannot_connect_other_database(roles):
    engine = create_engine(roles["runtime"].url.set(database="postgres"))
    try:
        with pytest.raises(DBAPIError), engine.connect():
            pass
    finally:
        engine.dispose()


def test_runtime_cannot_grant_itself_agreement_update(roles):
    # PostgreSQL may issue "no privileges were granted" rather than raising.
    # Assert the authoritative privilege and actual write denial afterward.
    with roles["runtime"].begin() as connection:
        connection.execute(text("GRANT UPDATE ON enrollment_baa_acceptances TO enrollment_runtime"))
        assert connection.execute(text("SELECT has_table_privilege(current_user,'enrollment_baa_acceptances','UPDATE')")).scalar_one() is False
        with pytest.raises(DBAPIError):
            connection.execute(text("UPDATE enrollment_baa_acceptances SET signer_name='Changed'"))
        connection.rollback()


def test_migration_role_cannot_rewrite_saved_agreement_and_refuses_foreign_tables(roles):
    with roles["migration"].begin() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("UPDATE enrollment_baa_acceptances SET signer_name='Changed'"))
        connection.rollback()
    with roles["migration"].begin() as connection:
        connection.execute(text("CREATE TABLE unrelated_data(id integer)"))
    try:
        with pytest.raises(RuntimeError):
            database.migrate(roles)
    finally:
        with roles["migration"].begin() as connection:
            connection.execute(text("DROP TABLE unrelated_data"))
    assert database.check(roles)["runtime_role_checked"]
