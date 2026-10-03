import {act as reactAct} from 'react';
import {ScribeLabEpisode} from './scribe-lab-episode';
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
const generatedSource=vi.hoisted(()=>({create:null as null|(()=>GeneratedPcmSource)}));
vi.mock('../../clients/capture/src/capture-source-factory',()=>({IOS_NATIVE_PCM_CAPTURE_ENABLED:false,createCaptureSource:async()=>generatedSource.create!(),isIosNativePlatform:async()=>false}));
const realFetch=globalThis.fetch.bind(globalThis);
type Trial={persona:string;round:number;workspace_id:string;steps:{name:string;elapsed_ms:number}[];wire:{path:string;status:number|null}[];passed:boolean;failure?:string};
class GeneratedPcmSource {
 readonly kind='synthetic' as const;
 starts=0;stops=0;private active=false;private options:CaptureSourceStartOptions|null=null;
 constructor(private readonly lifecycle:ScribeLabEpisode){}
 async start(options:CaptureSourceStartOptions){this.lifecycle.check();expect(this.active).toBe(false);this.active=true;this.options=options;this.starts++;}
 async emit(number:number){this.lifecycle.check();expect(this.active).toBe(true);const frames=number<2?16000:2400;
  const samples=new Int16Array(new ArrayBuffer(frames*2));for(let i=0;i<frames;i++)samples[i]=((i*17+(number+1)*101)%24001)-12000;
  const bytes=encodePcm16MonoWav(samples,pcm16WavProfile(this.options!.capabilities));
  await this.options!.onChunk({sequenceNumber:number,durationMs:frames/16,wavBytes:bytes});
  this.lifecycle.check();expect(bytes.every(b=>b===0)).toBe(true);
 }
 async stop(){if(!this.active)return;this.stops++;if(this.lifecycle.closed){this.active=false;return;}await this.emit(2);this.active=false;}
}
type Episode={lifecycle:ScribeLabEpisode;root:Root;host:HTMLDivElement;identity:AuthenticatedWorkspaceIdentity;wid:string;noteBefore:string;sourcesBefore:string;locksHeld:Set<string>;closeAlerts:string[];source:GeneratedPcmSource|null;trial?:Trial};
const trials:Trial[]=[];let mounted:Episode|undefined,terminalFailure:string|undefined;
const note=(w:Workspace)=>JSON.stringify(w.note,(_key,value)=>_key==='sources_changed'?undefined:value),sources=(w:Workspace)=>JSON.stringify(w.entries.filter(e=>['scratchpad','evidence'].includes(e.kind)));
function controls(ep:Episode){
 const act=async <T,>(callback:()=>T|Promise<T>):Promise<T>=>{ep.lifecycle.check();const result=await reactAct(callback);ep.lifecycle.check();return result;};
async function wait(check:()=>void){const until=performance.now()+15000;while(performance.now()<until){ep.lifecycle.check();let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));ep.lifecycle.check();try{check();done=true;}catch{}});if(done)return;}ep.lifecycle.check();check();}
function button(label:string){const result=[...ep.host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===label||b.textContent?.replace(/^📄\s*/u,'').trim()===label||b.getAttribute('aria-label')===label);expect(result,label).toBeTruthy();return result!;}
async function click(label:string){await wait(()=>expect(button(label).disabled,label).toBe(false));await act(async()=>button(label).click());}
async function input(selector:string,value:string){await wait(()=>expect(ep.host.querySelector(selector)).toBeTruthy());const field=ep.host.querySelector<HTMLTextAreaElement>(selector)!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function read(){ep.lifecycle.check();const w=await workspaceApi.read(ep.identity,ep.wid);ep.lifecycle.check();expect(note(w)).toBe(ep.noteBefore);expect(sources(w)).toBe(ep.sourcesBefore);return w;}
async function refresh(){await click('Refresh encounter');await wait(()=>expect(button('Refresh encounter').disabled).toBe(false));}
async function ask(content:string){await input('#team-question',content);await click('Send message');await wait(()=>expect(ep.host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toBe(''));return read();}
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
 return {act,wait,button,click,input,read,refresh,ask,workers,review};
}
beforeEach(()=>{if(!base)return;if(terminalFailure)throw new Error('Prior Scribe lab episode failed; no new case admitted: '+terminalFailure);
 const nativeAbort=transferableAbortController();vi.stubGlobal('AbortController',nativeAbort.constructor);vi.stubGlobal('AbortSignal',nativeAbort.signal.constructor);vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE',base);vi.stubEnv('VITE_CAPTURE_UPLOAD_ORIGINS',base);vi.stubGlobal('indexedDB',new IDBFactory());vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 expect(typeof AbortSignal.any).toBe('function');const a=new AbortController(),b=new AbortController(),combined=AbortSignal.any([a.signal,b.signal]);b.abort();expect(combined.aborted).toBe(true);
 const host=document.createElement('div');document.body.append(host);const ep:Episode={lifecycle:new ScribeLabEpisode(),host,root:createRoot(host),identity:{mode:'clerk_jwt',getToken:async()=>{throw new Error('Episode identity not initialized');}},wid:'',noteBefore:'',sourcesBefore:'',locksHeld:new Set(),closeAlerts:[],source:null};mounted=ep;
 generatedSource.create=()=>{ep.lifecycle.check();const source=new GeneratedPcmSource(ep.lifecycle);ep.source=source;return source;};
 vi.spyOn(window,'alert').mockImplementation(message=>{ep.closeAlerts.push(String(message));});Object.defineProperty(navigator,'locks',{configurable:true,value:{request:async(name:string,_options:LockOptions,callback:LockGrantedCallback<unknown>)=>{if(ep.locksHeld.has(name))return callback(null);ep.locksHeld.add(name);try{return await callback({name,mode:'exclusive'});}finally{ep.locksHeld.delete(name);}}} as LockManager});
 vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
 const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);if(url.origin!==base)throw new Error('Synthetic test permits only its own loopback bridge.');
 try{const r=await ep.lifecycle.fetch(realFetch,input,init);if(['POST','PUT'].includes(init?.method??''))ep.trial?.wire.push({path:url.pathname,status:r.status});return r;}catch(error){if(['POST','PUT'].includes(init?.method??''))ep.trial?.wire.push({path:url.pathname,status:null});throw error;}
 });
});
afterEach(async()=>{if(!base||!mounted)return;const ep=mounted;ep.lifecycle.close();
 try{try{await ep.lifecycle.drain(10000);}finally{
  await reactAct(async()=>ep.root.unmount());const until=performance.now()+5000;
  while(ep.locksHeld.size&&performance.now()<until)await reactAct(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});
  expect(ep.locksHeld.size,'actual recording lock released after unmount').toBe(0);expect(ep.closeAlerts).toEqual([]);
 }}
 catch(error){terminalFailure=error instanceof Error?error.message:String(error);throw error;}
 finally{ep.host.remove();mounted=undefined;generatedSource.create=null;Reflect.deleteProperty(navigator,'locks');vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();await saveReport();}
});
it.skipIf(!base).each([{persona:'physician',round:1},{persona:'nurse_practitioner',round:1},{persona:'physician_assistant',round:1},{persona:'physician',round:2},{persona:'nurse_practitioner',round:2},{persona:'physician_assistant',round:2}])('$persona round $round records generated audio, reviews it and accepts four actual specialist loops',async({persona,round})=>{
 const ep=mounted!;const {act,wait,button,click,read,ask,workers,review}=controls(ep);
 const began=performance.now(),trial:Trial={persona,round,workspace_id:'',steps:[],wire:[],passed:false};ep.trial=trial;trials.push(trial);const step=(name:string)=>{ep.lifecycle.check();trial.steps.push({name,elapsed_ms:Math.round(performance.now()-began)});};
 return ep.lifecycle.run(async()=>{try{
 const seeded=await ep.lifecycle.fetch(realFetch,`${base}/lab/case?persona=${persona}&round=${round}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(seeded.status,await seeded.clone().text()).toBe(200);
 const packet=await seeded.json() as {token:string;workspace:Workspace};ep.wid=packet.workspace.id;trial.workspace_id=ep.wid;ep.identity={mode:'clerk_jwt',getToken:async()=>packet.token};ep.noteBefore=note(packet.workspace);ep.sourcesBefore=sources(packet.workspace);const draftStorage=memoryDraftStorage();
 await act(async()=>ep.root.render(<EncounterWorkspace authenticated={ep.identity} draftStorage={draftStorage}/>));await click('Choose an encounter');
 await wait(()=>expect([...ep.host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].some(b=>b.textContent?.includes(packet.workspace.label))).toBe(true));
 await act(async()=>[...ep.host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].find(b=>b.textContent?.includes(packet.workspace.label))!.click());
 await wait(()=>expect(ep.host.querySelector('#team-notebook')).toBeTruthy());
 const scribeButton=[...ep.host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent==='Scribe')!;
 await act(async()=>scribeButton.click());await click('Record visit');
 await wait(()=>expect(ep.host.querySelector('[aria-label="Recording consent"] input')).toBeTruthy());await act(async()=>{const regions=ep.host.querySelector<HTMLInputElement>('[aria-label="Recording consent"] input')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(regions,'US-NY');regions.dispatchEvent(new Event('input',{bubbles:true}));});
 await wait(()=>expect(button('Confirm consent & record').disabled).toBe(false));
 expect(ep.host.querySelector('input[type="date"]')).toBeNull();await click('Confirm consent & record');
 await wait(()=>expect(button('Stop and upload').disabled).toBe(false));expect(ep.source?.starts).toBe(1);
 await act(async()=>{await ep.source!.emit(0);await ep.source!.emit(1);});await click('Stop and upload');
 await wait(()=>expect(ep.host.textContent).toContain('SIMULATED ASR FROM VERIFIED GENERATED AUDIO'));
 expect(ep.source?.stops).toBe(1);step('recorded_encrypted_uploaded_verified_and_simulated_asr_ready');
 await click('Continue to note');await wait(()=>expect(button('Use a Scribe recording').disabled).toBe(false));await click('Use a Scribe recording');await wait(()=>expect(ep.host.querySelector('[aria-label="Existing Scribe recording"]')?.textContent).toContain('SIMULATED ASR FROM VERIFIED GENERATED AUDIO'));
 const sourcePanel=ep.host.querySelector('[aria-label="Existing Scribe recording"]')!;const ack=sourcePanel.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
 await act(async()=>ack.click());await click('Use this version with my team');await wait(()=>expect(ep.host.textContent).toContain('Saved to this encounter’s sources'));
 let w=await workspaceApi.read(ep.identity,ep.wid);expect(note(w)).toBe(ep.noteBefore);expect(w.note?.latest?.sources_changed).toBe(true);expect(w.entries.filter(e=>e.kind==='evidence')).toHaveLength(1);ep.sourcesBefore=sources(w);step('explicit_review_and_actual_snapshot_share');
 const chief=[...ep.host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent==='Chief')!;
 await act(async()=>chief.click());await wait(()=>expect(button('Prepare team drafts').disabled).toBe(false));
 w=await ask('Ask Scribe only to organize the same recorded and reviewed transcript into a source-based private summary; keep the existing clinical note unchanged.');w=await workers();
 const scribe=w.handoffs!.find(h=>h.recipient_role==='scribe')! as ReviewableHandoff;const accepted=[await review(scribe,`${persona}: confirm missing DOB and owner without inventing facts.`)];step('scribe_summary_revision_and_acceptance');
 const chiefAgain=[...ep.host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent==='Chief')!;await act(async()=>chiefAgain.click());
 w=await ask(`For this invented ${persona} encounter, ask Research, Visit Prep and Follow-up to prepare independent private drafts from the recorded, reviewed Scribe transcript and Scribe’s accepted saved summary. Preserve unknown diagnosis, missing DOB and trial eligibility. Do not search publicly or send anything.`);
 expect(w.handoffs).toHaveLength(5);expect(new Set(w.handoffs!.filter(h=>h.recipient_role!=='scribe').map(h=>h.recipient_role))).toEqual(new Set(['research','visit_prep','follow_up']));step('chief_three_exact_assignments_saved');
 w=await workers();const first=w.handoffs!.filter(h=>h.recipient_role!=='scribe') as ReviewableHandoff[];expect(first.every(h=>h.status==='completed')).toBe(true);step('three_parallel_product_workers_completed');
 for(const h of first){accepted.push(await review(h,`${persona}: identify owner and due date for ${h.recipient_role}; preserve unknown trial eligibility.`));step(h.recipient_role+'_revision_and_acceptance');}
 await act(async()=>chiefAgain.click());w=await ask('Collect the revised saved work from all four specialists. Identify the exact saved draft versions and what a human must still do. Do not create more assignments.');expect(w.handoffs).toHaveLength(8);step('chief_reads_saved_teammate_drafts');
 for(const h of accepted){expect(w.entries.at(-1)?.reply?.content).toContain(h.result_entry_id!);expect(w.entries.at(-1)?.reply?.content).toContain(h.result_sha256!);}expect(w.entries.at(-1)?.reply?.content).toContain('A human must confirm owner, due date and trial eligibility');
 const r=await ep.lifecycle.fetch(realFetch,`${base}/lab/inspect?workspace_id=${ep.wid}`,{cache:'no-store',credentials:'omit',redirect:'error'});expect(r.status).toBe(200);const evidence=await r.json() as {admissions:{state:string;role:string}[];tool_receipts:{actor_id:string;human_id:string;detail:Record<string,unknown>}[];dispatches:{started_s:number;ended_s:number;role:string}[];capture:{complete:boolean;session_id:string;uploads:{sequence_number:number;frames:number}[];real_asr_tested:boolean;physical_microphone_tested:boolean}};
 expect(evidence.admissions).toHaveLength(11);expect(evidence.admissions.every(a=>a.state==='completed')).toBe(true);expect(evidence.tool_receipts).toHaveLength(15);expect(evidence.tool_receipts.every(r=>r.actor_id!==r.human_id)).toBe(true);
 expect(evidence.capture).toMatchObject({complete:true,real_asr_tested:false,physical_microphone_tested:false});expect(evidence.capture.uploads.map(p=>[p.sequence_number,p.frames])).toEqual([[0,16000],[1,16000],[2,2400]]);expect(trial.wire.filter(p=>p.path.startsWith('/lab/audio/')&&p.status===201)).toHaveLength(3);
 const parallel=evidence.dispatches.filter(d=>['research','visit_prep','follow_up'].includes(d.role)).slice(0,3);expect(Math.max(...parallel.map(d=>d.started_s))).toBeLessThan(Math.min(...parallel.map(d=>d.ended_s)));
 const reread=await read();for(const h of accepted)expect((reread.handoffs!.find(x=>x.id===h.id) as ReviewableHandoff).review).toMatchObject(h.review!);expect(trial.wire.every(x=>x.status===200||x.status===201||x.path.endsWith('/capture/admission')&&x.status===409)).toBe(true);step('fresh_read_exact_acceptance_and_custody');const captureRequests=trial.wire.filter(x=>x.path.includes('/capture/')||x.path.startsWith('/lab/audio/')).length;await act(async()=>ep.root.unmount());await wait(()=>expect(ep.locksHeld.size).toBe(0));expect(ep.closeAlerts).toEqual([]);ep.root=createRoot(ep.host);await act(async()=>ep.root.render(<EncounterWorkspace authenticated={ep.identity} draftStorage={draftStorage}/>));await click('Choose an encounter');await wait(()=>expect([...ep.host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].some(b=>b.textContent?.includes(packet.workspace.label))).toBe(true));await act(async()=>[...ep.host.querySelectorAll<HTMLButtonElement>('.team-encounter-option')].find(b=>b.textContent?.includes(packet.workspace.label))!.click());await wait(()=>expect(ep.host.querySelector('#team-notebook')).toBeTruthy());const reopened=await read();for(const h of accepted)expect((reopened.handoffs!.find(x=>x.id===h.id) as ReviewableHandoff).review).toMatchObject(h.review!);expect(trial.wire.filter(x=>x.path.includes('/capture/')||x.path.startsWith('/lab/audio/'))).toHaveLength(captureRequests);expect(ep.source).toMatchObject({starts:1,stops:1});step('reopened_product_ui_without_rerecording_or_duplicate_effect');
  const reviewRequests=trial.wire.filter(x=>x.path.endsWith('/review')||x.path.endsWith('/revision')).length;
  for(const h of accepted){const teammate=[...ep.host.querySelectorAll<HTMLButtonElement>('[aria-label="Provider Team"] button')].find(b=>b.querySelector('strong')?.textContent===h.recipient_name)!;
    expect(teammate).toBeTruthy();await act(async()=>teammate.click());
    await wait(()=>expect(ep.host.querySelector(`#turn-${h.result_entry_id} .team-bot-message header`)?.textContent).toContain('Draft accepted'));
    expect(ep.host.querySelector(`#turn-${h.result_entry_id} .team-bot-message header`)?.textContent).not.toContain('Unreviewed draft');
  }
  expect(trial.wire.filter(x=>x.path.endsWith('/review')||x.path.endsWith('/revision'))).toHaveLength(reviewRequests);
  step('reopened_each_specialist_conversation_shows_exact_saved_human_acceptance');trial.passed=true;
 }catch(e){trial.failure=(e instanceof Error?e.message:String(e))+'\nDOM: '+ep.host.textContent;terminalFailure=trial.failure.split('\n')[0];throw e;}},55000).catch(error=>{if(!trial.failure)trial.failure=(error instanceof Error?error.message:String(error))+'\nDOM: '+ep.host.textContent;terminalFailure=trial.failure.split('\n')[0];throw error;});
},60000);
async function saveReport(){if(!base||!environment?.COSMAS_SCRIBE_LAB_REPORT)return;const fs='node:fs/promises';const {writeFile}=await import(/* @vite-ignore */fs) as {writeFile:(p:string,s:string)=>Promise<void>};await writeFile(environment.COSMAS_SCRIBE_LAB_REPORT,JSON.stringify({schema:'cosmabot.scribe-to-specialists-signed-product-ui.v1',synthetic_only:true,source_adapter:'actual recording controller/queue/transport and v6 with offline MockTransport',hardware:'deterministic generated PCM only',speech_recognition:'simulated only after independently verified capture completes',personas_are_scripted_not_real_users:true,trials,total:trials.length,completed:trials.filter(t=>t.passed).length},null,2)+'\n');}
afterAll(saveReport);
