// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {WorkspaceSession} from './workspace-session';
import {teamFixture,teamUuid} from '../team-setup-test-fixture';
import {DraftJournal,editorAddress} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import {WorkspaceApiError,type Workspace,type WorkspaceIdentity} from '../workspace-api';
import type {ConversationHost} from './conversations';
import {PRESENTATION_KEY} from './presentation';
import type {ConversationInbox,ConversationSummary} from '../conversations-api';
async function fixture(){
  const api={read:vi.fn(async():Promise<ConversationInbox>=>({contract_version:1,as_of:new Date().toISOString(),rows:[],next_cursor:null})),mark:vi.fn(async()=>({contract_version:1 as const,marker_version:1,manual_unread:false,seen_watermark:null}))};
  const values=new Map<string,string>(),storage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value);}};
  const readWorkspace=vi.fn(async(_owner:WorkspaceIdentity,wid:string):Promise<Workspace>=>({...workspace,id:wid}));
  const session=new WorkspaceSession({presentation:{enabled:true,phone:true,storage},conversations:api,conversationRead:readWorkspace});session.setTeam(teamFixture());
  const workspace:Workspace={id:teamUuid(601),appointment_id:null,label:'Invented note',revision:1,entries:[],work_candidates:[]};
  session.setWorkspace(workspace);session.setSelected('chief');session.setPracticePage('notebook');
  const journal=new DraftJournal(await memoryDraftStorage()({scope:'invented'}));session.recovery.journal.current={scope:'invented',serverScope:'a'.repeat(64),value:journal};
  const host:ConversationHost={identity:{mode:'clerk_jwt',getToken:async()=>null},journal,scope:'invented',current:()=>true,blocked:()=>!!session.getSnapshot().pending,authorize:vi.fn(async()=>{}),failure:vi.fn(),navigate:vi.fn(async route=>{session.navigation.sequence.current++;session.setSelected(route.helper!);session.setPracticePage('notebook');session.setWorkspace({...workspace,id:route.workspaceId!});})};
  return {session,workspace,journal,host,api,storage,values,readWorkspace};
}
describe('shared conversation state',()=>{
  it('prepares journal addresses and restores drafts separately by bot and context',async()=>{
    const f=await fixture();f.session.models.updateThought('Chief directions');await f.session.conversations.open(f.workspace.id,'follow_up',f.host);
    expect(f.session.getSnapshot().thought).toBe('');f.session.models.updateThought('Follow-up draft');await f.session.conversations.open(teamUuid(602),'chief',f.host);
    f.session.models.updateThought('Another visit');await f.session.conversations.open(f.workspace.id,'chief',f.host);expect(f.session.getSnapshot().thought).toBe('Chief directions');
    await f.session.conversations.open(f.workspace.id,'follow_up',f.host);expect(f.session.getSnapshot().thought).toBe('Follow-up draft');
  });
  it('keeps outgoing text under its original bot when an ordinary same-notebook switch fails',async()=>{
    const f=await fixture();f.session.models.updateThought('Chief directions retained after a failed switch.');f.readWorkspace.mockRejectedValueOnce(new Error('Synthetic failed destination read'));
    const exposed:string[]=[];const stop=f.session.subscribe(()=>{const live=f.session.getSnapshot();if(!live.conversationBusy&&live.selected==='follow_up'&&live.thought)exposed.push(live.thought);});
    expect(await f.session.conversations.open(f.workspace.id,'follow_up',f.host)).toBe(false);
    expect(f.session.getSnapshot()).toMatchObject({selected:'chief',thought:'Chief directions retained after a failed switch.',conversationBusy:false});expect(exposed).toEqual([]);expect(f.api.mark).not.toHaveBeenCalled();stop();
    expect(await f.journal.load(editorAddress(f.workspace.id,'conversation:chief'))).toMatchObject({data:{text:'Chief directions retained after a failed switch.'}});
    expect(await f.session.conversations.open(f.workspace.id,'follow_up',f.host)).toBe(true);expect(f.session.getSnapshot().thought).toBe('');
    await f.session.conversations.open(f.workspace.id,'chief',f.host);expect(f.session.getSnapshot().thought).toBe('Chief directions retained after a failed switch.');
  });
  it.each([false,true])('retains both drafts when New message reopens the same note (observe during reopen: %s)',async observeDuringReopen=>{
    const f=await fixture(),chief='Retain these invented Chief directions after reopening.',followUp='Keep this separate invented Follow-up draft.';
    f.session.models.updateThought(chief);await f.session.conversations.observe(f.host);
    // New message retains the outgoing draft before showing the context picker.
    expect(await f.session.conversations.retain(f.host)).toBe(true);f.session.setPracticePage('home');
    // Reuse the real loader: choosing the existing note starts a new lifetime,
    // clears the composer, and shows Chief before the requested bot opens.
    await f.session.loading.openPrivate({identity:f.host.identity,workspace:f.workspace,team:f.session.getSnapshot().team!},{
      authenticated:f.host.identity,beforeOpen:()=>{},show:()=>{f.session.setSelected('chief');f.session.setPracticePage('notebook');},
      recoverAfterRead:async()=>{if(observeDuringReopen)await f.session.conversations.observe(f.host);},
    });
    await f.session.conversations.open(f.workspace.id,'follow_up',f.host);
    expect(f.session.getSnapshot().thought).toBe('');
    expect(await f.journal.load(editorAddress(f.workspace.id,'conversation:chief'))).toMatchObject({data:{text:chief}});
    f.session.models.updateThought(followUp);await f.session.conversations.observe(f.host);
    f.session.setPracticePage('home');await f.session.conversations.open(f.workspace.id,'chief',f.host);
    expect(f.session.getSnapshot().thought).toBe(chief);
    await f.session.conversations.open(f.workspace.id,'follow_up',f.host);expect(f.session.getSnapshot().thought).toBe(followUp);
    expect(f.session.getSnapshot().pending).toBeNull();
  });
  it('does not restore into a different bot or page after delayed authorization',async()=>{
    const f=await fixture();let resolve!:()=>void;f.host.authorize=()=>new Promise<void>(done=>{resolve=done;});
    const task=f.session.conversations.open(f.workspace.id,'follow_up',f.host);await vi.waitFor(()=>expect(resolve).toBeTypeOf('function'));
    f.session.setSelected('scribe');f.session.setPracticePage('home');f.session.models.updateThought('Newer text');resolve();await task;
    expect(f.session.getSnapshot().thought).toBe('Newer text');expect(f.api.mark).not.toHaveBeenCalled();
  });
  it('does not overwrite a destination edit made while its journal read settles',async()=>{
    const f=await fixture();let resolve!:()=>void;f.host.authorize=()=>new Promise<void>(done=>{resolve=done;});
    const task=f.session.conversations.open(f.workspace.id,'follow_up',f.host);await vi.waitFor(()=>expect(resolve).toBeTypeOf('function'));f.session.models.updateThought('Typed now');resolve();await task;
    expect(f.session.getSnapshot().thought).toBe('Typed now');expect(f.api.mark).not.toHaveBeenCalled();
  });
  it('keeps unconfirmed writes and their exact request from either presentation',async()=>{
    const f=await fixture(),pending={type:'entry' as const,body:{expected_revision:1,idempotency_key:teamUuid(603),kind:'scratchpad' as const,content:'Exact content'}};f.session.setPending(pending);
    expect(f.session.presentation.choose('workspace',false)).toBe(false);await f.session.conversations.open(f.workspace.id,'scribe',f.host);
    expect(f.host.navigate).not.toHaveBeenCalled();expect(f.session.getSnapshot().pending).toBe(pending);
  });
  it('keeps an older unhydrated chat draft when switching from an empty workspace composer',async()=>{
    const f=await fixture(),address=editorAddress(f.workspace.id,'conversation:chief');await f.journal.load(address);await f.journal.persist(address,{kind:'editor',workspaceId:f.workspace.id,editor:'conversation:chief',pending:null,data:{text:'Recover me'}});
    await f.session.conversations.open(f.workspace.id,'follow_up',f.host);await f.session.conversations.open(f.workspace.id,'chief',f.host);expect(f.session.getSnapshot().thought).toBe('Recover me');
    f.session.models.updateThought('');await f.session.conversations.retain(f.host);await f.session.conversations.open(f.workspace.id,'follow_up',f.host);await f.session.conversations.open(f.workspace.id,'chief',f.host);expect(f.session.getSnapshot().thought).toBe('');
  });
  it('retains an unhydrated saved-note task with empty directions, but respects its later explicit removal',async()=>{
    const f=await fixture(),address=editorAddress(f.workspace.id,'conversation:chief');
    const noteTask={contract:'chief-note-task.compose.v1' as const,note_id:teamUuid(630),note_version:1,content_hash:'a'.repeat(64),source_fingerprint:'b'.repeat(64)};
    await f.journal.load(address);await f.journal.persist(address,{kind:'editor',workspaceId:f.workspace.id,editor:'conversation:chief',pending:null,data:{text:'',noteTask}});
    await f.session.conversations.open(f.workspace.id,'follow_up',f.host);
    expect(await f.journal.load(address)).toMatchObject({data:{text:'',noteTask}});
    await f.session.conversations.open(f.workspace.id,'chief',f.host);
    expect(f.session.getSnapshot().phoneNoteTask?.selection.note_id).toBe(noteTask.note_id);
    f.session.setPhoneNoteTask(null);await f.session.conversations.retain(f.host);
    await f.session.conversations.open(f.workspace.id,'follow_up',f.host);
    await f.session.conversations.open(f.workspace.id,'chief',f.host);
    expect(f.session.getSnapshot().phoneNoteTask).toBeNull();
    expect(await f.journal.load(address)).toHaveProperty('data',{text:''});
  });
  it.each([false,true])('keeps a newly selected note when an older conversation draft loads (selection during load: %s)',async duringLoad=>{
    const f=await fixture(),address=editorAddress(f.workspace.id,'conversation:chief');
    const prior={contract:'chief-note-task.compose.v1' as const,note_id:teamUuid(631),note_version:1,content_hash:'a'.repeat(64),source_fingerprint:'b'.repeat(64)};
    await f.journal.load(address);await f.journal.persist(address,{kind:'editor',workspaceId:f.workspace.id,editor:'conversation:chief',pending:null,data:{text:'Older directions',noteTask:prior}});
    const selected={owner:f.host.identity,scope:f.host.scope,generation:f.session.generation.current,workspaceId:f.workspace.id,
      selection:{share_with_team:true as const,expected_revision:f.workspace.revision,idempotency_key:teamUuid(632),note_id:teamUuid(633),note_version:2,content_hash:'c'.repeat(64),source_fingerprint:'d'.repeat(64)},content:'New selected saved note'};
    if(duringLoad){
      let release!:()=>void;const original=f.journal.load.bind(f.journal);
      const load=vi.spyOn(f.journal,'load').mockImplementationOnce(async key=>{const retained=await original(key);await new Promise<void>(done=>{release=done;});return retained;});
      const observing=f.session.conversations.observe(f.host);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
      f.session.setPhoneNoteTask(selected);release();await observing;load.mockRestore();
      expect(f.session.getSnapshot().phoneNoteTask).toBe(selected);
    }else f.session.setPhoneNoteTask(selected);
    await f.session.conversations.observe(f.host);
    expect(f.session.getSnapshot()).toMatchObject({thought:'',phoneNoteTask:selected});
    expect(await f.journal.load(address)).toMatchObject({data:{text:'',noteTask:{note_id:selected.selection.note_id,note_version:2}}});
  });
  it('keeps layout preferences per device and retains them when rollout is disabled',async()=>{
    const f=await fixture();expect(f.session.presentation.current()).toBe('messages');expect(f.session.presentation.choose('workspace',false)).toBe(true);expect(f.values.get(PRESENTATION_KEY)).toBe('workspace');
    f.storage.setItem(PRESENTATION_KEY,'messages');const disabled=new WorkspaceSession({presentation:{enabled:false,phone:true,storage:f.storage}});disabled.setTeam(teamFixture());expect(disabled.presentation.current()).toBe('workspace');expect(f.values.get(PRESENTATION_KEY)).toBe('messages');
    const desktop=new WorkspaceSession({presentation:{enabled:true,phone:false,storage:f.storage}});desktop.setTeam(teamFixture());expect(desktop.presentation.current()).toBe('messages');
  });
  it('allows steady recording but blocks its transitions without replacing the session',async()=>{
    const f=await fixture(),generation=f.session.generation;f.session.setPrivateRecordingBusy(true);expect(f.session.presentation.choose('workspace',false)).toBe(true);expect(f.session.generation).toBe(generation);
    f.session.setRecordingTransition(true);expect(f.session.presentation.choose('messages',false)).toBe(false);
  });
  it('acknowledges Scribe replies only after their history is visible, using the original watermark',async()=>{
    const f=await fixture(),row={workspace_id:f.workspace.id,appointment_id:null,context_label:'Invented note',bot:{address:'scribe',role:'scribe' as const,name:'Scribe',available:true},preview:'Saved reply',preview_withheld:false,attention:'idle' as const,last_activity_at:new Date().toISOString(),watermark:'observed-before-open',unread:true,manual_unread:false,marker_version:3};
    await f.session.conversations.open(f.workspace.id,'scribe',f.host,row);
    expect(f.session.getSnapshot().mobilePanel).toBe('Notebook');expect(f.api.mark).toHaveBeenLastCalledWith(f.host.identity,f.workspace.id,'scribe',{});
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);expect(f.api.mark).toHaveBeenCalledTimes(1);
    f.session.setMobilePanel('Conversation');await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    expect(f.api.mark).toHaveBeenLastCalledWith(f.host.identity,f.workspace.id,'scribe',{watermark:row.watermark,manual_unread:false,expected_version:3});
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);expect(f.api.mark).toHaveBeenCalledTimes(2);
  });
  it('blocks a layout change while Research retains an unconfirmed request',async()=>{
    const f=await fixture();f.session.setResearchPending(true);expect(f.session.presentation.choose('workspace',false)).toBe(false);
    f.session.setResearchPending(false);expect(f.session.presentation.choose('workspace',false)).toBe(true);
  });

});

