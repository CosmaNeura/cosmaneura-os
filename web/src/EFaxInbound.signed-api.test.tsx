import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterAll,afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const [key,value] of Object.entries({VITE_COSMAS_ENV:'synth_os',VITE_WORKSPACE_ENABLED:'true',
 VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',VITE_EFAX_INBOUND_ENABLED:'true',VITE_WORKSPACE_HOSTED_ENABLED:'false',
 VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED:'false',VITE_DESKTOP_SYNTHETIC_ENABLED:'false'}))vi.stubEnv(key,value);});
import {EFaxInboundMount} from './EFaxInboundMount';
import {AccountRecoveryContext,type AccountRecoveryAccess} from './account-recovery';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {openDraftStore,privateDraftScope} from './draft-store';
import {type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import {validateEFaxRecovery} from './efax-inbound-recovery';
import {efaxPublicHash,type EFaxPending,type EFaxReceipt} from './efax-inbound-api';
import {vendorSha256} from './vendor-contract';
import {ScribeLabEpisode} from './scribe-lab-episode';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const {Blob:NativeBlob}=await vi.importActual<{Blob:typeof Blob}>('node:buffer');
const util='node:util';
const {transferableAbortController}=await import(/* @vite-ignore */util) as {transferableAbortController:()=>AbortController};
const environment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const configured=environment?.COSMAS_EFAX_INBOUND_LAB_URL;
function local(value:string){const u=new URL(value);if(u.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(u.hostname)||u.pathname!=='/'||u.search||u.hash||u.username||u.password)throw new Error('Only the owned loopback synthetic server is permitted.');return u.origin;}
const base=configured?local(configured):null,realFetch=globalThis.fetch.bind(globalThis),address=accountEditorAddress('efax-inbound');
type Packet={case_id:string;token:string;workspace:Workspace;installation_id:string;fax_id:string;pdf_sha256:string;pdf_byte_length:number};
type Wire={method:string;path:string;status:number|null;key?:string;body?:Record<string,unknown>;receipt?:EFaxReceipt;lost?:boolean;error?:string;response_detail?:string};
type Trial={persona:string;round:number;passed:boolean;case_id:string;steps:Array<{name:string;elapsed_ms:number}>;wire:Wire[];elapsed_ms:number;failure?:string;backend?:Counters};
type Counters={case_id:string;workspace:Workspace;provider_calls:number;credential_calls:number;case_provider_calls:number;case_credential_calls:number;image_calls:number;restarts:number;
 operation:null|{id:string;status:string;attempt_count:number;acquisition:boolean;invocation:boolean;outcome:string|null;document_sha256:string|null;document_pages:number|null;decisions:number;patient_link_id:null;appointment_id:null}};
type Episode={lifecycle:ScribeLabEpisode;host:HTMLDivElement;root:Root|null;idb:IDBFactory;identity:AuthenticatedWorkspaceIdentity;account:AccountIdentity|null;
 journal:DraftJournal|null;namespace:string;access:AccountRecoveryAccess|null;packet:Packet|null;trial:Trial|null;loseAcquire:boolean;denials:unknown[];blobs:Map<string,Blob>};
const trials:Trial[]=[];let current:Episode|undefined,terminalFailure:string|undefined;
function controls(ep:Episode){
 const check=()=>ep.lifecycle.check();
 const button=(label:string)=>{check();const b=[...ep.host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===label);expect(b,label).toBeTruthy();return b!;};
 async function wait(assertion:()=>void|Promise<void>){const deadline=performance.now()+10000;while(performance.now()<deadline){check();let passed=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));check();try{await assertion();passed=true;}catch{}});if(passed)return;}check();await assertion();}
 async function idle(){await wait(()=>expect(ep.host.textContent).not.toContain('Waiting for the current received-fax operation'));}
 async function click(label:string){await wait(()=>expect(button(label).disabled,label).toBe(false));await act(async()=>button(label).click());}
 async function tick(label:string){const field=[...ep.host.querySelectorAll<HTMLLabelElement>('label')].find(l=>l.textContent?.includes(label))?.querySelector<HTMLInputElement>('input[type="checkbox"]');expect(field,label).toBeTruthy();expect(field!.disabled).toBe(false);await act(async()=>field!.click());}
 async function choose(label:string,value:string){const field=[...ep.host.querySelectorAll<HTMLLabelElement>('label')].find(l=>l.textContent?.trim().startsWith(label))?.querySelector<HTMLSelectElement>('select');expect(field,label).toBeTruthy();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value')!.set!.call(field,value);field!.dispatchEvent(new Event('change',{bubbles:true}));});}
 async function saved(){const entry=await ep.journal!.load(address);expect(entry?.kind).toBe('account-editor');if(!entry||entry.kind!=='account-editor')throw new Error('Encrypted eFax record is missing');expect(entry.editor).toBe('efax-inbound');expect(entry.pending).toBeNull();return validateEFaxRecovery(entry.data,{box_id:ep.account!.box_id,owner_id:ep.account!.actor_id});}
 async function inspect(){const r=await ep.lifecycle.fetch(realFetch,`${base}/lab/inspect?case_id=${ep.packet!.case_id}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(r.status,await r.clone().text()).toBe(200);return r.json() as Promise<Counters>;}
 return {button,wait,idle,click,tick,choose,saved,inspect};
}
async function openJournal(ep:Episode){
 ep.account=await accountIdentityApi.read(ep.identity);ep.lifecycle.check();
 if(!ep.namespace)ep.namespace=await privateDraftScope(ep.account.recovery_scope,base!,webcrypto);
 ep.journal=new DraftJournal(await openDraftStore({scope:ep.namespace,native:false,indexedDB:ep.idb,crypto:webcrypto}));
 const expected={...ep.account};ep.access={journal:ep.journal,recoveryScope:expected.recovery_scope,authorize:async()=>{
  ep.lifecycle.check();const now=await accountIdentityApi.read(ep.identity);ep.lifecycle.check();expect(now).toEqual(expected);
 }};
}
async function mount(ep:Episode){await openJournal(ep);ep.root=createRoot(ep.host);await act(async()=>ep.root!.render(
 <AccountRecoveryContext.Provider value={ep.access}><EFaxInboundMount identity={ep.identity} onAuthenticationLost={e=>ep.denials.push(e)}/></AccountRecoveryContext.Provider>
));}
async function sealedRows(ep:Episode){const db=await new Promise<IDBDatabase>((resolve,reject)=>{const r=ep.idb.open('cosmas-private-drafts:v1:'+ep.namespace);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});try{return await new Promise<unknown[]>((resolve,reject)=>{const r=db.transaction('sealed-drafts').objectStore('sealed-drafts').getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}finally{db.close();}}
beforeEach(()=>{
 if(!base)return;if(terminalFailure)throw new Error('Prior signed eFax episode failed; no new case admitted: '+terminalFailure);
 const native=transferableAbortController();vi.stubGlobal('AbortController',native.constructor);vi.stubGlobal('AbortSignal',native.signal.constructor);
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('Blob',NativeBlob);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE',base);
 vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 const host=document.createElement('div');document.body.append(host);const ep:Episode={lifecycle:new ScribeLabEpisode(),host,root:null,idb:new IDBFactory(),identity:{mode:'clerk_jwt',getToken:async()=>{throw new Error('Signed case has not been admitted');}},
  account:null,journal:null,namespace:'',access:null,packet:null,trial:null,loseAcquire:false,denials:[],blobs:new Map()};current=ep;
 // Blob URL/file-picker are browser platform boundaries, not API/document mocks.
 Object.defineProperty(URL,'createObjectURL',{configurable:true,value:(blob:Blob)=>{const href='blob:synthetic-efax-'+crypto.randomUUID();ep.blobs.set(href,blob);return href;}});
 Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:(href:string)=>{ep.blobs.delete(href);}});
 vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
  ep.lifecycle.check();const u=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);if(u.origin!==base||!(u.pathname==='/provider-team/identity'||u.pathname.startsWith('/efax-inbound')))throw new Error('Only the exact signed synthetic product routes are permitted.');
  const body=init?.body?JSON.parse(String(init.body)) as Record<string,unknown>:undefined,wire:Wire={method:init?.method??'GET',path:u.pathname,status:null,...body?{body}: {},...typeof body?.idempotency_key==='string'?{key:body.idempotency_key}:{}};
  ep.trial?.wire.push(wire);
  try{
   if(body&&['/efax-inbound/grant','/efax-inbound/observe','/efax-inbound/propose','/efax-inbound/decide','/efax-inbound/acquire'].includes(u.pathname)){
    const persisted=await ep.journal!.load(address);expect(persisted?.kind).toBe('account-editor');
    if(!persisted||persisted.kind!=='account-editor')throw new Error('A command reached dispatch before encrypted custody');
    const saved=await validateEFaxRecovery(persisted.data,{box_id:ep.account!.box_id,owner_id:ep.account!.actor_id});
    expect(saved.pending).toEqual({kind:u.pathname.split('/').at(-1),request:body});
   }
   const response=await ep.lifecycle.fetch(realFetch,input,init);wire.status=response.status;
   if(response.status!==200){const error=await response.clone().json() as {detail?:unknown;error?:{code?:unknown}};wire.response_detail=String(error.detail??error.error?.code??'unrecognized error').slice(0,200);}
   if(body&&['/efax-inbound/grant','/efax-inbound/observe','/efax-inbound/propose','/efax-inbound/decide','/efax-inbound/acquire','/efax-inbound/resolve'].includes(u.pathname)&&response.status===200)wire.receipt=await response.clone().json() as EFaxReceipt;
   if(ep.loseAcquire&&u.pathname==='/efax-inbound/acquire'&&response.status===200){ep.loseAcquire=false;await response.arrayBuffer();wire.lost=true;throw new TypeError('Invented lost image-acquisition reply after actual server commit');}
   return response;
  }catch(error){wire.error=error instanceof Error?error.message:String(error);throw error;}
 });
});
afterEach(async()=>{
 if(!base||!current)return;const ep=current;ep.lifecycle.close();
 try{try{await ep.lifecycle.drain(10000);}finally{if(ep.root){await act(async()=>ep.root!.unmount());ep.root=null;}ep.journal?.close();ep.journal=null;expect(ep.blobs.size).toBe(0);}}
 catch(error){terminalFailure=String(error);throw error;}
 finally{ep.host.remove();current=undefined;Reflect.deleteProperty(URL,'createObjectURL');Reflect.deleteProperty(URL,'revokeObjectURL');vi.unstubAllGlobals();vi.unstubAllEnvs();await saveReport();}
});
it.skipIf(!base).each([{persona:'physician',round:1},{persona:'nurse_practitioner',round:1},{persona:'physician_assistant',round:1},
 {persona:'physician',round:2},{persona:'nurse_practitioner',round:2},{persona:'physician_assistant',round:2}])('$persona round $round explicitly reviews one received PDF through signed APIs and encrypted restart recovery',async({persona,round})=>{
 const ep=current!,c=controls(ep),started=performance.now(),trial:Trial={persona,round,passed:false,case_id:'',steps:[],wire:[],elapsed_ms:0};ep.trial=trial;trials.push(trial);
 const step=(name:string)=>{ep.lifecycle.check();trial.steps.push({name,elapsed_ms:Math.round(performance.now()-started)});};
 return ep.lifecycle.run(async()=>{try{
  const seeded=await ep.lifecycle.fetch(realFetch,`${base}/lab/case?persona=${persona}&round=${round}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(seeded.status,await seeded.clone().text()).toBe(200);ep.packet=await seeded.json() as Packet;trial.case_id=ep.packet.case_id;
  ep.identity={mode:'clerk_jwt',getToken:async()=>ep.packet!.token};await mount(ep);await c.wait(()=>expect(c.button('Check received-fax access').disabled).toBe(false));
  expect(trial.wire.some(w=>w.path.startsWith('/efax-inbound'))).toBe(false);step('mounted_signed_account_with_encrypted_storage_no_provider_read');
  await c.click('Check received-fax access');await c.wait(()=>expect(ep.host.textContent).toContain('An inbound eFax account is configured'));await c.idle();
  await c.choose('Account',ep.packet.installation_id);expect(c.button('Save received-fax access').disabled).toBe(true);
  await c.tick('Also permit separately approved image acquisition');await c.tick('I checked this account');await c.click('Save received-fax access');
  await c.wait(()=>expect(trial.wire.find(w=>w.path==='/efax-inbound/grant')?.receipt?.state).toBe('granted'));await c.idle();
  const grant=trial.wire.find(w=>w.path==='/efax-inbound/grant')!;expect(grant.body).toMatchObject({reviewed_account:true,reviewed_mark_read:true,image_enabled:true});
  await c.choose('Reviewed account',grant.receipt!.grant_id!);await c.click('Check received faxes · last 7 days');await c.wait(async()=>expect((await c.saved()).observation?.state).toBe('observed'));await c.idle();
  const observed=await c.saved();expect(observed.observation!.snapshot).toMatchObject({scope:'one_received_metadata_page',inbox_complete:false,continuation:'unknown',request:{limit:25,offset:0}});
  expect(trial.wire.find(w=>w.path==='/efax-inbound/observe')!.body).toMatchObject({limit:25,offset:0});expect((await c.inspect()).case_provider_calls).toBe(1);
  const fax=observed.observation!.snapshot!.items.find(item=>item.fax_id===ep.packet!.fax_id)!;expect(fax).toBeTruthy();
  const faxButton=[...ep.host.querySelectorAll<HTMLButtonElement>('li button')].find(b=>b.textContent?.includes('12125550102'))!;expect(faxButton).toBeTruthy();await act(async()=>faxButton.click());
  await c.wait(async()=>expect((await c.saved()).selected_fax_id).toBe(ep.packet!.fax_id));await c.idle();step('explicit_bounded_metadata_and_exact_fax_selection');
  await c.click('Prepare exact image acquisition');await c.wait(async()=>expect((await c.saved()).proposal?.state).toBe('pending_approval'));await c.idle();
  expect(c.button('Approve exact image acquisition').disabled).toBe(true);expect([...ep.host.querySelectorAll('button')].some(b=>b.textContent==='Acquire approved PDF once')).toBe(false);
  await c.tick('I checked the exact fax');await c.click('Approve exact image acquisition');await c.wait(async()=>expect((await c.saved()).approval?.state).toBe('approved'));await c.idle();
  const approved=await c.saved();expect(approved.approval!.ticket_id).toBe(approved.proposal!.ticket_id);expect((await c.inspect()).case_provider_calls).toBe(1);step('human_exact_mark_read_approval_saved_before_image_io');
  ep.loseAcquire=round===2;await c.click('Acquire approved PDF once');await c.wait(()=>expect(trial.wire.find(w=>w.path==='/efax-inbound/acquire')?.status).toBe(200));await c.idle();
  const acquire=trial.wire.find(w=>w.path==='/efax-inbound/acquire')!,command={kind:'acquire',request:acquire.body} as EFaxPending;
  expect(acquire.receipt!.public_request_sha256).toBe(await efaxPublicHash({box_id:ep.account!.box_id,owner_id:ep.account!.actor_id},command));
  if(round===2){expect(acquire.lost).toBe(true);expect(ep.host.textContent).toContain('result could not be confirmed');expect((await c.saved()).pending?.request.idempotency_key).toBe(acquire.key);}
  else{await c.wait(async()=>expect((await c.saved()).acquisition?.state).toBe('acquired'));expect((await c.saved()).pending).toBeNull();}
  const before=await c.inspect();expect(before.case_provider_calls).toBe(2);expect(before.image_calls).toBe(1);expect(before.operation).toMatchObject({status:'succeeded',attempt_count:1,decisions:1,document_sha256:ep.packet.pdf_sha256,document_pages:1});
  expect(before.workspace).toEqual(ep.packet.workspace);const sealed=JSON.stringify(await sealedRows(ep));expect(sealed).not.toContain(acquire.key!);expect(sealed).not.toContain(ep.packet.fax_id);expect(sealed).not.toContain('Invented café sender');
  step(round===2?'actual_image_saved_reply_lost_exact_command_retained_encrypted':'actual_pdf_parser_and_private_document_saved');
  await act(async()=>ep.root!.unmount());ep.root=null;ep.journal!.close();ep.journal=null;
  const restart=await ep.lifecycle.fetch(realFetch,`${base}/lab/restart`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:ep.packet.case_id}),cache:'no-store',credentials:'omit',redirect:'error'});expect(restart.status).toBe(200);
  const beforeReopen=trial.wire.filter(w=>w.path.startsWith('/efax-inbound')).length;await mount(ep);await c.wait(()=>expect(c.button('Restore saved received-fax work').disabled).toBe(false));
  expect(trial.wire.filter(w=>w.path.startsWith('/efax-inbound'))).toHaveLength(beforeReopen);await c.click('Restore saved received-fax work');await c.idle();expect(ep.host.textContent).not.toContain('Invented café sender');
  if(round===2){await c.click('Check saved received-fax result');await c.wait(async()=>expect((await c.saved()).pending).toBeNull());await c.idle();
   const replay=trial.wire.find(w=>w.path==='/efax-inbound/resolve'&&w.key===acquire.key)!;expect(replay.body).toEqual({idempotency_key:acquire.key,kind:'image'});expect(replay.receipt?.document?.sha256).toBe(ep.packet.pdf_sha256);}
  await c.click('Check received-fax access');await c.wait(()=>expect(c.button('Load saved PDF for attachment download').disabled).toBe(false));await c.idle();
  const recovered=await c.saved();expect(recovered.pending).toBeNull();expect(recovered.acquire_request?.request.idempotency_key).toBe(acquire.key);expect(recovered.acquisition?.document).toEqual({sha256:ep.packet.pdf_sha256,byte_length:ep.packet.pdf_byte_length,pages:1});
  expect(trial.wire.filter(w=>w.path==='/efax-inbound/acquire')).toHaveLength(1);expect((await c.inspect()).case_provider_calls).toBe(2);step('explicit_restore_and_database_only_exact_recovery_after_managed_restart');
  await c.click('Load saved PDF for attachment download');await c.wait(()=>expect(ep.host.querySelector<HTMLAnchorElement>('a[download="received-fax.pdf"]')).toBeTruthy());await c.idle();
  const attachment=ep.host.querySelector<HTMLAnchorElement>('a[download="received-fax.pdf"]')!;expect(attachment.textContent).toBe('Save received PDF attachment');
  const blob=ep.blobs.get(attachment.getAttribute('href')!)!;expect(blob).toBeTruthy();const bytes=new Uint8Array(await blob.arrayBuffer());expect(bytes.length).toBe(ep.packet.pdf_byte_length);expect(await vendorSha256(bytes)).toBe(ep.packet.pdf_sha256);
  expect(trial.wire.find(w=>w.path.includes('/documents/'))?.status).toBe(200);expect((await c.inspect()).case_provider_calls).toBe(2);expect(ep.denials).toEqual([]);
  expect(trial.wire.every(w=>w.status===200)).toBe(true);expect(trial.wire.filter(w=>w.lost)).toHaveLength(round===2?1:0);expect(ep.host.textContent).toContain('does not establish patient identity or clinical review');
  step('private_attachment_response_exact_pdf_hash_verified_no_second_image_get');trial.backend=await c.inspect();trial.passed=true;
 }catch(error){trial.failure=String(error)+'\nDOM: '+ep.host.textContent;terminalFailure=trial.failure;try{trial.backend=await c.inspect();}catch{/* Preserve the original assertion if the bounded diagnostic is unavailable. */}throw error;}
 finally{trial.elapsed_ms=Math.round(performance.now()-started);}},55000);
},60000);
async function saveReport(){if(!base||!environment?.COSMAS_EFAX_INBOUND_LAB_REPORT)return;const mod='node:fs/promises';const fs=await import(/* @vite-ignore */mod) as {writeFile:(p:string,v:string)=>Promise<void>};
 await fs.writeFile(environment.COSMAS_EFAX_INBOUND_LAB_REPORT,JSON.stringify({schema:'cosmabot.efax-inbound-signed-ui.v1',synthetic_only:true,
 boundary:'Mounted EFaxInboundMount/Panel, actual signed account identity and eFax API clients/parsers, real AES-GCM DraftJournal with fake IndexedDB, registered FastAPI routes/lifespan/managed profile, PostgreSQL approval/one-shot ledger, actual vendor adapter and bounded PDF subprocess. Only invented vendor HTTP/credentials and browser Blob URL affordance are fixture boundaries. No live account, native device, OS file-save, patient assignment, Chief handoff or clinical sign-off is qualified.',
 total:trials.length,completed:trials.filter(t=>t.passed).length,episodes:trials},null,2)+'\n');}
afterAll(saveReport);
