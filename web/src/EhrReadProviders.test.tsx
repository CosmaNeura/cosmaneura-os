import {athenaMedicationApi,ATHENA_MEDICATION_CORE,type AthenaMedicationCoreReceipt} from './athena-medication-api';
import {athenaAllergyApi} from './athena-allergy-api';
import {athenaMedicationFixtureBinding,athenaMedicationPatientsFixture} from '../ux-acceptance/athena-medication-fixtures';
import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EhrReadProviders} from './EhrReadProviders';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal,editorAddress} from './draft-journal';
import {openDraftStore} from './draft-store';
import {accountIdentityApi} from './account-identity-api';
import {ehrReadApi,type EhrProvider,type EhrReceipt} from './ehr-read-api';
import {emptyEhrReadRecovery,type EhrReadRecovery} from './ehr-read-recovery';
import {ehrBinding,ehrPractice,ehrScope,ehrUuid,ehrVisit,ehrWindowReceipt,ehrVerifiedReceipt,ehrReviewResult} from './ehr-read-fixtures.test-support';
import {WorkspaceApiError,type Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const opaque='e'.repeat(64),identity={mode:'clerk_jwt' as const,getToken:async()=>null};
let root:Root,host:HTMLDivElement,journal:DraftJournal,context:EditorRecoveryAccess,idb:IDBFactory,busy:ReturnType<typeof vi.fn>,denied:ReturnType<typeof vi.fn>;
const address=(provider:EhrProvider)=>editorAddress(ehrVisit.id,provider==='tebra'?'ehr-read:tebra':'ehr-read');
const storage=()=>openDraftStore({scope:opaque,native:false,indexedDB:idb,crypto:webcrypto});
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>!b.closest('[hidden]')&&b.textContent===label);
const group=(label='Records system')=>host.querySelector(`[role="group"][aria-label="${label}"]`)!;
const pressed=(label='Records system')=>[...group(label).querySelectorAll<HTMLButtonElement>('button')].find(b=>b.getAttribute('aria-pressed')==='true')!;
const providerValue=()=>({elation:'elation',tebra:'tebra',athena:'athena',Elation:'elation',Tebra:'tebra',Athena:'athena'}[pressed().textContent!]??pressed().textContent!);
const selectorDisabled=()=>[...group().querySelectorAll('button')].every(b=>b.disabled);
const choiceValue=(label:string)=>({allergies:'allergies',medications:'medications',appointments:'appointments','Allergy records':'allergies','Medication records':'medications',Appointments:'appointments'}[pressed(label).textContent!]??pressed(label).textContent!);
const choiceDisabled=(label:string)=>[...group(label).querySelectorAll('button')].every(b=>b.disabled);
async function wait(check:()=>void){for(let i=0;i<250;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(label:string){await wait(()=>expect(button(label)?.disabled,label).toBe(false));await act(async()=>button(label)!.click());await wait(()=>expect(busy.mock.lastCall?.[0]??false).toBe(false));}
async function press(label:string,value:string){const names:{[k:string]:string}={elation:'Elation',tebra:'Tebra',athena:'Athena',medications:'Medication records',appointments:'Appointments',allergies:'Allergy records'};const visible=names[value]??value;const control=[...group(label).querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===visible);expect(control).toBeTruthy();if(control!.getAttribute('aria-pressed')!=='true')await act(async()=>control!.click());}
async function choose(provider:EhrProvider){await press('Records system',provider);if(provider==='tebra')await press('Tebra records','appointments');await wait(()=>expect(button('Check '+(provider==='tebra'?'Tebra':'Elation')+' access')??button('Restore saved '+(provider==='tebra'?'Tebra':'Elation')+' work')).toBeTruthy());}
async function input(label:string,value:string){const target=[...host.querySelectorAll('label')].find(x=>!x.closest('[hidden]')&&x.textContent===label)?.querySelector('input');expect(target).toBeTruthy();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(target,value);target!.dispatchEvent(new Event('input',{bubbles:true}));});}
async function mount(){await act(async()=>root.render(<EditorRecoveryContext.Provider value={context}><EhrReadProviders identity={identity} enabled workspace={ehrVisit} onAuthenticationLost={denied} onBusyChange={busy}/></EditorRecoveryContext.Provider>));await wait(()=>expect(button('Check Elation access')??button('Restore saved Elation work')).toBeTruthy());}
async function retained(provider:EhrProvider){const value=await journal.load(address(provider));if(value?.kind!=='editor')throw new Error('Expected saved editor');return value.data as EhrReadRecovery;}
beforeEach(async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);vi.useFakeTimers({toFake:['Date']});vi.setSystemTime(new Date('2026-10-25T12:00:00Z'));
 idb=new IDBFactory();journal=new DraftJournal(await storage());busy=vi.fn();denied=vi.fn();const workspace:Workspace={...ehrVisit,appointment_id:null,entries:[],work_candidates:[]};context={journal,workspaceId:ehrVisit.id,recoveryScope:opaque,authorize:vi.fn(async()=>workspace),denied:vi.fn()};
 vi.spyOn(accountIdentityApi,'read').mockResolvedValue({contract_version:1,box_id:ehrScope.box_id,actor_id:ehrScope.owner_id,recovery_scope:opaque});
 vi.spyOn(ehrReadApi,'status').mockImplementation(async(_identity,_signal,provider='elation')=>({contract_version:1,provider,mode:'synthetic',transport:'mock',installation:null,status:'ready',...ehrBinding,practice:ehrPractice}));
 vi.spyOn(ehrReadApi,'execute').mockImplementation(async(_i,b,a)=>b.action==='observe'?ehrWindowReceipt(b):ehrVerifiedReceipt(a!,b));vi.spyOn(ehrReadApi,'inspect').mockImplementation(async(_i,a)=>a);vi.spyOn(ehrReadApi,'resolve');vi.spyOn(ehrReadApi,'review').mockImplementation(async(_i,_w,b,a)=>ehrReviewResult(a,b));
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();journal.close();vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers();});
it('defaults to Elation and switches without reading either provider or claiming a live Tebra connection',async()=>{await mount();expect(providerValue()).toBe('elation');await choose('tebra');expect(ehrReadApi.status).not.toHaveBeenCalled();expect(ehrReadApi.execute).not.toHaveBeenCalled();await click('Check Tebra access');expect(host.querySelector('[aria-label="Tebra appointments"]')?.textContent).toContain('Local example — invented Tebra records');expect(button('Use this practice’s Elation sandbox')).toBeUndefined();expect(ehrReadApi.status).toHaveBeenCalledWith(identity,expect.any(AbortSignal),'tebra');});
it('persists exact demographic verification before dispatch and hides the previous patient while selecting another appointment',async()=>{
 await mount();await choose('tebra');await click('Check Tebra access');await click('Load appointments');const row=()=>host.querySelector<HTMLButtonElement>('[aria-label="Tebra appointments"] ul button')!;await act(async()=>row().click());expect(ehrReadApi.execute).toHaveBeenCalledOnce();expect(button('Verify selected appointment')?.disabled).toBe(true);await input('Patient last name','Invented');await input('Date of birth','1980-02-03');
 vi.mocked(ehrReadApi.execute).mockImplementationOnce(async(_i,b,a)=>{expect((await retained('tebra')).pending?.request).toEqual(b);expect(b).toMatchObject({provider:'tebra',action:'verify',last_name:'Invented',birth_date:'1980-02-03'});return ehrVerifiedReceipt(a!,b);});await click('Verify selected appointment');expect(host.querySelector('[aria-label="Tebra appointments"]')?.textContent).toContain('Mira Invented');expect(host.textContent).toContain('Showing returned appointments only; this is not a complete schedule.');await act(async()=>row().click());expect(host.querySelector('[aria-label="Review patient and visit"]')).toBeNull();expect(button('Save reviewed appointment')).toBeUndefined();
});
it('keeps independent unresolved commands in actual encrypted journals through provider switching and a fresh reader',async()=>{
 vi.mocked(ehrReadApi.execute).mockRejectedValue(new WorkspaceApiError(503));await mount();await click('Check Elation access');await click('Load appointments');const elation=await retained('elation');await choose('tebra');await click('Check Tebra access');await click('Load appointments');const tebra=await retained('tebra');expect(tebra.pending?.request).toMatchObject({provider:'tebra'});expect(elation.pending?.request).not.toHaveProperty('provider');expect(tebra.pending?.request.idempotency_key).not.toBe(elation.pending?.request.idempotency_key);
 const fresh=new DraftJournal(await storage());expect(await fresh.load(address('elation'))).toMatchObject({data:elation});expect(await fresh.load(address('tebra'))).toMatchObject({data:tebra});fresh.close();await choose('elation');await click('Restore saved Elation work');vi.mocked(ehrReadApi.resolve).mockResolvedValueOnce({status:'unconfirmed',observation_id:ehrUuid(801),observation_key:elation.pending!.request.idempotency_key});await click('Check saved appointment result');expect(ehrReadApi.resolve).toHaveBeenLastCalledWith(identity,elation.pending!.request,null,expect.any(AbortSignal),'mock');expect((await retained('tebra')).pending).toEqual(tebra.pending);expect(ehrReadApi.execute).toHaveBeenCalledTimes(2);
});
it('keeps the shared busy lock while the selected provider dispatches despite the other mounted panel being idle',async()=>{
 await mount();await choose('tebra');await choose('elation');await click('Check Elation access');let finish!:(value:EhrReceipt)=>void;vi.mocked(ehrReadApi.execute).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await act(async()=>button('Load appointments')!.click());await wait(()=>expect(finish).toBeTypeOf('function'));expect(selectorDisabled()).toBe(true);expect(busy.mock.lastCall?.[0]).toBe(true);await press('Records system','tebra');expect(button('Check Elation access')).toBeTruthy();const pending=(await retained('elation')).pending!;if(pending.kind!=='read')throw new Error();await act(async()=>finish(await ehrWindowReceipt(pending.request)));await wait(()=>expect(selectorDisabled()).toBe(false));expect(busy.mock.lastCall?.[0]).toBe(false);await choose('tebra');expect(button('Check Tebra access')).toBeTruthy();
});
it('rejects placing a Tebra record under the legacy Elation journal address and vice versa',async()=>{
 const tebra=emptyEhrReadRecovery({...ehrScope,provider:'tebra'}),elation=emptyEhrReadRecovery(ehrScope);await journal.load(address('elation'));await journal.load(address('tebra'));await expect(journal.persist(address('elation'),{kind:'editor',workspaceId:ehrVisit.id,editor:'ehr-read',pending:null,data:tebra})).rejects.toThrow();await expect(journal.persist(address('tebra'),{kind:'editor',workspaceId:ehrVisit.id,editor:'ehr-read:tebra',pending:null,data:elation})).rejects.toThrow();
});
it('keeps Athena allergy default and locks both selectors during an explicitly chosen medication read',async()=>{
 vi.spyOn(athenaAllergyApi,'status');vi.spyOn(athenaMedicationApi,'status').mockResolvedValue({contract_version:1,...ATHENA_MEDICATION_CORE,mode:'synthetic',transport:'mock',status:'ready',...athenaMedicationFixtureBinding,practice_label:'Invented medication access'});
 let finish!:(value:AthenaMedicationCoreReceipt)=>void;vi.spyOn(athenaMedicationApi,'execute').mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await mount();await press('Records system','athena');await wait(()=>expect(button('Check Athena allergy access')).toBeTruthy());expect(choiceValue('Athena records')).toBe('allergies');expect(athenaAllergyApi.status).not.toHaveBeenCalled();expect(athenaMedicationApi.status).not.toHaveBeenCalled();
 await press('Athena records','medications');await click('Check Athena medication access');await act(async()=>button('Load authorized patients')!.click());await wait(()=>expect(finish).toBeTypeOf('function'));expect(choiceDisabled('Athena records')).toBe(true);expect(selectorDisabled()).toBe(true);expect(busy.mock.lastCall?.[0]).toBe(true);
 await press('Athena records','allergies');expect(button('Check Athena medication access')).toBeTruthy();expect(athenaAllergyApi.status).not.toHaveBeenCalled();const command=vi.mocked(athenaMedicationApi.execute).mock.calls[0][1];await act(async()=>finish(await athenaMedicationPatientsFixture(command)));await wait(()=>expect(selectorDisabled()).toBe(false));expect(choiceDisabled('Athena records')).toBe(false);expect(busy.mock.lastCall?.[0]).toBe(false);
});

