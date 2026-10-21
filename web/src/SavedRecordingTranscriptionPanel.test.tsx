import {act,useEffect,useState,useLayoutEffect,StrictMode} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {SavedRecordingTranscriptionPanel,parseVisitTranscriptionIntent,visitTranscriptionIntentHash,type SavedRecordingEntry,type RecordingTranscriptionGesture} from './SavedRecordingTranscriptionPanel';
import {prepareCapture} from './capture-api';
import {BffResponseError} from '../../clients/capture/src/bff/http-client';
import {workspaceApi,type ProviderTeam,type Workspace} from './workspace-api';
import {RecordingVisitPanel} from './RecordingVisitPanel';
import type {RecordingVisitBinding} from './private-recording-api';
const mocks=vi.hoisted(()=>({read:vi.fn(),write:vi.fn(),close:vi.fn(),ledger:vi.fn(),runtimeClose:vi.fn(),open:vi.fn(),savedRuntime:vi.fn(),bindVisit:vi.fn(),continueReview:null as null|(()=>Promise<void>),review:null as unknown,availability:null as 'loading'|'ready'|'unavailable'|null,privateBegin:vi.fn(),privateAppend:vi.fn(),privateFinish:vi.fn(),privateCancel:vi.fn()}));
vi.mock('./CreatorReviewPanel',()=>({CreatorReviewPanel:({onSource,onAvailability,onContinue}:{onSource:(view:unknown)=>void;onAvailability?:(v:'loading'|'ready'|'unavailable')=>void;onContinue:()=>Promise<void>})=>{mocks.continueReview=onContinue;useEffect(()=>{onAvailability?.(mocks.availability??(mocks.review?'ready':'loading'));onSource(mocks.review);},[onSource,onAvailability,mocks.availability,mocks.review]);return null;}}));
vi.mock('./private-transcription-native',async original=>({...await original<typeof import('./private-transcription-native')>(),privateSpeechNative:{begin:mocks.privateBegin,append:mocks.privateAppend,finish:mocks.privateFinish,cancel:mocks.privateCancel}}));
vi.mock('./saved-recording-runtime',()=>({openSavedRecordingRuntime:mocks.savedRuntime}));
vi.mock('./private-recording-runtime',()=>({openPrivateRecordingStore:async()=>({read:mocks.read,write:mocks.write,close:mocks.close}),PrivateRecordingRuntime:{open:mocks.open}}));
vi.mock('./private-recording-ledger',()=>({PrivateRecordingLedgerController:class{readCurrent=mocks.ledger;}}));
vi.mock('./private-recording-api',()=>({parsePrivateRecordingReceipt:async()=>{},parseRecordingVisitBinding:async()=>{},privateRecordingApi:{read:async()=>activeReceipt,readVisitBinding:async()=>activeBinding,bindVisit:mocks.bindVisit}}));
vi.mock('./capture-api',()=>({prepareCapture:vi.fn()}));
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
const workspace:Workspace={id:id(1),appointment_id:id(2),label:'Invented visit',revision:1,entries:[],work_candidates:[],private_draft:{title:'Visit',state:'linked',link_receipt_id:id(9),linked_at:'2026-10-09T12:00:00Z'}};
const receipt={local_recording_id:id(3),recording_id:id(4),workspace_id:id(1),state:'linked_metadata',link:{receipt_id:id(5),source_sha256:'a'.repeat(64),workspace_link_receipt_id:id(9)},finish:{manifest_sha256:'b'.repeat(64),chunks:1,frames:1}};
const admission={key:id(6),language:'en-US',attestation:{modality:'in_person',participant_regions:[],method:'verbal_attestation',all_parties_consented:true,granted_at:'2026-10-09T12:00:00Z'},source:{recording_id:id(4),link_receipt_id:id(5),source_sha256:'a'.repeat(64),manifest_sha256:'b'.repeat(64),chunks:1,frames:1}};
let root:Root,host:HTMLDivElement,stored:unknown,activeReceipt:unknown,activeBinding:RecordingVisitBinding|null;
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const back=vi.fn(),navigation=vi.fn();
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();vi.stubGlobal('crypto',webcrypto);mocks.review=null;mocks.availability=null;mocks.continueReview=null;activeReceipt=receipt;activeBinding=null;
  HTMLElement.prototype.scrollIntoView=vi.fn();
  stored={contract:'cosmas.saved-transfer.v1',recording_id:id(3),workspace_id:id(1),scope:'c'.repeat(64),link_request:null,receipt,admission:structuredClone(admission),admitted:null};
  mocks.read.mockImplementation(async()=>structuredClone(stored));
  mocks.write.mockImplementation(async(_key,_before,next)=>{stored=structuredClone(next);});
  mocks.ledger.mockResolvedValue({state:'finished',attach:{},receipt,finish:{}});
  mocks.open.mockResolvedValue({snapshot:{workspaceId:id(1),phase:'sealed',recordedChunks:1,elapsedSeconds:19},close:mocks.runtimeClose,
    snapshotForLedger:async()=>({phase:'sealed',manifestSHA256:'b'.repeat(64),chunks:1,frames:1}),
    savedChunks:async function*(){const wavBytes=new Uint8Array(46);wavBytes[44]=1;yield{wavBytes};}});
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
const button=(name:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===name);
async function mount(processing=false){await act(async()=>root.render(<SavedRecordingTranscriptionPanel entry={{recordingId:id(3),scope:'c'.repeat(64),platform:'desktop'}} identity={identity} workspace={workspace} team={{revision:1} as ProviderTeam}
  isCurrent={()=>true} locked={false} notesEnabled={false} onDraftLock={()=>{}} onReviewDraft={()=>{}} onCurrentDraft={()=>{}} notebookDirty={false} onNotebook={()=>{}}
  onRecordings={back} onNavigationLock={navigation} taskBot={{selection:{address:'scribe',team_revision:1},name:'Scribe',enabled:true,includeNotebook:false}}/>));
  await vi.waitFor(()=>expect(processing?host.textContent?.includes('Review your transcript'):button('Continue transcription')?.disabled===false).toBe(true));}
