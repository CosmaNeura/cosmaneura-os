// @vitest-environment-options {"url":"https://workspace.example.invalid/"}
import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterAll,afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const [k,v] of Object.entries({VITE_COSMAS_ENV:'early_adopter_beta',VITE_WORKSPACE_ENABLED:'true',VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',
 VITE_WORKSPACE_SCHEDULING_ENABLED:'true',VITE_WORKSPACE_APPOINTMENTS_ENABLED:'true',VITE_WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED:'true',
 VITE_WORKSPACE_HOSTED_ENABLED:'true',VITE_WORKSPACE_DATA_MODE:'synthetic',VITE_WORKSPACE_HOSTED_CLIENT:'web',VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://api.example.invalid',
 VITE_WORKSPACE_WEB_ORIGIN:'https://workspace.example.invalid',VITE_API_BASE:'https://api.example.invalid',VITE_WORKSPACE_DESKTOP_AUTH_ENABLED:'false',VITE_WORKSPACE_NATIVE_AUTH_ENABLED:'false',
 VITE_DESKTOP_SYNTHETIC_ENABLED:'false',VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED:'false'}))vi.stubEnv(k,v);});
import {EncounterWorkspace} from './EncounterWorkspace';
import {workspaceApi,type Workspace,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {appointmentApi} from './appointment-api';
import {editorAddress} from './draft-journal';
import {openDraftStore,privateDraftScope} from './draft-store';
import {practiceAccessApi} from './practice-access-api';
import {admitWorkspaceProtocol,workspaceProtocolGeneration} from './workspace-protocol';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const util='node:util';const {transferableAbortController}=await import(/* @vite-ignore */util) as {transferableAbortController:()=>AbortController};
const environment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const configured=environment?.COSMAS_SCHEDULING_FULL_LAB_URL;
const local=(value:string)=>{const u=new URL(value);if(u.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(u.hostname)||u.pathname!=='/'||u.search||u.hash||u.username||u.password)throw new Error('Only the owned loopback test server is allowed.');return u.origin;};
const base=configured?local(configured):null,logical='https://api.example.invalid',realFetch=globalThis.fetch.bind(globalThis);
type Wire={path:string;method:string;action?:string;key?:string;status:number|null;lost?:boolean;body?:Record<string,unknown>;response_detail?:string;transport_error?:string};
type Episode={persona:string;round:number|string;passed:boolean;steps:string[];wire:Wire[];elapsed_ms:number;failure?:string;backend_diagnostics?:unknown};
type Packet={workspace:Workspace;token:string;dob:null};
type Counters={workspace:Workspace;receiver_calls:number;availability_calls:number;receiver_writes:number;mapping_reviews:number;setup_requests:number;proposal_count:number;
 appointment_receipts:number;operations:{started:boolean;attempt_count:number;external_reference:null|string}[];diagnostics:unknown[];receiver_ledger:{appointment_operations:number;calendar_jobs:number};master_writer:{direct_identity_fixture_writes:number;other_patient:string};mapping_patient_id:string|null};
const episodes:Episode[]=[],transports=new Set<Promise<Response>>(),bridges:(()=>void)[]=[];
let root:Root|undefined,host:HTMLDivElement,idb:IDBFactory,identity:AuthenticatedWorkspaceIdentity,packet:Packet,active:Episode|undefined,loseConfirmation:boolean,loseProposal:boolean;
const button=(name:string,region:ParentNode=host)=>{const b=[...region.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===name||b.getAttribute('aria-label')===name);expect(b,name).toBeTruthy();return b!;};
async function wait(check:()=>void|Promise<void>){const until=performance.now()+10000;while(performance.now()<until){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,10));try{await check();done=true;}catch{}});if(done)return;}await check();}
async function click(name:string,region:ParentNode=host){await wait(()=>expect(button(name,region).disabled,name).toBe(false));await act(async()=>button(name,region).click());}
async function field(label:string,value:string){const input=host.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;expect(input).toBeTruthy();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}
const preserved=(w:Workspace)=>JSON.stringify({note:w.note,entries:w.entries,revision:w.revision});
async function inspect():Promise<Counters>{const r=await realFetch(`${base}/lab/inspect?workspace_id=${packet.workspace.id}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(r.status,await r.clone().text()).toBe(200);return r.json();}
async function assertPreserved(){const c=await inspect();expect(preserved(c.workspace)).toBe(preserved(packet.workspace));expect(c.receiver_writes).toBe(0);expect(c.appointment_receipts).toBe(0);expect(c.receiver_ledger.appointment_operations).toBe(0);expect(c.receiver_ledger.calendar_jobs).toBe(0);expect(c.master_writer.direct_identity_fixture_writes).toBe(0);
 expect(c.operations.every(o=>!o.started&&o.attempt_count===0&&o.external_reference===null)).toBe(true);return c;}
async function mount(){root=createRoot(host);await act(async()=>root!.render(<EncounterWorkspace authenticated={identity}/>));await click('Visits and notes');
 await wait(()=>expect([...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].some(b=>b.textContent?.includes(packet.workspace.label))).toBe(true));
 await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].find(b=>b.textContent?.includes(packet.workspace.label))!.click());await wait(()=>expect(host.querySelector('#team-notebook')).toBeTruthy());
 const follow=[...host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent==='Follow-up')!;expect(follow).toBeTruthy();await act(async()=>follow.click());
 await wait(()=>expect(host.querySelector('[aria-label="Scheduling patient setup"]')).toBeTruthy());}
async function open(persona:string,round:string){const r=await realFetch(`${base}/lab/case?persona=${persona}&round=${round}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(r.status,await r.clone().text()).toBe(200);packet=await r.json();expect(packet.dob).toBeNull();
 identity={mode:'clerk_jwt',getToken:async()=>packet.token};const g=workspaceProtocolGeneration(identity);await practiceAccessApi.compatibility(identity);admitWorkspaceProtocol(identity,g);await mount();}
function sameFailure(){const previous=episodes.find(e=>e.failure);if(previous)throw new Error('Prior episode failed; diagnostic stopped before creating another case: '+previous.failure!.split('\n')[0]);}
async function reopen(){await act(async()=>root!.unmount());root=undefined;await mount();}
async function lookup(){const region=host.querySelector('[aria-label="Scheduling patient setup"]')!;await click('Check patient setup',region);await wait(()=>expect(host.querySelector('[aria-label="Patient name"]')).toBeTruthy());
 await field('Patient name','Invented Jordan');expect(host.querySelector<HTMLInputElement>('[aria-label="Date of birth (optional)"]')!.value).toBe('');await click('Find patient',region);await wait(()=>expect(host.querySelector('[aria-label="Patient matches"]')).toBeTruthy());
 expect(host.querySelector('[aria-label="Patient matches"] button')?.getAttribute('aria-pressed')).toBe('false');expect(region.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);}
async function confirm(){const region=host.querySelector('[aria-label="Scheduling patient setup"]')!;await click('Invented Jordan café · DOB not supplied',region);expect(button('Save patient connection',region).disabled).toBe(true);
 const checks=region.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');expect(checks).toHaveLength(2);for(const q of checks)await act(async()=>q.click());await click('Save patient connection',region);}
async function checkEncrypted(){const team=await workspaceApi.team(identity),scope=await privateDraftScope(team.recovery_scope!,logical);
 const database=await new Promise<IDBDatabase>((resolve,reject)=>{const q=idb.open(`cosmas-private-drafts:v1:${scope}`);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
 try{const tx=database.transaction(['sealed-drafts','metadata'],'readonly');const rows=await new Promise<unknown[]>((resolve,reject)=>{const q=tx.objectStore('sealed-drafts').getAll();q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
 expect(rows.length).toBeGreaterThan(0);expect(JSON.stringify(rows)).not.toContain('Invented Jordan');expect(JSON.stringify(rows)).not.toContain('Invented existing clinical');
 const key=await new Promise<CryptoKey>((resolve,reject)=>{const q=tx.objectStore('metadata').get('draft-key-v1');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});expect(key.extractable).toBe(false);expect(key.algorithm.name).toBe('AES-GCM');}finally{database.close();}}
async function restorePatient(){await click('Restore scheduling patient draft');await click('Check saved patient details');await wait(()=>expect(host.textContent).toContain('Patient ready'));}
async function savedProposal(ticket:string){await wait(()=>expect([...host.querySelectorAll<HTMLButtonElement>('[aria-label="Appointments"] details button')].some(b=>b.textContent?.includes(' · Approved'))).toBe(true));
 const region=host.querySelector('[aria-label="Appointments"]')!;await act(async()=>[...region.querySelectorAll<HTMLButtonElement>('details button')].find(b=>b.textContent?.includes(' · Approved'))!.click());await wait(()=>expect(region.textContent).toContain('Proposal approved. Scheduling has not booked or changed the visit.'));
 expect((await appointmentApi.read(packet.workspace.id,identity,ticket)).state).toBe('approved');}
async function prepare(action:'book'|'reschedule'|'cancel'='book'){await wait(()=>expect(host.textContent).toContain('Patient ready'));
 if(action!=='cancel'){const tomorrow=new Date();tomorrow.setDate(tomorrow.getDate()+1);await field('Availability week starting',`${tomorrow.getFullYear()}-${String(tomorrow.getMonth()+1).padStart(2,'0')}-${String(tomorrow.getDate()).padStart(2,'0')}`);await click('Refresh availability');await wait(()=>expect(button('Choose this time').disabled).toBe(false));await click('Choose this time');}
 if(action!=='book'){await click('Refresh linked visit');await wait(()=>expect(host.textContent).toContain('Linked visit:'));const select=host.querySelector<HTMLSelectElement>('[aria-label="Appointments"] select')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value')!.set!.call(select,action);select.dispatchEvent(new Event('change',{bubbles:true}));});}
 const region=host.querySelector('[aria-label="Appointments"]')!;await wait(()=>expect(region.querySelector('input[type="checkbox"]')).toBeTruthy());const ack=region.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
 expect(ack.checked).toBe(false);expect(button('Prepare appointment proposal',region).disabled).toBe(true);await act(async()=>ack.click());await click('Prepare appointment proposal',region);
}
async function proposal(action:'book'|'reschedule'|'cancel'='book'){
 await prepare(action);const region=host.querySelector('[aria-label="Appointments"]')!;await wait(()=>expect(region.textContent).toContain('Awaiting your review.'));
 const catalog=await appointmentApi.catalog(packet.workspace.id,identity);expect(catalog.items).toHaveLength(1);const item=await appointmentApi.read(packet.workspace.id,identity,catalog.items[0].ticket_id);
 expect(item).toMatchObject({state:'pending_approval',appointment_saved:false,dispatch_started:false,operation_id:null});expect(item.intent.selection.patient_link_id).toBeTruthy();expect(item.intent.action).toBe(action);if(action!=='book')expect(item.intent.expected?.version).toBeTruthy();
 await click('Approve this appointment change',region);await wait(()=>expect(region.textContent).toContain('Proposal approved. Scheduling has not booked or changed the visit.'));
 const request=active!.wire.find(w=>w.path.endsWith('/decide'))!;expect(request.body).toMatchObject({revision_id:item.revision_id,payload_hash:item.payload_hash,choice:'approve'});
 expect([...region.querySelectorAll('button')].some(b=>b.textContent==='Send approved appointment change')).toBe(false);expect(active!.wire.some(w=>w.path.endsWith('/execute'))).toBe(false);
 const c=await assertPreserved();expect(c.proposal_count).toBe(1);expect(c.receiver_calls).toBe(2);expect(c.mapping_reviews).toBe(1);expect(c.setup_requests).toBe(2);expect(c.availability_calls).toBeGreaterThan(0);await checkEncrypted();
 const reads=c.availability_calls;await reopen();await restorePatient();await savedProposal(item.ticket_id);expect((await inspect()).availability_calls).toBe(reads);
 await click('Withdraw proposal');await wait(()=>expect(host.querySelector('[aria-label="Appointments"]')?.textContent).toContain('Withdrawn.'));await assertPreserved();}
beforeEach(()=>{window.history.replaceState(null,'',window.location.pathname+window.location.search);if(!base)return;vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();vi.stubGlobal('indexedDB',idb);host=document.createElement('div');document.body.append(host);loseConfirmation=false;loseProposal=false;
 vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{const u=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);if(u.origin!==logical)throw new Error('Only the exact invented hosted API is allowed.');
 let native=init;if(init?.signal){const source=init.signal,target=transferableAbortController(),abort=()=>target.abort(source.reason);source.addEventListener('abort',abort,{once:true});if(source.aborted)abort();bridges.push(()=>source.removeEventListener('abort',abort));native={...init,signal:target.signal};}
 const value=init?.body?JSON.parse(String(init.body)) as Record<string,unknown>:undefined,owner=active,record:Wire={path:u.pathname,method:init?.method??'GET',status:null,...value?.action?{action:String(value.action)}:{},...value?.idempotency_key?{key:String(value.idempotency_key)}:{},...value?{body:value}:{}};
 owner?.wire.push(record);const transport=realFetch(base+u.pathname+u.search,native);transports.add(transport);try{const r=await transport;record.status=r.status;Object.defineProperty(r,'url',{value:u.href});
 if(r.status!==200){try{const error=await r.clone().json() as {detail?:unknown};if(typeof error.detail==='string')record.response_detail=error.detail.slice(0,200);}catch{record.response_detail='Unparseable error response';}}
 if(loseProposal&&u.pathname.endsWith('/appointments')&&r.status===200){loseProposal=false;await r.arrayBuffer();record.lost=true;throw new TypeError('Lost committed proposal reply');}
 if(loseConfirmation&&value?.action==='confirm'&&r.status===200){loseConfirmation=false;loseProposal=false;await r.arrayBuffer();record.lost=true;throw new TypeError('Lost committed confirmation reply');}return r;
 }catch(error){record.transport_error=error instanceof Error?error.name+': '+error.message.slice(0,200):'Transport failed';throw error;}finally{transports.delete(transport);}});
});
afterEach(async()=>{if(active?.failure&&packet?.workspace.id){try{active.backend_diagnostics=(await inspect()).diagnostics;}catch{/* Keep the original failure when even the lab-only diagnostic cannot be read. */}}if(root){await act(async()=>root!.unmount());root=undefined;}try{if(transports.size)await Promise.race([Promise.allSettled([...transports]),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Owned transport did not settle after unmount')),10000))]);}
 finally{bridges.splice(0).forEach(f=>f());host?.remove();active=undefined;vi.unstubAllGlobals();await saveReport();}});
it.skipIf(!base).each([{persona:'physician',round:1},{persona:'nurse_practitioner',round:1},{persona:'physician_assistant',round:1},{persona:'physician',round:2},{persona:'nurse_practitioner',round:2},{persona:'physician_assistant',round:2}])('$persona round $round connects without DOB, reviews and reopens an unsubmitted signed receiver proposal',async({persona,round})=>{
 const started=performance.now(),episode:Episode={persona,round,passed:false,steps:[],wire:[],elapsed_ms:0};sameFailure();active=episode;episodes.push(episode);try{await open(persona,String(round));expect((await inspect()).mapping_reviews).toBe(0);episode.steps.push('unmapped_signed_visit');
 await lookup();await confirm();await proposal(persona==='physician'?'book':persona==='nurse_practitioner'?'reschedule':'cancel');episode.steps.push('explicit_DOB_optional_signed_master_mapping_exact_proposal_human_approval_encrypted_reopen_withdraw');expect(episode.wire.every(w=>w.status===200&&!w.lost)).toBe(true);episode.passed=true;
 }catch(e){episode.failure=String(e)+'\nDOM: '+host.textContent;throw e;}finally{episode.elapsed_ms=Math.round(performance.now()-started);}
},60000);
it.skipIf(!base)('reopens a lost committed patient confirmation and resolves its original encrypted key without receiver retry',async()=>{
 const started=performance.now(),episode:Episode={persona:'physician',round:'lost_confirmation',passed:false,steps:[],wire:[],elapsed_ms:0};sameFailure();active=episode;episodes.push(episode);
 try{await open('physician','lost_confirmation');await lookup();loseConfirmation=true;await confirm();await wait(()=>{
  expect(episode.wire.find(w=>w.action==='confirm')?.lost).toBe(true);expect(host.querySelector('[aria-label="Scheduling patient setup"]')?.getAttribute('aria-busy')).toBe('false');expect(host.textContent).toContain('Patient setup could not be confirmed');
 });const original=episode.wire.find(w=>w.action==='confirm')!;expect(original.lost).toBe(true);
 const c=await assertPreserved();expect(c.receiver_calls).toBe(2);expect(c.mapping_reviews).toBe(1);const before=episode.wire.filter(w=>['preview','confirm'].includes(w.action??'')).length;
 await reopen();await click('Restore scheduling patient draft');await wait(()=>expect(button('Check saved setup result').disabled).toBe(false));expect(episode.wire.filter(w=>['preview','confirm'].includes(w.action??''))).toHaveLength(before);
 await click('Check saved setup result');await wait(()=>expect(host.textContent).toContain('Patient ready'));const resolved=episode.wire.find(w=>w.action==='resolve')!;expect(resolved.key).toBe(original.key);expect((await inspect()).receiver_calls).toBe(2);
 const team=await workspaceApi.team(identity),scope=await privateDraftScope(team.recovery_scope!,logical),store=await openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});try{expect((await store.read(editorAddress(packet.workspace.id,'scheduling-patient'))).value?.body).toMatchObject({pending:null,data:{pending:null,saved:{request_key:original.key}}});}finally{store.close();}
 await proposal();episode.steps.push('encrypted_reopen_original_key_resolve_no_receiver_repeat');episode.passed=true;
 }catch(e){episode.failure=String(e)+'\nDOM: '+host.textContent;throw e;}finally{episode.elapsed_ms=Math.round(performance.now()-started);}
},60000);
it.skipIf(!base)('masks earlier patient identity after same-account reconnect and an actual parent workspace refresh',async()=>{
 const started=performance.now(),episode:Episode={persona:'physician',round:'reconnect',passed:false,steps:[],wire:[],elapsed_ms:0};sameFailure();active=episode;episodes.push(episode);
 try{await open('physician','reconnect');await lookup();await confirm();await wait(()=>expect(host.textContent).toContain('Patient ready'));const r=await realFetch(base+'/lab/reconnect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:packet.workspace.id})});expect(r.status).toBe(200);
 await click('Refresh encounter');await wait(()=>expect(button('Refresh encounter').disabled).toBe(false));expect(host.textContent).not.toContain('Invented Jordan café');expect(host.textContent).not.toContain('Patient ready');await click('Check saved patient details');
 await wait(()=>expect(host.textContent).toContain('Patient details are unavailable'));expect(host.textContent).not.toContain('Invented Jordan café');expect((await inspect()).receiver_calls).toBe(2);await assertPreserved();episode.steps.push('same_account_reconnect_current_parent_observation_masks_historical_receipt');episode.passed=true;
 }catch(e){episode.failure=String(e)+'\nDOM: '+host.textContent;throw e;}finally{episode.elapsed_ms=Math.round(performance.now()-started);}
},60000);
it.skipIf(!base)('recovers a committed proposal save from the encrypted full workspace without repeating receiver reads',async()=>{
 const started=performance.now(),episode:Episode={persona:'physician',round:'lost_proposal',passed:false,steps:[],wire:[],elapsed_ms:0};sameFailure();active=episode;episodes.push(episode);
 try{await open('physician','lost_proposal');await lookup();await confirm();loseProposal=true;await prepare();await wait(()=>expect(host.textContent).toContain('The request could not be confirmed'));
 const original=episode.wire.find(w=>w.method==='POST'&&w.path.endsWith('/appointments'))!;expect(original.lost).toBe(true);const before=await assertPreserved();expect(before.proposal_count).toBe(1);await checkEncrypted();
 await reopen();await restorePatient();await click('Restore appointment draft');await click('Retry the same save');await wait(()=>expect(host.textContent).toContain('Awaiting your review.'));
 const repeated=episode.wire.filter(w=>w.method==='POST'&&w.path.endsWith('/appointments'));expect(repeated).toHaveLength(2);expect(repeated[1].body).toEqual(original.body);const after=await assertPreserved();expect(after.proposal_count).toBe(1);expect(after.availability_calls).toBe(before.availability_calls);expect(after.receiver_calls).toBe(before.receiver_calls);
 episode.steps.push('sealed_journal_fresh_mount_same_proposal_key_recovery_no_receiver_repeat');episode.passed=true;
 }catch(e){episode.failure=String(e)+'\nDOM: '+host.textContent;throw e;}finally{episode.elapsed_ms=Math.round(performance.now()-started);}
},60000);
it.skipIf(!base)('signed master revocation refuses a stale exact patient choice without saving a personal mapping',async()=>{
 const started=performance.now(),episode:Episode={persona:'physician',round:'source_revoke',passed:false,steps:[],wire:[],elapsed_ms:0};sameFailure();active=episode;episodes.push(episode);
 try{await open('physician','source_revoke');await lookup();let r=await realFetch(base+'/lab/master',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:packet.workspace.id,operation:'revoke'})});expect(r.status).toBe(200);
 await confirm();await wait(()=>expect(host.textContent).toContain('Patient setup could not be confirmed'));expect(host.querySelector('[aria-label="Scheduling patient setup"]')?.textContent).not.toContain('Invented Jordan café');const before=await assertPreserved();expect(before.mapping_reviews).toBe(0);expect(before.receiver_calls).toBe(2);await checkEncrypted();
 await reopen();await click('Restore scheduling patient draft');await click('Check saved setup result');await wait(()=>expect(host.textContent).toContain('unfinished'));expect((await inspect()).receiver_calls).toBe(2);
 r=await realFetch(base+'/lab/master',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:packet.workspace.id,operation:'restore'})});expect(r.status).toBe(200);
 episode.steps.push('signed_master_tombstone_stale_choice_refusal_encrypted_original_command_no_retry');episode.passed=true;
 }catch(e){episode.failure=String(e)+'\nDOM: '+host.textContent;throw e;}finally{episode.elapsed_ms=Math.round(performance.now()-started);}
},60000);
it.skipIf(!base)('keeps same-name signed-master records as two unselected opaque choices with optional DOB',async()=>{
 const started=performance.now(),episode:Episode={persona:'physician',round:'same_name',passed:false,steps:[],wire:[],elapsed_ms:0};sameFailure();active=episode;episodes.push(episode);
 try{await open('physician','same_name');const r=await realFetch(base+'/lab/master',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:packet.workspace.id,operation:'same_name'})});expect(r.status).toBe(200);await lookup();
 const choices=host.querySelectorAll<HTMLButtonElement>('[aria-label="Patient matches"] button');expect(choices).toHaveLength(2);expect([...choices].every(b=>b.getAttribute('aria-pressed')==='false')).toBe(true);expect(new Set([...choices].map(b=>b.textContent)).size).toBe(1);expect((await assertPreserved()).mapping_reviews).toBe(0);
 await act(async()=>choices[1].click());const region=host.querySelector('[aria-label="Scheduling patient setup"]')!;const checks=region.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');expect(checks).toHaveLength(2);for(const q of checks)await act(async()=>q.click());await click('Save patient connection',region);await wait(()=>expect(host.textContent).toContain('Patient ready'));
 const after=await assertPreserved();expect(after.mapping_reviews).toBe(1);expect(after.mapping_patient_id).toBe(after.master_writer.other_patient);expect(after.receiver_calls).toBe(2);await checkEncrypted();
 episode.steps.push('two_same_name_null_DOB_distinct_opaque_choices_human_selects_second_exact_patient');episode.passed=true;
 }catch(e){episode.failure=String(e)+'\nDOM: '+host.textContent;throw e;}finally{episode.elapsed_ms=Math.round(performance.now()-started);}
},60000);
async function saveReport(){if(!base||!environment?.COSMAS_SCHEDULING_FULL_LAB_REPORT)return;const mod='node:fs/promises';const fs=await import(/* @vite-ignore */mod) as {writeFile:(p:string,v:string)=>Promise<void>};
 await fs.writeFile(environment.COSMAS_SCHEDULING_FULL_LAB_REPORT,JSON.stringify({schema:'cosmabot.scheduling-full-workspace-signed-master-receiver-ui.v1',synthetic_only:true,
 boundary:'Actual EncounterWorkspace and SchedulingPatientPanel, default AES-GCM browser DraftStore with fake IndexedDB, signed Clerk-shaped JWT/FastAPI/real PostgreSQL. Actual Scheduling receiver signed staff verifier, independently credentialed signed master writer and separate restricted PostgreSQL projection. Staff/account binding and Google OAuth/free-busy are invented substitutes. Consumer HTTP adapters route via MockTransport into actual receiver ASGI. Logical HTTPS-origin bridge only; no external request, booking, physical device or real patient.',
 total:episodes.length,completed:episodes.filter(e=>e.passed).length,episodes},null,2)+'\n');}
afterAll(saveReport);
