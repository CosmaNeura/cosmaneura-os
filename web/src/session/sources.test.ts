// @vitest-environment node
import {afterEach,describe,expect,it,vi} from 'vitest';
import {teamFixture,teamUuid as uuid} from '../team-setup-test-fixture';
import {vendorSha256} from '../vendor-contract';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from '../workspace-api';
import {efaxInboundApi,type EFaxPending,type EFaxReceipt} from '../efax-inbound-api';
import {efaxPdf,efaxReceipt,efaxScope} from '../efax-inbound-fixtures.test-support';
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

describe('reopening the exact saved received-fax PDF',()=>{
 afterEach(()=>vi.restoreAllMocks());
 async function faxFixture(deps:SourceDependencies={}){
  const request:Extract<EFaxPending,{kind:'acquire'}>={kind:'acquire',request:{idempotency_key:uuid(91),ticket_id:uuid(92),revision_id:uuid(93),expected_version:2,approval_sha256:'e'.repeat(64)}};
  const receipt:EFaxReceipt={...await efaxReceipt(request),state:'acquired',content_available:true,source_withheld:false,document:{sha256:await vendorSha256(efaxPdf),byte_length:efaxPdf.length,pages:1}};
  const account={contract_version:1 as const,box_id:efaxScope.box_id,actor_id:efaxScope.owner_id,recovery_scope:'c'.repeat(64)};
  const authorize=vi.fn(async()=>{}),accountRead=vi.fn(async()=>account),resolveEFax=vi.fn<typeof efaxInboundApi.resolve>(async()=>receipt),documentEFax=vi.fn<typeof efaxInboundApi.document>(async()=>new Uint8Array(efaxPdf));
  const f=await fixture({accountRead,resolveEFax,documentEFax,...deps});f.workspace.appointment_id=uuid(73);f.context.accountAccess={authorize};f.session.setMobilePanel('Sources');f.session.setPanel('Sources');
  const document={operation_id:receipt.operation_id!,document_sha256:receipt.document!.sha256,pages:1};
  f.session.setFaxSourceOffer({identity:f.context.authenticated!,generation:f.session.generation.current,workspaceId:f.workspace.id,document,request});
  return {...f,request,receipt,account,authorize,accountRead,resolveEFax,documentEFax,offer:f.session.getSnapshot().faxSourceOffer!};
 }
 it('reopens only the already acquired exact PDF without acquiring, saving or changing the Chief draft',async()=>{
  const f=await faxFixture(),controller=new AbortController(),command=vi.spyOn(efaxInboundApi,'command');f.session.setThought('Keep exact Chief directions');const before=f.session.getSnapshot();
  expect(await f.session.sources.loadFaxDocument(f.context,controller.signal)).toEqual(efaxPdf);
  expect(f.resolveEFax).toHaveBeenCalledExactlyOnceWith(f.context.authenticated,efaxScope,f.request,controller.signal);
  expect(f.documentEFax).toHaveBeenCalledExactlyOnceWith(f.context.authenticated,f.receipt,controller.signal);
  expect(f.authorize).toHaveBeenCalledTimes(2);expect(f.accountRead).toHaveBeenCalledTimes(2);expect(f.accountRead).toHaveBeenNthCalledWith(1,f.context.authenticated,controller.signal);expect(f.accountRead).toHaveBeenNthCalledWith(2,f.context.authenticated,controller.signal);
  expect(command).not.toHaveBeenCalled();expect(f.session.getSnapshot()).toBe(before);
 });
 it.each(['missing','withheld','unconfirmed','hash','operation','pages','account'] as const)('withholds a %s saved receipt before loading any PDF',async change=>{
  const f=await faxFixture();
  if(change==='missing'){const missing={contract_version:1 as const,scope:efaxScope,idempotency_key:f.request.request.idempotency_key,kind:'acquire' as const,state:'not_found' as const,retry_allowed:false,content_available:false,source_withheld:false,document:null};f.resolveEFax.mockResolvedValue(missing);}
  else if(change==='withheld')f.receipt.source_withheld=true;
  else if(change==='unconfirmed')f.receipt.state='outcome_unconfirmed';
  else if(change==='hash')f.receipt.document!.sha256='f'.repeat(64);
  else if(change==='operation')f.receipt.operation_id=uuid(94);
  else if(change==='pages')f.receipt.document!.pages=2;
  else f.receipt.scope={...efaxScope,owner_id:uuid(95)};
  expect(await f.session.sources.loadFaxDocument(f.context)).toBeNull();expect(f.documentEFax).not.toHaveBeenCalled();
 });
 const phases=['initial authorization','account lookup','saved result','document load','final authorization','final account lookup'] as const;
 it.each(phases)('rejects the old offer after same-visit replacement during %s',async phase=>{
  const f=await faxFixture();let release!:()=>void;const pause=()=>new Promise<void>(resolve=>{release=resolve;});
  if(phase==='initial authorization')f.authorize.mockImplementationOnce(pause);
  else if(phase==='account lookup')f.accountRead.mockImplementationOnce(async()=>{await pause();return f.account;});
  else if(phase==='saved result')f.resolveEFax.mockImplementationOnce(async()=>{await pause();return f.receipt;});
  else if(phase==='document load')f.documentEFax.mockImplementationOnce(async()=>{await pause();return new Uint8Array(efaxPdf);});
  else if(phase==='final authorization')f.authorize.mockResolvedValueOnce(undefined).mockImplementationOnce(pause);
  else f.accountRead.mockResolvedValueOnce(f.account).mockImplementationOnce(async()=>{await pause();return f.account;});
  const work=f.session.sources.loadFaxDocument(f.context);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
  f.session.setFaxSourceOffer({...f.offer,document:{...f.offer.document,operation_id:uuid(96)}});release();expect(await work).toBeNull();
  expect(f.session.getSnapshot().faxSourceOffer?.document.operation_id).toBe(uuid(96));
  if(['initial authorization','account lookup','saved result'].includes(phase))expect(f.documentEFax).not.toHaveBeenCalled();
 });
 it.each(['offer away and back','identity away and back','navigation away and back','visit link','request mutation','abort','native session'] as const)('withholds delayed bytes after %s',async change=>{
  const f=await faxFixture(),controller=new AbortController();let release!:(bytes:Uint8Array)=>void;
  if(change==='native session'){let active=true;const identity={mode:'desktop_native' as const,revision:'invented',isCurrent:()=>active};f.context.authenticated=identity;f.session.setIdentity(identity);f.offer.identity=identity;f.context.accountAccess={authorize:async()=>{if(!active)throw new WorkspaceApiError(401);}};f.documentEFax.mockImplementationOnce(async()=>{active=false;return new Uint8Array(efaxPdf);});expect(await f.session.sources.loadFaxDocument(f.context)).toBeNull();return;}
  f.documentEFax.mockImplementationOnce(()=>new Promise<Uint8Array>(resolve=>{release=resolve;}));const work=f.session.sources.loadFaxDocument(f.context,controller.signal);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
  if(change==='offer away and back'){f.session.setFaxSourceOffer({...f.offer});f.session.setFaxSourceOffer(f.offer);}
  else if(change==='identity away and back'){f.session.setIdentity({mode:'clerk_jwt',getToken:async()=>null});f.session.setIdentity(f.context.authenticated!);}
  else if(change==='navigation away and back'){f.session.setMobilePanel('Conversation');f.session.setMobilePanel('Sources');}
  else if(change==='visit link')f.session.setWorkspace({...f.workspace,appointment_id:uuid(97)});
  else if(change==='request mutation')f.offer.request.request.idempotency_key=uuid(98);
  else controller.abort();
  release(new Uint8Array(efaxPdf));expect(await work).toBeNull();
 });
 it('rejects a newer route epoch even if the screen and offer are otherwise unchanged',async()=>{
  const f=await faxFixture();f.resolveEFax.mockImplementationOnce(async()=>{f.session.navigation.sequence.current+=2;return f.receipt;});
  expect(await f.session.sources.loadFaxDocument(f.context)).toBeNull();expect(f.documentEFax).not.toHaveBeenCalled();
 });
 it.each(['box_id','actor_id','recovery_scope'] as const)('withholds verified bytes if the final account %s changes',async field=>{
  const f=await faxFixture();f.accountRead.mockResolvedValueOnce(f.account).mockResolvedValueOnce({...f.account,[field]:field==='recovery_scope'?'d'.repeat(64):uuid(99)});
  expect(await f.session.sources.loadFaxDocument(f.context)).toBeNull();expect(f.documentEFax).toHaveBeenCalledOnce();
 });
 it('propagates current authorization and byte-verification failures without retry or retaining bytes',async()=>{
  const f=await faxFixture(),denied=new WorkspaceApiError(403);f.authorize.mockRejectedValueOnce(denied);
  await expect(f.session.sources.loadFaxDocument(f.context)).rejects.toBe(denied);expect(f.accountRead).not.toHaveBeenCalled();expect(f.documentEFax).not.toHaveBeenCalled();
  const mismatch=new WorkspaceApiError(502);f.documentEFax.mockRejectedValueOnce(mismatch);await expect(f.session.sources.loadFaxDocument(f.context)).rejects.toBe(mismatch);expect(f.resolveEFax).toHaveBeenCalledOnce();expect(f.documentEFax).toHaveBeenCalledOnce();
 });
 it('does no I/O for an aborted, unlinked or unauthenticated offer',async()=>{
  const f=await faxFixture(),controller=new AbortController();controller.abort();expect(await f.session.sources.loadFaxDocument(f.context,controller.signal)).toBeNull();
  f.session.setWorkspace({...f.workspace,appointment_id:null});expect(await f.session.sources.loadFaxDocument(f.context)).toBeNull();
  f.session.setWorkspace(f.workspace);f.session.setIdentity(null);expect(await f.session.sources.loadFaxDocument(f.context)).toBeNull();expect(f.authorize).not.toHaveBeenCalled();expect(f.accountRead).not.toHaveBeenCalled();expect(f.documentEFax).not.toHaveBeenCalled();
 });
});
