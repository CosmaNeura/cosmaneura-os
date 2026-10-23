// @vitest-environment node
import {afterEach,describe,expect,it,vi} from 'vitest';
import {DraftJournal,notebookDraft,type NotebookDraft} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import type {AuthenticatedWorkspaceIdentity,ProviderTeam,Workspace} from '../workspace-api';
import {WorkspaceApiError} from '../workspace-api';
import type {RecoveryRead} from './recovery';
import {WorkspaceSession} from './workspace-session';

const workspace:Workspace={id:'00000000-0000-4000-8000-000000000021',label:'Invented private note',appointment_id:null,revision:1,entries:[],work_candidates:[]};
const team:ProviderTeam={revision:1,recovery_scope:'a'.repeat(64),template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},
  configuration:{practice_context:'DPC',bots:[{role:'chief',name:'Chief',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[]};
const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const address=`workspace:${workspace.id}`;
const retained:NotebookDraft={kind:'workspace',workspaceId:workspace.id,baseRevision:1,note:'Invented retained note',thought:'Next unsent question',evidence:'',source:'',
  pending:{type:'entry',body:{expected_revision:1,idempotency_key:'00000000-0000-4000-8000-000000000022',kind:'scratchpad',content:'Invented retained note'}}};
const owner={authenticated,currentAuthenticated:()=>authenticated,currentTeam:()=>team};
const input=(session:WorkspaceSession,draftStorage=memoryDraftStorage()):RecoveryRead=>({authenticated,team,workspace,
  generation:session.generation.current,apiBase:'http://127.0.0.1:8000',native:false,draftStorage});

afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();});

