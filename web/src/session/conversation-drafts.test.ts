// @vitest-environment node
import {afterEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../../clients/capture/node_modules/fake-indexeddb';
import {WorkspaceConversationDrafts} from './conversation-drafts';
import {DraftJournal,editorAddress} from '../draft-journal';
import {openDraftStore,type DraftStore} from '../draft-store';
import {conversationPreferenceKey} from '../conversation-preferences';
import type {ConversationDraft} from '../conversation-draft';
import type {ConversationSummary} from '../conversations-api';
import type {InboxPreferencesHost} from './inbox-preferences';
import {teamUuid} from '../team-setup-test-fixture';
import {WorkspaceApiError} from '../workspace-api';
import {notifyNativeWorkspaceForeground} from '../native-workspace-foreground';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const row=(wid=701,bot='chief'):ConversationSummary=>({workspace_id:teamUuid(wid),appointment_id:null,context_label:'Invented note',bot:{address:bot,role:bot==='chief'?'chief':'follow_up',name:bot,available:true},preview:'Saved server reply',preview_withheld:false,attention:'needs_review',last_activity_at:'2026-10-25T12:00:00Z',watermark:'invented',unread:true,manual_unread:true,marker_version:3});
const key=(r:ConversationSummary)=>conversationPreferenceKey(r.workspace_id,r.bot.address);
const cleanups:Array<()=>void>=[];
afterEach(()=>{for(const cleanup of cleanups.splice(0))cleanup();vi.restoreAllMocks();});
async function fixture(){
 const idb=new IDBFactory(),scope='d'.repeat(64),storage=()=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto as Crypto});
 const store=await storage(),journal=new DraftJournal(store),controller=new WorkspaceConversationDrafts();
 const host:InboxPreferencesHost={identity:{mode:'clerk_jwt',getToken:async()=>null},recovery:{journal,recoveryScope:scope,authorize:vi.fn(async()=>{})},current:()=>true,denied:vi.fn()};
 cleanups.push(()=>controller.clear(),()=>journal.close());
 async function save(r:ConversationSummary,data:ConversationDraft|null){const address=editorAddress(r.workspace_id,`conversation:${r.bot.address}`);if(!journal.has(address))await journal.load(address);await journal.persist(address,data?{kind:'editor',workspaceId:r.workspace_id,editor:`conversation:${r.bot.address}`,pending:null,data}:null);}
 return {controller,host,journal,store,storage,save};
}
it('reads text and selected-note presence from the encrypted per-bot/context drafts without changing server attention',async()=>{
 const f=await fixture(),rows=[row(),row(701,'follow_up'),row(702),row(703)];
 const note={contract:'chief-note-task.compose.v1' as const,note_id:teamUuid(55),note_version:2,content_hash:'a'.repeat(64),source_fingerprint:'b'.repeat(64)};
 await f.save(rows[0],{text:'Invented private Chief text'});await f.save(rows[1],{text:'',noteTask:note});await f.save(rows[2],{text:'  '});
 await f.controller.bind(f.host,rows);
 expect(f.controller.getSnapshot().items).toEqual({[key(rows[0])]:'text',[key(rows[1])]:'note'});
 expect(JSON.stringify(f.controller.getSnapshot().items)).not.toContain('private');expect(rows[0]).toMatchObject({unread:true,manual_unread:true,attention:'needs_review',preview:'Saved server reply'});
 expect(f.host.recovery.authorize).toHaveBeenCalledTimes(2);
 // A new store/journal instance decrypts the retained values after reload.
 f.controller.clear();f.journal.close();const next=new DraftJournal(await f.storage());cleanups.push(()=>next.close());
 await f.controller.bind({...f.host,recovery:{...f.host.recovery,journal:next}},rows);
 expect(f.controller.getSnapshot().items).toEqual({[key(rows[0])]:'text',[key(rows[1])]:'note'});
});
it('updates after confirmed clearing/discard without creating a parallel metadata record',async()=>{
 const f=await fixture(),r=row();await f.save(r,{text:'Invented draft'});await f.controller.bind(f.host,[r]);
 await f.save(r,{text:''});await vi.waitFor(()=>expect(f.controller.getSnapshot()).toMatchObject({checking:false,items:{}}));
 await f.save(r,{text:'Another invented draft'});await vi.waitFor(()=>expect(f.controller.getSnapshot().items[key(r)]).toBe('text'));
 await f.save(r,null);await vi.waitFor(()=>expect(f.controller.getSnapshot()).toMatchObject({checking:false,items:{}}));
 expect([...f.journal.records.keys()]).toEqual([editorAddress(r.workspace_id,'conversation:chief')]);
});
it('ignores writes to unrelated editors and withholds presence immediately when the journal closes',async()=>{
 const f=await fixture(),r=row();await f.save(r,{text:'Invented draft'});await f.controller.bind(f.host,[r]);const count=vi.mocked(f.host.recovery.authorize).mock.calls.length;
 await f.save(row(704),{text:'Another visit'});expect(f.host.recovery.authorize).toHaveBeenCalledTimes(count);
 f.journal.close();expect(f.controller.getSnapshot()).toMatchObject({identity:null,journal:null,items:{},checking:false});
});
it('discards a late local read after a different account takes ownership',async()=>{
 const f=await fixture(),other=await fixture(),r=row();await f.save(r,{text:'Account A private text'});
 const original=f.journal.load.bind(f.journal);let finish!:()=>void,entered!:()=>void;const started=new Promise<void>(resolve=>{entered=resolve;});
 vi.spyOn(f.journal,'load').mockImplementationOnce(async address=>{const result=await original(address);entered();await new Promise<void>(resolve=>{finish=resolve;});return result;});
 const first=f.controller.bind(f.host,[r]);await started;await f.controller.bind(other.host,[r]);finish();await first;
 expect(f.controller.getSnapshot()).toMatchObject({identity:other.host.identity,items:{},checking:false});expect(other.host.denied).not.toHaveBeenCalled();
});
it('lets new inbox rows and a newer empty draft win over an earlier read',async()=>{
 const f=await fixture(),r=row(),rows=[r];await f.save(r,{text:'Earlier draft'});await f.controller.bind(f.host,rows);
 const original=f.journal.load.bind(f.journal);let finish!:()=>void,entered!:()=>void;const started=new Promise<void>(resolve=>{entered=resolve;});
 vi.spyOn(f.journal,'load').mockImplementationOnce(async address=>{const result=await original(address);entered();await new Promise<void>(resolve=>{finish=resolve;});return result;});
 const older=f.controller.refresh();await started;await f.save(r,{text:''});await vi.waitFor(()=>expect(f.controller.getSnapshot()).toMatchObject({items:{},checking:false}));finish();await older;
 expect(f.controller.getSnapshot().items).toEqual({});await f.controller.bind(f.host,[]);expect(f.controller.getSnapshot().items).toEqual({});
});
it.each(['before','after'] as const)('denies disclosure when account authorization fails %s the local read, then recovers explicitly',async phase=>{
 const f=await fixture(),r=row();await f.save(r,{text:'Private draft'});const load=vi.spyOn(f.journal,'load');
 if(phase==='after')vi.mocked(f.host.recovery.authorize).mockResolvedValueOnce();
 vi.mocked(f.host.recovery.authorize).mockRejectedValueOnce(new WorkspaceApiError(403));await f.controller.bind(f.host,[r]);
 expect(f.controller.getSnapshot().items).toEqual({});expect(f.controller.getSnapshot().error).toContain('could not be checked');expect(f.host.denied).toHaveBeenCalledOnce();expect(load).toHaveBeenCalledTimes(phase==='before'?0:1);
 await f.controller.refresh();expect(f.controller.getSnapshot()).toMatchObject({items:{[key(r)]:'text'},error:'',checking:false});
});
it('reports local storage failure as unknown and keeps the retained draft for a later retry',async()=>{
 const f=await fixture(),r=row();await f.save(r,{text:'Retained draft'});vi.spyOn(f.journal,'load').mockRejectedValueOnce(new Error('Invented storage unavailable'));
 await f.controller.bind(f.host,[r]);expect(f.controller.getSnapshot()).toMatchObject({items:{},checking:false});expect(f.controller.getSnapshot().error).toContain('saved text is retained');
 await f.controller.refresh();expect(f.controller.getSnapshot().items[key(r)]).toBe('text');
});
it('does not publish a late authorization failure into a replacement account',async()=>{
 const f=await fixture(),other=await fixture(),r=row();let reject!:(cause:Error)=>void;
 vi.mocked(f.host.recovery.authorize).mockImplementationOnce(()=>new Promise((_resolve,no)=>{reject=no;}));const old=f.controller.bind(f.host,[r]);
 await f.controller.bind(other.host,[r]);reject(new WorkspaceApiError(403));await old;
 expect(f.host.denied).not.toHaveBeenCalled();expect(f.controller.getSnapshot()).toMatchObject({identity:other.host.identity,error:'',items:{}});
});
it('clears native background presence and cancels an in-flight local read until fresh authorization on return',async()=>{
 const f=await fixture(),r=row(),rows=[r];f.host.identity={mode:'clerk_jwt',getToken:async()=>null,nativeSession:{revision:teamUuid(10),isCurrent:()=>true}};
 await f.save(r,{text:'Invented native draft'});await f.controller.bind(f.host,rows);expect(f.controller.getSnapshot().items[key(r)]).toBe('text');
 const original=f.journal.load.bind(f.journal);let finish!:()=>void,entered!:()=>void;const started=new Promise<void>(resolve=>{entered=resolve;});
 vi.spyOn(f.journal,'load').mockImplementationOnce(async address=>{const value=await original(address);entered();await new Promise<void>(resolve=>{finish=resolve;});return value;});
 const older=f.controller.refresh();await started;notifyNativeWorkspaceForeground(f.host.identity,false);
 expect(f.controller.getSnapshot()).toMatchObject({items:{},checking:false});finish();await older;
 expect(f.controller.getSnapshot()).toMatchObject({items:{},checking:false});const count=vi.mocked(f.host.recovery.authorize).mock.calls.length;
 await f.save(r,{text:'Retained during native background'});expect(f.host.recovery.authorize).toHaveBeenCalledTimes(count);
 notifyNativeWorkspaceForeground(f.host.identity,true);await vi.waitFor(()=>expect(f.controller.getSnapshot()).toMatchObject({items:{[key(r)]:'text'},checking:false}));
 expect(f.host.recovery.authorize).toHaveBeenCalledTimes(count+2);expect(f.host.denied).not.toHaveBeenCalled();
});
it('starts withheld in a suspended native scene and ignores that scene after account replacement',async()=>{
 const f=await fixture(),other=await fixture(),r=row();f.host.identity={mode:'clerk_jwt',getToken:async()=>null,nativeSession:{revision:teamUuid(11),isCurrent:()=>true}};
 await f.save(r,{text:'Old account native draft'});notifyNativeWorkspaceForeground(f.host.identity,false);await f.controller.bind(f.host,[r]);
 expect(f.controller.getSnapshot()).toMatchObject({items:{},checking:false});expect(f.host.recovery.authorize).not.toHaveBeenCalled();
 let reject!:(cause:Error)=>void;vi.mocked(f.host.recovery.authorize).mockImplementationOnce(()=>new Promise((_resolve,no)=>{reject=no;}));
 notifyNativeWorkspaceForeground(f.host.identity,true);expect(f.host.recovery.authorize).toHaveBeenCalledOnce();
 await other.save(r,{text:'New account draft'});await f.controller.bind(other.host,[r]);reject(new WorkspaceApiError(403));await Promise.resolve();
 notifyNativeWorkspaceForeground(f.host.identity,false);notifyNativeWorkspaceForeground(f.host.identity,true);
 expect(f.controller.getSnapshot()).toMatchObject({identity:other.host.identity,items:{[key(r)]:'text'},checking:false,error:''});expect(f.host.denied).not.toHaveBeenCalled();
 expect(f.host.recovery.authorize).toHaveBeenCalledOnce();
});
it('announces only confirmed journal changes and isolates observer failure from a save',async()=>{
 const values=new Map<string,unknown>(),changed=vi.fn(),store:DraftStore={read:async address=>structuredClone(values.get(address)??{revision:null,value:null}) as Awaited<ReturnType<DraftStore['read']>>,write:vi.fn(async(address,_expected,value)=>{const record={revision:'1',value};values.set(address,record);return record;}),close:()=>{}};
 const journal=new DraftJournal(store),r=row(),address=editorAddress(r.workspace_id,'conversation:chief');cleanups.push(()=>journal.close());
 journal.subscribe(changed);journal.subscribe(()=>{throw new Error('Observer failure');});await journal.load(address);expect(changed).not.toHaveBeenCalled();
 await journal.persist(address,{kind:'editor',workspaceId:r.workspace_id,editor:'conversation:chief',data:{text:'Invented draft'},pending:null});expect(changed).toHaveBeenCalledExactlyOnceWith(address);
 vi.mocked(store.write).mockRejectedValueOnce(new Error('Unconfirmed different write'));await expect(journal.persist(address,null)).rejects.toThrow();expect(changed).toHaveBeenCalledTimes(1);
 journal.close();expect(changed).toHaveBeenLastCalledWith(null);
});
