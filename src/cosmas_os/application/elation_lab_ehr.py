"""Verified-visit-bound report selection and exact selected laboratory source custody."""

from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from cosmas_os.adapters.elation_lab_read import (
    ElationLabObservation,
    ElationLabPatient,
    ElationLabScope,
    ElationReportCandidate,
    ElationReportPage,
    parse_json,
    patient_identity,
    validate_page,
)
from cosmas_os.adapters.elation_read import ElationAppointment, ElationPatient, ElationReadScope
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.application import workspace as ws
from cosmas_os.application.elation_lab_snapshot import prepare_lab_review
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import EhrReadBinding, EhrReadRequest, EhrReadSnapshot
from cosmas_os.ports.ehr_reads import (
    PrivateItem,
    PrivatePatient,
    PrivateSnapshot,
    SnapshotPayload,
    VerifiedObservation,
)
from cosmas_os.ports.elation_lab_ehr import (
    METADATA_KEYS,
    LabPrivateItem,
    LabPrivateSnapshot,
    LabReportObservation,
    LabReportsObservation,
)

KINDS = ("lab_reports", "lab_report")


def available(port, connection_scope):
    return type(port) is SyntheticElationReads and port.labs_available(connection_scope)


def parent(s, read):
    snap = s.get(EhrReadSnapshot, read.parent_snapshot_id)
    prior = s.get(EhrReadRequest, snap.observation_id) if snap else None
    expected = "verify" if read.kind == "lab_reports" else "lab_reports"
    if (prior is None or prior.kind != expected
            or (prior.box_id, prior.owner_id, prior.account_id, prior.binding_id, prior.window_start, prior.window_end)
            != (read.box_id, read.owner_id, read.account_id, read.binding_id, read.window_start, read.window_end)
            or read.kind == "lab_report" and (prior.workspace_id, prior.patient_link_id) != (read.workspace_id, read.patient_link_id)):
        raise ws.WorkspaceError("ehr_read_source_invalid")
    return prior, snap


def visit(s, read):
    prior, snap = parent(s, read)
    return parent(s, prior) if prior.kind == "lab_reports" else (prior, snap)


def workspace(s, read):
    w = ws._workspace(s, read.box_id, read.owner_id, read.workspace_id)
    if w.patient_link_id != read.patient_link_id:
        raise ws.WorkspaceError("ehr_read_patient_changed")
    return w


def authorize(s, read, binding, port):
    from cosmas_os.application import ehr_reads as ehr
    from cosmas_os.application import provider_team

    if not (provider_team.runtime_settings.workspace_ehr_read_available
            and provider_team.runtime_settings.workspace_elation_labs_enabled
            and available(port, ehr._scope(binding))):
        raise ws.WorkspaceError("ehr_read_labs_unavailable", 404)
    workspace(s, read)
    original, _ = visit(s, read)
    ehr._authorize(s, original, port=port)
    ehr._review_custody(s, original)
    return binding


def current(s, read):
    page = read if read.kind == "lab_reports" else parent(s, read)[0]
    if s.scalar(select(EhrReadRequest.id).where(EhrReadRequest.binding_id == read.binding_id,
            EhrReadRequest.workspace_id == read.workspace_id, EhrReadRequest.kind == "lab_reports",
            EhrReadRequest.ordinal > page.ordinal).limit(1)):
        raise ws.WorkspaceError("ehr_read_superseded")


def scope(s, read):
    from cosmas_os.application import ehr_reads as ehr

    original, snap = visit(s, read)
    ehr._snapshot(s, original)
    value = SnapshotPayload.model_validate(snap.payload)
    binding = s.get(EhrReadBinding, read.binding_id)
    if (not isinstance(value.public, VerifiedObservation) or not isinstance(value.private, PrivateSnapshot)
            or len(value.private.items) != 1 or binding is None or binding.vendor != "elation" or binding.protocol is not None):
        raise ValueError("invalid_lab_visit")
    item = value.private.items[0]
    if not isinstance(item, PrivateItem) or item.patient is None or item.patient.deleted_at is not None:
        raise ValueError("invalid_lab_patient")
    p = item.patient
    identity = patient_identity(dict(id=int(p.patient_id), caregiver_practice=int(binding.practice_id),
        primary_physician=int(p.primary_physician_id), first_name=p.first_name, last_name=p.last_name,
        dob=p.birth_date.isoformat(), deleted_date=None), int(p.patient_id), int(binding.practice_id))
    authorization = payload_hash(dict(contract="ehr-elation-lab-authority.v1", account_id=read.account_id,
        binding_sha256=read.binding_digest, workspace_id=read.workspace_id, patient_link_id=read.patient_link_id,
        verified_observation_id=original.id, verified_source_sha256=snap.source_sha256,
        verified_item_handle=str(value.public.item.handle), verified_item_sha256=value.public.item.sha256))
    connection = ehr._scope(binding)
    if not isinstance(connection, ElationReadScope):
        raise ValueError("invalid_lab_connection")
    return ElationLabScope(connection, UUID(read.account_id), UUID(read.workspace_id), UUID(read.patient_link_id),
        int(p.patient_id), authorization, identity.identity_sha256), item, value.public


