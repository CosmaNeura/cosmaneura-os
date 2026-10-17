import {act} from 'react';
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
const realFetch=globalThis.fetch.bind(globalThis),pending=new Set<Promise<Response>>(),abortBridges:(()=>void)[]=[];
type Trial={persona:string;round:number;workspace_id:string;steps:{name:string;elapsed_ms:number}[];wire:{path:string;status:number|null}[];passed:boolean;failure?:string};
const trials:Trial[]=[];let active:Trial|undefined,root:Root,host:HTMLDivElement,identity:AuthenticatedWorkspaceIdentity,wid:string,noteBefore:string,sourcesBefore:string;
const note=(w:Workspace)=>JSON.stringify(w.note),sources=(w:Workspace)=>JSON.stringify(w.entries.filter(e=>['scratchpad','evidence'].includes(e.kind)));
async function wait(check:()=>void){for(let i=0;i<3000;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();done=true;}catch{}});if(done)return;}check();}
function button(label:string){const result=[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===label||b.getAttribute('aria-label')===label);expect(result,label).toBeTruthy();return result!;}
async function click(label:string){await wait(()=>expect(button(label).disabled,label).toBe(false));await act(async()=>button(label).click());}
async function input(selector:string,value:string){await wait(()=>expect(host.querySelector(selector)).toBeTruthy());const field=host.querySelector<HTMLTextAreaElement>(selector)!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function read(){const w=await workspaceApi.read(identity,wid);expect(note(w)).toBe(noteBefore);expect(sources(w)).toBe(sourcesBefore);return w;}
async function refresh(){await click('Refresh encounter');await wait(()=>expect(button('Refresh encounter').disabled).toBe(false));}
async function ask(content:string){await input('#team-question',content);await click('Send message');await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toBe(''));return read();}
async function workers(){const r=await realFetch(`${base}/lab/work`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:wid}),cache:'no-store',credentials:'omit',redirect:'error'});expect(r.status,await r.clone().text()).toBe(200);await refresh();return read();}
async function review(h:ReviewableHandoff,feedback:string){
 const earlier=host.querySelector<HTMLDetailsElement>('.team-earlier-tasks');if(earlier)earlier.open=true;
 await click(`Review ${h.recipient_name} result`);await wait(()=>expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent?.length).toBeGreaterThan(0));
 await click('Request changes');await input('.handoff-review textarea',feedback);await click('Save change request');await wait(()=>expect(button('Prepare revised draft').disabled).toBe(false));
 let current=await read();const changed=current.handoffs!.find(row=>row.id===h.id)! as ReviewableHandoff;expect(changed.review).toMatchObject({decision:'changes_requested',feedback,result_sha256:h.result_sha256});
 await click('Prepare revised draft');await wait(()=>expect(host.textContent).not.toContain('Saving revised assignment…'));current=await read();
 const revised=current.handoffs!.find(row=>(row as ReviewableHandoff).revision_request?.review_id===changed.review!.id)! as ReviewableHandoff;expect(revised).toBeTruthy();expect(revised.id).not.toBe(h.id);
 current=await workers();const completed=current.handoffs!.find(row=>row.id===revised.id)! as ReviewableHandoff;expect(completed.status).toBe('completed');
 await wait(()=>expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toContain(feedback));expect(completed.result_sha256).not.toBe(h.result_sha256);
 await click('Accept draft for next work');await wait(()=>expect(host.querySelector('.handoff-review')?.textContent).toContain('Draft accepted'));
 current=await read();const accepted=current.handoffs!.find(row=>row.id===completed.id)! as ReviewableHandoff;expect(accepted.review).toMatchObject({decision:'accepted',attempt_id:completed.attempt_id,result_entry_id:completed.result_entry_id,result_sha256:completed.result_sha256});
 await click('Close draft review');return accepted;
}
beforeEach(()=>{window.history.replaceState(null,'',window.location.pathname+window.location.search);if(!base)return;vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE',base);vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
 const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);if(url.origin!==base)throw new Error('Synthetic test permits only its own loopback bridge.');
 let native=init;if(init?.signal){const source=init.signal,target=transferableAbortController(),abort=()=>target.abort(source.reason);source.addEventListener('abort',abort,{once:true});if(source.aborted)abort();abortBridges.push(()=>source.removeEventListener('abort',abort));native={...init,signal:target.signal};}
 const owner=active,transport=realFetch(input,native);pending.add(transport);try{const r=await transport;owner?.wire.push({path:url.pathname,status:r.status});return r;}catch(e){owner?.wire.push({path:url.pathname,status:null});throw e;}finally{pending.delete(transport);}
 });host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{if(!base)return;await act(async()=>root.unmount());if(pending.size)await Promise.allSettled([...pending]);abortBridges.splice(0).forEach(fn=>fn());host.remove();active=undefined;vi.unstubAllGlobals();vi.unstubAllEnvs();});
