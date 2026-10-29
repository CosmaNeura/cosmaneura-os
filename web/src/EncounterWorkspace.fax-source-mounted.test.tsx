/** Full workspace shell qualification with real SettingsHub, Sources, fax
 * source mount/panel and encrypted DraftJournal. The account receiving offer
 * and workspace/source APIs are controlled boundaries; no provider/model I/O. */
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
import {editorAddress} from './draft-journal';
import type {FaxInboundMount} from './FaxInboundMount';
import type {FaxSourceReviewMountProps} from './FaxSourceReviewMount';
import {faxInboundApi,type FaxPending,type FaxReceipt} from './fax-inbound-api';
import {faxScope} from './fax-inbound-fixtures.test-support';
import {faxSourceApi,faxSourceRequestHash,FAX_SOURCE_LABEL,type FaxSourceReviewRequest,type FaxSourceOffer,type FaxSourceReceipt} from './fax-inbound-source-api';
import {vendorSha256} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./team-setup-api',async()=>{const {WorkspaceApiError}=await import('./workspace-api');return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404))}};});
vi.mock('./connection-catalog-api',async original=>({...await original<typeof import('./connection-catalog-api')>(),readConnectionCatalog:vi.fn()}));
vi.mock('./connection-summary',async original=>({...await original<typeof import('./connection-summary')>(),readConnectionSummary:vi.fn()}));
let source:FaxSourceReviewMountProps;
let accountAccess:AccountRecoveryAccess|null|undefined,editorAccess:EditorRecoveryAccess|null|undefined;
vi.mock('./FaxInboundMount',()=>({FaxInboundMount:(props:ComponentProps<typeof FaxInboundMount>)=>{
 accountAccess=useContext(AccountRecoveryContext);
 return <section aria-label="Controlled received-fax mount"><button disabled={props.locked} onClick={()=>props.onReviewDocument?.(documentOffer,acquireRequest)}>Review this received fax for the visit</button></section>;
}}));
vi.mock('./FaxSourceReviewMount',async original=>{
 const actual=await original<typeof import('./FaxSourceReviewMount')>();
 return {FaxSourceReviewMount:(props:FaxSourceReviewMountProps)=>{source=props;editorAccess=useContext(EditorRecoveryContext);return <actual.FaxSourceReviewMount {...props}/>;}};
});
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=> 'invented-signed-boundary'},opaque='a'.repeat(64),time='2026-10-02T14:00:00Z';
const documentOffer:FaxSourceOffer={operation_id:uuid(11),document_sha256:'d'.repeat(64),pages:1};
const acquireRequest:Extract<FaxPending,{kind:'acquire'}>=  {kind:'acquire',request:{idempotency_key:uuid(40),ticket_id:uuid(7),revision_id:uuid(9),expected_version:2,approval_sha256:'e'.repeat(64)}};
const privatePassage='Human-reviewed invented café passage. DOB and trial eligibility remain unknown.';
let root:Root,host:HTMLDivElement,idb:IDBFactory,current:Workspace&{appointment_id:string},packet:{receipt:FaxSourceReceipt;workspace:Workspace;entry:WorkspaceEntry};
let resolved:FaxReceipt;
const visible=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>!b.closest('[hidden]')&&b.textContent===label);
async function wait(check:()=>void|Promise<void>){for(let n=0;n<250;n++){let passed=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{await check();passed=true;}catch{}});if(passed)return;}await check();}
async function click(label:string){await wait(()=>expect(visible(label)?.disabled).toBe(false));await act(async()=>visible(label)!.click());}
async function setText(id:string,value:string){await act(async()=>{const field=host.querySelector<HTMLTextAreaElement>(id)!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function showNotebook(){await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-material-tabs button')].find(b=>b.textContent==='Notebook')!.click());}
async function settings(label:string){await wait(()=>{const buttons=[...host.querySelectorAll<HTMLButtonElement>('button')].filter(b=>!b.closest('[hidden]')),button=buttons.find(b=>b.textContent?.replace(/[←→›↗]/g,'').trim()===label||b.getAttribute('aria-label')===label||[...b.querySelectorAll('strong')].some(s=>s.textContent?.trim()===label));expect(button,`${label}: ${buttons.map(b=>b.textContent?.slice(0,100)).join(' | ')}`).toBeTruthy();expect(button?.matches(':disabled')).toBe(false);});await settingsNavigation(host).click(label);}
async function offerFax(){await settings('Team settings');await settings('Connections');await settings('Messaging & fax');await wait(()=>expect(accountAccess?.recoveryScope).toBe(opaque));await click('Review this received fax for the visit');await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('textarea[aria-label="Fax passage"]')).toBeTruthy());}
async function saveReceipt(request:FaxSourceReviewRequest):Promise<FaxSourceReceipt>{
 const entry:WorkspaceEntry={id:uuid(74),revision:request.expected_revision+1,kind:'fax_inbound_source',content:request.passage,source_label:FAX_SOURCE_LABEL,origin:'human',ticket:null,created_at:time,practice_fax_source_state:'current'};
 current={...current,revision:entry.revision,entries:[...current.entries,entry]};
 const receipt:FaxSourceReceipt={contract_version:1,scope:{...faxScope,workspace_id:current.id},idempotency_key:request.idempotency_key,request_sha256:await faxSourceRequestHash({...faxScope,workspace_id:current.id},request),review_id:uuid(42),entry_id:entry.id,entry_revision:entry.revision,operation_id:request.operation_id,source_sha256:'b'.repeat(64),content_sha256:await vendorSha256(new TextEncoder().encode(request.passage)),document_sha256:request.document_sha256,page_numbers:request.page_numbers,coverage:'human_selected_passage',extraction:'human_entered_no_ocr',source_withheld:false,state:'saved'};
 packet={workspace:structuredClone(current),entry:structuredClone(entry),receipt};return receipt;
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
 vi.spyOn(faxSourceApi,'review').mockImplementation(async(_identity,_scope,request)=>saveReceipt(request));vi.spyOn(faxSourceApi,'resolve').mockImplementation(async()=>structuredClone(packet.receipt));
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity}/>));await click('Visits and notes');await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.value).toBe('Existing saved clinical note'));
 // Same-composer assertions start in Chief; separate-bot ownership is covered by source draft regressions.
 await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.querySelector('strong')?.textContent==='chief')!.click());
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('ordinary Connections offer reaches the real Sources review, saves encrypted passage and prepares an editable Chief request',async()=>{
 await setText('#team-notebook','Unfinished provider note');await setText('#team-question','Preserved provider question');await offerFax();
 expect(source.visit.id).toBe(current.id);expect(source.offered).toEqual(documentOffer);expect(host.querySelector('[aria-label="Review received fax passage"]')?.closest('[hidden]')).toBeNull();
 await wait(()=>expect(editorAccess?.recoveryScope).toBe(opaque));expect(editorAccess?.journal).toBe(accountAccess?.journal);expect(faxSourceApi.review).not.toHaveBeenCalled();
 await act(async()=>{
  const passage=host.querySelector<HTMLTextAreaElement>('textarea[aria-label="Fax passage"]')!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(passage,privatePassage);passage.dispatchEvent(new Event('input',{bubbles:true}));
  const pages=host.querySelector<HTMLInputElement>('input[aria-label="Pages used"]')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(pages,'1');pages.dispatchEvent(new Event('input',{bubbles:true}));
 });
 expect(visible('Save reviewed fax passage for this visit')!.disabled).toBe(true);
 await act(async()=>host.querySelectorAll<HTMLInputElement>('[aria-label="Review received fax passage"] input[type=checkbox]').forEach(c=>c.click()));
 vi.mocked(faxSourceApi.review).mockImplementationOnce(async(_identity,scope,request)=>{
  expect(scope).toEqual({...faxScope,workspace_id:current.id});const editor=`fax-source-review:${documentOffer.operation_id}` as const;
  const sealed=await editorAccess!.journal.load(editorAddress(current.id,editor));expect(sealed?.kind).toBe('editor');if(sealed?.kind!=='editor')throw Error('Missing encrypted source request');
  expect((sealed.data as {pending:{request:FaxSourceReviewRequest}}).pending.request).toEqual(request);return saveReceipt(request);
 });
 await click('Save reviewed fax passage for this visit');await wait(()=>expect(host.querySelector('[aria-label="Saved fax passage"]')?.textContent).toBe(privatePassage));
 expect(host.querySelector(`[id="source-${packet.entry.id}"]`)?.textContent).toContain(privatePassage);expect(host.textContent).toContain(FAX_SOURCE_LABEL);
 expect(faxSourceApi.review).toHaveBeenCalledOnce();expect(workspaceApi.ask).not.toHaveBeenCalled();
 await click('Prepare a Chief request');await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toContain(packet.entry.id));
 const question=host.querySelector<HTMLTextAreaElement>('#team-question')!;await wait(()=>expect(question.disabled).toBe(false));expect(question.value).toContain('Preserved provider question');expect(question.value).not.toContain(privatePassage);
 await setText('#team-question',question.value+' Ask about uncertainty before suggesting next steps.');expect(question.value).toContain('Ask about uncertainty');
 await showNotebook();expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe('Unfinished provider note');
 expect(faxSourceApi.resolve).toHaveBeenCalledOnce();assertNoWork();
});