def encoded(value):
    raw = asdict(value)
    raw["scope"] = {**raw["scope"], "connection_scope": {
        key: str(item) if isinstance(item, UUID) else item for key, item in raw["scope"]["connection_scope"].items()}}
    for key in ("account_id", "workspace_id", "patient_link_id"):
        raw["scope"][key] = str(raw["scope"][key])
    raw["observed_at"] = value.observed_at.isoformat()
    return canonical_json(raw)


def decoded(raw, *, page=False):
    value: dict[str, Any] = parse_json(raw)
    if canonical_json(value) != raw:
        raise ValueError("noncanonical_lab_proof")
    scoped: dict[str, Any] = dict(value["scope"])
    connection: dict[str, Any] = dict(scoped.pop("connection_scope"))
    for key in ("box_id", "owner_id", "connection_id", "credential_generation"):
        connection[key] = UUID(connection[key])
    for key in ("account_id", "workspace_id", "patient_link_id"):
        scoped[key] = UUID(scoped[key])
    value["scope"] = ElationLabScope(connection_scope=ElationReadScope(**connection), **scoped)
    value["patient"] = ElationLabPatient(**value["patient"])
    value["observed_at"] = datetime.fromisoformat(value["observed_at"])
    value["provider_sources"] = tuple(value["provider_sources"])
    if page:
        value["candidates"] = tuple(ElationReportCandidate(**row) for row in value["candidates"])
    result = ElationReportPage(**value) if page else ElationLabObservation(**value)
    if encoded(result) != raw:
        raise ValueError("noncanonical_lab_proof")
    return result


def identity_json(patient):
    row = parse_json(patient.identity_json)
    return canonical_json({key: row[key] for key in ("first_name", "last_name", "dob")})


def candidate_item(item, candidate):
    from cosmas_os.application import ehr_reads as ehr

    metadata = parse_json(candidate.metadata_json)
    value = dict(handle=str(item.handle), metadata_json=canonical_json({key: metadata[key] for key in metadata if key in METADATA_KEYS}))
    return {**value, "sha256": ehr.item_hash("lab_reports", value)}


def report_item(item, prepared):
    from cosmas_os.application import ehr_reads as ehr

    value = dict(handle=str(item.handle), report_json=prepared.observation.report_json,
        changed_since_selection=prepared.observation.changed_since_selection, warnings=list(prepared.warnings),
        completeness=prepared.completeness, source_content=prepared.source_content, content_sha256=prepared.source_content_sha256)
    return {**value, "sha256": ehr.item_hash("verified_lab_report", value)}