async function visibleReply(){
  const f=await fixture();
  f.workspace.entries=[{id:teamUuid(620),revision:2,kind:'conversation',content:'Invented question',source_label:null,origin:'human',ticket:null,created_at:'2026-10-24T12:00:00Z',
    reply:{agent_name:'Chief',role:'chief',backend:'fake',content:'New invented reply',context_revision:1,citations:[]}}];
  f.workspace.revision=2;f.session.setWorkspace({...f.workspace});
  const row:ConversationSummary={workspace_id:f.workspace.id,appointment_id:null,context_label:'Invented note',bot:{address:'chief',role:'chief',name:'Chief',available:true},preview:'New invented reply',preview_withheld:false,attention:'idle',last_activity_at:'2026-10-24T12:00:01Z',watermark:'fresh-server-watermark',unread:true,manual_unread:false,marker_version:3};
  f.api.read.mockResolvedValue({contract_version:1,as_of:row.last_activity_at,rows:[row],next_cursor:null});
  return {...f,row};
}
describe('read acknowledgment for displayed replies',()=>{
  it('marks the fresh exact watermark after a confirming read and never clears manual unread',async()=>{
    const f=await visibleReply();f.row.manual_unread=true;
    await f.session.conversations.acknowledgeDisplayed(f.host,()=>true);
    expect(f.readWorkspace).toHaveBeenCalledOnce();expect(f.host.authorize).toHaveBeenCalledOnce();
    expect(f.api.mark).toHaveBeenCalledExactlyOnceWith(f.host.identity,f.workspace.id,'chief',{watermark:f.row.watermark});
    await f.session.conversations.acknowledgeDisplayed(f.host,()=>true);expect(f.api.mark).toHaveBeenCalledOnce();expect(f.api.read).toHaveBeenCalledOnce();
  });
  it('does not acknowledge a newer server reply that has not rendered',async()=>{
    const f=await visibleReply(),newer={...f.workspace,entries:[...f.workspace.entries,{...f.workspace.entries[0],id:teamUuid(621),reply:{...f.workspace.entries[0].reply!,content:'Not on screen yet'}}]};
    f.readWorkspace.mockResolvedValue(newer);
    await f.session.conversations.acknowledgeDisplayed(f.host,()=>true);expect(f.api.mark).not.toHaveBeenCalled();
    f.session.setWorkspace(newer);f.row.watermark='newer-server-watermark';
    await f.session.conversations.acknowledgeDisplayed(f.host,()=>true);
    expect(f.api.mark).toHaveBeenCalledExactlyOnceWith(f.host.identity,f.workspace.id,'chief',{watermark:'newer-server-watermark'});
  });
  it('follows bounded server pages to find the displayed conversation without inventing its watermark',async()=>{
    const f=await visibleReply();f.api.read.mockResolvedValueOnce({contract_version:1,as_of:f.row.last_activity_at,rows:[],next_cursor:'opaque-next-page'});
    await f.session.conversations.acknowledgeDisplayed(f.host,()=>true);
    expect(f.api.read).toHaveBeenNthCalledWith(1,f.host.identity,null);expect(f.api.read).toHaveBeenNthCalledWith(2,f.host.identity,'opaque-next-page');
    expect(f.api.mark).toHaveBeenCalledExactlyOnceWith(f.host.identity,f.workspace.id,'chief',{watermark:f.row.watermark});
  });
  it('stops after five sequential pages and retains an explicit read-sync error',async()=>{
    const f=await visibleReply();let page=0;f.api.read.mockImplementation(async()=>({contract_version:1,as_of:f.row.last_activity_at,rows:[],next_cursor:`opaque-page-${++page}`}));
    await f.session.conversations.acknowledgeDisplayed(f.host,()=>true);
    expect(f.api.read).toHaveBeenCalledTimes(5);expect(f.api.mark).not.toHaveBeenCalled();expect(f.readWorkspace).not.toHaveBeenCalled();
    expect(f.session.getSnapshot().conversationError).toContain('Read status could not sync');
    f.api.read.mockResolvedValue({contract_version:1,as_of:f.row.last_activity_at,rows:[f.row],next_cursor:null});
    await f.session.conversations.acknowledgeDisplayed(f.host,()=>true);expect(f.api.mark).toHaveBeenCalledOnce();expect(f.session.getSnapshot().conversationError).toBe('');
  });
  it('waits above the bottom and abandons a read if the history becomes hidden',async()=>{
    const f=await visibleReply();let visible=false;
    await f.session.conversations.acknowledgeDisplayed(f.host,()=>visible);expect(f.api.read).not.toHaveBeenCalled();
    let finish!:()=>void;f.host.authorize=()=>new Promise(resolve=>{finish=resolve;});visible=true;
    const task=f.session.conversations.acknowledgeDisplayed(f.host,()=>visible);await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));
    visible=false;finish();await task;expect(f.api.mark).not.toHaveBeenCalled();
    f.host.authorize=async()=>{};visible=true;await f.session.conversations.acknowledgeDisplayed(f.host,()=>visible);expect(f.api.mark).toHaveBeenCalledOnce();
  });
  it.each(['settings','research','notebook','owner','route'] as const)('does not mark after %s replaces the visible conversation',async change=>{
    const f=await visibleReply();let finish!:(value:Workspace)=>void;f.readWorkspace.mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
    const task=f.session.conversations.acknowledgeDisplayed(f.host,()=>true);await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));
    if(change==='settings')f.session.setSettingsOpen(true);
    if(change==='research'){f.session.setSelected('research');f.session.setSavedResearchChat(false);}
    if(change==='notebook')f.session.setMobilePanel('Notebook');
    if(change==='owner')f.host.current=()=>false;
    if(change==='route')f.session.navigation.sequence.current++;
    finish(f.workspace);await task;expect(f.api.mark).not.toHaveBeenCalled();
  });
  it('requires full source access even when a withheld inbox preview is followed by a matching history',async()=>{
    const f=await visibleReply();f.row.preview_withheld=true;f.readWorkspace.mockResolvedValue({...f.workspace,entries:f.workspace.entries.map(entry=>({...entry,google_source_state:'unavailable'}))});
    await f.session.conversations.acknowledgeDisplayed(f.host,()=>true);expect(f.api.mark).not.toHaveBeenCalled();
    f.readWorkspace.mockResolvedValue(f.workspace);await f.session.conversations.acknowledgeDisplayed(f.host,()=>true);expect(f.api.mark).toHaveBeenCalledOnce();
  });
  it('does not consume an opened Chief summary before it is visible and preserves manual-unread CAS',async()=>{
    const f=await visibleReply();f.api.mark.mockResolvedValue({contract_version:1,marker_version:4,manual_unread:true,seen_watermark:null});f.row.manual_unread=true;
    await f.session.conversations.open(f.workspace.id,'chief',f.host,f.row);
    expect(f.api.mark).toHaveBeenCalledExactlyOnceWith(f.host.identity,f.workspace.id,'chief',{});
    await f.session.conversations.acknowledgeVisible(f.host,()=>false);expect(f.api.mark).toHaveBeenCalledOnce();
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    expect(f.api.mark).toHaveBeenLastCalledWith(f.host.identity,f.workspace.id,'chief',{watermark:f.row.watermark,manual_unread:false,expected_version:4});
  });
  it('does not adopt a concurrently changed manual-unread version when opening a chat',async()=>{
    const f=await visibleReply();f.api.mark.mockResolvedValue({contract_version:1,marker_version:5,manual_unread:true,seen_watermark:null});
    await f.session.conversations.open(f.workspace.id,'chief',f.host,f.row);
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    expect(f.api.mark).toHaveBeenLastCalledWith(f.host.identity,f.workspace.id,'chief',{watermark:f.row.watermark,manual_unread:false,expected_version:3});
  });
  it('retains the exact opened-chat acknowledgment after a transient failure until retry succeeds',async()=>{
    const f=await visibleReply();f.row.manual_unread=true;
    f.api.mark.mockResolvedValue({contract_version:1,marker_version:4,manual_unread:true,seen_watermark:null});
    await f.session.conversations.open(f.workspace.id,'chief',f.host,f.row);f.api.mark.mockClear();
    f.api.mark.mockRejectedValueOnce(new Error('Synthetic interrupted read acknowledgment'));
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    expect(f.session.getSnapshot().conversationError).toContain('Read status could not sync');
    // A separate automatic watermark update must not hide the failed explicit
    // clear of the manual-unread flag.
    await f.session.conversations.acknowledgeDisplayed(f.host,()=>true);
    expect(f.api.mark).toHaveBeenCalledOnce();
    expect(f.session.getSnapshot().conversationError).toContain('Read status could not sync');
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    expect(f.api.mark).toHaveBeenLastCalledWith(f.host.identity,f.workspace.id,'chief',{watermark:f.row.watermark,manual_unread:false,expected_version:4});
    expect(f.session.getSnapshot().conversationError).toBe('');
    const settled=f.api.mark.mock.calls.length;
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    expect(f.api.mark).toHaveBeenCalledTimes(settled);
  });
  it('retries an interrupted opened-chat acknowledgment only while that history is current and visible',async()=>{
    const f=await visibleReply();await f.session.conversations.open(f.workspace.id,'chief',f.host,f.row);f.api.mark.mockClear();
    f.api.mark.mockRejectedValueOnce(new Error('Synthetic interrupted acknowledgment'));
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    await f.session.conversations.acknowledgeVisible(f.host,()=>false);
    expect(f.api.mark).toHaveBeenCalledOnce();
    f.session.invalidate();
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    expect(f.api.mark).toHaveBeenCalledOnce();
  });
  it('does not let an older acknowledgment failure replace a newer opened conversation',async()=>{
    const f=await visibleReply();await f.session.conversations.open(f.workspace.id,'chief',f.host,f.row);f.api.mark.mockClear();
    let reject!:(cause:Error)=>void;
    f.api.mark.mockImplementationOnce(()=>new Promise((_resolve,fail)=>{reject=fail;}));
    const older=f.session.conversations.acknowledgeVisible(f.host,()=>true);
    await vi.waitFor(()=>expect(reject).toBeTypeOf('function'));
    const next={...f.row,bot:{...f.row.bot,address:'follow_up',role:'follow_up' as const,name:'Follow-up'},watermark:'next-observed-watermark',marker_version:8};
    await f.session.conversations.open(f.workspace.id,'follow_up',f.host,next);
    reject(new Error('Synthetic late acknowledgment failure'));await older;
    expect(f.session.getSnapshot().conversationError).toBe('');
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    expect(f.api.mark).toHaveBeenLastCalledWith(f.host.identity,f.workspace.id,'follow_up',{watermark:next.watermark,manual_unread:false,expected_version:8});
  });
  it('shares one failed acknowledgment across simultaneous visibility events, then retries on a later event',async()=>{
    const f=await visibleReply();await f.session.conversations.open(f.workspace.id,'chief',f.host,f.row);f.api.mark.mockClear();
    let reject!:(cause:Error)=>void;
    f.api.mark.mockImplementationOnce(()=>new Promise((_resolve,fail)=>{reject=fail;}));
    const notifications=Array.from({length:4},()=>f.session.conversations.acknowledgeVisible(f.host,()=>true));
    reject(new Error('Synthetic interrupted acknowledgment'));await Promise.all(notifications);
    expect(f.api.mark).toHaveBeenCalledOnce();
    expect(f.session.getSnapshot().conversationError).toContain('Read status could not sync');
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    expect(f.api.mark).toHaveBeenCalledTimes(2);expect(f.session.getSnapshot().conversationError).toBe('');
  });
  it.each([401,403])('passes a current opened-chat acknowledgment denial (%s) to the session access handler',async status=>{
    const f=await visibleReply();await f.session.conversations.open(f.workspace.id,'chief',f.host,f.row);
    const denied=new WorkspaceApiError(status);f.api.mark.mockRejectedValueOnce(denied);
    await f.session.conversations.acknowledgeVisible(f.host,()=>true);
    expect(f.host.failure).toHaveBeenCalledExactlyOnceWith(denied);
  });
  it.each([401,403])('passes a current Mark unread denial (%s) to the session access handler',async status=>{
    const f=await visibleReply(),denied=new WorkspaceApiError(status);f.api.mark.mockRejectedValueOnce(denied);
    await f.session.conversations.markUnread(f.row,f.host.identity,f.host.failure);
    expect(f.host.failure).toHaveBeenCalledExactlyOnceWith(denied);
  });
  it('does not apply a late Mark unread denial after the account generation changes',async()=>{
    const f=await visibleReply();let reject!:(cause:Error)=>void;
    f.api.mark.mockImplementationOnce(()=>new Promise((_resolve,fail)=>{reject=fail;}));
    const request=f.session.conversations.markUnread(f.row,f.host.identity,f.host.failure);
    f.session.invalidate();reject(new WorkspaceApiError(403));await request;
    expect(f.host.failure).not.toHaveBeenCalled();expect(f.session.getSnapshot().conversationError).toBe('');
  });
  it('serializes duplicate visible notifications before automatic read updates',async()=>{
    const f=await visibleReply();await f.session.conversations.open(f.workspace.id,'chief',f.host,f.row);f.api.mark.mockClear();
    let finish!:()=>void;f.api.mark.mockImplementationOnce(()=>new Promise(resolve=>{finish=()=>resolve({contract_version:1,marker_version:4,manual_unread:false,seen_watermark:null});}));
    const first=f.session.conversations.acknowledgeVisible(f.host,()=>true),second=f.session.conversations.acknowledgeVisible(f.host,()=>true).then(()=>f.session.conversations.acknowledgeDisplayed(f.host,()=>true));
    await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));expect(f.api.mark).toHaveBeenCalledOnce();expect(f.api.read).toHaveBeenCalledOnce();
    finish();await Promise.all([first,second]);expect(f.api.mark).toHaveBeenCalledTimes(2);
    expect(f.api.mark).toHaveBeenLastCalledWith(f.host.identity,f.workspace.id,'chief',{watermark:f.row.watermark});
  });
});