it.each(['capture_request_conflict','capture_consent_required','capture_consent_unavailable'])('retains exact intent and offers recordings rather than futile retry for %s',async code=>{
  const original=structuredClone(stored);
  vi.mocked(prepareCapture).mockRejectedValue(new BffResponseError(409,code,null));
  await mount();await act(async()=>button('Continue transcription')!.click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('Your audio is saved');
  expect(button('Continue transcription')).toBeUndefined();expect(host.textContent).toContain(code);
  expect(stored).toEqual(original);expect(prepareCapture).toHaveBeenCalledOnce();
  await act(async()=>button('Return to recordings')!.click());expect(back).toHaveBeenCalledOnce();
  expect(navigation.mock.calls.some(call=>call[0]===true)).toBe(true);expect(navigation.mock.calls.at(-1)).toEqual([false]);
});
it('keeps the exact retry for an uncertain response without exposing private error text',async()=>{
  vi.mocked(prepareCapture).mockRejectedValue(new BffResponseError(503,'private-response-must-not-appear',null));
  await mount();await act(async()=>button('Continue transcription')!.click());
  expect(button('Continue transcription')?.disabled).toBe(false);expect(host.textContent).not.toContain('private-response-must-not-appear');
  await act(async()=>button('Continue transcription')!.click());
  expect(vi.mocked(prepareCapture).mock.calls[0]).toEqual(vi.mocked(prepareCapture).mock.calls[1]);
});

it('distinguishes prepared audio from confirmed upload and shows only the support reference',async()=>{
  (stored as {admitted:unknown}).admitted={status:'prepared',workspace_id:id(1),session_id:id(7),consent_record_id:id(8),configured_capture:{schema_version:'1.0',language_mode:'en-US'}};
  const snapshot={state:'uploading',recordedChunks:1};
  mocks.savedRuntime.mockResolvedValue({controller:{snapshot,subscribe:(listener:(value:unknown)=>void)=>{listener(snapshot);return()=>{};}},
    transcribe:vi.fn().mockRejectedValue(new Error('private error content')),
    uploadProgress:async()=>({confirmed:0,total:1,reference:'chunk_receipt_response_503'}),close:async()=>{}});
  await mount();expect(host.textContent).toContain('Your saved audio is ready. Choose Continue transcription');
  await act(async()=>button('Continue transcription')!.click());
  expect(host.textContent).toContain('0 of 1 audio parts confirmed by Scribe');
  expect(host.textContent).toContain('chunk_receipt_response_503');
  expect(host.textContent).not.toContain('private error content');
  expect(button('Continue transcription')?.disabled).toBe(false);
});

it('shows a finished transcription failure and a route back to the preserved recording',async()=>{
  const original=structuredClone(stored);
  (stored as {admitted:unknown}).admitted={status:'prepared',workspace_id:id(1),session_id:id(7),consent_record_id:id(8),configured_capture:{schema_version:'1.0',language_mode:'en-US'}};
  mocks.review={status:'speech_failed',source:null,working:null};
  const snapshot={state:'processing',recordedChunks:1};
  mocks.savedRuntime.mockResolvedValue({controller:{snapshot,subscribe:(listener:(value:unknown)=>void)=>{listener(snapshot);return()=>{};}},close:async()=>{}});
  await mount(true);
  expect(host.textContent).toContain('Scribe could not finish transcription. Your audio is saved');
  expect(host.textContent).not.toContain('Scribe is preparing your transcript');
  expect(button('Continue transcription')).toBeUndefined();
  await act(async()=>button('Return to recordings')!.click());expect(back).toHaveBeenCalledOnce();
  expect(mocks.write).not.toHaveBeenCalled();
  expect((stored as {admission:unknown}).admission).toEqual((original as {admission:unknown}).admission);
});

it('requires fresh explicit consent only after a definite no-admission result and retains earlier intent across reopen',async()=>{
  const original=structuredClone(admission);
  vi.mocked(prepareCapture).mockRejectedValueOnce(new BffResponseError(409,'capture_recording_consent_required',null)).mockRejectedValue(new BffResponseError(503,'unconfirmed',null));
  await mount();await act(async()=>button('Continue transcription')!.click());
  const send=button('Send recording with confirmed consent');expect(send?.disabled).toBe(true);
  expect(host.textContent).toContain('expired before Scribe accepted');
  await act(async()=>(host.querySelector('input[type="checkbox"]') as HTMLInputElement).click());
  expect(send?.disabled).toBe(false);await act(async()=>send!.click());
  const retained=stored as {contract:string;admission:typeof admission;prior_admissions:typeof admission[];renew_saved_consent:boolean};
  expect(retained.contract).toBe('cosmas.saved-transfer.v3');expect(retained.prior_admissions).toEqual([original]);
  expect(retained.admission.source).toEqual(original.source);expect(retained.admission.key).not.toBe(original.key);
  expect(retained.renew_saved_consent).toBe(true);expect(vi.mocked(prepareCapture).mock.calls[1][8]).toBe(true);
  await act(async()=>root.unmount());root=createRoot(host);await mount();
  await act(async()=>button('Continue transcription')!.click());
  expect(vi.mocked(prepareCapture).mock.calls[2]).toEqual(vi.mocked(prepareCapture).mock.calls[1]);
  expect((stored as typeof retained).prior_admissions).toEqual([original]);
});


async function waitFor(assert:()=>unknown){const deadline=performance.now()+1500;let failure:unknown;while(performance.now()<deadline){await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});try{assert();return;}catch(error){failure=error;}}throw failure;}
async function combined(){
  const origin={...workspace,id:id(10),appointment_id:null,label:'Original invented private notebook'};
  const source={...receipt,workspace_id:origin.id,owner_id:id(11),box_id:id(12),recovery_scope:'d'.repeat(64),state:'finished',link:null,
    finish:{...receipt.finish,request_sha256:'f'.repeat(64)}};
  const audioConsent={...admission.attestation,language:'en-US'};
  const request={idempotency_key:id(13),target_workspace_id:workspace.id,appointment_id:workspace.appointment_id!,expected_target_revision:workspace.revision,visit_confirmed:true as const};
  const requestHash=await visitTranscriptionIntentHash({contract:'cosmas.private-recording.visit-binding.v1',request});
  const binding:RecordingVisitBinding={contract:'cosmas.private-recording.visit-binding.v1',receipt_id:id(14),recording_id:id(4),origin_workspace_id:origin.id,target_workspace_id:workspace.id,
    appointment_id:workspace.appointment_id!,request,request_sha256:requestHash,appointment_sha256:'e'.repeat(64),source_sha256:'a'.repeat(64)};
  const intent=await parseVisitTranscriptionIntent({contract:'cosmas.visit-transcription.intent.v1',scope:'c'.repeat(64),owner_id:source.owner_id,box_id:source.box_id,recovery_scope:source.recovery_scope,
    recording_id:id(4),local_recording_id:id(3),origin_workspace_id:origin.id,request,request_sha256:requestHash,finish_request_sha256:source.finish.request_sha256,
    manifest_sha256:'b'.repeat(64),chunks:1,frames:1,audio_consent_sha256:await visitTranscriptionIntentHash(audioConsent),admission:{key:id(15),attestation:structuredClone(admission.attestation),language:'en-US',bot:{address:'scribe',team_revision:1}}});
  let claimed=false;const claim=vi.fn(()=>{if(claimed)return false;claimed=true;return true;});
  const gesture:RecordingTranscriptionGesture={identity,recordingId:id(3),scope:'c'.repeat(64),intent_sha256:await visitTranscriptionIntentHash(intent),claim};
  const entry:SavedRecordingEntry={recordingId:id(3),scope:'c'.repeat(64),platform:'desktop',originWorkspace:origin,binding,transcriptionGesture:gesture};
  const team={revision:1,recovery_scope:source.recovery_scope,configuration:{practice_context:'Invented',bots:[{role:'scribe',name:'Scribe',enabled:true,response_style:'brief',include_notebook:false,include_evidence:false}]}} as ProviderTeam;
  activeReceipt=source;activeBinding=binding;stored=null;
  mocks.read.mockImplementation(async key=>key==='visit-binding:'+id(3)?structuredClone(intent):structuredClone(stored));
  mocks.ledger.mockResolvedValue({state:'finished',attach:{},receipt:source,finish:{}});
  const recording={snapshot:{workspaceId:origin.id,phase:'sealed',recordedChunks:1,elapsedSeconds:19,title:'Invented combined test clip'},close:mocks.runtimeClose,
    snapshotForLedger:async()=>({recordingId:id(3),phase:'sealed',manifestSHA256:'b'.repeat(64),chunks:1,frames:1,consent:audioConsent,startedAt:'2026-10-20T12:00:00Z'}),
    savedChunks:async function*(){const wavBytes=new Uint8Array(46);wavBytes[44]=1;yield{wavBytes};}};
  mocks.open.mockResolvedValue(recording);
  const transcribe=vi.fn(async()=>{}),snapshot={state:'uploading',recordedChunks:1};
  mocks.savedRuntime.mockResolvedValue({controller:{snapshot,subscribe:(listener:(value:unknown)=>void)=>{listener(snapshot);return()=>{};}},transcribe,
    uploadProgress:async()=>({confirmed:0,total:1,reference:null}),close:async()=>{}});
  vi.mocked(prepareCapture).mockResolvedValue({status:'prepared',workspace_id:workspace.id,session_id:id(16),consent_record_id:id(17),configured_capture:{schema_version:'1.0',language_mode:'en-US'}});
  async function render(options:{entry?:SavedRecordingEntry;workspace?:Workspace;identity?:typeof identity;locked?:boolean;strict?:boolean;current?:()=>boolean;team?:ProviderTeam;onCommit?:()=>void;taskBot?:{selection:{address:string;team_revision:number};name:string;enabled:boolean;includeNotebook:boolean}}={}){
    const panel=<SavedRecordingTranscriptionPanel entry={options.entry??entry} identity={options.identity??identity} workspace={options.workspace??workspace} team={options.team??team}
      isCurrent={options.current??(()=>true)} locked={options.locked??false} notesEnabled={false} onDraftLock={()=>{}} onReviewDraft={()=>{}} onCurrentDraft={()=>{}} notebookDirty={false} onNotebook={()=>{}}
      taskBot={options.taskBot??{selection:{address:'scribe',team_revision:1},name:'Scribe',enabled:true,includeNotebook:false}}/>;
    const observed=<>{panel}<CommitProbe capture={options.onCommit}/></>;
    await act(async()=>root.render(options.strict?<StrictMode>{observed}</StrictMode>:observed));
  }
  return {entry,intent,binding,source,recording,render,claim,transcribe,origin,team};
}
function CommitProbe({capture}:{capture?:()=>void}){useLayoutEffect(()=>{capture?.();});return null;}
it.each(['identity','scope','recording','authority'] as const)('the first committed %s replacement cannot display the previous saved recording or Scribe session',async change=>{
 const c=await combined();const snapshot={state:'processing',recordedChunks:1};mocks.savedRuntime.mockResolvedValue({controller:{snapshot,subscribe:(listener:(value:unknown)=>void)=>{listener(snapshot);return()=>{};}},transcribe:c.transcribe,close:async()=>{}});
 await c.render();await waitFor(()=>expect(host.textContent).toContain('Invented combined test clip'));const commits:string[]=[];const onCommit=()=>commits.push(host.innerHTML);
 mocks.open.mockImplementation(()=>new Promise(()=>{}));
 if(change==='identity')await c.render({identity:{...identity},onCommit});
 if(change==='scope')await c.render({entry:{...c.entry,scope:'f'.repeat(64)},onCommit});
 if(change==='recording')await c.render({entry:{...c.entry,recordingId:id(99)},onCommit});
 if(change==='authority')await c.render({workspace:{...workspace,revision:workspace.revision+1},onCommit});
 expect(commits[0]).toContain('Opening saved recording');expect(commits[0]).not.toContain('Invented combined test clip');expect(commits[0]).not.toContain('Scribe transcript review');expect(commits[0]).not.toContain('2026-10-20T12:00:00Z');
 expect(c.transcribe).toHaveBeenCalledOnce();expect(prepareCapture).toHaveBeenCalledOnce();
});
it('one combined gesture starts existing admission/upload without another consent or send action',async()=>{
  const c=await combined();await c.render();await waitFor(()=>expect(c.transcribe).toHaveBeenCalledOnce());
  expect(prepareCapture).toHaveBeenCalledOnce();expect(c.claim).toHaveBeenCalledOnce();
  const call=vi.mocked(prepareCapture).mock.calls[0];expect(call[2]).toEqual(c.intent.admission.attestation);expect(call[3]).toBe(c.intent.admission.key);
  expect(call[7]).toMatchObject({recording_id:c.source.recording_id,origin_workspace_id:c.source.workspace_id,visit_binding_receipt_id:c.binding.receipt_id,source_sha256:c.binding.source_sha256});
  const admissionWrite=mocks.write.mock.calls.findIndex(call=>(call[2] as {admission?:unknown}).admission!==null);
  expect(mocks.write.mock.invocationCallOrder[admissionWrite]).toBeLessThan(vi.mocked(prepareCapture).mock.invocationCallOrder[0]);
  expect((stored as {admission:{key:string}}).admission.key).toBe(c.intent.admission.key);
});
it('StrictMode repeated setup still performs one exact automatic continuation',async()=>{
  const c=await combined();await c.render({strict:true});await waitFor(()=>expect(c.transcribe).toHaveBeenCalledOnce());
  expect(c.claim).toHaveBeenCalledOnce();expect(prepareCapture).toHaveBeenCalledOnce();
});
it('ordinary reopen requires explicit consent and retains the pre-journaled key and attestation',async()=>{
  const c=await combined();await c.render({entry:{...c.entry,transcriptionGesture:undefined}});
  await waitFor(()=>expect(button('Transcribe recording')).toBeDefined());expect(button('Transcribe recording')!.disabled).toBe(true);expect(prepareCapture).not.toHaveBeenCalled();
  await act(async()=>host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());await act(async()=>button('Transcribe recording')!.click());
  await waitFor(()=>expect(c.transcribe).toHaveBeenCalledOnce());expect(vi.mocked(prepareCapture).mock.calls[0][3]).toBe(c.intent.admission.key);
  expect(vi.mocked(prepareCapture).mock.calls[0][2]).toEqual(c.intent.admission.attestation);expect(c.claim).not.toHaveBeenCalled();
});
it.each(['failed','held'] as const)('spends the gesture before %s readiness and cannot auto-send on remount',async mode=>{
  const c=await combined();let release!:(value:typeof c.recording)=>void;
  if(mode==='failed')mocks.open.mockRejectedValueOnce(new Error('Synthetic readiness failed'));
  else mocks.open.mockImplementationOnce(()=>new Promise(resolve=>release=resolve));
  await c.render();await waitFor(()=>expect(c.claim).toHaveBeenCalledOnce());
  await act(async()=>root.unmount());root=createRoot(host);await c.render();
  if(mode==='held')await act(async()=>release(c.recording));
  await waitFor(()=>expect(button('Transcribe recording')).toBeDefined());expect(prepareCapture).not.toHaveBeenCalled();expect(c.transcribe).not.toHaveBeenCalled();
  expect(c.claim).toHaveBeenCalledTimes(2);
});
it.each(['owner','target_revision','source','consent','binding'] as const)('rejects changed %s before admission during a one-shot handoff',async change=>{
  const c=await combined();let target=workspace;
  if(change==='owner')activeReceipt={...c.source,owner_id:id(99)};
  if(change==='target_revision')target={...workspace,revision:workspace.revision+1};
  if(change==='source')mocks.open.mockResolvedValue({...c.recording,snapshotForLedger:async()=>({phase:'sealed',manifestSHA256:'e'.repeat(64),chunks:1,frames:1,consent:{...admission.attestation,language:'en-US'}})});
  if(change==='consent')mocks.open.mockResolvedValue({...c.recording,snapshotForLedger:async()=>({phase:'sealed',manifestSHA256:'b'.repeat(64),chunks:1,frames:1,consent:{...admission.attestation,modality:'phone',language:'en-US'}})});
  if(change==='binding')activeBinding={...c.binding,source_sha256:'e'.repeat(64)};
  await c.render({workspace:target});await waitFor(()=>expect(host.querySelector('[role=alert]')).toBeTruthy());
  expect(prepareCapture).not.toHaveBeenCalled();expect(c.transcribe).not.toHaveBeenCalled();
});
it('a lost admission reply preserves the exact continuation on manual retry and ordinary reopen',async()=>{
  const c=await combined();vi.mocked(prepareCapture).mockRejectedValue(new BffResponseError(503,'unconfirmed',null));
  await c.render();await waitFor(()=>expect(prepareCapture).toHaveBeenCalledOnce());const first=vi.mocked(prepareCapture).mock.calls[0];
  await waitFor(()=>expect(button('Continue transcription')?.disabled).toBe(false));await act(async()=>button('Continue transcription')!.click());await waitFor(()=>expect(prepareCapture).toHaveBeenCalledTimes(2));
  expect(vi.mocked(prepareCapture).mock.calls[1]).toEqual(first);
  await act(async()=>root.unmount());root=createRoot(host);await c.render({entry:{...c.entry,transcriptionGesture:undefined}});
  await waitFor(()=>expect(button('Continue transcription')?.disabled).toBe(false));expect(prepareCapture).toHaveBeenCalledTimes(2);
  await act(async()=>button('Continue transcription')!.click());await waitFor(()=>expect(prepareCapture).toHaveBeenCalledTimes(3));expect(vi.mocked(prepareCapture).mock.calls[2]).toEqual(first);
});
it('combined expiry allows explicit renewal then preserves its exact uncertain retry and remount history',async()=>{
  const c=await combined();vi.mocked(prepareCapture).mockRejectedValueOnce(new BffResponseError(409,'capture_recording_consent_required',null)).mockRejectedValue(new BffResponseError(503,'unconfirmed',null));
  await c.render();await waitFor(()=>expect(button('Send recording with confirmed consent')).toBeDefined());
  expect(button('Send recording with confirmed consent')!.disabled).toBe(true);
  await act(async()=>host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());await act(async()=>button('Send recording with confirmed consent')!.click());
  await waitFor(()=>expect(prepareCapture).toHaveBeenCalledTimes(2));const renewed=vi.mocked(prepareCapture).mock.calls[1];
  expect(renewed[3]).not.toBe(c.intent.admission.key);expect(renewed[8]).toBe(true);
  await act(async()=>button('Continue transcription')!.click());await waitFor(()=>expect(prepareCapture).toHaveBeenCalledTimes(3));expect(vi.mocked(prepareCapture).mock.calls[2]).toEqual(renewed);
  const retained=structuredClone(stored);await act(async()=>root.unmount());root=createRoot(host);await c.render({entry:{...c.entry,transcriptionGesture:undefined}});
  await waitFor(()=>expect(button('Continue transcription')?.disabled).toBe(false));expect(prepareCapture).toHaveBeenCalledTimes(3);
  await act(async()=>button('Continue transcription')!.click());await waitFor(()=>expect(prepareCapture).toHaveBeenCalledTimes(4));expect(vi.mocked(prepareCapture).mock.calls[3]).toEqual(renewed);
  expect((stored as {prior_admissions:unknown}).prior_admissions).toEqual((retained as {prior_admissions:unknown}).prior_admissions);
});

