import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EhrReadMount} from './EhrReadMount';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal,editorAddress} from './draft-journal';
import {openDraftStore,type DraftValue} from './draft-store';
import {accountIdentityApi} from './account-identity-api';
import {ehrReadApi,ehrProviderFields,ehrHash,ehrSourceContent} from './ehr-read-api';
import {emptyEhrReadRecovery,validateEhrReadRecovery,type EhrReadRecovery} from './ehr-read-recovery';
import {ehrBinding,ehrScope,ehrUuid,ehrVisit,ehrWindowReceipt,ehrVerifiedReceipt,ehrReviewBody,ehrReviewResult,ehrProblemsReceipt,ehrProblemsCommand} from './ehr-read-fixtures.test-support';
import type {Workspace} from './workspace-api';
import {WorkspaceSession} from './session/workspace-session';
import {useWorkspaceSession} from './session/use-workspace-session';
import {teamFixture} from './team-setup-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const opaque='e'.repeat(64),address=editorAddress(ehrVisit.id,'ehr-read'),identity={mode:'clerk_jwt' as const,getToken:async()=>null};
let root:Root,host:HTMLDivElement,journal:DraftJournal,context:EditorRecoveryAccess,idb:IDBFactory,denied:ReturnType<typeof vi.fn>,record:EhrReadRecovery,actor:string;
const store=()=>openDraftStore({scope:opaque,native:false,indexedDB:idb,crypto:webcrypto});
const button=(s:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===s);
async function wait(check:()=>void){for(let i=0;i<250;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function render(enabled=true,c:EditorRecoveryAccess|null=context){await act(async()=>root.render(<EditorRecoveryContext.Provider value={c}><EhrReadMount identity={identity} workspace={ehrVisit} enabled={enabled} onAuthenticationLost={denied}/></EditorRecoveryContext.Provider>));}
async function seed(){await journal.load(address);await journal.persist(address,{kind:'editor',workspaceId:ehrVisit.id,editor:'ehr-read',data:record,pending:null});}
beforeEach(async()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);idb=new IDBFactory();journal=new DraftJournal(await store());actor=ehrScope.owner_id;
 const workspace:Workspace={...ehrVisit,appointment_id:null,entries:[],work_candidates:[]};context={journal,workspaceId:ehrVisit.id,recoveryScope:opaque,authorize:vi.fn(async()=>workspace),denied:vi.fn()};denied=vi.fn();
 vi.spyOn(accountIdentityApi,'read').mockImplementation(async()=>({contract_version:1,box_id:ehrScope.box_id,actor_id:actor,recovery_scope:opaque}));vi.spyOn(ehrReadApi,'status');vi.spyOn(ehrReadApi,'execute');vi.spyOn(ehrReadApi,'resolve').mockResolvedValue({status:'unconfirmed',observation_id:ehrUuid(800),observation_key:ehrUuid(801)});
 record={...emptyEhrReadRecovery(ehrScope),binding:ehrBinding,pending:{kind:'read',request:{action:'observe',...ehrBinding,starts_at:'2026-10-25T12:00:00Z',ends_at:'2026-10-26T12:00:00Z',idempotency_key:ehrUuid(801)},anchor:null}};
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();journal.close();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('keeps the feature dark without opening identity, storage or EHR transport',async()=>{const load=vi.spyOn(journal,'load');await render(false);expect(host.textContent).toBe('');expect(accountIdentityApi.read).not.toHaveBeenCalled();expect(load).not.toHaveBeenCalled();expect(ehrReadApi.status).not.toHaveBeenCalled();});
it('retains an exact encrypted EHR command across a fresh reader and remount',async()=>{await seed();await render();await wait(()=>expect(button('Restore saved Elation work')?.disabled).toBe(false));await act(async()=>button('Restore saved Elation work')!.click());await wait(()=>expect(button('Check saved appointment result')?.disabled).toBe(false));await act(async()=>button('Check saved appointment result')!.click());await wait(()=>expect(ehrReadApi.resolve).toHaveBeenCalledOnce());expect(ehrReadApi.execute).not.toHaveBeenCalled();const fresh=new DraftJournal(await store());expect(await fresh.load(address)).toMatchObject({kind:'editor',data:record});fresh.close();await act(async()=>root.render(null));await render();await wait(()=>expect(button('Restore saved Elation work')).toBeTruthy());expect(ehrReadApi.resolve).toHaveBeenCalledOnce();});
it('refuses another actor in the same encrypted namespace and retains its ciphertext',async()=>{record={...record,scope:{...ehrScope,owner_id:ehrUuid(999)}};await seed();await render();await wait(()=>expect(host.textContent).toContain('storage could not be opened'));expect(button('Restore saved Elation work')).toBeUndefined();const fresh=new DraftJournal(await store());expect(await fresh.load(address)).toMatchObject({data:record});fresh.close();});
it('rechecks owner identity before restoring a private request',async()=>{await seed();await render();await wait(()=>expect(button('Restore saved Elation work')?.disabled).toBe(false));actor=ehrUuid(999);await act(async()=>button('Restore saved Elation work')!.click());await wait(()=>expect(denied).toHaveBeenCalled());expect(ehrReadApi.execute).not.toHaveBeenCalled();expect(ehrReadApi.resolve).not.toHaveBeenCalled();});
it('requires the exact current visit and signed private namespace',async()=>{await render(true,{...context,workspaceId:ehrUuid(999)});expect(host.textContent).toContain('Private saved-work storage for this visit');expect(accountIdentityApi.read).not.toHaveBeenCalled();await render(true,{...context,recoveryScope:'not-valid'});expect(accountIdentityApi.read).not.toHaveBeenCalled();});
it.each(['ehr-read','ehr-read:tebra'] as const)('enforces a 128 KiB data envelope at the actual encrypted %s store boundary',async editor=>{const address=editorAddress(ehrVisit.id,editor),storage=await store(),base:DraftValue={schema:1,updatedAt:'2026-10-25T12:00:00Z',body:{padding:''}},limit=131072+512;const size=new TextEncoder().encode(JSON.stringify(base)).length,value={...base,body:{padding:'x'.repeat(limit-size)}};await storage.write(address,null,value);await expect(storage.write(address,'1',{...value,body:{padding:value.body.padding+'x'}})).rejects.toMatchObject({code:'invalid'});storage.close();const fresh=await store();expect((await fresh.read(address)).value).toEqual(value);for(const near of [address+':extra',address.replace(':ehr-read',':ehr'),address.replace('editor:','account-editor:')])await expect(fresh.read(near)).rejects.toMatchObject({code:'invalid'});fresh.close();});
it.each(['ehr-read','ehr-read:tebra'] as const)('retains the same bounded %s frame in the native SecureQueue namespace',async editor=>{const address=editorAddress(ehrVisit.id,editor),records=new Map<string,{key:string;data:string;revision:string}>(),plugin={get:async({key}:{key:string})=>{const r=records.get(key);if(!r)throw {code:'SECURE_QUEUE_NOT_FOUND'};return r;},create:async(r:{key:string;data:string})=>{records.set(r.key,{...r,revision:'1'});return {revision:'1'};},compareAndSwap:async()=>{throw new Error('Unexpected CAS');}};
 const options={scope:'a'.repeat(64),native:true,indexedDB:new IDBFactory(),crypto:webcrypto,plugin},storage=await openDraftStore(options),value:DraftValue={schema:1,updatedAt:'2026-10-25T12:00:00Z',body:{kind:'editor',workspaceId:ehrVisit.id,editor,data:editor==='ehr-read:tebra'?emptyEhrReadRecovery({...ehrScope,provider:'tebra'}):record,pending:null}};
 await storage.write(address,null,value);storage.close();const key=`cosmas-private-draft:v1:${options.scope}:${address}`,retained=records.get(key)!;expect(new TextEncoder().encode(key).length).toBeLessThanOrEqual(512);expect(key.startsWith('cosmas-native-')).toBe(false);const bytes=Uint8Array.from(atob(retained.data),c=>c.charCodeAt(0));expect(bytes.length).toBeLessThanOrEqual(131072+1024);expect(JSON.parse(new TextDecoder().decode(bytes))).toEqual({version:1,scope:options.scope,address,value});const fresh=await openDraftStore(options);expect((await fresh.read(address)).value).toEqual(value);fresh.close();});


it.each(['elation','tebra','problems'] as const)('keeps fresh %s withholding published during review receipt persistence',async kind=>{
 const provider=kind==='problems'?'elation':kind;
 const scope={...ehrScope,...ehrProviderFields(provider)},editor=provider==='tebra'?'ehr-read:tebra':'ehr-read',address=editorAddress(ehrVisit.id,editor);
 const window=await ehrWindowReceipt({...ehrProviderFields(provider),action:'observe',...ehrBinding,starts_at:'2026-10-25T12:00:00Z',ends_at:'2026-10-26T12:00:00Z',idempotency_key:ehrUuid(881)});
 const verified=await ehrVerifiedReceipt(window),selected=kind==='problems'?await ehrProblemsReceipt(verified):verified,request=ehrReviewBody(selected),receipt=await ehrReviewResult(selected,request);
 const before:Workspace={...ehrVisit,appointment_id:null,entries:[],work_candidates:[]};
 const hidden:Workspace={...receipt.workspace,entries:receipt.workspace.entries.map(e=>({...e,content:'',source_label:'Unavailable EHR source',ehr_source_state:'unavailable'}))};
 const team={...teamFixture(),recovery_scope:opaque};let responseReturned=false;
 const read=vi.fn(async()=>responseReturned?hidden:before),session=new WorkspaceSession({recovery:{team:async()=>team,read}});
 session.setIdentity(identity);session.setTeam(team);session.setWorkspace(before);
 session.recovery.journal.current={scope:opaque,serverScope:opaque,value:journal};
 const access=session.recovery.editorAccess(identity,opaque,journal,ehrVisit.id,true,false,denied)!;
 await journal.load(address);await journal.persist(address,{kind:'editor',workspaceId:ehrVisit.id,editor,pending:null,data:{...emptyEhrReadRecovery(scope),binding:ehrBinding,window,verified,...(kind==='problems'?{problems:selected}:{}),pending:{kind:'review',request,anchor:selected}}});
 vi.spyOn(ehrReadApi,'review').mockImplementation(async()=>{responseReturned=true;return receipt;});
 function Harness(){const view=useWorkspaceSession(session),workspace=view.workspace!;return <EditorRecoveryContext.Provider value={access}><EhrReadMount identity={identity} provider={provider} enabled workspace={workspace}
  currentSources={workspace.entries.filter(e=>e.ehr_source_state).map(e=>({id:e.id,state:e.ehr_source_state!}))} onAskChief={vi.fn()} onAuthenticationLost={denied}/></EditorRecoveryContext.Provider>;}
 await act(async()=>root.render(<Harness/>));
 await wait(()=>expect(button('Restore saved '+(provider==='tebra'?'Tebra':'Elation')+' work')?.disabled).toBe(false));
 await act(async()=>button('Restore saved '+(provider==='tebra'?'Tebra':'Elation')+' work')!.click());
 await wait(()=>expect(button('Check saved source result')?.disabled).toBe(false));
 await act(async()=>button('Check saved source result')!.click());
 await wait(()=>expect(button('Prepare Chief draft')).toBeTruthy());
 expect(session.getSnapshot().workspace).toBe(hidden);
 expect(button('Prepare Chief draft')?.disabled).toBe(true);expect(host.textContent).not.toContain('Mira Invented');
 expect(read).toHaveBeenCalled();expect(ehrReadApi.review).toHaveBeenCalledOnce();expect(ehrReadApi.execute).not.toHaveBeenCalled();
 expect(await journal.load(address)).toMatchObject({data:{pending:null,saved:{entry_id:receipt.entry_id,source_withheld:false}}});
 expect(denied).not.toHaveBeenCalled();
});

it('recovers an encrypted problem-list command after remount without repeating the read or losing its verified parent',async()=>{
 const window=await ehrWindowReceipt(),verified=await ehrVerifiedReceipt(window),request=ehrProblemsCommand(verified),receipt=await ehrProblemsReceipt(verified,request);
 record={...emptyEhrReadRecovery(ehrScope),binding:ehrBinding,window,verified,pending:{kind:'read',request,anchor:verified}};await seed();journal.close();journal=new DraftJournal(await store());context={...context,journal};vi.mocked(ehrReadApi.resolve).mockResolvedValueOnce(receipt);
 await render();await wait(()=>expect(button('Restore saved Elation work')?.disabled).toBe(false));expect(host.textContent).not.toContain('Mira Invented');await act(async()=>button('Restore saved Elation work')!.click());await wait(()=>expect(button('Check saved problem-list result')?.disabled).toBe(false));await act(async()=>button('Check saved problem-list result')!.click());
 await wait(()=>expect(ehrReadApi.resolve).toHaveBeenCalledOnce());await wait(()=>expect(host.textContent).not.toContain('Checking and saving this step'));expect(ehrReadApi.execute).not.toHaveBeenCalled();expect(vi.mocked(ehrReadApi.resolve).mock.lastCall?.slice(1,3)).toEqual([request,verified]);const fresh=new DraftJournal(await store());expect(await fresh.load(address)).toMatchObject({data:{window,verified,problems:receipt,pending:null}});fresh.close();
});

it('round-trips an expanded problem review with both parent receipts through the bounded native SecureQueue bridge',async()=>{
 const window=await ehrWindowReceipt();if(window.observation.kind!=='window')throw new Error();const firstItem=window.observation.items[0];window.observation.items=Array.from({length:25},(_,index)=>({...firstItem,handle:ehrUuid(201+index)}));const {ehrItemHash}=await import('./ehr-read-api');for(const item of window.observation.items)item.sha256=await ehrItemHash(item);window.payload_sha256=await ehrHash(window.observation);const verified=await ehrVerifiedReceipt(window),problems=await ehrProblemsReceipt(verified,undefined,{coverage:'more_rows_available',total_count:30,items:Array.from({length:25},(_,index)=>({description:'Invented concern '+index,status:'Active',start_date:'2025-01-02',resolved_date:null,verification_status:'unconfirmed'}))});if(problems.observation.kind!=='verified_problems')throw new Error();expect(ehrSourceContent(problems.observation).length).toBeLessThanOrEqual(5000);
 const request=ehrReviewBody(problems),data=await validateEhrReadRecovery({...emptyEhrReadRecovery(ehrScope),binding:ehrBinding,window,verified,problems,pending:{kind:'review',request,anchor:problems}},ehrScope),records=new Map<string,{key:string;data:string;revision:string}>(),plugin={get:async({key}:{key:string})=>{const row=records.get(key);if(!row)throw {code:'SECURE_QUEUE_NOT_FOUND'};return row;},create:async(row:{key:string;data:string})=>{expect(Uint8Array.from(atob(row.data),c=>c.charCodeAt(0)).length).toBeLessThanOrEqual(131072+1024);records.set(row.key,{...row,revision:'1'});return {revision:'1'};},compareAndSwap:async()=>{throw new Error('Unexpected duplicate write');}};
 const options={scope:opaque,native:true,indexedDB:new IDBFactory(),crypto:webcrypto,plugin},nativeJournal=new DraftJournal(await openDraftStore(options));await nativeJournal.load(address);await nativeJournal.persist(address,{kind:'editor',workspaceId:ehrVisit.id,editor:'ehr-read',data,pending:null});nativeJournal.close();const fresh=new DraftJournal(await openDraftStore(options));expect(await fresh.load(address)).toMatchObject({data});fresh.close();expect(records.size).toBe(1);
});
