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

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from cosmas_os.domain.enums import PrincipalState, PrincipalType
from cosmas_os.domain.rules import AuthorizationError, DomainError
from cosmas_os.models import Principal

_AUDIO_SUFFIXES = {".wav", ".m4a", ".mp3", ".flac", ".ogg", ".aac"}
_PENDING_FILES_MSG = "database delete completed; stored files pending; rerun finishes them"
_DB_REASON_CODES = (
    "schema not classified for patient deletion",
    "admin authority required",
    "patient not found",
    "patient records could not be deleted",
    "deletion role not configured",
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

    # Lookup may RAISE inside SQL and abort the txn; use a savepoint so pending
    # file deletes from above remain committable when the patient is already gone.
    nested = session.begin_nested()
    try:
        patient_box = _patient_box(session, patient_id)
        nested.commit()
    except DomainError:
        nested.rollback()
        if confirm and pending_finished > 0:
            session.commit()
            return _report(
                patient_id,
                confirm=True,
                deleted=False,
                tables={},
                files={},
                pending_files_finished=pending_finished,
            )
        raise
    if patient_box != str(actor.box_id):
        raise AuthorizationError("admin authority required")

    if not confirm:
        plan = _plan(session, patient_id)
        files = _collect_files_for_plan(session, plan, file_roots, box_id=patient_box)
        return _report(
            patient_id,
            confirm=False,
            deleted=False,
            tables=_table_counts(plan.get("tables")),
            files=_file_counts(files, file_roots),
            pending_files_finished=0,
            exclusive_retained=_table_counts(plan.get("exclusive_retained")),
        )

    plan = _plan(session, patient_id)
    files = _collect_files_for_plan(session, plan, file_roots, box_id=patient_box)
    file_counts = _file_counts(files, file_roots)
    try:
        _record_pending_files(session, patient_id, patient_box, files, file_roots)
        result = _apply_secure_deletion(session, patient_id)
        session.commit()
    except (AuthorizationError, DomainError):
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise _map_delete_failure(exc) from None

    tables = _table_counts(result.get("tables"))
    try:
        _delete_files(blob, files, file_roots, plan=plan, box_id=patient_box)
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
        exclusive_retained=_table_counts(result.get("exclusive_retained")),
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
    """Resolve the bound practice owner via SECURITY DEFINER (no table SELECT)."""

    try:
        raw = session.scalar(text("SELECT public.patient_deletion_resolve_admin()"))
    except SQLAlchemyError as exc:
        mapped = _map_db_reason(exc)
        if mapped is not None:
            if str(mapped) == "admin authority required":
                raise AuthorizationError("admin authority required") from None
            raise mapped from None
        raise AuthorizationError("admin authority required") from None
    if not isinstance(raw, dict):
        raise AuthorizationError("admin authority required")
    principal_id = str(raw.get("principal_id") or "")
    box_id = str(raw.get("box_id") or "")
    if not principal_id or not box_id:
        raise AuthorizationError("admin authority required")
    # DEFINER already validated human/active/owner. Do not SELECT principals —
    # the documented admin LOGIN has no table rights, and a denied SELECT would
    # abort the transaction before pending-file helpers run.
    return Principal(
        id=principal_id,
        box_id=box_id,
        principal_type=PrincipalType.HUMAN.value,
        display_name="bound-admin",
        is_owner=True,
        state=PrincipalState.ACTIVE.value,
    )


def _patient_box(session: Session, patient_id: str) -> str:
    """Return the patient's box_id via SECURITY DEFINER (no table SELECT)."""

    try:
        box = session.scalar(
            text("SELECT public.patient_deletion_patient_box(CAST(:patient AS uuid))"),
            {"patient": patient_id},
        )
    except SQLAlchemyError as exc:
        mapped = _map_db_reason(exc)
        if mapped is not None:
            raise mapped from None
        raise DomainError("patient not found") from None
    if box is None:
        raise DomainError("patient not found")
    return str(box)


def _map_db_reason(exc: BaseException) -> DomainError | AuthorizationError | None:
    text_blob = " ".join(
        part
        for part in (
            str(exc),
            str(getattr(exc, "orig", "") or ""),
            str(getattr(getattr(exc, "orig", None), "diag", "") or ""),
        )
        if part
    ).lower()
    for reason in _DB_REASON_CODES:
        if reason.lower() in text_blob:
            if reason == "admin authority required":
                return AuthorizationError(reason)
            return DomainError(reason)
    return None


def _map_delete_failure(exc: BaseException) -> DomainError | AuthorizationError:
    mapped = _map_db_reason(exc)
    if mapped is not None:
        return mapped
    return DomainError("patient records could not be deleted")


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
    exclusive_retained: Mapping[str, int] | None = None,
) -> dict[str, object]:
    retained = dict(exclusive_retained or {})
    message_retained = int(retained.get("google_message_snapshots", 0)) + int(
        retained.get("microsoft_message_snapshots", 0)
    )
    calendar_retained = int(retained.get("google_calendar_snapshots", 0)) + int(
        retained.get("microsoft_calendar_snapshots", 0)
    )
    out: dict[str, object] = {
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
        "exclusive_retained": retained,
        "message snapshots retained, still used by another patient": message_retained,
        "calendar snapshots retained, still used by another patient": calendar_retained,
    }
    return out


