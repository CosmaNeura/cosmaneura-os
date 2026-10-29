// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {memoryDraftStorage} from '../draft-test-fixture';
import {teamFixture} from '../team-setup-test-fixture';
import type {AuthenticatedWorkspaceIdentity,Workspace} from '../workspace-api';
import type {RecordingContext,RecordingDependencies} from './recording';
import type {PrivateNotebookResult} from './recording-model';
import {WorkspaceSession} from './workspace-session';

async function fixture(deps:RecordingDependencies={}){
  const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
  const workspace:Workspace={id:'00000000-0000-4000-8000-000000000051',appointment_id:null,label:'Invented private notebook',revision:1,entries:[],work_candidates:[],private_draft:{title:'Invented private notebook',state:'unlinked',linked_at:null,link_receipt_id:null}};
  const team={...teamFixture(),recovery_scope:'a'.repeat(64)},result={identity:authenticated,workspace,team};
  const openPrivateDraft=vi.fn(async()=>result),session=new WorkspaceSession({recording:{openPrivateDraft,...deps}});
  session.setIdentity(authenticated);session.setWorkspace(workspace);session.setTeam(team);
  await session.recovery.prepare({authenticated,team,workspace,generation:0,apiBase:'http://127.0.0.1:8000',native:false,draftStorage:memoryDraftStorage()});
  session.recording.live.current={authenticated,editorJournal:session.recovery.journal.current!.value,editorScope:team.recovery_scope,generation:0};
  const context:RecordingContext={authenticated,authorize:vi.fn(async()=>{}),captureEnabled:true,locked:false,connectionNavigationLocked:false,captureNavigationLocked:false,captureDraftLocked:false,expand:vi.fn(),showNotebook:vi.fn(),openNotebook:vi.fn(async()=>{})};
  return {session,context,result,openPrivateDraft};
}

describe('session-owned recording navigation',()=>{
  it('opens consent on the current private notebook without creating a notebook or replacing its draft',async()=>{
    const f=await fixture();f.session.setNote('Invented unsaved notes');f.session.recording.startNotebook(f.context);
    const entry=f.session.getSnapshot().privateRecordingEntry!;
    expect(entry.returnWorkspaceId).toBe(f.result.workspace.id);expect(f.openPrivateDraft).not.toHaveBeenCalled();expect(f.session.getSnapshot().note).toBe('Invented unsaved notes');
    expect(await entry.prepareNotebook!()).toBe(f.result);expect(f.context.authorize).toHaveBeenCalledOnce();f.session.recovery.close();
  });
  it('rejects a continuation after generation invalidation before a view has rerendered',async()=>{
    const f=await fixture();f.session.recording.startNotebook(f.context);const entry=f.session.getSnapshot().privateRecordingEntry!;f.session.invalidate();
    expect(f.session.recording.isCurrent(entry)).toBe(false);await expect(entry.prepareNotebook!()).rejects.toMatchObject({status:403});expect(f.openPrivateDraft).not.toHaveBeenCalled();f.session.recovery.close();
  });
  it('does not attach the recording to a different returned notebook',async()=>{
    let result!:PrivateNotebookResult;const f=await fixture({openPrivateDraft:async()=>result});result={...f.result,workspace:{...f.result.workspace,id:'00000000-0000-4000-8000-000000000052'}};
    f.session.recording.startNotebook(f.context);await expect(f.session.getSnapshot().privateRecordingEntry!.prepareNotebook!()).rejects.toMatchObject({status:403});f.session.recovery.close();
  });
  it('retires a stopped Home recorder before opening the newly saved notebook',async()=>{
    const f=await fixture();f.session.recording.start({title:'Invented recording',prepareNotebook:async()=>f.result},f.context);const entry=f.session.getSnapshot().privateRecordingEntry!;
    const openNotebook=vi.fn(async()=>{expect(f.session.getSnapshot().privateRecordingEntry).toBeNull();f.session.invalidate();});
    await f.session.recording.returnNotebook(entry,f.result,{...f.context,openNotebook});expect(openNotebook).toHaveBeenCalledWith(f.result);f.session.recovery.close();
  });
  it('returns to the same notebook without replacing its working draft or recorder identity',async()=>{
    const f=await fixture();f.session.setNote('Keep these invented notes');f.session.recording.startNotebook(f.context);const entry=f.session.getSnapshot().privateRecordingEntry!;
    await f.session.recording.returnNotebook(entry,{...f.result,workspace:{...f.result.workspace,revision:2}},f.context);
    expect(f.session.getSnapshot()).toMatchObject({note:'Keep these invented notes',workspace:{revision:2},privateRecordingEntry:entry});expect(f.context.openNotebook).not.toHaveBeenCalled();expect(f.context.showNotebook).toHaveBeenCalledOnce();f.session.recovery.close();
  });
});