def validate_snapshot(s, read, snap):
    from cosmas_os.application import ehr_reads as ehr

    payload = SnapshotPayload.model_validate(snap.payload)
    pub, priv = payload.public, payload.private
    binding = s.get(EhrReadBinding, read.binding_id)
    if (not isinstance(pub, (LabReportsObservation, LabReportObservation)) or not isinstance(priv, LabPrivateSnapshot)
            or binding is None or binding.vendor != "elation" or binding.protocol is not None or read.transport != "mock"
            or pub.kind != ("lab_reports" if read.kind == "lab_reports" else "verified_lab_report")
            or str(pub.workspace_id) != read.workspace_id or str(priv.workspace_id) != read.workspace_id
            or str(priv.patient_link_id) != read.patient_link_id or pub.window.starts_at != read.window_start or pub.window.ends_at != read.window_end
            or (snap.box_id, snap.owner_id) != (read.box_id, read.owner_id)
            or priv.binding_sha256 != read.binding_digest or priv.request_sha256 != read.request_hash
            or read.request_hash != payload_hash(read.request_json) or snap.payload_sha256 != payload_hash(snap.payload)
            or snap.source_sha256 != ehr._commitment(read, snap.payload_sha256) or len(canonical_json(snap.payload).encode()) > 65536
            or len({item.handle for item in priv.items}) != len(priv.items) or len({item.report_id for item in priv.items}) != len(priv.items)):
        raise ValueError("invalid_lab_snapshot")
    scoped, _, verified = scope(s, read)
    prior, previous = parent(s, read)
    ehr._snapshot(s, prior)
    old = SnapshotPayload.model_validate(previous.payload)
    if (pub.practice.model_dump(mode="json") != verified.practice.model_dump(mode="json")
            or pub.parent.model_dump(mode="json") != dict(observation_id=prior.id, source_sha256=previous.source_sha256, item_sha256=read.request_json["item_sha256"])
            or read.request_json["observation_id"] != prior.id or read.request_json["observation_sha256"] != previous.source_sha256
            or read.request_json["workspace_id"] != read.workspace_id or read.request_json.get("provider") != "elation" or "protocol" in read.request_json):
        raise ValueError("invalid_lab_parent_proof")
    if isinstance(pub, LabReportsObservation):
        if not isinstance(old.public, VerifiedObservation) or str(old.public.item.handle) != read.item_handle or old.public.item.sha256 != pub.parent.item_sha256:
            raise ValueError("invalid_lab_visit_proof")
        observed = decoded(priv.page_snapshot_json, page=True)
        if not isinstance(observed, ElationReportPage):
            raise ValueError("invalid_lab_page")
        validate_page(observed, scoped, observed.source_sha256)
        if (priv.reader_snapshot_json is not None or priv.review_sha256 is not None
                or [(int(item.report_id), item.report_sha256) for item in priv.items] != [(row.report_id, row.report_sha256) for row in observed.candidates]
                or pub.model_dump(mode="json")["items"] != [candidate_item(item, row) for item, row in zip(priv.items, observed.candidates, strict=True)]
                or (pub.coverage, pub.returned_report_count, pub.other_report_count, pub.reported_total) !=
                (observed.coverage, observed.returned_report_count, observed.other_report_count, str(observed.reported_total) if observed.reported_total is not None else None)):
            raise ValueError("invalid_lab_candidates")
    else:
        if (not isinstance(old.public, LabReportsObservation) or not isinstance(old.private, LabPrivateSnapshot)
                or len(priv.items) != 1 or str(priv.items[0].handle) != read.item_handle):
            raise ValueError("invalid_lab_selection")
        item = priv.items[0]
        matched = next((row for row in old.private.items if row.handle == item.handle), None)
        displayed = next((row for row in old.public.items if row.handle == item.handle), None)
        if matched != item or displayed is None or displayed.sha256 != pub.parent.item_sha256:
            raise ValueError("invalid_lab_selection_proof")
        page = decoded(old.private.page_snapshot_json, page=True)
        if not isinstance(page, ElationReportPage):
            raise ValueError("invalid_lab_page")
        validate_page(page, scoped, page.source_sha256)
        observed = decoded(priv.reader_snapshot_json)
        if not isinstance(observed, ElationLabObservation) or observed.selected_report_sha256 != item.report_sha256:
            raise ValueError("invalid_lab_reader")
        prepared = prepare_lab_review(observed, expected_scope=scoped, expected_source_sha256=observed.source_sha256,
            expected_candidates_sha256=page.source_sha256, expected_report_id=int(item.report_id), authorize_read=lambda _: True)
        if prepared.snapshot_sha256 != priv.review_sha256 or pub.item.model_dump(mode="json") != report_item(item, prepared):
            raise ValueError("invalid_lab_review_projection")
    if pub.observed_at != observed.observed_at or pub.patient_identity_json != identity_json(observed.patient):
        raise ValueError("invalid_lab_patient_projection")
    return snap


