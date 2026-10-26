// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {WorkspaceSession} from './workspace-session';
import {DraftJournal,editorAddress} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import {teamFixture} from '../team-setup-test-fixture';
import type {ConversationHost} from './conversations';
import type {SourceContext,SourceDependencies} from './sources';
import type {CalendarSavedSource} from '../calendar-import-recovery';
import {calScope,calVisit,calUuid,calImported,calReviewBody,calReviewResult} from '../calendar-import-fixtures.test-support';
import {WorkspaceApiError} from '../workspace-api';
async function fixture(deps:SourceDependencies={}){
 const verified=await calImported(),result=await calReviewResult(verified,await calReviewBody(verified)),workspace={...result.workspace,appointment_id:calUuid(900)};
 const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
 const session=new WorkspaceSession({sources:{read:async()=>workspace,...deps},conversationRead:async()=>workspace,conversations:{read:vi.fn(async()=>({contract_version:1 as const,as_of:'2026-10-25T12:00:00Z',rows:[],next_cursor:null})),mark:vi.fn(async()=>({contract_version:1 as const,marker_version:1,manual_unread:false,seen_watermark:null}))}});
 session.setWorkspace(workspace);session.setTeam(teamFixture());session.setIdentity(identity);session.setSelected('chief');session.setPracticePage('notebook');
 const journal=new DraftJournal(await memoryDraftStorage()({scope:'invented'}));session.recovery.journal.current={scope:'invented',serverScope:'a'.repeat(64),value:journal};
 const host:ConversationHost={identity,journal,scope:'invented',current:()=>session.getSnapshot().identity===identity,blocked:()=>session.getSnapshot().busy||!!session.getSnapshot().pending,authorize:vi.fn(async()=>{}),navigate:vi.fn(async route=>{session.navigation.sequence.current++;session.setSelected(route.helper!);session.setSettingsOpen(false);session.setPracticeOpen(false);session.setPracticePage('notebook');}),failure:vi.fn()};
 const context:SourceContext={authenticated:identity,conversationHost:host,locked:false,connectionNavigationLocked:false,captureNavigationLocked:false,captureDraftLocked:false,connectionEditorsLocked:false,activityBusy:false,accessBusy:false,scribeSourceBusy:false,schedulingPatientBusy:false,accountAccess:null,failure:vi.fn(),focusQuestion:vi.fn()};
 const saved:CalendarSavedSource={workspace_id:calScope.workspace_id,entry_id:result.entry_id,entry_revision:result.entry_revision,source_sha256:result.source.source_sha256,content_sha256:result.source.content_sha256,request_sha256:result.request_sha256,source_withheld:false};
 return {session,workspace,journal,host,context,saved};
}
describe('shared imported calendar Chief draft preparation',()=>{
 it('preserves both specialist and retained Chief directions and sends no model request',async()=>{const f=await fixture(),send=vi.spyOn(f.session.models,'save');f.session.models.updateThought('Retained Chief instructions');await f.session.conversations.observe(f.host);await f.session.conversations.open(calVisit.id,'follow_up',f.host);f.session.models.updateThought('Specialist directions stay here');await f.session.sources.prepareCalendarImport(f.context,f.saved);
 expect(f.session.getSnapshot().thought).toContain('Retained Chief instructions\n\nReview the human-selected imported calendar');expect(f.session.getSnapshot().thought).not.toContain('Specialist directions');expect(f.session.getSnapshot().selectedSource).toBe(f.saved.entry_id);expect(await f.journal.load(editorAddress(calVisit.id,'conversation:follow_up'))).toMatchObject({data:{text:'Specialist directions stay here'}});expect(send).not.toHaveBeenCalled();expect(f.context.focusQuestion).toHaveBeenCalledOnce();});
 it('does not erase a retained saved-note task while preparing a new imported calendar source',async()=>{const f=await fixture();const task={contract:'chief-note-task.compose.v1' as const,note_id:calUuid(600),note_version:1,content_hash:'a'.repeat(64),source_fingerprint:'b'.repeat(64)};await f.journal.load(editorAddress(calVisit.id,'conversation:chief'));await f.journal.persist(editorAddress(calVisit.id,'conversation:chief'),{kind:'editor',workspaceId:calVisit.id,editor:'conversation:chief',pending:null,data:{text:'Directions for the saved note',noteTask:task}});await f.session.sources.prepareCalendarImport(f.context,f.saved);expect(f.session.getSnapshot().thought).toBe('Directions for the saved note');expect(f.session.getSnapshot().phoneNoteTask?.selection.note_id).toBe(task.note_id);expect(f.session.getSnapshot().error).toContain('Finish or close the saved-note draft');expect(f.context.focusQuestion).not.toHaveBeenCalled();});
 it.each(['withheld','hash','foreign-workspace'] as const)('refuses %s saved source without appending instructions',async kind=>{const f=await fixture();f.session.models.updateThought('Keep these directions');const source={...f.saved,...(kind==='withheld'?{source_withheld:true}:kind==='hash'?{content_sha256:'f'.repeat(64)}:{workspace_id:calUuid(999)})};await f.session.sources.prepareCalendarImport(f.context,source);expect(f.session.getSnapshot().thought).toBe('Keep these directions');expect(f.context.failure).toHaveBeenCalledOnce();});
 it('refuses a source whose current server projection is unavailable',async()=>{const f=await fixture({read:async()=>({...f.workspace,entries:f.workspace.entries.map(e=>({...e,calendar_import_source_state:'unavailable' as const,content:''}))})});await f.session.sources.prepareCalendarImport(f.context,f.saved);expect(f.session.getSnapshot().thought).toBe('');expect(f.context.failure).toHaveBeenCalledWith(expect.any(WorkspaceApiError));});
 it('does not append after a newer composer edit wins during source hashing',async()=>{let release!:(s:string)=>void;const f=await fixture({hash:()=>new Promise(r=>{release=r;})}),preparing=f.session.sources.prepareCalendarImport(f.context,f.saved);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));f.session.models.updateThought('New directions while checking');release(f.saved.content_sha256);await preparing;expect(f.session.getSnapshot().thought).toBe('New directions while checking');expect(f.context.focusQuestion).not.toHaveBeenCalled();});
 it('does not focus a newer route when retained Chief draft persistence settles',async()=>{const f=await fixture(),original=f.journal.persist.bind(f.journal);let release!:()=>void;vi.spyOn(f.journal,'persist').mockImplementation(async(address,draft)=>{if(draft?.kind==='editor'&&JSON.stringify(draft.data).includes('human-selected imported calendar'))await new Promise<void>(r=>{release=r;});return original(address,draft);});const preparing=f.session.sources.prepareCalendarImport(f.context,f.saved);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));f.session.navigation.sequence.current++;f.session.setPracticePage('home');release();await preparing;expect(f.context.focusQuestion).not.toHaveBeenCalled();});
 it('requires the shared conversation journal instead of moving specialist text into Chief',async()=>{const f=await fixture();f.session.setSelected('follow_up');f.session.models.updateThought('Unsent specialist directions');await f.session.sources.prepareCalendarImport({...f.context,conversationHost:null},f.saved);expect(f.session.getSnapshot()).toMatchObject({selected:'follow_up',thought:'Unsent specialist directions'});expect(f.context.failure).toHaveBeenCalledOnce();});
});


