/** Parent routing qualification. EncounterWorkspace, SettingsHub and encrypted
 * draft storage are real; signed workspace/account HTTP and the two already
 * qualified fax mounts are controlled boundaries. No provider/PDF/model I/O. */
import {act,useContext,type ComponentProps} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_VENDOR_SETUP_ENABLED','true');vi.stubEnv('VITE_FAX_INBOUND_ENABLED','true');vi.stubEnv('VITE_FAX_INBOUND_SOURCE_ENABLED','true');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {workspaceApi,type AuthenticatedWorkspaceIdentity,type Workspace,type WorkspaceEntry} from './workspace-api';
import {teamFixture,teamUuid as uuid} from './team-setup-test-fixture';
import {settingsNavigation} from './settings-test-navigation';
import {readConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary} from './connection-summary';
import {vendorSetupApi} from './vendor-setup-api';
import {accountIdentityApi} from './account-identity-api';
import {AccountRecoveryContext,type AccountRecoveryAccess} from './account-recovery';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal,editorAddress} from './draft-journal';
import {openDraftStore,privateDraftScope} from './draft-store';
import type {FaxInboundMount} from './FaxInboundMount';
import type {FaxSourceReviewMountProps} from './FaxSourceReviewMount';
import {faxInboundApi,type FaxPending,type FaxReceipt} from './fax-inbound-api';
import {faxScope} from './fax-inbound-fixtures.test-support';
import {FAX_SOURCE_LABEL,type FaxSourceOffer,type FaxSourceReceipt} from './fax-inbound-source-api';
import {emptyFaxSourceRecovery} from './fax-inbound-source-recovery';
import {vendorSha256} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./team-setup-api',async()=>{const {WorkspaceApiError}=await import('./workspace-api');return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404))}};});
vi.mock('./connection-catalog-api',async original=>({...await original<typeof import('./connection-catalog-api')>(),readConnectionCatalog:vi.fn()}));
vi.mock('./connection-summary',async original=>({...await original<typeof import('./connection-summary')>(),readConnectionSummary:vi.fn()}));
let inbound:ComponentProps<typeof FaxInboundMount>,source:FaxSourceReviewMountProps;
let accountAccess:AccountRecoveryAccess|null|undefined,editorAccess:EditorRecoveryAccess|null|undefined;
vi.mock('./FaxInboundMount',()=>({FaxInboundMount:(props:ComponentProps<typeof FaxInboundMount>)=>{
 inbound=props;accountAccess=useContext(AccountRecoveryContext);
 return <section aria-label="Controlled received-fax mount"><button disabled={props.locked} onClick={()=>props.onReviewDocument?.(documentOffer,acquireRequest)}>Review this received fax for the visit</button></section>;
}}));
vi.mock('./FaxSourceReviewMount',()=>({FaxSourceReviewMount:(props:FaxSourceReviewMountProps)=>{
 source=props;editorAccess=useContext(EditorRecoveryContext);
 return <section aria-label="Controlled fax passage mount"><p>{props.visit.label}</p><button disabled={props.locked} onClick={()=>props.onSaved?.(packet.receipt,structuredClone(packet.workspace))}>Save reviewed fax passage</button><button disabled={props.locked} onClick={()=>props.onAskChief?.(packet)}>Prepare Chief request from reviewed fax</button></section>;
}}));
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=> 'invented-signed-boundary'},opaque='a'.repeat(64),time='2026-10-02T14:00:00Z';
const documentOffer:FaxSourceOffer={operation_id:uuid(11),document_sha256:'d'.repeat(64),pages:1};
const acquireRequest:Extract<FaxPending,{kind:'acquire'}>={kind:'acquire',request:{idempotency_key:uuid(40),ticket_id:uuid(7),revision_id:uuid(9),expected_version:2,approval_sha256:'e'.repeat(64)}};
const privatePassage='Human-reviewed invented café passage. DOB and trial eligibility remain unknown.';
let root:Root,host:HTMLDivElement,idb:IDBFactory,current:Workspace&{appointment_id:string},packet:{receipt:FaxSourceReceipt;workspace:Workspace;entry:WorkspaceEntry};
let resolved:FaxReceipt;
const visible=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>!b.closest('[hidden]')&&b.textContent===label);
async function wait(check:()=>void|Promise<void>){for(let n=0;n<250;n++){let passed=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{await check();passed=true;}catch{}});if(passed)return;}await check();}
async function click(label:string){await wait(()=>expect(visible(label)?.disabled).toBe(false));await act(async()=>visible(label)!.click());}
async function setText(id:string,value:string){await act(async()=>{const field=host.querySelector<HTMLTextAreaElement>(id)!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function showNotebook(){await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-material-tabs button')].find(b=>b.textContent==='Notebook')!.click());}
async function settings(label:string){await wait(()=>{const buttons=[...host.querySelectorAll<HTMLButtonElement>('button')].filter(b=>!b.closest('[hidden]')),button=buttons.find(b=>b.textContent?.replace(/[←→›↗]/g,'').trim()===label||b.getAttribute('aria-label')===label||[...b.querySelectorAll('strong')].some(s=>s.textContent?.trim()===label));expect(button,`${label}: ${buttons.map(b=>b.textContent?.slice(0,100)).join(' | ')}`).toBeTruthy();expect(button?.matches(':disabled')).toBe(false);});await settingsNavigation(host).click(label);}
async function offerFax(){await settings('Team settings');await settings('Connections');await settings('Messaging & fax');await wait(()=>expect(accountAccess?.recoveryScope).toBe(opaque));await click('Review this received fax for the visit');await wait(()=>expect(source?.visit.id).toBe(current.id));}
async function preparePacket(){
 const entry:WorkspaceEntry={id:uuid(74),revision:3,kind:'fax_inbound_source',content:privatePassage,source_label:FAX_SOURCE_LABEL,origin:'human',ticket:null,created_at:time,practice_fax_source_state:'current'};
 current={...current,revision:3,entries:[...current.entries,entry]};
 packet={workspace:structuredClone(current),entry:structuredClone(entry),receipt:{contract_version:1,scope:{...faxScope,workspace_id:current.id},idempotency_key:uuid(41),request_sha256:'a'.repeat(64),review_id:uuid(42),entry_id:entry.id,entry_revision:3,operation_id:documentOffer.operation_id,source_sha256:'b'.repeat(64),content_sha256:await vendorSha256(new TextEncoder().encode(privatePassage)),document_sha256:documentOffer.document_sha256,page_numbers:[1],coverage:'human_selected_passage',extraction:'human_entered_no_ocr',source_withheld:false,state:'saved'}};
}
function assertNoWork(){expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();expect(faxInboundApi.command).not.toHaveBeenCalled();expect(faxInboundApi.document).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);idb=new IDBFactory();vi.stubGlobal('indexedDB',idb);vi.stubGlobal('fetch',vi.fn(async()=>{throw new Error('Unexpected HTTP outside controlled service boundary');}));
 const team=teamFixture();team.capture={enabled:false};team.scheduling={enabled:false};
 current={id:uuid(71),appointment_id:uuid(72),label:'Invented Shawn visit · DOB not provided',revision:2,work_candidates:[],entries:[{id:uuid(73),revision:2,kind:'scratchpad',content:'Existing saved clinical note',source_label:null,origin:'human',ticket:null,created_at:time},{id:uuid(75),revision:1,kind:'google_message',content:'Existing reviewed email',source_label:'Invented email',origin:'human',ticket:null,created_at:time,google_source_state:'current'},{id:uuid(76),revision:1,kind:'google_calendar',content:'Existing frozen calendar summary',source_label:'Invented event snapshot',origin:'human',ticket:null,created_at:time,calendar_source_state:'current'}]};
 accountAccess=editorAccess=undefined;
 vi.spyOn(workspaceApi,'privateDraftSummaries').mockResolvedValue({contract_version:2,drafts:[],has_more:false});vi.spyOn(workspaceApi,'team').mockImplementation(async()=>structuredClone(team));vi.spyOn(workspaceApi,'open').mockImplementation(async(auth)=>({identity:auth??identity,workspace:structuredClone(current),team:structuredClone(team)}));vi.spyOn(workspaceApi,'read').mockImplementation(async()=>structuredClone(current));vi.spyOn(workspaceApi,'catalog').mockImplementation(async()=>[{appointment_id:current.appointment_id,workspace_id:current.id,label:current.label}]);vi.spyOn(workspaceApi,'ask');vi.spyOn(workspaceApi,'append');
 vi.spyOn(accountIdentityApi,'read').mockResolvedValue({contract_version:1,box_id:faxScope.box_id,actor_id:faxScope.owner_id,recovery_scope:opaque});
 vi.spyOn(vendorSetupApi,'catalog').mockResolvedValue({contract_version:1,scope:faxScope,enabled:true,installed_accounts:[],patients:[],setups:[]});
 vi.mocked(readConnectionCatalog).mockResolvedValue({core:false,google:false,microsoft:false,scheduling:false,messaging:true,payments:false,portals:false});vi.mocked(readConnectionSummary).mockResolvedValue({label:'Connected',reason:'Invented practice fax account; controlled boundary',action:'Open fax work',tone:'ready'});
 resolved={contract_version:1,scope:faxScope,kind:'acquire',idempotency_key:acquireRequest.request.idempotency_key,request_sha256:'a'.repeat(64),public_request_sha256:'b'.repeat(64),receipt_sha256:'c'.repeat(64),state:'acquired',source_withheld:false,operation_id:documentOffer.operation_id,document_sha256:documentOffer.document_sha256,pages:1};vi.spyOn(faxInboundApi,'resolve').mockImplementation(async()=>structuredClone(resolved));vi.spyOn(faxInboundApi,'command');vi.spyOn(faxInboundApi,'document');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity}/>));await click('Visits and notes');await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.value).toBe('Existing saved clinical note'));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('routes actual settings to the current visit with the same authorized AES-GCM journal and no automatic image request',async()=>{
 await offerFax();expect(inbound.identity).toBe(identity);expect(source.identity).toBe(identity);expect(source.offered).toEqual(documentOffer);expect(source.visit).toEqual({id:current.id,label:current.label,revision:2});expect(host.querySelector('[aria-label="Controlled fax passage mount"]')?.closest('[hidden]')).toBeNull();
 await wait(()=>expect(editorAccess?.recoveryScope).toBe(opaque));expect(editorAccess?.workspaceId).toBe(current.id);expect(editorAccess?.journal).toBe(accountAccess?.journal);await act(async()=>{await accountAccess!.authorize();await editorAccess!.authorize();});
 const editor=`fax-source-review:${documentOffer.operation_id}` as const,address=editorAddress(current.id,editor),record={...emptyFaxSourceRecovery({...faxScope,workspace_id:current.id},documentOffer,source.visit),passage:privatePassage,page_numbers:[1]};
 await editorAccess!.journal.load(address);await editorAccess!.journal.persist(address,{kind:'editor',workspaceId:current.id,editor,data:record,pending:null});
 const namespace=await privateDraftScope(opaque,'http://127.0.0.1:8000',webcrypto),reader=new DraftJournal(await openDraftStore({scope:namespace,native:false,indexedDB:idb,crypto:webcrypto}));
 try{expect(await reader.load(address)).toEqual({kind:'editor',workspaceId:current.id,editor,data:record,pending:null});}finally{reader.close();}
 const database=await new Promise<IDBDatabase>((resolve,reject)=>{const r=idb.open('cosmas-private-drafts:v1:'+namespace);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
 try{const rows=await new Promise<Array<{address:string;ciphertext:ArrayBuffer;nonce:Uint8Array}>>((resolve,reject)=>{const r=database.transaction('sealed-drafts').objectStore('sealed-drafts').getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});const sealed=rows.find(r=>r.address===address);expect(sealed?.ciphertext.byteLength).toBeGreaterThan(16);expect(sealed?.nonce.byteLength).toBe(12);expect(sealed).not.toHaveProperty('body');expect(JSON.stringify(rows)).not.toContain(privatePassage);expect(JSON.stringify(rows)).not.toContain('Existing saved clinical note');}finally{database.close();}
 expect(faxInboundApi.resolve).not.toHaveBeenCalled();assertNoWork();
});
it('preserves unfinished notes, existing sources and the entered question while preparing an editable Chief request',async()=>{
 await setText('#team-notebook','Unfinished provider note');await setText('#team-question','Existing provider request');await offerFax();const existing=structuredClone(current.entries);await preparePacket();await click('Save reviewed fax passage');
 expect(source.currentSources).toEqual([{entry_id:packet.entry.id,state:'current'}]);expect(source.visit.revision).toBe(3);expect(packet.workspace.entries.filter(e=>e.id!==packet.entry.id)).toEqual(existing);
 await click('Prepare Chief request from reviewed fax');await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toContain(packet.entry.id));const question=host.querySelector<HTMLTextAreaElement>('#team-question')!.value;
 expect(question).toContain('Existing provider request');expect(question).toContain('without OCR or full-document coverage');expect(question).not.toContain(privatePassage);await showNotebook();expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe('Unfinished provider note');expect([...host.querySelectorAll('.team-roster button')].find(b=>b.querySelector('strong')?.textContent==='chief')?.getAttribute('aria-pressed')).toBe('true');expect(workspaceApi.read).toHaveBeenCalledWith(identity,current.id);assertNoWork();
});
it.each(['revoked','changed text','changed revision','withheld receipt','different workspace'] as const)('requires a fresh exact current source before preparing Chief: %s',async reason=>{
 await setText('#team-question','Preserved unanswered request');await offerFax();await preparePacket();await click('Save reviewed fax passage');
 if(reason==='revoked')current={...current,entries:current.entries.map(e=>e.id===packet.entry.id?{...e,content:'',practice_fax_source_state:'unavailable'}:e)};
 if(reason==='changed text')current={...current,entries:current.entries.map(e=>e.id===packet.entry.id?{...e,content:'Changed unreviewed private text'}:e)};
 if(reason==='changed revision')current={...current,entries:current.entries.map(e=>e.id===packet.entry.id?{...e,revision:4}:e)};
 if(reason==='withheld receipt')packet={...packet,receipt:{...packet.receipt,source_withheld:true}};
 if(reason==='different workspace')packet={...packet,receipt:{...packet.receipt,scope:{...packet.receipt.scope,workspace_id:uuid(88)}}};
 await click('Prepare Chief request from reviewed fax');await wait(()=>expect(host.querySelector('[role="alert"]')?.textContent).toBeTruthy());expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.value).toBe('Preserved unanswered request');await showNotebook();expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe('Existing saved clinical note');
 if(reason==='revoked')expect(source.currentSources).toEqual([{entry_id:packet.entry.id,state:'unavailable'}]);assertNoWork();
});
it('rechecks only the original acquisition receipt and refuses withheld or changed documents without reacquiring',async()=>{
 await offerFax();await act(async()=>expect(await source.onRefreshDocument!()).toEqual(documentOffer));expect(faxInboundApi.resolve).toHaveBeenCalledWith(identity,faxScope,acquireRequest);
 resolved={...resolved,source_withheld:true,document_sha256:null,pages:null};await act(async()=>expect(await source.onRefreshDocument!()).toBeNull());resolved={...resolved,source_withheld:false,document_sha256:'f'.repeat(64),pages:1};await act(async()=>expect(await source.onRefreshDocument!()).toBeNull());expect(faxInboundApi.resolve).toHaveBeenCalledTimes(3);assertNoWork();
});
it('locks navigation while passage work is pending and releases it without issuing work',async()=>{
 await offerFax();await act(async()=>source.onBusyChange!(true));expect(visible('Team settings')?.disabled).toBe(true);expect([...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].every(b=>b.disabled)).toBe(true);await act(async()=>visible('Team settings')!.click());expect(host.querySelector('.team-workspace')?.getAttribute('data-settings-open')).toBe('false');await act(async()=>source.onBusyChange!(false));await wait(()=>expect(visible('Team settings')?.disabled).toBe(false));assertNoWork();
});
it('allows the passage panel’s own verified Chief callback while its command is finishing, with unrelated navigation locked',async()=>{
 await offerFax();await preparePacket();await click('Save reviewed fax passage');await act(async()=>source.onBusyChange!(true));expect(visible('Team settings')?.disabled).toBe(true);await click('Prepare Chief request from reviewed fax');await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toContain(packet.entry.id));await act(async()=>source.onBusyChange!(false));assertNoWork();
});
it('hides a prior encounter offer after closing and opening another visit under the same signed account',async()=>{
 await offerFax();const old=source;await click('Close notebook');if(visible('Close anyway'))await click('Close anyway');await wait(()=>expect(visible('Visits and notes')).toBeDefined());expect(host.querySelector('[aria-label="Controlled fax passage mount"]')).toBeNull();current={...current,id:uuid(81),appointment_id:uuid(82),label:'Second invented encounter'};await click('Visits and notes');await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());await wait(()=>expect(host.textContent).toContain(current.label));await act(async()=>expect(await old.onRefreshDocument!()).toBeNull());await offerFax();expect(source.visit.id).toBe(uuid(81));expect(source.identity).toBe(identity);expect(faxInboundApi.resolve).not.toHaveBeenCalled();assertNoWork();
});
it('hides the old document offer on identity and visit changes and refuses its late refresh callback',async()=>{
 await offerFax();const old=source,nextIdentity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=> 'different-invented-signed-boundary'};
 current={...current,id:uuid(91),appointment_id:uuid(92),label:'Different invented encounter'};
 await act(async()=>root.render(<EncounterWorkspace authenticated={nextIdentity}/>));await wait(()=>expect(host.querySelector('[aria-label="Controlled fax passage mount"]')).toBeNull());await click('Visits and notes');await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());await wait(()=>expect(host.textContent).toContain(current.label));await act(async()=>expect(await old.onRefreshDocument!()).toBeNull());expect(faxInboundApi.resolve).not.toHaveBeenCalled();await offerFax();expect(source.identity).toBe(nextIdentity);expect(source.visit.id).toBe(uuid(91));assertNoWork();
});
it('never routes an invalid upstream document offer into source review',async()=>{
 await settings('Team settings');await settings('Connections');await settings('Messaging & fax');await act(async()=>inbound.onReviewDocument!({...documentOffer,document_sha256:'invalid'},acquireRequest));expect(host.querySelector('[aria-label="Controlled fax passage mount"]')).toBeNull();assertNoWork();
});
