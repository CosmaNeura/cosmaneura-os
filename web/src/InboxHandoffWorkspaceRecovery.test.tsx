import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_INBOX_ENABLED','true');vi.stubEnv('VITE_INBOX_HANDOFF_ENABLED','true');});
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EncounterWorkspace} from './EncounterWorkspace';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {teamFixture} from './team-setup-test-fixture';
import {accountIdentityApi} from './account-identity-api';
import {inboxHandoffApi} from './inbox-handoff-api';
import {inboxApi} from './inbox-api';
import {inboxFixture,actual as actualInbox} from './inbox-test-fixture';
import {validateInbox} from './inbox-contract';
import {inboxHandoffActor as actor,inboxHandoffFixtureOperation,inboxHandoffFixtureCatalog,inboxHandoffFixture} from './inbox-handoff-test-fixture';
import {emptyInboxHandoffRecovery,withInboxHandoffCommand,type InboxHandoffRecoveryRecord} from './inbox-handoff-recovery';
import {openDraftStore,privateDraftScope,DraftStoreError,type DraftStore,type DraftValue} from './draft-store';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {hasUnsavedWork} from './unsaved-work';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-incoming-workspace-owner'};
const team=teamFixture(),address=accountEditorAddress('inbox-handoffs');
let root:Root,host:HTMLDivElement,idb:IDBFactory,scope:string,failWrites:number;
let factory:(options:{scope:string;native:boolean})=>Promise<DraftStore>;
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(e=>visible(e)&&(e.textContent?.trim()===label||[...e.querySelectorAll('strong')].some(s=>s.textContent?.trim()===label)));
const wait=async(check:()=>void|Promise<void>)=>{for(let i=0;i<250;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{await check();done=true;}catch{}});if(done)return;}await check();};
const click=async(label:string)=>{await wait(()=>{expect(button(label),label).toBeTruthy();expect(button(label)!.matches(':disabled'),label).toBe(false);});await act(async()=>button(label)!.click());};
const field=()=>[...host.querySelectorAll('label')].find(e=>visible(e)&&e.textContent?.startsWith('Human result evidence'))?.querySelector('textarea') as HTMLTextAreaElement;
async function input(value:string){expect(field()?.matches(':disabled')).toBe(false);await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field(),value);field().dispatchEvent(new Event('input',{bubbles:true}));});}
async function store(){return openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});}
async function saved(){const reader=await store();try{return (await reader.read(address)).value?.body as {kind:'account-editor';pending:null;data:InboxHandoffRecoveryRecord}|undefined;}finally{reader.close();}}
async function seed(data:InboxHandoffRecoveryRecord){const journal=new DraftJournal(await store());try{await journal.load(address);await journal.persist(address,{kind:'account-editor',editor:'inbox-handoffs',pending:null,data});}finally{journal.close();}}
async function mount(){await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={factory}/>));}
async function open(){await click('Practice work');await click('Incoming follow-up');await wait(()=>expect(button('Refresh follow-up')?.matches(':disabled')===false||!!button('Restore saved follow-up')).toBe(true));}
async function select(){const ticket=host.querySelector<HTMLButtonElement>('nav[aria-label="Incoming follow-up items"] button');expect(ticket).toBeTruthy();await act(async()=>ticket!.click());await click('Record human result');await wait(()=>expect(field()?.matches(':disabled')).toBe(false));}
function noDispatch(){expect(inboxHandoffApi.execute).not.toHaveBeenCalled();expect(inboxHandoffApi.recover).not.toHaveBeenCalled();expect(inboxApi.execute).not.toHaveBeenCalled();expect(inboxApi.recover).not.toHaveBeenCalled();expect(workspaceApi.open).not.toHaveBeenCalled();}
beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  idb=new IDBFactory();failWrites=0;scope=await privateDraftScope(team.recovery_scope!,import.meta.env.VITE_API_BASE||'http://127.0.0.1:8000',webcrypto);
  factory=async options=>{const current=await openDraftStore({...options,native:false,indexedDB:idb,crypto:webcrypto});return {read:current.read.bind(current),close:current.close.bind(current),write:async(id:string,expected:string|null,value:DraftValue|null)=>{if(id===address&&failWrites>0){failWrites--;throw new DraftStoreError('unavailable');}return current.write(id,expected,value);}};};
  vi.spyOn(workspaceApi,'team').mockResolvedValue(structuredClone(team));vi.spyOn(workspaceApi,'open');vi.spyOn(workspaceApi,'practiceWork').mockResolvedValue({items:[],people:[],next_cursor:null});
  vi.spyOn(accountIdentityApi,'read').mockResolvedValue({contract_version:1,...actor,recovery_scope:team.recovery_scope!});
  vi.spyOn(inboxHandoffApi,'catalog').mockResolvedValue(await inboxHandoffFixtureCatalog());vi.spyOn(inboxHandoffApi,'detail').mockResolvedValue(await inboxHandoffFixture('published'));vi.spyOn(inboxHandoffApi,'execute');vi.spyOn(inboxHandoffApi,'recover');
  const initial=await inboxFixture('initial');vi.spyOn(inboxApi,'catalog').mockResolvedValue({...validateInbox('Catalog',actualInbox.catalog),items:[initial.detail.summary]});vi.spyOn(inboxApi,'detail').mockResolvedValue(initial);vi.spyOn(inboxApi,'execute');vi.spyOn(inboxApi,'recover');
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('opens signed follow-up on demand before an encounter, without opening the private Inbox',async()=>{
  await mount();expect(accountIdentityApi.read).not.toHaveBeenCalled();await click('Practice work');expect(inboxHandoffApi.catalog).not.toHaveBeenCalled();await click('Incoming follow-up');await wait(()=>expect(button('Refresh follow-up')?.matches(':disabled')).toBe(false));
  expect(accountIdentityApi.read).toHaveBeenCalledWith(identity,expect.anything());expect(inboxHandoffApi.catalog).toHaveBeenCalledWith(identity,actor,expect.anything());expect(inboxApi.catalog).not.toHaveBeenCalled();noDispatch();
});
it('retains an exact pending handoff through workspace close and reopen without recovering or retrying it automatically',async()=>{
  const operation=await inboxHandoffFixtureOperation();await seed(withInboxHandoffCommand(emptyInboxHandoffRecovery(actor),operation));
  await mount();await open();await click('Restore saved follow-up');await wait(()=>expect(button('Recover exact receipt')?.matches(':disabled')).toBe(false));const before=await saved(),panel=host.querySelector('.inbox-handoff');
  await click('Assigned work');await click('Incoming follow-up');expect(host.querySelector('.inbox-handoff')).toBe(panel);expect((await saved())?.data.pending).toEqual(operation);
  await click('Close notebook');await wait(()=>expect(host.querySelector('.inbox-handoff')).toBeNull());expect(await saved()).toEqual(before);await open();expect(button('Restore saved follow-up')).toBeTruthy();noDispatch();
});
it('keeps failed handoff input and blocks workspace exits until the exact retained draft is saved',async()=>{
  await mount();await open();await select();failWrites=1;await input('Retained responsible-person evidence during storage outage');await wait(()=>expect(button('Retry saving retained follow-up')).toBeTruthy());
  expect(hasUnsavedWork()).toBe(true);for(const label of ['Assigned work','Incoming messages','Back to notebook','Team settings','Done'])expect(button(label)?.matches(':disabled'),label).toBe(true);
  const panel=host.querySelector('.inbox-handoff');await click('Close notebook');expect(host.querySelector('.inbox-handoff')).toBe(panel);expect(field().value).toBe('Retained responsible-person evidence during storage outage');
  await click('Retry saving retained follow-up');await wait(async()=>expect((await saved())?.data.drafts[0]).toMatchObject({kind:'ticket',evidence:'Retained responsible-person evidence during storage outage'}));await wait(()=>expect(button('Back to notebook')?.matches(':disabled')).toBe(false));noDispatch();
});
it('clears rendered follow-up when signed account authority is lost, preserving its encrypted record',async()=>{
  await mount();await open();await select();await input('Previously retained human draft');await wait(async()=>expect((await saved())?.data.drafts[0]).toMatchObject({evidence:'Previously retained human draft'}));const before=await saved();
  vi.mocked(workspaceApi.team).mockRejectedValueOnce(new WorkspaceApiError(403));await click('Back');await click('Refresh follow-up');await wait(()=>expect(host.querySelector('.inbox-handoff')).toBeNull());expect(host.textContent).toContain('Workspace access is unavailable');expect(await saved()).toEqual(before);noDispatch();
});
it('passes a selected Inbox item into a warm follow-up controller without copying source text or preparing an action',async()=>{
  const initial=await inboxFixture('initial');await mount();await open();await click('Saved action history');const panel=host.querySelector('.inbox-handoff');await click('Incoming messages');await click(initial.detail.summary.label);await click('Open incoming follow-up');
  await wait(()=>expect(button('Prepare from selected Inbox message')?.matches(':disabled')).toBe(false));expect(host.querySelector('.inbox-handoff')).toBe(panel);expect(host.querySelector('.inbox-handoff textarea')).toBeNull();expect(inboxHandoffApi.detail).not.toHaveBeenCalled();expect((await saved())?.data.drafts??[]).toEqual([]);
  // Repeating the same explicit selection returns to the focused list, preserving the controller.
  await click('Saved action history');await click('Incoming messages');await click('Open incoming follow-up');await wait(()=>expect(button('Prepare from selected Inbox message')?.matches(':disabled')).toBe(false));expect(host.querySelector('.inbox-handoff')).toBe(panel);noDispatch();
});
