import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_VENDOR_SETUP_ENABLED','true');vi.stubEnv('VITE_FINANCE_SETUP_ENABLED','false');vi.stubEnv('VITE_PORTAL_SETUP_ENABLED','false');});
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EncounterWorkspace} from './EncounterWorkspace';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {teamFixture} from './team-setup-test-fixture';
import {teamSetupApi} from './team-setup-api';
import {vendorSetupApi} from './vendor-setup-api';
import {setupFixture} from './vendor-setup-test-fixture';
import {emptyVendorSetupRecovery,type VendorSetupRecoveryRecord} from './vendor-setup-recovery';
import {openDraftStore,privateDraftScope,DraftStoreError,type DraftStore,type DraftValue} from './draft-store';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {hasUnsavedWork} from './unsaved-work';
vi.mock('./team-setup-api',async()=>{const {WorkspaceApiError}=await import('./workspace-api');return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404)),rehearse:vi.fn()}};});
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-navigation-owner'};
const team=teamFixture(),address=accountEditorAddress('vendor-setup');
let root:Root,host:HTMLDivElement,fixture:Awaited<ReturnType<typeof setupFixture>>,idb:IDBFactory,scope:string;
let vendorFailures:number,holdTeam:boolean,releaseTeam:(()=>void)|null,parentWriteStarted:boolean,parentCloses:number;
let factory:ReturnType<typeof vi.fn<(options:{scope:string;native:boolean})=>Promise<DraftStore>>>;
const visible=(n:Element)=>!n.closest('[hidden]');
const text=(n:Element)=>n.textContent?.replace(/[←→›↗]/g,'').trim();
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(text(b)===label||[...b.querySelectorAll('strong')].some(s=>text(s)===label)));
const wait=async(check:()=>void|Promise<void>)=>{for(let i=0;i<250;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{await check();done=true;}catch{}});if(done)return;}await check();};
const click=async(label:string)=>{await wait(()=>{expect(button(label),label).toBeTruthy();expect(button(label)!.matches(':disabled'),label).toBe(false);});await act(async()=>button(label)!.click());};
const labelField=(label:string)=>{const found=[...host.querySelectorAll('label')].find(l=>visible(l)&&[...l.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('').trim()===label);const input=found?.querySelector('input,textarea,select') as HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement|undefined;if(!input)throw Error('Missing visible field '+label);return input;};
const input=async(field:HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement,value:string)=>{expect(field.matches(':disabled')).toBe(false);const proto=field.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:field.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;await act(async()=>{Object.getOwnPropertyDescriptor(proto,'value')!.set!.call(field,value);field.dispatchEvent(new Event(field.tagName==='SELECT'?'change':'input',{bubbles:true}));});};
async function plainStore(){return openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});}
async function readSetup(){const store=await plainStore();try{return (await store.read(address)).value?.body as {kind:'account-editor';pending:null;data:VendorSetupRecoveryRecord}|undefined;}finally{store.close();}}
async function seedSetup(data:VendorSetupRecoveryRecord){const journal=new DraftJournal(await plainStore());await journal.load(address);await journal.persist(address,{kind:'account-editor',editor:'vendor-setup',pending:null,data});journal.close();}
async function mount(){await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={factory}/>));}
async function openConnections(){await click('Team settings');await click('Connections');await click('Messaging & fax');await wait(()=>expect((button('Refresh connector settings')&&!button('Refresh connector settings')!.matches(':disabled'))||(button('Restore connector settings draft')&&!button('Restore connector settings draft')!.matches(':disabled'))).toBe(true));}
async function newDraft(){await openConnections();await click('New account configuration');await wait(()=>{const field=labelField('Configuration name');expect(field).toBeTruthy();expect(field.matches(':disabled')).toBe(false);});}
async function faultInput(value='Retain this exact volatile choice'){
 vendorFailures=1;await input(labelField('Configuration name'),value);await wait(()=>expect(button('Retry saving retained input')?.matches(':disabled')).toBe(false));
}
async function teamPractice(){await click('All connections');await click('All settings');await click('Your team');await click('Team preferences');await click('Practice context');await wait(()=>expect(host.querySelector('.team-practice-editor textarea')).toBeTruthy());}
function assertNoDispatch(){expect(vendorSetupApi.command).not.toHaveBeenCalled();expect(vendorSetupApi.resolve).not.toHaveBeenCalled();expect(workspaceApi.saveTeam).not.toHaveBeenCalled();}
beforeEach(async()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);
 // Node crypto/fake IndexedDB clone into Node's typed-array realm; align the DOM test's constructors.
 vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);vi.mocked(teamSetupApi.read).mockRejectedValue(new WorkspaceApiError(404));fixture=await setupFixture();idb=new IDBFactory();scope=await privateDraftScope(team.recovery_scope!,import.meta.env.VITE_API_BASE||'http://127.0.0.1:8000',webcrypto);vendorFailures=0;holdTeam=false;releaseTeam=null;parentWriteStarted=false;parentCloses=0;
 factory=vi.fn(async(options:{scope:string;native:boolean})=>{const storage=await openDraftStore({...options,native:false,indexedDB:idb,crypto:webcrypto});return {read:storage.read.bind(storage),close:()=>{parentCloses++;storage.close();},write:async(id:string,expected:string|null,value:DraftValue|null)=>{
  if(id==='team'&&value&&holdTeam){holdTeam=false;parentWriteStarted=true;await new Promise<void>(resolve=>{releaseTeam=resolve;});throw new DraftStoreError('unavailable');}
  if(id===address&&vendorFailures>0){vendorFailures--;throw new DraftStoreError('unavailable');}
  return storage.write(id,expected,value);
 }};});
 vi.spyOn(workspaceApi,'team').mockResolvedValue(structuredClone(team));vi.spyOn(workspaceApi,'saveTeam');vi.spyOn(vendorSetupApi,'catalog').mockResolvedValue(fixture.emptyCatalog);vi.spyOn(vendorSetupApi,'detail').mockResolvedValue(fixture.accountPending);vi.spyOn(vendorSetupApi,'command');vi.spyOn(vendorSetupApi,'resolve');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{releaseTeam?.();await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('blocks Close notebook while connection input is volatile and preserves it through authorized retry',async()=>{
 await mount();await newDraft();await faultInput();const panel=host.querySelector('.vendor-setup');const close=button('Close notebook')!,wasDisabled=close.matches(':disabled');await act(async()=>close.click());if(!wasDisabled)await wait(()=>expect(host.textContent?.includes('before closing')||!panel?.isConnected).toBe(true));expect(panel?.isConnected).toBe(true);expect(host.querySelector('.vendor-setup')).toBe(panel);expect(button('Retry saving retained input')).toBeTruthy();await click('Retry saving retained input');await wait(async()=>expect((await readSetup())?.data.draft.label).toBe('Retain this exact volatile choice'));expect(labelField('Configuration name').value).toBe('Retain this exact volatile choice');assertNoDispatch();
});
it('registers volatile connection input for beforeunload even with no notebook or team edits',async()=>{
 await mount();await newDraft();await faultInput();expect(hasUnsavedWork()).toBe(true);const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);expect(event.defaultPrevented).toBe(true);assertNoDispatch();
});
it('blocks an already visible Close anyway choice after a connection write fails',async()=>{
 await mount();await newDraft();await teamPractice();const practice=host.querySelector<HTMLTextAreaElement>('.team-practice-editor textarea')!;await input(practice,'Invented unsaved team context');await wait(()=>expect(host.textContent).toContain('Drafts saved on this device.'));
 await click('Close notebook');await wait(()=>expect(button('Close anyway')).toBeTruthy());await click('All settings');await click('Connections');await click('Messaging & fax');await wait(()=>expect(labelField('Configuration name')).toBeTruthy());await faultInput('Retain despite earlier close prompt');const panel=host.querySelector('.vendor-setup');const close=button('Close anyway')!,wasDisabled=close.matches(':disabled');await act(async()=>close.click());if(!wasDisabled)await wait(()=>expect(host.textContent?.includes('before closing')||!panel?.isConnected).toBe(true));expect(panel?.isConnected).toBe(true);expect(button('Retry saving retained input')).toBeTruthy();assertNoDispatch();
});
it('preserves a durable nested account-editor command when closing the notebook',async()=>{
 const saved={...emptyVendorSetupRecovery(fixture.emptyCatalog.scope),pending:fixture.accountOp};await seedSetup(saved);await mount();await openConnections();await click('Restore connector settings draft');await wait(()=>expect(button('Recover exact settings receipt')?.matches(':disabled')).toBe(false));const before=await readSetup();expect(before?.pending).toBeNull();expect(before?.data.pending).toEqual(fixture.accountOp);await click('Close notebook');await wait(()=>expect(host.querySelector('.vendor-setup')).toBeNull());expect(await readSetup()).toEqual(before);assertNoDispatch();
});
it('retains one scoped connector controller through a delayed parent failure and recheck plus exact local retry',async()=>{
 await mount();await newDraft();await input(labelField('Configuration name'),'Initial durable connector draft');await wait(async()=>expect((await readSetup())?.data.draft.label).toBe('Initial durable connector draft'));const panel=host.querySelector('.vendor-setup');await teamPractice();holdTeam=true;await input(host.querySelector<HTMLTextAreaElement>('.team-practice-editor textarea')!,'Parent write fails later');await wait(()=>expect(parentWriteStarted).toBe(true));
 await click('All settings');await click('Connections');await click('Messaging & fax');expect(host.querySelector('.vendor-setup')).toBe(panel);vendorFailures=1;await input(labelField('Configuration name'),'Exact input behind failed parent write');await act(async()=>releaseTeam!());await wait(()=>expect(host.textContent).toContain("This device's draft storage could not be checked"));await wait(()=>expect(button('Retry saving retained input')).toBeTruthy());expect(panel?.isConnected).toBe(true);expect(host.querySelector('.vendor-setup')).toBe(panel);expect(vendorSetupApi.catalog).toHaveBeenCalledTimes(1);
 await click('Recheck draft recovery');await wait(()=>expect(button('Retry saving retained input')?.matches(':disabled')).toBe(false));expect(host.querySelector('.vendor-setup')).toBe(panel);expect(parentCloses).toBe(0);await click('Retry saving retained input');await wait(async()=>expect((await readSetup())?.data.draft.label).toBe('Exact input behind failed parent write'));expect(labelField('Configuration name').value).toBe('Exact input behind failed parent write');expect(vendorSetupApi.catalog).toHaveBeenCalledTimes(1);expect(factory).toHaveBeenCalledTimes(1);assertNoDispatch();
});