def _table_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(k): int(v) for k, v in value.items()}


def _plan(session: Session, patient_id: str) -> dict[str, object]:
    try:
        raw = session.scalar(
            text("SELECT public.delete_patient_keyed_records_plan(CAST(:patient AS uuid))"),
            {"patient": patient_id},
        )
    except SQLAlchemyError as exc:
        mapped = _map_db_reason(exc)
        if mapped is not None:
            raise mapped from None
        raise DomainError("patient records could not be deleted") from None
    if not isinstance(raw, dict):
        raise DomainError("patient records could not be deleted")
    return raw


def _apply_secure_deletion(session: Session, patient_id: str) -> dict[str, object]:
    # SET LOCAL ROLE reverts automatically at transaction end.
    try:
        session.execute(text("SET LOCAL ROLE cosmas_patient_deletion"))
        raw = session.scalar(
            text("SELECT public.delete_patient_keyed_records(CAST(:patient AS uuid))"),
            {"patient": patient_id},
        )
    except SQLAlchemyError as exc:
        mapped = _map_db_reason(exc)
        if mapped is not None:
            raise mapped from None
        raise DomainError("patient records could not be deleted") from None
    if not isinstance(raw, dict):
        raise DomainError("patient records could not be deleted")
    return raw


@dataclass(frozen=True)
class _FileScanIds:
    """Ids that may appear in on-disk paths — never tickets or unrelated PKs."""

    recording_ids: frozenset[str]
    artifact_ids: frozenset[str]
    workspace_ids: frozenset[str]


def _pks_for_table(plan: Mapping[str, object], table: str) -> frozenset[str]:
    pks = plan.get("pks")
    if not isinstance(pks, dict):
        return frozenset()
    values = pks.get(table)
    if not isinstance(values, list):
        return frozenset()
    return frozenset(str(value) for value in values)


def _file_scan_ids_from_plan(plan: Mapping[str, object]) -> _FileScanIds:
    return _FileScanIds(
        recording_ids=_pks_for_table(plan, "private_recordings"),
        artifact_ids=_pks_for_table(plan, "artifacts"),
        workspace_ids=_pks_for_table(plan, "encounter_workspaces"),
    )


def _path_matches_patient_files(parts: tuple[str, ...], *, box_id: str, ids: _FileScanIds) -> bool:
    """Match a relative path only in the expected segment for each artifact kind.

    Ticket and unrelated plan PKs must never match here: a bait ticket whose id
    equals another practice's box or recording id used to delete that practice's
    files when any path segment was compared to the full plan PK set.
    """

    if not parts:
        return False
    first = parts[0]
    # Uploads: <box_id>/<artifact_id>/...
    if len(parts) >= 3 and first == box_id and parts[1] in ids.artifact_ids:
        return True
    # Uploads: <box_id>/uploads/<artifact_id>/...
    if (
        len(parts) >= 4
        and first == box_id
        and parts[1].lower() == "uploads"
        and parts[2] in ids.artifact_ids
    ):
        return True
    # Audio: <box_id>/<recording_id>/audio/...
    if (
        len(parts) >= 4
        and first == box_id
        and parts[1] in ids.recording_ids
        and parts[2].lower() == "audio"
    ):
        return True
    # Audio (local layout): <recording_id>/audio/...
    if len(parts) >= 3 and first in ids.recording_ids and parts[1].lower() == "audio":
        return True
    # Exports: <box_id>/<workspace_id>/exports/...
    if (
        len(parts) >= 4
        and first == box_id
        and parts[1] in ids.workspace_ids
        and parts[2].lower() == "exports"
    ):
        return True
    # Exports (local layout): <workspace_id>/exports/...
    if len(parts) >= 3 and first in ids.workspace_ids and parts[1].lower() == "exports":
        return True
    # Vendor documents are never folder-scanned: only exact DB keys from
    # patient_deletion_collect_file_keys (vendor_artifacts) may be deleted.
    return False


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


def _pending_file_payload(
    files: Sequence[_StoredFile], roots: Sequence[Path]
) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
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
        payload.append({"kind": item.kind, "path": relative})
    return payload


def _record_pending_files(
    session: Session,
    patient_id: str,
    box_id: str,
    files: Sequence[_StoredFile],
    roots: Sequence[Path],
) -> None:
    payload = _pending_file_payload(files, roots)
    if not payload:
        return
    try:
        session.execute(
            text(
                """
                SELECT public.patient_deletion_pending_record(
                  CAST(:patient AS uuid),
                  CAST(:box AS uuid),
                  CAST(:files AS jsonb)
                )
                """
            ),
            {"patient": patient_id, "box": box_id, "files": json.dumps(payload)},
        )
    except SQLAlchemyError as exc:
        mapped = _map_db_reason(exc)
        if mapped is not None:
            raise mapped from None
        raise


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
    try:
        session.execute(
            text(
                """
                SELECT public.patient_deletion_pending_clear(
                  CAST(:patient AS uuid),
                  CAST(:paths AS text[])
                )
                """
            ),
            {"patient": patient_id, "paths": list(paths)},
        )
    except SQLAlchemyError as exc:
        mapped = _map_db_reason(exc)
        if mapped is not None:
            raise mapped from None
        raise


