import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {GoogleMessageMount} from './GoogleMessageMount';
import {AccountRecoveryContext,type AccountRecoveryAccess} from './account-recovery';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {openDraftStore,privateDraftScope} from './draft-store';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {googleMessageApi,type GoogleMessageReceipt} from './google-message-api';
import {emptyGoogleMessageRecovery,type GoogleMessageRecoveryRecord} from './google-message-recovery';
import {teamCanonical} from './team-setup-request';
import {WorkspaceApiError} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const uuid=(n:number)=>`00000000-0000-4000-8000-${n.toString().padStart(12,'0')}`;
const identity={mode:'clerk_jwt' as const,getToken:async()=>null},opaque='e'.repeat(64),address=accountEditorAddress('google-messages');
const sha=async(s:string)=>[...new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))].map(n=>n.toString(16).padStart(2,'0')).join('');
let root:Root,host:HTMLDivElement,journal:DraftJournal,context:AccountRecoveryAccess,idb:IDBFactory,namespace:string,account:AccountIdentity,denied:ReturnType<typeof vi.fn>,record:GoogleMessageRecoveryRecord;
const button=(s:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===s);
async function wait(check:()=>void|Promise<void>){for(let i=0;i<200;i++){let ok=false;await act(async()=>{await new Promise(resolve=>setTimeout(resolve,2));try{await check();ok=true;}catch{}});if(ok)return;}await check();}
async function click(label:string){await wait(()=>{expect(button(label)).toBeTruthy();expect(button(label)!.disabled).toBe(false);});await act(async()=>button(label)!.click());await wait(()=>expect(host.textContent).not.toContain('Waiting for the current email operation'));}
async function render(enabled=true,c:AccountRecoveryAccess|null=context){await act(async()=>root.render(<AccountRecoveryContext.Provider value={c}><GoogleMessageMount identity={identity} workspace={{id:uuid(9),label:'Invented visit without DOB',revision:5}} enabled={enabled} onSaved={vi.fn()} onAuthenticationLost={denied}/></AccountRecoveryContext.Provider>));}
const store=()=>openDraftStore({scope:namespace,native:false,indexedDB:idb,crypto:webcrypto});
async function reread(){const reader=new DraftJournal(await store());try{return await reader.load(address);}finally{reader.close();}}
async function seed(value:GoogleMessageRecoveryRecord){await journal.load(address);await journal.persist(address,{kind:'account-editor',editor:'google-messages',data:value,pending:null});}
beforeEach(async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();namespace=await privateDraftScope(opaque,'http://127.0.0.1:8000',webcrypto);journal=new DraftJournal(await store());context={journal,recoveryScope:opaque,authorize:vi.fn(async()=>{})};
 account={contract_version:1,box_id:uuid(101),actor_id:uuid(102),recovery_scope:opaque};denied=vi.fn();vi.spyOn(accountIdentityApi,'read').mockImplementation(async()=>structuredClone(account));
 const observation={kind:'mail' as const,account:{label:'Invented doctor',email:'doctor@example.invalid'},items:[{id:'email_1',thread_id:'thread_1',subject:'Invented incoming email',sender:'sender@example.invalid',received_at:'2026-10-02T12:00:00Z',is_read:false}],more:false,observed_at:'2026-10-02T12:05:00Z'};
 const list:GoogleMessageReceipt={read_id:uuid(1),read_key:uuid(2),kind:'list',observation_id:uuid(1),source_sha256:'a'.repeat(64),payload_sha256:await sha(teamCanonical(observation)),status:'observed',message:null,observation};
 record={...emptyGoogleMessageRecovery({box_id:account.box_id,actor_id:account.actor_id}),list,selected_message_id:'email_1',pending:{kind:'message',request:{action:'read',idempotency_key:uuid(3),observation_id:list.read_id,observation_sha256:list.source_sha256,message_id:'email_1',thread_id:'thread_1'},workspace:null,list_anchor:list,message_anchor:null}};
 vi.spyOn(googleMessageApi,'status').mockResolvedValue({contract_version:1,state:'connected',full_mail_read:true,account:observation.account});vi.spyOn(googleMessageApi,'list');vi.spyOn(googleMessageApi,'read');vi.spyOn(googleMessageApi,'resolve').mockResolvedValue({status:'unconfirmed',kind:'message',read_key:uuid(3),read_id:uuid(4)});
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();journal.close();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('remains dark without identity, storage or provider reads when disabled',async()=>{
 const load=vi.spyOn(journal,'load');await render(false);expect(host.textContent).toBe('');expect(accountIdentityApi.read).not.toHaveBeenCalled();expect(load).not.toHaveBeenCalled();expect(googleMessageApi.status).not.toHaveBeenCalled();
});
it('requires an exact opaque signed recovery namespace before loading private email',async()=>{
 await render(true,{...context,recoveryScope:'invalid'});expect(host.textContent).toContain('Private saved-work storage');expect(accountIdentityApi.read).not.toHaveBeenCalled();
});
it('opens the current encrypted journal without an automatic Google read',async()=>{
 await render();await wait(()=>expect(button('Check email access')?.disabled).toBe(false));expect(accountIdentityApi.read).toHaveBeenCalled();expect(googleMessageApi.status).not.toHaveBeenCalled();expect(googleMessageApi.list).not.toHaveBeenCalled();
});
it('restores and preserves an exact encrypted pending request through a fresh reader and remount',async()=>{
 await seed(record);await render();await click('Restore saved email work');expect(googleMessageApi.read).not.toHaveBeenCalled();expect((await reread())?.kind).toBe('account-editor');
 await click('Check saved email result');expect(googleMessageApi.resolve).toHaveBeenCalledWith(identity,uuid(3),'message',expect.anything());expect(googleMessageApi.read).not.toHaveBeenCalled();
 const before=await reread();await act(async()=>root.render(null));expect(await reread()).toEqual(before);await render();await wait(()=>expect(button('Restore saved email work')).toBeTruthy());expect(googleMessageApi.resolve).toHaveBeenCalledTimes(1);
});
it('preserves a confirmed masked source receipt in encrypted storage and never displays it as current work after remount',async()=>{
 const text='Invented private email source.',contentSha=await sha(text),message:GoogleMessageReceipt={read_id:uuid(4),read_key:uuid(3),kind:'message',observation_id:record.list!.read_id,
  source_sha256:'b'.repeat(64),payload_sha256:'c'.repeat(64),status:'complete',observation:null,message:{message_id:'email_1',thread_id:'thread_1',history_id:null,
   subject:'Invented private subject',sender:'sender@example.invalid',received_at:'2026-10-02T12:00:00Z',is_read:false,observed_at:'2026-10-02T12:06:00Z',status:'complete',content:text,reason:null,raw_sha256:'d'.repeat(64),content_sha256:contentSha}};
 const masked={...record,pending:null,message,saved:{workspace_id:uuid(9),entry_id:uuid(10),entry_revision:6,source_sha256:message.source_sha256,content_sha256:contentSha,request_sha256:'f'.repeat(64),source_withheld:true}};
 await seed(masked);const before=await reread();await render();await click('Restore saved email work');expect(host.querySelector('pre')).toBeNull();
 expect(host.textContent).not.toContain(text);expect(button('Ask Chief about this email')).toBeUndefined();expect(host.textContent).toContain('exact email source save is confirmed');
 await act(async()=>root.render(null));expect(await reread()).toEqual(before);await render();await click('Restore saved email work');expect(host.querySelector('pre')).toBeNull();
 expect(googleMessageApi.read).not.toHaveBeenCalled();expect(googleMessageApi.resolve).not.toHaveBeenCalled();expect(await reread()).toEqual(before);
});
it('withholds a foreign actor record even if someone placed it in this encrypted namespace',async()=>{
 await seed({...record,scope:{...record.scope,actor_id:uuid(999)}});const before=await reread();await render();await wait(()=>expect(host.textContent).toContain('Private saved email work is unavailable'));
 expect(host.textContent).not.toContain('Invented incoming email');expect(await reread()).toEqual(before);expect(button('Restore saved email work')).toBeUndefined();
});
it('rechecks actor and scope before exposing a saved request on Restore',async()=>{
 await seed(record);await render();await wait(()=>expect(button('Restore saved email work')).toBeTruthy());account={...account,actor_id:uuid(999)};await click('Restore saved email work');
 expect(denied).toHaveBeenCalled();expect(host.textContent).not.toContain('Invented incoming email');expect(googleMessageApi.read).not.toHaveBeenCalled();expect((await reread())?.kind==='account-editor'&&(await reread() as {data:unknown}).data).toEqual(record);
});
it.each([401,403,404,426])('removes private controls after signed access denial (%s)',async status=>{
 vi.mocked(accountIdentityApi.read).mockRejectedValueOnce(new WorkspaceApiError(status));await render();await wait(()=>expect(host.textContent).toContain('could not be opened'));expect(denied).toHaveBeenCalled();expect(host.querySelector('pre,input')).toBeNull();expect(googleMessageApi.status).not.toHaveBeenCalled();
});
it('rejects a fresh actor change before local journal reads',async()=>{
 const load=vi.spyOn(journal,'load');vi.mocked(accountIdentityApi.read).mockResolvedValueOnce(account).mockResolvedValue({...account,actor_id:uuid(999)});await render();await wait(()=>expect(host.textContent).toContain('saved email work is unavailable'));expect(load).not.toHaveBeenCalled();expect(denied).toHaveBeenCalled();
});