it.each(['workspace','team','bot','origin'] as const)('a held admission cannot adopt a replacement %s owner when the original IDs return',async change=>{
  const c=await combined();let release!:(value:Awaited<ReturnType<typeof prepareCapture>>)=>void,held!:Promise<Awaited<ReturnType<typeof prepareCapture>>>;
  vi.mocked(prepareCapture).mockImplementationOnce(()=>held=new Promise(resolve=>release=resolve));
  await c.render();await waitFor(()=>expect(release).toBeTypeOf('function'));
  const retained=structuredClone(stored);
  if(change==='workspace')await c.render({workspace:{...workspace,id:id(99)}});
  if(change==='team')await c.render({team:{revision:2,recovery_scope:'d'.repeat(64)} as ProviderTeam});
  if(change==='bot')await c.render({taskBot:{selection:{address:id(98),team_revision:1},name:'Other invented Scribe',enabled:true,includeNotebook:false}});
  if(change==='origin')await c.render({entry:{...c.entry,originWorkspace:{...c.entry.originWorkspace!,id:id(97)}}});
  await c.render();await waitFor(()=>expect(button('Continue transcription')).toBeDefined());
  await act(async()=>{release({status:'prepared',workspace_id:workspace.id,session_id:id(16),consent_record_id:id(17),configured_capture:{schema_version:'1.0',language_mode:'en-US'}});await held;});
  expect(stored).toEqual(retained);expect(c.transcribe).not.toHaveBeenCalled();expect(mocks.savedRuntime).not.toHaveBeenCalled();expect(prepareCapture).toHaveBeenCalledOnce();
});
it.each(['language','modality','regions'] as const)('manual continuation rejects a retained admission with altered %s despite the original audio digest',async change=>{
  const c=await combined();
  if(change==='language')c.intent.admission.language='en-US+es-US';
  if(change==='modality')c.intent.admission.attestation.modality='phone';
  if(change==='regions')c.intent.admission.attestation.participant_regions=['US'];
  await c.render({entry:{...c.entry,transcriptionGesture:undefined}});await waitFor(()=>expect(button('Transcribe recording')).toBeDefined());
  await act(async()=>host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());await act(async()=>button('Transcribe recording')!.click());
  await waitFor(()=>expect(host.querySelector('[role=alert]')).toBeTruthy());
  expect(prepareCapture).not.toHaveBeenCalled();expect(c.transcribe).not.toHaveBeenCalled();expect(stored).toBeNull();
});

