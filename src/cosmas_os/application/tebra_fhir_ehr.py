"""FHIR-specific selection and payload validation using existing EHR source custody."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from cosmas_os.adapters.tebra_fhir_read import (
    TebraFhirMedication,
    TebraFhirMedicationRead,
    TebraFhirPatient,
    TebraFhirScope,
)
from cosmas_os.adapters.tebra_fhir_read_runtime import (
    SyntheticTebraFhirReads,
    TebraFhirAuthorizedPatient,
    TebraFhirConnectionScope,
)
from cosmas_os.application import model_work
from cosmas_os.application import workspace as ws
from cosmas_os.application.tebra_fhir_snapshot import prepare_medication_review
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import (
    EhrFhirPatientGrant,
    EhrReadBinding,
    EhrReadRequest,
    EhrReadSnapshot,
)
from cosmas_os.ports.ehr_reads import SnapshotPayload
from cosmas_os.ports.tebra_fhir_ehr import (
    FhirMedicationsObservation,
    FhirPatientsObservation,
    FhirPrivateItem,
    FhirPrivateSnapshot,
    reader_object,
)

KINDS = ("fhir_patients", "fhir_medications")


def scope(binding):
    return TebraFhirConnectionScope(UUID(binding.box_id), UUID(binding.owner_id), UUID(binding.account_id),
        UUID(binding.connection_id), UUID(binding.credential_generation), binding.practice_name)


def grant(s, identifier, *, current=False):
    query = select(EhrFhirPatientGrant).where(EhrFhirPatientGrant.id == str(identifier)).execution_options(populate_existing=True)
    row = s.scalar(query.with_for_update(read=True) if current else query)
    binding = s.get(EhrReadBinding, row.binding_id) if row else None
    if row is None or binding is None or binding.protocol != "fhir":
        raise ws.WorkspaceError("ehr_read_fhir_grant_unavailable")
    value = TebraFhirAuthorizedPatient(UUID(row.id), scope(binding), UUID(row.workspace_id), UUID(row.patient_link_id),
        row.fhir_patient_id, row.authorization_sha256, row.identity_json, row.identity_sha256)
    if value.commitment() != row.grant_digest or current and row.state != "active":
        raise ws.WorkspaceError("ehr_read_fhir_grant_changed")
    return row, value


def workspace(s, read):
    value = ws._workspace(s, read.box_id, read.owner_id, read.workspace_id)
    if value.patient_link_id != read.patient_link_id:
        raise ws.WorkspaceError("ehr_read_patient_changed")
    return value


def authorize(s, read, binding, port):
    from cosmas_os.application import provider_team

    if not (provider_team.runtime_settings.workspace_ehr_read_available
            and provider_team.runtime_settings.workspace_tebra_fhir_enabled):
        raise ws.WorkspaceError("ehr_read_unavailable", 404)
    workspace(s, read)
    if type(port) is not SyntheticTebraFhirReads or not port.current(scope(binding)):
        raise ws.WorkspaceError("ehr_read_binding_changed")
    if read.kind == "fhir_medications":
        row, selected = grant(s, read.fhir_grant_id, current=True)
        if (row.binding_id, row.workspace_id, row.patient_link_id) != (read.binding_id, read.workspace_id, read.patient_link_id) or not port.current_patient(selected):
            raise ws.WorkspaceError("ehr_read_fhir_grant_changed")
    else:
        snapshot = s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == read.id))
        if snapshot is not None:
            payload = SnapshotPayload.model_validate(snapshot.payload)
            if not isinstance(payload.private, FhirPrivateSnapshot):
                raise ws.WorkspaceError("ehr_read_source_invalid")
            for item in payload.private.items:
                _, selected = grant(s, item.grant_id, current=True)
                if not port.current_patient(selected):
                    raise ws.WorkspaceError("ehr_read_fhir_grant_changed")
    return binding


def status(s, box, actor, account_id, *, enabled, port, reauthenticate=None):
    from cosmas_os.application import ehr_reads as ehr

    account = ehr._identity(s, box, actor, account_id)
    if reauthenticate:
        reauthenticate()
    empty = dict(contract_version=1, provider="tebra", protocol="fhir", mode="synthetic", transport="mock",
        status="not_configured" if enabled else "not_enabled", connection_id=None, binding_sha256=None, display_label=None)
    if not enabled or type(port) is not SyntheticTebraFhirReads:
        return empty
    rows = list(s.scalars(select(EhrReadBinding).where(EhrReadBinding.box_id == box, EhrReadBinding.owner_id == actor,
        EhrReadBinding.account_id == account_id, EhrReadBinding.vendor == "tebra", EhrReadBinding.protocol == "fhir", EhrReadBinding.state == "active")))
    if len(rows) != 1:
        return empty
    try:
        binding = ehr._binding(s, account, rows[0].connection_id, rows[0].binding_digest, port=port)
        if reauthenticate:
            reauthenticate()
        ehr._binding(s, account, binding.connection_id, binding.binding_digest, port=port)
    except ws.WorkspaceError:
        return empty
    return {**empty, "status": "ready", "connection_id": binding.connection_id,
        "binding_sha256": binding.binding_digest, "display_label": binding.practice_name}


def reader_json(read):
    value = asdict(read)
    value["scope"] = {key: str(item) for key, item in value["scope"].items()}
    value["observed_at"] = read.observed_at.isoformat()
    return canonical_json(value)


def reader(raw):
    value = reader_object(raw)
    if canonical_json(value) != raw or set(value) != {"scope", "patient", "observed_at", "rows", "coverage", "reported_total", "warnings", "source_sha256", "provider_sources"}:
        raise ValueError("invalid_fhir_reader_payload")
    scoped = value["scope"]
    scoped = TebraFhirScope(box_id=UUID(scoped["box_id"]), owner_id=UUID(scoped["owner_id"]),
        connection_id=UUID(scoped["connection_id"]), credential_generation=UUID(scoped["credential_generation"]),
        patient_id=scoped["patient_id"], authorization_sha256=scoped["authorization_sha256"])
    return TebraFhirMedicationRead(scope=scoped, patient=TebraFhirPatient(**value["patient"]),
        observed_at=datetime.fromisoformat(value["observed_at"]), rows=tuple(TebraFhirMedication(**row) for row in value["rows"]),
        coverage=value["coverage"], reported_total=value["reported_total"], warnings=tuple(value["warnings"]),
        source_sha256=value["source_sha256"], provider_sources=tuple(value["provider_sources"]))


def patient_item(item):
    from cosmas_os.application import ehr_reads as ehr

    value = dict(handle=str(item.handle), patient_identity_json=item.patient_identity_json)
    return {**value, "sha256": ehr.item_hash("fhir_patients", value)}


def medication_item(item, prepared):
    from cosmas_os.application import ehr_reads as ehr

    observed = prepared.observation
    value = dict(handle=str(item.handle), patient_identity_json=item.patient_identity_json,
        coverage=observed.coverage, reported_total=observed.reported_total, warnings=list(observed.warnings),
        records=[{key: value for key, value in asdict(row).items() if key not in ("record_id", "patient_id")} for row in observed.rows],
        source_content=prepared.source_content, content_sha256=prepared.source_content_sha256)
    return {**value, "sha256": ehr.item_hash("fhir_medications", value)}


def validate_snapshot(s, read, snap):
    from cosmas_os.application import ehr_reads as ehr

    payload = SnapshotPayload.model_validate(snap.payload)
    pub, priv = payload.public, payload.private
    binding = s.get(EhrReadBinding, read.binding_id)
    if (not isinstance(pub, (FhirPatientsObservation, FhirMedicationsObservation)) or not isinstance(priv, FhirPrivateSnapshot)
            or binding is None or binding.protocol != "fhir" or binding.vendor != "tebra" or read.transport != "mock"
            or pub.kind != read.kind or str(pub.workspace_id) != read.workspace_id
            or pub.display_label != binding.practice_name or str(priv.workspace_id) != read.workspace_id
            or str(priv.patient_link_id) != read.patient_link_id
            or (snap.box_id, snap.owner_id) != (read.box_id, read.owner_id)
            or priv.binding_sha256 != read.binding_digest or priv.request_sha256 != read.request_hash
            or read.request_hash != payload_hash(read.request_json) or snap.payload_sha256 != payload_hash(snap.payload)
            or snap.source_sha256 != ehr._commitment(read, snap.payload_sha256)
            or len(canonical_json(snap.payload).encode()) > 65536
            or len({item.handle for item in priv.items}) != len(priv.items)):
        raise ValueError("invalid_fhir_snapshot")
    for item in priv.items:
        row, selected = grant(s, item.grant_id)
        if (row.binding_id, row.workspace_id, row.patient_link_id) != (read.binding_id, read.workspace_id, read.patient_link_id) or item.grant_sha256 != selected.commitment() or item.patient_identity_json != selected.identity_json:
            raise ValueError("invalid_fhir_selection")
    if isinstance(pub, FhirPatientsObservation):
        if priv.reader_snapshot_json is not None or pub.model_dump(mode="json")["items"] != [patient_item(item) for item in priv.items]:
            raise ValueError("invalid_fhir_candidates")
    else:
        if len(priv.items) != 1 or str(priv.items[0].grant_id) != read.fhir_grant_id or str(priv.items[0].handle) != read.item_handle:
            raise ValueError("invalid_fhir_selected_grant")
        item = priv.items[0]
        _, selected = grant(s, item.grant_id)
        parent = s.get(EhrReadSnapshot, read.parent_snapshot_id)
        prior = s.get(EhrReadRequest, parent.observation_id) if parent else None
        if prior is None or prior.kind != "fhir_patients":
            raise ValueError("invalid_fhir_parent")
        ehr._snapshot(s, prior)
        original = SnapshotPayload.model_validate(parent.payload)
        matched = next((old for old in original.private.items if old.handle == item.handle), None)
        if (matched != item or (prior.workspace_id, prior.patient_link_id, prior.binding_id) != (read.workspace_id, read.patient_link_id, read.binding_id)
                or pub.parent.model_dump(mode="json") != dict(observation_id=prior.id, source_sha256=parent.source_sha256, item_sha256=patient_item(item)["sha256"])
                or read.request_json["observation_id"] != prior.id or read.request_json["observation_sha256"] != parent.source_sha256
                or read.request_json["item_sha256"] != patient_item(item)["sha256"]):
            raise ValueError("invalid_fhir_parent_proof")
        observed = reader(priv.reader_snapshot_json)
        # Structural replay uses immutable server grant pins; current authority is checked separately at every release/admission.
        prepared = prepare_medication_review(observed, expected_scope=selected.read_scope(), expected_source_sha256=observed.source_sha256,
            expected_patient_identity_sha256=selected.identity_sha256, authorize_read=lambda _: True)
        if (prepared.snapshot_sha256 != priv.review_sha256 or observed.patient.identity_json != item.patient_identity_json
                or pub.observed_at != observed.observed_at or pub.item.model_dump(mode="json") != medication_item(item, prepared)):
            raise ValueError("invalid_fhir_review_projection")
    return snap


def patients(s, box, actor, account_id, *, key, connection_id, binding_sha256, workspace_id, port, reauthenticate=None):
    from cosmas_os.application import ehr_reads as ehr

    ehr._key(key)
    ehr._digest(binding_sha256)
    account = ehr._access(s, box, actor, account_id, reauthenticate)
    binding = ehr._binding(s, account, connection_id, binding_sha256, port=port)
    if binding.protocol != "fhir" or type(port) is not SyntheticTebraFhirReads:
        raise ws.WorkspaceError("ehr_read_provider_mismatch", 409)
    w = ws._workspace(s, box, actor, workspace_id, writing=True)
    body = dict(provider="tebra", protocol="fhir", action="fhir_patients", connection_id=connection_id,
        binding_sha256=binding_sha256, workspace_id=workspace_id, idempotency_key=key)
    read, replay = ehr._reserve(s, account, binding, body, None, port=port, workspace=w)
    if replay is not None:
        return replay
    try:
        candidates = port.patient_candidates(scope(binding), UUID(w.id), UUID(w.patient_link_id),
            authorize=lambda: ehr._provider_authorize(s, read.id, port, reauthenticate))
        items = []
        for selected in candidates:
            row, current = grant(s, selected.grant_id)
            if current != selected:
                raise ws.WorkspaceError("ehr_read_fhir_grant_changed")
            if row.state == "active":
                items.append(FhirPrivateItem(handle=uuid4(), grant_id=selected.grant_id,
                    grant_sha256=selected.commitment(), patient_identity_json=selected.identity_json))
        payload = dict(public=dict(provider="tebra", protocol="fhir", mode="synthetic", kind="fhir_patients",
            workspace_id=w.id, display_label=binding.practice_name, observed_at=model_work.now(s), coverage="authorized_candidates_only",
            items=[patient_item(item) for item in items]), private=dict(protocol="fhir", binding_sha256=read.binding_digest,
            request_sha256=read.request_hash, workspace_id=w.id, patient_link_id=w.patient_link_id,
            items=[item.model_dump(mode="json") for item in items], reader_snapshot_json=None, review_sha256=None))
        return ehr._store(s, read.id, payload, port, reauthenticate)
    except Exception as error:
        s.rollback()
        if isinstance(error, ws.WorkspaceError):
            raise
        raise ehr._provider_error(error) from None


def medications(s, box, actor, account_id, *, key, connection_id, binding_sha256, workspace_id,
        observation_id, observation_sha256, item_handle, item_sha256, port, reauthenticate=None):
    from cosmas_os.application import ehr_reads as ehr

    ehr._key(key)
    for digest in (binding_sha256, observation_sha256, item_sha256):
        ehr._digest(digest)
    account = ehr._access(s, box, actor, account_id, reauthenticate)
    binding = ehr._binding(s, account, connection_id, binding_sha256, port=port)
    prior = ehr._read(s, box, actor, account_id, observation_id)
    ehr._require_provider(s, prior, "tebra", "fhir")
    if prior.kind != "fhir_patients" or prior.binding_id != binding.id or prior.workspace_id != workspace_id:
        raise ws.WorkspaceError("ehr_read_not_observed")
    ehr._authorize(s, prior, port=port)
    ehr._current(s, prior)
    parent = ehr._snapshot(s, prior)
    original = SnapshotPayload.model_validate(parent.payload)
    if not isinstance(original.private, FhirPrivateSnapshot):
        raise ws.WorkspaceError("ehr_read_source_invalid")
    item = next((item for item in original.private.items if str(item.handle) == item_handle), None)
    if parent.source_sha256 != observation_sha256 or item is None or patient_item(item)["sha256"] != item_sha256:
        raise ws.WorkspaceError("ehr_read_not_observed")
    row, selected = grant(s, item.grant_id, current=True)
    w = workspace(s, prior)
    body = dict(provider="tebra", protocol="fhir", action="fhir_medications", connection_id=connection_id,
        binding_sha256=binding_sha256, workspace_id=workspace_id, idempotency_key=key, observation_id=observation_id,
        observation_sha256=observation_sha256, item_handle=item_handle, item_sha256=item_sha256)
    read, replay = ehr._reserve(s, account, binding, body, None, parent=parent, item_handle=item_handle, port=port, workspace=w, grant=row)
    if replay is not None:
        return replay
    try:
        prepared = port.medications(scope(binding), selected, authorize=lambda: ehr._provider_authorize(s, read.id, port, reauthenticate))
        payload = dict(public=dict(provider="tebra", protocol="fhir", mode="synthetic", kind="fhir_medications",
            workspace_id=w.id, display_label=binding.practice_name, observed_at=prepared.observation.observed_at,
            parent=dict(observation_id=prior.id, source_sha256=parent.source_sha256, item_sha256=item_sha256),
            item=medication_item(item, prepared)), private=dict(protocol="fhir", binding_sha256=read.binding_digest,
                request_sha256=read.request_hash, workspace_id=w.id, patient_link_id=w.patient_link_id,
                items=[item.model_dump(mode="json")], reader_snapshot_json=reader_json(prepared.observation), review_sha256=prepared.snapshot_sha256))
        return ehr._store(s, read.id, payload, port, reauthenticate)
    except Exception as error:
        s.rollback()
        if isinstance(error, ws.WorkspaceError):
            raise
        raise ehr._provider_error(error) from None