def perform(s, box, actor, account_id, *, action, key, connection_id, binding_sha256, workspace_id,
        observation_id, observation_sha256, item_handle, item_sha256, port, reauthenticate=None):
    from cosmas_os.application import ehr_reads as ehr

    ehr._key(key)
    for digest in (binding_sha256, observation_sha256, item_sha256):
        ehr._digest(digest)
    if action not in KINDS:
        raise ws.WorkspaceError("invalid_ehr_read_request", 422)
    from cosmas_os.application import provider_team

    if not (provider_team.runtime_settings.workspace_ehr_read_available and provider_team.runtime_settings.workspace_elation_labs_enabled):
        raise ws.WorkspaceError("ehr_read_labs_unavailable", 404)
    account = ehr._access(s, box, actor, account_id, reauthenticate)
    binding = ehr._binding(s, account, connection_id, binding_sha256, port=port)
    prior = ehr._read(s, box, actor, account_id, observation_id)
    ehr._require_provider(s, prior, "elation")
    if (binding.vendor != "elation" or binding.protocol is not None or prior.binding_id != binding.id
            or prior.kind != ("verify" if action == "lab_reports" else "lab_reports")
            or action == "lab_report" and prior.workspace_id != workspace_id):
        raise ws.WorkspaceError("ehr_read_not_observed")
    ehr._authorize(s, prior, port=port)
    ehr._current(s, prior)
    ehr._review_custody(s, prior)
    previous = ehr._snapshot(s, prior)
    old = SnapshotPayload.model_validate(previous.payload)
    if not isinstance(old.public, (LabReportsObservation, VerifiedObservation)):
        raise ws.WorkspaceError("ehr_read_source_invalid")
    displays = old.public.items if isinstance(old.public, LabReportsObservation) else (old.public.item,) if isinstance(old.public, VerifiedObservation) else ()
    selected = next((row for row in displays if str(row.handle) == item_handle), None)
    if selected is None or selected.sha256 != item_sha256 or previous.source_sha256 != observation_sha256:
        raise ws.WorkspaceError("ehr_read_not_observed")
    if not available(port, ehr._scope(binding)):
        raise ws.WorkspaceError("ehr_read_labs_unavailable", 404)
    w = ws._workspace(s, box, actor, workspace_id, writing=True)
    body = dict(provider="elation", action=action, connection_id=connection_id, binding_sha256=binding_sha256,
        workspace_id=workspace_id, idempotency_key=key, observation_id=observation_id, observation_sha256=observation_sha256,
        item_handle=item_handle, item_sha256=item_sha256)
    read, replay = ehr._reserve(s, account, binding, body, old.public.window, parent=previous,
        item_handle=item_handle, port=port, workspace=w)
    if replay is not None:
        return replay
    scoped, original, _ = scope(s, read)

    def verify_identity(appointment, patient):
        if not isinstance(appointment, ElationAppointment) or not isinstance(patient, ElationPatient):
            raise ws.WorkspaceError("ehr_read_record_unavailable")
        current_patient = PrivatePatient(patient_id=str(patient.patient_id), first_name=patient.first_name, last_name=patient.last_name,
            birth_date=patient.birth_date, primary_physician_id=str(patient.primary_physician_id), deleted_at=patient.deleted_at)
        if ehr._appointment(appointment) != original.appointment:
            raise ws.WorkspaceError("ehr_read_appointment_changed")
        if current_patient != original.patient:
            raise ws.WorkspaceError("ehr_read_patient_changed")
        return True

    try:
        def authorize_read():
            return ehr._provider_authorize(s, read.id, port, reauthenticate)
        if action == "lab_reports":
            appointment_result, patient_result, observed = port.lab_reports(scoped, int(original.appointment.appointment_id),
                authorize=authorize_read, verify_identity=verify_identity)
            validate_page(observed, scoped, observed.source_sha256)
            items = [LabPrivateItem(handle=uuid4(), report_id=str(row.report_id), report_sha256=row.report_sha256) for row in observed.candidates]
            projection = dict(kind="lab_reports", coverage=observed.coverage, returned_report_count=observed.returned_report_count,
                other_report_count=observed.other_report_count, reported_total=str(observed.reported_total) if observed.reported_total is not None else None,
                items=[candidate_item(item, row) for item, row in zip(items, observed.candidates, strict=True)])
            proof = dict(page_snapshot_json=encoded(observed), reader_snapshot_json=None, review_sha256=None)
        else:
            if not isinstance(old.private, LabPrivateSnapshot):
                raise ValueError("invalid_lab_parent")
            item = next(row for row in old.private.items if str(row.handle) == item_handle)
            page = decoded(old.private.page_snapshot_json, page=True)
            appointment_result, patient_result, prepared = port.lab_report(scoped, int(original.appointment.appointment_id), page,
                int(item.report_id), expected_candidates_sha256=page.source_sha256, authorize=authorize_read, verify_identity=verify_identity)
            observed, items = prepared.observation, [item]
            projection = dict(kind="verified_lab_report", item=report_item(item, prepared))
            proof = dict(page_snapshot_json=None, reader_snapshot_json=encoded(observed), review_sha256=prepared.snapshot_sha256)
        if appointment_result.scope != scoped.connection_scope or patient_result.scope != scoped.connection_scope:
            raise ValueError("invalid_lab_visit_scope")
        payload = dict(public=dict(provider="elation", mode="synthetic", workspace_id=workspace_id,
            practice=old.public.practice.model_dump(mode="json"), window=old.public.window.model_dump(mode="json"),
            observed_at=observed.observed_at, patient_identity_json=identity_json(observed.patient),
            parent=dict(observation_id=prior.id, source_sha256=previous.source_sha256, item_sha256=item_sha256), **projection),
            private=dict(lab_contract="elation_lab.v1", binding_sha256=read.binding_digest, request_sha256=read.request_hash,
                workspace_id=workspace_id, patient_link_id=w.patient_link_id, items=[item.model_dump(mode="json") for item in items],
                visit_provider_sources=[appointment_result.source_sha256, patient_result.source_sha256], **proof))
        normalized = SnapshotPayload.model_validate(payload).model_dump(mode="json")
        if len(canonical_json(normalized).encode()) > 65536:
            raise ws.WorkspaceError("ehr_read_response_too_large", 503)
        return ehr._store(s, read.id, payload, port, reauthenticate)
    except Exception as error:
        s.rollback()
        if isinstance(error, ws.WorkspaceError):
            raise
        raise ehr._provider_error(error) from None
