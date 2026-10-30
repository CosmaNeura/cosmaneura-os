"""Delete one patient's live records and stored files.

The practice owner is the admin. The check lives in this function so the API
and the admin command cannot bypass it. Dry-run is the default: it counts rows
and files and writes nothing. A confirmed delete is safe to repeat.

Backups are not opened or rewritten here. The append-only audit event stores
the actor, the time, and the patient's internal id only.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cosmas_os.domain.enums import PrincipalState, PrincipalType
from cosmas_os.domain.rules import AuthorizationError, DomainError
from cosmas_os.models import AuditEvent, PatientLink, Principal

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_FILE_COLUMNS = {
    "blob_key": "uploads",
    "file_key": "uploads",
    "storage_key": "uploads",
    "object_key": "uploads",
    "audio_key": "audio",
    "audio_path": "audio",
    "export_key": "exports",
    "export_path": "exports",
}
_AUDIO_SUFFIXES = {".wav", ".m4a", ".mp3", ".flac", ".ogg", ".aac"}
_PRESERVE = frozenset({"audit_events", "alembic_version"})
_MAX_STEPS = 10000


class BlobDeleter(Protocol):
    def delete(self, key: str) -> None: ...


@dataclass(frozen=True)
class _Key:
    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class _Edge:
    child: str
    parent: str
    child_cols: tuple[str, ...]
    parent_cols: tuple[str, ...]
    deferrable: bool
    nullable: tuple[bool, ...]


@dataclass(frozen=True)
class _StoredFile:
    kind: str
    blob_key: str | None
    path: Path | None


def storage_roots(blob: object) -> list[Path]:
    """Local blob directory for the adapter the rest of the app writes to."""

    root = getattr(blob, "root", None)
    if isinstance(root, Path):
        return [root]
    if isinstance(root, str) and root:
        return [Path(root)]
    return []


def delete_patient_records(
    session: Session,
    *,
    actor_principal_id: str,
    patient_link_id: str,
    confirm: bool,
    blob: BlobDeleter | None = None,
    file_roots: Sequence[Path] = (),
    now: datetime | None = None,
) -> dict[str, object]:
    """Count or delete every row and stored file keyed to one patient."""

    actor = _require_admin(session, actor_principal_id, lock=confirm)
    patient_id = _patient_id(patient_link_id)
    statement = select(PatientLink).where(PatientLink.id == patient_id)
    if confirm:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    patient = session.scalar(statement)
    if patient is None:
        return _report(patient_id, confirm=confirm, deleted=False, tables={}, files={})
    if patient.box_id != actor.box_id:
        raise AuthorizationError("admin authority required")

    rows = _collect_rows(session, patient_id)
    files = _collect_files(session, rows, file_roots)
    counts = {table: len(keys) for table, keys in sorted(rows.items()) if keys}
    file_counts = _file_counts(files)
    if not confirm:
        return _report(
            patient_id, confirm=False, deleted=False, tables=counts, files=file_counts
        )

    try:
        # Immutability triggers keep ordinary edits append-only. This confirmed
        # admin delete is the exception, and only for the rows collected above.
        # The setting lasts until this transaction ends.
        _suspend_history_guards(session)
        _delete_files(blob, files, file_roots, _deleted_ids(rows))
        _delete_rows(session, rows)
        session.expunge_all()
        session.add(
            AuditEvent(
                box_id=actor.box_id,
                aggregate_type="patient_link",
                aggregate_id=patient_id,
                event_type="patient.records_deleted",
                actor_principal_id=actor.id,
                outcome="deleted",
                detail={},
                created_at=now or datetime.now(UTC),
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _report(patient_id, confirm=True, deleted=True, tables=counts, files=file_counts)


def _require_admin(session: Session, actor_principal_id: str, *, lock: bool) -> Principal:
    try:
        actor_id = str(UUID(actor_principal_id))
    except (TypeError, ValueError):
        raise AuthorizationError("admin authority required") from None
    statement = select(Principal).where(Principal.id == actor_id)
    if lock:
        statement = statement.with_for_update()
    principal = session.scalar(statement)
    if (
        principal is None
        or principal.principal_type != PrincipalType.HUMAN.value
        or principal.state != PrincipalState.ACTIVE.value
        or not principal.is_owner
    ):
        raise AuthorizationError("admin authority required")
    return principal


def _patient_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError):
        raise DomainError("invalid patient id") from None


def _report(
    patient_id: str,
    *,
    confirm: bool,
    deleted: bool,
    tables: Mapping[str, int],
    files: Mapping[str, int],
) -> dict[str, object]:
    return {
        "dry_run": not confirm,
        "patient_link_id": patient_id,
        "deleted": deleted,
        "tables": dict(tables),
        "files": {
            "audio": int(files.get("audio", 0)),
            "uploads": int(files.get("uploads", 0)),
            "exports": int(files.get("exports", 0)),
        },
    }


def _quote(name: str) -> str:
    if _IDENT.fullmatch(name) is None:
        raise DomainError("patient records could not be deleted")
    return '"' + name + '"'


def _load_catalog(session: Session) -> tuple[dict[str, _Key], list[_Edge], dict[str, set[str]]]:
    keys: dict[str, _Key] = {}
    for table, columns in session.execute(
        text(
            """
            SELECT child.relname,
                   (SELECT array_agg(a.attname ORDER BY k.ord)
                    FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute a
                      ON a.attrelid = con.conrelid AND a.attnum = k.attnum)
            FROM pg_constraint con
            JOIN pg_class child ON child.oid = con.conrelid
            JOIN pg_namespace ns ON ns.oid = child.relnamespace
            WHERE con.contype = 'p' AND ns.nspname = 'public'
              AND child.relkind IN ('r', 'p')
            """
        )
    ):
        if columns:
            keys[str(table)] = _Key(str(table), tuple(str(column) for column in columns))
    edges: list[_Edge] = []
    for child, parent, deferrable, child_cols, parent_cols, nullable in session.execute(
        text(
            """
            SELECT child.relname, parent.relname, con.condeferrable,
                   (SELECT array_agg(a.attname ORDER BY k.ord)
                    FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute a
                      ON a.attrelid = con.conrelid AND a.attnum = k.attnum),
                   (SELECT array_agg(a.attname ORDER BY k.ord)
                    FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute a
                      ON a.attrelid = con.confrelid AND a.attnum = k.attnum),
                   (SELECT array_agg(NOT a.attnotnull ORDER BY k.ord)
                    FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute a
                      ON a.attrelid = con.conrelid AND a.attnum = k.attnum)
            FROM pg_constraint con
            JOIN pg_class child ON child.oid = con.conrelid
            JOIN pg_class parent ON parent.oid = con.confrelid
            JOIN pg_namespace ns ON ns.oid = child.relnamespace
            JOIN pg_namespace pns ON pns.oid = parent.relnamespace
            WHERE con.contype = 'f' AND ns.nspname = 'public' AND pns.nspname = 'public'
              AND child.relkind IN ('r', 'p') AND parent.relkind IN ('r', 'p')
            """
        )
    ):
        if not child_cols or not parent_cols or not nullable:
            continue
        edges.append(
            _Edge(
                str(child),
                str(parent),
                tuple(str(column) for column in child_cols),
                tuple(str(column) for column in parent_cols),
                bool(deferrable),
                tuple(bool(flag) for flag in nullable),
            )
        )
    columns: dict[str, set[str]] = defaultdict(set)
    for table, column in session.execute(
        text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            """
        )
    ):
        columns[str(table)].add(str(column))
    return keys, edges, columns


