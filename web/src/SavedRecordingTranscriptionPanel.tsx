import {PrivateTranscriptPanel,type PrivateTranscriptGesture} from './PrivateTranscriptPanel';
import {useCallback,useEffect,useRef,useState} from 'react';
import {PrivateRecordingRuntime,openPrivateRecordingStore,type PrivateRecordingStore} from './private-recording-runtime';
import {PrivateRecordingLedgerController} from './private-recording-ledger';
import {privateRecordingApi,parsePrivateRecordingReceipt,parseRecordingVisitBinding,type RecordingVisitBinding,type RecordingVisitRequest,type PrivateRecordingLinkRequest,type PrivateRecordingReceipt} from './private-recording-api';
import {prepareCapture,type PreparedCapture,type CaptureAttestation,type CaptureLanguage,type SavedRecordingSelection} from './capture-api';
import {openSavedRecordingRuntime} from './saved-recording-runtime';
import type {Workspace,ProviderTeam,AuthenticatedWorkspaceIdentity,CaptureTaskBot} from './workspace-api';
import {WorkspaceApiError} from './workspace-api';
import {CreatorReviewPanel} from './CreatorReviewPanel';
import {CaptureDraftPanel} from './CaptureDraftPanel';
import type {CaptureDraft} from './capture-notes-api';
import type {CreatorReviewView} from '../../clients/scribe-review/creator-review-api';
import type {SavedScratchpad} from './notebook-source';
import {vendorUuid,vendorCanonical,vendorSha256} from './vendor-contract';
import {savedTranscriptionRecovery} from './saved-transcription-recovery';
import './capture-panel.css';

export type VisitTranscriptionIntent={contract:'cosmas.visit-transcription.intent.v1';scope:string;owner_id:string;box_id:string;recovery_scope:string;
  recording_id:string;local_recording_id:string;origin_workspace_id:string;request:RecordingVisitRequest;request_sha256:string;
  finish_request_sha256:string;manifest_sha256:string;chunks:number;frames:number;audio_consent_sha256:string;
  admission:{key:string;attestation:CaptureAttestation;language:CaptureLanguage;bot:{address:string;team_revision:number}}};
/** This token permits one mounted continuation, never consent inferred from a saved receipt. */
export type RecordingTranscriptionGesture={identity:AuthenticatedWorkspaceIdentity;recordingId:string;scope:string;intent_sha256:string;claim:()=>boolean};
export type SavedRecordingEntry={recordingId:string;scope:string;platform:'ios'|'desktop';originWorkspace?:Workspace;visitResolved?:boolean;binding?:RecordingVisitBinding;transcriptionGesture?:RecordingTranscriptionGesture};
type Transfer={contract:'cosmas.saved-transfer.v1'|'cosmas.saved-transfer.v2'|'cosmas.saved-transfer.v3';binding?:RecordingVisitBinding;recording_id:string;workspace_id:string;scope:string;
  link_request:PrivateRecordingLinkRequest|null;receipt:PrivateRecordingReceipt|null;
  admission:null|{key:string;attestation:CaptureAttestation;language:CaptureLanguage;source:SavedRecordingSelection};
  admitted:PreparedCapture|null;prior_admissions?:NonNullable<Transfer['admission']>[];renew_saved_consent?:true};
