import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_EHR_READ_ENABLED','true');});
import {AthenaMedicationMount} from './AthenaMedicationMount';
import {athenaMedicationApi,type AthenaMedicationCoreReceipt} from './athena-medication-api';
import golden from './__fixtures__/athena-medication-source.json';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {createHandoffReviewTestRecovery} from './handoff-review-test-recovery';
import {WorkspaceSession} from './session/workspace-session';
import {useWorkspaceSession} from './session/use-workspace-session';
import type {ConversationHost} from './session/conversations';
import type {SourceContext} from './session/sources';
import {workspaceApi,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace} from './workspace-api';
import {editorAddress} from './draft-journal';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const moduleName='node:util';
const {transferableAbortController}=await import(/* @vite-ignore */moduleName) as {transferableAbortController:()=>AbortController};
const env=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const configured=env?.COSMAS_ATHENA_MEDICATION_UI_LAB_URL;
const base=configured?new URL(configured):null;
if(base&&(base.protocol!=='http:'||base.hostname!=='127.0.0.1'||base.pathname!=='/'||base.username||base.password||base.search||base.hash))throw new Error('Athena medication UI lab must use owned loopback.');
const realFetch=globalThis.fetch.bind(globalThis);
let root:Root|undefined,host:HTMLDivElement,recovery:EditorRecoveryAccess|undefined;
const pending=new Set<Promise<Response>>(),abortCleanup:(()=>void)[]=[];
afterEach(async()=>{if(root){await act(async()=>root!.unmount());root=undefined;}await Promise.allSettled([...pending]);recovery?.journal.close();for(const close of abortCleanup.splice(0))close();host?.remove();vi.unstubAllGlobals();});
it.skipIf(!base)('restores an exact clinical read after reload and preserves Chief directions through actual signed custody and grant withdrawal',async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE',base!.origin);
 vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 let dropped=false,savedMedication:AthenaMedicationCoreReceipt|undefined;const wire:{path:string;action?:string;key?:string;provider?:string;protocol?:string;clinical_scope?:string}[]=[];
 vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
  const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url);if(url.origin!==base!.origin)throw new Error('External request rejected by synthetic Athena lab.');
  let options=init;if(init?.signal){const c=transferableAbortController(),signal=init.signal,abort=()=>c.abort();signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();abortCleanup.push(()=>signal.removeEventListener('abort',abort));options={...init,signal:c.signal};}
  const body=init?.method==='POST'?JSON.parse(String(init.body)) as {action?:string;idempotency_key?:string;provider?:string;protocol?:string;clinical_scope?:string}:null;
  wire.push({path:url.pathname,action:body?.action,key:body?.idempotency_key,provider:body?.provider,protocol:body?.protocol,clinical_scope:body?.clinical_scope});
  const request=realFetch(input,options);pending.add(request);
  try{const response=await request;if(body?.action==='core_medications'&&!dropped&&response.ok){savedMedication=await response.json() as AthenaMedicationCoreReceipt;dropped=true;throw new Error('Invented lost success response');}return response;}finally{pending.delete(request);}
 });
 const packet=await (await realFetch(base!.origin+'/lab/state')).json() as {workspace:Workspace;team:ProviderTeam;token:string;patient_name:string};
 const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>packet.token};
 const session=new WorkspaceSession();session.setIdentity(identity);session.setWorkspace(packet.workspace);session.setTeam(packet.team);session.setSelected('chief');session.setPracticePage('notebook');session.models.updateThought('Keep my existing Chief directions.');
 const access=await createHandoffReviewTestRecovery(packet.workspace.id,()=>workspaceApi.read(identity,packet.workspace.id),webcrypto);
 access.recoveryScope=packet.team.recovery_scope;recovery=access;
 session.recovery.journal.current={scope:'e'.repeat(64),serverScope:packet.team.recovery_scope!,value:access.journal};
 access.authorize=session.recovery.editorAccess(identity,packet.team.recovery_scope!,access.journal,packet.workspace.id,true,false,()=>{})!.authorize;
 const failures:unknown[]=[];
 const conversation:ConversationHost={identity,journal:access.journal,scope:'e'.repeat(64),current:()=>true,blocked:()=>session.getSnapshot().busy,
  authorize:async()=>{expect((await workspaceApi.team(identity)).recovery_scope).toBe(packet.team.recovery_scope);},failure:e=>failures.push(e),navigate:async()=>{throw new Error('This test retains the current Chief conversation.');}};
 const sourceContext:SourceContext={authenticated:identity,locked:false,connectionNavigationLocked:false,captureNavigationLocked:false,captureDraftLocked:false,connectionEditorsLocked:false,activityBusy:false,accessBusy:false,scribeSourceBusy:false,schedulingPatientBusy:false,accountAccess:null,conversationHost:conversation,failure:e=>failures.push(e),focusQuestion:()=>{}};
 function Harness(){const view=useWorkspaceSession(session),w=view.workspace!;return <><EditorRecoveryContext.Provider value={access}><AthenaMedicationMount identity={identity} workspace={{id:w.id,label:w.label,revision:w.revision}}
  currentSources={w.entries.filter(e=>e.kind==='ehr_read_source'&&!!e.ehr_source_state).map(e=>({id:e.id,state:e.ehr_source_state!}))}
  onAuthenticationLost={e=>failures.push(e)} onAskChief={saved=>void session.sources.prepareEhr(sourceContext,saved)}/></EditorRecoveryContext.Provider><textarea aria-label="Chief directions" readOnly value={view.thought}/></>;}
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root!.render(<Harness/>));
 const find=(name:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===name);
 const wait=async(check:()=>void)=>{for(let n=0;n<750;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,20));try{check();done=true;}catch{/* Wait for the mounted control. */}});if(done)return;}try{check();}catch(cause){throw new Error(String(cause)+'\nSynthetic UI: '+host.textContent?.slice(0,2500)+'\nWire: '+JSON.stringify(wire)+'\nFailures: '+String(failures));}};
 const click=async(name:string)=>{await wait(()=>expect(find(name)?.disabled,name).toBe(false));await act(async()=>find(name)!.click());};
 await click('Check Athena medication access');await click('Load authorized patients');
 await wait(()=>expect(host.querySelectorAll('[aria-label="Authorized clinical patients"] button')).toHaveLength(1));
 expect((await (await realFetch(base!.origin+'/lab/counts')).json()).provider_calls).toBe(0);
 await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="Authorized clinical patients"] button')!.click());
 await wait(()=>expect(host.querySelector('[aria-label="Selected clinical patient"]')?.textContent).toContain(packet.patient_name));
 expect((host.querySelector('[aria-label="Chief directions"]') as HTMLTextAreaElement).value).toBe('Keep my existing Chief directions.');
 await click('Read medication records');await wait(()=>expect(find('Check saved medication-record result')?.disabled).toBe(false));
 const read=wire.find(row=>row.action==='core_medications')!;expect(read.key).toBeTruthy();
 expect((await (await realFetch(base!.origin+'/lab/counts')).json()).provider_calls).toBe(2);
 // Reload the task with the existing private journal. Merely mounting/restoring may not resend a read.
 const beforeReload=wire.filter(row=>row.path==='/connections/ehr/reads').length;
 await act(async()=>root!.unmount());root=createRoot(host);await act(async()=>root!.render(<Harness/>));
 await click('Restore saved Athena medication work');
 expect(wire.filter(row=>row.path==='/connections/ehr/reads')).toHaveLength(beforeReload);
 expect(host.querySelector('[aria-label="Review Athena medication records"]')).toBeNull();
 const headers={Authorization:'Bearer '+packet.token,'Content-Type':'application/json','X-Cosmas-Ehr-Read':'1'};
 for(const wrong of [{provider:'athena',protocol:'core'},{provider:'athena',protocol:'core',clinical_scope:null},{provider:'athena',protocol:'core',clinical_scope:'allergies'},{provider:'tebra',protocol:'core',clinical_scope:'medications'},{provider:'athena',protocol:'fhir',clinical_scope:'medications'}]){
  const rejected=await realFetch(base!.origin+'/connections/ehr/reads',{method:'POST',headers,body:JSON.stringify({action:'resolve',idempotency_key:read.key,...wrong})});
  expect([403,404,409,422]).toContain(rejected.status);expect(await rejected.text()).not.toContain(packet.patient_name);
 }
 await click('Check Athena medication access');await click('Check saved medication-record result');
 await wait(()=>expect(host.querySelector('[aria-label="Review Athena medication records"]')?.textContent).toContain(packet.patient_name));
 const details=host.querySelector<HTMLDetailsElement>('[aria-label="Review Athena medication records"] details')!;
 expect(details).toBeTruthy();expect(find('Save reviewed medication records')?.disabled).toBe(true);
 expect(host.querySelectorAll('input[type="checkbox"]')).toHaveLength(3);
 const original=details.querySelector('pre')!.textContent!;
 expect(original).toContain('Athena: recorded medication entries');expect(original).toContain('Complete original medication section JSON:');
 expect(original).toContain(golden.section_json);expect(original).toContain('No medications reported statement:');
 for(const exact of ['\"quantity\":0.50','\"tiny\":1e-7','\"signedzero\":-0','9223372036854775807'])expect(original).toContain(exact);
 expect(original).not.toContain('patientid');expect(original).not.toContain('departmentid');
 await act(async()=>{await new Promise<void>(resolve=>{details.addEventListener('toggle',()=>resolve(),{once:true});details.open=true;});});
 for(const checkbox of host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))await act(async()=>checkbox.click());
 await click('Save reviewed medication records');await click('Prepare Chief draft');
 await wait(()=>expect(session.getSnapshot().thought).toContain('Keep my existing Chief directions.\n\nReview'));
 expect(session.getSnapshot().selectedSource).toBeTruthy();
 const current=await workspaceApi.read(identity,packet.workspace.id);
 expect(current.entries.find(e=>e.id===session.getSnapshot().selectedSource)?.content).toBe(original);
 const draft=await access.journal.load(editorAddress(packet.workspace.id,'conversation:chief'));
 expect(draft).toMatchObject({data:{text:session.getSnapshot().thought}});
 const counts=await (await realFetch(base!.origin+'/lab/counts')).json() as {provider_calls:number;model_admissions:number};
 expect(counts.provider_calls).toBe(2);expect(wire.filter(row=>row.action==='core_patients')).toHaveLength(1);expect(wire.filter(row=>row.action==='core_medications')).toHaveLength(1);
 expect(wire.find(row=>row.action==='resolve')?.key).toBe(read.key);
 expect(wire.some(row=>/ask|model-work/.test(row.path))).toBe(false);
 await realFetch(base!.origin+'/lab/revoke',{method:'POST',body:'{}'});
 expect(savedMedication?.observation.kind).toBe('core_medications');
 await expect(athenaMedicationApi.inspect(identity,savedMedication!)).rejects.toMatchObject({status:409,code:'ehr_read_core_medication_grant_changed'});
 expect(wire.filter(row=>row.action==='inspect')).toHaveLength(1);
 expect(wire.filter(row=>row.path==='/connections/ehr/reads'||row.path.endsWith('/ehr-read/review')).every(row=>row.provider==='athena'&&row.protocol==='core'&&row.clinical_scope==='medications')).toBe(true);
 const revoked=await workspaceApi.read(identity,packet.workspace.id);
 const entry=revoked.entries.find(e=>e.id===session.getSnapshot().selectedSource)!;
 expect(entry.ehr_source_state).toBe('unavailable');expect(entry.content).toBe('');
 await act(async()=>session.sources.receive(revoked));
 expect(find('Prepare Chief draft')?.disabled).toBe(true);
 expect(session.getSnapshot().thought).toContain('Keep my existing Chief directions.');
 expect(failures).toEqual([]);
 const finalCounts=await (await realFetch(base!.origin+'/lab/counts')).json();expect(finalCounts).toEqual(counts);
 const fsName='node:fs/promises';const fs=await import(/* @vite-ignore */fsName) as {writeFile:(path:string,value:string)=>Promise<void>};
 await fs.writeFile(env!.COSMAS_ATHENA_MEDICATION_UI_LAB_REPORT!,JSON.stringify({passed:true,screenshots:0,...counts,lossless_clinical_section:true,explicit_medication_scope:true,withdrawn_grant_code_preserved:true,lost_response_recovered:true,wrong_protocol_withheld:true,reload_did_not_resend:true,draft_preserved:true,revoked_source_withheld:true,wire},null,2));
},90000);
