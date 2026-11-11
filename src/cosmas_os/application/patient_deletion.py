"""Delete one patient's live records and stored files.

The practice owner is the admin. Dry-run counts rows and files and writes
nothing, through ``delete_patient_keyed_records_plan``. A confirmed delete runs
only through the admin database command: it SET ROLEs to
``cosmas_patient_deletion`` and calls ``delete_patient_keyed_records``. The HTTP
route must not confirm. A repeat call is safe.

Confirmed deletes commit the database first, then remove stored files. Pending
file rows (internal ids and relative paths only) are recorded in the same
transaction so a later run can finish leftovers for that practice and report
them by count.

Backups are not opened or rewritten here. The append-only audit event stores
the actor, the time, and the patient's internal id only.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cosmas_os.domain.enums import PrincipalState, PrincipalType
from cosmas_os.domain.rules import AuthorizationError, DomainError
from cosmas_os.models import PatientLink, Principal

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
_PENDING_FILES_MSG = (
    "database delete completed; stored files pending; rerun finishes them"
)


class BlobDeleter(Protocol):
    def delete(self, key: str) -> None: ...


@dataclass(frozen=True)
class _StoredFile:
    kind: str
    blob_key: str | None
    path: Path | None
    relative_path: str | None = None


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
    actor_principal_id: str | None = None,
    patient_link_id: str,
    confirm: bool,
    blob: BlobDeleter | None = None,
    file_roots: Sequence[Path] = (),
    now: object = None,
) -> dict[str, object]:
    """Count or delete every row and stored file keyed to one patient."""

    del now
    patient_id = _patient_id(patient_link_id)
    if confirm:
        _require_deletion_role(session)
        actor = _resolve_bound_admin(session)
    elif actor_principal_id is None:
        # Admin CLI dry-run: actor comes from the session binding.
        actor = _resolve_bound_admin(session)
    else:
        actor = _require_admin(session, actor_principal_id, lock=False)

    pending_finished = 0
    if confirm:
        pending_finished = _finish_pending_files(
            session, blob, file_roots, box_id=str(actor.box_id)
        )

    statement = select(PatientLink).where(PatientLink.id == patient_id)
    if confirm:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    patient = session.scalar(statement)
    if patient is None:
        if confirm:
            session.commit()
            if pending_finished > 0:
                return _report(
                    patient_id,
                    confirm=True,
                    deleted=False,
                    tables={},
                    files={},
                    pending_files_finished=pending_finished,
                )
        raise DomainError("patient not found")
    if patient.box_id != actor.box_id:
        raise AuthorizationError("admin authority required")

    if not confirm:
        plan = _plan(session, patient_id)
        files = _collect_files_for_plan(session, plan, file_roots)
        return _report(
            patient_id,
            confirm=False,
            deleted=False,
            tables=_table_counts(plan.get("tables")),
            files=_file_counts(files),
            pending_files_finished=0,
        )

    plan = _plan(session, patient_id)
    files = _collect_files_for_plan(session, plan, file_roots)
    file_counts = _file_counts(files)
    try:
        _record_pending_files(session, patient_id, str(patient.box_id), files, file_roots)
        result = _apply_secure_deletion(session, patient_id)
        session.commit()
    except Exception:
        session.rollback()
        raise

    tables = _table_counts(result.get("tables"))
    try:
        _delete_files(blob, files, file_roots, _deleted_ids_from_plan(plan))
        _clear_pending_files(session, patient_id, files, file_roots)
        session.commit()
    except DomainError as exc:
        session.rollback()
        if str(exc) == "stored files could not be deleted":
            raise DomainError(_PENDING_FILES_MSG) from None
        raise
    except Exception:
        session.rollback()
        raise DomainError(_PENDING_FILES_MSG) from None
    return _report(
        patient_id,
        confirm=True,
        deleted=True,
        tables=tables,
        files=file_counts,
        pending_files_finished=pending_finished,
    )


def _require_deletion_role(session: Session) -> None:
    """Refuse confirmed deletes unless John's deletion role can execute the function."""

    ready = session.scalar(
        text(
            """
            SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cosmas_patient_deletion')
               AND COALESCE(
                    has_function_privilege(
                      'cosmas_patient_deletion',
                      'public.delete_patient_keyed_records(uuid)',
                      'EXECUTE'
                    ),
                    false
               )
               AND EXISTS (
                    SELECT 1
                      FROM pg_proc p
                     WHERE p.oid = to_regprocedure(
                             'public.delete_patient_keyed_records(uuid)'
                           )
                       AND p.prosecdef
               )
            """
        )
    )
    if not ready:
        raise DomainError("deletion role not configured")


