// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {teamFixture} from '../team-setup-test-fixture';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from '../workspace-api';
import type {NavigationContext} from './navigation';
import {WorkspaceSession} from './workspace-session';
import {DraftJournal,editorAddress} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import type {ConversationHost} from './conversations';

const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const workspace:Workspace={id:'00000000-0000-4000-8000-000000000061',appointment_id:null,label:'Invented private notebook',revision:1,entries:[],work_candidates:[]};
function context(session:WorkspaceSession):NavigationContext{return {authenticated,failure:vi.fn(),recoverAfterRead:vi.fn(async()=>{}),prepareRecovery:vi.fn(async()=>{}),viewNavigationLocked:false,connectionNavigationLocked:false,captureNavigationLocked:false,captureDraftLocked:false,minimizeRecording:vi.fn(),hasUnsavedWork:()=>false,replaceRoute:vi.fn(),openPrivateNotebook:vi.fn(async()=>{}),loadEncounters:vi.fn(async()=>{}),currentTeam:{get current(){return session.getSnapshot().team;}}};}
function open(session:WorkspaceSession){session.setIdentity(authenticated);session.setWorkspace(workspace);session.setTeam(teamFixture());session.setTeamDraft(teamFixture().configuration);session.setPracticePage('notebook');session.setSelected('chief');session.setMobilePanel('Conversation');}