it('reopens an already admitted uploaded transfer in review without a consent, admission or upload request',async()=>{
  const c=await combined();const snapshot={state:'processing',recordedChunks:1};
  mocks.savedRuntime.mockResolvedValue({controller:{snapshot,subscribe:(listener:(value:unknown)=>void)=>{listener(snapshot);return()=>{};}},transcribe:c.transcribe,close:async()=>{}});
  await c.render();await waitFor(()=>expect(c.transcribe).toHaveBeenCalledOnce());const retained=structuredClone(stored);const admittedCalls=vi.mocked(prepareCapture).mock.calls.length;
  await act(async()=>root.unmount());root=createRoot(host);await c.render({entry:{...c.entry,transcriptionGesture:undefined}});
  await waitFor(()=>expect(host.textContent).toContain('Review your transcript'));expect(host.querySelector('input[type=checkbox]')).toBeNull();expect(button('Continue transcription')).toBeUndefined();
  const reviewSection=host.querySelector('section[aria-label="Scribe transcript review"]');expect(reviewSection).not.toBeNull();expect(reviewSection!.closest('details')).toBeNull();
  expect(c.transcribe).toHaveBeenCalledOnce();expect(prepareCapture).toHaveBeenCalledTimes(admittedCalls);expect(stored).toEqual(retained);
});
it('reports an unavailable transcript honestly across reopen without repeating admission/upload, then adopts a ready review',async()=>{
  const c=await combined();const snapshot={state:'processing',recordedChunks:1};
  mocks.savedRuntime.mockResolvedValue({controller:{snapshot,subscribe:(listener:(value:unknown)=>void)=>{listener(snapshot);return()=>{};}},transcribe:c.transcribe,close:async()=>{}});
  await c.render();await waitFor(()=>expect(c.transcribe).toHaveBeenCalledOnce());const retained=structuredClone(stored);
  await act(async()=>root.unmount());root=createRoot(host);mocks.availability='unavailable';mocks.review={working:{note_ready:true}};
  await c.render({entry:{...c.entry,transcriptionGesture:undefined}});await waitFor(()=>expect(host.textContent).toContain('Your Scribe transcript cannot currently be retrieved'));
  expect(host.textContent).toContain('Choose Refresh in the review below');expect(host.textContent).not.toContain('Scribe transcript ready.');expect(host.textContent).not.toContain('Scribe is preparing your transcript');
  expect(host.textContent).not.toContain('could not finish transcription');expect(button('Continue transcription')).toBeUndefined();expect(stored).toEqual(retained);expect(c.transcribe).toHaveBeenCalledOnce();expect(prepareCapture).toHaveBeenCalledOnce();
  mocks.availability='ready';await c.render({entry:{...c.entry,transcriptionGesture:undefined}});await waitFor(()=>expect(host.textContent).toContain('Scribe transcript ready.'));
  expect(stored).toEqual(retained);expect(c.transcribe).toHaveBeenCalledOnce();expect(prepareCapture).toHaveBeenCalledOnce();
});
it('the real visit selector hands off one exact consent directly to the real saved transcription panel',async()=>{
  const c=await combined(),target={...workspace,revision:7};let visitIntent:unknown=null;activeBinding=null;
  mocks.read.mockImplementation(async key=>structuredClone(key==='visit-binding:'+id(3)?visitIntent:stored));
  mocks.write.mockImplementation(async(key,before,next)=>{expect(before).toEqual(key==='visit-binding:'+id(3)?visitIntent:stored);if(key==='visit-binding:'+id(3))visitIntent=structuredClone(next);else stored=structuredClone(next);});
  vi.spyOn(workspaceApi,'catalog').mockResolvedValue([{workspace_id:target.id,appointment_id:target.appointment_id!,label:target.label}]);
  vi.spyOn(workspaceApi,'open').mockResolvedValue({identity,team:c.team,workspace:target});vi.spyOn(workspaceApi,'openExisting').mockResolvedValue({identity,team:c.team,workspace:target});
  mocks.bindVisit.mockImplementation(async(_identity,_attach,_team,_source,request)=>activeBinding={...c.binding,request,request_sha256:await visitTranscriptionIntentHash({contract:'cosmas.private-recording.visit-binding.v1',request})});
  const bot={selection:{address:'scribe',team_revision:1},name:'Scribe',enabled:true,includeNotebook:false};
  function Workflow(){const [entry,setEntry]=useState<SavedRecordingEntry|null>(null);
    return entry?<SavedRecordingTranscriptionPanel entry={entry} identity={identity} workspace={target} team={c.team} isCurrent={()=>true} locked={false} notesEnabled={false} onDraftLock={()=>{}} onReviewDraft={()=>{}} onCurrentDraft={()=>{}} notebookDirty={false} onNotebook={()=>{}} taskBot={bot}/>:
      <RecordingVisitPanel entry={{recordingId:id(3),scope:'c'.repeat(64),platform:'desktop'}} identity={identity} origin={c.origin} team={c.team} locked={false} isCurrent={()=>true} taskBot={bot}
        onSelected={async(opened,binding,gesture)=>{expect(opened.revision).toBe(7);expect(gesture).toBeDefined();setEntry({...c.entry,binding:binding!,transcriptionGesture:gesture});}}/>;
  }
  await act(async()=>root.render(<Workflow/>));await waitFor(()=>expect(host.querySelector('select')).toBeTruthy());
  const select=host.querySelector('select')!;await act(async()=>{select.value=target.appointment_id!;select.dispatchEvent(new Event('change',{bubbles:true}));});
  await act(async()=>host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());await act(async()=>button('Confirm visit and transcribe')!.click());
  await waitFor(()=>expect(c.transcribe).toHaveBeenCalledOnce());const intent=await parseVisitTranscriptionIntent(visitIntent);
  expect(mocks.bindVisit).toHaveBeenCalledOnce();expect(prepareCapture).toHaveBeenCalledOnce();expect(vi.mocked(prepareCapture).mock.calls[0][3]).toBe(intent.admission.key);expect(vi.mocked(prepareCapture).mock.calls[0][2]).toEqual(intent.admission.attestation);
  expect(intent.request.expected_target_revision).toBe(7);expect(c.origin.appointment_id).toBeNull();expect((stored as {admission:{source:{origin_workspace_id:string}}}).admission.source.origin_workspace_id).toBe(c.origin.id);
});

