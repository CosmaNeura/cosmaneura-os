"""Explicit synthetic EHR read reservations, verification and human source custody."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from cosmas_os.adapters.ehr_read_runtime import runtime_provider, select_runtime
from cosmas_os.adapters.elation_read import (
    ElationAppointment,
    ElationMedication,
    ElationPatient,
    ElationPractice,
    ElationProblem,
    ElationReadError,
    ElationReadScope,
)
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.adapters.elation_sandbox_runtime import ManagedElationSandboxReads
from cosmas_os.adapters.tebra_read import (
    TebraAppointment,
    TebraPatient,
    TebraPractice,
    TebraReadError,
)
from cosmas_os.adapters.tebra_read_runtime import SyntheticTebraReads, TebraWorkspaceScope
from cosmas_os.application import model_work
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import (
    EhrReadBinding,
    EhrReadRequest,
    EhrReadSnapshot,
    EhrReadSourceReview,
)
from cosmas_os.elation_sandbox_models import ElationSandboxInstallationReceipt
from cosmas_os.models import ExternalIdentity, WorkspaceEntry
from cosmas_os.ports.ehr_reads import (
    MedicationDisplay,
    MedicationList,
    MedicationsObservation,
    MedicationsPrivateSnapshot,
    PrivateAppointment,
    PrivateItem,
    PrivateMedication,
    PrivatePatient,
    PrivateProblem,
    ProblemDisplay,
    ProblemList,
    ProblemsObservation,
    ProblemsPrivateSnapshot,
    SnapshotPayload,
    TebraPrivateAppointment,
    TebraPrivateItem,
    TebraPrivatePatient,
    TebraVerifiedObservation,
    TebraWindowObservation,
    VerifiedObservation,
    Window,
    WindowObservation,
)

_KEY = re.compile(r"^[A-Za-z0-9:_-]{8,100}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_runtime_reader = None
_withheld_sources = ContextVar("ehr_read_withheld_sources", default=frozenset())
SOURCE_LABEL = "Elation: reviewed appointment"


def configure_runtime_reader(reader):
    global _runtime_reader
    _runtime_reader = reader


@contextmanager
def install_runtime_reader(reader):
    global _runtime_reader
    previous, _runtime_reader = _runtime_reader, reader
    try:
        yield
    finally:
        _runtime_reader = previous


def _runtime(port=None, provider=None):
    candidate = port if port is not None else _runtime_reader() if _runtime_reader else None
    chosen = provider or runtime_provider(candidate) or "elation"
    selected = select_runtime(candidate, chosen)
    if selected is None:
        raise ws.WorkspaceError("ehr_read_unavailable", 404)
    return selected


def _problems_available(port, scope):
    return isinstance(port, (SyntheticElationReads, ManagedElationSandboxReads)) and port.problems_available(scope)


def _medications_available(port, scope):
    return isinstance(port, (SyntheticElationReads, ManagedElationSandboxReads)) and port.medications_available(scope)


def _provider_fields(provider):
    return {} if provider is None else {"provider": provider}


def _require_provider(s, read, provider):
    binding = s.get(EhrReadBinding, read.binding_id)
    if binding is None or binding.vendor != (provider or "elation"):
        raise ws.WorkspaceError("ehr_read_provider_mismatch", 409)


def source_label(provider, kind=None):
    if kind == "verified_problems":
        return "Elation: reviewed problem list"
    if kind == "verified_medications":
        return "Elation: reviewed medication records"
    return "Tebra: reviewed appointment" if provider == "tebra" else SOURCE_LABEL


def _identity(s, box, actor, account_id, *, writing=False):
    ws._human(s, box, actor, creating=writing)
    account = s.scalar(select(ExternalIdentity).where(ExternalIdentity.id == account_id,
        ExternalIdentity.box_id == box, ExternalIdentity.principal_id == actor,
        ExternalIdentity.active.is_(True)).with_for_update(read=not writing).execution_options(populate_existing=True))
    if account is None:
        raise ws.WorkspaceError("workspace_access_denied", 403)
    return account


def _access(s, box, actor, account_id, reauthenticate):
    model_work.lock_owner(s, box, actor)
    if reauthenticate is not None:
        reauthenticate()
    return _identity(s, box, actor, account_id, writing=True)


def _scope(binding):
    if binding.vendor == "tebra":
        return TebraWorkspaceScope(UUID(binding.box_id), UUID(binding.owner_id), UUID(binding.connection_id),
            UUID(binding.credential_generation), int(binding.customer_id), int(binding.practice_id),
            binding.practice_name, binding.practice_timezone)
    return ElationReadScope(UUID(binding.box_id), UUID(binding.owner_id), UUID(binding.connection_id),
        UUID(binding.credential_generation), int(binding.practice_id), binding.practice_name,
        environment=binding.environment)


def _binding(s, account, connection_id, digest, *, port=None):
    rows = list(s.scalars(select(EhrReadBinding).where(EhrReadBinding.box_id == account.box_id,
        EhrReadBinding.owner_id == account.principal_id, EhrReadBinding.account_id == account.id,
        EhrReadBinding.connection_id == connection_id, EhrReadBinding.state == "active")
        .with_for_update(read=True).execution_options(populate_existing=True)))
    if len(rows) != 1:
        raise ws.WorkspaceError("ehr_read_binding_unavailable")
    binding = rows[0]
    try:
        scope = _scope(binding)
        runtime = _runtime(port, binding.vendor)
        if type(runtime) is ManagedElationSandboxReads:
            installed = runtime.selected(scope)
            receipt = s.scalar(select(ElationSandboxInstallationReceipt).where(
                ElationSandboxInstallationReceipt.binding_id == binding.id))
            if (installed is None or receipt is None or receipt.installation_id != str(installed.id)
                    or receipt.installation_sha256 != installed.commitment()):
                raise ValueError
        if (binding.environment != ("synthetic" if binding.vendor == "tebra" else "sandbox")
                or binding.binding_digest != scope.commitment() or digest != binding.binding_digest
                or not runtime.current(scope)):
            raise ValueError
    except Exception:
        raise ws.WorkspaceError("ehr_read_binding_changed") from None
    return binding


def _authorize(s, read, *, port=None):
    account = _identity(s, read.box_id, read.owner_id, read.account_id)
    binding = _binding(s, account, read.connection_id, read.binding_digest, port=port)
    if read.transport != _runtime(port, binding.vendor).transport_mode:
        raise ws.WorkspaceError("ehr_read_binding_changed")
    if (binding.id, binding.credential_generation, binding.practice_id) != (
            read.binding_id, read.credential_generation, read.practice_id):
        raise ws.WorkspaceError("ehr_read_binding_changed")
    if read.kind in ("problems", "medications"):
        available = _problems_available if read.kind == "problems" else _medications_available
        if not available(_runtime(port, binding.vendor), _scope(binding)):
            raise ws.WorkspaceError(f"ehr_read_{read.kind}_unavailable", 404)
        parent_snapshot = s.get(EhrReadSnapshot, read.parent_snapshot_id)
        parent_read = s.get(EhrReadRequest, parent_snapshot.observation_id) if parent_snapshot else None
        if parent_read is None:
            raise ws.WorkspaceError("ehr_read_source_invalid")
        _review_custody(s, parent_read)
    root = _window_root(s, read)
    snapshot = s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == root.id))
    if snapshot is not None:
        public = SnapshotPayload.model_validate(snapshot.payload).public
        if public.practice.timezone != _runtime(port, binding.vendor).timezone_for(_scope(binding)):
            raise ws.WorkspaceError("ehr_read_binding_changed")
    return binding


def status(s, box, actor, account_id, *, enabled, port=None, reauthenticate=None, provider=None, include_problems=False, include_medications=False):
    vendor = provider or "elation"
    port = select_runtime(port, vendor)
    _identity(s, box, actor, account_id)
    if reauthenticate is not None:
        reauthenticate()
    empty = dict(contract_version=1, provider=vendor, mode="synthetic",
        status="not_enabled" if not enabled else "not_configured", connection_id=None,
        binding_sha256=None, practice=None, installation=None,
        transport=_runtime(port).transport_mode if runtime_provider(port) is not None else "mock")
    if include_problems:
        empty["problems"] = "not_enabled" if not enabled else "not_configured"
    if include_medications:
        empty["medications"] = "not_enabled" if not enabled else "not_configured"
    if not enabled or runtime_provider(port) is None:
        return empty
    if type(port) is ManagedElationSandboxReads:
        if not port.available():
            return {**empty, "status": "not_enabled"}
        candidates = port.candidates(box, actor, account_id)
        candidate = candidates[0] if len(candidates) == 1 else None
        if candidate is not None:
            empty = {**empty, "status": "setup_required", "installation": {
                "id": str(candidate.id), "sha256": candidate.commitment()},
                "practice": {"label": candidate.scope.practice_name, "timezone": candidate.timezone}}
    rows = list(s.scalars(select(EhrReadBinding).where(EhrReadBinding.box_id == box,
        EhrReadBinding.owner_id == actor, EhrReadBinding.account_id == account_id, EhrReadBinding.vendor == vendor,
        EhrReadBinding.state == "active").execution_options(populate_existing=True)))
    if len(rows) != 1:
        return empty
    account = _identity(s, box, actor, account_id)
    try:
        binding = _binding(s, account, rows[0].connection_id, rows[0].binding_digest, port=port)
    except ws.WorkspaceError:
        return empty
    if reauthenticate is not None:
        reauthenticate()
    try:
        _binding(s, account, binding.connection_id, binding.binding_digest, port=port)
    except ws.WorkspaceError:
        return empty
    if include_problems:
        empty["problems"] = "available" if vendor == "elation" and _problems_available(_runtime(port), _scope(binding)) else "not_enabled"
    if include_medications:
        empty["medications"] = "available" if vendor == "elation" and _medications_available(_runtime(port), _scope(binding)) else "not_enabled"
    return {**empty, "status": "ready", "connection_id": binding.connection_id,
        "binding_sha256": binding.binding_digest,
        "practice": {"label": binding.practice_name, "timezone": _runtime(port).timezone_for(_scope(binding))}}


def _stamp(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _commitment(read, digest):
    return payload_hash(dict(observation_id=read.id, request_sha256=read.request_hash,
        binding_sha256=read.binding_digest, payload_sha256=digest, valid_until=_stamp(read.valid_until)))


def item_hash(kind, item):
    value = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
    value.pop("sha256", None)
    domain = "ehr_verified_medications_item.v1" if kind == "verified_medications" else "ehr_verified_problems_item.v1" if kind == "verified_problems" else "ehr_window_item.v1" if kind == "window" else "ehr_verified_item.v1"
    return payload_hash(dict(kind=domain, item=value))


def _display(kind, item, problem_list=None, medication_list=None):
    appointment = item.appointment.model_dump(mode="json")
    value: dict[str, object] = dict(handle=str(item.handle), starts_at=appointment["starts_at"], ends_at=appointment["ends_at"],
        status=appointment["status"])
    if kind == "window":
        value["selectable"] = bool(item.appointment.patient_id is not None and getattr(item.appointment, "deleted_at", None) is None
            and item.appointment.status is not None and item.appointment.status != "Cancelled")
    else:
        if item.patient is None:
            raise ws.WorkspaceError("ehr_read_source_invalid")
        patient = item.patient.model_dump(mode="json")
        value["patient"] = {key: patient[key] for key in (("full_name", "birth_date") if isinstance(item, TebraPrivateItem) else ("first_name", "last_name", "birth_date"))}
    if kind == "verified_problems":
        if problem_list is None:
            raise ws.WorkspaceError("ehr_read_source_invalid")
        value["problems"] = problem_list.model_dump(mode="json")
    if kind == "verified_medications":
        if medication_list is None:
            raise ws.WorkspaceError("ehr_read_source_invalid")
        value["medications"] = medication_list.model_dump(mode="json")
    return {**value, "sha256": item_hash(kind, value)}


def _window_root(s, read):
    if read.kind == "window":
        return read
    snap = s.get(EhrReadSnapshot, read.parent_snapshot_id)
    parent = s.get(EhrReadRequest, snap.observation_id) if snap is not None else None
    if read.kind in ("problems", "medications"):
        if (parent is None or parent.kind != "verify" or
                (parent.box_id, parent.owner_id, parent.binding_id) != (read.box_id, read.owner_id, read.binding_id)):
            raise ws.WorkspaceError("ehr_read_source_invalid")
        return _window_root(s, parent)
    if (parent is None or parent.kind != "window" or
            (parent.box_id, parent.owner_id, parent.binding_id) != (read.box_id, read.owner_id, read.binding_id)):
        raise ws.WorkspaceError("ehr_read_source_invalid")
    return parent


def _current(s, read):
    root = _window_root(s, read)
    if s.scalar(select(EhrReadRequest.id).where(EhrReadRequest.binding_id == read.binding_id,
            EhrReadRequest.kind == "window", EhrReadRequest.ordinal > root.ordinal).limit(1)):
        raise ws.WorkspaceError("ehr_read_superseded")
    if model_work.now(s) >= min(root.valid_until, read.valid_until):
        raise ws.WorkspaceError("ehr_read_expired")


def _snapshot(s, read):
    snap = s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == read.id))
    if snap is None:
        raise ws.WorkspaceError("ehr_read_unconfirmed", 503)
    try:
        payload = SnapshotPayload.model_validate_json(canonical_json(snap.payload))
        public = payload.public
        binding = s.get(EhrReadBinding, read.binding_id)
        if (binding is None or public.provider != binding.vendor or (public.provider == "tebra" and read.transport != "mock")
                or (snap.box_id, snap.owner_id) != (read.box_id, read.owner_id)
                or read.request_hash != payload_hash(read.request_json)
                or payload.private.binding_sha256 != read.binding_digest
                or payload.private.request_sha256 != read.request_hash
                or payload.private.transport != read.transport
                or public.window.starts_at != read.window_start or public.window.ends_at != read.window_end
                or public.kind != {"window": "window", "verify": "verified_visit", "problems": "verified_problems", "medications": "verified_medications"}.get(read.kind)
                or snap.payload_sha256 != payload_hash(snap.payload)
                or snap.source_sha256 != _commitment(read, snap.payload_sha256)
                or len(canonical_json(snap.payload).encode()) > 65536
                or public.observed_at.utcoffset() is None):
            raise ValueError
        displays = public.items if isinstance(public, (WindowObservation, TebraWindowObservation)) else (public.item,)
        if (len(displays) != len(payload.private.items)
                or len({str(item.handle) for item in displays}) != len(displays)):
            raise ValueError
        ids = set()
        for display, item in zip(displays, payload.private.items, strict=True):
            a = item.appointment
            if (a.appointment_id in ids or int(a.appointment_id) > 2**63 - 1
                    or (isinstance(a, PrivateAppointment) and int(a.physician_id) > 2**63 - 1) or a.starts_at.utcoffset() is None
                    or a.ends_at.utcoffset() is None or not timedelta(0) < a.ends_at - a.starts_at <= timedelta(days=1)
                    or not public.window.starts_at <= a.starts_at <= public.window.ends_at
                    or (isinstance(a, PrivateAppointment) and datetime.fromisoformat(a.scheduled_date_raw.replace("Z", "+00:00")) != a.starts_at)
                    or (public.provider == "tebra" and a.starts_at >= public.window.ends_at)
                    or display.model_dump(mode="json") != _display(public.kind, item,
                        public.item.problems if isinstance(public, ProblemsObservation) else None,
                        public.item.medications if isinstance(public, MedicationsObservation) else None)):
                raise ValueError
            ids.add(a.appointment_id)
            if public.kind == "window" and item.patient is not None:
                raise ValueError
            if public.kind in ("verified_visit", "verified_problems", "verified_medications") and (item.patient is None or getattr(item.patient, "deleted_at", None) is not None
                    or getattr(a, "deleted_at", None) is not None or a.patient_id != item.patient.patient_id
                    or a.status is None or a.status == "Cancelled" or str(item.handle) != read.item_handle
                    or (isinstance(item.patient, TebraPrivatePatient) and item.patient.birth_date.isoformat() != read.request_json.get("birth_date"))):
                raise ValueError
        if isinstance(public, (VerifiedObservation, TebraVerifiedObservation)):
            parent = _window_root(s, read)
            parent_snap = _snapshot(s, parent)
            parent_payload = SnapshotPayload.model_validate(parent_snap.payload)
            original = next((i for i in parent_payload.private.items if str(i.handle) == read.item_handle), None)
            if original is None or original.appointment != payload.private.items[0].appointment:
                raise ValueError
        if isinstance(public, ProblemsObservation):
            if not isinstance(payload.private, ProblemsPrivateSnapshot):
                raise ValueError
            parent_snap = s.get(EhrReadSnapshot, read.parent_snapshot_id)
            parent_read = s.get(EhrReadRequest, parent_snap.observation_id) if parent_snap else None
            if parent_read is None or parent_read.kind != "verify":
                raise ValueError
            _snapshot(s, parent_read)
            original = SnapshotPayload.model_validate(parent_snap.payload)
            if (not isinstance(original.public, VerifiedObservation)
                    or payload.private.items != original.private.items
                    or public.practice != original.public.practice or public.coverage != original.public.coverage
                    or public.window != original.public.window
                    or public.parent.model_dump(mode="json") != dict(observation_id=parent_read.id,
                        source_sha256=parent_snap.source_sha256, item_sha256=original.public.item.sha256)
                    or public.parent.observation_id != UUID(read.request_json["observation_id"])
                    or public.parent.source_sha256 != read.request_json["observation_sha256"]
                    or public.parent.item_sha256 != read.request_json["item_sha256"]
                    or len(payload.private.problems) != len(public.item.problems.items)
                    or len({row.problem_id for row in payload.private.problems}) != len(payload.private.problems)
                    or len(source_content(public)) > 5000):
                raise ValueError
            for shown, row in zip(public.item.problems.items, payload.private.problems, strict=True):
                if (row.patient_id != payload.private.items[0].appointment.patient_id or row.practice_id != read.practice_id
                        or any(int(v) > 2**63-1 for v in (row.problem_id, row.patient_id, row.practice_id))
                        or shown.model_dump(mode="json") != row.model_dump(mode="json", exclude={"problem_id", "patient_id", "practice_id"})):
                    raise ValueError
        if isinstance(public, MedicationsObservation):
            if not isinstance(payload.private, MedicationsPrivateSnapshot):
                raise ValueError
            parent_snap = s.get(EhrReadSnapshot, read.parent_snapshot_id)
            parent_read = s.get(EhrReadRequest, parent_snap.observation_id) if parent_snap else None
            if parent_read is None or parent_read.kind != "verify":
                raise ValueError
            _snapshot(s, parent_read)
            original = SnapshotPayload.model_validate(parent_snap.payload)
            if (not isinstance(original.public, VerifiedObservation)
                    or payload.private.items != original.private.items
                    or public.practice != original.public.practice or public.coverage != original.public.coverage
                    or public.window != original.public.window
                    or public.parent.model_dump(mode="json") != dict(observation_id=parent_read.id,
                        source_sha256=parent_snap.source_sha256, item_sha256=original.public.item.sha256)
                    or public.parent.observation_id != UUID(read.request_json["observation_id"])
                    or public.parent.source_sha256 != read.request_json["observation_sha256"]
                    or public.parent.item_sha256 != read.request_json["item_sha256"]
                    or len(payload.private.medications) != len(public.item.medications.items)
                    or len({row.medication_id for row in payload.private.medications}) != len(payload.private.medications)
                    or len(source_content(public)) > 5000):
                raise ValueError
            for shown, row in zip(public.item.medications.items, payload.private.medications, strict=True):
                if (row.patient_id != payload.private.items[0].appointment.patient_id or row.practice_id != read.practice_id
                        or any(int(v) > 2**63-1 for v in (row.medication_id, row.patient_id, row.practice_id))
                        or shown.model_dump(mode="json") != row.model_dump(mode="json", exclude={"medication_id", "patient_id", "practice_id"})):
                    raise ValueError
        return snap
    except ws.WorkspaceError:
        raise
    except Exception:
        raise ws.WorkspaceError("ehr_read_source_invalid") from None


def _receipt(read, snap):
    public = SnapshotPayload.model_validate(snap.payload).public.model_dump(mode="json")
    return dict(**({"provider": "tebra"} if public["provider"] == "tebra" else {}), contract_version=1, observation_id=read.id, observation_key=read.idempotency_key,
        transport=SnapshotPayload.model_validate(snap.payload).private.transport,
        connection_id=read.connection_id, binding_sha256=read.binding_digest,
        source_sha256=snap.source_sha256, payload_sha256=payload_hash(public), observation=public)


def _review_custody(s, read):
    """A read receipt cannot bypass later loss of its selected-source content."""
    snap = s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == read.id))
    if snap is None:
        return
    reviews = s.scalars(select(EhrReadSourceReview).where(EhrReadSourceReview.snapshot_id == snap.id))
    for review in reviews:
        try:
            w = ws._workspace(s, read.box_id, read.owner_id, review.workspace_id)
            historical_source(s, w, review.entry_id)
        except ws.WorkspaceError:
            raise ws.WorkspaceError("ehr_read_source_unavailable") from None


def _read(s, box, actor, account_id, observation_id):
    read = s.get(EhrReadRequest, observation_id, populate_existing=True)
    if read is None or (read.box_id, read.owner_id, read.account_id) != (box, actor, account_id):
        raise ws.WorkspaceError("ehr_read_observation_unavailable", 404)
    return read


def inspect_observation(s, box, actor, account_id, *, observation_id, port=None, reauthenticate=None, provider=None):
    _access(s, box, actor, account_id, reauthenticate)
    read = _read(s, box, actor, account_id, observation_id)
    _require_provider(s, read, provider)
    _authorize(s, read, port=port)
    _current(s, read)
    _review_custody(s, read)
    receipt = _receipt(read, _snapshot(s, read))
    if reauthenticate is not None:
        reauthenticate()
    _authorize(s, read, port=port)
    _current(s, read)
    return receipt


def resolve_observation(s, box, actor, account_id, *, key, port=None, reauthenticate=None, provider=None):
    _key(key)
    _access(s, box, actor, account_id, reauthenticate)
    from cosmas_os.application import elation_sandbox_installation

    installation = elation_sandbox_installation.resolve(s, box, actor, account_id, key, port)
    if installation is not None:
        if provider == "tebra":
            raise ws.WorkspaceError("ehr_read_provider_mismatch", 409)
        return installation
    read = s.scalar(select(EhrReadRequest).where(EhrReadRequest.box_id == box,
        EhrReadRequest.owner_id == actor, EhrReadRequest.idempotency_key == key))
    if read is None:
        return dict(status="not_found", observation_id=None, observation_key=key)
    if read.account_id != account_id:
        raise ws.WorkspaceError("idempotency_conflict")
    _require_provider(s, read, provider)
    _authorize(s, read, port=port)
    _current(s, read)
    if not s.scalar(select(EhrReadSnapshot.id).where(EhrReadSnapshot.observation_id == read.id)):
        return dict(status="unconfirmed", observation_id=read.id, observation_key=key)
    return inspect_observation(s, box, actor, account_id, observation_id=read.id, port=port,
        reauthenticate=reauthenticate, provider=provider)


def _key(key):
    if type(key) is not str or _KEY.fullmatch(key) is None:
        raise ws.WorkspaceError("invalid_ehr_read_request", 422)


def _digest(value):
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ws.WorkspaceError("invalid_ehr_read_request", 422)


def _reserve(s, account, binding, body, window, *, parent=None, item_handle=None, port=None):
    key, request_hash = body["idempotency_key"], payload_hash(body)
    if s.scalar(select(ElationSandboxInstallationReceipt.id).where(
            ElationSandboxInstallationReceipt.box_id == account.box_id,
            ElationSandboxInstallationReceipt.owner_id == account.principal_id,
            ElationSandboxInstallationReceipt.idempotency_key == key)):
        raise ws.WorkspaceError("idempotency_conflict")
    replay = s.scalar(select(EhrReadRequest).where(EhrReadRequest.box_id == account.box_id,
        EhrReadRequest.owner_id == account.principal_id, EhrReadRequest.idempotency_key == key))
    if replay is not None:
        if replay.request_hash != request_hash or replay.account_id != account.id:
            raise ws.WorkspaceError("idempotency_conflict")
        _authorize(s, replay, port=port)
        _current(s, replay)
        _review_custody(s, replay)
        return replay, _receipt(replay, _snapshot(s, replay))
    now = model_work.now(s)
    ordinal = (s.scalar(select(func.max(EhrReadRequest.ordinal)).where(EhrReadRequest.binding_id == binding.id)) or 0) + 1
    if ordinal > 500:
        raise ws.WorkspaceError("ehr_read_history_limit")
    expires = now + timedelta(minutes=30)
    if parent is not None:
        expires = min(expires, s.get(EhrReadRequest, parent.observation_id).valid_until)
    read = EhrReadRequest(box_id=account.box_id, owner_id=account.principal_id, account_id=account.id,
        binding_id=binding.id, connection_id=binding.connection_id, credential_generation=binding.credential_generation,
        practice_id=binding.practice_id, binding_digest=binding.binding_digest,
        kind="window" if parent is None else body["action"] if body["action"] in ("problems", "medications") else "verify", idempotency_key=key, request_hash=request_hash,
        request_json=body, ordinal=ordinal, parent_snapshot_id=parent.id if parent else None,
        transport=_runtime(port, binding.vendor).transport_mode,
        item_handle=item_handle, window_start=window.starts_at, window_end=window.ends_at,
        valid_until=expires, created_at=now)
    s.add(read)
    s.flush()
    s.commit()  # Exact intent survives lost replies; no DB locks cross provider I/O.
    return read, None


def _provider_authorize(s, read_id, port, reauthenticate):
    read = s.get(EhrReadRequest, read_id, populate_existing=True)
    _access(s, read.box_id, read.owner_id, read.account_id, reauthenticate)
    _authorize(s, read, port=port)
    _current(s, read)
    s.commit()
    return True


def _store(s, read_id, payload, port, reauthenticate):
    read = s.get(EhrReadRequest, read_id, populate_existing=True)
    _access(s, read.box_id, read.owner_id, read.account_id, reauthenticate)
    _authorize(s, read, port=port)
    _current(s, read)
    payload = {**payload, "private": {**payload["private"], "transport": read.transport}}
    value = SnapshotPayload.model_validate(payload).model_dump(mode="json")
    snap = EhrReadSnapshot(box_id=read.box_id, owner_id=read.owner_id, observation_id=read.id,
        payload=value, payload_sha256=payload_hash(value), source_sha256=_commitment(read, payload_hash(value)))
    s.add(snap)
    s.flush()
    _snapshot(s, read)
    if reauthenticate is not None:
        reauthenticate()
    _authorize(s, read, port=port)
    _current(s, read)
    s.commit()
    # Committing releases the authority locks. Reacquire the same inspection
    # fence used by recovery before exposing the now-persisted observation.
    return inspect_observation(s, read.box_id, read.owner_id, read.account_id,
        observation_id=read_id, port=port, reauthenticate=reauthenticate, provider=read.request_json.get("provider"))


def _appointment(row: ElationAppointment):
    return PrivateAppointment.model_validate(dict(appointment_id=str(row.appointment_id), patient_id=str(row.patient_id) if row.patient_id else None,
        physician_id=str(row.physician_id), starts_at=row.starts_at, ends_at=row.ends_at,
        status=row.source_status, scheduled_date_raw=row.scheduled_date_raw, deleted_at=row.deleted_at))


def _provider_error(error):
    if isinstance(error, (ElationReadError, TebraReadError)):
        code = {"disabled": "unavailable", "invalid_response": "response_invalid",
            "connection_changed": "binding_changed", "access_denied": "binding_changed",
            "scope_changed": "binding_changed", "connector_disabled": "unavailable", "provider_throttled": "rate_limited"}.get(error.code, error.code)
        return ws.WorkspaceError("ehr_read_" + code, 429 if code == "rate_limited" else 503)
    return ws.WorkspaceError("ehr_read_unconfirmed", 503)


def observe(s, box, actor, account_id, *, key, connection_id, binding_sha256, starts_at, ends_at,
            port, reauthenticate=None, provider=None):
    _key(key)
    _digest(binding_sha256)
    try:
        window = Window(starts_at=starts_at, ends_at=ends_at)
    except Exception:
        raise ws.WorkspaceError("invalid_ehr_read_request", 422) from None
    account = _access(s, box, actor, account_id, reauthenticate)
    binding = _binding(s, account, connection_id, binding_sha256, port=port)
    if binding.vendor != (provider or "elation"):
        raise ws.WorkspaceError("ehr_read_provider_mismatch", 409)
    body = dict(**_provider_fields(provider), action="observe", connection_id=connection_id, binding_sha256=binding_sha256,
        idempotency_key=key, **window.model_dump(mode="json"))
    read, replay = _reserve(s, account, binding, body, window, port=port)
    if replay is not None:
        return replay
    read_id, scope = read.id, _scope(binding)
    if binding.vendor == "tebra":
        return _observe_tebra(s, read, binding, window, port, reauthenticate)
    try:
        runtime = _runtime(port)
        assert isinstance(runtime, (SyntheticElationReads, ManagedElationSandboxReads))
        assert isinstance(scope, ElationReadScope)
        practice_result, result = runtime.window(scope, window.starts_at, window.ends_at,
            authorize=lambda: _provider_authorize(s, read_id, port, reauthenticate))
        if practice_result.scope != scope or result.scope != scope or len(practice_result.rows) != 1:
            raise ValueError
        practice = practice_result.rows[0]
        if (not isinstance(practice, ElationPractice) or practice.name != scope.practice_name
                or practice.timezone != _runtime(port).timezone_for(scope)):
            raise ValueError
        private_items = []
        for row in result.rows:
            if not isinstance(row, ElationAppointment) or row.physician_id not in practice.active_physician_ids:
                raise ValueError
            private_items.append(PrivateItem(handle=uuid4(), appointment=_appointment(row), patient=None))
        payload = dict(public=dict(kind="window", provider="elation", mode="synthetic",
            practice=dict(label=practice.name, timezone=practice.timezone), observed_at=result.observed_at,
            window=window.model_dump(mode="json"), coverage=result.coverage,
            items=[_display("window", item) for item in private_items]),
            private=dict(binding_sha256=read.binding_digest, request_sha256=read.request_hash,
                items=[item.model_dump(mode="json") for item in private_items],
                provider_sources=[practice_result.source_sha256, result.source_sha256]))
        return _store(s, read_id, payload, port, reauthenticate)
    except ws.WorkspaceError:
        s.rollback()
        raise
    except Exception as error:
        s.rollback()
        raise _provider_error(error) from None


def verify(s, box, actor, account_id, *, key, connection_id, binding_sha256, observation_id,
           observation_sha256, item_handle, item_sha256, port, reauthenticate=None, provider=None, last_name=None, birth_date=None):
    _key(key)
    for digest in (binding_sha256, observation_sha256, item_sha256):
        _digest(digest)
    account = _access(s, box, actor, account_id, reauthenticate)
    binding = _binding(s, account, connection_id, binding_sha256, port=port)
    parent = _read(s, box, actor, account_id, observation_id)
    _require_provider(s, parent, provider)
    if parent.kind != "window" or parent.binding_id != binding.id:
        raise ws.WorkspaceError("ehr_read_not_observed")
    _authorize(s, parent, port=port)
    _current(s, parent)
    parent_snap = _snapshot(s, parent)
    payload = SnapshotPayload.model_validate(parent_snap.payload)
    original = next((item for item in payload.private.items if str(item.handle) == item_handle), None)
    if (parent_snap.source_sha256 != observation_sha256 or original is None
            or _display("window", original)["sha256"] != item_sha256
            or not _display("window", original)["selectable"] or original.appointment.patient_id is None):
        raise ws.WorkspaceError("ehr_read_not_observed")
    body = dict(**_provider_fields(provider), action="verify", connection_id=connection_id, binding_sha256=binding_sha256,
        idempotency_key=key, observation_id=observation_id, observation_sha256=observation_sha256,
        item_handle=item_handle, item_sha256=item_sha256)
    if binding.vendor == "tebra":
        if (type(last_name) is not str or not 1 <= len(last_name) <= 255 or last_name != last_name.strip()
                or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in last_name) or type(birth_date) is not date
                or not date(1850, 1, 1) <= birth_date <= date.today()):
            raise ws.WorkspaceError("invalid_ehr_read_request", 422)
        body.update(last_name=last_name, birth_date=birth_date.isoformat())
    elif last_name is not None or birth_date is not None:
        raise ws.WorkspaceError("invalid_ehr_read_request", 422)
    read, replay = _reserve(s, account, binding, body, payload.public.window,
        parent=parent_snap, item_handle=item_handle, port=port)
    if replay is not None:
        return replay
    read_id, scope = read.id, _scope(binding)
    if binding.vendor == "tebra":
        return _verify_tebra(s, read, binding, payload, original, port, reauthenticate)
    try:
        runtime = _runtime(port)
        assert isinstance(runtime, (SyntheticElationReads, ManagedElationSandboxReads))
        assert isinstance(scope, ElationReadScope)
        appointment_result, patient_result = runtime.visit(scope, int(original.appointment.appointment_id),
            int(original.appointment.patient_id), authorize=lambda: _provider_authorize(s, read_id, port, reauthenticate))
        if appointment_result.scope != scope or patient_result.scope != scope:
            raise ValueError
        appointment, patient = appointment_result.rows[0], patient_result.rows[0]
        if not isinstance(appointment, ElationAppointment) or not isinstance(patient, ElationPatient):
            raise ValueError
        if _appointment(appointment) != original.appointment or appointment.patient_id != patient.patient_id:
            raise ws.WorkspaceError("ehr_read_appointment_changed")
        private = PrivateItem(handle=original.handle, appointment=_appointment(appointment),
            patient=PrivatePatient(patient_id=str(patient.patient_id), first_name=patient.first_name,
                last_name=patient.last_name, birth_date=patient.birth_date,
                primary_physician_id=str(patient.primary_physician_id), deleted_at=patient.deleted_at))
        public = payload.public.model_dump(mode="json")
        public.pop("items")
        public.update(kind="verified_visit", observed_at=patient_result.observed_at,
            item=_display("verified_visit", private))
        value = dict(public=public, private=dict(binding_sha256=read.binding_digest,
            request_sha256=read.request_hash, items=[private.model_dump(mode="json")],
            provider_sources=[appointment_result.source_sha256, patient_result.source_sha256]))
        return _store(s, read_id, value, port, reauthenticate)
    except ws.WorkspaceError:
        s.rollback()
        raise
    except Exception as error:
        s.rollback()
        raise _provider_error(error) from None


def problems(s, box, actor, account_id, *, key, connection_id, binding_sha256, observation_id,
             observation_sha256, item_handle, item_sha256, port, reauthenticate=None, provider=None):
    """Read one problem page only after the same immutable visit identity is reread."""
    _key(key)
    for digest in (binding_sha256, observation_sha256, item_sha256):
        _digest(digest)
    if provider not in (None, "elation"):
        raise ws.WorkspaceError("ehr_read_provider_mismatch", 409)
    account = _access(s, box, actor, account_id, reauthenticate)
    binding = _binding(s, account, connection_id, binding_sha256, port=port)
    parent = _read(s, box, actor, account_id, observation_id)
    _require_provider(s, parent, provider)
    if binding.vendor != "elation" or parent.kind != "verify" or parent.binding_id != binding.id:
        raise ws.WorkspaceError("ehr_read_not_observed")
    _authorize(s, parent, port=port)
    _current(s, parent)
    _review_custody(s, parent)
    parent_snap = _snapshot(s, parent)
    payload = SnapshotPayload.model_validate(parent_snap.payload)
    if (not isinstance(payload.public, VerifiedObservation) or not len(payload.private.items) == 1
            or parent_snap.source_sha256 != observation_sha256
            or str(payload.public.item.handle) != item_handle or payload.public.item.sha256 != item_sha256):
        raise ws.WorkspaceError("ehr_read_not_observed")
    runtime, scope = _runtime(port), _scope(binding)
    if not isinstance(runtime, (SyntheticElationReads, ManagedElationSandboxReads)) or not isinstance(scope, ElationReadScope):
        raise ws.WorkspaceError("ehr_read_problems_unavailable", 404)
    if not runtime.problems_available(scope):
        raise ws.WorkspaceError("ehr_read_problems_unavailable", 404)
    original = payload.private.items[0]
    if not isinstance(original, PrivateItem) or original.patient is None or original.appointment.patient_id is None:
        raise ws.WorkspaceError("ehr_read_not_observed")
    body = dict(**_provider_fields(provider), action="problems", connection_id=connection_id,
        binding_sha256=binding_sha256, idempotency_key=key, observation_id=observation_id,
        observation_sha256=observation_sha256, item_handle=item_handle, item_sha256=item_sha256)
    read, replay = _reserve(s, account, binding, body, payload.public.window,
        parent=parent_snap, item_handle=item_handle, port=port)
    if replay is not None:
        return replay
    read_id = read.id

    def verify_identity(appointment, patient):
        if not isinstance(appointment, ElationAppointment) or not isinstance(patient, ElationPatient):
            raise ws.WorkspaceError("ehr_read_record_unavailable")
        current_patient = PrivatePatient(patient_id=str(patient.patient_id), first_name=patient.first_name,
            last_name=patient.last_name, birth_date=patient.birth_date,
            primary_physician_id=str(patient.primary_physician_id), deleted_at=patient.deleted_at)
        if _appointment(appointment) != original.appointment:
            raise ws.WorkspaceError("ehr_read_appointment_changed")
        if current_patient != original.patient:
            raise ws.WorkspaceError("ehr_read_patient_changed")
        return True

    try:
        appointment_result, patient_result, result = runtime.problem_list(scope,
            int(original.appointment.appointment_id), int(original.appointment.patient_id),
            authorize=lambda: _provider_authorize(s, read_id, port, reauthenticate), verify_identity=verify_identity)
        if any(value.scope != scope for value in (appointment_result, patient_result, result)):
            raise ValueError
        rows = []
        for row in result.rows:
            if not isinstance(row, ElationProblem):
                raise ValueError
            rows.append(PrivateProblem(problem_id=str(row.problem_id), patient_id=str(row.patient_id),
                practice_id=str(row.practice_id), description=row.description, status=row.status,
                start_date=row.start_date, resolved_date=row.resolved_date, verification_status=row.verification_status))
        if result.coverage not in ("end_of_results", "more_rows_available", "unknown"):
            raise ValueError
        problem_list = ProblemList(coverage=result.coverage, total_count=result.total_count,
            items=tuple(ProblemDisplay.model_validate(row.model_dump(exclude={"problem_id", "patient_id", "practice_id"})) for row in rows))
        public = payload.public.model_dump(mode="json")
        public.update(kind="verified_problems", observed_at=result.observed_at,
            parent=dict(observation_id=observation_id, source_sha256=observation_sha256, item_sha256=item_sha256),
            item=_display("verified_problems", original, problem_list))
        if len(source_content(public)) > 5000:
            raise ws.WorkspaceError("ehr_read_response_too_large", 503)
        value = dict(public=public, private=dict(binding_sha256=read.binding_digest,
            request_sha256=read.request_hash, items=[original.model_dump(mode="json")],
            problems=[row.model_dump(mode="json") for row in rows],
            provider_sources=[appointment_result.source_sha256, patient_result.source_sha256, result.source_sha256]))
        return _store(s, read_id, value, port, reauthenticate)
    except ws.WorkspaceError:
        s.rollback()
        raise
    except Exception as error:
        s.rollback()
        raise _provider_error(error) from None


def medications(s, box, actor, account_id, *, key, connection_id, binding_sha256, observation_id,
             observation_sha256, item_handle, item_sha256, port, reauthenticate=None, provider=None):
    """Read one medication page only after the same immutable visit identity is reread."""
    _key(key)
    for digest in (binding_sha256, observation_sha256, item_sha256):
        _digest(digest)
    if provider not in (None, "elation"):
        raise ws.WorkspaceError("ehr_read_provider_mismatch", 409)
    account = _access(s, box, actor, account_id, reauthenticate)
    binding = _binding(s, account, connection_id, binding_sha256, port=port)
    parent = _read(s, box, actor, account_id, observation_id)
    _require_provider(s, parent, provider)
    if binding.vendor != "elation" or parent.kind != "verify" or parent.binding_id != binding.id:
        raise ws.WorkspaceError("ehr_read_not_observed")
    _authorize(s, parent, port=port)
    _current(s, parent)
    _review_custody(s, parent)
    parent_snap = _snapshot(s, parent)
    payload = SnapshotPayload.model_validate(parent_snap.payload)
    if (not isinstance(payload.public, VerifiedObservation) or not len(payload.private.items) == 1
            or parent_snap.source_sha256 != observation_sha256
            or str(payload.public.item.handle) != item_handle or payload.public.item.sha256 != item_sha256):
        raise ws.WorkspaceError("ehr_read_not_observed")
    runtime, scope = _runtime(port), _scope(binding)
    if not isinstance(runtime, (SyntheticElationReads, ManagedElationSandboxReads)) or not isinstance(scope, ElationReadScope):
        raise ws.WorkspaceError("ehr_read_medications_unavailable", 404)
    if not runtime.medications_available(scope):
        raise ws.WorkspaceError("ehr_read_medications_unavailable", 404)
    original = payload.private.items[0]
    if not isinstance(original, PrivateItem) or original.patient is None or original.appointment.patient_id is None:
        raise ws.WorkspaceError("ehr_read_not_observed")
    body = dict(**_provider_fields(provider), action="medications", connection_id=connection_id,
        binding_sha256=binding_sha256, idempotency_key=key, observation_id=observation_id,
        observation_sha256=observation_sha256, item_handle=item_handle, item_sha256=item_sha256)
    read, replay = _reserve(s, account, binding, body, payload.public.window,
        parent=parent_snap, item_handle=item_handle, port=port)
    if replay is not None:
        return replay
    read_id = read.id

    def verify_identity(appointment, patient):
        if not isinstance(appointment, ElationAppointment) or not isinstance(patient, ElationPatient):
            raise ws.WorkspaceError("ehr_read_record_unavailable")
        current_patient = PrivatePatient(patient_id=str(patient.patient_id), first_name=patient.first_name,
            last_name=patient.last_name, birth_date=patient.birth_date,
            primary_physician_id=str(patient.primary_physician_id), deleted_at=patient.deleted_at)
        if _appointment(appointment) != original.appointment:
            raise ws.WorkspaceError("ehr_read_appointment_changed")
        if current_patient != original.patient:
            raise ws.WorkspaceError("ehr_read_patient_changed")
        return True

    try:
        appointment_result, patient_result, result = runtime.medication_list(scope,
            int(original.appointment.appointment_id), int(original.appointment.patient_id),
            authorize=lambda: _provider_authorize(s, read_id, port, reauthenticate), verify_identity=verify_identity)
        if any(value.scope != scope for value in (appointment_result, patient_result, result)):
            raise ValueError
        rows = []
        for row in result.rows:
            if not isinstance(row, ElationMedication):
                raise ValueError
            fields = asdict(row)
            for name in ("medication_id", "patient_id", "practice_id"):
                fields[name] = str(fields[name])
            rows.append(PrivateMedication.model_validate(fields))
        if result.coverage not in ("end_of_results", "more_rows_available", "unknown"):
            raise ValueError
        medication_list = MedicationList(coverage=result.coverage, total_count=result.total_count,
            items=tuple(MedicationDisplay.model_validate(row.model_dump(exclude={"medication_id", "patient_id", "practice_id"})) for row in rows))
        public = payload.public.model_dump(mode="json")
        public.update(kind="verified_medications", observed_at=result.observed_at,
            parent=dict(observation_id=observation_id, source_sha256=observation_sha256, item_sha256=item_sha256),
            item=_display("verified_medications", original, medication_list=medication_list))
        public = MedicationsObservation.model_validate(public).model_dump(mode="json")
        if len(source_content(public)) > 5000:
            raise ws.WorkspaceError("ehr_read_response_too_large", 503)
        value = dict(public=public, private=dict(binding_sha256=read.binding_digest,
            request_sha256=read.request_hash, items=[original.model_dump(mode="json")],
            medications=[row.model_dump(mode="json") for row in rows],
            provider_sources=[appointment_result.source_sha256, patient_result.source_sha256, result.source_sha256]))
        return _store(s, read_id, value, port, reauthenticate)
    except ws.WorkspaceError:
        s.rollback()
        raise
    except Exception as error:
        s.rollback()
        raise _provider_error(error) from None


def _tebra_result_hash(result):
    rows = json.loads(json.dumps([asdict(row) for row in result.rows], default=lambda value: value.isoformat()))
    return payload_hash(dict(contract="tebra-read-result.v1", binding_sha256=result.scope.commitment(),
        operation=result.operation, observed_at=result.observed_at.isoformat(), coverage=result.coverage, rows=rows))


def _tebra_appointment(row):
    if type(row) is not TebraAppointment:
        raise ValueError
    return TebraPrivateAppointment.model_validate(dict(appointment_id=str(row.appointment_id), patient_id=str(row.patient_id),
        starts_at=row.starts_at, ends_at=row.ends_at, status=row.source_status))


def _observe_tebra(s, read, binding, window, port, reauthenticate):
    read_id, scope = read.id, _scope(binding)
    try:
        assert isinstance(scope, TebraWorkspaceScope)
        runtime = _runtime(port, "tebra")
        assert isinstance(runtime, SyntheticTebraReads)
        practice_result, result = runtime.window(scope, window.starts_at, window.ends_at,
            authorize=lambda: _provider_authorize(s, read_id, port, reauthenticate))
        if len(result.rows) > 25:
            raise TebraReadError("too_many_results")
        if practice_result.scope != scope or result.scope != scope or len(practice_result.rows) != 1:
            raise ValueError
        practice = practice_result.rows[0]
        if (type(practice) is not TebraPractice or practice.practice_id != scope.practice_id
                or practice.practice_name != scope.practice_name or result.coverage != "returned_rows_only"):
            raise ValueError
        items = [TebraPrivateItem(handle=uuid4(), appointment=_tebra_appointment(row), patient=None) for row in result.rows]
        payload = dict(public=dict(kind="window", provider="tebra", mode="synthetic",
            practice=dict(label=scope.practice_name, timezone=scope.timezone), observed_at=result.observed_at,
            window=window.model_dump(mode="json"), coverage="returned_rows_only",
            items=[_display("window", item) for item in items]),
            private=dict(transport="mock", binding_sha256=read.binding_digest, request_sha256=read.request_hash,
                items=[item.model_dump(mode="json") for item in items],
                provider_sources=[_tebra_result_hash(practice_result), _tebra_result_hash(result)]))
        return _store(s, read_id, payload, port, reauthenticate)
    except ws.WorkspaceError:
        s.rollback()
        raise
    except Exception as error:
        s.rollback()
        raise _provider_error(error) from None


def _verify_tebra(s, read, binding, payload, original, port, reauthenticate):
    read_id, scope = read.id, _scope(binding)
    try:
        runtime = _runtime(port, "tebra")
        assert isinstance(runtime, SyntheticTebraReads)
        appointments, patients = runtime.visit(scope,
            int(original.appointment.appointment_id), int(original.appointment.patient_id),
            starts_at=read.window_start, ends_at=read.window_end, last_name=read.request_json["last_name"],
            birth_date=date.fromisoformat(read.request_json["birth_date"]),
            authorize=lambda: _provider_authorize(s, read_id, port, reauthenticate))
        if appointments.scope != scope or patients.scope != scope or len(appointments.rows) != 1 or len(patients.rows) != 1:
            raise ValueError
        appointment, patient = appointments.rows[0], patients.rows[0]
        if (not isinstance(appointment, TebraAppointment) or type(patient) is not TebraPatient or _tebra_appointment(appointment) != original.appointment
                or appointment.patient_id != patient.patient_id):
            raise ws.WorkspaceError("ehr_read_appointment_changed")
        private = TebraPrivateItem(handle=original.handle, appointment=original.appointment,
            patient=TebraPrivatePatient(patient_id=str(patient.patient_id), full_name=patient.full_name, birth_date=patient.birth_date))
        public = payload.public.model_dump(mode="json")
        public.pop("items")
        public.update(kind="verified_visit", observed_at=appointments.observed_at, item=_display("verified_visit", private))
        return _store(s, read_id, dict(public=public, private=dict(transport="mock", binding_sha256=read.binding_digest,
            request_sha256=read.request_hash, items=[private.model_dump(mode="json")],
            provider_sources=[_tebra_result_hash(appointments), _tebra_result_hash(patients)])), port, reauthenticate)
    except ws.WorkspaceError:
        s.rollback()
        raise
    except Exception as error:
        s.rollback()
        raise _provider_error(error) from None


def source_content(observation):
    value = observation.model_dump(mode="json") if hasattr(observation, "model_dump") else observation
    item, patient = value["item"], value["item"]["patient"]
    if value["kind"] == "verified_problems":
        return problem_source_content(value)
    if value["kind"] == "verified_medications":
        return medication_source_content(value)
    coverage = "Showing this page; more appointments may be available." if value["coverage"] == "more_rows_available" else "Showing the returned page."
    provider_name = "Tebra" if value["provider"] == "tebra" else "Elation"
    name = patient["full_name"] if value["provider"] == "tebra" else f"{patient['first_name']} {patient['last_name']}"
    if value["provider"] == "tebra":
        coverage = "Showing returned appointments only; this is not a complete schedule."
    return (f"{provider_name} selected visit (synthetic frozen observation)\n"
        f"Practice: {value['practice']['label']}\nPatient: {name}\n"
        f"Birth date: {patient['birth_date']}\nStarts: {item['starts_at']}\nEnds: {item['ends_at']}\n"
        f"Appointment status: {item['status'] or 'not provided'}\nObserved: {value['observed_at']}\n"
        f"Coverage: {coverage}\n\nThis reviewed snapshot does not book or update the EHR.")


def problem_source_content(value):
    item, patient = value["item"], value["item"]["patient"]
    problems = item["problems"]
    coverage = {"end_of_results": "End of returned results; not a complete chart.",
        "more_rows_available": "More problem rows are available; only this page was read.",
        "unknown": "The provider did not establish whether more problem rows exist."}[problems["coverage"]]
    lines = ["Elation problem list (synthetic frozen observation)",
        f"Practice: {value['practice']['label']}",
        f"Patient: {patient['first_name']} {patient['last_name']}", f"Birth date: {patient['birth_date']}",
        f"Visit starts: {item['starts_at']}", f"Visit ends: {item['ends_at']}",
        f"Observed: {value['observed_at']}", f"Coverage: {coverage}",
        f"Returned rows: {len(problems['items'])}; reported total: {problems['total_count'] if problems['total_count'] is not None else 'not provided'}.",
        "Description, status, dates and verification only; diagnosis codes and synopsis are not included.", ""]
    for row in problems["items"]:
        lines.append(f"- {row['description']} | Status: {row['status']} | Start: {row['start_date']} | "
            f"Resolved: {row['resolved_date'] or 'not provided'} | Verification: {row['verification_status'] or 'not provided'}")
    if not problems["items"]:
        lines.append("No problem rows returned; this does not establish absence of conditions.")
    lines.extend(["", "Provider statuses and verification are recorded as supplied, not confirmed diagnoses.",
        "This reviewed snapshot does not prescribe or update the EHR."])
    return "\n".join(lines)


def medication_source_content(value):
    item, patient = value["item"], value["item"]["patient"]
    medications = item["medications"]
    coverage = {"end_of_results": "End of returned results; not a complete chart.",
        "more_rows_available": "More medication records are available; only this page was read.",
        "unknown": "The provider did not establish whether more medication records exist."}[medications["coverage"]]
    lines = ["Elation medication records (synthetic frozen observation)",
        f"Practice: {value['practice']['label']}",
        f"Patient: {patient['first_name']} {patient['last_name']}", f"Birth date: {patient['birth_date']}",
        f"Visit starts: {item['starts_at']}", f"Visit ends: {item['ends_at']}",
        f"Observed: {value['observed_at']}", f"Coverage: {coverage}",
        f"Returned rows: {len(medications['items'])}; reported total: {medications['total_count'] if medications['total_count'] is not None else 'not provided'}.",
        "Optional details not listed were not provided. Dates are preserved as recorded; no timezone or current medication status is inferred.", ""]
    for row in medications["items"]:
        lines.append(f"- {row['medication_name']}")
        for key, label in (("strength", "Strength"), ("route", "Route"), ("form", "Form"),
                ("directions", "Directions"), ("medication_type", "Medication type"), ("order_type", "Order type"),
                ("is_doc_med", "Documentation flag"), ("is_permanent", "Permanent flag"),
                ("start_date", "Start date"), ("document_date", "Document date")):
            detail = row[key]
            if detail is not None:
                rendered = str(detail).lower() if isinstance(detail, bool) else detail if detail != "" else "(blank)"
                lines.append(f"  {label}: {rendered}")
        for key, state, label in (("signed_date", "signature_state", "Signed date"),
                ("discontinue_date", "discontinuation_state", "Discontinuation date"),
                ("deleted_date", "deletion_state", "Deleted date")):
            detail = row[key] if row[state] == "date_recorded" else "no date recorded" if row[state] == "no_date_recorded" else "unknown"
            lines.append(f"  {label}: {detail}")
    if not medications["items"]:
        lines.append("No medication records returned; this does not establish absence of medications.")
    lines.extend(["", "These are medication records, not a reconciled current medication list or proof of dispensing, transmission or use.",
        "This reviewed snapshot does not prescribe or update the EHR."])
    return "\n".join(lines)


def _review_body(wid, expected, key, observation_id, observation_sha256, item_handle, item_sha256,
                 reviewed_visit, reviewed_patient_identity, reviewed_exact_snapshot, reviewed_untrusted_source, provider=None):
    return dict(**_provider_fields(provider), workspace_id=wid, expected_revision=expected, idempotency_key=key,
        observation_id=observation_id, observation_sha256=observation_sha256, item_handle=item_handle,
        item_sha256=item_sha256, reviewed_visit=reviewed_visit, reviewed_patient_identity=reviewed_patient_identity,
        reviewed_exact_snapshot=reviewed_exact_snapshot, reviewed_untrusted_source=reviewed_untrusted_source)


def _selected_hash(observation_sha256, item_handle, item_sha256):
    return payload_hash(dict(observation_sha256=observation_sha256, item_handle=item_handle, item_sha256=item_sha256))


def historical_source(s, w, entry_id):
    entry = s.get(WorkspaceEntry, entry_id)
    review = s.scalar(select(EhrReadSourceReview).where(EhrReadSourceReview.entry_id == entry_id))
    if (entry is None or review is None or (entry.workspace_id, entry.box_id, entry.actor_id, entry.kind)
            != (w.id, w.box_id, w.owner_id, "ehr_read_source")):
        raise ws.WorkspaceError("ehr_read_source_unavailable", 404)
    snap = s.get(EhrReadSnapshot, review.snapshot_id)
    read = s.get(EhrReadRequest, snap.observation_id) if snap is not None else None
    if read is None or snap is None or read.kind not in ("verify", "problems", "medications"):
        raise ws.WorkspaceError("ehr_read_source_invalid")
    _snapshot(s, read)
    public = SnapshotPayload.model_validate(snap.payload).public
    if not isinstance(public, (VerifiedObservation, TebraVerifiedObservation, ProblemsObservation, MedicationsObservation)):
        raise ws.WorkspaceError("ehr_read_source_invalid")
    content = source_content(public)
    body = _review_body(w.id, review.expected_revision, review.idempotency_key, read.id,
        review.observation_sha256, review.item_handle, review.item_sha256, review.reviewed_visit,
        review.reviewed_patient_identity, review.reviewed_exact_snapshot, review.reviewed_untrusted_source, review.command_provider)
    if ((review.box_id, review.owner_id, review.workspace_id, review.patient_link_id, review.workspace_revision)
            != (w.box_id, w.owner_id, w.id, w.patient_link_id, entry.revision)
            or (snap.box_id, snap.owner_id, read.box_id, read.owner_id) != (w.box_id, w.owner_id, w.box_id, w.owner_id)
            or str(public.item.handle) != review.item_handle or public.item.sha256 != review.item_sha256
            or review.observation_sha256 != snap.source_sha256
            or review.source_sha256 != _selected_hash(review.observation_sha256, review.item_handle, review.item_sha256)
            or review.valid_until != read.valid_until or entry.content != content or entry.source_label != source_label(public.provider, public.kind)
            or review.content_sha256 != hashlib.sha256(content.encode()).hexdigest()
            or review.request_hash != payload_hash(body) or entry.request_hash != review.request_hash
            or entry.idempotency_key != review.idempotency_key or review.workspace_revision != review.expected_revision + 1
            or not all((review.reviewed_visit, review.reviewed_patient_identity, review.reviewed_exact_snapshot,
                        review.reviewed_untrusted_source))):
        raise ws.WorkspaceError("ehr_read_source_invalid")
    return entry


def validate_selected_source(s, w, entry_id):
    if (w.id, entry_id) in _withheld_sources.get():
        raise ws.WorkspaceError("ehr_read_source_unavailable")
    model_work.read_workspace(s, w.box_id, w.owner_id, w.id)
    entry = historical_source(s, w, entry_id)
    review = s.scalar(select(EhrReadSourceReview).where(EhrReadSourceReview.entry_id == entry_id))
    snap = s.get(EhrReadSnapshot, review.snapshot_id)
    read = s.get(EhrReadRequest, snap.observation_id)
    _authorize(s, read)
    _current(s, read)
    return entry


def selected_entries(s, w, settings, at_revision):
    from cosmas_os.ports.bot_capabilities import supports_skill
    if not supports_skill(settings, "saved_context") or not settings["include_evidence"]:
        return []
    result = []
    entries = s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == w.id,
        WorkspaceEntry.box_id == w.box_id, WorkspaceEntry.actor_id == w.owner_id,
        WorkspaceEntry.kind == "ehr_read_source", WorkspaceEntry.revision <= at_revision).order_by(WorkspaceEntry.revision))
    for entry in entries:
        try:
            result.append(validate_selected_source(s, w, entry.id))
        except ws.WorkspaceError:
            continue
    return result


def _selection_receipt(s, w, read, review, entry):
    workspace = ws.read(s, w.box_id, w.owner_id, w.id)
    projected = next(row for row in workspace["entries"] if row["id"] == entry.id)
    withheld = projected.get("ehr_source_state") == "unavailable"
    try:
        validate_selected_source(s, w, entry.id)
    except ws.WorkspaceError:
        withheld = True
    if withheld:
        token = _withheld_sources.set(_withheld_sources.get() | {(w.id, entry.id)})
        try:
            workspace = ws.read(s, w.box_id, w.owner_id, w.id)
        finally:
            _withheld_sources.reset(token)
    return dict(entry_id=entry.id, entry_revision=entry.revision, workspace=workspace,
        transport=read.transport, **({"provider": "tebra"} if s.get(EhrReadBinding, read.binding_id).vendor == "tebra" else {}),
        source=dict(entry_id=entry.id, source_sha256=review.source_sha256, content_sha256=review.content_sha256),
        request_sha256=review.request_hash, source_withheld=withheld)


def select_review(s, box, actor, wid, *, expected, key, observation_id, observation_sha256,
                  item_handle, item_sha256, reviewed_visit, reviewed_patient_identity,
                  reviewed_exact_snapshot, reviewed_untrusted_source, port=None, external_identity_id=None,
                  reauthenticate=None, provider=None):
    if (type(expected) is not int or expected < 1 or type(key) is not str or _KEY.fullmatch(key) is None
            or any(type(v) is not str or _DIGEST.fullmatch(v) is None for v in (observation_sha256, item_sha256))
            or any(v is not True for v in (reviewed_visit, reviewed_patient_identity, reviewed_exact_snapshot, reviewed_untrusted_source))):
        raise ws.WorkspaceError("invalid_ehr_read_review", 422)
    model_work.lock_owner(s, box, actor)
    if reauthenticate is not None:
        reauthenticate()
    w = ws._workspace(s, box, actor, wid, writing=True)
    read = s.get(EhrReadRequest, observation_id)
    if (read is None or read.kind not in ("verify", "problems", "medications") or (read.box_id, read.owner_id) != (box, actor)
            or external_identity_id is not None and read.account_id != external_identity_id):
        raise ws.WorkspaceError("ehr_read_observation_unavailable", 404)
    _require_provider(s, read, provider)
    _identity(s, box, actor, read.account_id)
    snap = _snapshot(s, read)
    body = _review_body(wid, expected, key, observation_id, observation_sha256, item_handle, item_sha256,
        reviewed_visit, reviewed_patient_identity, reviewed_exact_snapshot, reviewed_untrusted_source, provider)
    request_hash = payload_hash(body)
    replay = s.scalar(select(EhrReadSourceReview).where(EhrReadSourceReview.workspace_id == wid,
        EhrReadSourceReview.idempotency_key == key))
    if replay is not None:
        if replay.request_hash != request_hash:
            raise ws.WorkspaceError("idempotency_conflict")
        entry = historical_source(s, w, replay.entry_id)
        if reauthenticate is not None:
            reauthenticate()
        return _selection_receipt(s, w, read, replay, entry)
    _authorize(s, read, port=port)
    _current(s, read)
    if expected != w.revision:
        raise ws.WorkspaceError("workspace_revision_conflict")
    public = SnapshotPayload.model_validate(snap.payload).public
    if (not isinstance(public, (VerifiedObservation, TebraVerifiedObservation, ProblemsObservation, MedicationsObservation)) or observation_sha256 != snap.source_sha256
            or str(public.item.handle) != item_handle or public.item.sha256 != item_sha256):
        raise ws.WorkspaceError("ehr_read_source_changed")
    if w.revision >= 500:
        raise ws.WorkspaceError("workspace_history_limit")
    if s.scalar(select(WorkspaceEntry.id).where(WorkspaceEntry.workspace_id == wid, WorkspaceEntry.idempotency_key == key)):
        raise ws.WorkspaceError("idempotency_conflict")
    if s.scalar(select(EhrReadSourceReview.id).where(EhrReadSourceReview.workspace_id == wid,
            EhrReadSourceReview.snapshot_id == snap.id, EhrReadSourceReview.item_handle == item_handle)):
        raise ws.WorkspaceError("ehr_read_already_selected")
    content = source_content(public)
    w.revision += 1
    entry = WorkspaceEntry(workspace_id=wid, box_id=box, actor_id=actor, revision=w.revision,
        kind="ehr_read_source", content=content, source_label=source_label(public.provider, public.kind),
        idempotency_key=key, request_hash=request_hash)
    s.add(entry)
    s.flush()
    review = EhrReadSourceReview(command_provider=provider, workspace_id=wid, box_id=box, owner_id=actor, entry_id=entry.id,
        snapshot_id=snap.id, patient_link_id=w.patient_link_id, expected_revision=expected, workspace_revision=w.revision,
        idempotency_key=key, request_hash=request_hash, observation_sha256=observation_sha256,
        item_handle=item_handle, item_sha256=item_sha256,
        source_sha256=_selected_hash(observation_sha256, item_handle, item_sha256),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(), valid_until=read.valid_until,
        reviewed_visit=True, reviewed_patient_identity=True, reviewed_exact_snapshot=True, reviewed_untrusted_source=True)
    s.add(review)
    ws._audit(s, w, "ehr_read_reviewed")
    if reauthenticate is not None:
        reauthenticate()
    _authorize(s, read, port=port)
    _current(s, read)
    s.commit()
    return _selection_receipt(s, w, read, review, entry)
