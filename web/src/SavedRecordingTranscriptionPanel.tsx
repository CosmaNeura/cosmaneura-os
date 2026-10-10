import {useCallback,useEffect,useRef,useState} from 'react';
import {PrivateRecordingRuntime,openPrivateRecordingStore,type PrivateRecordingStore} from './private-recording-runtime';
import {PrivateRecordingLedgerController} from './private-recording-ledger';
import {privateRecordingApi,parsePrivateRecordingReceipt,parseRecordingVisitBinding,type RecordingVisitBinding,type PrivateRecordingLinkRequest,type PrivateRecordingReceipt} from './private-recording-api';
import {prepareCapture,type PreparedCapture,type CaptureAttestation,type CaptureLanguage,type SavedRecordingSelection} from './capture-api';
import {openSavedRecordingRuntime} from './saved-recording-runtime';
import type {Workspace,ProviderTeam,AuthenticatedWorkspaceIdentity,CaptureTaskBot} from './workspace-api';
import {WorkspaceApiError} from './workspace-api';
import {CreatorReviewPanel} from './CreatorReviewPanel';
import {CaptureDraftPanel} from './CaptureDraftPanel';
import type {CaptureDraft} from './capture-notes-api';
import type {CreatorReviewView} from '../../clients/scribe-review/creator-review-api';
import type {SavedScratchpad} from './notebook-source';
import {vendorUuid,vendorCanonical} from './vendor-contract';
import './capture-panel.css';

export type SavedRecordingEntry={recordingId:string;scope:string;platform:'ios'|'desktop';originWorkspace?:Workspace;visitResolved?:boolean;binding?:RecordingVisitBinding};
type Transfer={contract:'cosmas.saved-transfer.v1'|'cosmas.saved-transfer.v2';binding?:RecordingVisitBinding;recording_id:string;workspace_id:string;scope:string;
  link_request:PrivateRecordingLinkRequest|null;receipt:PrivateRecordingReceipt|null;
  admission:null|{key:string;attestation:CaptureAttestation;language:CaptureLanguage;source:SavedRecordingSelection};
  admitted:PreparedCapture|null};
