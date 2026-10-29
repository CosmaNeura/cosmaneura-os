// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../../clients/capture/node_modules/fake-indexeddb';
import {DraftJournal,accountEditorAddress} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import {openDraftStore} from '../draft-store';
import {teamUuid} from '../team-setup-test-fixture';
import {emptyConversationPreferences,parseConversationPreferences} from '../conversation-preferences';
import type {ConversationSummary} from '../conversations-api';
import type {Workspace} from '../workspace-api';
import {conversationActivityDate,organizedConversations,WorkspaceInboxPreferences,type InboxPreferencesHost} from './inbox-preferences';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const row=(n:number,role:ConversationSummary['bot']['role']='chief',attention:ConversationSummary['attention']='idle'):ConversationSummary=>({workspace_id:teamUuid(n),appointment_id:null,context_label:`Invented note ${n}`,bot:{address:role,role,name:role,available:true},preview:'Invented saved response',preview_withheld:false,attention,last_activity_at:`2026-10-24T12:00:${String(n%60).padStart(2,'0')}Z`,watermark:'opaque',unread:false,manual_unread:false,marker_version:1});
async function fixture(){
  const storage=memoryDraftStorage(),journal=new DraftJournal(await storage({scope:'a'.repeat(64)}));
  const host:InboxPreferencesHost={identity:{mode:'clerk_jwt',getToken:async()=>null},recovery:{journal,recoveryScope:'a'.repeat(64),authorize:vi.fn(async()=>{})},current:()=>true,denied:vi.fn()};
  const workspace:Workspace={id:row(1).workspace_id,appointment_id:teamUuid(90),label:'Invented linked visit',revision:1,entries:[],work_candidates:[],notebook:{title:'An actual private notebook',title_revision:4,created_at:'2026-10-24T12:00:00Z'}};
  const read=vi.fn(async()=>workspace),controller=new WorkspaceInboxPreferences(read);await controller.bind(host);
  return {storage,journal,host,workspace,read,controller};
}
function nativeFixture(){
  const records=new Map<string,{key:string;data:string;revision:string}>();
  return {records,plugin:{
    get:async({key}:{key:string})=>{const record=records.get(key);if(!record)throw {code:'SECURE_QUEUE_NOT_FOUND'};return {...record};},
    create:async(record:{key:string;data:string})=>{if(records.has(record.key))throw {code:'SECURE_QUEUE_ALREADY_EXISTS'};records.set(record.key,{...record,revision:'1'});return {revision:'1'};},
    compareAndSwap:async(record:{key:string;data:string;expectedRevision:string})=>{const old=records.get(record.key);if(!old||old.revision!==record.expectedRevision)throw {code:'SECURE_QUEUE_REVISION_CONFLICT'};const revision=String(BigInt(old.revision)+1n);records.set(record.key,{key:record.key,data:record.data,revision});return {revision};},
  }};
}
describe('encrypted account conversation organization',()=>{
  it.each([false,true])('round-trips pin/hide through scoped production storage without saving names or search text (native=%s)',async native=>{
    const f=nativeFixture(),indexedDB=new IDBFactory(),scope='c'.repeat(64),options={scope,native,indexedDB,crypto:webcrypto,...(native?{plugin:f.plugin}:{})},open=()=>openDraftStore(options);
    const journal=new DraftJournal(await open()),host:InboxPreferencesHost={identity:{mode:'clerk_jwt',getToken:async()=>null},recovery:{journal,recoveryScope:scope,authorize:async()=>{}},current:()=>true,denied:vi.fn()};
    const controller=new WorkspaceInboxPreferences();await controller.bind(host);expect(controller.getSnapshot().ready).toBe(true);expect(await controller.set(row(1),{pinned:true,hidden:true})).toBe(true);
    const expected={contract:'conversation-preferences.v1',items:[{workspace_id:row(1).workspace_id,bot:'chief',pinned:true,hidden:true}]};
    expect(controller.getSnapshot().value).toEqual(expected);journal.close();
    const reopened=new DraftJournal(await open()),next=new WorkspaceInboxPreferences();await next.bind({...host,recovery:{...host.recovery,journal:reopened}});expect(next.getSnapshot().value).toEqual(expected);
    const other=new DraftJournal(await openDraftStore({...options,scope:'d'.repeat(64)}));
    await next.bind({...host,identity:{mode:'clerk_jwt',getToken:async()=>null},recovery:{...host.recovery,journal:other,recoveryScope:'d'.repeat(64)}});expect(next.getSnapshot().value.items).toEqual([]);
    reopened.close();other.close();
  });
  it.each([false,true])('retains exact storage CAS and byte bounds for preferences and rejects nearby aliases (native=%s)',async native=>{
    const f=nativeFixture(),options={scope:'e'.repeat(64),native,indexedDB:new IDBFactory(),crypto:webcrypto,...(native?{plugin:f.plugin}:{})};
    const first=await openDraftStore(options),stale=await openDraftStore(options),id=accountEditorAddress('conversation-preferences');
    const value={schema:1 as const,updatedAt:'2026-10-24T00:00:00Z',body:{note:'Invented value'}};
    await first.write(id,null,value);await expect(stale.write(id,null,{...value,body:{note:'Concurrent value'}})).rejects.toMatchObject({code:'conflict'});
    for(const alias of ['account-editor:conversation-preferences:other','account-editor:conversations-preferences'])await expect(first.write(alias,null,value)).rejects.toMatchObject({code:'invalid'});
    await expect(first.write(id,'1',{...value,body:{note:'x'.repeat(131073+512)}})).rejects.toMatchObject({code:'invalid'});expect((await first.read(id)).value).toEqual(value);first.close();stale.close();
  });
  it('retains confirmed preferences when a write fails and restores hidden chats without removing pins',async()=>{
    const f=await fixture();expect(await f.controller.set(row(1),{pinned:true})).toBe(true);
    const persist=vi.spyOn(f.journal,'persist').mockRejectedValueOnce(new Error('Invented unavailable local store'));
    expect(await f.controller.set(row(1),{hidden:true})).toBe(false);expect(f.controller.getSnapshot().value.items[0]).toMatchObject({pinned:true,hidden:false});expect(f.controller.getSnapshot().error).toContain('previous conversation organization');
    persist.mockRestore();await f.controller.set(row(1),{hidden:true});await f.controller.set(row(2,'follow_up'),{hidden:true});await f.controller.restoreAll();
    expect(f.controller.getSnapshot().value.items).toEqual([{workspace_id:row(1).workspace_id,bot:'chief',pinned:true,hidden:false}]);
  });
  it('does not publish an old account write after the account scope changes',async()=>{
    const f=await fixture();let finish!:()=>void;f.host.recovery.authorize=()=>new Promise(resolve=>{finish=resolve;});
    const operation=f.controller.set(row(1),{hidden:true});await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));
    const journal=new DraftJournal(await f.storage({scope:'b'.repeat(64)})),host={...f.host,identity:{mode:'clerk_jwt' as const,getToken:async()=>null},recovery:{journal,recoveryScope:'b'.repeat(64),authorize:async()=>{}}};
    await f.controller.bind(host);finish();expect(await operation).toBe(false);expect(f.controller.getSnapshot().value.items).toEqual([]);
    expect(await f.journal.load(accountEditorAddress('conversation-preferences'))).toBeNull();
  });
  it('rejects extra data, duplicate identifiers and pending requests in this preference editor',async()=>{
    const f=await fixture(),value={contract:'conversation-preferences.v1' as const,items:[{workspace_id:row(1).workspace_id,bot:'chief',pinned:true,hidden:false}]},address=accountEditorAddress('conversation-preferences');
    for(const data of [{...value,query:'Private search'}, {...value,items:[{...value.items[0],label:'Private title'}]}, {...value,items:[value.items[0],value.items[0]]}, {...value,items:[{...value.items[0],workspace_id:'wrong-owner-id'}]}])
      await expect(f.journal.persist(address,{kind:'account-editor',editor:'conversation-preferences',data,pending:null})).rejects.toMatchObject({code:'integrity'});
    await expect(f.journal.persist(address,{kind:'account-editor',editor:'conversation-preferences',data:value,pending:teamUuid(7)})).rejects.toMatchObject({code:'integrity'});
    expect(await f.journal.load(address)).toBeNull();expect(()=>parseConversationPreferences({...value,items:Array.from({length:501},(_,n)=>({...value.items[0],workspace_id:teamUuid(1000+n)}))})).toThrow();
  });
  it('checks actual notebook metadata without inventing visit aliases and ignores a closed menu read',async()=>{
    const f=await fixture();await f.controller.inspect(row(1));expect(f.controller.getSnapshot().rename).toEqual({workspaceId:f.workspace.id,title:'An actual private notebook',titleRevision:4});
    f.read.mockResolvedValue({...f.workspace,notebook:undefined});await f.controller.inspect(row(1));expect(f.controller.getSnapshot().rename).toBeNull();
    let finish!:(workspace:Workspace)=>void;f.read.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));const pending=f.controller.inspect(row(1));await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));
    f.controller.closeMenu();finish(f.workspace);await pending;expect(f.controller.getSnapshot().rename).toBeNull();expect(await f.journal.load(accountEditorAddress('conversation-preferences'))).toBeNull();
  });
});
describe('bounded inbox projection',()=>{
  it('keeps Chief first and attention before pinned/recent chats, without mixing hidden results',()=>{
    const chief=row(1),needs=row(2,'follow_up','needs_review'),pinned=row(3,'research'),working=row(4,'visit_prep','working'),hidden=row(5,'scribe');
    const value={contract:'conversation-preferences.v1' as const,items:[{workspace_id:pinned.workspace_id,bot:pinned.bot.address,pinned:true,hidden:false},{workspace_id:hidden.workspace_id,bot:hidden.bot.address,pinned:false,hidden:true}]};
    const groups=organizedConversations([working,hidden,pinned,needs,chief],value,'');expect(groups.map(group=>group.title)).toEqual(['Chief','Needs you','Recent']);expect(groups.flatMap(group=>group.rows)).toEqual([chief,needs,pinned,working]);
    expect(organizedConversations([chief,hidden],value,'invented',true).flatMap(group=>group.rows)).toEqual([hidden]);
    expect(organizedConversations([chief,needs],emptyConversationPreferences(),'FOLLOW_UP').flatMap(group=>group.rows)).toEqual([needs]);
  });
  it('uses activity time today and calendar-day dates across month/year boundaries',()=>{
    const now=new Date(2026,0,1,12);expect(conversationActivityDate(new Date(2025,11,31,23).toISOString(),now)).toBe('Yesterday');
    expect(conversationActivityDate(new Date(2026,0,1,11).toISOString(),now)).toBe(new Date(2026,0,1,11).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}));
    expect(conversationActivityDate(new Date(2025,10,1,11).toISOString(),now)).toContain('2025');
  });
});
