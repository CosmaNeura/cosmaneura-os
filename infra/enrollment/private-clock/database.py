"""Manual, journal-only PostgreSQL bootstrap/check; no vendor or public API calls.

Inputs are selected private KV secrets. All CLI failures are fixed messages;
driver errors, binding documents, credentials and database URLs are never logged.
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlparse
from uuid import UUID, uuid5

from psycopg import sql
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool

from cosmas_os.enrollment.private_clock_lab import (
    BOX_NAMESPACE,
    ClockLabBinding,
    ClockStateBase,
    PostgresClockJournal,
    unique_json,
)

DATABASE = "cosmabot_enrollment_clock_lab"
LOGINS = {"admin": "clock_bootstrap", "a": "clock_journal_a", "b": "clock_journal_b"}
TABLE = "private_stripe_clock_journal"
OWNERS = "private_clock_role_bindings"


def input_bindings(raw: str, host: str, hashes: dict[str, str]) -> dict[str, ClockLabBinding]:
    if not 1 <= len(raw.encode()) <= 25000 or set(hashes) != {"a", "b"}:
        raise ValueError("bounded protected two-binding document required")
    value = unique_json(raw.encode())
    if (set(value) != {"contract_version", "synthetic_only", "bindings"}
            or value["contract_version"] != "enrollment-private-clock-setup.v1" or value["synthetic_only"] is not True
            or set(value["bindings"]) != {"a", "b"}):
        raise ValueError("private synthetic-only journal setup required")
    result = {slot: ClockLabBinding.model_validate(value["bindings"][slot]) for slot in ("a", "b")}
    def owned_origin(value):
        parsed = urlparse(value)
        return parsed.scheme == "https" and parsed.netloc == parsed.hostname and parsed.path == "" and not parsed.query and not parsed.fragment and bool(parsed.hostname and parsed.hostname.endswith(".staging.cosmas.ai"))
    for slot, binding in result.items():
        if (binding.sha256 != hashes[slot] or binding.journal_host != host or binding.journal_port != 5432
                or binding.journal_database != DATABASE or not binding.synthetic_only
                or not re.fullmatch(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.clerk\.accounts\.dev", binding.issuer)
                or str(UUID(binding.practice_id)) != binding.practice_id or binding.box_id != str(uuid5(BOX_NAMESPACE, binding.practice_id))
                or any(not owned_origin(v) for v in (binding.app_origin, binding.api_origin, binding.workspace_api_origin))
                or not binding.workspace_url.endswith("/chief") or not owned_origin(binding.workspace_url.removesuffix("/chief"))):
            raise ValueError("exact protected binding/server/Dev Clerk required")
    for field in ("practice_id", "box_id", "organization_id", "customer_id", "clock_id"):
        if len({getattr(b, field) for b in result.values()}) != 2:
            raise ValueError("separate protected composition scopes required")
    return result


def environment(operation: str) -> tuple[dict[str, Engine], dict[str, ClockLabBinding]]:
    host = os.environ.get("PRIVATE_CLOCK_DATABASE_HOST", "")
    if not re.fullmatch(r"psql-cbot-clock-stg-[a-z0-9]{6,8}\.postgres\.database\.azure\.com", host):
        raise ValueError("owned private journal server required")
    hashes = {s: os.environ.get(f"PRIVATE_CLOCK_BINDING_{s.upper()}_SHA256", "") for s in ("a", "b")}
    bindings = input_bindings(os.environ.get("PRIVATE_CLOCK_BINDINGS", ""), host, hashes)
    engines = {}
    for role in (("admin", "a", "b") if operation == "bootstrap" else ("a", "b")):
        url = make_url(os.environ.get(f"PRIVATE_CLOCK_{role.upper()}", ""))
        if (url.drivername != "postgresql+psycopg" or url.host != host or url.port not in (None, 5432)
                or url.database != DATABASE or url.username != LOGINS[role] or not url.password
                or dict(url.query) != {"sslmode": "verify-full", "sslrootcert": "/etc/ssl/certs/ca-certificates.crt"}):
            raise ValueError("exact journal-only role/TLS credential required")
        engines[role] = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10}, hide_parameters=True)
    return engines, bindings


def role_flags(connection, role: str):
    return connection.execute(text("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit,rolcanlogin FROM pg_roles WHERE rolname=:role"), {"role": role}).first()


def check_role(connection, role: str) -> None:
    if role_flags(connection, role) != (False, False, False, False, False, False, True):
        raise ValueError("unexpected journal role authority")
    if connection.execute(text("SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=:role"), {"role": role}).scalar_one():
        raise ValueError("journal role may not assume another role")


VALIDATE = """
CREATE OR REPLACE FUNCTION public.private_clock_validate() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE v jsonb; initial bigint; keys integer; distinct_keys integer;
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'immutable journal row'; END IF;
  IF TG_OP = 'UPDATE' AND NEW.binding_sha256 IS DISTINCT FROM OLD.binding_sha256 THEN
    RAISE EXCEPTION 'immutable binding';
  END IF;
  SELECT initial_frozen_time INTO STRICT initial FROM public.private_clock_role_bindings
    WHERE binding_sha256=NEW.binding_sha256;
  IF octet_length(NEW.state::text)>2048 OR json_typeof(NEW.state)<>'object' THEN RAISE EXCEPTION 'invalid journal'; END IF;
  SELECT count(*),count(DISTINCT key) INTO keys,distinct_keys FROM json_each(NEW.state);
  v := NEW.state::jsonb;
  IF keys<>6 OR distinct_keys<>6 OR NOT v ?& ARRAY['binding_sha256','high_water','pending_target','subscription_id','trial_start','trial_end']
    OR jsonb_typeof(v->'binding_sha256')<>'string' OR v->>'binding_sha256'<>NEW.binding_sha256
    OR jsonb_typeof(v->'high_water')<>'number' OR (v->>'high_water') !~ '^[0-9]+$'
    OR (v->>'high_water')::bigint<initial OR (v->>'high_water')::bigint>253402300799 THEN RAISE EXCEPTION 'invalid journal'; END IF;
  IF v->'subscription_id'='null'::jsonb THEN
    IF v->'trial_start'<>'null'::jsonb OR v->'trial_end'<>'null'::jsonb THEN RAISE EXCEPTION 'invalid trial'; END IF;
  ELSE
    IF jsonb_typeof(v->'subscription_id')<>'string' OR (v->>'subscription_id') !~ '^sub_[A-Za-z0-9]+$'
      OR jsonb_typeof(v->'trial_start')<>'number' OR (v->>'trial_start') !~ '^[0-9]+$'
      OR jsonb_typeof(v->'trial_end')<>'number' OR (v->>'trial_end') !~ '^[0-9]+$'
      OR (v->>'trial_start')::bigint<1 OR (v->>'trial_end')::bigint>253402300799
      OR (v->>'trial_end')::bigint-(v->>'trial_start')::bigint<>1209600 THEN RAISE EXCEPTION 'invalid trial'; END IF;
  END IF;
  IF v->'pending_target'<>'null'::jsonb THEN
    IF jsonb_typeof(v->'pending_target')<>'number' OR (v->>'pending_target') !~ '^[0-9]+$'
      OR v->'trial_end'='null'::jsonb OR (v->>'pending_target')::bigint<(v->>'high_water')::bigint
      OR (v->>'pending_target')::bigint NOT BETWEEN (v->>'trial_end')::bigint-1 AND (v->>'trial_end')::bigint+1
      THEN RAISE EXCEPTION 'invalid target'; END IF;
  END IF;
  IF TG_OP='UPDATE' THEN
    IF (v->>'high_water')::bigint<(OLD.state->>'high_water')::bigint THEN RAISE EXCEPTION 'journal rewind'; END IF;
    IF OLD.state->>'subscription_id' IS NOT NULL AND
      (v->'subscription_id' IS DISTINCT FROM OLD.state::jsonb->'subscription_id' OR
       v->'trial_start' IS DISTINCT FROM OLD.state::jsonb->'trial_start' OR
       v->'trial_end' IS DISTINCT FROM OLD.state::jsonb->'trial_end') THEN RAISE EXCEPTION 'immutable trial'; END IF;
    IF OLD.state->>'pending_target' IS NOT NULL AND
      NOT (v->'pending_target'=OLD.state::jsonb->'pending_target' OR
           v->'pending_target'='null'::jsonb AND v->>'high_water'=OLD.state->>'pending_target') THEN RAISE EXCEPTION 'unsettled target'; END IF;
  END IF;
  RETURN NEW;