type Runtime=Awaited<ReturnType<typeof openSavedRecordingRuntime>>;
function need(v:unknown):asserts v{if(!v)throw new WorkspaceApiError(503,'capture_saved_recording_changed');}
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
function validate(value:unknown,entry:SavedRecordingEntry,wid:string):Transfer{
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
  onDraftLock,onReviewDraft,onCurrentDraft,scratchpad,notebookDirty,onNotebook}:{entry:SavedRecordingEntry;identity:AuthenticatedWorkspaceIdentity;
  workspace:Workspace;team:ProviderTeam;isCurrent:()=>boolean;taskBot?:CaptureTaskBot;locked:boolean;notesEnabled:boolean;
  onDraftLock:(v:boolean)=>void;onReviewDraft:(v:CaptureDraft)=>void;onCurrentDraft:(v:CaptureDraft)=>void;
  scratchpad?:SavedScratchpad;notebookDirty:boolean;onNotebook:()=>void}){
  const origin=entry.originWorkspace??workspace;
  const [ready,setReady]=useState(false),[busy,setBusy]=useState(false),[consented,setConsented]=useState(false),[error,setError]=useState('');
  const [transfer,setTransfer]=useState<Transfer|null>(null),[snapshot,setSnapshot]=useState<Runtime['controller']['snapshot']|null>(null);
  const [review,setReview]=useState<CreatorReviewView|null>(null),[reviewLock,setReviewLock]=useState(false),[showDraft,setShowDraft]=useState(false),[draftLocked,setDraftLocked]=useState(false);
  const live=useRef({identity,entry,workspace,team,isCurrent,locked,taskBot});live.current={identity,entry,workspace,team,isCurrent,locked,taskBot};
  const owner=useRef<{alive:boolean;store:PrivateRecordingStore;recording:PrivateRecordingRuntime;runtime:Runtime|null;unsubscribe?:()=>void}|null>(null);
  const saved=useRef<Transfer|null>(null),flight=useRef(false);
  const noteSection=useRef<HTMLDivElement>(null);
  const reportDraftLock=useCallback((value:boolean)=>{setDraftLocked(value);onDraftLock(value);},[onDraftLock]);
  useEffect(()=>{if(showDraft){const heading=noteSection.current?.querySelector<HTMLElement>('h3');if(heading){heading.tabIndex=-1;heading.focus();heading.scrollIntoView({block:'start'});}}},[showDraft]);
  const current=()=>!!owner.current?.alive&&live.current.identity===identity&&live.current.entry.scope===entry.scope&&live.current.entry.recordingId===entry.recordingId&&live.current.workspace.id===workspace.id&&live.current.isCurrent();
  useEffect(()=>{let alive=true;
    void(async()=>{
      const store=await openPrivateRecordingStore(entry.scope,entry.platform);
      let recording:PrivateRecordingRuntime;
      try{recording=await PrivateRecordingRuntime.open({scope:entry.scope,platform:entry.platform,isCurrent:()=>alive&&live.current.isCurrent(),openStore:async()=>store},{recordingId:entry.recordingId,title:'Saved recording'});}catch(cause){store.close();throw cause;}
      if(!alive){await recording.close();return;}
      const selected={alive:true,store,recording,runtime:null as Runtime|null,unsubscribe:undefined as (()=>void)|undefined};owner.current=selected;
      need(recording.snapshot.workspaceId===origin.id&&recording.snapshot.phase==='sealed'&&recording.snapshot.recordedChunks>0);
      const value=await store.read('transfer:'+entry.recordingId);if(!current())return;
      saved.current=value===null?null:validate(value,entry,workspace.id);
      if(saved.current?.receipt){const ledger=new PrivateRecordingLedgerController({identity,team,workspace:origin,store,scope:entry.scope,isCurrent:current});const original=await ledger.readCurrent(entry.recordingId);need(original?.state==='finished');await parsePrivateRecordingReceipt(saved.current.receipt,original.attach);need(current());if(entry.binding)await parseRecordingVisitBinding(entry.binding,saved.current.receipt);}
      setTransfer(saved.current);
      if(saved.current?.admitted)await openRuntime(saved.current.admitted);
      if(current())setReady(true);
    })().catch(()=>{if(alive)setError('This saved recording could not be opened for transcription. Your original audio is retained.');});
    return()=>{alive=false;const selected=owner.current;if(selected){selected.alive=false;selected.unsubscribe?.();void(async()=>{try{await selected.runtime?.close();}finally{await selected.recording.close();}})();}owner.current=null;};
  },[identity,entry.scope,entry.recordingId,workspace.id]);
  async function persist(next:Transfer){need(current()&&owner.current);validate(next,entry,workspace.id);
    await owner.current.store.write('transfer:'+entry.recordingId,saved.current,next);need(current());saved.current=next;setTransfer(next);}
  async function openRuntime(admitted:PreparedCapture){need(current()&&owner.current);const selected=owner.current;
    const opened=await openSavedRecordingRuntime({workspaceId:workspace.id,admitted,identity,scope:entry.scope,recording:selected.recording,
      chunks:saved.current!.admission!.source.chunks,platform:entry.platform,isCurrent:current});
    if(!current()){await opened.close();return;}selected.runtime=opened;selected.unsubscribe=opened.controller.subscribe(setSnapshot);
    if(opened.reviewOnly)setSnapshot({...opened.controller.snapshot,state:'processing',sessionId:admitted.session_id});
  }
  async function transcribe(){if(!ready||flight.current||locked||!workspace.appointment_id||!taskBot?.enabled||!saved.current?.admission&&!consented)return;
    flight.current=true;setBusy(true);setError('');
    try{
      need(current()&&owner.current);const selected=owner.current;
      const ledger=new PrivateRecordingLedgerController({identity,team,workspace:origin,store:selected.store,scope:entry.scope,isCurrent:current});
      const record=await ledger.readCurrent(entry.recordingId);need(record?.state==='finished'&&record.receipt&&record.finish);
      let receipt=await privateRecordingApi.read(identity,record.attach,team,record.receipt.recording_id);need(current());
      const audio=await selected.recording.snapshotForLedger();
      need(audio.phase==='sealed'&&receipt.finish?.manifest_sha256===audio.manifestSHA256&&receipt.finish.chunks===audio.chunks&&receipt.finish.frames===audio.frames);
      let frames=0,chunks=0,signal=false;
      for await(const chunk of selected.recording.savedChunks()){
        frames+=(chunk.wavBytes.length-44)/2;chunks++;
        signal ||= chunk.wavBytes.subarray(44).some(v=>v!==0);
      }
      need(current()&&frames===audio.frames&&chunks===audio.chunks);
      if(!signal)throw Object.assign(new Error('No recorded speech'),{code:'saved_audio_silent'});
      let next=saved.current??{contract:entry.binding?'cosmas.saved-transfer.v2' as const:'cosmas.saved-transfer.v1' as const,...(entry.binding?{binding:entry.binding}:{}),recording_id:entry.recordingId,workspace_id:workspace.id,scope:entry.scope,link_request:null,receipt:null,admission:null,admitted:null};
      if(entry.binding){
        const binding=await privateRecordingApi.readVisitBinding(identity,record.attach,team,receipt);need(current()&&binding&&vendorCanonical(binding)===vendorCanonical(entry.binding)&&binding.target_workspace_id===workspace.id&&binding.appointment_id===workspace.appointment_id);
      }else if(!receipt.link){
        need(workspace.private_draft?.link_receipt_id);
        if(!next.link_request){next={...next,link_request:{idempotency_key:crypto.randomUUID(),expected_workspace_revision:workspace.revision,workspace_link_receipt_id:workspace.private_draft.link_receipt_id}};await persist(next);}
        receipt=await privateRecordingApi.link(identity,record.attach,team,receipt.recording_id,next.link_request!);need(current());
      }
      need(entry.binding||receipt.state==='linked_metadata'&&receipt.link?.workspace_link_receipt_id===workspace.private_draft?.link_receipt_id);
      if(next.receipt)need(vendorCanonical(next.receipt)===vendorCanonical(receipt));
      next={...next,receipt};await persist(next);
      if(!next.admission){
        need(consented&&(entry.binding||receipt.link)&&receipt.finish);
        const {language,...original}=audio.consent;
        next={...next,admission:{key:crypto.randomUUID(),language,attestation:{...original,granted_at:new Date().toISOString()},
          source:{recording_id:receipt.recording_id,...(entry.binding?{origin_workspace_id:origin.id,visit_binding_receipt_id:entry.binding.receipt_id,source_sha256:entry.binding.source_sha256}:{link_receipt_id:receipt.link!.receipt_id,source_sha256:receipt.link!.source_sha256}),
            manifest_sha256:audio.manifestSHA256,chunks:audio.chunks,frames:audio.frames}}};await persist(next);
      }
      if(!next.admitted){const a=next.admission!;
        const admitted=await prepareCapture(workspace.id,identity,a.attestation,a.key,undefined,taskBot.selection,a.language,a.source);need(current());
        next={...next,admitted};await persist(next);}
      if(!selected.runtime)await openRuntime(next.admitted!);need(current()&&selected.runtime);
      await selected.runtime.transcribe();
    }catch(cause){
      const selected=owner.current;
      if(current()&&selected?.runtime?.controller.snapshot.state==='error'&&selected.runtime.controller.snapshot.recordedChunks<(saved.current?.admission?.source.chunks??0)){
        selected.unsubscribe?.();selected.unsubscribe=undefined;
        await selected.runtime.close().catch(()=>{});selected.runtime=null;
        if(current())setSnapshot(null);
      }
      if(current()){
      const code=cause&&typeof cause==='object'&&'code'in cause?cause.code:'';
      setError(code==='saved_audio_silent'?'This recording contains no microphone signal. Play it from Home to check it, or make a new recording with the microphone available.':code==='capture_connection_required'?'Connect your Core account before transcribing. Your recording remains saved on this device.':code==='capture_saved_recording_changed'?'This recording or its visit connection changed. Return Home and reopen the original recording before continuing.':code==='capture_consent_unavailable'?'Scribe could not confirm this transcription consent. Your recording is saved; return Home and resolve consent before continuing.':code==='capture_access_unavailable'||cause instanceof WorkspaceApiError&&[401,403].includes(cause.status)?'Sign in again to continue. Your recording and transfer are saved.':`Transcription could not continue. Your original audio and progress are saved. Choose ${saved.current?.admission?'Continue transcription':'Transcribe recording'} to retry.`);
    }}
    finally{flight.current=false;if(current())setBusy(false);}
  }
  const processing=!!transfer?.admitted&&(snapshot?.state==='processing'||review!==null);
  return <section className="capture-panel saved-transcription" aria-label="Saved recording transcription" data-english-only={transfer?.admission?.language==='en-US'}>
    <h2>{showDraft?'Review your visit note':processing?'Review your transcript':'Transcribe your saved recording'}</h2>
    {workspace.appointment_id&&<><ol aria-label="Transcription steps"><li>Visit confirmed</li><li>{processing?'Audio uploaded':'Send recording to Scribe'}</li><li>Review transcript and save your note</li></ol>
    <p>Your original recording stays on this device. Find it under Home → Recordings on this device.</p></>}
    {!workspace.appointment_id?<p role="status">Choose a visit below, then send this recording to Scribe.</p>:<>
      <p><strong>{workspace.label}</strong> · {owner.current?.recording.snapshot.title}</p>
      {!transfer?.admission&&!processing&&<label className="private-recording-check"><input type="checkbox" checked={consented} disabled={busy||locked} onChange={event=>setConsented(event.target.checked)}/>I confirm everyone agreed to transcription, and this recording belongs to the visit shown above.</label>}
      {!processing&&<button className="team-primary" disabled={!ready||busy||locked||!taskBot?.enabled||!transfer?.admission&&!consented} onClick={()=>void transcribe()}>{busy?'Sending saved recording…':transfer?.admission?'Continue transcription':'Transcribe recording'}</button>}
      {!taskBot?.enabled&&<p role="status">Enable Scribe in team settings to transcribe this recording. Your audio is saved.</p>}
    </>}
    {snapshot&&<p role="status">{showDraft?'Review and edit your visit note below.':review?.working?.note_ready?'Transcript ready. Review it, then continue to your note.':processing?'Audio uploaded. Scribe is preparing your transcript.':`Preparing your saved recording… ${Math.floor(snapshot.recordedChunks/Math.max(1,transfer?.admission?.source.chunks??1)*100)}%`}</p>}
    {error&&<p role="alert">{error}</p>}
    {processing&&transfer?.admitted&&<details className="saved-transcript-review" open={!showDraft}><summary>Review transcript</summary><CreatorReviewPanel workspaceId={workspace.id} sessionId={transfer.admitted.session_id} identity={identity}
      locked={locked||busy||draftLocked} onLock={setReviewLock} onSource={setReview} onContinue={async()=>{await owner.current?.runtime?.releaseUploadedCapture();if(current())setShowDraft(true);}}/></details>}
    {showDraft&&review?.working?.note_ready&&notesEnabled&&transfer?.admitted&&<div ref={noteSection}><CaptureDraftPanel workspaceId={workspace.id} sessionId={transfer.admitted.session_id}
      sourceId={review.working.working_transcript_id} identity={identity} onDraftLock={reportDraftLock} onReviewDraft={onReviewDraft} onCurrentDraft={onCurrentDraft}
      reviewLocked={locked} sourceLocked={reviewLock||busy} taskBot={taskBot} scratchpad={scratchpad} notebookDirty={notebookDirty} onNotebook={onNotebook} simpleFlow/></div>}
  </section>;
}