it.skipIf(!base).each([{persona:'physician',round:1},{persona:'nurse_practitioner',round:1},{persona:'physician_assistant',round:1},{persona:'physician',round:2},{persona:'nurse_practitioner',round:2},{persona:'physician_assistant',round:2}])('$persona round $round gives Chief Scribe sources then reviews four actual specialist loops',async({persona,round})=>{
 const began=performance.now(),trial:Trial={persona,round,workspace_id:'',steps:[],wire:[],passed:false};active=trial;trials.push(trial);const step=(name:string)=>trial.steps.push({name,elapsed_ms:Math.round(performance.now()-began)});
 try{
 const seeded=await realFetch(`${base}/lab/case?persona=${persona}&round=${round}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(seeded.status,await seeded.clone().text()).toBe(200);
 const packet=await seeded.json() as {token:string;workspace:Workspace};wid=packet.workspace.id;trial.workspace_id=wid;identity={mode:'clerk_jwt',getToken:async()=>packet.token};noteBefore=note(packet.workspace);sourcesBefore=sources(packet.workspace);
 await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));await click('Visits and notes');
 await wait(()=>expect([...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].some(b=>b.textContent?.includes(packet.workspace.label))).toBe(true));
 await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].find(b=>b.textContent?.includes(packet.workspace.label))!.click());
 await wait(()=>expect(host.querySelector('#team-notebook')).toBeTruthy());
 const chief=[...host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent==='Chief')!;await act(async()=>chief.click());await wait(()=>expect(button('Prepare team drafts').disabled).toBe(false));step('opened_saved_encounter_scribe_sources');
 await click('Prepare team drafts');expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.value).toContain('independent');
 let w=await ask(`For this invented ${persona} encounter, ask Research, Visit Prep and Follow-up to prepare independent private drafts from the saved Scribe transcript and summary. Preserve unknown diagnosis, missing DOB and trial eligibility. Do not search publicly or send anything.`);
 expect(w.handoffs).toHaveLength(3);expect(new Set(w.handoffs!.map(h=>h.recipient_role))).toEqual(new Set(['research','visit_prep','follow_up']));step('chief_three_exact_assignments_saved');
 w=await workers();expect(w.handoffs!.every(h=>h.status==='completed')).toBe(true);step('three_parallel_product_workers_completed');
 const first=[...w.handoffs!] as ReviewableHandoff[];const accepted=[];
 for(const h of first){accepted.push(await review(h,`${persona}: identify owner and due date for ${h.recipient_role}; preserve unknown trial eligibility.`));step(h.recipient_role+'_revision_and_acceptance');}
 const chiefAgain=[...host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent==='Chief')!;await act(async()=>chiefAgain.click());
 w=await ask('Ask Scribe only to organize the same saved transcript and summary into a source-based private documentation draft; keep the existing clinical note unchanged.');w=await workers();
 const scribe=w.handoffs!.find(h=>h.recipient_role==='scribe')! as ReviewableHandoff;accepted.push(await review(scribe,`${persona}: confirm missing DOB and owner without inventing facts.`));step('scribe_revision_and_acceptance_note_unchanged');
 await act(async()=>chiefAgain.click());w=await ask('Collect the revised saved work from all four specialists. Explain which drafts were accepted and what a human must still do. Do not create more assignments.');expect(w.handoffs).toHaveLength(8);step('chief_reads_saved_teammate_drafts');
 const r=await realFetch(`${base}/lab/inspect?workspace_id=${wid}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(r.status).toBe(200);const evidence=await r.json() as {admissions:{state:string;role:string}[];tool_receipts:{actor_id:string;human_id:string;detail:Record<string,unknown>}[];dispatches:{started_s:number;ended_s:number;role:string}[]};
 expect(evidence.admissions).toHaveLength(11);expect(evidence.admissions.every(a=>a.state==='completed')).toBe(true);expect(evidence.tool_receipts).toHaveLength(25);expect(evidence.tool_receipts.every(r=>r.actor_id!==r.human_id)).toBe(true);
 const parallel=evidence.dispatches.filter(d=>['research','visit_prep','follow_up'].includes(d.role)).slice(0,3);expect(Math.max(...parallel.map(d=>d.started_s))).toBeLessThan(Math.min(...parallel.map(d=>d.ended_s)));
 const reread=await read();for(const h of accepted)expect((reread.handoffs!.find(x=>x.id===h.id) as ReviewableHandoff).review).toMatchObject(h.review!);expect(trial.wire.every(x=>x.status===200)).toBe(true);step('fresh_read_exact_acceptance_and_custody');trial.passed=true;
 }catch(e){trial.failure=(e instanceof Error?e.message:String(e))+'\nDOM: '+host.textContent;throw e;}
},60000);
afterAll(async()=>{if(!base||!environment?.COSMAS_MULTI_LAB_REPORT)return;const fs='node:fs/promises';const {writeFile}=await import(/* @vite-ignore */fs) as {writeFile:(p:string,s:string)=>Promise<void>};await writeFile(environment.COSMAS_MULTI_LAB_REPORT,JSON.stringify({schema:'cosmabot.multispecialist-signed-product-ui.v1',synthetic_only:true,source_adapter:'actual v6 with offline MockTransport',personas_are_scripted_not_real_users:true,trials,total:trials.length,completed:trials.filter(t=>t.passed).length},null,2)+'\n');});
