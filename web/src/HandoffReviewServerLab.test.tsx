import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterAll,afterEach,beforeEach,expect,it,vi} from 'vitest';
import {HandoffReviewPanel} from './HandoffReviewPanel';
import {workspaceApi,type Workspace,type WorkspaceIdentity} from './workspace-api';
import type {HandoffReviewInput,HandoffRevisionInput,ReviewableHandoff} from './handoff-review-api';
import {hasUnsavedWork} from './unsaved-work';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {createHandoffReviewTestRecovery} from './handoff-review-test-recovery';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const utilModule='node:util';const {transferableAbortController}=await import(/* @vite-ignore */utilModule) as {transferableAbortController:()=>AbortController};
const labEnvironment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const labUrl=labEnvironment?.COSMAS_HANDOFF_LAB_URL;
function localLabUrl(value:string):string {
  const url=new URL(value);
  if(url.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(url.hostname)||url.username||url.password||url.search||url.hash||url.pathname!=='/')throw new Error('The test server must be a loopback origin.');
  return url.origin;
}
const base=labUrl?localLabUrl(labUrl):null;
type Step={name:string;elapsed_ms:number;workspace_revision?:number;attempt_id?:string;result_entry_id?:string;result_sha256?:string};
type Trial={persona:string;round:number;workspace_id:string;boundary:string;steps:Step[];wire:{path:string;status:number|null;error?:string;request:HandoffReviewInput|HandoffRevisionInput}[];
  outcome:string;failure?:{message:string;dom:string;alerts:string[];configuration:Record<string,unknown>}};
