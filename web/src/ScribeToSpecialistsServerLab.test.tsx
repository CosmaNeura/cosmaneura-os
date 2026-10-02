import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterAll,afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_CAPTURE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_CAPTURE_NOTES_ENABLED','true');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {workspaceApi,type Workspace,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import type {ReviewableHandoff} from './handoff-review-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {encodePcm16MonoWav,pcm16WavProfile,type CaptureSourceStartOptions} from '../../clients/capture/src/capture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const util='node:util';const {transferableAbortController}=await import(/* @vite-ignore */util) as {transferableAbortController:()=>AbortController};
const environment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const base=environment?.COSMAS_SCRIBE_LAB_URL;
const generatedSource=vi.hoisted(()=>({current:null as null|{emit:(number:number)=>Promise<void>;starts:number;stops:number}}));
vi.mock('../../clients/capture/src/capture-source-factory',()=>({IOS_NATIVE_PCM_CAPTURE_ENABLED:false,createCaptureSource:async()=>{const source=new GeneratedPcmSource();generatedSource.current=source;return source;},isIosNativePlatform:async()=>false}));
const realFetch=globalThis.fetch.bind(globalThis),pending=new Set<Promise<Response>>(),abortBridges:(()=>void)[]=[];
type Trial={persona:string;round:number;workspace_id:string;steps:{name:string;elapsed_ms:number}[];wire:{path:string;status:number|null}[];passed:boolean;failure?:string};
class GeneratedPcmSource {
 readonly kind='synthetic' as const;
 starts=0;stops=0;private active=false;private options:CaptureSourceStartOptions|null=null;
 async start(options:CaptureSourceStartOptions){expect(this.active).toBe(false);this.active=true;this.options=options;this.starts++;}
 async emit(number:number){expect(this.active).toBe(true);const frames=number<2?16000:2400;
  const samples=new Int16Array(new ArrayBuffer(frames*2));for(let i=0;i<frames;i++)samples[i]=((i*17+(number+1)*101)%24001)-12000;
  const bytes=encodePcm16MonoWav(samples,pcm16WavProfile(this.options!.capabilities));
  await this.options!.onChunk({sequenceNumber:number,durationMs:frames/16,wavBytes:bytes});
  expect(bytes.every(b=>b===0)).toBe(true);
 }
 async stop(){if(!this.active)return;this.stops++;await this.emit(2);this.active=false;}
}
const trials:Trial[]=[];let locksHeld=new Set<string>();const closeAlerts:string[]=[];let active:Trial|undefined,root:Root,host:HTMLDivElement,identity:AuthenticatedWorkspaceIdentity,wid:string,noteBefore:string,sourcesBefore:string;
const note=(w:Workspace)=>JSON.stringify(w.note,(_key,value)=>_key==='sources_changed'?undefined:value),sources=(w:Workspace)=>JSON.stringify(w.entries.filter(e=>['scratchpad','evidence'].includes(e.kind)));
async function wait(check:()=>void){for(let i=0;i<3000;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();done=true;}catch{}});if(done)return;}check();}
function button(label:string){const result=[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===label||b.textContent?.replace(/^📄\s*/u,'').trim()===label||b.getAttribute('aria-label')===label);expect(result,label).toBeTruthy();return result!;}
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
beforeEach(()=>{if(!base)return;const nativeAbort=transferableAbortController();vi.stubGlobal('AbortController',nativeAbort.constructor);vi.stubGlobal('AbortSignal',nativeAbort.signal.constructor);vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE',base);vi.stubEnv('VITE_CAPTURE_UPLOAD_ORIGINS',base);vi.stubGlobal('indexedDB',new IDBFactory());vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 expect(typeof AbortSignal.any).toBe('function');const a=new AbortController(),b=new AbortController(),combined=AbortSignal.any([a.signal,b.signal]);b.abort();expect(combined.aborted).toBe(true);
 closeAlerts.length=0;vi.spyOn(window,'alert').mockImplementation(message=>{closeAlerts.push(String(message));});const held=new Set<string>();locksHeld=held;Object.defineProperty(navigator,'locks',{configurable:true,value:{request:async(name:string,_options:LockOptions,callback:LockGrantedCallback<unknown>)=>{if(held.has(name))return callback(null);held.add(name);try{return await callback({name,mode:'exclusive'});}finally{held.delete(name);}}} as LockManager});
 vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
 const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);if(url.origin!==base)throw new Error('Synthetic test permits only its own loopback bridge.');
 let native=init;if(init?.signal){const source=init.signal,target=transferableAbortController(),abort=()=>target.abort(source.reason);source.addEventListener('abort',abort,{once:true});if(source.aborted)abort();abortBridges.push(()=>source.removeEventListener('abort',abort));native={...init,signal:target.signal};}
 const owner=active,transport=realFetch(input,native);pending.add(transport);try{const r=await transport;if(['POST','PUT'].includes(init?.method??''))owner?.wire.push({path:url.pathname,status:r.status});return r;}catch(e){if(['POST','PUT'].includes(init?.method??''))owner?.wire.push({path:url.pathname,status:null});throw e;}finally{pending.delete(transport);}
 });host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{if(!base)return;await act(async()=>root.unmount());await wait(()=>expect(locksHeld.size,'actual recording lock released after unmount').toBe(0));expect(closeAlerts).toEqual([]);if(pending.size)await Promise.allSettled([...pending]);abortBridges.splice(0).forEach(fn=>fn());host.remove();active=undefined;Reflect.deleteProperty(navigator,'locks');vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
it.skipIf(!base).each([{persona:'physician',round:1},{persona:'nurse_practitioner',round:1},{persona:'physician_assistant',round:1},{persona:'physician',round:2},{persona:'nurse_practitioner',round:2},{persona:'physician_assistant',round:2}])('$persona round $round records generated audio, reviews it and accepts four actual specialist loops',async({persona,round})=>{
 const began=performance.now(),trial:Trial={persona,round,workspace_id:'',steps:[],wire:[],passed:false};active=trial;trials.push(trial);const step=(name:string)=>trial.steps.push({name,elapsed_ms:Math.round(performance.now()-began)});
 try{
 const seeded=await realFetch(`${base}/lab/case?persona=${persona}&round=${round}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(seeded.status,await seeded.clone().text()).toBe(200);
 const packet=await seeded.json() as {token:string;workspace:Workspace};wid=packet.workspace.id;trial.workspace_id=wid;identity={mode:'clerk_jwt',getToken:async()=>packet.token};noteBefore=note(packet.workspace);sourcesBefore=sources(packet.workspace);const draftStorage=memoryDraftStorage();
 await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={draftStorage}/>));await click('Choose an encounter');
 await wait(()=>expect([...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].some(b=>b.textContent?.includes(packet.workspace.label))).toBe(true));
 await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].find(b=>b.textContent?.includes(packet.workspace.label))!.click());
 await wait(()=>expect(host.querySelector('#team-notebook')).toBeTruthy());
 const scribeButton=[...host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent==='Scribe')!;
 await act(async()=>scribeButton.click());await click('Record visit');
 await wait(()=>expect(host.querySelector('[aria-label="Recording consent"] input')).toBeTruthy());await act(async()=>{const regions=host.querySelector<HTMLInputElement>('[aria-label="Recording consent"] input')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(regions,'US-NY');regions.dispatchEvent(new Event('input',{bubbles:true}));});
 await wait(()=>expect(button('Confirm consent & record').disabled).toBe(false));
 expect(host.querySelector('input[type="date"]')).toBeNull();await click('Confirm consent & record');
 await wait(()=>expect(button('Stop and upload').disabled).toBe(false));expect(generatedSource.current?.starts).toBe(1);
 await act(async()=>{await generatedSource.current!.emit(0);await generatedSource.current!.emit(1);});await click('Stop and upload');
 await wait(()=>expect(host.textContent).toContain('SIMULATED ASR FROM VERIFIED GENERATED AUDIO'));
 expect(generatedSource.current?.stops).toBe(1);step('recorded_encrypted_uploaded_verified_and_simulated_asr_ready');
 await click('Continue to note');await wait(()=>expect(button('Use a Scribe recording').disabled).toBe(false));await click('Use a Scribe recording');await wait(()=>expect(host.querySelector('[aria-label="Existing Scribe recording"]')?.textContent).toContain('SIMULATED ASR FROM VERIFIED GENERATED AUDIO'));
 const sourcePanel=host.querySelector('[aria-label="Existing Scribe recording"]')!;const ack=sourcePanel.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
 await act(async()=>ack.click());await click('Use this version with my team');await wait(()=>expect(host.textContent).toContain('Saved to this encounter’s sources'));
 let w=await workspaceApi.read(identity,wid);expect(note(w)).toBe(noteBefore);expect(w.note?.latest?.sources_changed).toBe(true);expect(w.entries.filter(e=>e.kind==='evidence')).toHaveLength(1);sourcesBefore=sources(w);step('explicit_review_and_actual_snapshot_share');
 const chief=[...host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent==='Chief')!;
 await act(async()=>chief.click());await wait(()=>expect(button('Prepare team drafts').disabled).toBe(false));
 w=await ask('Ask Scribe only to organize the same recorded and reviewed transcript into a source-based private summary; keep the existing clinical note unchanged.');w=await workers();
 const scribe=w.handoffs!.find(h=>h.recipient_role==='scribe')! as ReviewableHandoff;const accepted=[await review(scribe,`${persona}: confirm missing DOB and owner without inventing facts.`)];step('scribe_summary_revision_and_acceptance');
 const chiefAgain=[...host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent==='Chief')!;await act(async()=>chiefAgain.click());
 w=await ask(`For this invented ${persona} encounter, ask Research, Visit Prep and Follow-up to prepare independent private drafts from the recorded, reviewed Scribe transcript and Scribe’s accepted saved summary. Preserve unknown diagnosis, missing DOB and trial eligibility. Do not search publicly or send anything.`);
 expect(w.handoffs).toHaveLength(5);expect(new Set(w.handoffs!.filter(h=>h.recipient_role!=='scribe').map(h=>h.recipient_role))).toEqual(new Set(['research','visit_prep','follow_up']));step('chief_three_exact_assignments_saved');
 w=await workers();const first=w.handoffs!.filter(h=>h.recipient_role!=='scribe') as ReviewableHandoff[];expect(first.every(h=>h.status==='completed')).toBe(true);step('three_parallel_product_workers_completed');
 for(const h of first){accepted.push(await review(h,`${persona}: identify owner and due date for ${h.recipient_role}; preserve unknown trial eligibility.`));step(h.recipient_role+'_revision_and_acceptance');}
 await act(async()=>chiefAgain.click());w=await ask('Collect the revised saved work from all four specialists. Identify the exact saved draft versions and what a human must still do. Do not create more assignments.');expect(w.handoffs).toHaveLength(8);step('chief_reads_saved_teammate_drafts');
 for(const h of accepted){expect(w.entries.at(-1)?.reply?.content).toContain(h.result_entry_id!);expect(w.entries.at(-1)?.reply?.content).toContain(h.result_sha256!);}expect(w.entries.at(-1)?.reply?.content).toContain('A human must confirm owner, due date and trial eligibility');
 const r=await realFetch(`${base}/lab/inspect?workspace_id=${wid}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(r.status).toBe(200);const evidence=await r.json() as {admissions:{state:string;role:string}[];tool_receipts:{actor_id:string;human_id:string;detail:Record<string,unknown>}[];dispatches:{started_s:number;ended_s:number;role:string}[];capture:{complete:boolean;session_id:string;uploads:{sequence_number:number;frames:number}[];real_asr_tested:boolean;physical_microphone_tested:boolean}};
 expect(evidence.admissions).toHaveLength(11);expect(evidence.admissions.every(a=>a.state==='completed')).toBe(true);expect(evidence.tool_receipts).toHaveLength(15);expect(evidence.tool_receipts.every(r=>r.actor_id!==r.human_id)).toBe(true);
 expect(evidence.capture).toMatchObject({complete:true,real_asr_tested:false,physical_microphone_tested:false});expect(evidence.capture.uploads.map(p=>[p.sequence_number,p.frames])).toEqual([[0,16000],[1,16000],[2,2400]]);expect(trial.wire.filter(p=>p.path.startsWith('/lab/audio/')&&p.status===201)).toHaveLength(3);
 const parallel=evidence.dispatches.filter(d=>['research','visit_prep','follow_up'].includes(d.role)).slice(0,3);expect(Math.max(...parallel.map(d=>d.started_s))).toBeLessThan(Math.min(...parallel.map(d=>d.ended_s)));
 const reread=await read();for(const h of accepted)expect((reread.handoffs!.find(x=>x.id===h.id) as ReviewableHandoff).review).toMatchObject(h.review!);expect(trial.wire.every(x=>x.status===200||x.status===201||x.path.endsWith('/capture/admission')&&x.status===409)).toBe(true);step('fresh_read_exact_acceptance_and_custody');const captureRequests=trial.wire.filter(x=>x.path.includes('/capture/')||x.path.startsWith('/lab/audio/')).length;await act(async()=>root.unmount());await wait(()=>expect(locksHeld.size).toBe(0));expect(closeAlerts).toEqual([]);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={draftStorage}/>));await click('Choose an encounter');await wait(()=>expect([...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].some(b=>b.textContent?.includes(packet.workspace.label))).toBe(true));await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].find(b=>b.textContent?.includes(packet.workspace.label))!.click());await wait(()=>expect(host.querySelector('#team-notebook')).toBeTruthy());const reopened=await read();for(const h of accepted)expect((reopened.handoffs!.find(x=>x.id===h.id) as ReviewableHandoff).review).toMatchObject(h.review!);expect(trial.wire.filter(x=>x.path.includes('/capture/')||x.path.startsWith('/lab/audio/'))).toHaveLength(captureRequests);expect(generatedSource.current).toMatchObject({starts:1,stops:1});step('reopened_product_ui_without_rerecording_or_duplicate_effect');trial.passed=true;
 }catch(e){trial.failure=(e instanceof Error?e.message:String(e))+'\nDOM: '+host.textContent;throw e;}
},60000);
afterAll(async()=>{if(!base||!environment?.COSMAS_SCRIBE_LAB_REPORT)return;const fs='node:fs/promises';const {writeFile}=await import(/* @vite-ignore */fs) as {writeFile:(p:string,s:string)=>Promise<void>};await writeFile(environment.COSMAS_SCRIBE_LAB_REPORT,JSON.stringify({schema:'cosmabot.scribe-to-specialists-signed-product-ui.v1',synthetic_only:true,source_adapter:'actual recording controller/queue/transport and v6 with offline MockTransport',hardware:'deterministic generated PCM only',speech_recognition:'simulated only after independently verified capture completes',personas_are_scripted_not_real_users:true,trials,total:trials.length,completed:trials.filter(t=>t.passed).length},null,2)+'\n');});
