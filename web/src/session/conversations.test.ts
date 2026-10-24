// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {WorkspaceSession} from './workspace-session';
import {teamFixture,teamUuid} from '../team-setup-test-fixture';
import {DraftJournal,editorAddress} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import type {Workspace} from '../workspace-api';
import type {ConversationHost} from './conversations';
import {PRESENTATION_KEY} from './presentation';
async function fixture(){
  const api={read:vi.fn(async()=>({contract_version:1 as const,as_of:new Date().toISOString(),rows:[],next_cursor:null})),mark:vi.fn(async()=>({contract_version:1 as const,marker_version:1,manual_unread:false,seen_watermark:null}))};
  const values=new Map<string,string>(),storage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value);}};
  const session=new WorkspaceSession({presentation:{enabled:true,phone:true,storage},conversations:api,conversationRead:async(_owner,wid)=>({...workspace,id:wid})});session.setTeam(teamFixture());
  const workspace:Workspace={id:teamUuid(601),appointment_id:null,label:'Invented note',revision:1,entries:[],work_candidates:[]};
  session.setWorkspace(workspace);session.setSelected('chief');session.setPracticePage('notebook');
  const journal=new DraftJournal(await memoryDraftStorage()({scope:'invented'}));session.recovery.journal.current={scope:'invented',serverScope:'a'.repeat(64),value:journal};
  const host:ConversationHost={identity:{mode:'clerk_jwt',getToken:async()=>null},journal,scope:'invented',current:()=>true,blocked:()=>!!session.getSnapshot().pending,authorize:vi.fn(async()=>{}),failure:vi.fn(),navigate:vi.fn(async route=>{session.navigation.sequence.current++;session.setSelected(route.helper!);session.setPracticePage('notebook');session.setWorkspace({...workspace,id:route.workspaceId!});})};
  return {session,workspace,journal,host,api,storage,values};
}
describe('shared conversation state',()=>{
  it('prepares journal addresses and restores drafts separately by bot and context',async()=>{
    const f=await fixture();f.session.models.updateThought('Chief directions');await f.session.conversations.open(f.workspace.id,'follow_up',f.host);
    expect(f.session.getSnapshot().thought).toBe('');f.session.models.updateThought('Follow-up draft');await f.session.conversations.open(teamUuid(602),'chief',f.host);
    f.session.models.updateThought('Another visit');await f.session.conversations.open(f.workspace.id,'chief',f.host);expect(f.session.getSnapshot().thought).toBe('Chief directions');
    await f.session.conversations.open(f.workspace.id,'follow_up',f.host);expect(f.session.getSnapshot().thought).toBe('Follow-up draft');
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
    await f.session.conversations.acknowledgeVisible(f.host);expect(f.api.mark).toHaveBeenCalledTimes(1);
    f.session.setMobilePanel('Conversation');await f.session.conversations.acknowledgeVisible(f.host);
    expect(f.api.mark).toHaveBeenLastCalledWith(f.host.identity,f.workspace.id,'scribe',{watermark:row.watermark,manual_unread:false,expected_version:3});
    await f.session.conversations.acknowledgeVisible(f.host);expect(f.api.mark).toHaveBeenCalledTimes(2);
  });
  it('blocks a layout change while Research retains an unconfirmed request',async()=>{
    const f=await fixture();f.session.setResearchPending(true);expect(f.session.presentation.choose('workspace',false)).toBe(false);
    f.session.setResearchPending(false);expect(f.session.presentation.choose('workspace',false)).toBe(true);
  });

});