describe('one workspace navigation owner',()=>{
  it('keeps bot, context and working draft when changing the material in the same conversation',async()=>{
    const session=new WorkspaceSession();open(session);session.setThought('Invented unsent question');const host=context(session);
    await session.navigation.applyRoute({page:'notebook',workspaceId:workspace.id,helper:'chief',material:'Review'},host);
    expect(session.navigation.route()).toEqual({page:'notebook',workspaceId:workspace.id,helper:'chief',material:'Review'});
    expect(session.getSnapshot().thought).toBe('Invented unsent question');expect(session.generation.current).toBe(0);expect(host.openPrivateNotebook).not.toHaveBeenCalled();
  });
  it('discards a late deep-link read after a newer route wins',async()=>{
    let finish!:(value:Workspace)=>void;const read=vi.fn(()=>new Promise<Workspace>(resolve=>{finish=resolve;}));
    const session=new WorkspaceSession({navigation:{read,team:async()=>teamFixture()}});open(session);const host=context(session);
    const routing=session.navigation.applyRoute({page:'notebook',workspaceId:'00000000-0000-4000-8000-000000000062',helper:'chief'},host);
    await vi.waitFor(()=>expect(read).toHaveBeenCalledOnce());session.navigation.goHome(host);finish({...workspace,id:'00000000-0000-4000-8000-000000000062'});await routing;
    expect(session.getSnapshot().practicePage).toBe('home');expect(host.openPrivateNotebook).not.toHaveBeenCalled();
  });
  it('keeps Home when notebook recovery finishes after the user leaves',async()=>{
    const destination={...workspace,id:'00000000-0000-4000-8000-000000000062'};
    const session=new WorkspaceSession({navigation:{read:async()=>destination,team:async()=>teamFixture()}});open(session);const host=context(session);
    let finish!:()=>void;host.openPrivateNotebook=result=>session.loading.openPrivate(result,{authenticated,beforeOpen:()=>{},show:()=>session.setPracticePage('notebook'),recoverAfterRead:()=>new Promise(resolve=>{finish=resolve;})});
    const routing=session.navigation.applyRoute({page:'notebook',workspaceId:destination.id,helper:'follow_up',material:'Review'},host);
    await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));session.navigation.goHome(host);finish();await routing;
    expect(session.getSnapshot()).toMatchObject({practicePage:'home',selected:'chief',mobilePanel:'Conversation'});
  });
  it('does not restore a notebook route after its recovery belongs to a cleared account',async()=>{
    const destination={...workspace,id:'00000000-0000-4000-8000-000000000062'};
    const session=new WorkspaceSession({navigation:{read:async()=>destination,team:async()=>teamFixture()}});open(session);const host=context(session);
    let finish!:()=>void;host.openPrivateNotebook=result=>session.loading.openPrivate(result,{authenticated,beforeOpen:()=>{},show:()=>session.setPracticePage('notebook'),recoverAfterRead:()=>new Promise(resolve=>{finish=resolve;})});
    const routing=session.navigation.applyRoute({page:'notebook',workspaceId:destination.id,helper:'follow_up',material:'Review'},host);
    await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));session.clear();session.setPracticePage('home');finish();await routing;
    expect(session.getSnapshot()).toMatchObject({practicePage:'home',workspace:null,identity:null,mobilePanel:'Conversation'});
    expect(host.failure).not.toHaveBeenCalled();
  });
  it('does not start an old notebook read after a delayed draft flush and newer navigation',async()=>{
    const read=vi.fn(async()=>({...workspace,id:'00000000-0000-4000-8000-000000000062'}));
    const session=new WorkspaceSession({navigation:{read,team:async()=>teamFixture()}});open(session);const host=context(session);
    let finish!:()=>void;session.recovery.scheduledDraftSave.current={run:()=>new Promise<void>(resolve=>{finish=resolve;}),cancel:()=>{},drain:async()=>{}};
    const routing=session.navigation.applyRoute({page:'notebook',workspaceId:'00000000-0000-4000-8000-000000000062'},host);
    await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));session.recovery.scheduledDraftSave.current=null;session.navigation.goHome(host);finish();await routing;
    expect(read).not.toHaveBeenCalled();expect(session.getSnapshot().practicePage).toBe('home');
  });
  it('ignores a rejected old notebook read after the account is cleared',async()=>{
    let reject!:(cause:Error)=>void;const read=vi.fn(()=>new Promise<Workspace>((_resolve,fail)=>{reject=fail;}));
    const session=new WorkspaceSession({navigation:{read,team:async()=>teamFixture()}});open(session);const host=context(session);
    const routing=session.navigation.applyRoute({page:'notebook',workspaceId:'00000000-0000-4000-8000-000000000062'},host);
    await vi.waitFor(()=>expect(reject).toBeTypeOf('function'));session.clear();session.setPracticePage('home');session.setError('New account state');
    reject(new WorkspaceApiError(403));await routing;
    expect(session.getSnapshot()).toMatchObject({practicePage:'home',workspace:null,error:'New account state'});
    expect(host.failure).not.toHaveBeenCalled();expect(host.replaceRoute).not.toHaveBeenCalled();
  });
  it('does not leave a notebook with an unconfirmed request',async()=>{
    const read=vi.fn(),session=new WorkspaceSession({navigation:{read}});open(session);const host=context(session);
    const pending={type:'entry' as const,body:{kind:'scratchpad' as const,content:'Invented note',expected_revision:1,idempotency_key:'invented-exact-key'}};session.setPending(pending);
    await session.navigation.applyRoute({page:'notebook',workspaceId:'00000000-0000-4000-8000-000000000062'},host);
    expect(read).not.toHaveBeenCalled();expect(session.getSnapshot().pending).toBe(pending);expect(host.replaceRoute).toHaveBeenCalledWith(session.navigation.route());
  });
  it('keeps settings and its draft visible until the unsaved-team decision is resolved',async()=>{
    const session=new WorkspaceSession();open(session);session.setSettingsOpen(true);session.setTeamDraft({...teamFixture().configuration,practice_context:'Edited practice'});const host=context(session);
    await session.navigation.applyRoute({page:'home'},host);expect(session.getSnapshot()).toMatchObject({settingsOpen:true,confirmTeamExit:true});expect(host.replaceRoute).toHaveBeenCalledWith(session.navigation.route());
    session.setTeamDraft(teamFixture().configuration);session.team.finishExit();expect(session.getSnapshot()).toMatchObject({practicePage:'home',settingsOpen:false});
  });
  it('keeps the recorder mounted while Home merely minimizes it',()=>{
    const session=new WorkspaceSession();open(session);const host=context(session);const generation=session.generation.current;
    session.navigation.goHome(host);expect(host.minimizeRecording).toHaveBeenCalledOnce();expect(session.generation.current).toBe(generation);expect(session.getSnapshot().workspace).toBe(workspace);
  });
  it('does not navigate during a locked source or capture review',()=>{
    const session=new WorkspaceSession();open(session);const host={...context(session),captureDraftLocked:true};session.navigation.goHome(host);
    expect(session.getSnapshot().practicePage).toBe('notebook');expect(host.minimizeRecording).not.toHaveBeenCalled();
  });
});

