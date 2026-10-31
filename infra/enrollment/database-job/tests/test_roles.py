"""Always run against an owned temporary PostgreSQL cluster; no skip/remote URL."""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
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
        subprocess.run([str(pg / "initdb"), "-D", str(data), "-U", "foundation_rehearsal", "--pwfile", str(work / "password"), "--auth-local=trust", "--auth-host=scram-sha-256", "--no-locale", "--encoding=UTF8"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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
                # Model provider ownership and PostgreSQL's original PUBLIC cT
                # default. Never pre-revoke it to make qualification pass.
                connection.execute(text("CREATE ROLE azure_superuser NOLOGIN"))
                for name in ("azure_maintenance", "azure_sys"):
                    connection.execute(text(f"CREATE DATABASE {name} OWNER azure_superuser"))
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
    assert receipt == {"contract_version": "enrollment-database-check.v2", "schema_version": "enrollment_20261031_v1",
        "runtime_role_checked": True, "immutable_receipt_checked": True, "grant_table_count": 9,
        "managed_database_ownership_acl_checked": True, "provider_database_default_access_allowed": True,
        "provider_database_count": 2, "azure_connectivity_qualified": False,
        "restore_qualified": False, "journey_qualified": False}


def test_provider_defaults_survive_bootstrap_migrate_and_metadata_only_check(roles):
    with roles["admin"].connect() as connection:
        original = list(connection.execute(text("SELECT datname,datdba,datacl FROM pg_database WHERE datname IN ('azure_maintenance','azure_sys') ORDER BY datname")))
    connections = []

    def connected(connection):
        connections.append(connection.engine.url.database)

    for engine in roles.values():
        event.listen(engine, "engine_connect", connected)
    try:
        database.bootstrap(roles)
        database.migrate(roles)
        assert database.check(roles)["managed_database_ownership_acl_checked"]
    finally:
        for engine in roles.values():
            event.remove(engine, "engine_connect", connected)
    assert connections and set(connections) == {database.DATABASE}
    with roles["admin"].connect() as connection:
        assert list(connection.execute(text("SELECT datname,datdba,datacl FROM pg_database WHERE datname IN ('azure_maintenance','azure_sys') ORDER BY datname"))) == original
        assert len(original) == 2
    with roles["runtime"].connect() as connection:
        for name in database.PROVIDER_DATABASES:
            assert connection.execute(text("SELECT has_database_privilege(current_user,:name,'CONNECT'),has_database_privilege(current_user,:name,'TEMP'),has_database_privilege(current_user,:name,'CREATE')"), {"name": name}).first() == (True, True, False)


@pytest.fixture
def provider_admin(roles):
    fixture_admin = create_engine(roles["admin"].url.set(username="foundation_rehearsal"))
    try:
        yield fixture_admin
    finally:
        fixture_admin.dispose()


@pytest.mark.parametrize("public_privileges", [None, "CONNECT", "TEMPORARY"])
def test_stronger_provider_public_restrictions_qualify_without_rewriting_acl(roles, provider_admin, public_privileges):
    with provider_admin.begin() as connection:
        connection.execute(text("REVOKE ALL ON DATABASE azure_sys FROM PUBLIC"))
        if public_privileges:
            connection.execute(text(f"GRANT {public_privileges} ON DATABASE azure_sys TO PUBLIC"))
        original = connection.execute(text("SELECT datdba,datacl FROM pg_database WHERE datname='azure_sys'")).first()
    try:
        database.bootstrap(roles)
        database.migrate(roles)
        assert database.check(roles)["provider_database_count"] == 2
        with provider_admin.connect() as connection:
            assert connection.execute(text("SELECT datdba,datacl FROM pg_database WHERE datname='azure_sys'")).first() == original
    finally:
        with provider_admin.begin() as connection:
            connection.execute(text("GRANT CONNECT,TEMPORARY ON DATABASE azure_sys TO PUBLIC"))


def test_provider_public_grant_option_catalog_corruption_is_rejected(roles, provider_admin):
    # Ordinary GRANT forbids grant options to PUBLIC. Only this owned local
    # fixture superuser fabricates a damaged catalog entry; it is rolled back.
    with provider_admin.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("""UPDATE pg_database SET datacl=ARRAY[
                makeaclitem('azure_superuser'::regrole,'azure_superuser'::regrole,'CREATE,CONNECT,TEMPORARY',false),
                makeaclitem(0,'azure_superuser'::regrole,'CONNECT',true)] WHERE datname='azure_sys'"""))
            # Runtime's separate connection cannot see an uncommitted catalog
            # change; qualify metadata through the same local test transaction.
            with pytest.raises(database.ProviderBaselineMismatch) as captured:
                database.check_provider_databases(connection)
            projection = database.failure_receipt("check", "check", captured.value)["provider_baseline_projection"]
            assert any(row["grantee"] == "PUBLIC" and row["grantable"] for database_row in projection for row in database_row["acl"])
        finally:
            transaction.rollback()
    assert database.check(roles)["runtime_role_checked"]


@pytest.mark.parametrize("field,value", [("grantable", 0), ("grantee_oid", False), ("grantable", None)])
def test_provider_metadata_rejects_boolean_integer_coercions_and_missing_field(roles, field, value):
    with roles["runtime"].connect() as connection:
        class MetadataConnection:
            def execute(self, statement):
                rows = [dict(row) for row in connection.execute(statement).mappings()]
                if value is None:
                    rows[0].pop(field)
                else:
                    rows[0][field] = value
                return SimpleNamespace(mappings=lambda: rows)

        with pytest.raises(database.ProviderBaselineMismatch):
            database.check_provider_databases(MetadataConnection())


@pytest.mark.parametrize("grant,revoke,tag", [
    ("GRANT CONNECT ON DATABASE azure_sys TO enrollment_runtime", "REVOKE CONNECT ON DATABASE azure_sys FROM enrollment_runtime", "enrollment_runtime"),
    ("GRANT CREATE ON DATABASE azure_sys TO PUBLIC", "REVOKE CREATE ON DATABASE azure_sys FROM PUBLIC", "PUBLIC"),
    ("ALTER DATABASE azure_sys OWNER TO enrollment_runtime", "ALTER DATABASE azure_sys OWNER TO azure_superuser", "enrollment_runtime"),
])
def test_provider_acl_rejects_added_application_grant_public_create_and_app_owner(roles, provider_admin, monkeypatch, capsys, grant, revoke, tag):
    try:
        with provider_admin.begin() as connection:
            connection.execute(text(grant))
        monkeypatch.setattr(database.sys, "argv", ["database.py", "check"])
        monkeypatch.setattr(database, "engines_from_environment", lambda operation: {"runtime": roles["runtime"]})
        assert database.main() == 1
        output = capsys.readouterr()
        assert output.out == ""
        failure = json.loads(output.err)
        assert {key: value for key, value in failure.items() if key != "provider_baseline_projection"} == {
            "error": "enrollment_database_preparation_failed", "class": "ValueError",
            "operation": "check", "stage": "check", "code": "managed_database_ownership_acl"}
        assert tag in json.dumps(failure["provider_baseline_projection"])
    finally:
        with provider_admin.begin() as connection:
            connection.execute(text(revoke))
    assert database.check(roles)["runtime_role_checked"]


@pytest.mark.parametrize("change", ["grantee", "grantor", "owner"])
def test_unknown_provider_acl_roles_are_rejected_and_not_disclosed(roles, provider_admin, change):
    # These are local fixture mutations, not Azure permission changes.
    with provider_admin.begin() as connection:
        connection.execute(text('CREATE ROLE "private-sentinel" NOLOGIN'))
        if change == "owner":
            connection.execute(text('ALTER DATABASE azure_sys OWNER TO "private-sentinel"'))
        else:
            connection.execute(text('GRANT CONNECT ON DATABASE azure_sys TO "private-sentinel" WITH GRANT OPTION'))
            if change == "grantor":
                connection.execute(text('SET ROLE "private-sentinel"'))
                connection.execute(text('GRANT CONNECT ON DATABASE azure_sys TO PUBLIC'))
                connection.execute(text('RESET ROLE'))
    try:
        with pytest.raises(database.ProviderBaselineMismatch) as captured:
            database.check(roles)
        failure = database.failure_receipt("check", "check", captured.value)
        assert failure["code"] == "managed_database_ownership_acl"
        assert "private-sentinel" not in json.dumps(failure)
        projection = next(row for row in failure["provider_baseline_projection"] if row["database"] == "azure_sys")
        if change == "owner":
            assert projection["owner"] == "unknown"
        else:
            assert any(row[change] == "unknown" for row in projection["acl"])
    finally:
        with provider_admin.begin() as connection:
            if change == "owner":
                connection.execute(text('ALTER DATABASE azure_sys OWNER TO azure_superuser'))
            else:
                connection.execute(text('REVOKE ALL ON DATABASE azure_sys FROM "private-sentinel" CASCADE'))
            connection.execute(text('DROP ROLE "private-sentinel"'))
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
