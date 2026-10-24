// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {notebookDraft} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import {conversationFixture,modelReceipt,pendingWorkspace,modelTimestamp} from '../model-work-test-fixture';
import {modelRequestHash,type ModelOperation} from '../model-work-request';
import type {AuthenticatedWorkspaceIdentity,ProviderTeam,Workspace} from '../workspace-api';
import {WorkspaceSession} from './workspace-session';
import type {ModelActionContext} from './model-actions';
import {teamFixture} from '../team-setup-test-fixture';

const team:ProviderTeam={revision:1,recovery_scope:'a'.repeat(64),template_version:'provider-team-v1',llm:{enabled:true,model:'gpt-4.1'},
  configuration:{practice_context:'DPC',bots:[{role:'visit_prep',name:'Visit Prep',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[]};
const operation:Extract<ModelOperation,{type:'ask'}>={type:'ask',model_contract:1,origin:'durable_admission_v1',body:conversationFixture};
const identity={boxId:'invented-box',actorId:'invented-human'};
function context(session:WorkspaceSession,authenticated?:AuthenticatedWorkspaceIdentity):ModelActionContext {
  return {authenticated,notebookDraft,modelFailure:cause=>session.lifecycle.modelFailure(cause,{authenticated,clear:session.clear,recoveryFailed:()=>session.setRecoveryState('failed'),invalidateSetup:()=>{}})};
}
function open(session:WorkspaceSession,workspace:Workspace){session.setIdentity(identity);session.setWorkspace({...workspace,revision:1,entries:[]});session.setTeam(team);session.setTeamDraft(team.configuration);session.models.updateThought(conversationFixture.content);}
async function durable(session:WorkspaceSession,workspace:Workspace,authenticated:AuthenticatedWorkspaceIdentity){
  open(session,workspace);session.setIdentity(authenticated);
  await session.recovery.prepare({authenticated,team,workspace,generation:session.generation.current,apiBase:'http://127.0.0.1:8000',native:false,draftStorage:memoryDraftStorage()});
}

describe('shared model request ownership',()=>{
  it.each(['ask','save'] as const)('blocks %s during conversation restoration and sends only the restored bot draft afterward',async command=>{
    const workspace=await pendingWorkspace(),ask=vi.fn(async(_owner,_id,body:typeof conversationFixture)=>modelReceipt(body,workspace.id));
    const session=new WorkspaceSession({models:{workspace:{ask,read:async()=>workspace,team:async()=>teamFixture()}}});open(session,workspace);
    session.setTeam(teamFixture());session.setTeamDraft(teamFixture().configuration);session.setSelected('follow_up');
    session.models.updateThought('Keep this invented Chief draft separate.');session.setConversationBusy(true);
    if(command==='ask')await session.models.ask('follow_up',null,context(session));
    else await session.models.save({...operation,body:{...operation.body,role:'follow_up',content:session.getSnapshot().thought}},'submit',context(session));
    expect(ask).not.toHaveBeenCalled();expect(session.getSnapshot()).toMatchObject({thought:'Keep this invented Chief draft separate.',pending:null,busy:false});
    session.models.updateThought('Send this invented Follow-up draft.');session.setConversationBusy(false);
    await session.models.ask('follow_up',null,context(session));
    expect(ask).toHaveBeenCalledOnce();expect(ask.mock.calls[0][2]).toMatchObject({role:'follow_up',content:'Send this invented Follow-up draft.'});
  });
  it('checks a retained exact request without starting model work',async()=>{
    const workspace=await pendingWorkspace(),saved=await modelReceipt();
    const ask=vi.fn(),resolve=vi.fn(async()=>({...saved,outcome:'not_found' as const,saved_entry:null}));
    const session=new WorkspaceSession({models:{workspace:{ask,read:async()=>workspace,team:async()=>team},resolve}});open(session,workspace);session.setPending(operation);
    await session.models.save(operation,'resolve',context(session));
    expect(ask).not.toHaveBeenCalled();expect(resolve.mock.calls[0]).toEqual([identity,workspace.id,operation]);
    expect(session.getSnapshot().pending).toBe(operation);expect(session.getSnapshot().modelObservation?.receipt.outcome).toBe('not_found');
  });

  it('reuses the same model body and key after a lost reply',async()=>{
    const workspace=await pendingWorkspace(),receipt=await modelReceipt();
    const ask=vi.fn().mockRejectedValueOnce(new Error('Lost reply')).mockResolvedValueOnce(receipt);
    const session=new WorkspaceSession({models:{workspace:{ask,read:async()=>workspace,team:async()=>team}}});open(session,workspace);
    await session.models.save(operation,'submit',context(session));expect(session.getSnapshot().pending).toBe(operation);
    await session.models.save(operation,'submit',context(session));
    expect(ask.mock.calls.map(call=>call[2])).toEqual([operation.body,operation.body]);
    expect(ask.mock.calls[1][2]).toBe(operation.body);expect(session.getSnapshot().pending).toBeNull();
  });

  it('replaces an explicitly acknowledged request using a new key while retaining the old hash and outcome',async()=>{
    const workspace=await pendingWorkspace(),receipt=await modelReceipt();
    const read=vi.fn().mockResolvedValueOnce(workspace).mockResolvedValue({...workspace,revision:3});
    const ask=vi.fn(async(_owner,_id,body:typeof conversationFixture)=>modelReceipt(body,workspace.id,3));
    const session=new WorkspaceSession({models:{workspace:{ask,read,team:async()=>team}}});open(session,workspace);
    session.setPending(operation);session.setModelObservation({receipt:{...receipt,outcome:'not_found',saved_entry:null},observedAt:modelTimestamp});
    session.setReplacementDraft({content:'Invented revised question',role:'visit_prep',acknowledged:true});
    await session.models.replace(context(session));
    expect(ask).toHaveBeenCalledOnce();expect(ask.mock.calls[0][2]).toMatchObject({content:'Invented revised question',expected_revision:2});
    expect(ask.mock.calls[0][2].idempotency_key).not.toBe(operation.body.idempotency_key);
    expect(session.getSnapshot().previousModelRequest).toMatchObject({operation:{type:'ask',body:operation.body},request_sha256:await modelRequestHash(operation.body),outcome:'not_found'});
    expect(session.getSnapshot().pending).toBeNull();
  });

  it('retains the prior exact request if local storage cannot acknowledge a replacement',async()=>{
    const workspace=await pendingWorkspace(),ask=vi.fn(),authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
    const session=new WorkspaceSession({models:{workspace:{ask}}});await durable(session,workspace,authenticated);session.setPending(operation);
    vi.spyOn(session.recovery.journal.current!.value,'persist').mockRejectedValue(new Error('Local write failed'));
    const next:ModelOperation={...operation,body:{...operation.body,idempotency_key:'invented-replacement-key',content:'Invented next request'}};
    await session.models.save(next,'submit',context(session,authenticated));
    expect(ask).not.toHaveBeenCalled();expect(session.getSnapshot().pending).toBe(operation);
    expect(session.getSnapshot().error).toContain('No new request was sent');session.recovery.close();
  });

  it('preserves a native next draft, including identical text, when the previous request settles',async()=>{
    const workspace=await pendingWorkspace(),receipt=await modelReceipt();
    const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null,nativeSession:{revision:'invented-native-session',isCurrent:()=>true}};
    let release!:(value:typeof receipt)=>void,entered!:()=>void;
    const dispatched=new Promise<void>(resolve=>{entered=resolve;});
    const ask=vi.fn(()=>{entered();return new Promise<typeof receipt>(resolve=>{release=resolve;});});
    const session=new WorkspaceSession({models:{workspace:{ask,read:async()=>workspace,team:async()=>team}}});await durable(session,workspace,authenticated);
    const saving=session.models.save(operation,'submit',context(session,authenticated));await dispatched;
    expect(session.getSnapshot().thought).toBe('');session.models.updateThought(operation.body.content);
    release(receipt);await saving;
    expect(session.getSnapshot()).toMatchObject({thought:operation.body.content,pending:null,busy:false});
    expect(await session.recovery.journal.current!.value.load(`workspace:${workspace.id}`)).toMatchObject({thought:operation.body.content,pending:null});
    session.recovery.close();
  });

  it('does not query an altered saved request hash',async()=>{
    const workspace=await pendingWorkspace(),resolve=vi.fn(),read=vi.fn();
    const session=new WorkspaceSession({models:{workspace:{read},resolve}});open(session,workspace);
    const entry=structuredClone(workspace.entries[0]);entry.model_request!.request_sha256='0'.repeat(64);
    await session.models.checkEntryResult(entry,context(session));
    expect(resolve).not.toHaveBeenCalled();expect(read).not.toHaveBeenCalled();expect(session.getSnapshot().error).not.toBe('');
  });

  it('drops a late response and releases ownership when the session is cleared',async()=>{
    const workspace=await pendingWorkspace(),receipt=await modelReceipt();let release!:(value:typeof receipt)=>void;
    const ask=vi.fn(()=>new Promise<typeof receipt>(resolve=>{release=resolve;}));
    const session=new WorkspaceSession({models:{workspace:{ask}}});open(session,workspace);
    const saving=session.models.save(operation,'submit',context(session));session.clear();release(receipt);await saving;
    expect(session.getSnapshot()).toMatchObject({workspace:null,pending:null,thought:'',busy:false});
    expect(session.models.modelBusy.current).toBe(false);
  });
});
