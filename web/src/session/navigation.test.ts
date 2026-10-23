// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {teamFixture} from '../team-setup-test-fixture';
import type {AuthenticatedWorkspaceIdentity,Workspace} from '../workspace-api';
import type {NavigationContext} from './navigation';
import {WorkspaceSession} from './workspace-session';

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
