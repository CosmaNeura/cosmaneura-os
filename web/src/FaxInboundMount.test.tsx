import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {FaxInboundMount} from './FaxInboundMount';
import {AccountRecoveryContext,type AccountRecoveryAccess} from './account-recovery';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {openDraftStore,privateDraftScope} from './draft-store';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {faxInboundApi,type FaxPending} from './fax-inbound-api';
import {emptyFaxRecovery,type FaxRecovery} from './fax-inbound-recovery';
import {faxScope,faxUuid,faxStatus} from './fax-inbound-fixtures.test-support';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
import {WorkspaceApiError} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>null},opaque='e'.repeat(64),address=accountEditorAddress('fax-inbound');
let root:Root,host:HTMLDivElement,idb:IDBFactory,namespace:string,journal:DraftJournal,context:AccountRecoveryAccess,account:AccountIdentity,denied:ReturnType<typeof vi.fn>,record:FaxRecovery;
const button=(s:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===s);
async function wait(check:()=>void|Promise<void>){for(let i=0;i<200;i++){let ok=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{await check();ok=true;}catch{}});if(ok)return;}await check();}
async function click(label:string){await wait(()=>expect(button(label)?.disabled).toBe(false));await act(async()=>button(label)!.click());await wait(()=>expect(host.textContent).not.toContain('Checking the current request…'));}
const store=()=>openDraftStore({scope:namespace,native:false,indexedDB:idb,crypto:webcrypto});
async function readSaved(){const reader=new DraftJournal(await store());try{return await reader.load(address);}finally{reader.close();}}
async function render(enabled=true,c:AccountRecoveryAccess|null=context){await act(async()=>root.render(<AccountRecoveryContext.Provider value={c}><FaxInboundMount identity={identity} enabled={enabled} onAuthenticationLost={denied}/></AccountRecoveryContext.Provider>));}
async function seed(){await journal.load(address);await journal.persist(address,{kind:'account-editor',editor:'fax-inbound',data:record,pending:null});}
beforeEach(async()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);idb=new IDBFactory();namespace=await privateDraftScope(opaque,'http://127.0.0.1:8000',webcrypto);journal=new DraftJournal(await store());context={journal,recoveryScope:opaque,authorize:vi.fn(async()=>{})};account={contract_version:1,box_id:faxScope.box_id,actor_id:faxScope.owner_id,recovery_scope:opaque};denied=vi.fn();vi.spyOn(accountIdentityApi,'read').mockImplementation(async()=>structuredClone(account));vi.spyOn(faxInboundApi,'status').mockResolvedValue(faxStatus);vi.spyOn(faxInboundApi,'command');vi.spyOn(faxInboundApi,'resolve').mockImplementation(async(_i,_s,p)=>({contract_version:1,state:'not_found',idempotency_key:p.request.idempotency_key}));vi.spyOn(faxInboundApi,'document');
 const p:FaxPending={kind:'observe',request:{idempotency_key:faxUuid(40),grant_id:faxUuid(4),starts_at:'2026-09-25T18:00:00Z',ends_at:'2026-10-02T18:00:00Z',limit:25}};record={...emptyFaxRecovery(faxScope),pending:p};host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();journal.close();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('stays default-closed without private storage or API calls',async()=>{const load=vi.spyOn(journal,'load');await render(false);expect(host.textContent).toContain('not enabled in this app build');expect(accountIdentityApi.read).not.toHaveBeenCalled();expect(load).not.toHaveBeenCalled();expect(faxInboundApi.status).not.toHaveBeenCalled();});
