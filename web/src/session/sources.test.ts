// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {teamFixture} from '../team-setup-test-fixture';
import {vendorSha256} from '../vendor-contract';
import type {AuthenticatedWorkspaceIdentity,Workspace} from '../workspace-api';
import type {GoogleMessageSaved} from '../google-message-recovery';
import type {SourceContext,SourceDependencies} from './sources';
import {WorkspaceSession} from './workspace-session';

async function fixture(deps:SourceDependencies={}){
  const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null},content='Invented selected email';
  const workspace:Workspace={id:'invented-workspace',appointment_id:null,label:'Invented notebook',revision:2,work_candidates:[],entries:[{id:'invented-source',revision:2,kind:'google_message',content,source_label:'Invented email',origin:'human',ticket:null,created_at:'2026-10-23T12:00:00Z',google_source_state:'current'}]};
  const source:GoogleMessageSaved={workspace_id:workspace.id,entry_id:'invented-source',entry_revision:2,source_sha256:'a'.repeat(64),content_sha256:await vendorSha256(new TextEncoder().encode(content)),request_sha256:'b'.repeat(64),source_withheld:false};
  const session=new WorkspaceSession({sources:{read:async()=>workspace,...deps}});session.setWorkspace(workspace);session.setTeam(teamFixture());session.setIdentity(authenticated);
  const context:SourceContext={authenticated,locked:false,connectionNavigationLocked:false,captureNavigationLocked:false,captureDraftLocked:false,connectionEditorsLocked:false,activityBusy:false,accessBusy:false,scribeSourceBusy:false,schedulingPatientBusy:false,accountAccess:null,failure:vi.fn(),focusQuestion:vi.fn()};
  return {session,context,source,workspace};
}
describe('shared selected-source preparation',()=>{
  it('verifies the selected saved source and appends editable directions without sending',async()=>{
    const f=await fixture(),save=vi.spyOn(f.session.models,'save');f.session.setThought('Invented existing directions');await f.session.sources.prepareGoogle(f.context,f.source);
    expect(f.session.getSnapshot()).toMatchObject({selected:'chief',selectedSource:f.source.entry_id});expect(f.session.getSnapshot().thought).toContain('Invented existing directions\n\nReview the human-selected email source');expect(save).not.toHaveBeenCalled();expect(f.context.focusQuestion).toHaveBeenCalledOnce();
  });
  it('refuses a changed hash or a revoked selected source',async()=>{
    const f=await fixture();await f.session.sources.prepareGoogle(f.context,{...f.source,content_sha256:'0'.repeat(64)});await f.session.sources.prepareGoogle(f.context,{...f.source,source_withheld:true});
    expect(f.context.failure).toHaveBeenCalledTimes(2);expect(f.session.getSnapshot().thought).toBe('');expect(f.context.focusQuestion).not.toHaveBeenCalled();
  });
  it('does not apply a hash result after the session changes',async()=>{
    let finish!:(value:string)=>void;const hash=vi.fn(()=>new Promise<string>(resolve=>{finish=resolve;})),f=await fixture({hash});
    const preparing=f.session.sources.prepareGoogle(f.context,f.source);await vi.waitFor(()=>expect(hash).toHaveBeenCalledOnce());f.session.clear();finish(f.source.content_sha256);await preparing;
    expect(f.session.getSnapshot()).toMatchObject({workspace:null,thought:''});expect(f.context.focusQuestion).not.toHaveBeenCalled();
  });
  it('retains an unsaved notebook edit when refreshed sources also change the saved notebook',async()=>{
    const f=await fixture();f.session.setNote('Invented unsaved notes');f.session.sources.receive({...f.workspace,revision:3,entries:[...f.workspace.entries,{id:'new-note',revision:3,kind:'scratchpad',content:'Another saved note',source_label:null,origin:'human',ticket:null,created_at:'2026-10-23T12:00:00Z'}]});
    expect(f.session.getSnapshot()).toMatchObject({note:'Invented unsaved notes',conflict:true});
  });
});
