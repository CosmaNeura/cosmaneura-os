// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {memoryDraftStorage} from '../draft-test-fixture';
import {teamFixture,teamUuid} from '../team-setup-test-fixture';
import type {AccountIdentity} from '../account-identity-api';
import type {AuthenticatedWorkspaceIdentity,Workspace} from '../workspace-api';
import type {ActivityContext,ActivityDependencies} from './activity';
import {WorkspaceSession} from './workspace-session';

async function fixture(deps:ActivityDependencies={}){
  const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null},team=teamFixture();
  const workspace:Workspace={id:teamUuid(201),appointment_id:teamUuid(202),label:'Invented visit',revision:2,work_candidates:[],entries:[{
    id:teamUuid(203),kind:'conversation',revision:2,content:'Invented question',origin:'human',source_label:null,ticket:null,created_at:'2026-10-23T12:00:00Z',
    reply:{role:'chief',agent_id:team.members.find(bot=>bot.role==='chief')!.agent_id!,agent_name:'Chief',backend:'fake',context_revision:1,content:'Invented answer',citations:[]},
  }]};
  const account:AccountIdentity={contract_version:1,box_id:teamUuid(204),actor_id:teamUuid(205),recovery_scope:team.recovery_scope!};
  const session=new WorkspaceSession({activity:{read:async()=>workspace,team:async()=>team,accountRead:async()=>account,...deps}});
  session.setIdentity(authenticated);session.setTeam(team);session.setTeamDraft(team.configuration);session.setWorkspace(workspace);session.setSettingsOpen(true);
  await session.recovery.prepare({authenticated,team,workspace,generation:0,apiBase:'http://127.0.0.1:8000',native:false,draftStorage:memoryDraftStorage()});
  const context={box_id:account.box_id,owner_id:account.actor_id,recovery_scope:account.recovery_scope},journal=session.recovery.journal.current!.value;
  const host:ActivityContext={authenticated,activityContext:context,activityEnabled:true,accountAccess:{authorize:vi.fn(async()=>{})},editorJournal:journal,editorScope:account.recovery_scope,
    currentTeam:{current:team},currentTeamDraft:{current:team.configuration},hasUnsavedWork:()=>false,failure:vi.fn(),resetCapture:vi.fn()};
  session.activity.live.current={authenticated,editorJournal:journal,editorScope:account.recovery_scope,settingsOpen:true,practiceOpen:false,activityContext:context,activityBlocked:false,workspace,note:''};
  return {session,host,workspace,account,selection:{workspace_id:workspace.id,appointment_id:workspace.appointment_id!,entry_id:workspace.entries[0].id}};
}

describe('shared activity navigation',()=>{
  it('opens the freshly authorized exact result without asking a bot or changing the draft',async()=>{
    const f=await fixture(),ask=vi.spyOn(f.session.models,'ask');f.session.setThought('Invented unsent next question');
    await f.session.activity.open(f.selection,f.host);
    expect(f.session.getSnapshot()).toMatchObject({selected:'chief',selectedResult:f.selection.entry_id,settingsOpen:false,thought:'Invented unsent next question'});
    expect(ask).not.toHaveBeenCalled();f.session.recovery.close();
  });
  it('does not open another notebook while current work is unsaved',async()=>{
    const read=vi.fn(),f=await fixture({read});f.host.hasUnsavedWork=()=>true;
    await expect(f.session.activity.open({...f.selection,workspace_id:teamUuid(206)},f.host)).rejects.toMatchObject({status:503});
    expect(read).not.toHaveBeenCalled();expect(f.session.getSnapshot().workspace).toBe(f.workspace);f.session.recovery.close();
  });
  it('withholds a late account proof after the owner changes',async()=>{
    let finish!:(value:AccountIdentity)=>void;const accountRead=vi.fn(()=>new Promise<AccountIdentity>(resolve=>{finish=resolve;})),f=await fixture({accountRead});
    const stop=f.session.activity.watch(f.host);await vi.waitFor(()=>expect(accountRead).toHaveBeenCalledOnce());
    f.session.clear();finish(f.account);await Promise.resolve();await Promise.resolve();
    expect(f.session.getSnapshot().activityProof).toBeNull();stop();
  });
  it('rejects a result that disappears in the fresh source read',async()=>{
    const read=vi.fn(async()=>({...f.workspace,entries:[]}));const f=await fixture({read});
    await expect(f.session.activity.open(f.selection,f.host)).rejects.toMatchObject({status:503});
    expect(read).toHaveBeenCalledOnce();expect(f.session.getSnapshot().selectedResult).toBeNull();f.session.recovery.close();
  });
});