def _collect_rows(session: Session, patient_id: str) -> dict[str, set[tuple[str, ...]]]:
    keys, edges, columns = _load_catalog(session)
    patient_key = keys.get("patient_links")
    if patient_key is None:
        raise DomainError("patient records could not be deleted")
    rows: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    rows["patient_links"].add((patient_id,))
    incoming: dict[str, list[_Edge]] = defaultdict(list)
    for edge in edges:
        incoming[edge.parent].append(edge)
    dirty = {"patient_links"}
    steps = 0
    while dirty:
        steps += 1
        if steps > _MAX_STEPS:
            raise DomainError("patient records could not be deleted")
        parent = dirty.pop()
        parent_key = keys.get(parent)
        parent_rows = rows.get(parent) or set()
        if parent_key is None or not parent_rows:
            continue
        for edge in incoming.get(parent, ()):
            if edge.child in _PRESERVE:
                raise DomainError("patient records could not be deleted")
            child_key = keys.get(edge.child)
            if child_key is None:
                raise DomainError("patient records could not be deleted")
            found = _child_rows(session, edge, parent_key, child_key, parent_rows, columns, patient_id)
            fresh = found - rows[edge.child]
            if fresh:
                rows[edge.child].update(fresh)
                dirty.add(edge.child)
    return {table: found for table, found in rows.items() if found}


