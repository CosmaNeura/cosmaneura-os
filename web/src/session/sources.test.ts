// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {teamFixture,teamUuid as uuid} from '../team-setup-test-fixture';
import {vendorSha256} from '../vendor-contract';
import type {AuthenticatedWorkspaceIdentity,Workspace} from '../workspace-api';
import type {GoogleMessageSaved} from '../google-message-recovery';
import type {SourceContext,SourceDependencies} from './sources';
import {DraftJournal,editorAddress} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import type {ConversationHost} from './conversations';
import {WorkspaceSession} from './workspace-session';

async function fixture(deps:SourceDependencies={},kind:'google_message'|'microsoft_message'='google_message'){
  const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null},content='Invented selected email';
  const workspace:Workspace={id:uuid(71),appointment_id:null,label:'Invented notebook',revision:2,work_candidates:[],entries:[{id:uuid(72),revision:2,kind:'google_message',content,source_label:'Invented email',origin:'human',ticket:null,created_at:'2026-10-23T12:00:00Z',google_source_state:'current'}]};
  const source:GoogleMessageSaved={workspace_id:workspace.id,entry_id:uuid(72),entry_revision:2,source_sha256:'a'.repeat(64),content_sha256:await vendorSha256(new TextEncoder().encode(content)),request_sha256:'b'.repeat(64),source_withheld:false};
  if(kind==='microsoft_message'){workspace.appointment_id=uuid(73);workspace.entries[0]={...workspace.entries[0],kind,google_source_state:undefined,microsoft_source_state:'current'};}
  const session=new WorkspaceSession({sources:{read:async()=>workspace,...deps},conversationRead:async()=>workspace});session.setWorkspace(workspace);session.setTeam(teamFixture());session.setIdentity(authenticated);session.setSelected('chief');session.setPracticePage('notebook');
  const journal=new DraftJournal(await memoryDraftStorage()({scope:'invented'}));session.recovery.journal.current={scope:'invented',serverScope:'a'.repeat(64),value:journal};
  const host:ConversationHost={identity:authenticated,journal,scope:'invented',current:()=>session.getSnapshot().identity===authenticated,blocked:()=>session.getSnapshot().busy||!!session.getSnapshot().pending,authorize:vi.fn(async()=>{}),navigate:vi.fn(async route=>{session.navigation.sequence.current++;session.setSelected(route.helper!);session.setSettingsOpen(false);session.setPracticeOpen(false);session.setPracticePage('notebook');}),failure:vi.fn()};
  const context:SourceContext={authenticated,conversationHost:host,locked:false,connectionNavigationLocked:false,captureNavigationLocked:false,captureDraftLocked:false,connectionEditorsLocked:false,activityBusy:false,accessBusy:false,scribeSourceBusy:false,schedulingPatientBusy:false,accountAccess:null,failure:vi.fn(),focusQuestion:vi.fn()};
  return {session,context,source,workspace,journal,host};
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

it('prepares a reviewed Outlook source in the retained Chief draft without moving specialist text or sending',async()=>{
 const f=await fixture({},'microsoft_message'),save=vi.spyOn(f.session.models,'save');f.session.models.updateThought('Existing Chief directions');await f.session.conversations.observe(f.host);
 await f.session.conversations.open(f.workspace.id,'follow_up',f.host);f.session.models.updateThought('Separate specialist directions');
 await f.session.sources.prepareMicrosoft(f.context,f.source);
 expect(f.session.getSnapshot().thought).toBe('Existing Chief directions\n\nReview the human-selected email source '+f.source.entry_id+' and prepare appropriate private assignments. Preserve the existing clinical note; ask me about missing details before proposing outside actions.');
 expect(await f.journal.load(editorAddress(f.workspace.id,'conversation:follow_up'))).toMatchObject({data:{text:'Separate specialist directions'}});expect(save).not.toHaveBeenCalled();expect(f.context.focusQuestion).toHaveBeenCalledOnce();
});
it('requires Microsoft source custody and refuses Gmail substitution or withdrawn Outlook content',async()=>{
 const gmail=await fixture();gmail.session.models.updateThought('Keep directions');await gmail.session.sources.prepareMicrosoft(gmail.context,gmail.source);
 expect(gmail.session.getSnapshot().thought).toBe('Keep directions');expect(gmail.context.failure).toHaveBeenCalledOnce();
 const outlook=await fixture({},'microsoft_message');outlook.workspace.entries[0].microsoft_source_state='unavailable';await outlook.session.sources.prepareMicrosoft(outlook.context,outlook.source);
 expect(outlook.session.getSnapshot().thought).toBe('');expect(outlook.context.failure).toHaveBeenCalledOnce();
});
it('withholds Outlook draft preparation if access changes while authorization is pending',async()=>{
 const f=await fixture({},'microsoft_message');f.session.models.updateThought('Keep directions');let release!:()=>void;
 // Observe/retain first, so this deferred authorization is the final source check.
 await f.session.conversations.observe(f.host);f.host.authorize=()=>new Promise<void>(resolve=>{release=resolve;});
 const work=f.session.sources.prepareMicrosoft(f.context,f.source);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
 f.session.sources.receive({...f.workspace,entries:f.workspace.entries.map(e=>({...e,microsoft_source_state:'unavailable' as const,content:''}))});release();await work;
 expect(f.session.getSnapshot().thought).toBe('Keep directions');expect(f.context.focusQuestion).not.toHaveBeenCalled();
});

