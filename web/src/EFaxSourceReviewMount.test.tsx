import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EFaxSourceReviewMount,type EFaxSourceReviewMountProps} from './EFaxSourceReviewMount';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal,editorAddress,type EditorKind} from './draft-journal';
import {openDraftStore,privateDraftScope} from './draft-store';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {efaxSourceApi,efaxSourceRequestHash,type EFaxSourceReviewRequest} from './efax-inbound-source-api';
import {emptyEFaxSourceRecovery,type EFaxSourceRecovery} from './efax-inbound-source-recovery';
import {WorkspaceApiError,type Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const uuid=(n:number)=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0'),scope={box_id:uuid(1),owner_id:uuid(2),workspace_id:uuid(3)};
const identity={mode:'clerk_jwt' as const,getToken:async()=>null},opaque='e'.repeat(64);
const editor:EditorKind=`efax-source-review:${uuid(4)}`,address=editorAddress(scope.workspace_id,editor);
let root:Root,host:HTMLDivElement,idb:IDBFactory,namespace:string,journal:DraftJournal,context:EditorRecoveryAccess,account:AccountIdentity,props:EFaxSourceReviewMountProps,record:EFaxSourceRecovery;
const button=(s:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===s);
async function wait(check:()=>void|Promise<void>){for(let n=0;n<200;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{await check();done=true;}catch{}});if(done)return;}await check();}
async function click(label:string){await wait(()=>expect(button(label)?.disabled,label).toBe(false));await act(async()=>button(label)!.click());await wait(()=>expect(host.textContent).not.toContain('Waiting for the current fax passage operation'));}
const store=()=>openDraftStore({scope:namespace,native:false,indexedDB:idb,crypto:webcrypto});
async function readSaved(target=address){const reader=new DraftJournal(await store());try{return await reader.load(target);}finally{reader.close();}}
async function render(c:EditorRecoveryAccess|null|undefined=context,p=props){await act(async()=>root.render(<EditorRecoveryContext.Provider value={c}><EFaxSourceReviewMount {...p}/></EditorRecoveryContext.Provider>));}
async function enterPassage(){await wait(()=>expect(host.querySelector('textarea')).toBeTruthy());await act(async()=>{
 const text=host.querySelector<HTMLTextAreaElement>('textarea')!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(text,record.passage);text.dispatchEvent(new Event('input',{bubbles:true}));
 const pages=host.querySelector<HTMLInputElement>('input[aria-label="Pages used"]')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(pages,'1, 3');pages.dispatchEvent(new Event('input',{bubbles:true}));
 });await act(async()=>host.querySelectorAll<HTMLInputElement>('input[type=checkbox]').forEach(c=>c.click()));}