it('simultaneous clean Continue callbacks release once and cannot show a note after owner replacement',async()=>{
  const c=await combined();let release!:()=>void,held!:Promise<void>;const snapshot={state:'processing',recordedChunks:1};
  const releaseUploaded=vi.fn(()=>held=new Promise<void>(resolve=>release=resolve));
  const runtime={controller:{snapshot,subscribe:(listener:(value:unknown)=>void)=>{listener(snapshot);return()=>{};}},transcribe:c.transcribe,close:async()=>{},releaseUploadedCapture:releaseUploaded};
  mocks.savedRuntime.mockResolvedValue(runtime);await c.render();await waitFor(()=>expect(mocks.continueReview).toBeTypeOf('function'));
  let continuations!:Promise<void>[];await act(async()=>{continuations=[mocks.continueReview!(),mocks.continueReview!()];});await waitFor(()=>expect(release).toBeTypeOf('function'));expect(releaseUploaded).toHaveBeenCalledOnce();
  await c.render({workspace:{...workspace,id:id(99)}});await c.render();await waitFor(()=>expect(host.textContent).toContain('Review your transcript'));
  await act(async()=>{release();await held;await Promise.all(continuations);});expect(host.textContent).not.toContain('Review your visit note');
  expect(c.transcribe).toHaveBeenCalledOnce();expect(prepareCapture).toHaveBeenCalledOnce();
});
it('held failed-upload progress cannot write an old error after replacement ownership returns',async()=>{
  const c=await combined();let release!:(value:null)=>void,held!:Promise<null>;const snapshot={state:'uploading',recordedChunks:1};
  const transcribe=vi.fn(async()=>{throw new Error('Invented upload uncertainty');});
  mocks.savedRuntime.mockResolvedValue({controller:{snapshot,subscribe:(listener:(value:unknown)=>void)=>{listener(snapshot);return()=>{};}},transcribe,close:async()=>{},uploadProgress:()=>held=new Promise<null>(resolve=>release=resolve)});
  await c.render();await waitFor(()=>expect(release).toBeTypeOf('function'));const retained=structuredClone(stored);
  await c.render({workspace:{...workspace,id:id(99)}});await c.render();await waitFor(()=>expect(button('Continue transcription')?.disabled).toBe(false));
  await act(async()=>{release(null);await held;});expect(host.querySelector('[role=alert]')).toBeNull();expect(stored).toEqual(retained);expect(transcribe).toHaveBeenCalledOnce();expect(prepareCapture).toHaveBeenCalledOnce();
});