def _child_rows(
    session: Session,
    edge: _Edge,
    parent_key: _Key,
    child_key: _Key,
    parent_rows: set[tuple[str, ...]],
    columns: Mapping[str, set[str]],
    patient_id: str,
) -> set[tuple[str, ...]]:
    has_patient = "patient_link_id" in columns.get(edge.child, set())
    selected = ", ".join(f"c.{_quote(column)}::text" for column in child_key.columns)
    if has_patient:
        selected += ", c.patient_link_id::text"
    match = " AND ".join(
        f"c.{_quote(child_col)}::text = p.{_quote(parent_col)}::text"
        for child_col, parent_col in zip(edge.child_cols, edge.parent_cols, strict=True)
    )
    found: set[tuple[str, ...]] = set()
    for chunk in _chunks(tuple(parent_rows), 200):
        where, params = _key_clause("p", parent_key.columns, chunk, "pk")
        statement = (
            f"SELECT {selected} FROM public.{_quote(edge.child)} AS c "
            f"WHERE EXISTS (SELECT 1 FROM public.{_quote(edge.parent)} AS p "
            f"WHERE ({where}) AND {match})"
        )
        for record in session.execute(text(statement), params):
            raw = tuple(record)
            linked = raw[-1] if has_patient else None
            identity = tuple(str(value) for value in (raw[:-1] if has_patient else raw))
            if has_patient and linked is not None and str(linked) != patient_id:
                raise DomainError("patient records are shared")
            found.add(identity)
    return found