describe('session-owned draft recovery',()=>{
  it('retains account editor access across notebook navigation but rejects a replaced journal',async()=>{
    const session=new WorkspaceSession({recovery:{team:async()=>team}});await session.recovery.prepare(input(session));
    const access=session.recovery.accountAccess(authenticated,team.recovery_scope,session.recovery.journal.current!.value,true)!;
    session.invalidate();await expect(access.authorize()).resolves.toBeUndefined();session.recovery.close();
    await expect(access.authorize()).rejects.toMatchObject({status:403});
  });

  it('does not publish a late editor recovery read into a newer notebook',async()=>{
    let finish!:(value:Workspace)=>void;const read=vi.fn(()=>new Promise<Workspace>(resolve=>{finish=resolve;}));
    const session=new WorkspaceSession({recovery:{team:async()=>team,read}});session.setWorkspace(workspace);await session.recovery.prepare(input(session));
    const access=session.recovery.editorAccess(authenticated,team.recovery_scope!,session.recovery.journal.current!.value,workspace.id,true,false,vi.fn())!;
    const checking=access.authorize();await vi.waitFor(()=>expect(read).toHaveBeenCalledOnce());session.clear();finish(workspace);
    await expect(checking).rejects.toMatchObject({status:403});expect(session.getSnapshot().workspace).toBeNull();
  });

  it('offers the exact draft and request after a session reload without replaying it',async()=>{
    const factory=memoryDraftStorage(),first=new WorkspaceSession();
    await first.recovery.prepare(input(first,factory));
    await first.recovery.journal.current!.value.persist(address,retained);
    first.recovery.close();
    const second=new WorkspaceSession();await second.recovery.prepare(input(second,factory));
    expect(second.getSnapshot().recoveryOffers).toEqual([{address,draft:retained}]);
    expect(second.getSnapshot().pending).toBeNull();
    second.recovery.close();
  });

  it('refuses another account recovery scope before opening its storage',async()=>{
    const session=new WorkspaceSession(),request=input(session);await session.recovery.prepare(request);
    const other=vi.fn(memoryDraftStorage());
    await expect(session.recovery.prepare({...request,team:{...team,recovery_scope:'b'.repeat(64)},draftStorage:other})).rejects.toMatchObject({status:403});
    expect(other).not.toHaveBeenCalled();
    expect(session.recovery.journal.current?.serverScope).toBe(team.recovery_scope);
    session.recovery.close();
  });

  it('closes a late storage open after the owner is invalidated',async()=>{
    const session=new WorkspaceSession(),store=await memoryDraftStorage()({scope:'c'.repeat(64)});
    const closed=vi.spyOn(store,'close');
    let entered!:()=>void,finish!:(value:typeof store)=>void;
    const opened=new Promise<void>(resolve=>{entered=resolve;});
    const loading=session.recovery.prepare(input(session,()=>{entered();return new Promise(resolve=>{finish=resolve;});}));
    await opened;session.invalidate();finish(store);await loading;
    expect(closed).toHaveBeenCalledOnce();
    expect(session.recovery.journal.current).toBeNull();
    expect(session.getSnapshot().recoveryOffers).toEqual([]);
  });

  it('flushes the final local draft before closing and preserves its exact pending body',async()=>{
    vi.useFakeTimers();
    const session=new WorkspaceSession(),factory=memoryDraftStorage();await session.recovery.prepare(input(session,factory));
    const active=session.recovery.journal.current!,closed=vi.spyOn(active.value,'close');
    session.setWorkspace(workspace);session.setTeam(team);session.setNote(retained.note);
    const cleanup=session.recovery.schedule(owner,()=>retained);
    const scheduled=session.recovery.scheduledDraftSave.current!;
    session.recovery.close();
    expect(closed).not.toHaveBeenCalled();
    await scheduled.drain();await Promise.resolve();await Promise.resolve();
    expect(closed).toHaveBeenCalledOnce();
    const reopened=new DraftJournal(await factory({scope:active.scope}));
    expect(await reopened.load(address)).toEqual(retained);
    cleanup?.();reopened.close();
  });

  it('does not turn failed target recovery into a saved acknowledgment when an older local write settles',async()=>{
    vi.useFakeTimers();
    const session=new WorkspaceSession();await session.recovery.prepare(input(session));
    session.setWorkspace(workspace);session.setTeam(team);
    const cleanup=session.recovery.schedule(owner,()=>retained);
    const saving=session.recovery.scheduledDraftSave.current!.run();
    session.setRecoveryState('failed');await saving;
    expect(session.getSnapshot().recoveryState).toBe('failed');
    cleanup?.();session.recovery.close();
  });

  it('does not discard an unconfirmed recovered request',async()=>{
    const session=new WorkspaceSession();await session.recovery.prepare(input(session));
    await session.recovery.journal.current!.value.persist(address,retained);
    const offer={address,draft:retained};session.setRecoveryOffers([offer]);
    const persist=vi.spyOn(session.recovery.journal.current!.value,'persist');
    await session.recovery.discard(offer);
    expect(persist).not.toHaveBeenCalled();
    expect(session.getSnapshot().recoveryOffers).toEqual([offer]);
    session.recovery.close();
  });

  it('retains a native next-message draft alongside the exact in-flight model request',async()=>{
    vi.useFakeTimers();
    const session=new WorkspaceSession();await session.recovery.prepare(input(session));
    const native:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null,nativeSession:{revision:'invented-session-1',isCurrent:()=>true}};
    const pending={type:'ask' as const,body:{expected_revision:1,team_revision:1,idempotency_key:'00000000-0000-4000-8000-000000000024',role:'chief',content:'Invented sent question'}};
    session.setWorkspace(workspace);session.setTeam(team);session.setPending(pending);session.setBusy(true);
    const cleanup=session.recovery.schedule({...owner,authenticated:native,currentAuthenticated:()=>native},request=>
      notebookDraft(workspace,'','Invented next question','','',request));
    await session.recovery.scheduledDraftSave.current!.run();
    expect(await session.recovery.journal.current!.value.load(address)).toMatchObject({thought:'Invented next question',pending});
    cleanup?.();session.recovery.close();
  });

  it('does not flush another owner or a suspended native identity',async()=>{
    const session=new WorkspaceSession(),run=vi.fn(async()=>{});
    session.recovery.scheduledDraftSave.current={run,cancel:()=>{},drain:async()=>{}};
    session.recovery.flush({...owner,currentAuthenticated:()=>undefined});
    const native:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null,nativeSession:{revision:'invented-session-1',isCurrent:()=>false}};
    session.recovery.flush({...owner,authenticated:native,currentAuthenticated:()=>native});
    expect(run).not.toHaveBeenCalled();
  });

  it('revalidates access before restoring the exact request and working text',async()=>{
    const read=vi.fn(async()=>({...workspace,revision:2})),readTeam=vi.fn(async()=>team);
    const session=new WorkspaceSession({recovery:{read,team:readTeam}});
    session.setWorkspace(workspace);session.setTeam(team);session.setRecoveryOffers([{address,draft:retained}]);
    const show=vi.fn(),failure=vi.fn();
    await session.recovery.restore({address,draft:retained},{authenticated,show,failure});
    expect(readTeam).toHaveBeenCalledWith(authenticated);
    expect(read).toHaveBeenCalledWith(authenticated,workspace.id);
    expect(session.getSnapshot()).toMatchObject({note:retained.note,thought:retained.thought,workspace:{revision:2},recoveryOffers:[]});
    expect(session.getSnapshot().pending).toBe(retained.pending);
    expect(show).toHaveBeenCalledWith({kind:'workspace',material:'Notebook',noteTask:undefined,helper:undefined});
    expect(failure).not.toHaveBeenCalled();
  });

  it('withholds recovered text when access is revoked',async()=>{
    const denied=new WorkspaceApiError(403);
    const session=new WorkspaceSession({recovery:{team:async()=>team,read:async()=>{throw denied;}}});
    session.setWorkspace(workspace);session.setTeam(team);
    const show=vi.fn(),failure=vi.fn();
    await session.recovery.restore({address,draft:retained},{authenticated,show,failure});
    expect(session.getSnapshot()).toMatchObject({note:'',thought:'',pending:null});
    expect(show).not.toHaveBeenCalled();expect(failure).toHaveBeenCalledWith(denied);
  });

  it('drops a late restore after changing the session',async()=>{
    let finish!:(value:Workspace)=>void,entered!:()=>void;
    const reading=new Promise<void>(resolve=>{entered=resolve;});
    const session=new WorkspaceSession({recovery:{team:async()=>team,read:()=>{entered();return new Promise(resolve=>{finish=resolve;});}}});
    session.setWorkspace(workspace);session.setTeam(team);
    const show=vi.fn(),failure=vi.fn();
    const restoring=session.recovery.restore({address,draft:retained},{authenticated,show,failure});
    await reading;session.invalidate();session.setNote('New session draft');session.setBusy(false);
    finish(workspace);await restoring;
    expect(session.getSnapshot()).toMatchObject({note:'New session draft',pending:null,busy:false});
    expect(show).not.toHaveBeenCalled();expect(failure).not.toHaveBeenCalled();
  });

  it('keeps the recovered note-task revision and hashes when the saved note changes',async()=>{
    const session=new WorkspaceSession({recovery:{team:async()=>team,read:async()=>workspace}});
    session.setWorkspace(workspace);session.setTeam(team);await session.recovery.prepare(input(session));
    const task={contract:'chief-note-task.compose.v1' as const,note_id:'00000000-0000-4000-8000-000000000025',
      note_version:7,content_hash:'b'.repeat(64),source_fingerprint:'c'.repeat(64)};
    const show=vi.fn();await session.recovery.restore({address,draft:{...retained,chief_note_task:task}},
      {authenticated,show,failure:vi.fn()});
    expect(show).toHaveBeenCalledWith(expect.objectContaining({kind:'workspace',material:'Conversation',helper:'chief',
      noteTask:expect.objectContaining({content:'',selection:expect.objectContaining({note_id:task.note_id,note_version:7,
        content_hash:task.content_hash,source_fingerprint:task.source_fingerprint})})}));
    session.recovery.close();
  });

  it('keeps an unconfirmed request when explicitly closing the workspace',async()=>{
    const session=new WorkspaceSession();await session.recovery.prepare(input(session));
    const active=session.recovery.journal.current!.value;await active.persist(address,retained);
    const clear=vi.fn(),onExit=vi.fn(),confirm=vi.fn();
    await session.recovery.exit(true,{navigationLocked:false,hasUnsavedWork:()=>true,confirm,clear,onExit});
    expect(await active.load(address)).toEqual(retained);
    expect(clear).toHaveBeenCalledOnce();expect(onExit).toHaveBeenCalledOnce();expect(confirm).not.toHaveBeenCalled();
    session.recovery.close();
  });

  it.each([
    {type:'followUpDecision' as const,ticketId:'00000000-0000-4000-8000-000000000027',body:{revision_id:'00000000-0000-4000-8000-000000000028',payload_hash:'d'.repeat(64),choice:'approve' as const}},
    {type:'review' as const,noteId:'00000000-0000-4000-8000-000000000029',body:{expected_revision:1,idempotency_key:'00000000-0000-4000-8000-000000000030',content_hash:'e'.repeat(64),source_fingerprint:'f'.repeat(64)}},
  ])('returns recovered $type work to its existing review destination',async pending=>{
    const session=new WorkspaceSession({recovery:{team:async()=>team,read:async()=>workspace}});
    session.setWorkspace(workspace);session.setTeam(team);
    const show=vi.fn();
    await session.recovery.restore({address,draft:{...retained,pending}}, {authenticated,show,failure:vi.fn()});
    expect(show).toHaveBeenCalledWith(expect.objectContaining({kind:'workspace',material:pending.type==='followUpDecision'?'Work':'Review'}));
    expect(session.getSnapshot().pending).toBe(pending);
  });

  it('returns a recovered team draft to Settings without applying it',async()=>{
    const read=vi.fn(),session=new WorkspaceSession({recovery:{team:async()=>team,read}});
    session.setTeam(team);
    const configuration={...team.configuration,practice_context:'Invented changed practice description'};
    const show=vi.fn();
    await session.recovery.restore({address:'team',draft:{kind:'team',baseRevision:1,configuration,pending:null}}, {authenticated,show,failure:vi.fn()});
    expect(show).toHaveBeenCalledWith({kind:'team'});expect(read).not.toHaveBeenCalled();
    expect(session.getSnapshot().teamDraft).toBe(configuration);
    expect(session.getSnapshot().team).toBe(team);
    expect(session.getSnapshot().pending).toBeNull();
  });
});