type Runtime=Awaited<ReturnType<typeof openSavedRecordingRuntime>>;
function need(v:unknown):asserts v{if(!v)throw new WorkspaceApiError(503,'capture_saved_recording_changed');}
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
const digest=(v:unknown)=>vendorSha256(new TextEncoder().encode(vendorCanonical(v)));
const hash=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
export function visitTranscriptionCommand(value:unknown):RecordingVisitRequest{
  need(closed(value,'idempotency_key,target_workspace_id,appointment_id,expected_target_revision,visit_confirmed')&&vendorUuid(value.idempotency_key)&&
    vendorUuid(value.target_workspace_id)&&vendorUuid(value.appointment_id)&&Number.isSafeInteger(value.expected_target_revision)&&Number(value.expected_target_revision)>0&&value.visit_confirmed===true);
  return value as RecordingVisitRequest;
}
export async function parseVisitTranscriptionIntent(value:unknown):Promise<VisitTranscriptionIntent>{
  need(closed(value,'contract,scope,owner_id,box_id,recovery_scope,recording_id,local_recording_id,origin_workspace_id,request,request_sha256,finish_request_sha256,manifest_sha256,chunks,frames,audio_consent_sha256,admission')&&value.contract==='cosmas.visit-transcription.intent.v1');
  const v=value as VisitTranscriptionIntent;
  need([v.owner_id,v.box_id,v.recording_id,v.local_recording_id,v.origin_workspace_id].every(vendorUuid)&&
    [v.scope,v.recovery_scope,v.request_sha256,v.finish_request_sha256,v.manifest_sha256,v.audio_consent_sha256].every(hash));
  visitTranscriptionCommand(v.request);
  need(v.request_sha256===await digest({contract:'cosmas.private-recording.visit-binding.v1',request:v.request})&&
    Number.isSafeInteger(v.chunks)&&v.chunks>0&&v.chunks<=360&&Number.isSafeInteger(v.frames)&&v.frames>0&&v.frames<=57600000);
  need(closed(v.admission,'key,attestation,language,bot')&&vendorUuid(v.admission.key)&&['en-US','en-US+es-US'].includes(v.admission.language)&&
    closed(v.admission.bot,'address,team_revision')&&(v.admission.bot.address==='scribe'||vendorUuid(v.admission.bot.address))&&Number.isSafeInteger(v.admission.bot.team_revision)&&v.admission.bot.team_revision>0);
  const a=v.admission.attestation;
  need(closed(a,'modality,participant_regions,method,all_parties_consented,granted_at')&&['in_person','virtual','phone'].includes(a.modality)&&
    a.method==='verbal_attestation'&&a.all_parties_consented===true&&Array.isArray(a.participant_regions)&&a.participant_regions.length<=16&&
    a.participant_regions.every(r=>typeof r==='string'&&/^[A-Z]{2}(?:-[A-Z0-9]{1,3})?$/.test(r))&&new Set(a.participant_regions).size===a.participant_regions.length&&
    typeof a.granted_at==='string'&&Number.isFinite(Date.parse(a.granted_at)));
  return v;
}
export const visitTranscriptionIntentHash=digest;
export function requireVisitTranscriptionConsent(intent:VisitTranscriptionIntent,consent:CaptureAttestation&{language:CaptureLanguage}){
  const {language,granted_at:_recordedAt,...recorded}=consent;
  const {granted_at:_transcriptionAt,...attested}=intent.admission.attestation;
  need(intent.admission.language===language&&vendorCanonical(attested)===vendorCanonical(recorded));
}
export function requireVisitTranscriptionSource(intent:VisitTranscriptionIntent,receipt:PrivateRecordingReceipt,entry:SavedRecordingEntry,team:ProviderTeam){
  need(intent.scope===entry.scope&&intent.local_recording_id===entry.recordingId&&receipt.local_recording_id===entry.recordingId&&
    intent.recording_id===receipt.recording_id&&intent.origin_workspace_id===receipt.workspace_id&&intent.owner_id===receipt.owner_id&&intent.box_id===receipt.box_id&&
    intent.recovery_scope===receipt.recovery_scope&&intent.recovery_scope===team.recovery_scope&&receipt.finish&&
    intent.finish_request_sha256===receipt.finish.request_sha256&&intent.manifest_sha256===receipt.finish.manifest_sha256&&intent.chunks===receipt.finish.chunks&&intent.frames===receipt.finish.frames);
}
function validate(value:unknown,entry:SavedRecordingEntry,wid:string):Transfer{
  if(value&&typeof value==='object'&&'contract'in value&&value.contract==='cosmas.saved-transfer.v3'){
    const v=value as Transfer;
    const fields=(entry.binding?'contract,recording_id,workspace_id,scope,link_request,receipt,admission,admitted,binding':'contract,recording_id,workspace_id,scope,link_request,receipt,admission,admitted')+',prior_admissions,renew_saved_consent';
    need(closed(v,fields)&&v.renew_saved_consent===true&&Array.isArray(v.prior_admissions)&&v.prior_admissions.length>0&&v.prior_admissions.length<=20&&v.admission);
    const {prior_admissions,renew_saved_consent,...base}=v;
    const original={...base,contract:entry.binding?'cosmas.saved-transfer.v2' as const:'cosmas.saved-transfer.v1' as const};
    validate(original,entry,wid);
    for(const admission of prior_admissions) {
      validate({...original,admission,admitted:null},entry,wid);
      need(vendorCanonical(admission.source)===vendorCanonical(v.admission.source)&&admission.language===v.admission.language);
      const {granted_at:priorTime,...priorConsent}=admission.attestation;
      const {granted_at:currentTime,...currentConsent}=v.admission.attestation;
      need(priorTime!==currentTime&&vendorCanonical(priorConsent)===vendorCanonical(currentConsent));
    }
    return v;
  }
  need(closed(value,entry.binding?'contract,recording_id,workspace_id,scope,link_request,receipt,admission,admitted,binding':'contract,recording_id,workspace_id,scope,link_request,receipt,admission,admitted')&&value.contract===(entry.binding?'cosmas.saved-transfer.v2':'cosmas.saved-transfer.v1')&&value.recording_id===entry.recordingId&&value.workspace_id===wid&&value.scope===entry.scope);
  const v=value as Transfer;
  if(entry.binding)need(v.binding&&vendorCanonical(v.binding)===vendorCanonical(entry.binding)&&v.link_request===null);
  if(v.link_request)need(closed(v.link_request,'idempotency_key,expected_workspace_revision,workspace_link_receipt_id')&&vendorUuid(v.link_request.idempotency_key)&&vendorUuid(v.link_request.workspace_link_receipt_id)&&Number.isSafeInteger(v.link_request.expected_workspace_revision)&&v.link_request.expected_workspace_revision>0);
  if(v.receipt)need(v.receipt.local_recording_id===entry.recordingId&&v.receipt.workspace_id===(entry.originWorkspace?.id??wid)&&(entry.binding||v.receipt.link)&&v.receipt.finish);
  if(v.admission){
    need(closed(v.admission,'key,attestation,language,source')&&vendorUuid(v.admission.key)&&['en-US','en-US+es-US'].includes(v.admission.language)&&v.receipt);
    const a=v.admission.attestation,s=v.admission.source;
    need(closed(a,'modality,participant_regions,method,all_parties_consented,granted_at')&&['in_person','virtual','phone'].includes(a.modality)&&a.method==='verbal_attestation'&&a.all_parties_consented===true&&Array.isArray(a.participant_regions)&&a.participant_regions.length<=20&&a.participant_regions.every(r=>typeof r==='string'&&/^[A-Z]{2}(?:-[A-Z0-9]{1,3})?$/.test(r))&&new Set(a.participant_regions).size===a.participant_regions.length&&typeof a.granted_at==='string'&&Number.isFinite(Date.parse(a.granted_at)));
    need((entry.binding?closed(s,'recording_id,origin_workspace_id,visit_binding_receipt_id,source_sha256,manifest_sha256,chunks,frames')&&'visit_binding_receipt_id'in s&&s.visit_binding_receipt_id===entry.binding.receipt_id&&s.origin_workspace_id===entry.binding.origin_workspace_id&&s.source_sha256===entry.binding.source_sha256:closed(s,'recording_id,link_receipt_id,source_sha256,manifest_sha256,chunks,frames')&&'link_receipt_id'in s&&s.link_receipt_id===v.receipt.link?.receipt_id&&s.source_sha256===v.receipt.link?.source_sha256)&&s.recording_id===v.receipt.recording_id&&s.manifest_sha256===v.receipt.finish?.manifest_sha256&&Number.isSafeInteger(s.chunks)&&s.chunks>0&&s.chunks<=360&&s.chunks===v.receipt.finish.chunks&&Number.isSafeInteger(s.frames)&&s.frames>0&&s.frames<=57600000&&s.frames===v.receipt.finish.frames);
  }
  if(v.admitted)need(closed(v.admitted,'status,workspace_id,session_id,consent_record_id,configured_capture')&&v.admission&&v.admitted.status==='prepared'&&v.admitted.workspace_id===wid&&vendorUuid(v.admitted.session_id)&&vendorUuid(v.admitted.consent_record_id)&&closed(v.admitted.configured_capture,'schema_version,language_mode')&&v.admitted.configured_capture.schema_version==='1.0'&&v.admitted.configured_capture.language_mode===v.admission.language);
  return v;
}