async function seed(target=address,kind:EditorKind=editor,r=record){await journal.load(target);await journal.persist(target,{kind:'editor',workspaceId:scope.workspace_id,editor:kind,data:r,pending:null});}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();namespace=await privateDraftScope(opaque,'http://127.0.0.1:8000',webcrypto);journal=new DraftJournal(await store());
 context={journal,workspaceId:scope.workspace_id,recoveryScope:opaque,authorize:vi.fn(async()=>({id:scope.workspace_id,revision:5}) as Workspace),denied:vi.fn()};
 account={contract_version:1,box_id:scope.box_id,actor_id:scope.owner_id,recovery_scope:opaque};
 props={identity,enabled:true,offered:{operation_id:uuid(4),document_sha256:'a'.repeat(64),pages:3,label:'Invented acquired fax'},visit:{id:scope.workspace_id,label:'Invented walk-in · DOB optional',revision:5},onAuthenticationLost:vi.fn(),onRefreshDocument:vi.fn(async()=>props.offered)};
 const request:EFaxSourceReviewRequest={expected_revision:5,idempotency_key:uuid(6),operation_id:uuid(4),document_sha256:'a'.repeat(64),passage:'Invented private fax passage. DOB and trial eligibility unknown.',page_numbers:[1,3],reviewed_patient:true,reviewed_exact_document:true,reviewed_exact_text:true,reviewed_untrusted_source:true};
 record={...emptyEFaxSourceRecovery(scope,props.offered,props.visit),passage:request.passage,page_numbers:request.page_numbers,pending:{request,request_sha256:await efaxSourceRequestHash(scope,request)}};
 vi.spyOn(accountIdentityApi,'read').mockImplementation(async()=>structuredClone(account));
 vi.spyOn(efaxSourceApi,'resolve').mockImplementation(async(_i,s,r)=>({contract_version:1,scope:s,idempotency_key:r.idempotency_key,state:'not_found'}));vi.spyOn(efaxSourceApi,'review');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();journal.close();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('stays closed when disabled or without exact verified visit recovery namespace',async()=>{
 const load=vi.spyOn(journal,'load');await render(context,{...props,enabled:false});expect(accountIdentityApi.read).not.toHaveBeenCalled();expect(load).not.toHaveBeenCalled();
 await render(null);expect(host.textContent).toContain('Private saved-work storage');await render({...context,recoveryScope:undefined});expect(accountIdentityApi.read).not.toHaveBeenCalled();
 await render({...context,workspaceId:uuid(99)});expect(host.textContent).toContain('Private saved-work storage');expect(load).not.toHaveBeenCalled();
});
it('checks actual current workspace and account namespace before encrypted load',async()=>{
 const load=vi.spyOn(journal,'load');vi.mocked(context.authorize).mockResolvedValueOnce({id:uuid(99),revision:5} as Workspace);await render();await wait(()=>expect(host.textContent).toContain('could not be opened'));expect(load).not.toHaveBeenCalled();expect(accountIdentityApi.read).not.toHaveBeenCalled();
 vi.mocked(accountIdentityApi.read).mockResolvedValueOnce({...account,recovery_scope:'f'.repeat(64)});await render(context,{...props,offered:{...props.offered,label:'Invented second offer'}});await wait(()=>expect(host.textContent).toContain('could not be opened'));expect(load).not.toHaveBeenCalled();
});
it('preserves exact pending request encrypted through independent reopen, restore and DB-only resolve',async()=>{
 await seed();const before=await readSaved();await render();await click('Restore saved fax passage');expect(host.textContent).not.toContain(record.passage);expect(efaxSourceApi.review).not.toHaveBeenCalled();await click('Check saved fax review');expect(efaxSourceApi.resolve).toHaveBeenCalledWith(identity,scope,record.pending!.request,expect.any(AbortSignal));expect(await readSaved()).toEqual(before);
 await act(async()=>root.render(null));await render();await wait(()=>expect(button('Restore saved fax passage')).toBeDefined());expect(efaxSourceApi.resolve).toHaveBeenCalledOnce();expect(efaxSourceApi.review).not.toHaveBeenCalled();
 const db=await new Promise<IDBDatabase>((resolve,reject)=>{const r=idb.open('cosmas-private-drafts:v1:'+namespace);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
 const rows=await new Promise<unknown[]>((resolve,reject)=>{const r=db.transaction('sealed-drafts').objectStore('sealed-drafts').getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
 expect(JSON.stringify(rows)).not.toContain(record.passage);expect(JSON.stringify(rows)).not.toContain(record.pending!.request.idempotency_key);expect(JSON.stringify(rows)).not.toContain(record.offered.document_sha256);db.close();
});
it('persists the exact encrypted command before source POST and reopens a lost reply without resubmitting',async()=>{
 await render();await enterPassage();let dispatched:EFaxSourceReviewRequest|undefined;
 vi.mocked(efaxSourceApi.review).mockImplementationOnce(async(_identity,actualScope,request)=>{
  expect(actualScope).toEqual(scope);const stored=await readSaved();expect(stored?.kind).toBe('editor');if(stored?.kind!=='editor')throw new Error('Missing encrypted command');
  const data=stored.data as EFaxSourceRecovery;expect(data.pending!.request).toEqual(request);expect(data.pending!.request_sha256).toBe(await efaxSourceRequestHash(scope,request));
  expect(stored.pending).toBeNull();dispatched=structuredClone(request);throw new WorkspaceApiError(503);
 });
 await click('Save reviewed fax passage for this visit');expect(dispatched).toBeDefined();expect(efaxSourceApi.review).toHaveBeenCalledOnce();const stored=await readSaved();
 await act(async()=>root.render(null));await render();await click('Restore saved fax passage');expect(host.textContent).not.toContain(record.passage);await click('Check saved fax review');
 expect(efaxSourceApi.resolve).toHaveBeenCalledWith(identity,scope,dispatched,expect.any(AbortSignal));expect(efaxSourceApi.review).toHaveBeenCalledOnce();expect(await readSaved()).toEqual(stored);
});
it('operation-qualified addresses retain a different document pending request without replacement',async()=>{
 await seed();const old=await readSaved();const offered={...props.offered,operation_id:uuid(40)},kind:EditorKind=`efax-source-review:${uuid(40)}`,otherAddress=editorAddress(scope.workspace_id,kind);
 await render(context,{...props,offered});await wait(()=>expect(host.querySelector('textarea')).toBeTruthy());expect(await readSaved()).toEqual(old);expect(await readSaved(otherAddress)).toBeNull();
});
it('rejects foreign owner recovery without deleting the encrypted record',async()=>{
 const foreignScope={...scope,owner_id:uuid(99)},foreignRequest=record.pending!.request;
 const foreign={...record,scope:foreignScope,pending:{request:foreignRequest,request_sha256:await efaxSourceRequestHash(foreignScope,foreignRequest)}};await seed(address,editor,foreign);const before=await readSaved();await render();
 await wait(()=>expect(host.textContent).toContain('could not be opened'));expect(await readSaved()).toEqual(before);expect(button('Restore saved fax passage')).toBeUndefined();expect(efaxSourceApi.review).not.toHaveBeenCalled();
});
it('rechecks owner before every encrypted load and refuses changed identity before storage access',async()=>{
 const load=vi.spyOn(journal,'load');vi.mocked(accountIdentityApi.read).mockResolvedValueOnce(account).mockResolvedValue({...account,actor_id:uuid(99)});await render();await wait(()=>expect(host.textContent).toContain('could not be opened'));expect(load).not.toHaveBeenCalled();expect(props.onAuthenticationLost).toHaveBeenCalled();
});
it.each([401,403,404,426])('clears the mounted source access after explicit account denial %s',async(status)=>{
 vi.mocked(accountIdentityApi.read).mockRejectedValueOnce(new WorkspaceApiError(status));await render();await wait(()=>expect(host.textContent).toContain('could not be opened'));expect(props.onAuthenticationLost).toHaveBeenCalled();expect(context.denied).toHaveBeenCalled();expect(host.querySelector('textarea')).toBeNull();
});
it('rejects journal editor whose operation does not match exact acquired document',async()=>{
 const changed={...record,offered:{...record.offered,operation_id:uuid(99)}};await expect(seed(address,editor,changed)).rejects.toThrow();expect(await readSaved()).toBeNull();
 const otherEditor:EditorKind=`efax-source-review:${uuid(99)}`;await expect(seed(editorAddress(scope.workspace_id,otherEditor),otherEditor,record)).rejects.toThrow();
});
it('fences delayed account proof after document replacement before journal load',async()=>{
 const load=vi.spyOn(journal,'load');let finish!:(a:AccountIdentity)=>void;vi.mocked(accountIdentityApi.read).mockReturnValueOnce(new Promise(r=>{finish=r;}));await render();await wait(()=>expect(accountIdentityApi.read).toHaveBeenCalledOnce());
 await render(context,{...props,offered:{...props.offered,document_sha256:'f'.repeat(64)}});await act(async()=>finish(account));await wait(()=>expect(host.querySelector('textarea')).toBeTruthy());
 expect(load).toHaveBeenCalledOnce();expect(efaxSourceApi.review).not.toHaveBeenCalled();
});
it('fences a delayed encrypted load after visit replacement and retains the original journal',async()=>{
 await seed();const before=await readSaved();const original=context.journal.load.bind(context.journal);let finish!:(v:Awaited<ReturnType<typeof original>>)=>void;
 vi.spyOn(journal,'load').mockImplementationOnce(()=>new Promise(r=>{finish=r;}));await render();await wait(()=>expect(journal.load).toHaveBeenCalledOnce());
 const changedContext={...context,workspaceId:uuid(33),authorize:vi.fn(async()=>({id:uuid(33),revision:1}) as Workspace)};
 await render(changedContext,{...props,visit:{id:uuid(33),label:'Invented second walk-in',revision:1}});await act(async()=>finish(before));
 await wait(()=>expect(host.querySelector('textarea')).toBeTruthy());expect(button('Restore saved fax passage')).toBeUndefined();expect(host.textContent).not.toContain(record.passage);
 expect(await readSaved()).toEqual(before);expect(efaxSourceApi.review).not.toHaveBeenCalled();
});
it('preserves journal when identity changes before an authorized local rewrite',async()=>{
 await seed();const before=await readSaved();await render();await click('Restore saved fax passage');await click('Check saved fax review');await click('Prepare a new review for current visit');await click('Check exact acquired PDF');
 const afterReset=await readSaved();vi.mocked(accountIdentityApi.read).mockResolvedValue({...account,actor_id:uuid(99)});await click('Save passage draft privately');expect(await readSaved()).toEqual(afterReset);expect(before).not.toBeNull();expect(props.onAuthenticationLost).toHaveBeenCalled();expect(efaxSourceApi.review).not.toHaveBeenCalled();
});
