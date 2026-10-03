import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterAll,afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const [key,value] of Object.entries({VITE_COSMAS_ENV:'synth_os',VITE_WORKSPACE_ENABLED:'true',
 VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',VITE_EFAX_INBOUND_ENABLED:'true',VITE_EFAX_INBOUND_SOURCE_ENABLED:'true',
 VITE_WORKSPACE_HOSTED_ENABLED:'false',VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED:'false',VITE_DESKTOP_SYNTHETIC_ENABLED:'false'}))vi.stubEnv(key,value);});
import {EFaxSourceReviewMount} from './EFaxSourceReviewMount';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {accountIdentityApi,type AccountIdentity} from './account-identity-api';
import {DraftJournal,editorAddress} from './draft-journal';
import {openDraftStore,privateDraftScope} from './draft-store';
import {workspaceApi,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import {validateEFaxSourceRecovery,type EFaxSourceRecovery} from './efax-inbound-source-recovery';
import {efaxSourceRequestHash,verifyEFaxSourceWorkspace,type EFaxSourceOffer,type EFaxSourceVisit,type EFaxSourceReviewRequest,type EFaxSourceReceipt} from './efax-inbound-source-api';
import {efaxInboundApi,type EFaxPending} from './efax-inbound-api';
import {ScribeLabEpisode} from './scribe-lab-episode';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const util='node:util';
const {transferableAbortController}=await import(/* @vite-ignore */util) as {transferableAbortController:()=>AbortController};
const environment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const configured=environment?.COSMAS_EFAX_SOURCE_LAB_URL;
function local(value:string){const u=new URL(value);if(u.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(u.hostname)||u.pathname!=='/'||u.search||u.hash||u.username||u.password)throw new Error('Only the owned loopback synthetic server is permitted.');return u.origin;}
const base=configured?local(configured):null,realFetch=globalThis.fetch.bind(globalThis);
type Packet={case_id:string;token:string;workspace:Workspace;account:AccountIdentity;passage:string;visit:EFaxSourceVisit;offered:EFaxSourceOffer;acquisition:Extract<EFaxPending,{kind:'acquire'}>};
type Wire={method:string;path:string;status:number|null;key?:string;body?:Record<string,unknown>;receipt?:EFaxSourceReceipt;lost?:boolean;error?:string;response_detail?:string};
type Counters={case_id:string;workspace:Workspace;case_provider_calls:number;image_calls:number;review_count:number;restarts:number;
 source:null|{review_id:string;entry_id:string;request_sha256:string;document_sha256:string;content_sha256:string;source_sha256:string;patient_link_id:string|null};
 operation:null|{id:string;status:string;attempt_count:number;invocation:boolean;outcome:string;document_sha256:string;pages:number}};
type Trial={persona:string;round:number;passed:boolean;case_id:string;steps:Array<{name:string;elapsed_ms:number}>;wire:Wire[];elapsed_ms:number;failure?:string;backend?:Counters};
type Episode={lifecycle:ScribeLabEpisode;host:HTMLDivElement;root:Root|null;idb:IDBFactory;identity:AuthenticatedWorkspaceIdentity;account:AccountIdentity|null;
 journal:DraftJournal|null;namespace:string;access:EditorRecoveryAccess|null;packet:Packet|null;trial:Trial|null;loseSave:boolean;denials:unknown[];
 savedCallbacks:Array<{receipt:EFaxSourceReceipt;workspace:Workspace}>;chiefCallbacks:Array<Parameters<NonNullable<import('./EFaxSourceReviewPanel').EFaxSourceReviewPanelProps['onAskChief']>>[0]>};
const trials:Trial[]=[];let current:Episode|undefined,terminalFailure:string|undefined;
const scope=(ep:Episode)=>({box_id:ep.account!.box_id,owner_id:ep.account!.actor_id,workspace_id:ep.packet!.visit.id});
const address=(ep:Episode)=>editorAddress(ep.packet!.visit.id,`efax-source-review:${ep.packet!.offered.operation_id}`);
function controls(ep:Episode){
 const check=()=>ep.lifecycle.check();
 const button=(label:string)=>{check();const b=[...ep.host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===label);expect(b,label).toBeTruthy();return b!;};
 async function wait(assertion:()=>void|Promise<void>){const deadline=performance.now()+10000;while(performance.now()<deadline){check();let passed=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));check();try{await assertion();passed=true;}catch{}});if(passed)return;}check();await assertion();}
 async function idle(){await wait(()=>expect(ep.host.textContent).not.toContain('Waiting for the current fax passage operation'));}
 async function click(label:string){await wait(()=>expect(button(label).disabled,label).toBe(false));await act(async()=>button(label).click());await idle();}
 async function enter(){await wait(()=>expect(ep.host.querySelector('textarea')).toBeTruthy());await act(async()=>{
  const t=ep.host.querySelector<HTMLTextAreaElement>('textarea')!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(t,ep.packet!.passage);t.dispatchEvent(new Event('input',{bubbles:true}));
  const p=ep.host.querySelector<HTMLInputElement>('input[aria-label="Pages used"]')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(p,'1');p.dispatchEvent(new Event('input',{bubbles:true}));
 });}
 async function ack(){expect(ep.host.querySelectorAll('input[type=checkbox]')).toHaveLength(4);await act(async()=>ep.host.querySelectorAll<HTMLInputElement>('input[type=checkbox]').forEach(c=>{expect(c.disabled).toBe(false);c.click();}));}
 async function saved(){const entry=await ep.journal!.load(address(ep));expect(entry?.kind).toBe('editor');if(!entry||entry.kind!=='editor')throw new Error('Encrypted passage record is missing');expect(entry.editor).toBe(`efax-source-review:${ep.packet!.offered.operation_id}`);expect(entry.pending).toBeNull();return validateEFaxSourceRecovery(entry.data,scope(ep),ep.packet!.offered);}
 async function inspect(){const r=await ep.lifecycle.fetch(realFetch,`${base}/lab/inspect?case_id=${ep.packet!.case_id}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(r.status,await r.clone().text()).toBe(200);return r.json() as Promise<Counters>;}
 return {button,wait,idle,click,enter,ack,saved,inspect};
}
async function openJournal(ep:Episode){
 ep.account=await accountIdentityApi.read(ep.identity);ep.lifecycle.check();expect(ep.account).toEqual(ep.packet!.account);
 if(!ep.namespace)ep.namespace=await privateDraftScope(ep.account.recovery_scope,base!,webcrypto);
 ep.journal=new DraftJournal(await openDraftStore({scope:ep.namespace,native:false,indexedDB:ep.idb,crypto:webcrypto}));
 ep.access={journal:ep.journal,workspaceId:ep.packet!.visit.id,recoveryScope:ep.account.recovery_scope,authorize:async()=>{
  ep.lifecycle.check();const workspace=await workspaceApi.read(ep.identity,ep.packet!.visit.id);ep.lifecycle.check();expect(workspace.id).toBe(ep.packet!.visit.id);return workspace;
 },denied:e=>ep.denials.push(e)};
}
async function mount(ep:Episode){await openJournal(ep);ep.root=createRoot(ep.host);await act(async()=>ep.root!.render(
 <EditorRecoveryContext.Provider value={ep.access}><EFaxSourceReviewMount identity={ep.identity} offered={ep.packet!.offered} visit={ep.packet!.visit}
 onAuthenticationLost={e=>ep.denials.push(e)} onSaved={(receipt,workspace)=>ep.savedCallbacks.push({receipt,workspace})}
 onAskChief={source=>ep.chiefCallbacks.push(source)} onRefreshDocument={async()=>{
  const result=await efaxInboundApi.resolve(ep.identity,{box_id:ep.account!.box_id,owner_id:ep.account!.actor_id},ep.packet!.acquisition);ep.lifecycle.check();
  if(result.state!=='acquired'||!('document'in result)||!result.document||result.source_withheld||!result.content_available)return null;
  return result.operation_id===ep.packet!.offered.operation_id&&result.document.sha256===ep.packet!.offered.document_sha256&&result.document.pages===ep.packet!.offered.pages?ep.packet!.offered:null;
 }}/></EditorRecoveryContext.Provider>
));}
async function independentSaved(ep:Episode):Promise<EFaxSourceRecovery>{const reader=new DraftJournal(await openDraftStore({scope:ep.namespace,native:false,indexedDB:ep.idb,crypto:webcrypto}));try{
 const entry=await reader.load(address(ep));if(!entry||entry.kind!=='editor')throw new Error('Dispatch has no independently reopened encrypted custody');expect(entry.pending).toBeNull();return validateEFaxSourceRecovery(entry.data,scope(ep),ep.packet!.offered);
}finally{reader.close();}}
async function sealedRows(ep:Episode){const db=await new Promise<IDBDatabase>((resolve,reject)=>{const r=ep.idb.open('cosmas-private-drafts:v1:'+ep.namespace);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});try{return await new Promise<unknown[]>((resolve,reject)=>{const r=db.transaction('sealed-drafts').objectStore('sealed-drafts').getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}finally{db.close();}}
beforeEach(()=>{
 if(!base)return;if(terminalFailure)throw new Error('Prior signed passage episode failed; no new case admitted: '+terminalFailure);
 const native=transferableAbortController();vi.stubGlobal('AbortController',native.constructor);vi.stubGlobal('AbortSignal',native.signal.constructor);
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE',base);
 vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 const host=document.createElement('div');document.body.append(host);const ep:Episode={lifecycle:new ScribeLabEpisode(),host,root:null,idb:new IDBFactory(),identity:{mode:'clerk_jwt',getToken:async()=>{throw new Error('Signed case has not been admitted');}},
  account:null,journal:null,namespace:'',access:null,packet:null,trial:null,loseSave:false,denials:[],savedCallbacks:[],chiefCallbacks:[]};current=ep;
 vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
  ep.lifecycle.check();const u=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);
  const allowed=['/provider-team/identity','/workspaces/'+ep.packet?.visit.id,'/workspaces/'+ep.packet?.visit.id+'/efax-inbound-source','/workspaces/'+ep.packet?.visit.id+'/efax-inbound-source/resolve','/efax-inbound/resolve'];
  if(u.origin!==base||!allowed.includes(u.pathname)||u.search)throw new Error('Only exact signed synthetic passage routes are permitted.');
  const body=init?.body?JSON.parse(String(init.body)) as Record<string,unknown>:undefined,wire:Wire={method:init?.method??'GET',path:u.pathname,status:null,...body?{body}: {},...typeof body?.idempotency_key==='string'?{key:body.idempotency_key}:{}};
  ep.trial?.wire.push(wire);
  try{
   const headers=new Headers(init?.headers);expect(headers.get('Authorization')).toBe('Bearer '+ep.packet!.token);expect(headers.get('X-Cosmas-Draft-Recovery')).toBe('2');
   if(u.pathname==='/provider-team/identity'){expect(headers.get('X-Cosmas-Team-Contract')).toBe('2');expect(headers.has('X-Cosmas-EFax-Inbound')).toBe(false);}
   else if(u.pathname==='/workspaces/'+ep.packet!.visit.id)expect(headers.get('X-Cosmas-Model-Contract')).toBe('1');
   else expect(headers.get('X-Cosmas-EFax-Inbound')).toBe('1');
   if(body&&u.pathname==='/workspaces/'+ep.packet!.visit.id+'/efax-inbound-source'){
    const saved=await independentSaved(ep);expect(saved.pending!.request).toEqual(body);expect(saved.pending!.request_sha256).toBe(await efaxSourceRequestHash(scope(ep),body as EFaxSourceReviewRequest));
   }
   const response=await ep.lifecycle.fetch(realFetch,input,init);wire.status=response.status;
   if(response.status!==200){const error=await response.clone().json() as {detail?:unknown;error?:{code?:unknown}};wire.response_detail=String(error.detail??error.error?.code??'unrecognized error').slice(0,200);}
   if(u.pathname.includes('/efax-inbound-source')&&response.status===200)wire.receipt=await response.clone().json() as EFaxSourceReceipt;
   if(ep.loseSave&&u.pathname==='/workspaces/'+ep.packet!.visit.id+'/efax-inbound-source'&&response.status===200){ep.loseSave=false;await response.arrayBuffer();wire.lost=true;throw new TypeError('Invented lost source-save reply after actual server commit');}
   return response;
  }catch(error){wire.error=error instanceof Error?error.message:String(error);throw error;}
 });
});
afterEach(async()=>{
 if(!base||!current)return;const ep=current;ep.lifecycle.close();
 try{try{await ep.lifecycle.drain(10000);}finally{if(ep.root){await act(async()=>ep.root!.unmount());ep.root=null;}ep.journal?.close();ep.journal=null;}}
 catch(error){terminalFailure=String(error);throw error;}
 finally{ep.host.remove();current=undefined;vi.unstubAllGlobals();vi.unstubAllEnvs();await saveReport();}
});
it.skipIf(!base).each([{persona:'physician',round:1},{persona:'nurse_practitioner',round:1},{persona:'physician_assistant',round:1},
 {persona:'physician',round:2},{persona:'nurse_practitioner',round:2},{persona:'physician_assistant',round:2}])('$persona round $round manually reviews an acquired fax passage and recovers exact signed source after restart',async({persona,round})=>{
 const ep=current!,c=controls(ep),started=performance.now(),trial:Trial={persona,round,passed:false,case_id:'',steps:[],wire:[],elapsed_ms:0};ep.trial=trial;trials.push(trial);
 const step=(name:string)=>{ep.lifecycle.check();trial.steps.push({name,elapsed_ms:Math.round(performance.now()-started)});};
 return ep.lifecycle.run(async()=>{try{
  const seeded=await ep.lifecycle.fetch(realFetch,`${base}/lab/case?persona=${persona}&round=${round}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(seeded.status,await seeded.clone().text()).toBe(200);ep.packet=await seeded.json() as Packet;trial.case_id=ep.packet.case_id;
  ep.identity={mode:'clerk_jwt',getToken:async()=>ep.packet!.token};await mount(ep);await c.wait(()=>expect(ep.host.querySelector('textarea')).toBeTruthy());
  expect(trial.wire.some(w=>w.path.includes('/efax-inbound-source')||w.path==='/efax-inbound/resolve')).toBe(false);expect((await c.inspect()).case_provider_calls).toBe(2);expect(ep.host.textContent).toContain('Date of birth is optional');
  step('actual_signed_account_and_visit_mount_no_automatic_source_or_image_read');
  await c.enter();expect(c.button('Save reviewed fax passage for this visit').disabled).toBe(true);await c.click('Save passage draft privately');
  const privateDraft=await independentSaved(ep);expect(privateDraft.passage).toBe(ep.packet.passage);expect(privateDraft.pending).toBeNull();expect(trial.wire.some(w=>w.path.includes('/efax-inbound-source'))).toBe(false);
  await c.ack();ep.loseSave=round===2;await c.click('Save reviewed fax passage for this visit');await c.wait(()=>expect(trial.wire.find(w=>w.path.endsWith('/efax-inbound-source'))?.status).toBe(200));await c.idle();
  const save=trial.wire.find(w=>w.path.endsWith('/efax-inbound-source'))!,request=save.body as EFaxSourceReviewRequest;expect(request.passage).toBe(ep.packet.passage);expect(request.page_numbers).toEqual([1]);expect(save.receipt!.request_sha256).toBe(await efaxSourceRequestHash(scope(ep),request));
  if(round===2){expect(save.lost).toBe(true);expect((await c.saved()).pending!.request).toEqual(request);expect(ep.savedCallbacks).toHaveLength(0);}
  else{await c.wait(async()=>expect((await c.saved()).saved?.state).toBe('saved'));expect(ep.savedCallbacks).toHaveLength(1);}
  const acquired=await c.inspect();expect(acquired.review_count).toBe(1);expect(acquired.case_provider_calls).toBe(2);expect(acquired.image_calls).toBe(1);expect(acquired.workspace.note).toEqual(ep.packet.workspace.note);
  const preserved=acquired.workspace.entries.filter(e=>ep.packet!.workspace.entries.some(old=>old.id===e.id));expect(preserved).toEqual(ep.packet.workspace.entries);const rows=JSON.stringify(await sealedRows(ep));expect(rows).not.toContain(request.passage);expect(rows).not.toContain(request.idempotency_key);expect(rows).not.toContain(request.document_sha256);
  step(round===2?'review_committed_reply_lost_exact_command_encrypted':'manual_passage_saved_as_separate_source_note_preserved');
  await act(async()=>ep.root!.unmount());ep.root=null;ep.journal!.close();ep.journal=null;
  const restart=await ep.lifecycle.fetch(realFetch,`${base}/lab/restart`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:ep.packet.case_id}),cache:'no-store',credentials:'omit',redirect:'error'});expect(restart.status).toBe(200);
  const sourceCalls=trial.wire.filter(w=>w.path.includes('/efax-inbound-source')).length;await mount(ep);await c.wait(()=>expect(c.button('Restore saved fax passage').disabled).toBe(false));expect(trial.wire.filter(w=>w.path.includes('/efax-inbound-source'))).toHaveLength(sourceCalls);
  await c.click('Restore saved fax passage');expect(ep.host.textContent).not.toContain(ep.packet.passage);if(round===2){await c.click('Check saved fax review');await c.wait(async()=>expect((await c.saved()).pending).toBeNull());}
  await c.click('Check saved fax source');await c.wait(()=>expect(ep.host.textContent).toContain('Fax passage saved for this visit'));const saved=await c.saved();expect(saved.saved_request).toEqual(request);expect(saved.saved!.request_sha256).toBe(save.receipt!.request_sha256);
  expect(trial.wire.filter(w=>w.path.endsWith('/efax-inbound-source'))).toHaveLength(1);expect(trial.wire.filter(w=>w.path.endsWith('/efax-inbound-source/resolve')).every(w=>w.body?.idempotency_key===request.idempotency_key)).toBe(true);
  step('explicit_encrypted_restore_original_key_resolution_after_managed_restart');
  expect(ep.chiefCallbacks).toHaveLength(0);await c.click('Prepare a Chief request');expect(ep.chiefCallbacks).toHaveLength(1);const prepared=ep.chiefCallbacks[0];expect(prepared.receipt.request_sha256).toBe(saved.saved!.request_sha256);expect(prepared.entry.content).toBe(request.passage);await verifyEFaxSourceWorkspace(prepared.workspace,prepared.receipt,request);
  expect(trial.wire.every(w=>w.status===200)).toBe(true);expect(trial.wire.filter(w=>w.lost)).toHaveLength(round===2?1:0);expect(ep.denials).toEqual([]);trial.backend=await c.inspect();expect(trial.backend.case_provider_calls).toBe(2);expect(trial.backend.review_count).toBe(1);
  step('verified_current_source_packet_prepares_editable_chief_callback_only');trial.passed=true;
 }catch(error){trial.failure=String(error)+'\nDOM: '+ep.host.textContent;terminalFailure=trial.failure;try{trial.backend=await c.inspect();}catch{/* Keep the original assertion. */}throw error;}
 finally{trial.elapsed_ms=Math.round(performance.now()-started);}},55000);
},60000);
async function saveReport(){if(!base||!environment?.COSMAS_EFAX_SOURCE_LAB_REPORT)return;const mod='node:fs/promises';const fs=await import(/* @vite-ignore */mod) as {writeFile:(p:string,v:string)=>Promise<void>};
 await fs.writeFile(environment.COSMAS_EFAX_SOURCE_LAB_REPORT,JSON.stringify({schema:'cosmabot.efax-source-signed-ui.v1',synthetic_only:true,
 boundary:'Mounted EFaxSourceReviewMount/Panel, actual signed account/workspace/source API clients/parsers, real AES-GCM DraftJournal with fake IndexedDB, registered FastAPI routes/lifespan/managed profile, PostgreSQL source review and F8 one-shot PDF acquisition, actual vendor adapter and bounded PDF subprocess. Only invented vendor HTTP/credentials and browser storage are fixture boundaries. Pre-approved PDF acquisition is fixture setup, manual passage review is actual UI. No live account, native device, PDF viewer usability, actual Chief execution, clinician usability validation or clinical sign-off is qualified.',
 total:trials.length,completed:trials.filter(t=>t.passed).length,episodes:trials},null,2)+'\n');}
afterAll(saveReport);
