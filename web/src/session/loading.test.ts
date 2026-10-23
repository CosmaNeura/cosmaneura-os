// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import type {AuthenticatedWorkspaceIdentity,ProviderTeam,Workspace} from '../workspace-api';
import {WorkspaceApiError} from '../workspace-api';
import {WorkspaceSession} from './workspace-session';
import type {RefreshContext,OpenContext} from './loading';

const workspace:Workspace={id:'00000000-0000-4000-8000-000000000031',label:'Invented visit',appointment_id:null,revision:3,entries:[],work_candidates:[]};
const team:ProviderTeam={revision:1,recovery_scope:'a'.repeat(64),template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},configuration:{practice_context:'DPC',bots:[{role:'chief',name:'Chief',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[]};
const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
function context():RefreshContext{return {authenticated,failure:vi.fn(),recoverAfterRead:vi.fn(async()=>{}),prepareRecovery:vi.fn(async()=>{}),recordingBlocked:false,invalidateSetup:vi.fn(),invalidatePrep:vi.fn()};}
function opened(session:WorkspaceSession){session.setIdentity(authenticated);session.setWorkspace(workspace);session.setTeam(team);session.setTeamDraft(team.configuration);}
function openContext():OpenContext{return {...context(),locked:false,captureNavigationLocked:false,captureDraftLocked:false,hasUnsavedWork:()=>false,begin:vi.fn(),resetCapture:vi.fn(),focusChief:vi.fn(),focusFax:vi.fn(),showResearch:vi.fn(),afterOpen:vi.fn(),retryRead:vi.fn(async()=>{})};}

describe('shared workspace loading',()=>{
  it('does not replay a notebook-opening write through a general retry',async()=>{
    const open=vi.fn().mockRejectedValue(new Error('Lost response')),session=new WorkspaceSession({loading:{open}}),host=openContext();
    await session.loading.open(host,'invented-appointment');
    expect(open).toHaveBeenCalledOnce();expect(host.failure).toHaveBeenCalledWith(expect.any(Error),host.retryRead);
    await host.retryRead();expect(open).toHaveBeenCalledOnce();
  });
  it('drops a late notebook open after identity invalidation',async()=>{
    let finish!:(result:{identity:AuthenticatedWorkspaceIdentity;workspace:Workspace;team:ProviderTeam})=>void;
    const session=new WorkspaceSession({loading:{open:()=>new Promise(resolve=>{finish=resolve;})}}),host=openContext();
    const opening=session.loading.open(host,'invented-appointment');session.clear();finish({identity:authenticated,workspace,team});await opening;
    expect(session.getSnapshot()).toMatchObject({identity:null,workspace:null});expect(host.recoverAfterRead).not.toHaveBeenCalled();
  });
  it('preserves edited team settings while opening a saved visit',async()=>{
    const session=new WorkspaceSession({loading:{open:async()=>({identity:authenticated,workspace,team})}});opened(session);
    const draft={...team.configuration,practice_context:'Invented unsaved edit'};session.setTeamDraft(draft);session.setEntryIntent('chief');
    const host=openContext();await session.loading.open(host,'invented-appointment');
    expect(session.getSnapshot()).toMatchObject({teamDraft:draft,selected:'chief',practicePage:'notebook'});expect(host.focusChief).toHaveBeenCalledWith(workspace.id,1);
  });
  it('refreshes saved history without replacing working text or team edits',async()=>{
    const latest={...workspace,revision:4},latestTeam={...team,revision:2};
    const session=new WorkspaceSession({loading:{read:async()=>latest,team:async()=>latestTeam}});opened(session);
    const draft={...team.configuration,practice_context:'Edited practice'};session.setTeamDraft(draft);session.setNote('Invented unsaved text');session.setThought('Next question');session.setRecoveryState('failed');
    const host=context();await session.loading.refresh(host);
    expect(session.getSnapshot()).toMatchObject({workspace:latest,team:latestTeam,teamDraft:draft,note:'Invented unsaved text',thought:'Next question',busy:false});
    expect(host.recoverAfterRead).toHaveBeenCalledWith(latestTeam,latest,0,true);expect(host.invalidateSetup).toHaveBeenCalledOnce();
  });
  it('drops a late refresh after the session is cleared',async()=>{
    let finish!:(value:Workspace)=>void;const session=new WorkspaceSession({loading:{read:()=>new Promise(resolve=>{finish=resolve;}),team:async()=>team}});opened(session);
    const host=context(),loading=session.loading.refresh(host);session.clear();finish(workspace);await loading;
    expect(session.getSnapshot()).toMatchObject({workspace:null,team:null,busy:false});expect(host.recoverAfterRead).not.toHaveBeenCalled();
  });
  it('does not refresh while a recording or exact request is unresolved',async()=>{
    const read=vi.fn();const session=new WorkspaceSession({loading:{read}});opened(session);
    await session.loading.refresh({...context(),recordingBlocked:true});
    session.setPending({type:'entry',body:{kind:'scratchpad',content:'Invented',expected_revision:3,idempotency_key:'invented-exact-key'}});
    await session.loading.refresh(context());expect(read).not.toHaveBeenCalled();
  });
  it('rejects a handoff read older than the draft being reviewed',async()=>{
    const session=new WorkspaceSession({loading:{read:async()=>({...workspace,revision:2}),team:async()=>team}});opened(session);
    const host=context();await expect(session.loading.refreshHandoff({...host,blocked:false})).rejects.toMatchObject({status:503});
    expect(session.getSnapshot().workspace).toBe(workspace);expect(host.failure).toHaveBeenCalledOnce();
  });
  it('retains exact pending recovery when rechecking local storage',async()=>{
    const session=new WorkspaceSession({loading:{team:async()=>team}});opened(session);session.setRecoveryState('failed');
    const pending={type:'entry' as const,body:{kind:'scratchpad' as const,content:'Invented',expected_revision:3,idempotency_key:'invented-exact-key'}};session.setPending(pending);
    const host=context();await session.loading.recheckRecovery(host);
    expect(host.prepareRecovery).toHaveBeenCalledWith(team,workspace,0,false);expect(session.getSnapshot().pending).toBe(pending);
  });
  it('does not navigate back to visits after a newer navigation wins',async()=>{
    let finish!:(rows:[])=>void,nav=0;const session=new WorkspaceSession({loading:{catalog:()=>new Promise(resolve=>{finish=resolve;})}});
    const show=vi.fn(),host={authenticated,failure:vi.fn(),retry:vi.fn(async()=>{}),begin:()=>++nav,currentNavigation:()=>nav,show,refreshRecordings:vi.fn()};
    const loading=session.loading.catalog(host);nav++;finish([]);await loading;
    expect(show).toHaveBeenCalledOnce();expect(session.getSnapshot()).toMatchObject({encounters:null,homeBusy:false});
  });
  it('withholds a private notebook returned for another owner',async()=>{
    const session=new WorkspaceSession(),host={...context(),beforeOpen:vi.fn(),show:vi.fn()};
    await expect(session.loading.openPrivate({identity:{mode:'clerk_jwt',getToken:async()=>null},workspace,team},host)).rejects.toBeInstanceOf(WorkspaceApiError);
    expect(session.getSnapshot().workspace).toBeNull();expect(host.show).not.toHaveBeenCalled();
  });
});