it('retains directions and the calendar import task on a blocked Back, then restores its origin',async()=>{const f=await fixture();f.session.models.updateThought('Retained calendar directions');expect(await f.session.sources.openCalendarImport(f.context,'sources')).toBe(true);expect(f.session.getSnapshot().calendarImportReview).toMatchObject({open:true,origin:'sources'});expect(f.session.sources.closeCalendarImport({...f.context,connectionNavigationLocked:true})).toBe(false);expect(f.session.sources.closeCalendarImport(f.context)).toBe(true);expect(f.session.getSnapshot()).toMatchObject({thought:'Retained calendar directions',mobilePanel:'Sources',calendarImportReview:{open:false}});expect(await f.journal.load(editorAddress(calVisit.id,'conversation:chief'))).toMatchObject({data:{text:'Retained calendar directions'}});});
it('does not open an import after a new composer edit wins during retention',async()=>{const f=await fixture();let release!:()=>void;vi.mocked(f.host.authorize).mockImplementationOnce(()=>new Promise<void>(r=>{release=r;}));const opening=f.session.sources.openCalendarImport(f.context,'conversation');await vi.waitFor(()=>expect(release).toBeTypeOf('function'));f.session.models.updateThought('New directions');release();expect(await opening).toBe(false);expect(f.session.getSnapshot().calendarImportReview).toBeNull();});