async function historyFixture(){
  const api={read:vi.fn(async()=>({contract_version:1 as const,as_of:new Date().toISOString(),rows:[],next_cursor:null})),mark:vi.fn(async()=>({contract_version:1 as const,marker_version:1,manual_unread:false,seen_watermark:null}))};
  const read=vi.fn(async()=>workspace),session=new WorkspaceSession({presentation:{enabled:true,phone:true},conversations:api,conversationRead:read});open(session);
  const host=context(session),journal=new DraftJournal(await memoryDraftStorage()({scope:'a'.repeat(64)}));session.recovery.journal.current={scope:'a'.repeat(64),serverScope:'b'.repeat(64),value:journal};
  const conversation:ConversationHost={identity:authenticated,journal,scope:'a'.repeat(64),current:()=>true,blocked:()=>!!session.getSnapshot().pending||!!session.getSnapshot().privateRecordingEntry||session.getSnapshot().privateRecordingBusy,authorize:vi.fn(async()=>{}),navigate:target=>session.navigation.applyRoute(target,host),failure:vi.fn()};
  return {session,host,journal,conversation,api,read};
}
describe('browser and native history navigation',()=>{
  it('retains separate bot drafts through same-notebook back and forward without replacing the workspace lifetime',async()=>{
    const f=await historyFixture(),generation=f.session.generation.current;
    f.session.models.updateThought('Keep these Chief directions.');
    await f.session.navigation.followHistory({page:'notebook',workspaceId:workspace.id,helper:'follow_up',material:'Conversation'},f.host,f.conversation);
    expect(f.session.getSnapshot()).toMatchObject({selected:'follow_up',thought:'',conversationBusy:false});f.session.models.updateThought('Separate Follow-up directions.');
    await f.session.navigation.followHistory({page:'notebook',workspaceId:workspace.id,helper:'chief',material:'Conversation'},f.host,f.conversation);
    expect(f.session.getSnapshot().thought).toBe('Keep these Chief directions.');
    await f.session.navigation.followHistory({page:'notebook',workspaceId:workspace.id,helper:'follow_up',material:'Conversation'},f.host,f.conversation);
    expect(f.session.getSnapshot().thought).toBe('Separate Follow-up directions.');expect(f.session.generation.current).toBe(generation);expect(f.host.openPrivateNotebook).not.toHaveBeenCalled();
    expect(await f.journal.load(editorAddress(workspace.id,'conversation:chief'))).toMatchObject({data:{text:'Keep these Chief directions.'}});
  });
  it.each(['home','work','visits','settings','notebook'] as const)('restores the current route for a %s history target while an exact request is unconfirmed',async page=>{
    const f=await historyFixture(),pending={type:'entry' as const,body:{kind:'scratchpad' as const,content:'Retained exact text',expected_revision:1,idempotency_key:'retained-key'}};
    f.session.setPending(pending);f.session.models.updateThought('Chief only');const before=f.session.navigation.route();
    expect(await f.session.navigation.followHistory({page,...(page==='notebook'?{workspaceId:workspace.id,helper:'follow_up'}:{})},f.host,f.conversation)).toBe(false);
    expect(f.session.navigation.route()).toEqual(before);expect(f.host.replaceRoute).toHaveBeenCalledWith(before);expect(f.session.getSnapshot().pending).toBe(pending);expect(f.session.getSnapshot().thought).toBe('Chief only');expect(f.read).not.toHaveBeenCalled();expect(f.api.mark).not.toHaveBeenCalled();
  });
  it('restores the original bot and route if the destination read fails before its draft can be restored',async()=>{
    const f=await historyFixture();f.session.models.updateThought('Retain the Chief draft on failure.');const before=f.session.navigation.route();f.read.mockRejectedValueOnce(new Error('Synthetic unavailable read'));
    const exposed:string[]=[];const stop=f.session.subscribe(()=>{const live=f.session.getSnapshot();if(!live.conversationBusy&&live.selected==='follow_up'&&live.thought)exposed.push(live.thought);});
    expect(await f.session.navigation.followHistory({page:'notebook',workspaceId:workspace.id,helper:'follow_up',material:'Conversation'},f.host,f.conversation)).toBe(false);
    expect(f.session.navigation.route()).toEqual(before);expect(f.session.getSnapshot()).toMatchObject({thought:'Retain the Chief draft on failure.',conversationBusy:false});expect(f.host.replaceRoute).toHaveBeenCalledWith(before);expect(f.api.mark).not.toHaveBeenCalled();expect(exposed).toEqual([]);stop();
  });
  it('resumes through the conversation controller after the unsaved Settings decision',async()=>{
    const f=await historyFixture();f.session.models.updateThought('Chief draft retained through Settings.');f.session.setSettingsOpen(true);f.session.setTeamDraft({...teamFixture().configuration,practice_context:'Edited practice'});
    expect(await f.session.navigation.followHistory({page:'notebook',workspaceId:workspace.id,helper:'follow_up',material:'Conversation'},f.host,f.conversation)).toBe(false);
    expect(f.session.getSnapshot()).toMatchObject({settingsOpen:true,confirmTeamExit:true,selected:'chief'});expect(f.read).not.toHaveBeenCalled();
    f.session.setTeamDraft(teamFixture().configuration);f.session.team.finishExit();await vi.waitFor(()=>expect(f.session.getSnapshot()).toMatchObject({settingsOpen:false,selected:'follow_up',conversationBusy:false,thought:''}));
    expect(await f.journal.load(editorAddress(workspace.id,'conversation:chief'))).toMatchObject({data:{text:'Chief draft retained through Settings.'}});
  });
  it('does not replace a newer route after an opened conversation waits for its read-marker response',async()=>{
    const f=await historyFixture();let finish!:()=>void;f.api.mark.mockImplementationOnce(()=>new Promise(resolve=>{finish=()=>resolve({contract_version:1,marker_version:1,manual_unread:false,seen_watermark:null});}));
    const pending=f.session.navigation.followHistory({page:'notebook',workspaceId:workspace.id,helper:'follow_up',material:'Review'},f.host,f.conversation);await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));
    f.session.navigation.goHome(f.host);finish();expect(await pending).toBe(false);expect(f.session.getSnapshot().practicePage).toBe('home');expect(f.session.getSnapshot().mobilePanel).toBe('Conversation');
  });
  it('does not roll back a newer navigation when the destination read finishes late',async()=>{
    const f=await historyFixture();f.session.models.updateThought('Retained Chief text.');let finish!:(value:Workspace)=>void;f.read.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
    const pending=f.session.navigation.followHistory({page:'notebook',workspaceId:workspace.id,helper:'follow_up',material:'Review'},f.host,f.conversation);await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));
    f.session.navigation.goHome(f.host);finish(workspace);expect(await pending).toBe(false);expect(f.session.getSnapshot().practicePage).toBe('home');expect(f.api.mark).not.toHaveBeenCalled();expect(f.host.replaceRoute).toHaveBeenLastCalledWith(f.session.navigation.route());
  });
  it('keeps a steady recorder while returning Home, but rejects changing its bot/context and all transitions',async()=>{
    const f=await historyFixture(),generation=f.session.generation.current;f.session.setPrivateRecordingBusy(true);
    expect(await f.session.navigation.followHistory({page:'notebook',workspaceId:workspace.id,helper:'follow_up'},f.host,f.conversation)).toBe(false);
    expect(await f.session.navigation.followHistory({page:'home'},f.host,f.conversation)).toBe(true);expect(f.host.minimizeRecording).toHaveBeenCalledOnce();expect(f.session.getSnapshot().privateRecordingBusy).toBe(true);expect(f.session.generation.current).toBe(generation);expect(f.session.getSnapshot().workspace).toBe(workspace);
    f.session.setRecordingTransition(true);expect(await f.session.navigation.followHistory({page:'notebook',workspaceId:workspace.id,helper:'chief'},f.host,f.conversation)).toBe(false);expect(f.session.getSnapshot().practicePage).toBe('home');
  });
});


