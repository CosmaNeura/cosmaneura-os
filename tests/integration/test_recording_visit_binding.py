"""Real signed association, preserved origins and existing-visit capture admission."""
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_private_recordings import attached, base, finish_body, headers, post
from tests.integration.test_private_recordings import recording as _recording
from tests.integration.test_private_recordings import signed_workspace as _signed_workspace
from tests.integration.test_saved_recording_transcription import SavedCore
from tests.integration.test_workspace_capture import ref

from cosmas_os.adapters.core_capture_admission import HttpCoreCaptureAdmission
from cosmas_os.api import app as api
from cosmas_os.models import CoreCaptureAccount, EncounterWorkspace, PatientLink, Principal
from cosmas_os.private_recording_models import (
    PrivateRecording,
    PrivateRecordingTransfer,
    PrivateRecordingTransferSession,
    PrivateRecordingVisitBinding,
)

recording = _recording
signed_workspace = _signed_workspace


def case(recording):
    f, origin, _, receipt = attached(recording)
    path = base(origin) + "/" + receipt["recording_id"]
    finish = post(f, path + "/finish", finish_body())
    assert finish.status_code == 200, finish.text
    command = {"idempotency_key": str(uuid4()), "target_workspace_id": f.workspace["id"],
        "appointment_id": f.workspace["appointment_id"], "expected_target_revision": f.workspace["revision"],
        "visit_confirmed": True}
    return f, origin, finish.json(), path + "/visit-binding", command


def test_existing_visit_binding_preserves_both_notebooks_and_exact_recovery(recording, session):
    f, origin, receipt, path, command = case(recording)
    before_origin = session.get(EncounterWorkspace, origin["id"]).revision
    before_target = session.get(EncounterWorkspace, f.workspace["id"]).revision
    assert f.client.get(path, headers=headers(f)).json() is None
    response = post(f, path, command)
    assert response.status_code == 200, response.text
    binding = response.json()
    assert binding["origin_workspace_id"] == origin["id"]
    assert binding["target_workspace_id"] == f.workspace["id"]
    assert post(f, path, command).json() == binding
    assert f.client.get(path, headers=headers(f)).json() == binding
    assert post(f, path, {**command, "idempotency_key": str(uuid4())}).status_code == 409
    assert session.get(PrivateRecording, receipt["recording_id"]).workspace_id == origin["id"]
    assert session.get(EncounterWorkspace, origin["id"]).revision == before_origin
    assert session.get(EncounterWorkspace, origin["id"]).appointment_id is None
    assert session.get(EncounterWorkspace, f.workspace["id"]).revision == before_target
    assert session.scalar(select(func.count()).select_from(PrivateRecordingVisitBinding)) == 1


@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_visit_association_is_append_only_in_migrated_postgres(recording, session, verb):
    f, _, _, path, command = case(recording)
    assert post(f, path, command).status_code == 200
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(text(verb + " private_recording_visit_bindings" +
            (" SET created_at=now()" if verb == "UPDATE" else "")))
    assert session.scalar(select(func.count()).select_from(PrivateRecordingVisitBinding)) == 1


@pytest.mark.parametrize("field,value", [("expected_target_revision", 200), ("target_workspace_id", "uuid"),
    ("appointment_id", "uuid"), ("visit_confirmed", False), ("visit_confirmed", "true"), ("audio", "forbidden")])
def test_wrong_target_revision_confirmation_and_audio_refused(recording, session, field, value):
    f, _, _, path, command = case(recording)
    response = post(f, path, {**command, field: str(uuid4()) if value == "uuid" else value})
    assert response.status_code in (404, 409, 422), response.text
    assert session.scalar(select(func.count()).select_from(PrivateRecordingVisitBinding)) == 0


@pytest.mark.parametrize("change", ["revoked_patient", "changed_appointment", "revoked_identity"])
def test_binding_reads_recheck_current_patient_visit_and_identity(recording, session, change):
    f, _, _, path, command = case(recording)
    assert post(f, path, command).status_code == 200
    if change == "revoked_patient":
        session.get(PatientLink, f.appointment.patient_link_id).revoked_at = datetime.now(UTC)
    elif change == "changed_appointment":
        f.appointment.external_id = "changed-invented-appointment"
    else:
        f.binding.active = False
    session.commit()
    response = f.client.get(path, headers=headers(f))
    assert response.status_code in (403, 404, 409)
    assert "receipt_id" not in response.text


def test_another_owner_cannot_receive_the_recording(recording, session):
    f, _, _, path, command = case(recording)
    other = Principal(box_id=f.box, principal_type="human", display_name="Invented other provider")
    session.add(other)
    session.flush()
    target = EncounterWorkspace(box_id=f.box, owner_id=other.id, appointment_id=f.appointment.id,
        patient_link_id=f.appointment.patient_link_id, create_key="invented-other-owner", revision=1)
    session.add(target)
    session.commit()
    assert post(f, path, {**command, "target_workspace_id": target.id}).status_code == 404
    assert session.scalar(select(func.count()).select_from(PrivateRecordingVisitBinding)) == 0