it.each(['withheld','deleted','changed'] as const)('preserves the draft when the source is %s during final authorization',async change=>{
 const f=await fixture(),previousSource=calUuid(979),text='Keep my existing Chief directions';
 f.session.models.updateThought(text);await f.session.conversations.observe(f.host);
 f.session.setSelectedSource(previousSource);
 f.session.setCalendarImportReview({identity:f.host.identity,generation:f.session.generation.current,workspaceId:f.workspace.id,open:true,origin:'sources'});
 let release!:()=>void,paused=false;
 vi.mocked(f.host.authorize).mockImplementation(async()=>{if(f.session.getSnapshot().busy&&!paused){paused=true;await new Promise<void>(r=>{release=r;});}});
 const preparing=f.session.sources.prepareCalendarImport(f.context,f.saved);
 await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
 const entries=change==='deleted'?[]:f.workspace.entries.map(entry=>entry.id===f.saved.entry_id?{...entry,
  ...(change==='withheld'?{calendar_import_source_state:'unavailable' as const,content:''}:{content:entry.content+' changed while authorizing'})}:entry);
 f.session.sources.receive({...f.workspace,entries});release();await preparing;
 expect(f.session.getSnapshot()).toMatchObject({thought:text,selectedSource:previousSource,calendarImportReview:{open:true}});
 expect(f.context.failure).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({status:409,code:'calendar_import_source_changed'}));
 expect(f.context.focusQuestion).not.toHaveBeenCalled();
 expect(await f.journal.load(editorAddress(calVisit.id,'conversation:chief'))).toMatchObject({data:{text}});
});


describe('calendar import from the connection catalog',()=>{
 it('retains the draft and returns to connections after a blocked Back is resolved',async()=>{
  const f=await fixture();f.session.models.updateThought('Keep my calendar directions');f.session.setSettingsEntry('connections');f.session.setSettingsOpen(true);
  expect(await f.session.sources.openCalendarImport(f.context,'connections')).toBe(true);
  expect(f.session.getSnapshot()).toMatchObject({settingsOpen:false,calendarImportReview:{open:true,origin:'connections'},ehrReview:null});
  expect(f.session.sources.closeCalendarImport({...f.context,connectionNavigationLocked:true})).toBe(false);
  expect(f.session.getSnapshot().calendarImportReview?.open).toBe(true);
  expect(f.session.sources.closeCalendarImport(f.context)).toBe(true);
  expect(f.session.getSnapshot()).toMatchObject({settingsOpen:true,settingsEntry:'connections',thought:'Keep my calendar directions',calendarImportReview:{open:false}});
  expect(await f.journal.load(editorAddress(calVisit.id,'conversation:chief'))).toMatchObject({data:{text:'Keep my calendar directions'}});
 });
 it('keeps the catalog and draft when authorization fails',async()=>{
  const f=await fixture();f.session.setSettingsEntry('connections');f.session.setSettingsOpen(true);f.session.models.updateThought('Keep these directions');vi.mocked(f.host.authorize).mockRejectedValueOnce(new WorkspaceApiError(403,'not_authorized'));
  expect(await f.session.sources.openCalendarImport(f.context,'connections')).toBe(false);
  expect(f.session.getSnapshot()).toMatchObject({settingsOpen:true,settingsEntry:'connections',calendarImportReview:null,thought:'Keep these directions'});expect(f.context.failure).toHaveBeenCalledOnce();
 });
 it('does not open an old account catalog request after account replacement',async()=>{
  const f=await fixture();f.session.setSettingsEntry('connections');f.session.setSettingsOpen(true);let release!:()=>void;vi.mocked(f.host.authorize).mockImplementationOnce(()=>new Promise<void>(resolve=>{release=resolve;}));
  const opening=f.session.sources.openCalendarImport(f.context,'connections');await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
  f.session.setIdentity({mode:'clerk_jwt',getToken:async()=>null});release();expect(await opening).toBe(false);expect(f.session.getSnapshot().calendarImportReview).toBeNull();
 });
});