it('clears prior upload progress when the mounted recording owner is replaced',async()=>{
  const c=await combined();const snapshot={state:'uploading',recordedChunks:1};
  mocks.savedRuntime.mockResolvedValue({controller:{snapshot,subscribe:(listener:(value:unknown)=>void)=>{listener(snapshot);return()=>{};}},transcribe:vi.fn(async()=>{throw new Error('Invented lost receipt');}),close:async()=>{},uploadProgress:async()=>({confirmed:0,total:1,reference:'invented_old_progress'})});
  await c.render();await waitFor(()=>expect(host.textContent).toContain('0 of 1 audio parts confirmed'));expect(host.textContent).toContain('invented_old_progress');
  await c.render({workspace:{...workspace,revision:2}});await waitFor(()=>expect(button('Continue transcription')?.disabled).toBe(false));
  expect(host.textContent).not.toContain('0 of 1 audio parts confirmed');expect(host.textContent).not.toContain('invented_old_progress');expect(prepareCapture).toHaveBeenCalledOnce();
});

it('hides redundant consent only while a claimed continuation is pending and restores it after an admission-free failure',async()=>{
  const c=await combined();const original=c.recording.snapshotForLedger;let reads=0,release!:(value:Awaited<ReturnType<typeof original>>)=>void,held!:Promise<Awaited<ReturnType<typeof original>>>;
  c.recording.snapshotForLedger=()=>++reads===1?original():held=new Promise(resolve=>release=resolve);
  await c.render();await waitFor(()=>expect(release).toBeTypeOf('function'));expect(host.querySelector('input[type=checkbox]')).toBeNull();expect(button('Sending saved recording…')?.disabled).toBe(true);
  await act(async()=>{release({...await original(),consent:{...admission.attestation,modality:'phone',language:'en-US'}} as Awaited<ReturnType<typeof original>>);await held;});
  await waitFor(()=>expect(host.querySelector('[role=alert]')).toBeTruthy());expect(host.querySelector('input[type=checkbox]')).not.toBeNull();expect(button('Transcribe recording')?.disabled).toBe(true);expect(prepareCapture).not.toHaveBeenCalled();expect(stored).toBeNull();
});