it('keeps a retained save and current route on Home until that exact operation is settled',()=>{
  const session=new WorkspaceSession();open(session);const host=context(session);
  const pending={type:'entry' as const,body:{kind:'scratchpad' as const,content:'Exact retained note',expected_revision:1,idempotency_key:'invented-retained-note'}};
  session.setPending(pending);session.models.updateThought('Keep this independent Chief draft');
  const before=session.navigation.route(),sequence=session.navigation.sequence.current;
  const flush=vi.fn(async()=>{});session.recovery.scheduledDraftSave.current={run:flush,cancel:()=>{},drain:async()=>{}};
  session.navigation.goHome(host);
  expect(session.navigation.route()).toEqual(before);expect(session.navigation.sequence.current).toBe(sequence);
  expect(session.getSnapshot().pending).toBe(pending);expect(session.getSnapshot().thought).toBe('Keep this independent Chief draft');
  expect(host.minimizeRecording).not.toHaveBeenCalled();expect(flush).not.toHaveBeenCalled();
  session.setPending(null);session.navigation.goHome(host);
  expect(session.getSnapshot().practicePage).toBe('home');expect(session.getSnapshot().thought).toBe('Keep this independent Chief draft');
  expect(host.minimizeRecording).toHaveBeenCalledOnce();expect(flush).toHaveBeenCalledOnce();
});
