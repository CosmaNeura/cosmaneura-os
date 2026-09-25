"""Local signed-team transitions and effective restrictions; no remote service is called."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import json
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.api import app as api
from cosmas_os.application import conversation, handoffs, model_work, provider_team as team, routines, team_setup
from cosmas_os.application import workspace as ws
from cosmas_os.models import AuditEvent, Base, CoreCaptureAccount, ExternalIdentity, Operation, Principal, ProviderBot, ProviderTeamRevision, RoutineRevision, RoutineRun, Ticket, WorkspaceHandoffAttempt
from cosmas_os.ports.bot_capabilities import BotReply, DraftBrief
from tests.integration.test_workspace_capture import capture_case as _capture_case
from tests.integration.test_routines import configuration as routine_configuration

capture_case = _capture_case


@pytest.fixture
def case(capture_case, monkeypatch):
    f = capture_case
    f.configuration.workspace_team_setup_enabled = True
    f.configuration.workspace_prep_enabled = True
    for module, name in [(team, 'runtime_settings'), (conversation, 'runtime_settings'),
                         (handoffs, 'runtime_settings'), (routines, 'settings')]:
        monkeypatch.setattr(module, name, f.configuration)
    f.headers = {'Authorization': 'Bearer '+f.token(), 'X-Cosmas-Team-Contract': '1', 'X-Cosmas-Model-Contract': '1'}
    return f


def rehearse(f, configuration, expected=0, headers=None):
    return f.client.post('/provider-team/rehearsal', headers=headers or f.headers,
        json={'expected_revision': expected, 'configuration': configuration, 'scenario_id': 'preset_setup.v1'})


def save(f, configuration, expected=0, review=None, key=None, headers=None):
    command = {'expected_revision': expected, 'configuration': configuration, 'idempotency_key': key or str(uuid4())}
    if review is not None: command['setup_review'] = review
    return f.client.post('/provider-team', headers=headers or f.headers, json=command), command


def reviewed_save(f, configuration, expected=0):
    rehearsal = rehearse(f, configuration, expected)
    assert rehearsal.status_code == 200, rehearsal.text
    result, command = save(f, configuration, expected, rehearsal.json()['setup_review'])
    assert result.status_code == 200, result.text
    return result.json(), command


def add_preset(configuration, preset_id):
    value = deepcopy(configuration)
    bindings = value.setdefault('presets', [])
    if not bindings:
        bindings.append({'preset_id':'provider','version':1,'slots':{role:role for role in ('scribe','visit_prep','follow_up','chief')}})
    if any(p['preset_id'] == preset_id for p in bindings): return value
    selected = next(p for p in team_setup.catalog()['presets'] if p['preset_id'] == preset_id)
    slots = {}
    for slot in selected['slots']:
        address = slot['address'] or str(uuid4()); slots[slot['slot']] = address
        if slot['address'] is not None: continue
        bot = {key: item for key,item in slot.items() if key not in {'slot','address'}}
        bot['instance_id'] = address; value['bots'].append(bot)
    bindings.append({'preset_id':preset_id,'version':1,'slots':slots})
    return value


def counts(f):
    return {model.__tablename__: f.session.scalar(select(func.count()).select_from(model))
        for model in (Principal,ProviderBot,ProviderTeamRevision,AuditEvent,Ticket,Operation,RoutineRun)}


def table_fingerprints(f):
    return {table.name: hashlib.sha256('\n'.join(sorted(json.dumps(dict(row),sort_keys=True,default=str)
        for row in f.session.execute(select(table)).mappings())).encode()).hexdigest()
        for table in Base.metadata.sorted_tables}


def test_all_presets_rehearse_without_writes_then_save_nine_stable_private_bots(case,tmp_path):
    f=case
    configuration=add_preset(add_preset(team.default_configuration(),'front_desk'),'practice_manager')
    before=table_fingerprints(f); response=rehearse(f,configuration)
    assert response.status_code==200,response.text
    value=response.json()
    assert table_fingerprints(f)==before and len(value['cases'])==7 and f.port.calls==[]
    assert value['setup_review']['configuration_sha256']==team_setup.digest(value['configuration'])
    assert {x['state'] for x in value['setup']['capabilities'] if x['capability'] in {'inbox_operations','membership_billing'}}=={'unavailable_in_beta'}
    assert save(f,configuration)[0].status_code==409
    result,command=save(f,configuration,review=value['setup_review']);assert result.status_code==200,result.text
    installed=result.json();assert len(installed['members'])==9
    assert f.client.post('/provider-team',headers=f.headers,json=command).json()==installed
    assert len({m['agent_id'] for m in installed['members']})==9
    assert add_preset(installed['configuration'],'front_desk')==installed['configuration']
    setup=f.client.get('/provider-team/setup',headers=f.headers)
    assert setup.status_code==200 and setup.json()['team']==installed
    assert f.account_id not in setup.text and f.identity_id not in setup.text
    # Public response fixtures only; no request headers, credentials or private
    # connection correspondence is included in frontend contract evidence.
    (tmp_path/'rehearsal.json').write_text(json.dumps(value,sort_keys=True,ensure_ascii=False))
    (tmp_path/'setup.json').write_text(json.dumps(setup.json(),sort_keys=True,ensure_ascii=False))


def test_legacy_header_and_exact_historical_recovery_preserve_original_body(case):
    f=case; legacy_headers={'Authorization':f.headers['Authorization']}
    base=team.default_configuration(); first,old_command=save(f,base,headers=legacy_headers)
    assert first.status_code==200
    enhanced=add_preset(first.json()['configuration'],'front_desk')
    installed,_=reviewed_save(f,enhanced,expected=1)
    assert f.client.get('/provider-team',headers=legacy_headers).status_code==426
    assert f.client.post('/provider-team',headers=legacy_headers,json=old_command).status_code==426
    recovered=f.client.post('/provider-team',headers=f.headers,json=old_command)
    assert recovered.status_code==200 and recovered.json()['revision']==1
    assert recovered.json()['recovery_scope']==installed['recovery_scope']
    assert f.client.get('/provider-team',headers=f.headers).json()['revision']==2
    assert 'presets' not in old_command['configuration'] and all('blocked_capabilities' not in b for b in old_command['configuration']['bots'])


@pytest.mark.parametrize('headers', [{}, {'X-Cosmas-Team-Contract':'0'}, {'X-Cosmas-Team-Contract':'1, 1'}])
def test_new_routes_require_exact_contract_without_changing_legacy_reads(case,headers):
    f=case; selected={'Authorization':f.headers['Authorization'],**headers}
    assert f.client.get('/provider-team/setup',headers=selected).status_code==426
    assert rehearse(f,team.default_configuration(),headers=selected).status_code==426
    if not headers: assert f.client.get('/provider-team',headers=selected).status_code==200


def test_changed_prerequisites_reject_new_save_but_committed_retry_survives_disable(case):
    f=case; configuration=add_preset(team.default_configuration(),'front_desk')
    preview=rehearse(f,configuration).json()
    # The fixture deliberately reuses a session; mirror request teardown so an
    # independent revocation is not blocked by this completed read's row lock.
    f.session.rollback()
    with Session(f.engine) as separate:
        separate.get(CoreCaptureAccount,f.account_id).revoked_at=datetime.now(UTC);separate.commit()
    response,_=save(f,configuration,review=preview['setup_review'])
    assert response.status_code==409 and response.json()['detail']=='team_setup_prerequisites_changed'
    current=rehearse(f,configuration).json(); response,command=save(f,configuration,review=current['setup_review'])
    assert response.status_code==200,response.text
    f.configuration.workspace_team_setup_enabled=False
    repeated=f.client.post('/provider-team',headers=f.headers,json=command)
    assert repeated.status_code==200 and repeated.json()==response.json()
    changed={**command,'setup_review':{**command['setup_review'],'prerequisites_sha256':'a'*64}}
    assert f.client.post('/provider-team',headers=f.headers,json=changed).status_code==409


def test_readiness_is_scoped_to_current_signed_identity_not_box_runtime_flag(case):
    f=case
    first=f.client.get('/provider-team/setup',headers=f.headers).json()
    prep=lambda value: next(row for row in value['setup']['capabilities'] if row['bot']=='visit_prep' and row['capability']=='encounter_prep')
    assert prep(first)['state']=='requires_encounter'
    other=Principal(box_id=f.box,principal_type='human',state='active',display_name='Invented second owner')
    f.session.add(other);f.session.flush()
    binding=ExternalIdentity(box_id=f.box,principal_id=other.id,provider='clerk',issuer=f.configuration.clerk_issuer,
        subject='user_'+uuid4().hex,organization_id='org_invented',reviewed_by='Invented reviewer',evidence_ref='synthetic:team-setup')
    f.session.add(binding);f.session.commit()
    headers={**f.headers,'Authorization':'Bearer '+f.token(sub=binding.subject)}
    result=f.client.get('/provider-team/setup',headers=headers)
    assert result.status_code==200,result.text
    assert prep(result.json())['state']=='connection_required'
    assert first['setup']['prerequisites_sha256']!=result.json()['setup']['prerequisites_sha256']
    assert f.account_id not in result.text and f.actor not in result.text


def test_model_deny_uses_local_named_behavior_without_calling_model(case,monkeypatch):
    f=case;f.configuration.workspace_llm_backend='azure_gpt41';f.configuration.workspace_llm_api_key=SecretStr('invented-model-token')
    config=team.default_configuration();config['bots'][0]['blocked_capabilities']=['model_answer']
    installed,_=reviewed_save(f,config)
    f.configuration.workspace_team_setup_enabled=False
    monkeypatch.setattr(model_work,'dispatch_claim',lambda *_:pytest.fail('Restricted bot must not use model dispatcher'))
    result=f.client.post('/workspaces/'+f.workspace['id']+'/conversation',headers=f.headers,
        json={'expected_revision':1,'team_revision':installed['revision'],'role':'scribe','content':'Review saved context','idempotency_key':'w33-local-only'})
    assert result.status_code==200,result.text
    assert f.client.get('/workspaces/'+f.workspace['id'],headers=f.headers).json()['entries'][-1]['reply']['backend']=='local_source_review_v1'


@pytest.mark.parametrize('who',['chief','scribe'])
@pytest.mark.parametrize('restriction',['private_draft_handoff','model_answer'])
def test_handoff_deny_excludes_issuer_or_recipient_before_assignment(case,who,restriction):
    f=case;configuration=team.default_configuration()
    next(bot for bot in configuration['bots'] if bot['role']==who)['blocked_capabilities']=[restriction]
    reviewed_save(f,configuration)
    f.configuration.workspace_team_setup_enabled=False
    version=team.current(f.session,f.box,f.actor);chief=next(b for b in version.configuration['bots'] if b['role']=='chief')
    candidates=handoffs.available_roles(f.session,f.box,f.actor,version,chief)
    assert (not candidates) if who=='chief' else 'scribe' not in candidates


def test_brief_deny_keeps_schedule_and_prevents_new_run(case,monkeypatch):
    f=case;f.configuration.workspace_routines_enabled=True
    config=team.default_configuration();next(b for b in config['bots'] if b['role']=='chief')['blocked_capabilities']=['practice_work_brief']
    installed,_=reviewed_save(f,config)
    value=routines.save(f.session,f.box,f.actor,'chief',expected=0,team_revision=installed['revision'],
        key='w33-restricted-brief',configuration=routine_configuration())
    revision=f.session.scalar(select(RoutineRevision).where(RoutineRevision.agent_id==value['agent_id']))
    f.configuration.workspace_team_setup_enabled=False
    due=revision.created_at.astimezone(UTC).replace(hour=8,minute=0,second=0,microsecond=0)+timedelta(days=1)
    monkeypatch.setattr(routines,'_now',lambda _:due)
    assert routines.run_once(f.session,f.box,f.actor,'chief')=={'status':'restricted'}
    assert f.session.scalar(select(func.count()).select_from(RoutineRun).where(RoutineRun.agent_id==value['agent_id']))==0
    assert routines.read(f.session,f.box,f.actor,'chief')['configuration']['enabled'] is True


def test_brief_lost_team_after_source_read_publishes_no_run(case, monkeypatch):
    f = case
    f.configuration.workspace_routines_enabled = True
    installed, _ = reviewed_save(f, team.default_configuration())
    value = routines.save(f.session, f.box, f.actor, 'chief', expected=0,
        team_revision=installed['revision'], key='lost-team-brief', configuration=routine_configuration())
    revision = f.session.scalar(select(RoutineRevision).where(RoutineRevision.agent_id == value['agent_id']))
    due = revision.created_at.astimezone(UTC).replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
    monkeypatch.setattr(routines, '_now', lambda _: due)
    original = routines._snapshot

    def unavailable_after_read(*args):
        result = original(*args)
        monkeypatch.setattr(team, 'current', lambda *_: None)
        return result

    monkeypatch.setattr(routines, '_snapshot', unavailable_after_read)
    with pytest.raises(ws.WorkspaceError, match='team_revision_conflict'):
        routines.run_once(f.session, f.box, f.actor, 'chief')
    assert f.session.scalar(select(func.count()).select_from(RoutineRun)
        .where(RoutineRun.agent_id == value['agent_id'])) == 0


@pytest.mark.parametrize('who',['chief','scribe'])
def test_queued_handoff_is_failed_before_model_after_owner_adds_restriction(case,monkeypatch,who):
    f=case;f.configuration.workspace_llm_backend='azure_gpt41';f.configuration.workspace_llm_api_key=SecretStr('invented-model-token')
    installed,_=reviewed_save(f,team.default_configuration())
    monkeypatch.setattr(model_work,'dispatch_claim',lambda claim: BotReply('Invented private draft request',(),
        'azure_gpt41',handoffs=(DraftBrief('scribe','Organize saved context for human review.'),)))
    assigned=f.client.post('/workspaces/'+f.workspace['id']+'/conversation',headers=f.headers,
        json={'expected_revision':1,'team_revision':1,'role':'chief','content':'Prepare a private draft','idempotency_key':'w33-queue'})
    assert assigned.status_code==200,assigned.text
    handoff=f.client.get('/workspaces/'+f.workspace['id'],headers=f.headers).json()['handoffs'][0]
    configuration=deepcopy(installed['configuration']);next(b for b in configuration['bots'] if b['role']==who)['blocked_capabilities']=['private_draft_handoff']
    reviewed_save(f,configuration,expected=1);f.session.rollback()
    f.configuration.workspace_team_setup_enabled=False
    monkeypatch.setattr(model_work,'dispatch_claim',lambda *_:pytest.fail('Queued restricted work cannot call the model'))
    @contextmanager
    def factory():
        with Session(f.engine) as session:yield session
    assert handoffs.process_next(factory)
    f.session.expire_all();attempt=f.session.get(WorkspaceHandoffAttempt,handoff['attempt_id'])
    assert attempt.status=='failed' and attempt.result_entry_id is None and attempt.error_code=='authority_changed'
    assert f.client.get('/workspaces/'+f.workspace['id'],headers=f.headers).json()['revision']==3


def test_preset_binding_cannot_disappear_or_rebind_active_identity(case):
    f=case;configuration=add_preset(team.default_configuration(),'front_desk');installed,_=reviewed_save(f,configuration)
    removed=deepcopy(installed['configuration']);removed.pop('presets')
    response=rehearse(f,removed,1)
    assert response.status_code==409 and response.json()['detail']=='team_preset_missing'
    changed=deepcopy(installed['configuration']);slots=changed['presets'][1]['slots']
    slots['inbox'],slots['intake']=slots['intake'],slots['inbox']
    response=rehearse(f,changed,1)
    assert response.status_code==409 and response.json()['detail']=='team_preset_binding_immutable'


def test_saved_retirement_allows_only_new_slot_identity_and_preserves_old_principal(case):
    f=case;installed,_=reviewed_save(f,add_preset(team.default_configuration(),'front_desk'))
    original=deepcopy(installed['configuration']);address=original['presets'][1]['slots']['inbox']
    retired=deepcopy(original);old=next(b for b in retired['bots'] if team.bot_address(b)==address)
    old['retired']=True;old['enabled']=False
    retired_team,_=reviewed_save(f,retired,expected=1)
    old_agent=next(m['agent_id'] for m in installed['members'] if team.bot_address(m)==address)
    replacement=deepcopy(retired_team['configuration']);new_address=str(uuid4())
    new_bot={**old,'instance_id':new_address,'name':'Replacement Inbox'};new_bot.pop('retired')
    replacement['bots'].append(new_bot);replacement['presets'][1]['slots']['inbox']=new_address
    replaced,_=reviewed_save(f,replacement,expected=2)
    agents={team.bot_address(m):m['agent_id'] for m in replaced['members']}
    assert agents[address]==old_agent and agents[new_address]!=old_agent
    f.session.expire_all();old_principal=f.session.get(Principal,old_agent)
    assert old_principal.state=='disabled' and old_principal.tombstoned_at is not None
    assert next(b for b in replaced['configuration']['bots'] if team.bot_address(b)==address)==old
    assert f.session.scalar(select(func.count()).select_from(ProviderTeamRevision).where(
        ProviderTeamRevision.box_id==f.box,ProviderTeamRevision.owner_id==f.actor))==3
    revived=deepcopy(replaced['configuration']);next(b for b in revived['bots'] if team.bot_address(b)==address).pop('retired')
    response=rehearse(f,revived,3)
    assert response.status_code==409 and response.json()['detail']=='team_member_retired'


def test_two_identical_reviewed_installs_create_one_revision_and_same_private_agents(case):
    f=case;configuration=add_preset(team.default_configuration(),'front_desk')
    review=rehearse(f,configuration).json()['setup_review'];f.session.rollback()
    barrier=Barrier(2)
    def install():
        with Session(f.engine) as session:
            barrier.wait(timeout=5)
            return team.save(session,f.box,f.actor,expected=0,key='w33-concurrent-install',
                configuration=configuration,setup_review=review,external_identity_id=f.identity_id,team_contract=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(install) for _ in range(2)];results=[item.result(timeout=15) for item in futures]
    assert results[0]==results[1] and results[0]['revision']==1
    assert f.session.scalar(select(func.count()).select_from(ProviderBot).where(
        ProviderBot.box_id==f.box,ProviderBot.owner_id==f.actor))==7
    assert f.session.scalar(select(func.count()).select_from(ProviderTeamRevision).where(
        ProviderTeamRevision.box_id==f.box,ProviderTeamRevision.owner_id==f.actor))==1


@pytest.mark.parametrize('fault',['duplicate_key','null_review','unknown_field','surrogate','oversized','encoding','query','duplicate_header'])
def test_malformed_or_ambiguous_commands_reject_safely_without_writes(case,fault):
    f=case;marker='PRIVATE-INPUT-MUST-NOT-BE-ECHOED'
    body={'expected_revision':0,'configuration':team.default_configuration(),'idempotency_key':'invalid-boundary'}
    body['configuration']['practice_context']=marker
    path='/provider-team';headers={**f.headers,'Content-Type':'application/json'}
    if fault=='null_review':body['setup_review']=None
    elif fault=='unknown_field':body['unknown']=marker
    elif fault=='surrogate':body['configuration']['practice_context']='bad\ud800'
    elif fault=='encoding':headers['Content-Encoding']='gzip'
    elif fault=='query':path+='?unexpected=private'
    elif fault=='duplicate_header':headers=list(headers.items())+[('X-Cosmas-Team-Contract','1')]
    raw=json.dumps(body)
    if fault=='duplicate_key':raw='{"expected_revision":1,'+raw[1:]
    elif fault=='oversized':raw=' '*team_setup.MAX_REQUEST_BYTES+raw
    before=counts(f);response=f.client.post(path,headers=headers,content=raw)
    assert response.status_code==(426 if fault=='duplicate_header' else 422)
    assert response.json()=={'detail':'team_contract_unsupported' if fault=='duplicate_header' else 'invalid_team_setup_request'}
    assert marker not in response.text and response.headers['cache-control']=='no-store' and counts(f)==before


@pytest.mark.parametrize('route',['/provider-team','/provider-team/rehearsal'])
def test_signed_session_is_rechecked_after_slow_body_before_recovery_or_evaluation(case,monkeypatch,route):
    from fastapi import HTTPException
    f=case;response,command=save(f,team.default_configuration());assert response.status_code==200
    if route.endswith('rehearsal'):command={'expected_revision':1,'configuration':team.default_configuration(),'scenario_id':'preset_setup.v1'}
    original=api.read_team_request
    async def slow_body(request,schema):
        result=await original(request,schema)
        def expired(**kwargs):raise HTTPException(401,'authentication_required')
        monkeypatch.setattr(api,'_identity',expired)
        return result
    monkeypatch.setattr(api,'read_team_request',slow_body)
    before=counts(f);response=f.client.post(route,headers=f.headers,json=command)
    assert response.status_code==401 and counts(f)==before