it('requires exact signed namespace and owner before loading encrypted records',async()=>{await render(true,{...context,recoveryScope:'invalid'});expect(host.textContent).toContain('Private saved-work storage');expect(accountIdentityApi.read).not.toHaveBeenCalled();});
it('preserves pending keys encrypted through independent journal reopen and remount with no automatic provider read',async()=>{
 await seed();const before=await readSaved();await render();await click('Restore received-fax work');expect(faxInboundApi.command).not.toHaveBeenCalled();await click('Check saved receiving result');expect(faxInboundApi.resolve).toHaveBeenCalledWith(identity,faxScope,record.pending,expect.any(AbortSignal));expect(await readSaved()).toEqual(before);
 await act(async()=>root.render(null));await render();await wait(()=>expect(button('Restore received-fax work')).toBeDefined());expect(faxInboundApi.resolve).toHaveBeenCalledOnce();expect(faxInboundApi.document).not.toHaveBeenCalled();
 const database=await new Promise<IDBDatabase>((resolve,reject)=>{const request=idb.open('cosmas-private-drafts:v1:'+namespace);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});const rows=await new Promise<unknown[]>((resolve,reject)=>{const request=database.transaction('sealed-drafts').objectStore('sealed-drafts').getAll();request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});expect(JSON.stringify(rows)).not.toContain(record.pending!.request.idempotency_key);expect(JSON.stringify(rows)).not.toContain('2026-09-25T18:00:00Z');database.close();
});
it('withholds a foreign owner record without deleting encrypted recovery',async()=>{record={...record,scope:{...faxScope,owner_id:faxUuid(99)}};await seed();const before=await readSaved();await render();await wait(()=>expect(host.textContent).toContain('could not be opened'));expect(await readSaved()).toEqual(before);expect(faxInboundApi.command).not.toHaveBeenCalled();expect(button('Restore received-fax work')).toBeUndefined();});
it('rechecks owner before every journal load and never adopts a changed actor',async()=>{const load=vi.spyOn(journal,'load');vi.mocked(accountIdentityApi.read).mockResolvedValueOnce(account).mockResolvedValue({...account,actor_id:faxUuid(99)});await render();await wait(()=>expect(host.textContent).toContain('could not be opened'));expect(load).not.toHaveBeenCalled();expect(denied).toHaveBeenCalled();});
it.each([401,403,404,426])('hides access controls after signed denial %s',async status=>{vi.mocked(accountIdentityApi.read).mockRejectedValueOnce(new WorkspaceApiError(status));await render();await wait(()=>expect(host.textContent).toContain('could not be opened'));expect(denied).toHaveBeenCalled();expect(faxInboundApi.command).not.toHaveBeenCalled();expect(host.querySelector('input,select,a')).toBeNull();});
it('rejects an unreviewed image request journal without exact prior proposal and approval',async()=>{record={...record,pending:{kind:'acquire',request:{idempotency_key:faxUuid(41),ticket_id:faxUuid(7),revision_id:faxUuid(9),expected_version:2,approval_sha256:'e'.repeat(64)}}};await expect(seed()).rejects.toThrow();});

it('preserves the exact unknown request through feature closure, identity replacement and foreground return',async()=>{
 await seed();const before=await readSaved();await render();await click('Restore received-fax work');
 await act(async()=>notifyNativeWorkspaceForeground(identity,false));expect(host.textContent).not.toContain('2026-09-25');expect(await readSaved()).toEqual(before);
 await act(async()=>notifyNativeWorkspaceForeground(identity,true));await wait(()=>expect(button('Restore received-fax work')).toBeDefined());expect(faxInboundApi.command).not.toHaveBeenCalled();
 await render(false);expect(host.textContent).toContain('not enabled');expect(await readSaved()).toEqual(before);await render();await click('Restore received-fax work');
 const next={mode:'clerk_jwt' as const,getToken:async()=>null};account={...account,actor_id:faxUuid(99)};
 await act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><FaxInboundMount identity={next} enabled onAuthenticationLost={denied}/></AccountRecoveryContext.Provider>));
 await wait(()=>expect(host.textContent).toContain('could not be opened'));expect(button('Check saved receiving result')).toBeUndefined();expect(await readSaved()).toEqual(before);expect(faxInboundApi.command).not.toHaveBeenCalled();
});