const trials:Trial[]=[],readWorkspace=workspaceApi.read,realFetch=globalThis.fetch.bind(globalThis);
let root:Root|undefined,host:HTMLDivElement,current:Workspace,replaceWorkspace:(w:Workspace)=>void,currentIdentity:WorkspaceIdentity;
let activeTrial:Trial|undefined;
let reviewRecovery:EditorRecoveryAccess|undefined;
const abortBridges:(()=>void)[]=[];
const hash=async(text:string)=>[...new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))].map(n=>n.toString(16).padStart(2,'0')).join('');
function Harness({initial,identity}:{initial:Workspace;identity:WorkspaceIdentity}) {
  const [workspace,setWorkspace]=useState(initial),[selected,setSelected]=useState(initial.handoffs!.find(h=>h.status==='completed')!.id);
  current=workspace;replaceWorkspace=setWorkspace;
  return <EditorRecoveryContext.Provider value={reviewRecovery}><HandoffReviewPanel key={`${workspace.id}:${selected}`} workspace={workspace} handoff={workspace.handoffs!.find(h=>h.id===selected)!} identity={identity}
    locked={false} onSaved={setWorkspace} onRevisionPrepared={setSelected}/></EditorRecoveryContext.Provider>;
}
function button(label:string){const found=[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===label);expect(found,label).toBeTruthy();return found!;}
async function wait(check:()=>void){for(let n=0;n<300;n++){let done=false;await act(async()=>{await new Promise(resolve=>setTimeout(resolve,10));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(label:string){await wait(()=>expect(button(label).disabled,label).toBe(false));await act(async()=>button(label).click());}
async function input(value:string){const field=host.querySelector('textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
function bridgeHeaders(identity:WorkspaceIdentity):Headers {
  if('mode' in identity)throw new Error('The bridge must supply an invented local identity, without credentials.');
  return new Headers({'Content-Type':'application/json','X-Box-Id':identity.boxId,'X-Actor-Principal-Id':identity.actorId});
}
beforeEach(()=>{
  if(!base)return;
  vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE',base);
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);
    if(url.origin!==base)throw new Error('Non-loopback request blocked by the synthetic UI lab.');
    const command=init?.method==='POST'&&/\/handoffs\/[^/]+\/(review|revision)$/.test(url.pathname);
    let nativeInit=init;
    if(init?.signal){
      const source=init.signal,native=transferableAbortController(),abort=()=>native.abort(source.reason);
      source.addEventListener('abort',abort,{once:true});if(source.aborted)abort();
      abortBridges.push(()=>source.removeEventListener('abort',abort));nativeInit={...init,signal:native.signal};
    }
    try{const response=await realFetch(input,nativeInit);
      if(command)activeTrial?.wire.push({path:url.pathname,status:response.status,request:JSON.parse(String(init!.body)) as HandoffReviewInput|HandoffRevisionInput});
      return response;
    }catch(error){if(command)activeTrial?.wire.push({path:url.pathname,status:null,error:error instanceof Error?error.message:String(error),
      request:JSON.parse(String(init!.body)) as HandoffReviewInput|HandoffRevisionInput});throw error;}
  });
  host=document.createElement('div');document.body.append(host);
});
afterEach(async()=>{if(root){await act(async()=>root!.unmount());root=undefined;}reviewRecovery?.journal.close();reviewRecovery=undefined;for(const dispose of abortBridges.splice(0))dispose();host?.remove();activeTrial=undefined;vi.unstubAllGlobals();vi.unstubAllEnvs();});

it.skipIf(!base).each([{persona:'physician',round:1},{persona:'nurse_practitioner',round:1},{persona:'physician_assistant',round:1},
  {persona:'physician',round:2},{persona:'nurse_practitioner',round:2},{persona:'physician_assistant',round:2}])('actual product server $persona round $round reviews, revises, runs the specialist and accepts its exact saved draft',async({persona,round})=>{
  const started=performance.now(),trial:Trial={persona,round,workspace_id:'',boundary:'Actual mounted product review UI, bounded HTTP APIs, FastAPI services, PostgreSQL persistence and product model worker. Invented encounters and an injected upstream model response; no clinical sign-off, live connectors, or physical device.',steps:[],wire:[],outcome:'running'};
  trials.push(trial);activeTrial=trial;
  const step=(name:string,handoff?:ReviewableHandoff)=>trial.steps.push({name,elapsed_ms:Math.round((performance.now()-started)*100)/100,
    ...(current?{workspace_revision:current.revision}:{}),...(handoff?{attempt_id:handoff.attempt_id,result_entry_id:handoff.result_entry_id??undefined,result_sha256:handoff.result_sha256??undefined}:{})});
  try {
    const seeded=await realFetch(`${base}/lab/case?persona=${persona}&round=${round}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(seeded.status).toBe(200);
    const packet=await seeded.json() as {identity:WorkspaceIdentity;workspace:Workspace};expect('mode' in packet.identity).toBe(false);currentIdentity=packet.identity;
    const original=packet.workspace.handoffs!.find(h=>h.status==='completed')! as ReviewableHandoff;trial.workspace_id=packet.workspace.id;
    const originalEntry=packet.workspace.entries.find(e=>e.id===original.result_entry_id)!;expect(originalEntry.reply).toBeTruthy();
    reviewRecovery=await createHandoffReviewTestRecovery(packet.workspace.id,()=>readWorkspace(currentIdentity,current.id),webcrypto);
    root=createRoot(host);await act(async()=>root!.render(<Harness initial={packet.workspace} identity={packet.identity}/>));
    await wait(()=>expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toBe(originalEntry.reply!.content));step('opened_saved_draft',original);
    await click('Request changes');const feedback=`${persona}: identify an owner and due date; preserve unknown diagnosis and trial eligibility.`;
    await input(feedback);await click('Save change request');await wait(()=>expect(button('Prepare revised draft').disabled).toBe(false));
    const changed=current.handoffs!.find(h=>h.id===original.id)! as ReviewableHandoff;expect(changed.review).toMatchObject({decision:'changes_requested',feedback,result_sha256:await hash(originalEntry.reply!.content)});
    step('change_request_persisted',changed);expect(trial.wire.at(-1)).toMatchObject({status:200,request:{decision:'changes_requested',feedback}});
    await click('Prepare revised draft');await wait(()=>expect(current.handoffs!.some(h=>(h as ReviewableHandoff).revision_request?.review_id===changed.review!.id)).toBe(true));
    const newTask=current.handoffs!.find(h=>(h as ReviewableHandoff).revision_request?.review_id===changed.review!.id)! as ReviewableHandoff;
    expect(newTask.id).not.toBe(original.id);expect(newTask.revision_request).toMatchObject({parent_handoff_id:original.id,review_id:changed.review!.id,feedback,result_sha256:original.result_sha256});step('revision_assignment_persisted',newTask);
    const worked=await realFetch(`${base}/lab/work`,{method:'POST',headers:bridgeHeaders(currentIdentity),body:JSON.stringify({workspace_id:current.id,handoff_id:newTask.id}),cache:'no-store',credentials:'omit',redirect:'error'});
    expect([200,204]).toContain(worked.status);
    const latest=await readWorkspace(currentIdentity,current.id);await act(async()=>replaceWorkspace(latest));
    const completed=latest.handoffs!.find(h=>h.id===newTask.id)! as ReviewableHandoff;expect(completed.status).toBe('completed');
    const result=latest.entries.find(e=>e.id===completed.result_entry_id)!;expect(result.reply).toBeTruthy();expect(completed.result_sha256).toBe(await hash(result.reply!.content));
    expect(result.reply!.content).toContain('identify an owner and due date');expect(completed.result_sha256).not.toBe(original.result_sha256);
    await wait(()=>expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toBe(result.reply!.content));step('specialist_work_saved',completed);
    expect(host.textContent).not.toContain('Draft accepted');await click('Accept draft for next work');await wait(()=>expect(host.textContent).toContain('Draft accepted'));
    const accepted=current.handoffs!.find(h=>h.id===completed.id)! as ReviewableHandoff;expect(accepted.review).toMatchObject({decision:'accepted',attempt_id:completed.attempt_id,result_entry_id:result.id,result_sha256:await hash(result.reply!.content)});
    expect(trial.wire).toHaveLength(3);expect(trial.wire.every(w=>w.status===200)).toBe(true);expect(hasUnsavedWork()).toBe(false);step('exact_revised_draft_accepted',accepted);
    const reread=await readWorkspace(currentIdentity,current.id);expect((reread.handoffs!.find(h=>h.id===accepted.id) as ReviewableHandoff).review).toMatchObject(accepted.review!);
    step('acceptance_confirmed_by_fresh_read',accepted);trial.outcome='completed';
  }catch(error){trial.outcome='failed';trial.failure={message:error instanceof Error?error.message:String(error),dom:host.textContent??'',
    alerts:[...host.querySelectorAll('[role="alert"]')].map(e=>e.textContent??''),configuration:{api_base:import.meta.env.VITE_API_BASE,
      hosted_requested:import.meta.env.VITE_WORKSPACE_HOSTED_ENABLED,desktop_synthetic:import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED,
      idempotency_uuid_available:typeof crypto.randomUUID==='function',page:window.location.href}};throw error;}
},30000);

afterAll(async()=>{
  const output=labEnvironment?.COSMAS_HANDOFF_LAB_REPORT;if(!output||!base)return;
  const fsModule='node:fs/promises';const fs=await import(/* @vite-ignore */fsModule) as {writeFile:(path:string,body:string)=>Promise<void>};
  await fs.writeFile(output,JSON.stringify({schema:'cosmabot.handoff-review-product-server-ui.v1',synthetic_only:true,server_origin:base,
    episodes:trials.map(trial=>({...trial,passed:trial.outcome==='completed'})),scenarios:trials,total:trials.length,
    completed:trials.filter(t=>t.outcome==='completed').length,failed:trials.filter(t=>t.outcome==='failed').length},null,2)+'\n');
});
