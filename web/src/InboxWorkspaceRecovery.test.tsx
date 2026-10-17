import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_INBOX_ENABLED','true');});
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EncounterWorkspace} from './EncounterWorkspace';
import {InboxMount} from './InboxMount';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {teamFixture} from './team-setup-test-fixture';
import {inboxApi} from './inbox-api';
import {actual,inboxFixture,inboxFixtureOperation,inboxFixtureScope} from './inbox-test-fixture';
import {validateInbox} from './inbox-contract';
import {emptyInboxRecovery,type InboxRecoveryRecord} from './inbox-recovery';
import {openDraftStore,privateDraftScope,DraftStoreError,type DraftStore,type DraftValue} from './draft-store';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {hasUnsavedWork} from './unsaved-work';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-inbox-mount-owner'};
const team=teamFixture(),address=accountEditorAddress('inbox-work');
let root:Root,host:HTMLDivElement,idb:IDBFactory,scope:string,failWrites:number;
let initial:Awaited<ReturnType<typeof inboxFixture>>;
let factory:(options:{scope:string;native:boolean})=>Promise<DraftStore>;
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(e=>visible(e)&&(e.textContent?.trim()===label||[...e.querySelectorAll('strong')].some(s=>s.textContent?.trim()===label)));
const wait=async(check:()=>void|Promise<void>)=>{for(let i=0;i<250;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{await check();done=true;}catch{}});if(done)return;}await check();};
const click=async(label:string)=>{await wait(()=>{expect(button(label),label).toBeTruthy();expect(button(label)!.matches(':disabled'),label).toBe(false);});await act(async()=>button(label)!.click());};
const field=()=>[...host.querySelectorAll('label')].find(e=>visible(e)&&e.textContent?.startsWith('Human review instructions'))?.querySelector('textarea') as HTMLTextAreaElement;
async function input(value:string){expect(field()?.matches(':disabled')).toBe(false);await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field(),value);field().dispatchEvent(new Event('input',{bubbles:true}));});}
async function store(){return openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});}
async function saved(){const reader=await store();try{return (await reader.read(address)).value?.body as {kind:'account-editor';pending:null;data:InboxRecoveryRecord}|undefined;}finally{reader.close();}}
async function mount(){await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={factory}/>));}
async function open(){await click('Practice work');await click('Messages');await wait(()=>expect(button('Refresh private Inbox')?.matches(':disabled')===false||!!button('Restore saved Inbox work')).toBe(true));}
async function select(){await click(initial.detail.summary.label);await click('Plan human review');await wait(()=>expect(field()?.matches(':disabled')).toBe(false));await wait(async()=>expect((await saved())?.data.drafts).toHaveLength(1));}
function noDispatch(){expect(inboxApi.execute).not.toHaveBeenCalled();expect(inboxApi.recover).not.toHaveBeenCalled();expect(workspaceApi.saveTeam).not.toHaveBeenCalled();expect(workspaceApi.open).not.toHaveBeenCalled();}
beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  idb=new IDBFactory();failWrites=0;scope=await privateDraftScope(team.recovery_scope!,import.meta.env.VITE_API_BASE||'http://127.0.0.1:8000',webcrypto);
  initial=await inboxFixture('initial');
  factory=async options=>{const current=await openDraftStore({...options,native:false,indexedDB:idb,crypto:webcrypto});return {read:current.read.bind(current),close:current.close.bind(current),write:async(id:string,expected:string|null,value:DraftValue|null)=>{if(id===address&&failWrites>0){failWrites--;throw new DraftStoreError('unavailable');}return current.write(id,expected,value);}};};
  vi.spyOn(workspaceApi,'team').mockResolvedValue(structuredClone(team));vi.spyOn(workspaceApi,'saveTeam');vi.spyOn(workspaceApi,'open');vi.spyOn(workspaceApi,'practiceWork').mockResolvedValue({items:[],people:[],next_cursor:null});
  vi.spyOn(inboxApi,'catalog').mockResolvedValue({...validateInbox('Catalog',actual.catalog),items:[initial.detail.summary]});vi.spyOn(inboxApi,'detail').mockResolvedValue(initial);vi.spyOn(inboxApi,'execute');vi.spyOn(inboxApi,'recover');
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('does not read Inbox when its compiled mount is disabled',async()=>{
  await act(async()=>root.render(<InboxMount identity={identity} onDenied={vi.fn()} enabled={false}/>));
  expect(host.textContent).toBe('');expect(inboxApi.catalog).not.toHaveBeenCalled();
});
it('loads Inbox only on demand before encounter selection and preserves its encrypted draft across views and close',async()=>{
  await mount();expect(inboxApi.catalog).not.toHaveBeenCalled();await click('Practice work');expect(inboxApi.catalog).not.toHaveBeenCalled();await click('Messages');await select();
  await input('Retained incoming review before encounter selection');await wait(async()=>expect((await saved())?.data.drafts[0].instructions).toBe('Retained incoming review before encounter selection'));
  const panel=host.querySelector('.inbox-panel');await click('Assigned to me');await click('Messages');expect(host.querySelector('.inbox-panel')).toBe(panel);expect(field().value).toBe('Retained incoming review before encounter selection');
  const before=await saved();await click('Close notebook');await wait(()=>expect(host.querySelector('.inbox-panel')).toBeNull());expect(await saved()).toEqual(before);noDispatch();
});
it('blocks all workspace exits during failed Inbox storage and retains exact input through authorized local retry',async()=>{
  await mount();await open();await select();failWrites=1;await input('Exact Inbox input during storage outage');await wait(()=>expect(button('Retry saving retained Inbox work')).toBeTruthy());
  expect(field().value).toBe('Exact Inbox input during storage outage');expect(hasUnsavedWork()).toBe(true);
  for(const label of ['Assigned to me','Back to notebook','Team settings'])expect(button(label)?.matches(':disabled'),label).toBe(true);
  const panel=host.querySelector('.inbox-panel');await click('Close notebook');expect(host.querySelector('.inbox-panel')).toBe(panel);expect(host.textContent).toContain('before closing');
  await click('Retry saving retained Inbox work');await wait(async()=>expect((await saved())?.data.drafts[0].instructions).toBe('Exact Inbox input during storage outage'));
  await wait(()=>expect(button('Back to notebook')?.matches(':disabled')).toBe(false));expect(field().value).toBe('Exact Inbox input during storage outage');noDispatch();
});
it('retains a nested exact pending Inbox action and offers it after reopening without sending or retrying',async()=>{
  const operation=await inboxFixtureOperation(),record={...emptyInboxRecovery(inboxFixtureScope),pending:operation};
  const journal=new DraftJournal(await store());await journal.load(address);await journal.persist(address,{kind:'account-editor',editor:'inbox-work',pending:null,data:record});journal.close();
  await mount();await open();await click('Restore saved Inbox work');await wait(()=>expect(button('Recover exact Inbox receipt')?.matches(':disabled')).toBe(false));const before=await saved();
  await click('Close notebook');await wait(()=>expect(host.querySelector('.inbox-panel')).toBeNull());expect(await saved()).toEqual(before);await open();expect(button('Restore saved Inbox work')).toBeTruthy();noDispatch();
});
it('clears private rendered Inbox content when current account authorization is lost',async()=>{
  await mount();await open();await select();vi.mocked(workspaceApi.team).mockRejectedValueOnce(new WorkspaceApiError(403));await click('Refresh private Inbox');
  await wait(()=>expect(host.querySelector('.inbox-panel')).toBeNull());expect(host.textContent).toContain('Workspace access is unavailable');noDispatch();
});
it('does not offer or reveal a saved Inbox record belonging to a different signed owner scope',async()=>{
  const record=emptyInboxRecovery({...inboxFixtureScope,owner_id:crypto.randomUUID()});
  const journal=new DraftJournal(await store());await journal.load(address);await journal.persist(address,{kind:'account-editor',editor:'inbox-work',pending:null,data:record});journal.close();
  await mount();await click('Practice work');await click('Messages');await wait(()=>expect(host.textContent).toContain('Private Inbox recovery could not be loaded'));
  expect(button('Restore saved Inbox work')).toBeUndefined();expect(host.querySelector('.inbox-panel pre')).toBeNull();expect((await saved())?.data).toEqual(record);noDispatch();
});