it('transcribes unavailable Scribe review locally from the same retained source with one action and no upload/admission change',async()=>{
  (stored as {admitted:unknown}).admitted={status:'prepared',workspace_id:id(1),session_id:id(7),consent_record_id:id(8),configured_capture:{schema_version:'1.0',language_mode:'en-US'}};
  const original=structuredClone(stored),privateRows=new Map<string,unknown>(),localIdentity={...identity,nativeSession:{revision:'invented-local-revision',isCurrent:()=>true}};
  mocks.read.mockImplementation(async key=>structuredClone(key.startsWith('private-transcript:')?privateRows.get(key)??null:stored));
  mocks.write.mockImplementation(async(key,before,next)=>{expect(key).toBe('private-transcript:'+id(3));expect(privateRows.get(key)??null).toEqual(before);privateRows.set(key,structuredClone(next));});
  mocks.open.mockResolvedValue({snapshot:{recordingId:id(3),workspaceId:id(1),phase:'sealed',recordedChunks:1,elapsedSeconds:23,title:'Invented retained clip'},close:mocks.runtimeClose,
    snapshotForLedger:async()=>({phase:'sealed',manifestSHA256:'b'.repeat(64),chunks:1,frames:1}),
    snapshotForPrivateTranscript:async()=>({recordingId:id(3),scope:'c'.repeat(64),phase:'sealed',audioSHA256:'e'.repeat(64),chunks:1,frames:1,consent:{language:'en-US'}}),
    savedChunks:async function*(){const wavBytes=new Uint8Array(46);wavBytes[44]=1;yield{sequence:0,sha256:'f'.repeat(64),wavBytes};}});
  mocks.privateBegin.mockResolvedValue({runId:id(30)});mocks.privateAppend.mockImplementation(async v=>({sequence:v.sequence}));mocks.privateFinish.mockResolvedValue({runId:id(30),recordingId:id(3),audioSHA256:'e'.repeat(64),frames:1,text:'Invented private fallback words.',engine:'ios-speech-on-device-v1',language:'en-US'});mocks.privateCancel.mockResolvedValue(undefined);
  const upload=vi.fn(),releaseUploaded=vi.fn(),snapshot={state:'processing',recordedChunks:1};mocks.availability='unavailable';mocks.review=null;
  mocks.savedRuntime.mockResolvedValue({controller:{snapshot,subscribe:(listener:(value:unknown)=>void)=>{listener(snapshot);return()=>{};}},transcribe:upload,close:async()=>{},releaseUploadedCapture:releaseUploaded});
  const render=()=>act(async()=>root.render(<SavedRecordingTranscriptionPanel entry={{recordingId:id(3),scope:'c'.repeat(64),platform:'ios'}} identity={localIdentity} workspace={workspace} team={{revision:1} as ProviderTeam}
    isCurrent={()=>true} locked={false} notesEnabled={false} onDraftLock={()=>{}} onReviewDraft={()=>{}} onCurrentDraft={()=>{}} notebookDirty={false} onNotebook={()=>{}} onNavigationLock={navigation}
    taskBot={{selection:{address:'scribe',team_revision:1},name:'Scribe',enabled:true,includeNotebook:false}}/>));
  await render();await waitFor(()=>expect(button('Transcribe on this iPhone')?.disabled).toBe(false));expect(mocks.privateBegin).not.toHaveBeenCalled();
  await act(async()=>button('Transcribe on this iPhone')!.click());await waitFor(()=>expect(host.querySelector('textarea')?.value).toBe('Invented private fallback words.'));
  expect(mocks.privateBegin).toHaveBeenCalledOnce();expect(mocks.privateBegin).toHaveBeenCalledWith(expect.objectContaining({scope:'c'.repeat(64),recordingId:id(3),audioSHA256:'e'.repeat(64),chunks:1,frames:1}));
  expect(prepareCapture).not.toHaveBeenCalled();expect(upload).not.toHaveBeenCalled();expect(stored).toEqual(original);expect(privateRows.get('private-transcript:'+id(3))).toMatchObject({workspaceId:id(1),working:'Invented private fallback words.'});
  await act(async()=>root.unmount());root=createRoot(host);mocks.availability='loading';await render();
  await waitFor(()=>expect(host.querySelector('textarea')?.value).toBe('Invented private fallback words.'));expect(button('Transcribe on this iPhone')).toBeUndefined();
  expect(host.textContent).toContain('Checking your existing Scribe transcript');expect(host.textContent).not.toContain('Scribe transcript ready');
  const reviewSection=host.querySelector('section[aria-label="Scribe transcript review"]');expect(reviewSection).not.toBeNull();expect(reviewSection!.closest('details')).toBeNull();
  expect(mocks.privateBegin).toHaveBeenCalledOnce();expect(prepareCapture).not.toHaveBeenCalled();expect(upload).not.toHaveBeenCalled();expect(stored).toEqual(original);
  const textarea=host.querySelector('textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(textarea,'Invented edits before opening note.');textarea.dispatchEvent(new Event('input',{bubbles:true}));});
  expect(navigation).toHaveBeenLastCalledWith(true);mocks.availability='ready';mocks.review={working:{note_ready:true}};await render();
  mocks.write.mockRejectedValueOnce(new Error('Local encrypted save unavailable'));
  await act(async()=>{await expect(mocks.continueReview!()).rejects.toThrow();});expect(releaseUploaded).not.toHaveBeenCalled();expect(host.textContent).not.toContain('Review your visit note');expect(host.querySelector('textarea')?.value).toBe('Invented edits before opening note.');
  let release!:()=>void,continuation!:Promise<void>;releaseUploaded.mockImplementationOnce(()=>new Promise<void>(resolve=>{release=resolve;}));
  await act(async()=>{continuation=mocks.continueReview!();});await waitFor(()=>expect(release).toBeTypeOf('function'));
  expect(releaseUploaded).toHaveBeenCalledOnce();expect(privateRows.get('private-transcript:'+id(3))).toMatchObject({working:'Invented edits before opening note.'});
  expect(host.querySelector('textarea')?.disabled).toBe(true);expect(navigation).toHaveBeenLastCalledWith(true);expect(host.textContent).not.toContain('Review your visit note');
  await act(async()=>mocks.continueReview!());expect(releaseUploaded).toHaveBeenCalledOnce();
  await act(async()=>{release();await continuation;});
  expect(host.textContent).toContain('Review your visit note');expect(stored).toEqual(original);expect(mocks.privateBegin).toHaveBeenCalledOnce();expect(upload).not.toHaveBeenCalled();
});