def test_a_visit_with_a_prior_transfer_is_never_replaced(recording, session):
    f, _, receipt, path, command = case(recording)
    session.add(PrivateRecordingTransfer(recording_id=receipt["recording_id"], workspace_id=f.workspace["id"],
        request_sha256="a" * 64, request={"synthetic": "occupied"}))
    session.commit()
    response = post(f, path, command)
    assert response.status_code == 409 and response.json()["detail"] == "private_recording_visit_in_use"
    assert session.scalar(select(func.count()).select_from(PrivateRecordingVisitBinding)) == 0


def setup_capture(recording, session, monkeypatch):
    f, origin, receipt, path, command = case(recording)
    f.appointment.source, f.appointment.external_id = "cosmaneura_core", ref("appointment")
    session.add(CoreCaptureAccount(external_identity_id=f.binding.id,
        core_actor_ref=ref("authority_actor"), core_tenant_ref=ref("authority_tenant"),
        reviewed_by="Invented reviewer", evidence_ref="synthetic:review", reviewed_at=datetime.now(UTC)))
    session.commit()
    response = post(f, path, command)
    assert response.status_code == 200, response.text
    binding = response.json()
    for config in (f.configuration, api.settings):
        monkeypatch.setattr(config, "workspace_capture_backend", "core")
        monkeypatch.setattr(config, "workspace_capture_notes_enabled", True)
        monkeypatch.setattr(config, "core_capture_origin", "https://core.example.invalid")
        monkeypatch.setattr(config, "core_capture_scope", "api://synthetic-core/.default")
        monkeypatch.setattr(config, "core_capture_managed_identity_client_id", str(uuid4()))
    port = SavedCore()
    api.app.dependency_overrides[api._capture_connection] = lambda: port
    source = {"recording_id": receipt["recording_id"], "origin_workspace_id": origin["id"],
        "visit_binding_receipt_id": binding["receipt_id"], "source_sha256": binding["source_sha256"],
        "manifest_sha256": receipt["finish"]["manifest_sha256"], "chunks": 1, "frames": 16000}
    body = {"idempotency_key": str(uuid4()), "saved_recording": source,
        "attestation": {"modality": "in_person", "participant_regions": [], "method": "verbal_attestation",
            "all_parties_consented": True, "granted_at": datetime.now(UTC).isoformat()},
        "configured_capture": {"schema_version": "1.0", "language_mode": "en-US"},
        "bot": {"address": "scribe", "team_revision": 1}}
    return f, port, body


def submit(f, body):
    return f.client.post(f"/workspaces/{f.workspace['id']}/capture/admission",
        headers={"Authorization": "Bearer " + f.token()}, json=body)


def test_existing_visit_uses_original_audio_and_recovers_same_admission(recording, session, monkeypatch):
    f, port, body = setup_capture(recording, session, monkeypatch)
    try:
        first = submit(f, body)
        assert first.status_code == 200, first.text
        assert first.json()["workspace_id"] == f.workspace["id"]
        assert submit(f, body).json() == first.json()
        assert port.keys[0] == port.keys[1]
        assert submit(f, {**body, "saved_recording": {**body["saved_recording"], "origin_workspace_id": str(uuid4())}}).status_code == 404
    finally:
        api.app.dependency_overrides.pop(api._capture_connection, None)


