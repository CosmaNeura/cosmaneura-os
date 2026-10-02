"""Explicit personal patient-link custody; no scheduling or clinical-note writes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC
from uuid import UUID, uuid4

from pydantic import AwareDatetime, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from cosmas_os.application import model_work
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    ExternalIdentity,
    PatientLink,
    SchedulingAccount,
    SchedulingPatientAccount,
)
from cosmas_os.ports.scheduling import SchedulingSelection
from cosmas_os.ports.scheduling_patient_setup import (
    Digest,
    PatientPreview,
    PatientPreviewRequest,
    PatientVerification,
    PatientVerifyRequest,
    SearchPatientSelector,
    patient_digest,
    validate_preview,
    validate_verification,
)
from cosmas_os.ports.scribe_capture import ProtectedModel
from cosmas_os.scheduling_login_models import SchedulingLoginCredential
from cosmas_os.scheduling_patient_models import (
    SchedulingPatientMappingReview,
    SchedulingPatientSetupRequest,
    SchedulingPatientSetupSnapshot,
)

_binding_reader = None


class PatientSetupBinding(ProtectedModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    account_id: str = Field(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    selection: SchedulingSelection
    binding_sha256: Digest
    connected_at: AwareDatetime
    grant_sha256: Digest


@contextmanager
def install_binding_reader(reader):
    global _binding_reader
    previous, _binding_reader = _binding_reader, reader
    try:
        yield
    finally:
        _binding_reader = previous


def _gate(configuration):
    if configuration is None or getattr(configuration, "workspace_scheduling_patient_setup_available", False) is not True:
        raise ws.WorkspaceError("scheduling_patient_setup_unavailable", 403)


def _uuid(value):
    try:
        parsed = UUID(str(value))
        if parsed.int == 0 or str(parsed) != str(value):
            raise ValueError
        return str(parsed)
    except (ValueError, TypeError, AttributeError):
        raise ws.WorkspaceError("invalid_scheduling_patient_request", 422) from None


def request_hash(workspace_id, command):
    return patient_digest("cosmas-scheduling-patient-command.v1", {"workspace_id": workspace_id, "request": command})


def _source(s, w):
    a = s.get(AppointmentObservation, w.appointment_id, populate_existing=True)
    p = s.get(PatientLink, w.patient_link_id, populate_existing=True)
    if a is None or p is None:
        raise ws.WorkspaceError("encounter_unavailable", 404)
    return {"workspace_id": w.id, "patient_link_id": w.patient_link_id, "appointment_id": a.id,
        "appointment_source": a.source, "appointment_ref": a.external_id, "source_owner_id": a.source_owner_id,
        "source_sha256": a.source_sha256, "patient_source_owner_id": p.source_owner_id,
        "patient_source_account_id": p.source_account_id, "patient_state": p.state}


def _access(s, box, owner, wid, identity_id, configuration, reauthenticate=None):
    _gate(configuration)
    model_work.lock_owner(s, box, owner)
    if reauthenticate is not None:
        reauthenticate()
    _gate(configuration)
    w = ws._workspace(s, box, owner, wid, writing=True)
    identity = s.scalar(select(ExternalIdentity).where(ExternalIdentity.id == identity_id,
        ExternalIdentity.box_id == box, ExternalIdentity.principal_id == owner, ExternalIdentity.active.is_(True))
        .with_for_update(read=True).execution_options(populate_existing=True))
    if identity is None:
        raise ws.WorkspaceError("workspace_access_denied", 403)
    return w


def _account(s, w, identity_id):
    account = s.scalar(select(SchedulingAccount).where(SchedulingAccount.external_identity_id == identity_id,
        SchedulingAccount.revoked_at.is_(None)).with_for_update(read=True).execution_options(populate_existing=True))
    if account is None:
        raise ws.WorkspaceError("scheduling_connection_required")
    return account


def _binding(s, w, identity_id, account):
    credential = s.scalar(select(SchedulingLoginCredential).where(SchedulingLoginCredential.account_id == account.id)
        .with_for_update(read=True).execution_options(populate_existing=True))
    if credential is None or credential.status != "ready" or credential.sealed is None or credential.expires_at <= model_work.now(s):
        raise ws.WorkspaceError("scheduling_patient_grant_unavailable")
    try:
        if _binding_reader is None:
            raise ValueError
        binding = PatientSetupBinding.model_validate(_binding_reader(s, identity_id, account))
        selected = SchedulingSelection(box_id=w.box_id, owner_id=w.owner_id, practice_id=account.practice_id,
            expected_actor_id=account.actor_id, practitioner_id=account.practitioner_id,
            location_id=account.location_id, appointment_type_id=account.appointment_type_id)
        if (binding.account_id, binding.selection, binding.binding_sha256, binding.connected_at) != (
            account.id, selected, credential.binding_digest, credential.connected_at):
            raise ValueError
        return binding
    except Exception:
        raise ws.WorkspaceError("scheduling_patient_grant_unavailable") from None


def _current(s, w, request, configuration, *, revision=False):
    _gate(configuration)
    ws._workspace(s, w.box_id, w.owner_id, w.id)
    identity = s.scalar(select(ExternalIdentity.id).where(ExternalIdentity.id == request.external_identity_id,
        ExternalIdentity.box_id == w.box_id, ExternalIdentity.principal_id == w.owner_id, ExternalIdentity.active.is_(True)))
    if identity is None:
        raise ws.WorkspaceError("scheduling_patient_account_changed")
    if (request.workspace_id, request.box_id, request.owner_id, request.patient_link_id) != (w.id, w.box_id, w.owner_id, w.patient_link_id):
        raise ws.WorkspaceError("scheduling_patient_source_changed")
    account = _account(s, w, request.external_identity_id)
    binding = _binding(s, w, request.external_identity_id, account)
    if (account.id, binding.selection.model_dump(mode="json"), binding.binding_sha256, binding.connected_at, binding.grant_sha256) != (
        request.account_id, request.selection, request.binding_sha256, request.connected_at, request.grant_sha256):
        raise ws.WorkspaceError("scheduling_patient_account_changed")
    if _source(s, w) != request.source_context or revision and w.revision != request.expected_revision:
        raise ws.WorkspaceError("scheduling_patient_source_changed")
    if request.kind == "preview":
        _latest(s, request)
    else:
        _latest(s, _parent(s, request))
    return binding


def _latest(s, request):
    newest = s.scalar(select(func.max(SchedulingPatientSetupRequest.ordinal)).where(
        SchedulingPatientSetupRequest.account_id == request.account_id,
        SchedulingPatientSetupRequest.workspace_id == request.workspace_id, SchedulingPatientSetupRequest.kind == "preview"))
    if newest != request.ordinal:
        raise ws.WorkspaceError("scheduling_patient_preview_superseded")


def _parent(s, request):
    parent = s.get(SchedulingPatientSetupRequest, request.preview_request_id)
    if parent is None or parent.kind != "preview" or (parent.workspace_id, parent.box_id, parent.owner_id, parent.account_id,
        parent.patient_link_id, parent.external_identity_id) != (request.workspace_id, request.box_id, request.owner_id,
        request.account_id, request.patient_link_id, request.external_identity_id):
        raise ws.WorkspaceError("scheduling_patient_receipt_invalid")
    return parent


def _source_hash(request, payload_sha256):
    return patient_digest("cosmas-scheduling-patient-source.v1", {"request_id": request.id,
        "request_sha256": request.request_sha256, "account_id": request.account_id,
        "binding_sha256": request.binding_sha256, "connected_at": request.connected_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "grant_sha256": request.grant_sha256, "source_context_sha256": request.source_context_sha256,
        "payload_sha256": payload_sha256})


def _snapshot(s, request):
    snap = s.scalar(select(SchedulingPatientSetupSnapshot).where(SchedulingPatientSetupSnapshot.request_id == request.id))
    if snap is None:
        return None
    try:
        if request.request_sha256 != request_hash(request.workspace_id, request.command) or request.source_context_sha256 != patient_digest(
            "cosmas-scheduling-patient-context.v1", request.source_context):
            raise ValueError
        parsed = (PatientPreview if request.kind == "preview" else PatientVerification).model_validate(snap.payload)
        _public_revision(parsed)
        if (str(parsed.request_nonce), str(parsed.practice_id), str(parsed.actor_id)) != (request.request_nonce,
            request.selection["practice_id"], request.selection["expected_actor_id"]):
            raise ValueError
        if (snap.workspace_id, snap.box_id, snap.owner_id) != (request.workspace_id, request.box_id, request.owner_id):
            raise ValueError
        if snap.payload_sha256 != patient_digest("cosmas-scheduling-patient-payload.v1", snap.payload) or snap.source_sha256 != _source_hash(request, snap.payload_sha256):
            raise ValueError
        if request.kind == "confirm":
            parent = _parent(s, request)
            prior = _snapshot(s, parent)
            if prior is None:
                raise ValueError
            preview = PatientPreview.model_validate(prior.payload)
            choice = next((v for v in preview.choices if str(v.choice_ref) == request.command["choice_ref"]), None)
            if not isinstance(parsed, PatientVerification) or choice is None or parsed.identity != choice or parsed.lookup_ref != preview.lookup_ref:
                raise ValueError
            if (str(parent.id), prior.source_sha256, choice.identity_sha256) != (request.command["preview_id"],
                request.command["preview_sha256"], request.command["identity_sha256"]):
                raise ValueError
        return snap
    except (ValueError, TypeError, KeyError):
        raise ws.WorkspaceError("scheduling_patient_receipt_invalid") from None


def _public_revision(value):
    identities = value.choices if isinstance(value, PatientPreview) else (value.identity,)
    if any(item.subject_revision > 9007199254740991 for item in identities):
        raise ws.WorkspaceError("scheduling_patient_receipt_invalid")


def mapping_hash(review, request, verification):
    return patient_digest("cosmas-scheduling-patient-mapping.v1", {"review_id": review.id, "mapping_id": review.mapping_id,
        "request_id": request.id, "request_sha256": request.request_sha256, "box_id": request.box_id,
        "owner_id": request.owner_id, "patient_link_id": request.patient_link_id, "account_id": request.account_id,
        "practice_id": str(verification.practice_id), "patient_id": str(verification.patient_id),
        "identity_sha256": verification.identity.identity_sha256, "subject_revision": verification.identity.subject_revision})


def _mapping(s, request, snap):
    review = s.scalar(select(SchedulingPatientMappingReview).where(SchedulingPatientMappingReview.request_id == request.id))
    if review is None:
        raise ws.WorkspaceError("scheduling_patient_receipt_invalid")
    mapping = s.get(SchedulingPatientAccount, review.mapping_id, populate_existing=True)
    verification = PatientVerification.model_validate(snap.payload)
    if mapping is None or (review.snapshot_id, review.workspace_id, review.box_id, review.owner_id, review.patient_link_id,
        mapping.box_id, mapping.patient_link_id, mapping.practice_id, mapping.patient_id, mapping.reviewed_by,
        mapping.evidence_ref, mapping.reviewed_at) != (snap.id, request.workspace_id, request.box_id, request.owner_id,
        request.patient_link_id, request.box_id, request.patient_link_id, str(verification.practice_id), str(verification.patient_id),
        request.owner_id, "scheduling-patient:v1:" + review.id, review.created_at):
        raise ws.WorkspaceError("scheduling_patient_receipt_invalid")
    if not review.reviewed_same_patient or not review.reviewed_exact_identity or review.mapping_sha256 != mapping_hash(review, request, verification):
        raise ws.WorkspaceError("scheduling_patient_receipt_invalid")
    return review, mapping, verification


def _receipt(s, w, request, configuration):
    snap = _snapshot(s, request)
    withheld = False
    preview, mapping = None, None
    try:
        _current(s, w, request, configuration)
        if snap is not None:
            parsed = (PatientPreview if request.kind == "preview" else PatientVerification).model_validate(snap.payload)
            if parsed.expires_at <= model_work.now(s) and request.kind == "preview":
                raise ws.WorkspaceError("scheduling_patient_preview_expired")
    except ws.WorkspaceError:
        withheld = True
    if snap is not None and request.kind == "confirm":
        review, row, verified = _mapping(s, request, snap)
        if row.revoked_at is not None:
            withheld = True
        if not withheld:
            mapping = {"mapping_id": row.id, "mapping_sha256": review.mapping_sha256,
                "identity_sha256": verified.identity.identity_sha256, "subject_revision": verified.identity.subject_revision}
    elif snap is not None and not withheld:
        parsed = PatientPreview.model_validate(snap.payload)
        preview = parsed.model_dump(mode="json", include={"checked_at", "expires_at", "choices", "more"})
    return {"contract_version": 1, "kind": request.kind, "request_id": request.id, "request_key": request.idempotency_key,
        "request_sha256": request.request_sha256, "status": "saved" if snap is not None else "unconfirmed",
        "source_withheld": withheld, "source_sha256": snap.source_sha256 if snap is not None else None,
        "preview": preview, "mapping": mapping}


def _find(s, w, identity_id, kind, key):
    row = s.scalar(select(SchedulingPatientSetupRequest).where(SchedulingPatientSetupRequest.workspace_id == w.id,
        SchedulingPatientSetupRequest.owner_id == w.owner_id, SchedulingPatientSetupRequest.kind == kind,
        SchedulingPatientSetupRequest.idempotency_key == key))
    if row is not None and row.external_identity_id != identity_id:
        raise ws.WorkspaceError("scheduling_patient_receipt_unavailable", 404)
    return row


def _reserve(s, w, identity_id, command, configuration, parent=None):
    account = _account(s, w, identity_id)
    binding = _binding(s, w, identity_id, account)
    if w.revision != command["expected_revision"]:
        raise ws.WorkspaceError("workspace_revision_conflict")
    if command["action"] == "preview":
        # A fresh preview would supersede the current sidecar. Replacement of
        # an existing patient mapping needs a separate explicit review path.
        _conflict(s, w, str(binding.selection.practice_id))
    context = _source(s, w)
    ordinal = (s.scalar(select(func.max(SchedulingPatientSetupRequest.ordinal)).where(
        SchedulingPatientSetupRequest.account_id == account.id, SchedulingPatientSetupRequest.workspace_id == w.id)) or 0) + 1
    if ordinal > 500:
        raise ws.WorkspaceError("scheduling_patient_setup_limit")
    request = SchedulingPatientSetupRequest(workspace_id=w.id, box_id=w.box_id, owner_id=w.owner_id,
        patient_link_id=w.patient_link_id, external_identity_id=identity_id, account_id=account.id, ordinal=ordinal,
        expected_revision=command["expected_revision"], kind=command["action"], idempotency_key=command["idempotency_key"],
        request_sha256=request_hash(w.id, command), command=command, selection=binding.selection.model_dump(mode="json"),
        binding_sha256=binding.binding_sha256, connected_at=binding.connected_at, grant_sha256=binding.grant_sha256,
        source_context=context, source_context_sha256=patient_digest("cosmas-scheduling-patient-context.v1", context),
        preview_request_id=parent.id if parent is not None else None)
    s.add(request)
    ws._audit(s, w, "scheduling_patient_" + command["action"] + "_reserved")
    s.flush()
    return request, binding


def _save_snapshot(s, request, parsed):
    payload = parsed.model_dump(mode="json")
    snap = SchedulingPatientSetupSnapshot(workspace_id=request.workspace_id, box_id=request.box_id, owner_id=request.owner_id,
        request_id=request.id, payload=payload, payload_sha256=patient_digest("cosmas-scheduling-patient-payload.v1", payload))
    snap.source_sha256 = _source_hash(request, snap.payload_sha256)
    s.add(snap)
    s.flush()
    _snapshot(s, request)
    return snap


def preview(s, box, owner, wid, external_identity_id, *, expected_revision, key, search, port, configuration, reauthenticate=None):
    from cosmas_os.api.scheduling_patient_schemas import Preview
    try:
        command = Preview(action="preview", expected_revision=expected_revision, idempotency_key=UUID(_uuid(key)),
            search=SearchPatientSelector.model_validate(search)).model_dump(mode="json")
    except ValueError:
        raise ws.WorkspaceError("invalid_scheduling_patient_request", 422) from None
    try:
        w = _access(s, box, owner, wid, external_identity_id, configuration, reauthenticate)
        prior = _find(s, w, external_identity_id, "preview", command["idempotency_key"])
        if prior is not None:
            if prior.request_sha256 != request_hash(wid, command):
                raise ws.WorkspaceError("idempotency_conflict")
            result = _receipt(s, w, prior, configuration)
            if reauthenticate is not None:
                reauthenticate()
            _gate(configuration)
            final = _receipt(s, w, prior, configuration)
            if result["source_withheld"]:
                final.update(source_withheld=True, preview=None, mapping=None)
            result = final
            s.commit()
            return result
        birth_date = SearchPatientSelector.model_validate(command["search"]).birth_date
        if birth_date is not None and birth_date > model_work.now(s).date():
            raise ws.WorkspaceError("invalid_scheduling_patient_request", 422)
        request, binding = _reserve(s, w, external_identity_id, command, configuration)
        assert binding.selection.expected_actor_id is not None
        read_id, wire = request.id, PatientPreviewRequest(request_nonce=UUID(request.request_nonce),
            expected_actor_id=binding.selection.expected_actor_id, selector=command["search"], limit=5)
        s.commit()
        assert not s.in_transaction()
        parsed = PatientPreview.model_validate(port.preview(binding.selection, wire))
        w = _access(s, box, owner, wid, external_identity_id, configuration, reauthenticate)
        request = s.get(SchedulingPatientSetupRequest, read_id, populate_existing=True)
        _current(s, w, request, configuration, revision=True)
        _public_revision(parsed)
        validate_preview(binding.selection, wire, parsed, model_work.now(s))
        _save_snapshot(s, request, parsed)
        if reauthenticate is not None:
            reauthenticate()
        _current(s, w, request, configuration, revision=True)
        result = _receipt(s, w, request, configuration)
        s.commit()
        return result
    except ws.WorkspaceError:
        s.rollback()
        raise
    except Exception:
        s.rollback()
        raise ws.WorkspaceError("scheduling_patient_response_unconfirmed", 503) from None


def confirm(s, box, owner, wid, external_identity_id, *, expected_revision, key, preview_id, preview_sha256,
            choice_ref, identity_sha256, reviewed_same_patient, reviewed_exact_identity, port, configuration, reauthenticate=None):
    from cosmas_os.api.scheduling_patient_schemas import Confirm
    try:
        command = Confirm(action="confirm", expected_revision=expected_revision, idempotency_key=UUID(_uuid(key)), preview_id=UUID(_uuid(preview_id)),
            preview_sha256=preview_sha256, choice_ref=UUID(_uuid(choice_ref)), identity_sha256=identity_sha256,
            reviewed_same_patient=reviewed_same_patient, reviewed_exact_identity=reviewed_exact_identity).model_dump(mode="json")
    except ValueError:
        raise ws.WorkspaceError("invalid_scheduling_patient_request", 422) from None
    try:
        w = _access(s, box, owner, wid, external_identity_id, configuration, reauthenticate)
        prior = _find(s, w, external_identity_id, "confirm", command["idempotency_key"])
        if prior is not None:
            if prior.request_sha256 != request_hash(wid, command):
                raise ws.WorkspaceError("idempotency_conflict")
            result = _receipt(s, w, prior, configuration)
            if reauthenticate is not None:
                reauthenticate()
            _gate(configuration)
            final = _receipt(s, w, prior, configuration)
            if result["source_withheld"]:
                final.update(source_withheld=True, preview=None, mapping=None)
            result = final
            s.commit()
            return result
        parent = s.get(SchedulingPatientSetupRequest, command["preview_id"])
        if parent is None or parent.kind != "preview" or (parent.workspace_id, parent.owner_id, parent.external_identity_id) != (wid, owner, external_identity_id):
            raise ws.WorkspaceError("scheduling_patient_receipt_unavailable", 404)
        _current(s, w, parent, configuration)
        snap = _snapshot(s, parent)
        if snap is None or snap.source_sha256 != preview_sha256:
            raise ws.WorkspaceError("scheduling_patient_receipt_invalid")
        checked = PatientPreview.model_validate(snap.payload)
        choice = next((v for v in checked.choices if str(v.choice_ref) == command["choice_ref"]), None)
        if choice is None or choice.identity_sha256 != identity_sha256 or checked.expires_at <= model_work.now(s):
            raise ws.WorkspaceError("scheduling_patient_preview_expired")
        request, binding = _reserve(s, w, external_identity_id, command, configuration, parent)
        _conflict(s, w, str(checked.practice_id))
        assert binding.selection.expected_actor_id is not None
        read_id, wire = request.id, PatientVerifyRequest(request_nonce=UUID(request.request_nonce), expected_actor_id=binding.selection.expected_actor_id,
            lookup_ref=checked.lookup_ref, choice_ref=choice.choice_ref, identity_sha256=identity_sha256)
        s.commit()
        assert not s.in_transaction()
        verified = PatientVerification.model_validate(port.verify(binding.selection, wire, checked))
        w = _access(s, box, owner, wid, external_identity_id, configuration, reauthenticate)
        request = s.get(SchedulingPatientSetupRequest, read_id, populate_existing=True)
        _current(s, w, request, configuration, revision=True)
        _public_revision(verified)
        validate_verification(binding.selection, wire, checked, verified, model_work.now(s))
        _conflict(s, w, str(verified.practice_id), str(verified.patient_id))
        snap = _save_snapshot(s, request, verified)
        at, review_id, mapping_id = model_work.now(s), str(uuid4()), str(uuid4())
        mapping = SchedulingPatientAccount(id=mapping_id, box_id=box, patient_link_id=w.patient_link_id,
            practice_id=str(verified.practice_id), patient_id=str(verified.patient_id), reviewed_by=owner,
            evidence_ref="scheduling-patient:v1:" + review_id, reviewed_at=at)
        s.add(mapping)
        s.flush()
        review = SchedulingPatientMappingReview(id=review_id, workspace_id=wid, box_id=box, owner_id=owner,
            request_id=request.id, snapshot_id=snap.id, mapping_id=mapping_id, patient_link_id=w.patient_link_id,
            reviewed_same_patient=True, reviewed_exact_identity=True, created_at=at)
        review.mapping_sha256 = mapping_hash(review, request, verified)
        s.add(review)
        s.flush()
        ws._audit(s, w, "scheduling_patient_link_reviewed")
        _mapping(s, request, snap)
        if reauthenticate is not None:
            reauthenticate()
        _current(s, w, request, configuration, revision=True)
        result = _receipt(s, w, request, configuration)
        s.commit()
        return result
    except IntegrityError as error:
        s.rollback()
        if (getattr(error.orig, "sqlstate", None) == "23505" and
            getattr(getattr(error.orig, "diag", None), "constraint_name", None) in {
                "uq_scheduling_patient_active_link", "uq_scheduling_patient_active_remote"}):
            raise ws.WorkspaceError("scheduling_patient_mapping_review_required") from None
        raise
    except ws.WorkspaceError:
        s.rollback()
        raise
    except Exception:
        s.rollback()
        raise ws.WorkspaceError("scheduling_patient_response_unconfirmed", 503) from None


def _conflict(s, w, practice_id, patient_id=None):
    condition = SchedulingPatientAccount.patient_link_id == w.patient_link_id
    if patient_id is not None:
        condition = or_(condition, SchedulingPatientAccount.patient_id == patient_id)
    if s.scalar(select(SchedulingPatientAccount.id).where(SchedulingPatientAccount.box_id == w.box_id,
        SchedulingPatientAccount.practice_id == practice_id, SchedulingPatientAccount.revoked_at.is_(None), condition)) is not None:
        raise ws.WorkspaceError("scheduling_patient_mapping_review_required")


def inspect(s, box, owner, wid, external_identity_id, *, request_id, configuration, reauthenticate=None):
    try:
        w = _access(s, box, owner, wid, external_identity_id, configuration, reauthenticate)
        request = s.get(SchedulingPatientSetupRequest, _uuid(request_id))
        if request is None or (request.workspace_id, request.box_id, request.owner_id, request.external_identity_id) != (wid, box, owner, external_identity_id):
            raise ws.WorkspaceError("scheduling_patient_receipt_unavailable", 404)
        result = _receipt(s, w, request, configuration)
        if reauthenticate is not None:
            reauthenticate()
        _gate(configuration)
        # Preserve the first withholding result across the final projection.
        final = _receipt(s, w, request, configuration)
        if result["source_withheld"]:
            final.update(source_withheld=True, preview=None, mapping=None)
        s.commit()
        return final
    except Exception:
        s.rollback()
        raise


def resolve(s, box, owner, wid, external_identity_id, *, kind, key, configuration, reauthenticate=None):
    if kind not in {"preview", "confirm"}:
        raise ws.WorkspaceError("invalid_scheduling_patient_request", 422)
    w = _access(s, box, owner, wid, external_identity_id, configuration, reauthenticate)
    request = _find(s, w, external_identity_id, kind, _uuid(key))
    if request is not None:
        request_id = request.id
        s.commit()
        return inspect(s, box, owner, wid, external_identity_id, request_id=request_id, configuration=configuration, reauthenticate=reauthenticate)
    result = {"contract_version": 1, "kind": kind, "request_id": None, "request_key": str(key), "request_sha256": None,
        "status": "not_found", "source_withheld": False, "source_sha256": None, "preview": None, "mapping": None}
    if reauthenticate is not None:
        reauthenticate()
    _gate(configuration)
    s.commit()
    return result


def personal_mapping_for(s, w, external_identity_id, account, *, configuration):
    _gate(configuration)
    review = s.scalar(select(SchedulingPatientMappingReview).join(SchedulingPatientSetupRequest,
        SchedulingPatientSetupRequest.id == SchedulingPatientMappingReview.request_id).where(
        SchedulingPatientMappingReview.box_id == w.box_id, SchedulingPatientMappingReview.owner_id == w.owner_id,
        SchedulingPatientMappingReview.patient_link_id == w.patient_link_id, SchedulingPatientSetupRequest.account_id == account.id,
        SchedulingPatientSetupRequest.external_identity_id == external_identity_id).order_by(SchedulingPatientMappingReview.created_at.desc()).limit(1))
    if review is None:
        raise ws.WorkspaceError("scheduling_patient_correspondence_required")
    request = s.get(SchedulingPatientSetupRequest, review.request_id)
    _current(s, w, request, configuration)
    snap = _snapshot(s, request)
    if snap is None:
        raise ws.WorkspaceError("scheduling_patient_correspondence_required")
    _, mapping, _ = _mapping(s, request, snap)
    if mapping.revoked_at is not None:
        raise ws.WorkspaceError("scheduling_patient_correspondence_required")
    return mapping


def status(s, box, owner, wid, external_identity_id, *, configuration, reauthenticate=None):
    try:
        w = _access(s, box, owner, wid, external_identity_id, configuration, reauthenticate)
        account = _account(s, w, external_identity_id)
        _binding(s, w, external_identity_id, account)
        try:
            mapping = personal_mapping_for(s, w, external_identity_id, account, configuration=configuration)
            state, mapping_id = "linked", mapping.id
        except ws.WorkspaceError:
            state, mapping_id = "link_required", None
        if reauthenticate is not None:
            reauthenticate()
        _gate(configuration)
        ws._workspace(s, box, owner, wid)
        _binding(s, w, external_identity_id, _account(s, w, external_identity_id))
        if state == "linked":
            try:
                mapping = personal_mapping_for(s, w, external_identity_id, account, configuration=configuration)
                mapping_id = mapping.id
            except ws.WorkspaceError:
                state, mapping_id = "link_required", None
        result = {"contract_version": 1, "state": state, "mapping_id": mapping_id}
        s.commit()
        return result
    except Exception:
        s.rollback()
        raise
