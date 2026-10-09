"""Signed saved-source admission pins the source, consent and session."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_private_recordings import attached, base, finish_body, post
from tests.integration.test_private_recordings import recording as _recording
from tests.integration.test_private_recordings import signed_workspace as _signed_workspace
from tests.integration.test_private_workspace_drafts import appointment
from tests.integration.test_workspace_capture import LocalCore, ref

from cosmas_os.api import app as api
from cosmas_os.application import workspace as ws
from cosmas_os.models import CoreCaptureAccount
from cosmas_os.private_recording_models import (
    PrivateRecordingTransfer,
    PrivateRecordingTransferSession,
)

recording = _recording
signed_workspace = _signed_workspace


class SavedCore(LocalCore):
    def __init__(self):
        super().__init__()
        self.keys = []

    def admit_capture(self, binding, credential, attestation, key, **kwargs):
        self.keys.append(key)
        receipt = super().admit_capture(binding, credential, attestation, key, **kwargs)
        self.saved = receipt.model_copy(update={"configured_capture": kwargs.get("configured_capture") or receipt.configured_capture})
        return self.saved


@pytest.fixture
def saved_case(recording, session, monkeypatch):
    f, draft, _, row = attached(recording)
    path = base(draft) + "/" + row["recording_id"]
    assert post(f, path + "/finish", finish_body()).status_code == 200
    a = appointment(session, f)
    a.source, a.external_id = "cosmaneura_core", ref("appointment")
    account = CoreCaptureAccount(external_identity_id=f.binding.id, core_actor_ref=ref("authority_actor"),
        core_tenant_ref=ref("authority_tenant"), reviewed_by="Invented reviewer", evidence_ref="synthetic:review", reviewed_at=datetime.now(UTC))
    session.add(account)
    session.commit()
    linked = ws.link_appointment(session, f.box, f.actor, draft["id"], expected=1, key="saved-recording-visit", appointment=a.id, confirmed=True)
    receipt = post(f, path + "/link", {"idempotency_key":str(uuid4()),"expected_workspace_revision":2,"workspace_link_receipt_id":linked["link_receipt_id"]}).json()
    for config in (f.configuration, api.settings):
        monkeypatch.setattr(config,"workspace_capture_backend","core")
        monkeypatch.setattr(config,"core_capture_origin","https://core.example.invalid")
        monkeypatch.setattr(config,"core_capture_scope","api://synthetic-core/.default")
        monkeypatch.setattr(config,"core_capture_managed_identity_client_id",str(uuid4()))
        monkeypatch.setattr(config,"workspace_capture_notes_enabled",True)
    port = SavedCore()
    api.app.dependency_overrides[api._capture_connection] = lambda: port
    body = {"idempotency_key":str(uuid4()),"attestation":{"modality":"in_person","participant_regions":[],"method":"verbal_attestation","all_parties_consented":True,"granted_at":datetime.now(UTC).isoformat()},
        "configured_capture":{"schema_version":"1.0","language_mode":"en-US"},"bot":{"address":"scribe","team_revision":1},
        "saved_recording":{"recording_id":row["recording_id"],"link_receipt_id":receipt["link"]["receipt_id"],"source_sha256":receipt["link"]["source_sha256"],
        "manifest_sha256":receipt["finish"]["manifest_sha256"],"chunks":receipt["finish"]["chunks"],"frames":receipt["finish"]["frames"]}}
    try:
        yield f, draft, body, port
    finally:
        api.app.dependency_overrides.pop(api._capture_connection,None)


def submit(case, body=None):
    f,draft,original,_ = case
    return f.client.post(f"/workspaces/{draft['id']}/capture/admission",headers={"Authorization":"Bearer "+f.token()},json=body or original)


def test_saved_source_retries_same_session_and_retains_exact_consent(saved_case, session):
    first = submit(saved_case)
    assert first.status_code == 200, first.text
    retry = submit(saved_case,{**saved_case[2],"idempotency_key":str(uuid4())})
    assert retry.status_code == 200 and retry.json()==first.json()
    assert saved_case[3].keys[0] == saved_case[3].keys[1]
    assert session.scalar(select(func.count()).select_from(PrivateRecordingTransfer))==1
    assert session.scalar(select(func.count()).select_from(PrivateRecordingTransferSession))==1
    row=session.scalar(select(PrivateRecordingTransfer))
    assert row.request["attestation"]["granted_at"]==saved_case[2]["attestation"]["granted_at"].replace('+00:00','Z')


@pytest.mark.parametrize("field",["recording_id","link_receipt_id","source_sha256","manifest_sha256","chunks","frames"])
def test_changed_source_is_rejected_before_core(saved_case,field):
    body = saved_case[2]
    wrong = str(uuid4()) if field.endswith('_id') else ('b' if body['saved_recording'][field]=='a'*64 else 'a')*64 if field.endswith('sha256') else body['saved_recording'][field]+1
    response = submit(saved_case,{**body,"saved_recording":{**body["saved_recording"],field:wrong}})
    assert response.status_code in (404,409), response.text
    assert saved_case[3].calls==[]


def test_saved_transfer_refuses_live_recorder_and_truncated_completion(saved_case):
    admitted=submit(saved_case)
    assert admitted.status_code==200,admitted.text
    f,draft,body,port=saved_case
    path=f"/workspaces/{draft['id']}/capture/operations"
    # A completed import cannot select the native microphone path or claim fewer chunks.
    operation={"kind":"complete","payload":{"protocol_version":"1.0","capture_lease_id":str(uuid4()),"capture_lease_generation":1,
        "channels":[{"channel":"microphone","final_sequence_number":body['saved_recording']['chunks']}]}}
    response=f.client.post(path,headers={"Authorization":"Bearer "+f.token()},json={"idempotency_key":str(uuid4()),"session_id":admitted.json()['session_id'],"operation":operation})
    assert response.status_code==409,response.text
    calls=len(port.calls)
    other=f.client.post(path,headers={"Authorization":"Bearer "+f.token()},json={"idempotency_key":str(uuid4()),"session_id":str(uuid4()),"operation":{"kind":"capabilities"}})
    assert other.status_code==409 and len(port.calls)==calls


def test_second_consent_cannot_replace_original_transfer(saved_case):
    assert submit(saved_case).status_code==200
    body=saved_case[2]
    result=submit(saved_case,{**body,"attestation":{**body['attestation'],"granted_at":datetime.now(UTC).isoformat()}})
    assert result.status_code==409


@pytest.mark.parametrize('kind', ['native_recording_context','source_start'])
def test_import_cannot_request_microphone_authority(saved_case, kind):
    admitted=submit(saved_case)
    assert admitted.status_code==200
    f,draft,_,port=saved_case
    operation={'kind':kind}
    if kind=='source_start':
        operation.update(action='prepare',payload={'attempt_id':str(uuid4()),'source':'ios_microphone',
            'owner_proof':'a'*64,'lease_id':str(uuid4()),'lease_receipt_id':str(uuid4()),
            'lease_generation':1,'capture_authorized_until':datetime.now(UTC).isoformat()})
    calls=len(port.calls)
    response=f.client.post(f"/workspaces/{draft['id']}/capture/operations",headers={'Authorization':'Bearer '+f.token()},
        json={'idempotency_key':str(uuid4()),'session_id':admitted.json()['session_id'],'operation':operation})
    assert response.status_code==409 and len(port.calls)==calls


@pytest.mark.parametrize('phase',['exchange','resolve','binding','admit'])
def test_saved_import_rechecks_account_after_each_remote_phase(saved_case,session,phase):
    def revoke(observed):
        if observed==phase:
            with Session(session.get_bind()) as independent:
                account=independent.scalar(select(CoreCaptureAccount))
                account.revoked_at=datetime.now(UTC)
                independent.commit()
    saved_case[3].after=revoke
    response=submit(saved_case)
    assert response.status_code==409 and 'session_id' not in response.text
    assert len(saved_case[3].calls)==['exchange','resolve','binding','admit'].index(phase)+1
    assert session.scalar(select(func.count()).select_from(PrivateRecordingTransferSession))==0


@pytest.mark.parametrize('table',['private_recording_transfers','private_recording_transfer_sessions'])
@pytest.mark.parametrize('verb',['UPDATE','DELETE'])
def test_transfer_history_is_immutable_in_postgres(saved_case,session,table,verb):
    assert submit(saved_case).status_code==200
    with Session(session.get_bind()) as independent:
        with pytest.raises(DBAPIError):
            independent.execute(text(f'{verb} {table}'+(' SET created_at=now()' if verb=='UPDATE' else '')))
            independent.commit()
        independent.rollback()
    assert session.scalar(select(func.count()).select_from(PrivateRecordingTransfer))==1
    assert session.scalar(select(func.count()).select_from(PrivateRecordingTransferSession))==1


def test_lost_admission_reply_retains_intent_and_recovers_same_remote_session(saved_case,session,monkeypatch):
    from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
    port=saved_case[3]
    original=port.admit_capture
    def lose_reply(*args,**kwargs):
        original(*args,**kwargs)
        raise ConnectorUnavailable('synthetic_reply_lost')
    monkeypatch.setattr(port,'admit_capture',lose_reply)
    assert submit(saved_case).status_code==503
    assert session.scalar(select(func.count()).select_from(PrivateRecordingTransfer))==1
    assert session.scalar(select(func.count()).select_from(PrivateRecordingTransferSession))==0
    sha=session.scalar(select(PrivateRecordingTransfer)).request_sha256
    original_id=port.saved.session_id
    monkeypatch.setattr(port,'admit_capture',original)
    recovered=submit(saved_case)
    assert recovered.status_code==200 and recovered.json()['session_id']==str(original_id)
    assert session.scalar(select(PrivateRecordingTransfer)).request_sha256==sha


def test_saved_session_cannot_silently_replace_its_consent(saved_case,monkeypatch):
    assert submit(saved_case).status_code==200
    port=saved_case[3]
    original=port.admit_capture
    monkeypatch.setattr(port,'admit_capture',lambda *a,**k: original(*a,**k).model_copy(update={'consent_record_id':uuid4()}))
    assert submit(saved_case).status_code==409
