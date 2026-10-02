// @vitest-environment-options {"url":"https://workspace.example.invalid/"}
import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterAll,afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{
  for(const [key,value] of Object.entries({
    VITE_COSMAS_ENV:'early_adopter_beta',VITE_WORKSPACE_ENABLED:'true',
    VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',VITE_WORKSPACE_SCHEDULING_ENABLED:'true',
    VITE_WORKSPACE_APPOINTMENTS_ENABLED:'true',VITE_WORKSPACE_HOSTED_ENABLED:'true',
    VITE_WORKSPACE_DATA_MODE:'synthetic',VITE_WORKSPACE_HOSTED_CLIENT:'web',
    VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://api.example.invalid',
    VITE_WORKSPACE_WEB_ORIGIN:'https://workspace.example.invalid',VITE_API_BASE:'https://api.example.invalid',
    VITE_WORKSPACE_DESKTOP_AUTH_ENABLED:'false',VITE_WORKSPACE_NATIVE_AUTH_ENABLED:'false',
    VITE_DESKTOP_SYNTHETIC_ENABLED:'false',VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED:'false',
  }))vi.stubEnv(key,value);
});
import {AppointmentPanel} from './AppointmentPanel';
import {appointmentApi} from './appointment-api';
import {workspaceApi,type AuthenticatedWorkspaceIdentity,type CaptureBotSelection,type Workspace} from './workspace-api';
import {practiceAccessApi} from './practice-access-api';
import {admitWorkspaceProtocol,workspaceProtocolGeneration} from './workspace-protocol';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal,editorAddress} from './draft-journal';
import {openDraftStore} from './draft-store';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {hasUnsavedWork} from './unsaved-work';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const utilModule='node:util';
const {transferableAbortController}=await import(/* @vite-ignore */utilModule) as {transferableAbortController:()=>AbortController};
const environment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const configured=environment?.COSMAS_HOSTED_APPOINTMENT_LAB_URL;
const localOrigin=(value:string)=>{const u=new URL(value);if(u.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(u.hostname)||u.username||u.password||u.search||u.hash||u.pathname!=='/')throw new Error('The synthetic product server must be a loopback origin.');return u.origin;};
const base=configured?localOrigin(configured):null;
type Packet={workspace:Workspace;bot:CaptureBotSelection;token:string;scope:string;slot:{starts_at:string;ends_at:string};dob:null;receiver_calls:number};
type Wire={method:string;path:string;status:number|null;key?:string;choice?:string;revision_id?:string;payload_hash?:string;error?:string};
type Episode={persona:string;round:number|string;passed:boolean;elapsed_ms:number;steps:string[];wire:Wire[];ticket_id?:string;payload_hash?:string;receiver_calls?:number;failure?:string};
type Counters={workspace:Workspace;receiver_calls:number;receiver_writes:number;appointment_receipts:number;operations:{ticket_id:string;dispatch_started:boolean;attempt_count:number}[]};
const episodes:Episode[]=[],recoveries:Episode[]=[],realFetch=globalThis.fetch.bind(globalThis),transports=new Set<Promise<Response>>(),abortBridges:(()=>void)[]=[];
let root:Root|undefined,host:HTMLDivElement,identity:AuthenticatedWorkspaceIdentity,access:EditorRecoveryAccess,journal:DraftJournal|undefined,idb:IDBFactory,packet:Packet,active:Episode|undefined,loseNextPrepare=false,lost=false;
const namespace=async(value:string)=>[...new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(n=>n.toString(16).padStart(2,'0')).join('');
function button(name:string){const value=[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===name);expect(value,name).toBeTruthy();return value!;}
async function wait(check:()=>void){for(let n=0;n<1500;n++){let done=false;await act(async()=>{await new Promise(resolve=>setTimeout(resolve,10));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(name:string){await wait(()=>expect(button(name).disabled,name).toBe(false));await act(async()=>button(name).click());}
const noteIdentity=(w:Workspace)=>JSON.stringify({note:w.note,entries:w.entries,revision:w.revision});
async function inspect():Promise<Counters>{const response=await realFetch(base+'/lab/inspect',{cache:'no-store',credentials:'omit',redirect:'error'});expect(response.status).toBe(200);return response.json();}
async function assertPreserved(before:string){const counters=await inspect();expect(noteIdentity(counters.workspace)).toBe(before);expect(counters.receiver_writes).toBe(0);expect(counters.appointment_receipts).toBe(0);expect(counters.operations.every(o=>!o.dispatch_started&&o.attempt_count===0)).toBe(true);return counters;}
async function render(){
  root=createRoot(host);await act(async()=>root!.render(<EditorRecoveryContext.Provider value={access}>
    <AppointmentPanel workspaceId={packet.workspace.id} identity={identity} bot={packet.bot} enabled locked={false}
      selectedSlot={packet.slot}/>
  </EditorRecoveryContext.Provider>));
  await wait(()=>{
    const restore=[...host.querySelectorAll<HTMLButtonElement>('button')].find(value=>value.textContent==='Restore appointment draft');
    expect(restore?!restore.disabled:!button('Refresh saved proposals').disabled).toBe(true);
  });
}
async function reopen(){await act(async()=>root!.unmount());root=undefined;journal!.close();journal=new DraftJournal(await openDraftStore({scope:await namespace(packet.scope),native:false,indexedDB:idb,crypto:webcrypto}));access={...access,journal};await render();}
async function openCase(persona:string,round:string){
  const response=await realFetch(base+'/lab/case?persona='+persona+'&round='+round,{cache:'no-store',credentials:'omit',redirect:'error'});expect(response.status).toBe(200);packet=await response.json();
  expect(packet.dob).toBeNull();identity={mode:'clerk_jwt',getToken:async()=>packet.token};
  const generation=workspaceProtocolGeneration(identity);await practiceAccessApi.compatibility(identity);admitWorkspaceProtocol(identity,generation);
  idb=new IDBFactory();journal=new DraftJournal(await openDraftStore({scope:await namespace(packet.scope),native:false,indexedDB:idb,crypto:webcrypto}));
  access={journal,workspaceId:packet.workspace.id,authorize:()=>workspaceApi.read(identity,packet.workspace.id),denied:error=>{throw error;}};
  await render();expect(host.textContent).toContain('Booking or changing a visit is not available yet');
  expect(host.querySelector('[name="dob"],[aria-label*="birth"],[aria-label*="DOB"]')).toBeNull();
  return packet;
}
function noExecutionControls(){expect([...host.querySelectorAll('button')].some(b=>['Send approved appointment change','Check saved result','Retry the same appointment change'].includes(b.textContent??''))).toBe(false);expect(active!.wire.some(w=>w.path.endsWith('/execute'))).toBe(false);}
async function deliberatePrepare(){
  const checkbox=host.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  expect(checkbox.checked).toBe(false);expect(button('Prepare appointment proposal').disabled).toBe(true);
  expect(active!.wire.filter(w=>w.method==='POST')).toHaveLength(0);
  await act(async()=>checkbox.click());await click('Prepare appointment proposal');
}
async function finishReviewedLoop(episode:Episode,before:string){
  await wait(()=>expect(host.textContent).toContain('Awaiting your review.'));
  const prepared=episode.wire.find(w=>w.method==='POST'&&w.path.endsWith('/appointments'))!;
  const catalog=await appointmentApi.catalog(packet.workspace.id,identity),saved=catalog.items.find(value=>value.state==='pending_approval');
  expect(saved).toBeTruthy();const item=await appointmentApi.read(packet.workspace.id,identity,saved!.ticket_id);
  expect(item.state).toBe('pending_approval');expect(item.appointment_saved).toBe(false);expect(item.dispatch_started).toBe(false);
  expect(Date.parse(item.intent.slot!.starts_at)).toBe(Date.parse(packet.slot.starts_at));
  episode.ticket_id=item.ticket_id;episode.payload_hash=item.payload_hash;episode.steps.push('exact_saved_proposal_reviewed');
  expect(episode.wire.filter(w=>w.choice==='approve')).toHaveLength(0);noExecutionControls();
  await click('Approve this appointment change');await wait(()=>expect(host.textContent).toContain('Proposal approved. Scheduling has not booked or changed the visit.'));
  const choice=episode.wire.find(w=>w.choice==='approve')!;
  expect(choice.revision_id).toBe(item.revision_id);expect(choice.payload_hash).toBe(item.payload_hash);episode.steps.push('exact_hash_and_revision_human_approval');
  noExecutionControls();await assertPreserved(before);
  await reopen();await wait(()=>expect(host.querySelector('article')).toBeNull());
  const selector=[...host.querySelectorAll<HTMLButtonElement>('li button')].find(b=>b.textContent?.endsWith('Approved'));
  expect(selector).toBeTruthy();await act(async()=>selector!.click());await wait(()=>expect(host.textContent).toContain('Proposal approved. Scheduling has not booked or changed the visit.'));
  expect(host.querySelector('article')!.textContent).toContain('Requested appointment:');episode.steps.push('stored_approved_proposal_reopened');
  noExecutionControls();await click('Withdraw proposal');await wait(()=>expect(host.querySelector('article')?.textContent).toContain('Withdrawn.'));
  const withdraw=episode.wire.find(w=>w.choice==='reject')!;expect(withdraw.revision_id).toBe(item.revision_id);expect(withdraw.payload_hash).toBe(item.payload_hash);
  const counters=await assertPreserved(before);expect(counters.receiver_calls).toBe(packet.receiver_calls+1);
  expect(episode.wire.filter(w=>w.method==='POST'&&w.path.endsWith('/appointments'))[0].key).toBe(prepared.key);
  await wait(()=>expect(hasUnsavedWork()).toBe(false));expect(await journal!.load(editorAddress(packet.workspace.id,'appointments'))).toBeNull();
  episode.receiver_calls=counters.receiver_calls;episode.steps.push('withdrawn_with_note_unchanged_and_zero_receiver_writes');
}
beforeEach(()=>{
 if(!base)return;vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
 vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 host=document.createElement('div');document.body.append(host);loseNextPrepare=false;lost=false;
 vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
   const u=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);
   if(u.origin!=='https://api.example.invalid')throw new Error('Only the pinned invented hosted API origin is allowed.');
   let nativeInit=init;if(init?.signal){const source=init.signal,native=transferableAbortController(),abort=()=>native.abort(source.reason);source.addEventListener('abort',abort,{once:true});if(source.aborted)abort();abortBridges.push(()=>source.removeEventListener('abort',abort));nativeInit={...init,signal:native.signal};}
   const method=init?.method??'GET';let value:Record<string,unknown>={};if(method==='POST')value=JSON.parse(String(init?.body));
   const owner=active,record:Wire={method,path:u.pathname,status:null,...typeof value.idempotency_key==='string'?{key:value.idempotency_key}:{},...typeof value.choice==='string'?{choice:value.choice}:{},...typeof value.revision_id==='string'?{revision_id:value.revision_id}:{},...typeof value.payload_hash==='string'?{payload_hash:value.payload_hash}:{}};
   owner?.wire.push(record);const transport=realFetch(base+u.pathname+u.search,nativeInit);transports.add(transport);
   try{const response=await transport;record.status=response.status;
     // The loopback bridge is a test transport for the exact logical hosted URL.
     // Preserve that URL while keeping the actual backend body/status/headers.
     Object.defineProperty(response,'url',{value:u.href});
     if(loseNextPrepare&&!lost&&method==='POST'&&u.pathname.endsWith('/appointments')&&response.status===200){await response.arrayBuffer();lost=true;throw new TypeError('Invented lost save response after commit');}
     return response;
   }catch(error){record.error=error instanceof Error?error.message:String(error);throw error;}finally{transports.delete(transport);}
 });
});
afterEach(async()=>{
 if(root){await act(async()=>root!.unmount());root=undefined;}journal?.close();journal=undefined;
 if(transports.size){let timer:ReturnType<typeof setTimeout>|undefined;try{await Promise.race([Promise.allSettled([...transports]),new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new Error('Synthetic transport did not settle in teardown')),15000);})]);}finally{if(timer)clearTimeout(timer);}}
 for(const dispose of abortBridges.splice(0))dispose();host?.remove();active=undefined;vi.unstubAllGlobals();
});
it.skipIf(!base).each([{persona:'physician',round:1},{persona:'nurse_practitioner',round:1},{persona:'physician_assistant',round:1},
 {persona:'physician',round:2},{persona:'nurse_practitioner',round:2},{persona:'physician_assistant',round:2}])('$persona round $round deliberately shares, reviews, reopens and withdraws a hosted proposal',async({persona,round})=>{
 const start=performance.now(),episode:Episode={persona,round,passed:false,elapsed_ms:0,steps:[],wire:[]};episodes.push(episode);active=episode;
 try{await openCase(persona,String(round));const before=noteIdentity(packet.workspace);episode.steps.push('DOB_optional_private_recovery_ready_no_write');
   await deliberatePrepare();await finishReviewedLoop(episode,before);expect(episode.wire.every(w=>w.status===200&&!w.error)).toBe(true);episode.passed=true;
 }catch(error){episode.failure=(error instanceof Error?error.message:String(error))+'; '+(host.textContent??'');throw error;}finally{episode.elapsed_ms=Math.round((performance.now()-start)*100)/100;}
},45000);
it.skipIf(!base)('recovers a lost committed proposal response with the identical durable key and no new receiver read',async()=>{
 const start=performance.now(),episode:Episode={persona:'physician',round:'lost_save',passed:false,elapsed_ms:0,steps:[],wire:[]};recoveries.push(episode);active=episode;
 try{await openCase('physician','lost_save');const before=noteIdentity(packet.workspace);loseNextPrepare=true;
   await deliberatePrepare();await wait(()=>expect(host.textContent).toContain('The request could not be confirmed.'));
   expect(lost).toBe(true);const original=await journal!.load(editorAddress(packet.workspace.id,'appointments'));expect(original?.pending).toBeTruthy();
   const beforeRecovery=await assertPreserved(before);expect(beforeRecovery.receiver_calls).toBe(packet.receiver_calls+1);
   await reopen();await wait(()=>expect(button('Restore appointment draft').disabled).toBe(false));await click('Restore appointment draft');
   await wait(()=>expect(host.textContent).toContain('The earlier request is retained exactly.'));
   await click('Retry the same save');await wait(()=>expect(host.textContent).toContain('Awaiting your review.'));
   const prepares=episode.wire.filter(w=>w.method==='POST'&&w.path.endsWith('/appointments'));
   expect(prepares).toHaveLength(2);expect(prepares[0].key).toBe(original!.pending);expect(prepares[1].key).toBe(prepares[0].key);
   expect((await inspect()).receiver_calls).toBe(beforeRecovery.receiver_calls);episode.steps.push('lost_reply_recovered_exact_key_without_receiver_reread');
   await finishReviewedLoop(episode,before);episode.passed=true;
 }catch(error){episode.failure=(error instanceof Error?error.message:String(error))+'; '+(host.textContent??'');throw error;}finally{episode.elapsed_ms=Math.round((performance.now()-start)*100)/100;}
},45000);
afterAll(async()=>{
 const output=environment?.COSMAS_HOSTED_APPOINTMENT_LAB_REPORT;if(!output||!base)return;
 const fsModule='node:fs/promises';const fs=await import(/* @vite-ignore */fsModule) as {writeFile:(p:string,s:string)=>Promise<void>};
 await fs.writeFile(output,JSON.stringify({schema:'cosmabot.hosted-appointment-product-server-ui.v1',synthetic_only:true,
 boundary:'Mounted actual AppointmentPanel, actual hosted auth/compatibility/API parsing, encrypted browser DraftJournal with synthetic IndexedDB, signed FastAPI, PostgreSQL, bounded GET-only scheduling receiver. Transparent exact invented HTTPS-origin to loopback transport. No live provider, physical mobile/browser, model call or booking.',
 episodes,recoveries},null,2)+'\n');
});
