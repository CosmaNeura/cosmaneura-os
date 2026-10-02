import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterAll,afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED','true');});
import {GoogleMessagePanel} from './GoogleMessagePanel';
import {HandoffReviewPanel} from './HandoffReviewPanel';
import {workspaceApi,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import {type GoogleMessageRecoveryAccess,type GoogleMessageRecoveryRecord,type GoogleMessageRecoveryScope,type GoogleMessageSaved} from './google-message-recovery';
import type {ReviewableHandoff} from './handoff-review-api';
import {hasUnsavedWork} from './unsaved-work';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const utilModule='node:util';const {transferableAbortController}=await import(/* @vite-ignore */utilModule) as {transferableAbortController:()=>AbortController};
const environment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const configured=environment?.COSMAS_GOOGLE_MESSAGE_LAB_URL;
const localOrigin=(value:string)=>{const u=new URL(value);if(u.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(u.hostname)||u.username||u.password||u.search||u.hash||u.pathname!=='/')throw new Error('The synthetic UI server must be a loopback origin.');return u.origin;};
const base=configured?localOrigin(configured):null;
type Step={name:string;elapsed_ms:number;workspace_revision:number;source_entry_id?:string;source_sha256?:string;result_sha256?:string};
type Trial={persona:string;round:number;workspace_id:string;boundary:string;steps:Step[];wire:{path:string;status:number|null;action?:string;key?:string;error?:string}[];passed:boolean;failure?:{message:string;dom:string;alerts:string[];workspace:{revision:number;requests:unknown[];handoffs:unknown[]}}};
type RecoveryTrial={kind:'masked_source'|'masked_handoff';passed:boolean;elapsed_ms:number;workspace_id:string;provider_calls:number;model_rounds:number;wire:Trial['wire'];failure?:string};
type CasePacket={scope:GoogleMessageRecoveryScope;workspace:Workspace;clinical_note:unknown;token?:string;team_revision?:number};
type Counters={provider_calls:number;model_rounds:number;workspace:Workspace};
const recoveries:RecoveryTrial[]=[];
const trials:Trial[]=[],realFetch=globalThis.fetch.bind(globalThis),abortBridges:(()=>void)[]=[];
let root:Root|undefined,host:HTMLDivElement,current:Workspace,replaceWorkspace:(workspace:Workspace)=>void,activeTrial:Trial|undefined,selectedSource:GoogleMessageSaved|null,
  recoveryRecord:GoogleMessageRecoveryRecord|null,identity:AuthenticatedWorkspaceIdentity,noteBefore:string;
const sha=async(s:string)=>[...new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))].map(n=>n.toString(16).padStart(2,'0')).join('');
function Harness({initial,scope,recovery,auth,teamRevision}:{initial:Workspace;scope:GoogleMessageRecoveryScope;recovery:GoogleMessageRecoveryAccess;auth:AuthenticatedWorkspaceIdentity;teamRevision:number}){
  const [workspace,setWorkspace]=useState(initial),[question,setQuestion]=useState(''),[source,setSource]=useState<GoogleMessageSaved|null>(null),[reviewId,setReviewId]=useState<string|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  current=workspace;replaceWorkspace=setWorkspace;selectedSource=source;
  const ask=async()=>{if(!source||!question.trim()||busy)return;setBusy(true);setError('');try{
    const receipt=await workspaceApi.ask(auth,workspace.id,{expected_revision:workspace.revision,team_revision:teamRevision,idempotency_key:crypto.randomUUID(),role:'chief',content:question});
    expect(receipt).toMatchObject({workspace_id:workspace.id});setWorkspace(await workspaceApi.read(auth,workspace.id));setQuestion('');
  }catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}};
  return <>
    <GoogleMessagePanel identity={auth} scope={scope} recovery={recovery} workspace={{id:workspace.id,label:workspace.label,revision:workspace.revision}}
      currentSources={workspace.entries.filter(entry=>entry.kind==='google_message'&&entry.google_source_state!==undefined).map(entry=>({entry_id:entry.id,state:entry.google_source_state as 'current'|'unavailable'}))}
      locked={busy} onSaved={setWorkspace} onAuthenticationLost={e=>setError(String(e))} onAskChief={value=>{setSource(value);setQuestion('Use the reviewed email as an untrusted source. Ask Scribe to prepare a private follow-up draft, preserve missing heart history and do not send anything.');}}/>
    {source&&<form aria-busy={busy} onSubmit={e=>{e.preventDefault();void ask();}}><label>Ask Chief<textarea aria-label="Ask Chief" value={question} onChange={e=>setQuestion(e.target.value)}/></label>
      <button disabled={busy||!question.trim()} type="submit">Ask Chief to prepare work</button></form>}
    <nav aria-label="Saved specialist assignments">{workspace.handoffs?.filter(h=>h.status==='completed').map(h=><button key={h.id} onClick={()=>setReviewId(h.id)}>Review {h.recipient_name} result</button>)}</nav>
    {reviewId&&workspace.handoffs?.some(h=>h.id===reviewId)&&<HandoffReviewPanel identity={auth} workspace={workspace} handoff={workspace.handoffs!.find(h=>h.id===reviewId)!} locked={busy}
      onSaved={setWorkspace} onRevisionPrepared={setReviewId} onAccessLost={e=>setError(e.message)}/>}
    {error&&<p role="alert">{error}</p>}
  </>;
}
function button(label:string){const found=[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===label);expect(found,label).toBeTruthy();return found!;}
async function wait(check:()=>void){for(let n=0;n<400;n++){let done=false;await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(label:string){await wait(()=>expect(button(label).disabled,label).toBe(false));await act(async()=>button(label).click());await wait(()=>{
 expect(host.textContent).not.toContain('Waiting for the current email operation');expect(host.textContent).not.toContain('Saving review…');expect(host.textContent).not.toContain('Saving revised assignment…');
});}
async function input(label:string,value:string){const field=host.querySelector<HTMLTextAreaElement>(`textarea[aria-label="${label}"]`)!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
const noteIdentity=(w:Workspace)=>JSON.stringify(w.note??null);
async function openCase(round:string,persona='physician'){
 const seeded=await realFetch(`${base}/lab/case?persona=${persona}&round=${round}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(seeded.status).toBe(200);
 const packet=await seeded.json() as CasePacket;identity={mode:'clerk_jwt',getToken:async()=>packet.token??'invented-lab-token'};
 const recovery:GoogleMessageRecoveryAccess={authorize:async()=>{},load:async()=>recoveryRecord,persist:async value=>{recoveryRecord=value?structuredClone(value):null;}};
 root=createRoot(host);await act(async()=>root!.render(<Harness initial={packet.workspace} scope={packet.scope} recovery={recovery} auth={identity} teamRevision={packet.team_revision??1}/>));
 await wait(()=>expect(button('Check email access').disabled).toBe(false));noteBefore=noteIdentity(packet.workspace);return packet;
}
async function readForReview(){
 await click('Check email access');await click('Select email');await wait(()=>expect(host.querySelector<HTMLButtonElement>('.google-message-list button')?.disabled).toBe(false));
 await act(async()=>host.querySelector<HTMLButtonElement>('.google-message-list button')!.click());await click('Read full email');
 await click('Use for current visit');await act(async()=>host.querySelector<HTMLInputElement>('.google-message-check input')!.click());
}
async function counters(path:'revoke'|'inspect',wid:string):Promise<Counters>{
 const r=path==='revoke'?await realFetch(`${base}/lab/revoke`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:wid}),cache:'no-store',credentials:'omit',redirect:'error'}):
  await realFetch(`${base}/lab/inspect?workspace_id=${wid}`,{cache:'no-store',credentials:'omit',redirect:'error'});
 expect(r.status).toBe(200);const value=await r.json() as Counters;expect(Number.isInteger(value.provider_calls)).toBe(true);expect(Number.isInteger(value.model_rounds)).toBe(true);return value;
}
beforeEach(()=>{
 if(!base)return;vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE',base);
 vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
   const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);if(url.origin!==base)throw new Error('Only the loopback synthetic product server is allowed.');
   let nativeInit=init;if(init?.signal){const source=init.signal,native=transferableAbortController(),abort=()=>native.abort(source.reason);source.addEventListener('abort',abort,{once:true});if(source.aborted)abort();abortBridges.push(()=>source.removeEventListener('abort',abort));nativeInit={...init,signal:native.signal};}
   const mutating=init?.method==='POST';let action:string|undefined,key:string|undefined;if(mutating){try{const value=JSON.parse(String(init.body));action=value.action;key=value.idempotency_key;}catch{/* tests retain no raw request contents */}}
   try{const response=await realFetch(input,nativeInit);if(mutating)activeTrial?.wire.push({path:url.pathname,status:response.status,action,key});return response;}
   catch(e){if(mutating)activeTrial?.wire.push({path:url.pathname,status:null,action,key,error:e instanceof Error?e.message:String(e)});throw e;}
 });host=document.createElement('div');document.body.append(host);recoveryRecord=null;selectedSource=null;
});
afterEach(async()=>{if(root){await act(async()=>root!.unmount());root=undefined;}for(const dispose of abortBridges.splice(0))dispose();host?.remove();activeTrial=undefined;vi.unstubAllGlobals();vi.unstubAllEnvs();});
it.skipIf(!base).each([{persona:'physician',round:1},{persona:'nurse_practitioner',round:1},{persona:'physician_assistant',round:1},
 {persona:'physician',round:2},{persona:'nurse_practitioner',round:2},{persona:'physician_assistant',round:2}])('$persona round $round uses actual email custody APIs then Chief/specialist/edit/accept without replacing the clinical note',async({persona,round})=>{
 const started=performance.now(),trial:Trial={persona,round,workspace_id:'',boundary:'Mounted product email and handoff review controls, actual bounded HTTP APIs, FastAPI services, PostgreSQL custody and product model worker. Invented message/visit, deterministic authentication fixture and injected upstream Gmail/model responses; no live service, native layout, clinical sign-off or sending.',steps:[],wire:[],passed:false};trials.push(trial);activeTrial=trial;
 const step=(name:string,result_sha256?:string)=>trial.steps.push({name,elapsed_ms:Math.round((performance.now()-started)*100)/100,workspace_revision:current.revision,
   ...(selectedSource?{source_entry_id:selectedSource.entry_id,source_sha256:selectedSource.source_sha256}:{}),...(result_sha256?{result_sha256}:{})});
 try{
  const seeded=await realFetch(`${base}/lab/case?persona=${persona}&round=${round}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(seeded.status).toBe(200);
  const packet=await seeded.json() as {scope:GoogleMessageRecoveryScope;workspace:Workspace;clinical_note:unknown;token?:string;team_revision?:number};
  identity={mode:'clerk_jwt',getToken:async()=>packet.token??'invented-lab-token'};trial.workspace_id=packet.workspace.id;noteBefore=noteIdentity(packet.workspace);expect(packet.workspace.note).toBeTruthy();
  const recovery:GoogleMessageRecoveryAccess={authorize:async()=>{},load:async()=>recoveryRecord,persist:async value=>{recoveryRecord=value?structuredClone(value):null;}};
  const teamRevision=packet.team_revision??(await workspaceApi.team(identity)).revision;
  root=createRoot(host);await act(async()=>root!.render(<Harness initial={packet.workspace} scope={packet.scope} recovery={recovery} auth={identity} teamRevision={teamRevision}/>));
  await wait(()=>expect(button('Check email access').disabled).toBe(false));expect(trial.wire).toHaveLength(0);step('opened_email_work_no_provider_read');
  await click('Check email access');expect(host.textContent).toContain('Full email access granted');await click('Select email');
  await wait(()=>expect(host.querySelector<HTMLButtonElement>('.google-message-list button')?.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('.google-message-list button')!.click());
  await click('Read full email');await wait(()=>expect(host.querySelector('[aria-label="Complete selected email"]')).toBeTruthy());
  const exact=recoveryRecord!.message!;expect(exact.status).toBe('complete');expect(host.querySelector('[aria-label="Complete selected email"]')!.textContent).toBe(exact.message!.content);
  expect(exact.message!.content_sha256).toBe(await sha(exact.message!.content!));expect(host.querySelector('img,a')).toBeNull();step('full_selected_email_read');
  await click('Use for current visit');await act(async()=>host.querySelector<HTMLInputElement>('.google-message-check input')!.click());await click('Save reviewed email for this visit');
  await wait(()=>expect(host.textContent).toContain('Email source saved'));expect(noteIdentity(current)).toBe(noteBefore);const savedEntry=current.entries.find(e=>e.id===recoveryRecord!.saved!.entry_id)!;expect(savedEntry.kind).toBe('google_message');expect(savedEntry.content).toBe(exact.message!.content);step('source_saved_clinical_note_unchanged');
  expect(current.handoffs??[]).toHaveLength(0);await click('Ask Chief about this email');expect(host.querySelector('textarea[aria-label="Ask Chief"]')).toBeTruthy();
  await input('Ask Chief',`For this invented ${persona} visit, prepare follow-up work from the reviewed email. Ask Scribe for a private draft; identify missing information and do not send.`);await click('Ask Chief to prepare work');
  await wait(()=>expect(current.entries.some(e=>e.kind==='conversation')).toBe(true));step('chief_request_explicitly_submitted');
  const workResponse=await realFetch(`${base}/lab/work`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:current.id}),cache:'no-store',credentials:'omit',redirect:'error'});expect(workResponse.status).toBe(200);
  const latest=await workspaceApi.read(identity,current.id);await act(async()=>replaceWorkspace(latest));expect(noteIdentity(latest)).toBe(noteBefore);
  const initial=latest.handoffs!.find(h=>h.status==='completed')! as ReviewableHandoff;expect(initial).toBeTruthy();await click(`Review ${initial.recipient_name} result`);
  const initialEntry=latest.entries.find(e=>e.id===initial.result_entry_id)!;await wait(()=>expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toBe(initialEntry.reply!.content));step('specialist_saved_result_opened',initial.result_sha256!);
  await click('Request changes');const feedback=`${persona}: identify an owner and due date, keeping missing heart history and trial eligibility unconfirmed.`;await input('Change request',feedback);await click('Save change request');
  await click('Prepare revised draft');await wait(()=>expect(current.handoffs!.some(h=>(h as ReviewableHandoff).revision_request?.parent_handoff_id===initial.id)).toBe(true));
  const revised=current.handoffs!.find(h=>(h as ReviewableHandoff).revision_request?.parent_handoff_id===initial.id)! as ReviewableHandoff;expect(revised).toBeTruthy();step('human_edit_revision_saved');
  const revisedWork=await realFetch(`${base}/lab/work`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:current.id,handoff_id:revised.id}),cache:'no-store',credentials:'omit',redirect:'error'});expect(revisedWork.status).toBe(200);
  const completed=await workspaceApi.read(identity,current.id);await act(async()=>replaceWorkspace(completed));const final=completed.handoffs!.find(h=>h.id===revised.id)! as ReviewableHandoff;
  const entry=completed.entries.find(e=>e.id===final.result_entry_id)!;expect(final.status).toBe('completed');expect(entry.reply!.content).toContain('identify an owner and due date');expect(final.result_sha256).toBe(await sha(entry.reply!.content));
  await click('Accept draft for next work');await wait(()=>expect(host.textContent).toContain('Draft accepted'));const accepted=current.handoffs!.find(h=>h.id===final.id)! as ReviewableHandoff;expect(accepted.review).toMatchObject({decision:'accepted',result_sha256:final.result_sha256});
  const verified=await workspaceApi.read(identity,current.id);expect(noteIdentity(verified)).toBe(noteBefore);expect(verified.entries.find(e=>e.id===savedEntry.id)?.content).toBe(exact.message!.content);expect(recoveryRecord?.pending).toBeNull();expect(hasUnsavedWork()).toBe(false);
  expect(trial.wire.every(w=>w.status===200||w.status===409&&w.path===`/workspaces/${current.id}/conversation`)).toBe(true);step('exact_revised_draft_accepted_note_preserved',final.result_sha256!);trial.passed=true;
 }catch(e){trial.failure={message:e instanceof Error?e.message:String(e),dom:host.textContent??'',alerts:[...host.querySelectorAll('[role="alert"]')].map(e=>e.textContent??''),workspace:{
   revision:current?.revision??0,requests:current?.entries.filter(e=>e.kind==='conversation').map(e=>({id:e.id,revision:e.revision,request:e.model_request,has_reply:!!e.reply}))??[],
   handoffs:current?.handoffs?.map(h=>({id:h.id,status:h.status,attempt_id:h.attempt_id,result_entry_id:h.result_entry_id}))??[]}};throw e;}
},45000);
it.skipIf(!base).each(['masked_source','masked_handoff'] as const)('%s confirms a lost exact save after revocation without source disclosure or another provider/model call',async kind=>{
 const started=performance.now(),evidence:RecoveryTrial={kind,passed:false,elapsed_ms:0,workspace_id:'',provider_calls:0,model_rounds:0,wire:[]};recoveries.push(evidence);
 const trial:Trial={persona:'physician',round:kind==='masked_source'?3:4,workspace_id:'',boundary:'Terminal synthetic lost-reply recovery through actual signed product APIs; source grant revoked after commit. No live provider or model.',steps:[],wire:evidence.wire,passed:false};activeTrial=trial;
 try{
  const packet=await openCase(kind);evidence.workspace_id=packet.workspace.id;trial.workspace_id=packet.workspace.id;await readForReview();
  let revoked:Counters|undefined;
  const fetchBefore=globalThis.fetch;
  const loseSuccessfulReply=(suffix:string)=>vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
   const u=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url),response=await fetchBefore(input,init);
   if(!revoked&&init?.method==='POST'&&u.pathname.endsWith(suffix)&&response.status===200){await response.arrayBuffer();revoked=await counters('revoke',packet.workspace.id);throw new TypeError('Invented lost reply after server committed the exact save');}
   return response;
  });
  if(kind==='masked_source'){
   loseSuccessfulReply('/google-messages/review');await click('Save reviewed email for this visit');await wait(()=>expect(recoveryRecord?.pending?.kind).toBe('review'));
   expect(revoked).toBeTruthy();const original=recoveryRecord!.pending!;await click('Retry exact source save');
   await wait(()=>expect(host.textContent).toContain('exact email source save is confirmed'));expect(recoveryRecord?.pending).toBeNull();expect(recoveryRecord?.saved?.source_withheld).toBe(true);
   const requests=evidence.wire.filter(w=>w.path.endsWith('/google-messages/review'));expect(requests).toHaveLength(2);expect(requests[0].key).toBe(original.request.idempotency_key);expect(requests[1].key).toBe(requests[0].key);
   expect(host.querySelector('[aria-label="Complete selected email"]')).toBeNull();expect(host.textContent).not.toContain('sender@example.invalid');expect([...host.querySelectorAll('button')].some(b=>b.textContent==='Ask Chief about this email')).toBe(false);
  }else{
   await click('Save reviewed email for this visit');await click('Ask Chief about this email');await click('Ask Chief to prepare work');
   await wait(()=>{expect(current.entries.some(entry=>entry.kind==='conversation')).toBe(true);expect(host.querySelector('form')?.getAttribute('aria-busy')).toBe('false');});
   const workResponse=await realFetch(`${base}/lab/work`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:current.id}),cache:'no-store',credentials:'omit',redirect:'error'});expect(workResponse.status).toBe(200);
   const latest=await workspaceApi.read(identity,current.id);await act(async()=>replaceWorkspace(latest));const handoff=latest.handoffs!.find(h=>h.status==='completed')!;expect(handoff).toBeTruthy();await click(`Review ${handoff.recipient_name} result`);
   await click('Request changes');const feedback='Keep the invented café email fact unconfirmed and identify an owner and due date.';await input('Change request',feedback);
   loseSuccessfulReply(`/handoffs/${handoff.id}/review`);await click('Save change request');await wait(()=>expect(host.textContent).toContain('Review save unconfirmed'));expect(revoked).toBeTruthy();
   await act(async()=>replaceWorkspace(revoked!.workspace));expect(host.querySelector('[aria-label="Complete saved draft"]')).toBeNull();
   expect(host.querySelector('[aria-label="Complete selected email"]')).toBeNull();expect(host.textContent).not.toContain('sender@example.invalid');expect(host.textContent).not.toContain(feedback);
   await click('Retry same review save');await wait(()=>expect(host.textContent).toContain('exact saved review is confirmed'));
   const requests=evidence.wire.filter(w=>w.path.endsWith(`/handoffs/${handoff.id}/review`));expect(requests).toHaveLength(2);expect(requests[1].key).toBe(requests[0].key);
   expect(host.querySelector('[aria-label="Complete saved draft"]')).toBeNull();expect(host.textContent).not.toContain('Draft accepted');expect(host.textContent).not.toContain(feedback);
   expect([...host.querySelectorAll('button')].some(b=>b.textContent==='Prepare revised draft'||b.textContent==='Ask Chief for fresh work')).toBe(false);
  }
  expect(hasUnsavedWork()).toBe(false);const after=await counters('inspect',packet.workspace.id);expect(after.provider_calls).toBe(revoked!.provider_calls);expect(after.model_rounds).toBe(revoked!.model_rounds);expect(noteIdentity(after.workspace)).toBe(noteBefore);
  evidence.provider_calls=after.provider_calls;evidence.model_rounds=after.model_rounds;evidence.elapsed_ms=Math.round((performance.now()-started)*100)/100;evidence.passed=true;
 }catch(e){evidence.failure=(e instanceof Error?e.message:String(e))+'; '+(host.textContent??'');throw e;}
},45000);
afterAll(async()=>{const output=environment?.COSMAS_GOOGLE_MESSAGE_LAB_REPORT;if(!output||!base)return;const fsModule='node:fs/promises';const fs=await import(/* @vite-ignore */fsModule) as {writeFile:(p:string,s:string)=>Promise<void>};
 await fs.writeFile(output,JSON.stringify({schema:'cosmabot.google-message-product-server-ui.v1',synthetic_only:true,server_origin:base,episodes:trials,total:trials.length,completed:trials.filter(t=>t.passed).length,failed:trials.filter(t=>!t.passed).length,recovery_episodes:recoveries},null,2)+'\n');});
