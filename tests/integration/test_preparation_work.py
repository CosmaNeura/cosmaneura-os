"""Actual Postgres/API authorization and F-8 transitions; Core transport is an explicit fixture."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_workspace_capture import capture_case as _capture_case
from tests.integration.test_workspace_prep import setup
from tests.unit.test_encounter_prep import receipt

from cosmas_os.api import app as api
from cosmas_os.application import follow_up, prep_work, provider_team, shared_work
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.domain.enums import DecisionKind
from cosmas_os.domain.rules import AuthorizationError, DomainError
from cosmas_os.models import (
    ActionRevision,
    Decision,
    ExternalIdentity,
    FollowUpReceipt,
    FollowUpSource,
    Operation,
    Principal,
    Ticket,
)
from cosmas_os.ports.encounter_prep import CorePrepReceipt

capture_case = _capture_case


def rehash(value):
    import hashlib
    import json
    value = deepcopy(value)
    value.pop("snapshot_sha256", None)
    value["snapshot_sha256"] = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()
    return value


@pytest.fixture
def case(capture_case, monkeypatch):
    f = capture_case
    f.configuration.workspace_prep_work_enabled = True
    monkeypatch.setattr(prep_work, "settings", f.configuration)
    monkeypatch.setattr(provider_team, "runtime_settings", f.configuration)
    f.bot, _ = setup(f)
    f.prep = receipt(f.appointment.external_id)
    def context(binding, credential):
        f.port.step("prep")
        return CorePrepReceipt.model_validate(f.prep)
    f.port.encounter_context = context
    f.prep_path = f"/workspaces/{f.workspace['id']}/prep-work"
    f.headers = {"Authorization": "Bearer " + f.token()}
    return f


def create(f, **changes):
    command = {"bot": f.bot, "expected_entry_revision": 1, "snapshot_sha256": f.prep["snapshot_sha256"],
        "body": "Ask the responsible team member to check saved preparation information.",
        "due_date": "2026-09-29", "expected_outcome": "Provider can review the current saved intake summary.",
        "share_context": True, "idempotency_key": "preparation-proposal", **changes}
    result = f.client.post(f.prep_path, headers=f.headers, json=command)
    return result, command


def approve(f, item, **changes):
    command = {"expected_version": item["version"], "revision_id": item["revision_id"],
        "payload_hash": item["payload_hash"], "choice": "approve", "bot": f.bot,
        "expected_snapshot_sha256": item["proposed_snapshot_sha256"], **changes}
    return f.client.post(f.prep_path + '/' + item["ticket_id"] + '/decide', headers=f.headers, json=command), command


def published(f):
    response, proposal = create(f)
    assert response.status_code == 200, response.text
    result, approval = approve(f, response.json()["item"])
    assert result.status_code == 200, result.text
    return result.json()["item"], proposal, approval


def assign(f, item):
    person = Principal(box_id=f.box, principal_type="human", state="active", display_name="Invented preparation staff")
    f.session.add(person)
    f.session.flush()
    binding = ExternalIdentity(box_id=f.box, principal_id=person.id, provider="clerk", issuer=f.configuration.clerk_issuer,
        subject="prep_staff_" + uuid4().hex, organization_id="org_invented", reviewed_by="Invented reviewer", evidence_ref="test:prep-staff")
    f.session.add(binding)
    f.session.commit()
    staff_headers = {"Authorization": "Bearer " + f.token(sub=binding.subject)}
    path = '/practice-work/' + item["ticket_id"]
    offer_command = {"expected_version": item["version"], "revision_id": item["revision_id"], "payload_hash": item["payload_hash"],
        "idempotency_key": "preparation-offer", "kind": "offer", "recipient_id": person.id}
    offered = f.client.post(path + '/handoffs', headers=f.headers, json=offer_command)
    assert offered.status_code == 200, offered.text
    accept_command = {**offer_command, "expected_version": offered.json()["version"], "recipient_id": None,
        "offer_id": offered.json()["pending_offer"]["id"], "kind": "accept", "idempotency_key": "preparation-accept"}
    accepted = f.client.post(path + '/handoffs', headers=staff_headers, json=accept_command)
    assert accepted.status_code == 200, accepted.text
    return accepted.json(), person.id, staff_headers, binding.id


def ready(f, item, headers=None, **changes):
    command = {"expected_version": item["version"], "revision_id": item["revision_id"], "payload_hash": item["payload_hash"],
        "idempotency_key": "preparation-ready", "evidence": "Saved information is available for the provider to check.", **changes}
    return f.client.post('/practice-work/' + item["ticket_id"] + '/complete', headers=headers or f.headers, json=command), command


def verify(f, item, **changes):
    command = {"bot": f.bot, "expected_version": item["version"], "revision_id": item["revision_id"],
        "payload_hash": item["payload_hash"], "current_snapshot_sha256": f.prep["snapshot_sha256"],
        "reviewed_summary": True, "idempotency_key": "preparation-verify", **changes}
    return f.client.post(f.prep_path + '/' + item["ticket_id"] + '/verify', headers=f.headers, json=command), command


def test_signed_source_to_staff_ready_to_provider_saved_summary_verification(case):
    f = case
    item, proposal, approval = published(f)
    assert item["work_kind"] == "visit_preparation" and item["state"] == "approved" and not item["ready_for_review"]
    assert [r["kind"] for r in item["receipts"]] == ["internal_publication"]
    assert f.port.calls == ["exchange", "resolve", "binding", "prep"] * 2 and f.port.saved is None
    assert f.client.get('/workspaces/' + f.workspace['id'], headers=f.headers).json()["follow_ups"] == []
    accepted, staff, staff_headers, _ = assign(f, item)
    result, completion = ready(f, accepted, staff_headers)
    assert result.status_code == 200, result.text
    pending = result.json()
    assert pending["state"] == "approved" and pending["ready_for_review"] and pending["pending_offer"] is None
    assert [row["kind"] for row in pending["receipts"]] == ["internal_publication", "ready_for_review"]
    assert f.session.get(Ticket, item["ticket_id"]).closed_at is None
    assert f.client.get('/workspaces/' + f.workspace['id'], headers=staff_headers).status_code == 404
    assert not {"workspace_id", "source_ref", "prep_receipt", "proposed_snapshot_sha256"} & pending.keys()
    result, verification = verify(f, pending)
    assert result.status_code == 200, result.text
    closed = result.json()["item"]
    assert closed["state"] == "closed" and not closed["ready_for_review"]
    assert closed["receipts"][-1]["kind"] == "provider_verification"
    operation = f.session.scalar(select(Operation).where(Operation.ticket_id == item["ticket_id"]))
    assert operation.adapter == prep_work.ADAPTER and operation.status == "succeeded" and operation.external_reference is None
    assert f.session.scalar(select(func.count()).select_from(Operation).where(Operation.ticket_id == item["ticket_id"])) == 1
    assert f.session.scalar(select(func.count()).select_from(Decision).where(Decision.ticket_id == item["ticket_id"])) == 1
    assert f.session.scalar(select(func.count()).select_from(FollowUpReceipt).where(FollowUpReceipt.ticket_id == item["ticket_id"])) == 3
    proof = f.session.scalar(select(FollowUpReceipt).where(FollowUpReceipt.ticket_id == item["ticket_id"], FollowUpReceipt.kind == "provider_verification"))
    assert proof.source_snapshot_sha256 == verification["current_snapshot_sha256"]
    assert proof.source_proof["sources"][0]["source_ref"] == f.prep["sources"][0]["source_ref"]
    raw = f.prep["sources"][0]["source_ref"]
    for value in [result.text, str(svc.list_queue(svc.Container(f.session), f.box)),
        str(svc.audit_timeline(svc.Container(f.session), f.box, item["ticket_id"]))]:
        assert raw not in value and raw.removeprefix('intake_') not in value
    assert f.client.get(f.prep_path, headers=f.headers).json()["items"][0] == closed


def test_exact_committed_commands_recover_without_new_core_reads_even_after_source_changes(case):
    f = case
    item, proposal, approval = published(f)
    result, completion = ready(f, item)
    result, verification = verify(f, result.json())
    assert result.status_code == 200, result.text
    before = len(f.port.calls)
    f.port.after = lambda _: pytest.fail('Committed replay must not read Core')
    f.prep = rehash({**f.prep, "sources": []})
    f.configuration.workspace_capture_backend = "disabled"
    for path, command in [(f.prep_path, proposal), (f.prep_path+'/'+item['ticket_id']+'/decide', approval),
        ('/practice-work/'+item['ticket_id']+'/complete', completion),
        (f.prep_path+'/'+item['ticket_id']+'/verify', verification)]:
        response = f.client.post(path, headers=f.headers, json=command)
        assert response.status_code == 200, response.text
    assert len(f.port.calls) == before
    assert f.client.post(f.prep_path, headers=f.headers, json={**proposal, "body": "Changed command"}).status_code == 409


def test_source_changed_after_display_blocks_approval_and_provider_verification(case):
    f = case
    response, _ = create(f)
    item = response.json()["item"]
    original = deepcopy(f.prep)
    f.prep['sources'][0]['content'] = 'A changed saved summary.'
    f.prep = rehash(f.prep)
    response, _ = approve(f, item)
    assert response.status_code == 409 and response.json()['detail'] == 'prep_work_source_changed'
    f.prep = original
    response, _ = approve(f, item)
    item = response.json()['item']
    response, _ = ready(f, item)
    item = response.json()
    old_hash = f.prep['snapshot_sha256']
    f.prep['sources'][0]['content'] = 'Current saved summary.'
    f.prep = rehash(f.prep)
    response, _ = verify(f, item, current_snapshot_sha256=old_hash)
    assert response.status_code == 409
    response, _ = verify(f, item)
    assert response.status_code == 200 and response.json()['item']['state'] == 'closed'


@pytest.mark.parametrize('missing', ['absent', 'truncated', 'empty'])
def test_empty_proposal_context_is_allowed_but_final_summary_must_exist_and_be_complete(case, missing):
    f = case
    f.prep = rehash({**f.prep, 'sources': []})
    item, _, _ = published(f)
    response, _ = ready(f, item)
    item = response.json()
    f.prep = receipt(f.appointment.external_id)
    if missing == 'absent':
        f.prep['sources'] = []
    elif missing == 'truncated':
        f.prep['sources'][0]['truncated'] = True
    else:
        f.prep['sources'][0]['content'] = ' '
    f.prep = rehash(f.prep)
    result, _ = verify(f, item)
    assert result.status_code == 409 and result.json()['detail'] == 'prep_work_saved_summary_required'
    assert f.session.get(Ticket, item['ticket_id']).state == 'approved'


@pytest.mark.parametrize('phase', ['exchange', 'resolve', 'binding', 'prep'])
def test_revocation_during_new_proposal_core_read_produces_no_ticket(case, phase):
    f = case
    def revoke(observed):
        if observed == phase:
            with Session(f.engine) as separate:
                separate.get(ExternalIdentity, f.identity_id).active = False
                separate.commit()
    f.port.after = revoke
    response, _ = create(f)
    assert response.status_code in {403,404,409}
    assert f.session.scalar(select(func.count()).select_from(FollowUpSource).where(FollowUpSource.workspace_id == f.workspace['id'])) == 0


@pytest.mark.parametrize('field', ['body', 'expected_outcome', 'evidence'])
@pytest.mark.parametrize('representation', ['reference', 'token', 'encoded'])
def test_credential_bearing_intake_references_never_enter_shared_text(case, field, representation):
    f = case
    raw = f.prep['sources'][0]['source_ref']
    token = raw.removeprefix('intake_')
    secret = raw if representation == 'reference' else token if representation == 'token' else ''.join('%'+format(ord(c),'02x') for c in token)
    if field == 'evidence':
        item, _, _ = published(f)
        response, _ = ready(f, item, evidence='Check '+secret)
    else:
        response, _ = create(f, **{field:'Check '+secret})
    assert response.status_code == 422 and response.json()['detail'] == 'prep_work_private_link'
    assert raw not in response.text and token not in response.text


def test_staff_readiness_requires_exact_responsibility_version_and_provider_alone_verifies(case):
    f = case
    item, _, _ = published(f)
    accepted, staff, staff_headers, _ = assign(f, item)
    assert ready(f, accepted)[0].status_code == 409
    assert ready(f, accepted, staff_headers, expected_version=1)[0].status_code == 409
    pending, command = ready(f, accepted, staff_headers)
    assert pending.status_code == 200
    result, verification = verify(f, pending.json(), reviewed_summary=False)
    assert result.status_code == 400
    verification['reviewed_summary'] = True
    assert f.client.post(f.prep_path+'/'+item['ticket_id']+'/verify', headers=staff_headers, json=verification).status_code == 404
    assert f.session.get(Ticket, item['ticket_id']).state == 'approved'


def test_unpublished_rejection_remains_available_with_core_offline(case):
    f = case
    response, _ = create(f)
    item = response.json()['item']
    f.configuration.workspace_capture_backend = 'disabled'
    command = {'expected_version':item['version'],'revision_id':item['revision_id'],'payload_hash':item['payload_hash'],'choice':'reject'}
    path=f.prep_path+'/'+item['ticket_id']+'/decide'
    response=f.client.post(path,headers=f.headers,json=command)
    assert response.status_code==200 and response.json()['item']['state']=='rejected'
    assert f.client.post(path,headers=f.headers,json=command).status_code==200
    assert f.session.scalar(select(Operation).where(Operation.ticket_id==item['ticket_id'])) is None


def test_legacy_follow_up_paths_and_mutable_provenance_are_rejected(case):
    f = case
    item, _, _ = published(f)
    with pytest.raises(ws.WorkspaceError):
        follow_up.decide(f.session,f.box,f.actor,f.workspace['id'],item['ticket_id'],revision_id=item['revision_id'],digest=item['payload_hash'],choice='approve')
    f.session.rollback()
    with pytest.raises(AuthorizationError):
        svc.decide(svc.Container(f.session),item['ticket_id'],f.actor,DecisionKind.APPROVE)
    f.session.rollback()
    operation=f.session.scalar(select(Operation).where(Operation.ticket_id==item['ticket_id']))
    with pytest.raises(DomainError):
        svc.execute_operation(svc.Container(f.session),operation.id)
    for table in ['follow_up_sources','action_revisions','follow_up_receipts']:
        key='id' if table=='action_revisions' else 'ticket_id'
        value=item['revision_id'] if key=='id' else item['ticket_id']
        with pytest.raises(DBAPIError):
            f.session.execute(text(f'DELETE FROM {table} WHERE {key}=:id'),{'id':value})
            f.session.commit()
        f.session.rollback()


@pytest.mark.parametrize('path_kind', ['create', 'approve', 'reject', 'verify', 'replay'])
def test_signed_authority_is_rechecked_after_body_read(case, monkeypatch, path_kind):
    from fastapi import HTTPException
    f = case
    if path_kind in {'create', 'replay'}:
        response, command = create(f)
        assert response.status_code == 200
        path = f.prep_path
        if path_kind == 'create':
            command = {**command, 'idempotency_key': 'another-proposal', 'expected_entry_revision': response.json()['entry_revision']}
    elif path_kind == 'verify':
        item, _, _ = published(f)
        response, _ = ready(f, item)
        pending = response.json()
        path = f.prep_path+'/'+item['ticket_id']+'/verify'
        command = {'bot': f.bot, 'expected_version': pending['version'], 'revision_id': item['revision_id'],
            'payload_hash': item['payload_hash'], 'current_snapshot_sha256': f.prep['snapshot_sha256'],
            'reviewed_summary': True, 'idempotency_key': 'slow-verify'}
    else:
        response, _ = create(f)
        item = response.json()['item']
        path = f.prep_path+'/'+item['ticket_id']+'/decide'
        command = {'expected_version': item['version'], 'revision_id': item['revision_id'],
            'payload_hash': item['payload_hash'], 'choice': path_kind}
        if path_kind == 'approve':
            command.update(bot=f.bot, expected_snapshot_sha256=f.prep['snapshot_sha256'])
    original = api.read_capture_request
    calls = len(f.port.calls)
    async def slow_body(request, schema, **kwargs):
        value = await original(request, schema, **kwargs)
        def expired(**kwargs): raise HTTPException(401, 'authentication_required')
        monkeypatch.setattr(api, '_identity', expired)
        return value
    monkeypatch.setattr(api, 'read_capture_request', slow_body)
    result = f.client.post(path, headers=f.headers, json=command)
    assert result.status_code == 401
    assert len(f.port.calls) == calls


def test_ready_work_retains_history_and_allows_originator_reclaim_after_staff_revocation(case):
    f = case
    item, _, _ = published(f)
    accepted, staff, staff_headers, binding = assign(f, item)
    response, command = ready(f, accepted, staff_headers)
    pending = response.json()
    person = Principal(box_id=f.box, principal_type='human', state='active', display_name='Other invented staff')
    f.session.add(person)
    f.session.commit()
    attempt = {'expected_version': pending['version'], 'revision_id': pending['revision_id'],
        'payload_hash': pending['payload_hash'], 'kind': 'offer', 'recipient_id': person.id, 'idempotency_key': 'late-offer'}
    path = '/practice-work/'+pending['ticket_id']
    assert f.client.post(path+'/handoffs', headers=staff_headers, json=attempt).status_code == 409
    f.session.get(ExternalIdentity, binding).active = False
    f.session.get(Principal, staff).state = 'disabled'
    f.session.commit()
    reclaim = {**attempt, 'kind': 'reclaim', 'recipient_id': None, 'idempotency_key': 'provider-reclaim'}
    result = f.client.post(path+'/handoffs', headers=f.headers, json=reclaim)
    assert result.status_code == 200, result.text
    reclaimed = result.json()
    assert reclaimed['responsible']['id'] == f.actor and reclaimed['ready_for_review']
    assert len(reclaimed['handoffs']) == 3 and not reclaimed['receipts'][-1]['actor']['available']
    assert f.client.post(path+'/handoffs', headers=f.headers, json=reclaim).json() == reclaimed
    assert verify(f, pending)[0].status_code == 409
    result, _ = verify(f, reclaimed)
    assert result.status_code == 200 and result.json()['item']['state'] == 'closed'


@pytest.mark.parametrize('phase', ['approve', 'ready', 'verify'])
def test_concurrent_exact_effects_create_only_one_receipt_and_version_transition(case, phase):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    f = case
    response, _ = create(f)
    item = response.json()['item']
    if phase != 'approve':
        response, _ = approve(f, item)
        item = response.json()['item']
    if phase == 'verify':
        response, _ = ready(f, item)
        item = response.json()
    version = item['version']
    barrier = Barrier(2)
    checked = CorePrepReceipt.model_validate(f.prep)
    approval = {'expected_version': version, 'revision_id': item['revision_id'], 'payload_hash': item['payload_hash'],
        'choice': 'approve', 'bot': f.bot, 'expected_snapshot_sha256': f.prep['snapshot_sha256']}
    verification = {'expected_version': version, 'revision_id': item['revision_id'], 'payload_hash': item['payload_hash'],
        'bot': f.bot, 'current_snapshot_sha256': f.prep['snapshot_sha256'], 'reviewed_summary': True,
        'idempotency_key': 'concurrent-verification'}
    f.session.commit()
    def perform(_):
        with Session(f.engine) as separate:
            barrier.wait(timeout=10)
            if phase == 'approve':
                return prep_work.decide(separate, f.box, f.actor, f.workspace['id'], item['ticket_id'], approval, checked)['item']
            if phase == 'verify':
                return prep_work.verify(separate, f.box, f.actor, f.workspace['id'], item['ticket_id'], verification, checked)['item']
            return shared_work.complete(separate, f.box, f.actor, item['ticket_id'], expected=version,
                revision_id=item['revision_id'], digest=item['payload_hash'], key='concurrent-ready', evidence='Ready for provider review.')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(perform, range(2)))
    assert results[0] == results[1] and results[0]['version'] == version+1
    kind = {'approve': 'internal_publication', 'ready': 'ready_for_review', 'verify': 'provider_verification'}[phase]
    assert f.session.scalar(select(func.count()).select_from(FollowUpReceipt).where(
        FollowUpReceipt.ticket_id == item['ticket_id'], FollowUpReceipt.kind == kind)) == 1


@pytest.mark.parametrize('change', [
    {'source_kind': 'reviewed_note'}, {'source_kind': 'unknown'}, {'prep_snapshot_sha256': None},
    {'prep_receipt': None}, {'prep_receipt': {'sources': []}},
    {'content_hash': 'a'*64}, {'prep_receipt': {'snapshot_sha256': 'a'*64, 'sources': []}},
])
def test_database_source_union_rejects_incomplete_or_mixed_provenance(case, change):
    from sqlalchemy.exc import IntegrityError
    f = case
    response, _ = create(f)
    item = response.json()['item']
    original = f.session.get(ActionRevision, item['revision_id'])
    ticket = Ticket(box_id=f.box, lane=prep_work.LANE, state='pending_approval', created_by_principal_id=f.actor,
        appointment_id=f.appointment.id, patient_link_id=f.appointment.patient_link_id)
    f.session.add(ticket)
    f.session.flush()
    fields = ['action_type','target_ref','content','payload','payload_hash','automation_class','policy_version',
        'charter_version','config_version','created_by_principal_id']
    revision = ActionRevision(ticket_id=ticket.id, box_id=f.box, revision_number=1,
        **{key: getattr(original, key) for key in fields})
    f.session.add(revision)
    f.session.flush()
    source = FollowUpSource(ticket_id=ticket.id, box_id=f.box, workspace_id=f.workspace['id'], owner_id=f.actor,
        action_revision_id=revision.id, payload_hash=revision.payload_hash, workspace_revision=100,
        idempotency_key='invalid-source', request_hash='a'*64,
        **{'source_kind':'core_prep','prep_snapshot_sha256':f.prep['snapshot_sha256'],'prep_receipt':f.prep, **change})
    f.session.add(source)
    with pytest.raises(IntegrityError) as error:
        f.session.flush()
    assert error.value.orig.diag.constraint_name == 'ck_follow_up_source_kind'
    f.session.rollback()


@pytest.mark.parametrize('change', [{}, {'source_snapshot_sha256':'a'*64},
    {'source_snapshot_sha256':'a'*64,'source_proof':{'snapshot_sha256':'a'*64,'sources':[]}},
    {'source_snapshot_sha256':'a'*64,'source_proof':{'snapshot_sha256':'b'*64,'sources':[{}]}}])
def test_database_provider_verification_requires_private_complete_proof(case, change):
    from sqlalchemy.exc import IntegrityError
    f = case
    item, _, _ = published(f)
    operation = f.session.scalar(select(Operation).where(Operation.ticket_id==item['ticket_id']))
    row = FollowUpReceipt(ticket_id=item['ticket_id'], box_id=f.box, operation_id=operation.id, actor_id=f.actor,
        kind='provider_verification', content='Invalid fixture proof', request_hash='a'*64,
        idempotency_key='invalid-proof', **change)
    f.session.add(row)
    with pytest.raises(IntegrityError) as error:
        f.session.flush()
    assert error.value.orig.diag.constraint_name == 'ck_follow_up_receipt_proof'
    f.session.rollback()


def test_routine_counts_only_provider_verified_preparation_completion_without_private_proof(case, monkeypatch):
    from cosmas_os.application import routines
    f = case
    f.configuration.workspace_routines_enabled = True
    monkeypatch.setattr(routines, "settings", f.configuration)
    item, _, _ = published(f)
    response, _ = ready(f, item)
    pending = response.json()
    before = routines._snapshot(f.session, f.box, f.actor, '2026-09-29')
    assert before['counts']['open'] == 1 and before['counts']['verified_complete'] == 0
    assert not before['items'][0]['human_completion']
    f.session.commit()
    result, _ = verify(f, pending)
    assert result.status_code == 200, result.text
    after = routines._snapshot(f.session, f.box, f.actor, '2026-09-29')
    assert after['counts']['open'] == 0 and after['counts']['verified_complete'] == 1
    assert after['items'][0]['human_completion']
    assert 'source_proof' not in str(after) and f.prep['sources'][0]['source_ref'] not in str(after)


@pytest.mark.parametrize('gate', ['workspace_prep_enabled', 'workspace_prep_work_enabled', 'workspace_capture_backend'])
def test_new_effect_rechecks_runtime_gate_after_core_read(case, gate):
    f = case
    def disable(phase):
        if phase == 'prep':
            setattr(f.configuration, gate, 'disabled' if gate == 'workspace_capture_backend' else False)
    f.port.after = disable
    response, _ = create(f)
    assert response.status_code == 404
    assert f.session.scalar(select(func.count()).select_from(FollowUpSource).where(
        FollowUpSource.workspace_id == f.workspace['id'])) == 0