def test_two_recordings_for_one_visit_keep_separate_sessions_and_reopen_each(recording, session, monkeypatch):
    f, port, first_body = setup_capture(recording, session, monkeypatch)
    sessions, operation_sessions, wire_errors = {}, [], []

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith('/capture-admissions'):
            if body.get('expected_session_id') is not None:
                receipt = next(v for v in sessions.values() if str(v[0]) == body['expected_session_id'])
                assert body['attestation'] is None and 'recording_key_sha256' not in body
                assert body['expected_session_id'] == str(receipt[0])
            else:
                key = body['recording_key_sha256']
                assert body['recover_legacy_request'] is True
                assert request.headers['Idempotency-Key'] == 'saved:' + key
                receipt = sessions.setdefault(key, (uuid4(), uuid4()))
            value = {'contract_version': '1', 'binding_ref': body['binding_ref'],
                'workspace_id': body['workspace_id'], 'appointment_ref': ref('appointment'),
                'operation_ref': ref('scribe_admission'), 'session_id': str(receipt[0]),
                'consent_record_id': str(receipt[1]), 'status': 'admitted',
                'request_nonce': body['request_nonce'], 'checked_at': datetime.now(UTC).isoformat()}
            value['configured_capture'] = first_body['configured_capture']
        else:
            assert request.url.path.endswith('/capture-operations')
            assert body['operation'] == {'kind': 'capabilities', 'profile_receipt_id': None}
            operation_sessions.append(body['expected_session_id'])
            assert body['expected_session_id'] in {str(v[0]) for v in sessions.values()}
            value = {'contract_version': '1', 'binding_ref': body['binding_ref'],
                'workspace_id': body['workspace_id'], 'request_nonce': body['request_nonce'],
                'operation': 'capabilities', 'checked_at': datetime.now(UTC).isoformat(),
                'receipt': {'protocol_version': '1.0', 'media': {'media_type': 'audio/wav',
                    'encoding': 'pcm_s16le', 'channels': 1, 'sample_rate_hz': 16000},
                    'target_chunk_duration_ms': 10000, 'max_envelope_bytes': 327680,
                    'max_chunks': 1000, 'remaining_aggregate_plaintext_bytes': 67108864,
                    'capture_lease_ttl_seconds': 900, 'reservation_window_seconds': 900,
                    'max_reservations_per_batch': 90, 'upload_concurrency': 2}}
        return httpx.Response(200, json=value, headers={
            'Cache-Control': 'no-store', 'X-Cosmaneura-Capture-Version': '1'})

    def checked_handler(request):
        try:
            return handler(request)
        except Exception as error:
            wire_errors.append(repr(error))
            raise
    adapter = HttpCoreCaptureAdmission('https://core.example.invalid',
        lambda: 'synthetic_workload', transport=httpx.MockTransport(checked_handler))
    monkeypatch.setattr(port, 'admit_capture', adapter.admit_capture)
    monkeypatch.setattr(port, 'perform_capture_operation', adapter.perform_capture_operation, raising=False)
    try:
        first = submit(f, first_body)
        assert first.status_code == 200, first.text
        origin = recording[1]
        attached_second = post(f, base(origin), {**recording[2],
            'idempotency_key': str(uuid4()), 'local_recording_id': str(uuid4())})
        assert attached_second.status_code == 200, attached_second.text
        second_id = attached_second.json()['recording_id']
        path = base(origin) + '/' + second_id
        finished = post(f, path + '/finish', {**finish_body(), 'manifest_sha256': 'b' * 64})
        assert finished.status_code == 200, finished.text
        bound = post(f, path + '/visit-binding', {'idempotency_key': str(uuid4()),
            'target_workspace_id': f.workspace['id'], 'appointment_id': f.workspace['appointment_id'],
            'expected_target_revision': f.workspace['revision'], 'visit_confirmed': True})
        assert bound.status_code == 200, bound.text
        second_body = {**first_body, 'idempotency_key': str(uuid4()), 'saved_recording': {
            **first_body['saved_recording'], 'recording_id': second_id,
            'visit_binding_receipt_id': bound.json()['receipt_id'],
            'source_sha256': bound.json()['source_sha256'], 'manifest_sha256': 'b' * 64}}
        second = submit(f, second_body)
        assert second.status_code == 200, second.text
        assert first.json()['session_id'] != second.json()['session_id']
        assert submit(f, first_body).json() == first.json()
        for admitted in (first, second, first):
            selected = admitted.json()['session_id']
            response = f.client.post(f"/workspaces/{f.workspace['id']}/capture/operations",
                headers={'Authorization': 'Bearer ' + f.token()}, json={
                    'idempotency_key': str(uuid4()), 'session_id': selected,
                    'operation': {'kind': 'capabilities'}})
            assert response.status_code == 200, (response.text, wire_errors)
        assert operation_sessions == [first.json()['session_id'], second.json()['session_id'], first.json()['session_id']]
        transfers = session.scalars(select(PrivateRecordingTransfer).where(
            PrivateRecordingTransfer.workspace_id == f.workspace['id'])).all()
        assert {t.recording_id for t in transfers} == {first_body['saved_recording']['recording_id'], second_id}
        assert {str(session.get(PrivateRecordingTransferSession, t.id).session_id) for t in transfers} == {
            first.json()['session_id'], second.json()['session_id']}
    finally:
        adapter.close()
        api.app.dependency_overrides.pop(api._capture_connection, None)


@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding", "admit"])
def test_existing_visit_rechecks_binding_after_remote_io(recording, session, monkeypatch, phase):
    f, port, body = setup_capture(recording, session, monkeypatch)
    def change(_):
        if _ == phase:
            with Session(session.get_bind()) as independent:
                from cosmas_os.models import AppointmentObservation
                appointment = independent.get(AppointmentObservation, f.appointment.id)
                assert appointment is not None
                appointment.external_id = "changed-invented-visit"
                independent.commit()
    port.after = change
    try:
        assert submit(f, body).status_code == 409
        assert len(port.calls) == ["exchange", "resolve", "binding", "admit"].index(phase) + 1
    finally:
        api.app.dependency_overrides.pop(api._capture_connection, None)