def _resolve_bound_admin(session: Session) -> Principal:
    row = session.execute(
        text(
            """
            SELECT b.principal_id::text, b.box_id::text
              FROM public.patient_deletion_admin_bindings b
             WHERE b.db_role = session_user
            """
        )
    ).first()
    if row is None:
        raise AuthorizationError("admin authority required")
    if not session.scalar(
        text("SELECT pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER')")
    ):
        raise AuthorizationError("admin authority required")
    principal = session.scalar(select(Principal).where(Principal.id == str(row[0])))
    if (
        principal is None
        or principal.principal_type != PrincipalType.HUMAN.value
        or principal.state != PrincipalState.ACTIVE.value
        or not principal.is_owner
        or str(principal.box_id) != str(row[1])
    ):
        raise AuthorizationError("admin authority required")
    return principal


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
    pending_files_finished: int,
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
        "pending_files_finished": int(pending_files_finished),
    }


def _quote(name: str) -> str:
    if _IDENT.fullmatch(name) is None:
        raise DomainError("patient records could not be deleted")
    return '"' + name + '"'


def _table_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(k): int(v) for k, v in value.items()}


def _plan(session: Session, patient_id: str) -> dict[str, object]:
    raw = session.scalar(
        text("SELECT public.delete_patient_keyed_records_plan(CAST(:patient AS uuid))"),
        {"patient": patient_id},
    )
    if not isinstance(raw, dict):
        raise DomainError("patient records could not be deleted")
    return raw


def _apply_secure_deletion(session: Session, patient_id: str) -> dict[str, object]:
    # SET LOCAL ROLE reverts automatically at transaction end.
    session.execute(text("SET LOCAL ROLE cosmas_patient_deletion"))
    raw = session.scalar(
        text("SELECT public.delete_patient_keyed_records(CAST(:patient AS uuid))"),
        {"patient": patient_id},
    )
    if not isinstance(raw, dict):
        raise DomainError("patient records could not be deleted")
    return raw


def _deleted_ids_from_plan(plan: Mapping[str, object]) -> set[str]:
    found: set[str] = set()
    pks = plan.get("pks")
    if isinstance(pks, dict):
        for values in pks.values():
            if isinstance(values, list):
                found.update(str(value) for value in values)
    tables = plan.get("tables")
    if isinstance(tables, dict):
        found.update(str(key) for key in tables)
    return found


def _relative_for(path: Path, roots: Sequence[Path]) -> str | None:
    for root in roots:
        try:
            base = root.resolve()
            relative = path.resolve().relative_to(base)
        except (OSError, ValueError):
            continue
        text_path = relative.as_posix()
        if _safe_relative(text_path):
            return text_path
    return None


def _record_pending_files(
    session: Session,
    patient_id: str,
    box_id: str,
    files: Sequence[_StoredFile],
    roots: Sequence[Path],
) -> None:
    for item in files:
        relative = item.relative_path
        if relative is None and item.path is not None:
            relative = _relative_for(item.path, roots)
        if relative is None and item.blob_key is not None and _safe_relative(item.blob_key):
            relative = item.blob_key
        if relative is None or not _safe_relative(relative):
            continue
        if item.path is not None and not item.path.exists() and item.blob_key is None:
            continue
        session.execute(
            text(
                """
                INSERT INTO public.patient_deletion_pending_files (
                  patient_link_id, box_id, kind, relative_path
                ) VALUES (
                  CAST(:patient AS uuid), CAST(:box AS uuid), :kind, :path
                )
                """
            ),
            {"patient": patient_id, "box": box_id, "kind": item.kind, "path": relative},
        )


def _clear_pending_files(
    session: Session,
    patient_id: str,
    files: Sequence[_StoredFile],
    roots: Sequence[Path],
) -> None:
    paths: set[str] = set()
    for item in files:
        relative = item.relative_path
        if relative is None and item.path is not None:
            relative = _relative_for(item.path, roots)
        if relative is None and item.blob_key is not None and _safe_relative(item.blob_key):
            relative = item.blob_key
        if relative is not None:
            paths.add(relative)
    if not paths:
        session.execute(
            text(
                "DELETE FROM public.patient_deletion_pending_files "
                "WHERE patient_link_id = CAST(:patient AS uuid)"
            ),
            {"patient": patient_id},
        )
        return
    session.execute(
        text(
            """
            DELETE FROM public.patient_deletion_pending_files
             WHERE patient_link_id = CAST(:patient AS uuid)
               AND relative_path = ANY(CAST(:paths AS text[]))
            """
        ),
        {"patient": patient_id, "paths": list(paths)},
    )


def _finish_pending_files(
    session: Session,
    blob: BlobDeleter | None,
    roots: Sequence[Path],
    *,
    box_id: str,
) -> int:
    rows = list(
        session.execute(
            text(
                """
                SELECT id::text, kind, relative_path
                  FROM public.patient_deletion_pending_files
                 WHERE box_id = CAST(:box AS uuid)
                 ORDER BY created_at, id
                FOR UPDATE
                """
            ),
            {"box": box_id},
        )
    )
    if not rows:
        return 0
    finished = 0
    for pending_id, kind, relative_path in rows:
        relative = str(relative_path)
        if not _safe_relative(relative):
            continue
        deleted = False
        if blob is not None:
            try:
                blob.delete(relative)
                deleted = True
            except Exception:
                deleted = False
        for root in roots:
            path = _inside(root, relative)
            if path is not None:
                _unlink(path)
                deleted = True
        if deleted:
            session.execute(
                text(
                    "DELETE FROM public.patient_deletion_pending_files WHERE id = CAST(:id AS uuid)"
                ),
                {"id": pending_id},
            )
            finished += 1
            del kind
    return finished