it('opens a reviewed Inbox draft in its encounter and retains an interrupted AI request in encrypted recovery',async()=>{
  const observed=(await import('./__fixtures__/inbox-analysis-w87.json')).default;
  const {inboxDraftSelection}=await import('./inbox-analysis-contract');
  initial=await inboxFixture('triaged');const selection=inboxDraftSelection(initial)!;
  vi.mocked(inboxApi.catalog).mockResolvedValue({...validateInbox('Catalog',actual.catalog),items:[initial.detail.summary]});
  vi.mocked(inboxApi.detail).mockResolvedValue(initial);
  vi.mocked(workspaceApi.team).mockResolvedValue({...observed.setup.team,recovery_scope:team.recovery_scope} as import('./workspace-api').ProviderTeam);
  const workspace={...observed.workspace,id:selection.workspace_id,revision:selection.expected_revision,entries:[],work_candidates:[]} as import('./workspace-api').Workspace;
  vi.spyOn(workspaceApi,'read').mockResolvedValue(workspace);
  vi.spyOn(workspaceApi,'ask').mockRejectedValue(new WorkspaceApiError(503));
  await mount();await open();await click(initial.detail.summary.label);
  await wait(()=>expect(button('Draft a reply')?.matches(':disabled')).toBe(false));await click('Draft a reply');
  await wait(()=>expect(host.querySelector('[aria-label="Reviewed Inbox draft"]'),host.textContent??'').not.toBeNull());
  expect(workspaceApi.ask).not.toHaveBeenCalled();expect(button('Create private draft')?.matches(':disabled')).toBe(true);
  await wait(()=>expect(host.querySelector<HTMLInputElement>('[aria-label="Reviewed Inbox draft"] input')?.matches(':disabled')).toBe(false));
  const consent=host.querySelector('[aria-label="Reviewed Inbox draft"] input') as HTMLInputElement;
  await act(async()=>consent.click());await click('Create private draft');
  await wait(()=>expect(workspaceApi.ask).toHaveBeenCalledTimes(1));
  expect(vi.mocked(workspaceApi.ask).mock.calls[0][2].inbox_analysis).toEqual({...selection.analysis,consented:true});
  const reader=new DraftJournal(await store());const retained=await reader.load(`workspace:${workspace.id}`);reader.close();
  expect(retained).toMatchObject({kind:'workspace',pending:{type:'ask',model_contract:1,body:{inbox_analysis:{...selection.analysis,consented:true}}}});
  expect(inboxApi.execute).not.toHaveBeenCalled();expect(inboxApi.recover).not.toHaveBeenCalled();
});