END $$;
"""


def bootstrap(engines: dict[str, Engine], bindings: dict[str, ClockLabBinding]) -> None:
    with engines["admin"].begin() as c:
        if c.execute(text("SELECT current_database()")).scalar_one() != DATABASE:
            raise ValueError("wrong journal database")
        names = set(c.execute(text("SELECT datname FROM pg_database")).scalars())
        required = {DATABASE, "postgres", "template0", "template1"}
        if not required.issubset(names) or names - required - {"azure_maintenance", "azure_sys"}:
            raise ValueError("unrelated server database")
        if set(inspect(c).get_table_names()) - {TABLE, OWNERS} or inspect(c).get_view_names():
            raise ValueError("unrelated journal database table")
        driver = c.connection.driver_connection
        if driver is None:
            raise ValueError("open journal driver connection required")
        cursor = driver.cursor()
        try:
            c.execute(text(f"CREATE TABLE IF NOT EXISTS {OWNERS} (role_name text PRIMARY KEY, binding_sha256 varchar(64) UNIQUE NOT NULL, initial_frozen_time bigint NOT NULL)"))
            expected = {(LOGINS[s], b.sha256, b.initial_frozen_time) for s, b in bindings.items()}
            saved = set(c.execute(text(f"SELECT role_name,binding_sha256,initial_frozen_time FROM {OWNERS}")).all())
            if saved and saved != expected:
                raise ValueError("immutable journal ownership differs")
            for slot, b in bindings.items():
                role = LOGINS[slot]
                if role_flags(c, role) is None:
                    cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}").format(sql.Identifier(role), sql.Literal(engines[slot].url.password)))
                else:
                    check_role(c, role)
                    cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(engines[slot].url.password)))
                check_role(c, role)
                c.execute(text(f"INSERT INTO {OWNERS} VALUES (:role,:hash,:initial) ON CONFLICT DO NOTHING"), {"role": role, "hash": b.sha256, "initial": b.initial_frozen_time})
            ClockStateBase.metadata.create_all(c)
            if set(c.execute(text(f"SELECT binding_sha256 FROM {TABLE}")).scalars()) - {b.sha256 for b in bindings.values()}:
                raise ValueError("foreign journal row")
            c.execute(text(VALIDATE))
            c.execute(text("REVOKE ALL ON FUNCTION public.private_clock_validate() FROM PUBLIC"))
            c.execute(text(f"DROP TRIGGER IF EXISTS private_clock_guard ON {TABLE}"))
            c.execute(text(f"CREATE TRIGGER private_clock_guard BEFORE INSERT OR UPDATE OR DELETE ON {TABLE} FOR EACH ROW EXECUTE FUNCTION public.private_clock_validate()"))
            for b in bindings.values():
                initial = {"binding_sha256": b.sha256, "high_water": b.initial_frozen_time, "pending_target": None,
                           "subscription_id": None, "trial_start": None, "trial_end": None}
                c.execute(text(f"INSERT INTO {TABLE} (binding_sha256,state) VALUES (:hash,CAST(:state AS json)) ON CONFLICT DO NOTHING"), {"hash": b.sha256, "state": json.dumps(initial)})
            # The owner is the isolated bootstrap account; no runtime ownership or DDL.
            for db in (DATABASE, "postgres", "template1"):
                cursor.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(db)))
            cursor.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            cursor.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, {}, {}").format(sql.Identifier(LOGINS["a"]), sql.Identifier(LOGINS["b"])))
            cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES REVOKE ALL ON TABLES FROM PUBLIC, {}, {}").format(sql.Identifier(LOGINS["a"]), sql.Identifier(LOGINS["b"])))
            c.execute(text(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY"))
            for slot, b in bindings.items():
                role = LOGINS[slot]
                cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(DATABASE), sql.Identifier(role)))
                cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
                cursor.execute(sql.SQL("GRANT SELECT, UPDATE ON {} TO {}").format(sql.Identifier(TABLE), sql.Identifier(role)))
                for setting, value in (("statement_timeout", "15s"), ("lock_timeout", "5s"), ("idle_in_transaction_session_timeout", "15s")):
                    cursor.execute(sql.SQL("ALTER ROLE {} IN DATABASE {} SET {} = {}").format(sql.Identifier(role), sql.Identifier(DATABASE), sql.Identifier(setting), sql.Literal(value)))
                cursor.execute(sql.SQL("DROP POLICY IF EXISTS {} ON {}").format(sql.Identifier(role), sql.Identifier(TABLE)))
                predicate = sql.SQL("binding_sha256 = {} AND state->>'binding_sha256' = {}").format(sql.Literal(b.sha256), sql.Literal(b.sha256))
                cursor.execute(sql.SQL("CREATE POLICY {} ON {} TO {} USING ({}) WITH CHECK ({})").format(sql.Identifier(role), sql.Identifier(TABLE), sql.Identifier(role), predicate, predicate))
            cursor.execute(sql.SQL("DROP POLICY IF EXISTS clock_bootstrap ON {}").format(sql.Identifier(TABLE)))
            cursor.execute(sql.SQL("CREATE POLICY clock_bootstrap ON {} TO {} USING (binding_sha256 IN ({},{})) WITH CHECK (binding_sha256 IN ({},{}))").format(
                sql.Identifier(TABLE), sql.Identifier(LOGINS["admin"]), sql.Literal(bindings["a"].sha256), sql.Literal(bindings["b"].sha256),
                sql.Literal(bindings["a"].sha256), sql.Literal(bindings["b"].sha256)))
            c.execute(text(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY"))
            policies = set(c.execute(text("SELECT policyname FROM pg_policies WHERE schemaname='public' AND tablename=:table"), {"table": TABLE}).scalars())
            if policies != set(LOGINS.values()):
                raise ValueError("foreign journal policy")
        finally:
            cursor.close()
    check(engines, bindings)


def check(engines: dict[str, Engine], bindings: dict[str, ClockLabBinding]) -> None:
    for slot, binding in bindings.items():
        with engines[slot].begin() as c:
            role = LOGINS[slot]
            if c.execute(text("SELECT current_user,current_database()")).one() != (role, DATABASE):
                raise ValueError("wrong journal role/database")
            check_role(c, role)
            if set(c.execute(text(f"SELECT binding_sha256 FROM {TABLE}")).scalars()) != {binding.sha256}:
                raise ValueError("journal RLS scope mismatch")
            for privilege in ("INSERT", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                if c.execute(text("SELECT has_table_privilege(current_user,:table,:privilege)"), {"table": TABLE, "privilege": privilege}).scalar_one():
                    raise ValueError("excess journal table authority")
            if (c.execute(text("SELECT has_schema_privilege(current_user,'public','CREATE')")).scalar_one()
                    or c.execute(text("SELECT has_database_privilege(current_user,current_database(),'TEMP')")).scalar_one()
                    or c.execute(text("SELECT has_table_privilege(current_user,:table,'SELECT')"), {"table": OWNERS}).scalar_one()):
                raise ValueError("excess journal database authority")
            # No-op UPDATE checks the database fence while preserving a pending advance.
            c.execute(text(f"UPDATE {TABLE} SET state=state WHERE binding_sha256=:hash"), {"hash": binding.sha256})
        journal = PostgresClockJournal(engines[slot], binding)
        journal.read()


def main() -> int:
    engines = {}
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"bootstrap", "check"}:
            raise ValueError("explicit private journal operation required")
        operation = sys.argv[1]
        engines, bindings = environment(operation)
        (bootstrap if operation == "bootstrap" else check)(engines, bindings)
        print(json.dumps({"operation": operation, "journal_checked": True, "bindings": 2, "hosted_qualified": False}))
        return 0
    except Exception as error:
        print(json.dumps({"error": "private_clock_database_failed", "class": type(error).__name__}), file=sys.stderr)
        return 1
    finally:
        for engine in engines.values():
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