def _finish_pending_files(
    session: Session,
    blob: BlobDeleter | None,
    roots: Sequence[Path],
    *,
    box_id: str,
) -> int:
    try:
        rows = list(
            session.execute(
                text(
                    "SELECT id::text, kind, relative_path "
                    "FROM public.patient_deletion_pending_list(CAST(:box AS uuid))"
                ),
                {"box": box_id},
            )
        )
    except SQLAlchemyError as exc:
        mapped = _map_db_reason(exc)
        if mapped is not None:
            raise mapped from None
        raise
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
            try:
                session.execute(
                    text("SELECT public.patient_deletion_pending_delete(CAST(:id AS uuid))"),
                    {"id": pending_id},
                )
            except SQLAlchemyError as exc:
                mapped = _map_db_reason(exc)
                if mapped is not None:
                    raise mapped from None
                raise
            finished += 1
            del kind
    return finished


def _collect_files_for_plan(
    session: Session,
    plan: Mapping[str, object],
    file_roots: Sequence[Path],
    *,
    box_id: str,
) -> list[_StoredFile]:
    pks = plan.get("pks")
    if not isinstance(pks, dict):
        pks = {}
    stored: dict[str, _StoredFile] = {}
    try:
        raw = session.scalar(
            text("SELECT public.patient_deletion_collect_file_keys(CAST(:pks AS jsonb))"),
            {"pks": json.dumps(pks)},
        )
    except SQLAlchemyError as exc:
        mapped = _map_db_reason(exc)
        if mapped is not None:
            raise mapped from None
        raise DomainError("patient records could not be deleted") from None
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "")
            path = str(item.get("path") or "")
            if kind not in {"audio", "uploads", "exports"} or not _safe_relative(path):
                continue
            _add_file(stored, _StoredFile(kind, path, None, path), file_roots)
    scan_ids = _file_scan_ids_from_plan(plan)
    for root in file_roots:
        for path in _scan(root, box_id=box_id, ids=scan_ids):
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


def _scan(root: Path, *, box_id: str, ids: _FileScanIds) -> list[Path]:
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
                relative_parts = path.resolve().relative_to(base).parts
            except OSError:
                continue
            if _path_matches_patient_files(relative_parts, box_id=box_id, ids=ids):
                found.append(path)
    return found


def _file_counts(files: Sequence[_StoredFile], roots: Sequence[Path]) -> dict[str, int]:
    counts = {"audio": 0, "uploads": 0, "exports": 0}
    for item in files:
        # Rootless blob stores (Azure) have no local path; _delete_files still
        # deletes every blob_key, so count it.
        if (item.path is not None and item.path.exists()) or (
            not roots and item.blob_key is not None
        ):
            counts[item.kind] += 1
    return counts


def _delete_files(
    blob: BlobDeleter | None,
    files: Sequence[_StoredFile],
    roots: Sequence[Path],
    *,
    plan: Mapping[str, object],
    box_id: str,
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
    scan_ids = _file_scan_ids_from_plan(plan)
    for root in roots:
        _prune(root, box_id=box_id, ids=scan_ids)


def _unlink(path: Path) -> None:
    try:
        if path.is_file() and not path.is_symlink():
            path.unlink()
        meta = Path(str(path) + ".meta")
        if meta.is_file() and not meta.is_symlink():
            meta.unlink()
    except OSError:
        raise DomainError("stored files could not be deleted") from None


def _dir_matches_patient_files(parts: tuple[str, ...], *, box_id: str, ids: _FileScanIds) -> bool:
    """Empty dirs under matched file trees may be removed after unlink."""

    if not parts:
        return False
    if _path_matches_patient_files(parts + ("_",), box_id=box_id, ids=ids):
        return True
    if len(parts) == 1 and (parts[0] in ids.recording_ids or parts[0] in ids.workspace_ids):
        return True
    if (
        len(parts) == 2
        and parts[0] == box_id
        and (
            parts[1] in ids.artifact_ids
            or parts[1] in ids.recording_ids
            or parts[1] in ids.workspace_ids
            or parts[1].lower() == "uploads"
        )
    ):
        return True
    if (
        len(parts) == 3
        and parts[0] == box_id
        and parts[1].lower() == "uploads"
        and parts[2] in ids.artifact_ids
    ):
        return True
    # Never prune by walking vendor-documents/; those files are unlinked only
    # via exact collected keys.
    return False


def _prune(root: Path, *, box_id: str, ids: _FileScanIds) -> None:
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
        if not _dir_matches_patient_files(relative.parts, box_id=box_id, ids=ids):
            continue
        try:
            if not any(current.iterdir()):
                current.rmdir()
        except OSError:
            raise DomainError("stored files could not be deleted") from None
