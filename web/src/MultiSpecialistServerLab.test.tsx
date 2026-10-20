import {act as reactAct} from 'react';
import {ScribeLabEpisode} from './scribe-lab-episode';
import {createRoot,type Root} from 'react-dom/client';
import {afterAll,afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {workspaceApi,type Workspace,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import type {ReviewableHandoff} from './handoff-review-api';
import {memoryDraftStorage} from './draft-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const util='node:util';const {transferableAbortController}=await import(/* @vite-ignore */util) as {transferableAbortController:()=>AbortController};
const environment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const base=environment?.COSMAS_MULTI_LAB_URL;
const realFetch=globalThis.fetch.bind(globalThis);
type Trial={persona:string;round:number;workspace_id:string;steps:{name:string;elapsed_ms:number}[];wire:{path:string;method:string;status:number|null;aborted?:boolean}[];passed:boolean;failure?:string};
type Episode={lifecycle:ScribeLabEpisode;root:Root;host:HTMLDivElement;identity:AuthenticatedWorkspaceIdentity;wid:string;noteBefore:string;sourcesBefore:string;trial?:Trial};
const trials:Trial[]=[];let mounted:Episode|undefined,terminalFailure:string|undefined;
const note=(w:Workspace)=>JSON.stringify(w.note),sources=(w:Workspace)=>JSON.stringify(w.entries.filter(e=>['scratchpad','evidence'].includes(e.kind)));
function controls(ep:Episode){
const act=async <T,>(callback:()=>T|Promise<T>):Promise<T>=>{ep.lifecycle.check();const result=await reactAct(callback);ep.lifecycle.check();return result;};
async function wait(check:()=>void){const until=performance.now()+15000;while(performance.now()<until){ep.lifecycle.check();let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));ep.lifecycle.check();try{check();done=true;}catch{}});if(done)return;}ep.lifecycle.check();check();}
function button(label:string){const result=[...ep.host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===label||b.getAttribute('aria-label')===label);expect(result,label).toBeTruthy();return result!;}
async function click(label:string){await wait(()=>expect(button(label).disabled,label).toBe(false));await act(async()=>button(label).click());}
async function input(selector:string,value:string){await wait(()=>expect(ep.host.querySelector(selector)).toBeTruthy());const field=ep.host.querySelector<HTMLTextAreaElement>(selector)!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function read(){ep.lifecycle.check();const w=await workspaceApi.read(ep.identity,ep.wid);ep.lifecycle.check();expect(note(w)).toBe(ep.noteBefore);expect(sources(w)).toBe(ep.sourcesBefore);return w;}
async function refresh(){await click('Refresh encounter');await wait(()=>expect(button('Refresh encounter').disabled).toBe(false));}
async function ask(content:string){await input('#team-question',content);await click('Send message');await wait(()=>expect(ep.host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toBe(''));const current=await read();expect(current.entries.find(e=>e.kind==='conversation'&&e.content===content)?.reply).toBeTruthy();return current;}
async function workers(){const r=await ep.lifecycle.fetch(realFetch,`${base}/lab/work`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:ep.wid}),cache:'no-store',credentials:'omit',redirect:'error'});expect(r.status,await r.clone().text()).toBe(200);await refresh();return read();}
async function review(h:ReviewableHandoff,feedback:string){
 const earlier=ep.host.querySelector<HTMLDetailsElement>('.team-earlier-tasks');if(earlier)earlier.open=true;
 await click(`Review ${h.recipient_name} result`);await wait(()=>expect(ep.host.querySelector('[aria-label="Complete saved draft"]')?.textContent?.length).toBeGreaterThan(0));
 await click('Request changes');await input('.handoff-review textarea',feedback);await click('Save change request');await wait(()=>expect(button('Prepare revised draft').disabled).toBe(false));
 let current=await read();const changed=current.handoffs!.find(row=>row.id===h.id)! as ReviewableHandoff;expect(changed.review).toMatchObject({decision:'changes_requested',feedback,result_sha256:h.result_sha256});
 await click('Prepare revised draft');await wait(()=>expect(ep.host.textContent).not.toContain('Saving revised assignment…'));current=await read();
 const revised=current.handoffs!.find(row=>(row as ReviewableHandoff).revision_request?.review_id===changed.review!.id)! as ReviewableHandoff;expect(revised).toBeTruthy();expect(revised.id).not.toBe(h.id);
 current=await workers();const completed=current.handoffs!.find(row=>row.id===revised.id)! as ReviewableHandoff;expect(completed.status).toBe('completed');
 await wait(()=>expect(ep.host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toContain(feedback));expect(completed.result_sha256).not.toBe(h.result_sha256);
 await click('Accept draft for next work');await wait(()=>expect(ep.host.querySelector('.handoff-review')?.textContent).toContain('Draft accepted'));
 current=await read();const accepted=current.handoffs!.find(row=>row.id===completed.id)! as ReviewableHandoff;expect(accepted.review).toMatchObject({decision:'accepted',attempt_id:completed.attempt_id,result_entry_id:completed.result_entry_id,result_sha256:completed.result_sha256});
 await click('Close draft review');return accepted;
}
async function coworker(name:string){await wait(()=>expect([...ep.host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent===name)).toBeTruthy());await act(async()=>[...ep.host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent===name)!.click());}
return {act,wait,button,click,read,ask,workers,review,coworker};
}
beforeEach(()=>{window.history.replaceState(null,'',window.location.pathname+window.location.search);if(!base)return;if(terminalFailure)throw new Error('Prior multi-specialist episode failed; no new case admitted: '+terminalFailure);
const nativeAbort=transferableAbortController();vi.stubGlobal('AbortController',nativeAbort.constructor);vi.stubGlobal('AbortSignal',nativeAbort.signal.constructor);vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE',base);
const host=document.createElement('div');document.body.append(host);const ep:Episode={lifecycle:new ScribeLabEpisode(),host,root:createRoot(host),identity:{mode:'clerk_jwt',getToken:async()=>{throw new Error('Episode identity not initialized');}},wid:'',noteBefore:'',sourcesBefore:''};mounted=ep;
vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);if(url.origin!==base)throw new Error('Synthetic test permits only its own loopback bridge.');const method=init?.method??'GET';
try{const response=await ep.lifecycle.fetch(realFetch,input,init);ep.trial?.wire.push({path:url.pathname,method,status:response.status});return response;}catch(error){ep.trial?.wire.push({path:url.pathname,method,status:null,aborted:init?.signal?.aborted===true});throw error;}
});});
afterEach(async()=>{if(!base||!mounted)return;const ep=mounted;ep.lifecycle.close();
try{try{await ep.lifecycle.drain(10000);}finally{await reactAct(async()=>ep.root.unmount());}}
catch(error){terminalFailure=error instanceof Error?error.message:String(error);throw error;}
finally{ep.host.remove();mounted=undefined;vi.unstubAllGlobals();vi.unstubAllEnvs();await saveReport();}
},20000);
it.skipIf(!base).each([{persona:'physician',round:1},{persona:'nurse_practitioner',round:1},{persona:'physician_assistant',round:1},{persona:'physician',round:2},{persona:'nurse_practitioner',round:2},{persona:'physician_assistant',round:2}])('$persona round $round gives Chief Scribe sources then reviews four actual specialist loops',async({persona,round})=>{
 const ep=mounted!;const {act,wait,button,click,read,ask,workers,review,coworker}=controls(ep);
 const began=performance.now(),trial:Trial={persona,round,workspace_id:'',steps:[],wire:[],passed:false};ep.trial=trial;trials.push(trial);const step=(name:string)=>{ep.lifecycle.check();trial.steps.push({name,elapsed_ms:Math.round(performance.now()-began)});};
 return ep.lifecycle.run(async()=>{try{
 const seeded=await ep.lifecycle.fetch(realFetch,`${base}/lab/case?persona=${persona}&round=${round}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(seeded.status,await seeded.clone().text()).toBe(200);
 const packet=await seeded.json() as {token:string;workspace:Workspace};ep.wid=packet.workspace.id;trial.workspace_id=ep.wid;ep.identity={mode:'clerk_jwt',getToken:async()=>packet.token};ep.noteBefore=note(packet.workspace);ep.sourcesBefore=sources(packet.workspace);
 await act(async()=>ep.root.render(<EncounterWorkspace authenticated={ep.identity} draftStorage={memoryDraftStorage()}/>));await click('Visits and notes');
 await wait(()=>expect([...ep.host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].some(b=>b.textContent?.includes(packet.workspace.label))).toBe(true));
 await act(async()=>[...ep.host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].find(b=>b.textContent?.includes(packet.workspace.label))!.click());
 await wait(()=>expect(ep.host.querySelector('#team-notebook')).toBeTruthy());
 await coworker('Chief');await wait(()=>expect(button('Prepare team drafts').disabled).toBe(false));step('opened_saved_encounter_scribe_sources');
 await click('Prepare team drafts');expect(ep.host.querySelector<HTMLTextAreaElement>('#team-question')!.value).toContain('independent');
 let w=await ask(`For this invented ${persona} encounter, ask Research, Visit Prep and Follow-up to prepare independent private drafts from the saved Scribe transcript and summary. Preserve unknown diagnosis, missing DOB and trial eligibility. Do not search publicly or send anything.`);
 expect(w.handoffs).toHaveLength(3);expect(new Set(w.handoffs!.map(h=>h.recipient_role))).toEqual(new Set(['research','visit_prep','follow_up']));step('chief_three_exact_assignments_saved');
 w=await workers();expect(w.handoffs!.every(h=>h.status==='completed')).toBe(true);step('three_parallel_product_workers_completed');
 const first=[...w.handoffs!] as ReviewableHandoff[];const accepted=[];
 for(const h of first){accepted.push(await review(h,`${persona}: identify owner and due date for ${h.recipient_role}; preserve unknown trial eligibility.`));step(h.recipient_role+'_revision_and_acceptance');}
 await coworker('Chief');
 w=await ask('Ask Scribe only to organize the same saved transcript and summary into a source-based private documentation draft; keep the existing clinical note unchanged.');w=await workers();
 const scribe=w.handoffs!.find(h=>h.recipient_role==='scribe')! as ReviewableHandoff;accepted.push(await review(scribe,`${persona}: confirm missing DOB and owner without inventing facts.`));step('scribe_revision_and_acceptance_note_unchanged');
 await coworker('Chief');w=await ask('Collect the revised saved work from all four specialists. Explain which drafts were accepted and what a human must still do. Do not create more assignments.');expect(w.handoffs).toHaveLength(8);step('chief_reads_saved_teammate_drafts');
 const r=await ep.lifecycle.fetch(realFetch,`${base}/lab/inspect?workspace_id=${ep.wid}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(r.status).toBe(200);const evidence=await r.json() as {admissions:{state:string;role:string}[];tool_receipts:{actor_id:string;human_id:string;detail:Record<string,unknown>}[];dispatches:{started_s:number;ended_s:number;role:string}[]};
 expect(evidence.admissions).toHaveLength(11);expect(evidence.admissions.every(a=>a.state==='completed')).toBe(true);expect(evidence.tool_receipts).toHaveLength(25);expect(evidence.tool_receipts.every(r=>r.actor_id!==r.human_id)).toBe(true);
 const parallel=evidence.dispatches.filter(d=>['research','visit_prep','follow_up'].includes(d.role)).slice(0,3);expect(Math.max(...parallel.map(d=>d.started_s))).toBeLessThan(Math.min(...parallel.map(d=>d.ended_s)));
 const reread=await read();for(const h of accepted)expect((reread.handoffs!.find(x=>x.id===h.id) as ReviewableHandoff).review).toMatchObject(h.review!);
 // Navigation and refresh may cancel obsolete reads; every command and completed read must succeed.
 expect(trial.wire.filter(x=>x.status!==200&&!(x.method==='GET'&&x.status===null&&x.aborted))).toEqual([]);step('fresh_read_exact_acceptance_and_custody');trial.passed=true;
 }catch(e){trial.failure=(e instanceof Error?e.message:String(e))+'\nDOM: '+ep.host.textContent;terminalFailure=trial.failure.split('\n')[0];throw e;}},120000).catch(error=>{if(!trial.failure)trial.failure=(error instanceof Error?error.message:String(error))+'\nDOM: '+ep.host.textContent;terminalFailure=trial.failure.split('\n')[0];throw error;});
},130000);
async function saveReport(){if(!base||!environment?.COSMAS_MULTI_LAB_REPORT)return;const fs='node:fs/promises';const {writeFile}=await import(/* @vite-ignore */fs) as {writeFile:(p:string,s:string)=>Promise<void>};await writeFile(environment.COSMAS_MULTI_LAB_REPORT,JSON.stringify({schema:'cosmabot.multispecialist-signed-product-ui.v1',synthetic_only:true,source_adapter:'actual v6 with offline MockTransport',personas_are_scripted_not_real_users:true,trials,total:trials.length,completed:trials.filter(t=>t.passed).length},null,2)+'\n');}
afterAll(saveReport);
