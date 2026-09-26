"""Compare complete synthetic workspace snapshots without exporting row values.

This is a read-only recovery measurement, not permission to resume a restored
service. Identity revocations and remote results newer than the backup still
require reconciliation before activation. The frozen D3 fingerprint is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url

from cosmas_os.application.database_fingerprint import (
    DatabaseFingerprintError,
    _make_database_engine,
    _validate_database_url,
)
from cosmas_os.model_registry import metadata
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

WORKSPACE_FINGERPRINT_CONTRACT = "cosmas-os-workspace-database-fingerprint-v1"

# Catalog definitions contain no object OIDs, database names, or wall-clock times.
# Definitions and grants are hashed, not exposed in evidence or error messages.
_CATALOG_QUERIES = {
    "database_properties": """
        SELECT pg_encoding_to_char(encoding), datcollate, datctype, datlocprovider,
          daticulocale, datcollversion FROM pg_database WHERE datname=current_database()
    """,
    "database_access": """
        SELECT pg_get_userbyid(d.datdba), pg_get_userbyid(a.grantor),
          CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
          a.privilege_type, a.is_grantable
        FROM pg_database d CROSS JOIN LATERAL
          aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a
        WHERE d.datname=current_database() ORDER BY 1,2,3,4,5
    """,
    "columns": """
        SELECT c.relname, a.attnum, a.attname, format_type(a.atttypid,a.atttypmod),
          a.attnotnull, a.attidentity, a.attgenerated, pg_get_expr(d.adbin,d.adrelid)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname='public' AND c.relkind IN ('r','p')
        ORDER BY c.relname COLLATE "C", a.attnum
    """,
    "constraints": """
        SELECT c.relname, k.conname, k.contype, k.convalidated,
          k.condeferrable, k.condeferred, pg_get_constraintdef(k.oid,true)
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
        ORDER BY c.relname COLLATE "C", k.conname COLLATE "C"
    """,
    "indexes": """
        SELECT c.relname, i.relname, x.indisvalid, x.indisready, pg_get_indexdef(i.oid)
        FROM pg_index x JOIN pg_class c ON c.oid=x.indrelid
        JOIN pg_class i ON i.oid=x.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' ORDER BY c.relname COLLATE "C", i.relname COLLATE "C"
    """,
    "triggers": """
        SELECT c.relname, t.tgname, t.tgenabled, pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND NOT t.tgisinternal
        ORDER BY c.relname COLLATE "C", t.tgname COLLATE "C"
    """,
    "functions": """
        SELECT p.proname, pg_get_function_identity_arguments(p.oid),
          pg_get_functiondef(p.oid), p.prosecdef, p.proconfig
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.prokind IN ('f','p')
        ORDER BY p.proname COLLATE "C", pg_get_function_identity_arguments(p.oid) COLLATE "C"
    """,
    "policies": """
        SELECT tablename, policyname, permissive, roles, cmd, qual, with_check
        FROM pg_policies WHERE schemaname='public'
        ORDER BY tablename COLLATE "C", policyname COLLATE "C"
    """,
    "table_access": """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
          pg_get_userbyid(c.relowner), pg_get_userbyid(a.grantor),
          CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
          a.privilege_type, a.is_grantable
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,
          acldefault(CASE WHEN c.relkind='S' THEN 'S'::"char" ELSE 'r'::"char" END,c.relowner))) a
        WHERE n.nspname='public' AND c.relkind IN ('r','p','S')
        ORDER BY c.relname COLLATE "C", 4, 5, 6, 7, 8
    """,
    "function_access": """
        SELECT p.proname, pg_get_function_identity_arguments(p.oid),
          pg_get_userbyid(p.proowner), pg_get_userbyid(a.grantor),
          CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
          a.privilege_type, a.is_grantable
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
        WHERE n.nspname='public' ORDER BY 1,2,3,4,5,6,7
    """,
    "schema_access": """
        SELECT n.nspname, pg_get_userbyid(n.nspowner), pg_get_userbyid(a.grantor),
          CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
          a.privilege_type, a.is_grantable
        FROM pg_namespace n CROSS JOIN LATERAL
          aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a
        WHERE n.nspname='public' ORDER BY 1,2,3,4,5,6
    """,
    "default_access": """
        SELECT pg_get_userbyid(d.defaclrole), n.nspname, d.defaclobjtype,
          pg_get_userbyid(a.grantor),
          CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
          a.privilege_type, a.is_grantable
        FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
        CROSS JOIN LATERAL aclexplode(d.defaclacl) a
        WHERE d.defaclnamespace=0 OR n.nspname='public' ORDER BY 1,2,3,4,5,6,7
    """,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _constraint_tokens(definition: str) -> list[str]:
    """Normalize only PostgreSQL's unconstrained varchar-literal → text casts.

    pg_dump reparses an array-level cast into element-level casts. The server's
    pretty deparser already handles equivalent AND grouping. Preserve other casts,
    typmods, expressions, literal contents and token order; do not simplify SQL.
    Quoted/E/U& strings are indivisible so lookalike SQL inside a value is inert.
    """
    tokens = re.findall(r"(?:E|U&)'(?:''|\\.|[^'\\])*'|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|::|[A-Za-z_][A-Za-z0-9_$]*|[0-9]+|[^\s]", definition)
    result: list[str] = []
    index = 0
    while index < len(tokens):
        if tokens[index:index+2] == ["ARRAY", "["]:
            end = index+2
            literals: list[str] = []
            while end+3 < len(tokens):
                part = tokens[end:end+4]
                if not (part[0].startswith("'") and part[1:] == ["::", "character", "varying"]):
                    break
                literals.append(part[0])
                end += 4
                if tokens[end:end+1] != [","]:
                    break
                end += 1
            if literals and tokens[end:end+5] == ["]", "::", "text", "[", "]"]:
                result += ["ARRAY", "["]
                for position, literal in enumerate(literals):
                    if position:
                        result.append(",")
                    result += [literal, "::", "text"]
                result.append("]")
                index = end+5
                continue
        if (tokens[index].startswith("'")
                and tokens[index+1:index+6] == ["::", "character", "varying", "::", "text"]):
            result += [tokens[index], "::", "text"]
            index += 6
            continue
        result.append(tokens[index])
        index += 1
    return result


def _index_definition(definition: str) -> str:
    """Normalize only pg_dump's two literal VARCHAR-array → text[] forms.

    Unlike CHECK deparsing, index deparsing retains parentheses around the
    array cast or each element cast. Never simplify identifiers, type modifiers,
    other casts, literal contents, array ordering or any surrounding predicate.
    Unaffected definitions retain their original representation.
    """
    tokens = re.findall(r"(?:E|U&)'(?:''|\\.|[^'\\])*'|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|::|[A-Za-z_][A-Za-z0-9_$]*|[0-9]+|[^\s]", definition)
    result: list[str] = []
    index = 0
    changed = False
    while index < len(tokens):
        grouped = tokens[index:index + 3] == ["(", "ARRAY", "["]
        elementwise = tokens[index:index + 2] == ["ARRAY", "["]
        end = index + (3 if grouped else 2)
        literals: list[str] = []
        if grouped or elementwise:
            while end < len(tokens):
                literal_at = end if grouped else end + 1
                if (literal_at >= len(tokens) or not tokens[literal_at].startswith("'")
                        or tokens[literal_at + 1:literal_at + 4] != ["::", "character", "varying"]):
                    literals = []
                    break
                if elementwise and not grouped and (
                    tokens[end] != "("
                    or tokens[literal_at + 4:literal_at + 7] != [")", "::", "text"]
                ):
                    literals = []
                    break
                literals.append(tokens[literal_at])
                end = literal_at + (4 if grouped else 7)
                if tokens[end:end + 1] != [","]:
                    break
                end += 1
            suffix = ["]", ")", "::", "text", "[", "]"] if grouped else ["]"]
            if literals and tokens[end:end + len(suffix)] == suffix:
                result.extend(["ARRAY", "["])
                for position, literal in enumerate(literals):
                    if position:
                        result.append(",")
                    result.extend([literal, "::", "text"])
                result.append("]")
                index = end + len(suffix)
                changed = True
                continue
        result.append(tokens[index])
        index += 1
    return " ".join(result) if changed else definition


def _catalog_rows(name: str, rows: Any):
    for row in rows:
        value = list(row)
        if name == "constraints":
            value[-1] = _constraint_tokens(value[-1])
        elif name == "indexes":
            value[-1] = _index_definition(value[-1])
        yield value


def _rows_fingerprint(label: str, rows: Any) -> dict[str, int | str]:
    digest = hashlib.sha256(label.encode() + b"\0")
    count = 0
    for value in rows:
        data = _canonical(value)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
        count += 1
    return {"count": count, "sha256": digest.hexdigest()}


@dataclass(frozen=True)
class WorkspaceFingerprint:
    contract: str
    status: str
    schema_revision: str
    tables: dict[str, dict[str, int | str]]
    catalog: dict[str, dict[str, int | str]]
    aggregate_sha256: str

    def sanitized_json(self) -> str:
        value = asdict(self)
        value["evidence_sha256"] = hashlib.sha256(_canonical(value)).hexdigest()
        return _canonical(value).decode()


def workspace_fingerprint_failure_json() -> str:
    return _canonical({"contract": WORKSPACE_FINGERPRINT_CONTRACT, "status": "failed"}).decode()


def fingerprint_workspace_database(
    database_url: str, *, cosmas_env: str, data_mode: str,
    database_engine: Engine | None = None, require_verify_full: bool = True,
) -> WorkspaceFingerprint:
    """Read one consistent snapshot; missing or unexpected public tables fail closed.

    Role login/membership, external blobs, native Keychain and post-backup external
    changes need separate qualification. This measurement does not activate them.
    """
    local = cosmas_env == "synth_os" and not require_verify_full
    if (cosmas_env != "early_adopter_beta" and not local) or data_mode != "synthetic":
        raise DatabaseFingerprintError("database fingerprint failed")
    if local:
        try:
            target = make_url(database_url)
            if (target.drivername != "postgresql+psycopg" or not target.username or not target.password
                    or target.host not in {"127.0.0.1", "localhost", "::1"} or target.query
                    or not (target.database or "").startswith("w1a_")):
                raise ValueError()
        except Exception:
            raise DatabaseFingerprintError("database fingerprint failed") from None
    else:
        _validate_database_url(database_url, require_verify_full=require_verify_full)
    engine = database_engine
    try:
        if engine is None:
            engine = _make_database_engine(database_url)
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                connection.execute(text("SET LOCAL search_path = pg_catalog, public"))
                connection.execute(text("SET LOCAL statement_timeout = 10000"))
                connection.execute(text("SET LOCAL lock_timeout = 3000"))
                revision = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
                if revision != EXPECTED_SCHEMA_REVISION:
                    raise DatabaseFingerprintError("database fingerprint failed")
                actual = set(connection.execute(text(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f','S')"
                )).scalars())
                if actual != set(metadata.tables) | {"alembic_version"}:
                    raise DatabaseFingerprintError("database fingerprint failed")
                quote = connection.dialect.identifier_preparer.quote_identifier
                tables = {}
                for name, table in sorted(metadata.tables.items()):
                    order = ", ".join(quote(column.name) for column in table.primary_key)
                    if not order:
                        raise DatabaseFingerprintError("database fingerprint failed")
                    rows = connection.execution_options(stream_results=True).execute(text(
                        f"SELECT to_jsonb(item) FROM public.{quote(name)} item ORDER BY {order}"
                    )).scalars()
                    tables[name] = _rows_fingerprint(name, rows)
                connection.execution_options(stream_results=False)
                catalog = {name: _rows_fingerprint(name, _catalog_rows(name, connection.execute(text(query))))
                           for name, query in _CATALOG_QUERIES.items()}
    except Exception:
        raise DatabaseFingerprintError("database fingerprint failed") from None
    finally:
        if database_engine is None and engine is not None:
            try:
                engine.dispose()
            except Exception:
                raise DatabaseFingerprintError("database fingerprint failed") from None
    digest = hashlib.sha256(_canonical({"schema_revision": revision, "tables": tables, "catalog": catalog})).hexdigest()
    return WorkspaceFingerprint(WORKSPACE_FINGERPRINT_CONTRACT, "snapshot_ready", str(revision), tables, catalog, digest)