def _collect_files_for_plan(
    session: Session,
    plan: Mapping[str, object],
    file_roots: Sequence[Path],
) -> list[_StoredFile]:
    pks = plan.get("pks")
    if not isinstance(pks, dict):
        pks = {}
    columns: dict[str, set[str]] = {}
    for table, column in session.execute(
        text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            """
        )
    ):
        columns.setdefault(str(table), set()).add(str(column))
    keys: dict[str, tuple[str, ...]] = {}
    for table, pk_cols in session.execute(
        text(
            """
            SELECT c.relname,
                   (SELECT array_agg(a.attname ORDER BY k.ord)
                      FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                      JOIN pg_attribute a
                        ON a.attrelid = con.conrelid AND a.attnum = k.attnum)
              FROM pg_constraint con
              JOIN pg_class c ON c.oid = con.conrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE con.contype = 'p' AND n.nspname = 'public'
            """
        )
    ):
        if pk_cols:
            keys[str(table)] = tuple(str(col) for col in pk_cols)
    stored: dict[str, _StoredFile] = {}
    for table, values in pks.items():
        if not isinstance(values, list) or not values:
            continue
        key = keys.get(str(table))
        if key is None:
            continue
        named = tuple(column for column in _FILE_COLUMNS if column in columns.get(str(table), set()))
        if named:
            selected = ", ".join(f"t.{_quote(column)}::text" for column in named)
            pk_expr = (
                f"t.{_quote(key[0])}::text"
                if len(key) == 1
                else " || ',' || ".join(f"t.{_quote(col)}::text" for col in key)
            )
            for record in session.execute(
                text(
                    f"SELECT {selected} FROM public.{_quote(str(table))} AS t "
                    f"WHERE ({pk_expr}) = ANY(CAST(:pks AS text[]))"
                ),
                {"pks": [str(v) for v in values]},
            ):
                for column, value in zip(named, record, strict=True):
                    if isinstance(value, str) and value and _safe_relative(value):
                        _add_file(
                            stored,
                            _StoredFile(_FILE_COLUMNS[column], value, None, value),
                            file_roots,
                        )
        if str(table) == "vendor_artifacts" and {
            "box_id",
            "workspace_id",
            "owner_id",
            "artifact_id",
        } <= columns.get(str(table), set()):
            pk_expr = (
                f"t.{_quote(key[0])}::text"
                if len(key) == 1
                else " || ',' || ".join(f"t.{_quote(col)}::text" for col in key)
            )
            for box_id, workspace_id, owner_id, artifact_id in session.execute(
                text(
                    "SELECT t.box_id::text, t.workspace_id::text, t.owner_id::text, "
                    "t.artifact_id::text FROM public.vendor_artifacts AS t "
                    f"WHERE ({pk_expr}) = ANY(CAST(:pks AS text[]))"
                ),
                {"pks": [str(v) for v in values]},
            ):
                relative = f"{box_id}/vendor-documents/{workspace_id}/{owner_id}/{artifact_id}.pdf"
                _add_file(
                    stored,
                    _StoredFile("exports", relative, None, relative),
                    file_roots,
                )
    deleted_ids = _deleted_ids_from_plan(plan)
    for root in file_roots:
        for path in _scan(root, deleted_ids):
            relative = _relative_for(path, file_roots)
            _add_file(
                stored,
                _StoredFile(_kind_for(path), None, path, relative),
                file_roots,
            )
    return list(stored.values())


def _safe_relative(value: str) -> bool:
    parts = Path(value).parts
    return not Path(value).is_absolute() and ".." not in parts and bool(parts) and parts[0] != ""


def _add_file(stored: dict[str, _StoredFile], item: _StoredFile, roots: Sequence[Path]) -> None:
    path = item.path
    if path is None and item.blob_key is not None:
        for root in roots:
            candidate = _inside(root, item.blob_key)
            if candidate is not None:
                path = candidate
                break
    relative = item.relative_path
    if relative is None and path is not None:
        relative = _relative_for(path, roots)
    if relative is None and item.blob_key is not None and _safe_relative(item.blob_key):
        relative = item.blob_key
    identity = str(path.resolve()) if path is not None and path.exists() else item.blob_key
    if identity is None:
        return
    if path is not None and path.exists():
        stored[identity] = _StoredFile(item.kind, item.blob_key, path, relative)
    elif item.blob_key is not None and identity not in stored:
        stored[identity] = _StoredFile(item.kind, item.blob_key, None, relative)


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