export function SavedRecordingTranscriptionPanel({entry,identity,workspace,team,isCurrent,taskBot,locked,notesEnabled,
  onDraftLock,onReviewDraft,onCurrentDraft,scratchpad,notebookDirty,onNotebook,onRecordings,onNavigationLock}:{entry:SavedRecordingEntry;identity:AuthenticatedWorkspaceIdentity;
  workspace:Workspace;team:ProviderTeam;isCurrent:()=>boolean;taskBot?:CaptureTaskBot;locked:boolean;notesEnabled:boolean;
  onDraftLock:(v:boolean)=>void;onReviewDraft:(v:CaptureDraft)=>void;onCurrentDraft:(v:CaptureDraft)=>void;
  scratchpad?:SavedScratchpad;notebookDirty:boolean;onNotebook:()=>void;onRecordings?:()=>void;onNavigationLock?:(busy:boolean)=>void}){
  const origin=entry.originWorkspace??workspace;
  const [ready,setReady]=useState(false),[busy,setBusy]=useState(false),[consented,setConsented]=useState(false),[error,setError]=useState('');
  const [renewConsent,setRenewConsent]=useState(false),[claimedContinuation,setClaimedContinuation]=useState(false);
  const [uploadProgress,setUploadProgress]=useState<Awaited<ReturnType<Runtime['uploadProgress']>>|null>(null);
  const [clipDate,setClipDate]=useState<string|null>(null);
  const [privateGesture,setPrivateGesture]=useState<PrivateTranscriptGesture|null>(null),[privateBusy,setPrivateBusy]=useState(false);
  const [recovery,setRecovery]=useState<ReturnType<typeof savedTranscriptionRecovery>>(null);
  const [transfer,setTransfer]=useState<Transfer|null>(null),[snapshot,setSnapshot]=useState<Runtime['controller']['snapshot']|null>(null);
  const [reviewAvailability,setReviewAvailability]=useState<'loading'|'ready'|'unavailable'>('loading');
  const [review,setReview]=useState<CreatorReviewView|null>(null),[reviewLock,setReviewLock]=useState(false),[showDraft,setShowDraft]=useState(false),[draftLocked,setDraftLocked]=useState(false);
  const live=useRef({identity,entry,workspace,team,isCurrent,locked,taskBot});live.current={identity,entry,workspace,team,isCurrent,locked,taskBot};
  const owner=useRef<{alive:boolean;store:PrivateRecordingStore;recording:PrivateRecordingRuntime;runtime:Runtime|null;unsubscribe?:()=>void}|null>(null);
  const saved=useRef<Transfer|null>(null),flight=useRef<symbol|null>(null);
  const continuation=useRef<{gesture:RecordingTranscriptionGesture;identity:AuthenticatedWorkspaceIdentity;recordingId:string;scope:string;authority:string;armed:boolean;started:boolean}|null>(null);
  const noteSection=useRef<HTMLDivElement>(null);
  const transcriptionSection=useRef<HTMLElement>(null);
  const reportDraftLock=useCallback((value:boolean)=>{setDraftLocked(value);onDraftLock(value);},[onDraftLock]);
  useEffect(()=>{onNavigationLock?.(busy||privateBusy);return()=>onNavigationLock?.(false);},[busy,privateBusy,onNavigationLock]);
  useEffect(()=>{if(ready){const heading=transcriptionSection.current?.querySelector<HTMLElement>('h2');if(heading){heading.tabIndex=-1;heading.focus();heading.scrollIntoView({block:'start'});}}},[ready]);
  useEffect(()=>{if(showDraft){const heading=noteSection.current?.querySelector<HTMLElement>('h3');if(heading){heading.tabIndex=-1;heading.focus();heading.scrollIntoView({block:'start'});}}},[showDraft]);
  const authorityKey=vendorCanonical({workspace:workspace.id,workspace_revision:workspace.revision,origin:origin.id,appointment:workspace.appointment_id,binding:entry.binding??null,team_revision:team.revision,recovery_scope:team.recovery_scope??null,bot:taskBot?.selection??null,enabled:taskBot?.enabled??false});
  const authorityCurrent=()=>live.current.identity===identity&&live.current.entry.scope===entry.scope&&live.current.entry.recordingId===entry.recordingId&&live.current.workspace.id===workspace.id&&
    live.current.workspace.appointment_id===workspace.appointment_id&&live.current.workspace.revision===workspace.revision&&(live.current.entry.originWorkspace?.id??live.current.workspace.id)===origin.id&&live.current.team.revision===team.revision&&live.current.team.recovery_scope===team.recovery_scope&&
    vendorCanonical(live.current.entry.binding??null)===vendorCanonical(entry.binding??null)&&vendorCanonical(live.current.taskBot?.selection??null)===vendorCanonical(taskBot?.selection??null)&&live.current.taskBot?.enabled===taskBot?.enabled&&live.current.isCurrent();
  const current=(selected=owner.current)=>!!selected?.alive&&owner.current===selected&&authorityCurrent();
  const reportReviewAvailability=useCallback((value:'loading'|'ready'|'unavailable')=>{if(current())setReviewAvailability(value);},[identity,entry.scope,entry.recordingId,authorityKey]);
  const reportReview=useCallback((value:CreatorReviewView|null)=>{if(current())setReview(value);},[identity,entry.scope,entry.recordingId,authorityKey]);
  useEffect(()=>{let alive=true;
    setReady(false);setBusy(false);setPrivateGesture(null);setPrivateBusy(false);setConsented(false);setRenewConsent(false);setRecovery(null);setUploadProgress(null);setReviewLock(false);setDraftLocked(false);setReview(null);setReviewAvailability('loading');setShowDraft(false);setClipDate(null);setTransfer(null);setSnapshot(null);setError('');saved.current=null;flight.current=null;
    const gesture=entry.transcriptionGesture,prior=continuation.current;
    if(gesture&&(!prior||prior.gesture!==gesture||prior.identity!==identity||prior.recordingId!==entry.recordingId||prior.scope!==entry.scope||prior.authority!==authorityKey)){
      // Claim before async readiness. StrictMode's repeated setup uses this same
      // ref; an actual remount has a new ref and cannot reclaim the spent token.
      continuation.current={gesture,identity,recordingId:entry.recordingId,scope:entry.scope,authority:authorityKey,
        armed:gesture.identity===identity&&gesture.recordingId===entry.recordingId&&gesture.scope===entry.scope&&hash(gesture.intent_sha256)&&gesture.claim(),started:false};
    }else if(!gesture)continuation.current=null;
    setClaimedContinuation(!!continuation.current?.armed&&!continuation.current.started);
    void(async()=>{
      const store=await openPrivateRecordingStore(entry.scope,entry.platform);
      let recording:PrivateRecordingRuntime;
      try{recording=await PrivateRecordingRuntime.open({scope:entry.scope,platform:entry.platform,isCurrent:()=>alive&&authorityCurrent(),openStore:async()=>store},{recordingId:entry.recordingId,title:'Saved recording'});}catch(cause){store.close();throw cause;}
      if(!alive||!authorityCurrent()){await recording.close();return;}
      const selected={alive:true,store,recording,runtime:null as Runtime|null,unsubscribe:undefined as (()=>void)|undefined};owner.current=selected;
      need(recording.snapshot.workspaceId===origin.id&&recording.snapshot.phase==='sealed'&&recording.snapshot.recordedChunks>0);
      const check=()=>alive&&current(selected);
      const audioDetails=await recording.snapshotForLedger();if(!check())return;
      if(audioDetails.startedAt)setClipDate(audioDetails.startedAt);
      const value=await store.read('transfer:'+entry.recordingId);if(!check())return;
      saved.current=value===null?null:validate(value,entry,workspace.id);
      if(saved.current?.receipt){const ledger=new PrivateRecordingLedgerController({identity,team,workspace:origin,store,scope:entry.scope,isCurrent:check});const original=await ledger.readCurrent(entry.recordingId);need(original?.state==='finished');await parsePrivateRecordingReceipt(saved.current.receipt,original.attach);need(check());if(entry.binding)await parseRecordingVisitBinding(entry.binding,saved.current.receipt);need(check());}
      setTransfer(saved.current);
      if(saved.current?.admitted)await openRuntime(saved.current.admitted,selected);
      if(check())setReady(true);
    })().catch(()=>{if(alive&&authorityCurrent()){setClaimedContinuation(false);setError('This saved recording could not be opened for transcription. Your original audio is retained.');}});
    return()=>{alive=false;const selected=owner.current;if(selected){selected.alive=false;selected.unsubscribe?.();void(async()=>{try{await selected.runtime?.close();}finally{await selected.recording.close();}})();}owner.current=null;};
  },[identity,entry.scope,entry.recordingId,workspace.id,workspace.appointment_id,workspace.revision,origin.id,team.revision,team.recovery_scope,taskBot?.selection.address,taskBot?.selection.team_revision,taskBot?.enabled,entry.binding?.request_sha256,entry.binding?.source_sha256,authorityKey]);
  useEffect(()=>{
    const next=continuation.current;
    if(!ready||locked||!current()||!next?.armed||next.started||next.identity!==identity||next.recordingId!==entry.recordingId||next.scope!==entry.scope||next.authority!==authorityKey)return;
    const selected=owner.current;next.started=true;void transcribe(next.gesture).finally(()=>{if(current(selected))setClaimedContinuation(false);});
  },[ready,locked,identity,entry.recordingId,entry.scope,authorityKey]);
  async function persist(next:Transfer,selected=owner.current){need(current(selected)&&selected);validate(next,entry,workspace.id);
    await selected.store.write('transfer:'+entry.recordingId,saved.current,next);need(current(selected));saved.current=next;setTransfer(next);}
  async function openRuntime(admitted:PreparedCapture,selected=owner.current){need(current(selected)&&selected);
    const opened=await openSavedRecordingRuntime({workspaceId:workspace.id,admitted,identity,scope:entry.scope,recording:selected.recording,
      chunks:saved.current!.admission!.source.chunks,platform:entry.platform,isCurrent:()=>current(selected)});
    if(!current(selected)){await opened.close();return;}selected.runtime=opened;selected.unsubscribe=opened.controller.subscribe(value=>{if(current(selected))setSnapshot(value);});
    if(opened.reviewOnly)setSnapshot({...opened.controller.snapshot,state:'processing',sessionId:admitted.session_id});
  }
  async function transcribe(gesture?:RecordingTranscriptionGesture){if(!ready||flight.current||locked||recovery?.retry===false||!workspace.appointment_id||!taskBot?.enabled||(!saved.current?.admission||renewConsent)&&!consented&&!gesture)return;
    const selected=owner.current;if(!current(selected)||!selected)return;const ticket=Symbol('saved-transcription');flight.current=ticket;
    const requestCurrent=()=>current(selected);setBusy(true);setError('');setUploadProgress(null);
    try{
      need(requestCurrent());
      const ledger=new PrivateRecordingLedgerController({identity,team,workspace:origin,store:selected.store,scope:entry.scope,isCurrent:requestCurrent});
      const record=await ledger.readCurrent(entry.recordingId);need(record?.state==='finished'&&record.receipt&&record.finish);
      let receipt=await privateRecordingApi.read(identity,record.attach,team,record.receipt.recording_id);need(requestCurrent());
      const audio=await selected.recording.snapshotForLedger();
      need(audio.phase==='sealed'&&receipt.finish?.manifest_sha256===audio.manifestSHA256&&receipt.finish.chunks===audio.chunks&&receipt.finish.frames===audio.frames);
      let confirmedIntent:VisitTranscriptionIntent|null=null;
      if(entry.binding){
        const retained=await selected.store.read('visit-binding:'+entry.recordingId);need(requestCurrent());
        if(retained!==null&&typeof retained==='object'&&'contract'in retained&&retained.contract==='cosmas.visit-transcription.intent.v1')
          confirmedIntent=await parseVisitTranscriptionIntent(retained);
      }
      if(confirmedIntent){
        requireVisitTranscriptionSource(confirmedIntent,receipt,entry,team);requireVisitTranscriptionConsent(confirmedIntent,audio.consent);
        need(entry.binding&&vendorCanonical(confirmedIntent.request)===vendorCanonical(entry.binding.request)&&confirmedIntent.request_sha256===entry.binding.request_sha256&&
          confirmedIntent.request.target_workspace_id===workspace.id&&confirmedIntent.request.appointment_id===workspace.appointment_id&&
          confirmedIntent.audio_consent_sha256===await digest(audio.consent)&&
          vendorCanonical(confirmedIntent.admission.bot)===vendorCanonical(taskBot.selection));
      }
      if(gesture)need(!renewConsent&&confirmedIntent&&continuation.current?.gesture===gesture&&continuation.current.armed&&gesture.identity===identity&&
        gesture.scope===entry.scope&&gesture.recordingId===entry.recordingId&&confirmedIntent.request.expected_target_revision===workspace.revision&&
        await visitTranscriptionIntentHash(confirmedIntent)===gesture.intent_sha256);
      // Reopening requires a new explicit gesture, but keeps the original
      // admission key/consent until a definite receiver rejection permits renewal.
      if(renewConsent)confirmedIntent=null;
      let frames=0,chunks=0,signal=false;
      for await(const chunk of selected.recording.savedChunks()){
        frames+=(chunk.wavBytes.length-44)/2;chunks++;
        signal ||= chunk.wavBytes.subarray(44).some(v=>v!==0);
      }
      need(requestCurrent()&&frames===audio.frames&&chunks===audio.chunks);
      if(!signal)throw Object.assign(new Error('No recorded speech'),{code:'saved_audio_silent'});
      let next=saved.current??{contract:entry.binding?'cosmas.saved-transfer.v2' as const:'cosmas.saved-transfer.v1' as const,...(entry.binding?{binding:entry.binding}:{}),recording_id:entry.recordingId,workspace_id:workspace.id,scope:entry.scope,link_request:null,receipt:null,admission:null,admitted:null};
      if(entry.binding){
        const binding=await privateRecordingApi.readVisitBinding(identity,record.attach,team,receipt);need(requestCurrent()&&binding&&vendorCanonical(binding)===vendorCanonical(entry.binding)&&binding.target_workspace_id===workspace.id&&binding.appointment_id===workspace.appointment_id);
      }else if(!receipt.link){
        need(workspace.private_draft?.link_receipt_id);
        if(!next.link_request){next={...next,link_request:{idempotency_key:crypto.randomUUID(),expected_workspace_revision:workspace.revision,workspace_link_receipt_id:workspace.private_draft.link_receipt_id}};await persist(next,selected);}
        receipt=await privateRecordingApi.link(identity,record.attach,team,receipt.recording_id,next.link_request!);need(requestCurrent());
      }
      need(entry.binding||receipt.state==='linked_metadata'&&receipt.link?.workspace_link_receipt_id===workspace.private_draft?.link_receipt_id);
      if(next.receipt)need(vendorCanonical(next.receipt)===vendorCanonical(receipt));
      next={...next,receipt};await persist(next,selected);
      if(renewConsent){
        need(consented&&next.admission&&!next.admitted&&(next.prior_admissions?.length??0)<20);
        next={...next,contract:'cosmas.saved-transfer.v3',prior_admissions:[...(next.prior_admissions??[]),next.admission],
          renew_saved_consent:true,admission:{...next.admission,key:crypto.randomUUID(),attestation:{...next.admission.attestation,granted_at:new Date().toISOString()}}};
        await persist(next,selected);setRenewConsent(false);
      }
      if(!next.admission){
        need((consented||confirmedIntent)&&(entry.binding||receipt.link)&&receipt.finish);
        const {language,...original}=audio.consent;
        next={...next,admission:{key:confirmedIntent?.admission.key??crypto.randomUUID(),language:confirmedIntent?.admission.language??language,attestation:confirmedIntent?.admission.attestation??{...original,granted_at:new Date().toISOString()},
          source:{recording_id:receipt.recording_id,...(entry.binding?{origin_workspace_id:origin.id,visit_binding_receipt_id:entry.binding.receipt_id,source_sha256:entry.binding.source_sha256}:{link_receipt_id:receipt.link!.receipt_id,source_sha256:receipt.link!.source_sha256}),
            manifest_sha256:audio.manifestSHA256,chunks:audio.chunks,frames:audio.frames}}};await persist(next,selected);
      }
      if(confirmedIntent){
        const original=next.contract==='cosmas.saved-transfer.v3'?next.prior_admissions?.[0]:next.admission;
        need(original?.key===confirmedIntent.admission.key&&original.language===confirmedIntent.admission.language&&
          vendorCanonical(original.attestation)===vendorCanonical(confirmedIntent.admission.attestation));
      }
      if(!next.admitted){const a=next.admission!;
        const admitted=await prepareCapture(workspace.id,identity,a.attestation,a.key,undefined,taskBot.selection,a.language,a.source,next.renew_saved_consent===true);need(requestCurrent());
        next={...next,admitted};await persist(next,selected);}
      if(!selected.runtime)await openRuntime(next.admitted!,selected);need(requestCurrent()&&selected.runtime);
      await selected.runtime.transcribe();
    }catch(cause){
      if(requestCurrent()&&selected?.runtime?.controller.snapshot.state==='error'&&selected.runtime.controller.snapshot.recordedChunks<(saved.current?.admission?.source.chunks??0)){
        selected.unsubscribe?.();selected.unsubscribe=undefined;
        await selected.runtime.close().catch(()=>{});selected.runtime=null;
        if(requestCurrent())setSnapshot(null);
      }
      if(requestCurrent()){
      if(selected?.runtime){const progress=await selected.runtime.uploadProgress().catch(()=>null);if(requestCurrent())setUploadProgress(progress);}
      if(!requestCurrent())return;
      const code=cause&&typeof cause==='object'&&'code'in cause?cause.code:'';
      if(code==='capture_recording_consent_required'&&!saved.current?.admitted){
        setRenewConsent(true);setConsented(false);setRecovery(null);
        setError('Your earlier transcription request expired before Scribe accepted it. Confirm consent below, then send this saved recording. Your original audio and earlier request are retained.');
      }else{
      const blocked=savedTranscriptionRecovery(code);setRecovery(blocked);
      if(blocked)setError(blocked.message);
      else
      setError(code==='saved_audio_silent'?'This recording contains no microphone signal. Play it from Home to check it, or make a new recording with the microphone available.':code==='capture_connection_required'?'Connect your Core account before transcribing. Your recording remains saved on this device.':code==='capture_saved_recording_changed'?'This recording or its visit connection changed. Return Home and reopen the original recording before continuing.':code==='capture_access_unavailable'||cause instanceof WorkspaceApiError&&[401,403].includes(cause.status)?'Sign in again to continue. Your recording and transfer are saved.':`Transcription could not continue. Your original audio and progress are saved. Choose ${saved.current?.admission?'Continue transcription':'Transcribe recording'} to retry.`);
    }}}
    finally{if(flight.current===ticket)flight.current=null;if(requestCurrent())setBusy(false);}
  }
  function transcribePrivately(){
    const selected=owner.current;if(!ready||busy||privateBusy||locked||!current(selected)||!selected||entry.platform!=='ios'||reviewAvailability!=='unavailable')return;
    let claimed=false;setPrivateGesture({identity,scope:entry.scope,recording:selected.recording,claim:()=>{if(claimed||!current(selected))return false;claimed=true;return true;}});
  }
  const processing=!!transfer?.admitted&&(snapshot?.state==='processing'||review!==null);
  return <section ref={transcriptionSection} className="capture-panel saved-transcription" aria-label="Saved recording transcription" data-english-only={transfer?.admission?.language==='en-US'}>
    <h2>{showDraft?'Review your visit note':processing?'Review your transcript':'Transcribe your saved recording'}</h2>
    {workspace.appointment_id&&<><ol aria-label="Transcription steps"><li>Visit confirmed</li><li>{processing?'Audio uploaded':'Send recording to Scribe'}</li><li>Review transcript and save your note</li></ol>
    <p>Your original recording stays on this device. Find it under Home → Recordings on this device.</p></>}
    {!workspace.appointment_id?<p role="status">Choose a visit below, then send this recording to Scribe.</p>:<>
      <p><strong>{workspace.label}</strong> · {owner.current?.recording.snapshot.title}</p>
      {ready&&owner.current&&<p>{clipDate&&<time dateTime={clipDate}>{new Date(clipDate).toLocaleString()} · </time>}{Math.floor(owner.current.recording.snapshot.elapsedSeconds/60)}:{String(Math.floor(owner.current.recording.snapshot.elapsedSeconds%60)).padStart(2,'0')} saved recording</p>}
      {!claimedContinuation&&(!transfer?.admission||renewConsent)&&!processing&&<label className="private-recording-check"><input type="checkbox" checked={consented} disabled={busy||locked} onChange={event=>setConsented(event.target.checked)}/>I confirm everyone agreed to transcription, and this recording belongs to the visit shown above.</label>}
      {!processing&&recovery?.retry!==false&&<button className="team-primary" disabled={!ready||busy||locked||!taskBot?.enabled||(!transfer?.admission||renewConsent)&&!consented} onClick={()=>void transcribe()}>{busy?'Sending saved recording…':renewConsent?'Send recording with confirmed consent':transfer?.admission?'Continue transcription':'Transcribe recording'}</button>}
      {!taskBot?.enabled&&<p role="status">Enable Scribe in team settings to transcribe this recording. Your audio is saved.</p>}
    </>}
    {snapshot&&<p role="status">{showDraft?'Review and edit your visit note below.':reviewAvailability==='unavailable'?'Audio uploaded. Your transcript cannot currently be retrieved. Your audio and progress are retained. Open Review transcript and choose Refresh to check again.':processing&&reviewAvailability==='loading'?'Audio uploaded. Checking your existing transcript.':review?.working?.note_ready?'Transcript ready. Review it, then continue to your note.':review?.status==='speech_failed'?'Scribe could not finish transcription. Your audio is saved. Return to recordings to play it.':review?.status==='speech_retryable'?'Your audio is uploaded. Scribe will retry transcription automatically; choose Refresh to check progress.':processing?'Audio uploaded. Scribe is preparing your transcript.':uploadProgress?`${uploadProgress.confirmed} of ${uploadProgress.total} audio parts confirmed by Scribe. Your recording is saved.`:snapshot.recordedChunks===(transfer?.admission?.source.chunks??0)?busy?'Sending your saved audio to Scribe. Keep CosmaBot open until upload is confirmed.':'Your saved audio is ready. Choose Continue transcription to send the remaining parts.':`Preparing your saved recording… ${Math.floor(snapshot.recordedChunks/Math.max(1,transfer?.admission?.source.chunks??1)*100)}%`}</p>}
    {entry.platform==='ios'&&ready&&current()&&processing&&reviewAvailability==='unavailable'&&!privateGesture&&<button className="team-primary" disabled={busy||privateBusy||locked} onClick={transcribePrivately}>Transcribe on this iPhone</button>}
    {privateGesture&&privateGesture.identity===identity&&privateGesture.scope===entry.scope&&owner.current?.recording===privateGesture.recording&&current()&&<PrivateTranscriptPanel identity={identity} scope={entry.scope} recording={privateGesture.recording} isCurrent={()=>current()&&!live.current.locked} onBusy={setPrivateBusy} transcriptionGesture={privateGesture} savedScribeSource/>}
    {error&&uploadProgress?.reference&&<details><summary>Support details</summary><p>Upload status: <code>{uploadProgress.reference}</code></p></details>}
    {error&&<p role="alert">{error}</p>}
    {(recovery||review?.status==='speech_failed')&&<div className="capture-actions">
      {onRecordings&&<button className="team-primary" disabled={busy||locked} onClick={onRecordings}>Return to recordings</button>}
      {recovery&&<details><summary>Support details</summary><p>Recording connection: <code>{recovery.reference}</code></p></details>}
    </div>}
    {processing&&transfer?.admitted&&<details className="saved-transcript-review" open={!showDraft}><summary>Review transcript</summary><CreatorReviewPanel workspaceId={workspace.id} sessionId={transfer.admitted.session_id} identity={identity}
      locked={locked||busy||draftLocked} onLock={setReviewLock} onAvailability={reportReviewAvailability} onSource={reportReview} onContinue={async()=>{const selected=owner.current;if(!current(selected)||!selected?.runtime)return;await selected.runtime.releaseUploadedCapture();if(current(selected))setShowDraft(true);}}/></details>}
    {showDraft&&review?.working?.note_ready&&notesEnabled&&transfer?.admitted&&<div ref={noteSection}><CaptureDraftPanel workspaceId={workspace.id} sessionId={transfer.admitted.session_id}
      sourceId={review.working.working_transcript_id} identity={identity} onDraftLock={reportDraftLock} onReviewDraft={onReviewDraft} onCurrentDraft={onCurrentDraft}
      reviewLocked={locked} sourceLocked={reviewLock||busy} taskBot={taskBot} scratchpad={scratchpad} notebookDirty={notebookDirty} onNotebook={onNotebook} simpleFlow/></div>}
  </section>;
}