it('applies one explicit catalog provider intent without reading records or resetting later manual choices',async()=>{
 await mount();const request={provider:'athena' as const,intent:{}};
 const render=()=>act(async()=>root.render(<EditorRecoveryContext.Provider value={context}><EhrReadProviders {...{requestedProvider:request}} identity={identity} enabled workspace={ehrVisit} onAuthenticationLost={denied} onBusyChange={busy}/></EditorRecoveryContext.Provider>));
 await render();await wait(()=>expect(button('Check Athena allergy access')).toBeTruthy());expect(providerValue()).toBe('athena');expect(ehrReadApi.status).not.toHaveBeenCalled();expect(ehrReadApi.execute).not.toHaveBeenCalled();
 await choose('elation');await render();expect(providerValue()).toBe('elation');expect(button('Check Elation access')).toBeTruthy();
});

it('waits for an explicit catalog task to become active, then keeps both provider journals mounted',async()=>{
 const request={provider:'athena' as const,intent:{}};
 const render=(active:boolean)=>act(async()=>root.render(<EditorRecoveryContext.Provider value={context}><EhrReadProviders requestedProvider={request} active={active} identity={identity} enabled workspace={ehrVisit} onAuthenticationLost={denied} onBusyChange={busy}/></EditorRecoveryContext.Provider>));
 await render(false);expect(providerValue()).toBe('elation');expect(ehrReadApi.status).not.toHaveBeenCalled();await render(true);await wait(()=>expect(button('Check Athena allergy access')).toBeTruthy());expect(providerValue()).toBe('athena');
 await choose('elation');const elation=host.querySelector('[aria-label="Elation appointments"]');expect(elation).toBeTruthy();await render(false);await render(true);expect(providerValue()).toBe('elation');expect(host.querySelector('[aria-label="Elation appointments"]')).toBe(elation);expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it('rejects a provider intent during active work without switching later after cleanup',async()=>{
 await mount();await click('Check Elation access');let finish!:(value:EhrReceipt)=>void;vi.mocked(ehrReadApi.execute).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await act(async()=>button('Load appointments')!.click());await wait(()=>expect(finish).toBeTypeOf('function'));
 const request={provider:'athena' as const,intent:{}};await act(async()=>root.render(<EditorRecoveryContext.Provider value={context}><EhrReadProviders requestedProvider={request} identity={identity} enabled workspace={ehrVisit} onAuthenticationLost={denied} onBusyChange={busy}/></EditorRecoveryContext.Provider>));expect(providerValue()).toBe('elation');expect(selectorDisabled()).toBe(true);
 const pending=(await retained('elation')).pending!;if(pending.kind!=='read')throw new Error();await act(async()=>finish(await ehrWindowReceipt(pending.request)));await wait(()=>expect(selectorDisabled()).toBe(false));expect(providerValue()).toBe('elation');expect(button('Check Athena allergy access')).toBeUndefined();
});