def _chunks(rows: tuple[tuple[str, ...], ...], size: int) -> list[tuple[tuple[str, ...], ...]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _key_clause(
    alias: str, columns: Sequence[str], rows: Sequence[tuple[str, ...]], prefix: str
) -> tuple[str, dict[str, str]]:
    groups: list[str] = []
    params: dict[str, str] = {}
    for index, row in enumerate(rows):
        parts: list[str] = []
        for column_index, column in enumerate(columns):
            name = f"{prefix}_{index}_{column_index}"
            params[name] = row[column_index]
            parts.append(f"{alias}.{_quote(column)}::text = :{name}")
        groups.append("(" + " AND ".join(parts) + ")")
    return " OR ".join(groups), params


def _suspend_history_guards(session: Session) -> None:
    # Any database role can set this transaction-local flag. The immutability
    # triggers that guard ordinary clinical history allow a delete only while
    # it is on. A superuser connection also skips the remaining specialty
    # triggers for this transaction; the setting ends when the transaction does.
    session.execute(text("SELECT set_config('cosmas.patient_deletion', 'on', true)"))
    savepoint = session.begin_nested()
    try:
        session.execute(text("SET LOCAL session_replication_role = replica"))
    except Exception:
        savepoint.rollback()
        return
    savepoint.commit()


def _delete_rows(session: Session, rows: Mapping[str, set[tuple[str, ...]]]) -> None:
    keys, edges, _columns = _load_catalog(session)
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    remaining = {table for table, found in rows.items() if found and table not in _PRESERVE}
    edges_left = [
        edge
        for edge in edges
        if not edge.deferrable and edge.child in remaining and edge.parent in remaining and edge.child != edge.parent
    ]
    while remaining:
        blocked = {edge.parent for edge in edges_left if edge.child in remaining and edge.parent in remaining}
        ready = sorted(table for table in remaining if table not in blocked)
        if not ready:
            nullable = next((edge for edge in edges_left if all(edge.nullable)), None)
            if nullable is None:
                raise DomainError("patient records could not be deleted")
            _null_edge(session, nullable, keys[nullable.child], rows[nullable.child])
            edges_left = [edge for edge in edges_left if edge is not nullable]
            continue
        for table in ready:
            if table not in blocked:
                _delete_table(session, keys[table], rows[table])
                remaining.remove(table)


def _null_edge(session: Session, edge: _Edge, child_key: _Key, child_rows: set[tuple[str, ...]]) -> None:
    assignments = ", ".join(f"{_quote(column)} = NULL" for column in edge.child_cols)
    for chunk in _chunks(tuple(child_rows), 200):
        where, params = _key_clause("c", child_key.columns, chunk, "pk")
        session.execute(
            text(f"UPDATE public.{_quote(edge.child)} AS c SET {assignments} WHERE {where}"),
            params,
        )


def _delete_table(session: Session, key: _Key, row_keys: set[tuple[str, ...]]) -> None:
    for chunk in _chunks(tuple(row_keys), 200):
        where, params = _key_clause("t", key.columns, chunk, "pk")
        session.execute(text(f"DELETE FROM public.{_quote(key.table)} AS t WHERE {where}"), params)


def _deleted_ids(rows: Mapping[str, set[tuple[str, ...]]]) -> set[str]:
    return {value for found in rows.values() for key in found for value in key}


def _collect_files(
    session: Session,
    rows: Mapping[str, set[tuple[str, ...]]],
    file_roots: Sequence[Path],
) -> list[_StoredFile]:
    keys, _edges, columns = _load_catalog(session)
    stored: dict[str, _StoredFile] = {}
    for table, found in rows.items():
        key = keys.get(table)
        if key is None or not found:
            continue
        named = tuple(
            column for column in _FILE_COLUMNS if column in columns.get(table, set())
        )
        if named:
            selected = ", ".join(f"t.{_quote(column)}::text" for column in named)
            for chunk in _chunks(tuple(found), 200):
                where, params = _key_clause("t", key.columns, chunk, "pk")
                for record in session.execute(
                    text(f"SELECT {selected} FROM public.{_quote(table)} AS t WHERE {where}"),
                    params,
                ):
                    for column, value in zip(named, record, strict=True):
                        if isinstance(value, str) and value and _safe_relative(value):
                            _add_file(stored, _StoredFile(_FILE_COLUMNS[column], value, None), file_roots)
        if table == "vendor_artifacts" and {"box_id", "workspace_id", "owner_id", "artifact_id"} <= columns.get(table, set()):
            for chunk in _chunks(tuple(found), 200):
                where, params = _key_clause("t", key.columns, chunk, "pk")
                for box_id, workspace_id, owner_id, artifact_id in session.execute(
                    text(
                        "SELECT t.box_id::text, t.workspace_id::text, t.owner_id::text, "
                        "t.artifact_id::text FROM public.vendor_artifacts AS t WHERE " + where
                    ),
                    params,
                ):
                    relative = f"{box_id}/vendor-documents/{workspace_id}/{owner_id}/{artifact_id}.pdf"
                    _add_file(stored, _StoredFile("exports", relative, None), file_roots)
    deleted_ids = _deleted_ids(rows)
    for root in file_roots:
        for path in _scan(root, deleted_ids):
            _add_file(stored, _StoredFile(_kind_for(path), None, path), file_roots)
    return list(stored.values())


def _safe_relative(value: str) -> bool:
    parts = Path(value).parts
    return (
        not Path(value).is_absolute()
        and ".." not in parts
        and bool(parts)
        and parts[0] != ""
    )


def _add_file(stored: dict[str, _StoredFile], item: _StoredFile, roots: Sequence[Path]) -> None:
    path = item.path
    if path is None and item.blob_key is not None:
        for root in roots:
            candidate = _inside(root, item.blob_key)
            if candidate is not None:
                path = candidate
                break
    identity = str(path.resolve()) if path is not None and path.exists() else item.blob_key
    if identity is None:
        return
    if path is not None and path.exists():
        stored[identity] = _StoredFile(item.kind if item.blob_key is None else item.kind, item.blob_key, path)
    elif item.blob_key is not None and identity not in stored:
        stored[identity] = item


def _kind_for(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    suffix = path.suffix.lower()
    if "audio" in parts or suffix in _AUDIO_SUFFIXES:
        return "audio"
    if "exports" in parts or "vendor-documents" in parts or suffix == ".pdf":
        return "exports"
    return "uploads"


def _inside(root: Path, relative: str) -> Path | None:
    try:
        base = root.resolve()
        candidate = (base / relative).resolve()
    except OSError:
        return None
    if candidate.is_file() and candidate.is_relative_to(base) and not candidate.is_symlink():
        return candidate
    return None


def _scan(root: Path, deleted_ids: set[str]) -> list[Path]:
    try:
        base = root.resolve()
    except OSError:
        return []
    if not base.is_dir():
        return []
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(base, followlinks=False):
        current = Path(directory)
        try:
            if not current.resolve().is_relative_to(base):
                dirnames.clear()
                continue
        except OSError:
            dirnames.clear()
            continue
        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
        for name in filenames:
            path = current / name
            if path.is_symlink() or name.endswith(".meta"):
                continue
            try:
                relative_parts = set(path.resolve().relative_to(base).parts)
            except OSError:
                continue
            if relative_parts & deleted_ids:
                found.append(path)
    return found


def _file_counts(files: Sequence[_StoredFile]) -> dict[str, int]:
    counts = {"audio": 0, "uploads": 0, "exports": 0}
    for item in files:
        if item.path is not None and item.path.exists():
            counts[item.kind] += 1
    return counts


def _delete_files(
    blob: BlobDeleter | None,
    files: Sequence[_StoredFile],
    roots: Sequence[Path],
    deleted_ids: set[str],
) -> None:
    seen: set[str] = set()
    for item in files:
        if item.blob_key is not None and item.blob_key not in seen and blob is not None:
            seen.add(item.blob_key)
            try:
                blob.delete(item.blob_key)
            except Exception:
                raise DomainError("stored files could not be deleted") from None
        if item.path is not None:
            _unlink(item.path)
    for root in roots:
        _prune(root, deleted_ids)


def _unlink(path: Path) -> None:
    try:
        if path.is_file() and not path.is_symlink():
            path.unlink()
        meta = Path(str(path) + ".meta")
        if meta.is_file() and not meta.is_symlink():
            meta.unlink()
    except OSError:
        raise DomainError("stored files could not be deleted") from None


def _prune(root: Path, deleted_ids: set[str]) -> None:
    try:
        base = root.resolve()
    except OSError:
        raise DomainError("stored files could not be deleted") from None
    if not base.is_dir():
        return
    for directory, _dirnames, _filenames in os.walk(base, topdown=False, followlinks=False):
        current = Path(directory)
        if current == base or current.is_symlink():
            continue
        try:
            relative = current.resolve().relative_to(base)
        except OSError:
            raise DomainError("stored files could not be deleted") from None
        if not (set(relative.parts) & deleted_ids):
            continue
        try:
            if not any(current.iterdir()):
                current.rmdir()
        except OSError:
            raise DomainError("stored files could not be deleted") from None