it('preserves a retained Chief saved-note task and the originating specialist draft',async()=>{
 const f=await fixture(),task={contract:'chief-note-task.compose.v1' as const,note_id:uuid(88),note_version:1,content_hash:'a'.repeat(64),source_fingerprint:'b'.repeat(64)};
 await f.journal.load(editorAddress(f.workspace.id,'conversation:chief'));await f.journal.persist(editorAddress(f.workspace.id,'conversation:chief'),{kind:'editor',workspaceId:f.workspace.id,editor:'conversation:chief',pending:null,data:{text:'Chief saved-note directions',noteTask:task}});
 f.session.setSelected('follow_up');f.session.models.updateThought('Keep specialist directions');await f.session.sources.prepareGoogle(f.context,f.source);
 expect(f.session.getSnapshot().thought).toBe('Chief saved-note directions');expect(f.session.getSnapshot().phoneNoteTask?.selection.note_id).toBe(task.note_id);expect(f.session.getSnapshot().error).toContain('Finish or close the saved-note draft');expect(f.context.focusQuestion).not.toHaveBeenCalled();expect(await f.journal.load(editorAddress(f.workspace.id,'conversation:follow_up'))).toMatchObject({data:{text:'Keep specialist directions'}});
});
it('requires the current conversation journal instead of silently transferring a specialist draft',async()=>{const f=await fixture();f.session.setSelected('follow_up');f.session.models.updateThought('Stay in Follow-up');await f.session.sources.prepareGoogle({...f.context,conversationHost:null},f.source);expect(f.session.getSnapshot()).toMatchObject({selected:'follow_up',thought:'Stay in Follow-up'});expect(f.context.failure).toHaveBeenCalledOnce();});
it.each(['edit','navigation','identity'] as const)('fences a later %s while the saved email source is being checked',async change=>{
 let finish!:(value:string)=>void;const f=await fixture({hash:()=>new Promise(r=>{finish=r;})});f.session.models.updateThought('Original Chief');const work=f.session.sources.prepareGoogle(f.context,f.source);await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));
 if(change==='edit')f.session.models.updateThought('Newer Chief edit');else if(change==='navigation'){f.session.navigation.sequence.current++;f.session.setPracticePage('home');}else f.session.setIdentity({mode:'clerk_jwt',getToken:async()=>null});finish(f.source.content_sha256);await work;expect(f.session.getSnapshot().thought).toBe(change==='edit'?'Newer Chief edit':'Original Chief');expect(f.context.focusQuestion).not.toHaveBeenCalled();
});
it('does not focus a newer navigation when appended draft persistence settles',async()=>{
 const f=await fixture(),persist=f.journal.persist.bind(f.journal);let release!:()=>void;vi.spyOn(f.journal,'persist').mockImplementation(async(address,value)=>{if(value?.kind==='editor'&&JSON.stringify(value.data).includes('human-selected email'))await new Promise<void>(r=>{release=r;});return persist(address,value);});
 const work=f.session.sources.prepareGoogle(f.context,f.source);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));f.session.navigation.sequence.current++;f.session.setPracticePage('home');release();await work;expect(f.context.focusQuestion).not.toHaveBeenCalled();
});
it('keeps calendar preparation on the same safe per-bot journal path',async()=>{
 const f=await fixture();f.workspace.entries[0]={...f.workspace.entries[0],kind:'google_calendar',calendar_source_state:'current'};f.session.models.updateThought('Chief calendar directions');await f.session.conversations.observe(f.host);await f.session.conversations.open(f.workspace.id,'follow_up',f.host);f.session.models.updateThought('Separate follow-up directions');await f.session.sources.prepareGoogle(f.context,f.source,'google_calendar');expect(f.session.getSnapshot().thought).toContain('Chief calendar directions\n\nReview the human-selected calendar summary');expect(f.session.getSnapshot().thought).not.toContain('Separate follow-up directions');expect(await f.journal.load(editorAddress(f.workspace.id,'conversation:follow_up'))).toMatchObject({data:{text:'Separate follow-up directions'}});
});
