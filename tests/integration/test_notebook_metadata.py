"""Signed title recovery and accurate catalog projections against PostgreSQL."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from tests.integration import test_private_workspace_drafts as private

from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    CoreCaptureAccount,
    EncounterWorkspace,
    PatientLink,
    WorkspaceTitleRevision,
)

create, headers, appointment = private.create, private.headers, private.appointment
signed_workspace = private.signed_workspace


def test_local_source_time_without_utc_date_remains_unknown(signed_workspace, session):
    f = signed_workspace
    _, draft = create(f)
    account = CoreCaptureAccount(
        external_identity_id=f.binding.id, core_actor_ref="authority_actor_" + "0" * 25 + "1",
        core_tenant_ref="authority_tenant_" + "0" * 25 + "2", reviewed_by="Invented reviewer",
        evidence_ref="test:local-time-correspondence", reviewed_at=datetime.now(UTC),
    )
    session.add(account)
    session.flush()
    link = PatientLink(
        box_id=f.box, source_pair_key="invented-local:" + str(uuid4()), label="Invented local-time visit",
        source_owner_id=f.actor, source_account_id=account.id, state="confirmed",
        confirmed_by_principal_id=f.actor, attested_at=datetime.now(UTC),
    )
    session.add(link)
    session.flush()
    selected = AppointmentObservation(
        box_id=f.box, external_id="invented-local:" + str(uuid4()), source="cosmaneura_core",
        source_local_start=datetime(2026, 10, 16, 9, 30), source_owner_id=f.actor,
        source_sha256="a" * 64, patient_label="Invented local-time visit", patient_link_id=link.id,
    )
    session.add(selected)
    session.commit()
    catalog_row = next(row for row in ws.catalog(session, f.box, f.actor) if row["appointment_id"] == selected.id)
    assert catalog_row["start_at"] is None
    ws.link_appointment(session, f.box, f.actor, draft["id"], expected=1, key="local-time-link-001",
                        appointment=selected.id, confirmed=True)
    response = f.client.get("/workspaces/private-drafts/summary", headers=headers(f))
    assert response.status_code == 200, response.text
    row = response.json()["drafts"][0]
    assert row["link_state"] == "linked" and row["patient_label"] == selected.patient_label
    assert row["visit_at"] is None


def test_title_replay_does_not_change_original_intent_or_clinical_revision(signed_workspace, session):
    f = signed_workspace
    original, draft = create(f)
    path = f"/workspaces/{draft['id']}/title"
    body = {"title": "Yesterday's invented visit", "expected_title_revision": 0, "idempotency_key": "rename-notebook-001"}
    assert f.client.post(path + '/resolve', headers=headers(f), json=body).json()['outcome'] == 'not_found'
    response = f.client.post(path, headers=headers(f), json=body)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert f.client.post(path, headers=headers(f), json=body).json() == receipt
    assert f.client.post(path + '/resolve', headers=headers(f), json=body).json()['receipt'] == receipt
    reopened = f.client.get(f"/workspaces/{draft['id']}", headers=headers(f)).json()
    assert reopened['notebook']['title'] == body['title']
    assert reopened['revision'] == draft['revision'] and reopened['private_draft']['title'] == original['title']
    assert f.client.post('/workspaces/private-drafts/resolve', headers=headers(f), json=original).json()['workspace']['id'] == draft['id']
    assert f.client.post('/workspaces/private-drafts', headers=headers(f), json=original).status_code == 200
    assert f.client.post(path, headers=headers(f), json={**body, 'title': 'Different'}).status_code == 409
    assert f.client.post(path, headers=headers(f), json={**body, 'idempotency_key': 'stale-rename-002'}).status_code == 409
    assert session.scalar(select(func.count()).select_from(WorkspaceTitleRevision).where(WorkspaceTitleRevision.workspace_id == draft['id'])) == 1
    session.expire_all()
    assert session.get(EncounterWorkspace, draft['id']).draft_title == original['title']
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(text('UPDATE workspace_title_revisions SET title=:title WHERE id=:id'), {'title': 'Rewritten', 'id': receipt['receipt_id']})


def test_metadata_contains_actual_patient_dates_and_withholds_revoked_links(signed_workspace, session):
    f = signed_workspace
    _, draft = create(f)
    ws.append(session, f.box, f.actor, draft['id'], expected=1, key='metadata-notes-001', kind='scratchpad', content='Invented notes')
    private = f.client.get('/workspaces/private-drafts/summary', headers=headers(f)).json()
    row = private['drafts'][0]
    assert private['contract_version'] == 2 and row['title_revision'] == 0
    assert row['patient_label'] is None and row['visit_at'] is None and row['duration_seconds'] is None
    assert row['recording_state'] == 'none' and row['note_state'] == 'draft'
    selected = appointment(session, f)
    ws.link_appointment(session, f.box, f.actor, draft['id'], expected=2, key='metadata-link-001', appointment=selected.id, confirmed=True)
    row = f.client.get('/workspaces/private-drafts/summary', headers=headers(f)).json()['drafts'][0]
    assert row['patient_label'] == selected.patient_label and row['visit_at'] == selected.start_at.isoformat()
    session.get(PatientLink, selected.patient_link_id).revoked_at = selected.start_at
    session.commit()
    assert f.client.get('/workspaces/private-drafts/summary', headers=headers(f)).json()['drafts'] == []
    assert f.client.post(f"/workspaces/{draft['id']}/title", headers=headers(f), json={
        'title': 'Denied', 'expected_title_revision': 0, 'idempotency_key': 'revoked-title-001'}).status_code == 404


@pytest.mark.parametrize('bad', [{'title': ' '}, {'expected_title_revision': True}, {'expected_title_revision': -1}, {'owner_id': 'other'}, {'title': 'x'*161}])
def test_invalid_title_contract_never_appends(signed_workspace, session, bad):
    f = signed_workspace
    _, draft = create(f)
    response = f.client.post(f"/workspaces/{draft['id']}/title", headers=headers(f), json={
        'title': 'Invented title', 'expected_title_revision': 0, 'idempotency_key': 'invalid-title-001', **bad})
    assert response.status_code == 422
    assert session.scalar(select(func.count()).select_from(WorkspaceTitleRevision).where(WorkspaceTitleRevision.workspace_id == draft['id'])) == 0
