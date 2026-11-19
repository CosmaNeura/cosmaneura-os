import {CaptureFlowController} from '../../clients/capture/src/configured/flow/controller';
import {EncryptedIndexedDbFlowStore} from '../../clients/capture/src/configured/flow/encrypted-store';
import {EncryptedIndexedDbFlowStore as QueueProfileStore} from '../../clients/capture/src/flow/encrypted-store';
import {CaptureQueue} from '../../clients/capture/src/queue/capture-queue';
import {BffCaptureQueueTransport} from '../../clients/capture/src/bff/queue-transport';
import {HttpCiphertextUploadTarget} from '../../clients/capture/src/bff/upload-target';
import {QueueInvariantError} from '../../clients/capture/src/queue/errors';
import {workspaceCaptureBff,type PreparedCapture} from './capture-api';
import {creatorReviewApi} from './creator-review-api';
import {captureQueueDatabaseName,openCaptureQueueStorage} from './capture-storage';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {SavedRecordingSource} from './saved-recording-source';
import type {AudioRetentionClock,AudioRetentionPolicy,PrivateRecordingRuntime,PrivateRecordingStore} from './private-recording-runtime';
import {isAudioRetentionProtected,markTransferRetentionReleased} from './private-recording-runtime';
import {audioRetentionEffective,refuseExpiredAudio} from './private-recording-retention';
import {acquireCaptureFlowLock} from '../../clients/capture/src/flow/capture-lock';
import {workspaceAuthHeaders} from './workspace-auth-headers';
import {workspaceApiBase} from './workspace-base';

/** Session-scoped import queue DB name (same helper the browser queue open uses). */
export function savedRecordingImportQueueDatabaseName(sessionId:string){return captureQueueDatabaseName(sessionId);}

export async function importSavedChunks(controller:Pick<CaptureFlowController,'snapshot'|'startRecording'|'pauseRecording'|'prepareContinuation'|'stopRecording'|'resumePendingWork'>,
  source:SavedRecordingSource,total:number,current:()=>boolean):Promise<void>{
  const check=()=>{if(!current())throw new QueueInvariantError('capture_access_unavailable');};
  check();
  if(controller.snapshot.state==='uploading'||controller.snapshot.state==='error'){
    if(controller.snapshot.recordedChunks!==total)throw new QueueInvariantError('capture_saved_session_changed');
    await controller.resumePendingWork();return;
  }
  if(controller.snapshot.state==='processing')return;
  while(controller.snapshot.recordedChunks<total){
    check();
    if(controller.snapshot.state==='paused')await controller.prepareContinuation();
    check();await controller.startRecording();
    const first=controller.snapshot.recordedChunks;
    try{const imported=await source.feed(first,total);check();
      if(imported<1||controller.snapshot.recordedChunks!==first+imported)throw new QueueInvariantError('capture_chunk_position_conflict');
    }catch(error){await controller.pauseRecording().catch(()=>{});throw error;}
    if(controller.snapshot.recordedChunks<total)await controller.pauseRecording();
  }
  check();
  if(controller.snapshot.recordedChunks!==total)throw new QueueInvariantError('capture_saved_session_changed');
  await controller.stopRecording();
}

/**
 * Saved-import queue/flow/profile DB names. All include `sessionId` so PCM is not
 * duplicated into the visit's long-lived workspace capture-queue
 * (`cosmas-capture-queue:${workspaceId}`). Browser queue open uses sessionId as
 * the first `openCaptureQueueStorage` arg → `cosmas-capture-queue:${sessionId}`.
 */
export function savedRecordingImportStoreNames(input:{scope:string;workspaceId:string;sessionId:string}):{
  flow:string;profile:string;captureQueueOpenArgs:{workspaceId:string;sessionId:string};
}{
  const {scope,workspaceId,sessionId}=input;
  return {
    flow:`cosmas-saved-flow:v1:${scope}:${workspaceId}:${sessionId}`,
    profile:`cosmas-saved-profile:v1:${scope}:${workspaceId}:${sessionId}`,
    // Intentionally sessionId (not visit workspaceId): session-scoped import queue.
    captureQueueOpenArgs:{workspaceId:sessionId,sessionId},
  };
}

/** Separate session stores preserve the original clip and any live visit queue. */
export async function openSavedRecordingRuntime(options:{workspaceId:string;admitted:PreparedCapture;identity:AuthenticatedWorkspaceIdentity;
  scope:string;recording:PrivateRecordingRuntime;chunks:number;platform:'ios'|'desktop';isCurrent:()=>boolean;
  /** T1: refuse expired audio when both switches are on. Absent means off. */
  audioRetention?:AudioRetentionPolicy|null;now?:AudioRetentionClock;
  /** Private-recording store for retention protection + release marker (never deletes transfer:). */
  store?:PrivateRecordingStore}){
  const {workspaceId,admitted,identity}=options,sessionId=admitted.session_id;
  // Refuse before any import/transfer when both switches are on. Safe code; no audio bytes.
  // Protected rows (open owner, attach/finish pending, unreleased transfer:) skip refuse.
  // Never delete the panel's transfer:<recordingId> row — that breaks CAS persist/resume.
  let transferRecordingId:string|undefined=options.recording.snapshot?.recordingId;
  if(audioRetentionEffective(options.audioRetention)){
    const proof=await options.recording.snapshotForLedger();
    transferRecordingId??=proof.recordingId;
    const protectedRow=options.store?await isAudioRetentionProtected(options.store,proof.recordingId):false;
    if(!protectedRow){
      const ended=options.recording.snapshot?.endedAt;
      refuseExpiredAudio({recordingId:proof.recordingId,phase:proof.phase,endedAt:ended,updatedAt:proof.updatedAt,
        chunks:Array.from({length:proof.chunks},(_,sequence)=>({sequence}))},options.now?.()??Date.now(),options.audioRetention);
    }
  }
  /** Ends sweep protection only; leaves transfer:<id> intact for panel persist/relaunch. */
  const releaseTransferProtection=async()=>{
    if(!audioRetentionEffective(options.audioRetention)||!options.store||!transferRecordingId)return;
    const iso=new Date(options.now?.()??Date.now()).toISOString();
    try{await markTransferRetentionReleased(options.store,transferRecordingId,iso);}catch{/* best-effort marker */}
  };
  const abort=new AbortController();let active=true,task:Promise<void>|null=null;
  let reference:string|null=null;
  const current=()=>active&&!abort.signal.aborted&&options.isCurrent();
  const unlock=await acquireCaptureFlowLock();
  const stores=savedRecordingImportStoreNames({scope:options.scope,workspaceId,sessionId});
  let flow:EncryptedIndexedDbFlowStore;
  try{flow=await EncryptedIndexedDbFlowStore.open({databaseName:stores.flow});}catch(error){await unlock();throw error;}
  let profiles:QueueProfileStore;
  try{profiles=await QueueProfileStore.open({databaseName:stores.profile});}catch(error){flow.close();await unlock();throw error;}
  let queue:Awaited<ReturnType<typeof openCaptureQueueStorage>>|undefined,controller:CaptureFlowController|undefined;
  try{
    const desired=options.platform==='ios'?'native':'browser',previous=await profiles.getQueueStorageKind(sessionId);
    if(previous&&previous!==desired)throw new QueueInvariantError('queue_storage_profile_changed');
    // Session-scoped import queue — not the visit's long-lived private-recording / workspace queue.
    queue=await openCaptureQueueStorage(stores.captureQueueOpenArgs.workspaceId,stores.captureQueueOpenArgs.sessionId,options.platform==='ios');
    await profiles.claimQueueStorageKind(sessionId,queue.kind);
    const source=new SavedRecordingSource(options.recording,current);
    const bff=workspaceCaptureBff(workspaceId,sessionId,identity,abort.signal,(kind,status)=>{
      // Both values come from this closed operation adapter, never a response body.
      reference=`${kind}_response_${status}`;
    });
    const origins=String(import.meta.env.VITE_CAPTURE_UPLOAD_ORIGINS??'').split(',').map(v=>v.trim()).filter(Boolean);
    const apiBase=workspaceApiBase(identity);
    const apiOrigin=new URL(apiBase).origin;
    const authorizeCosmaBot=origins.length===1&&origins[0]===apiOrigin
      ?async()=>{const headers=await workspaceAuthHeaders(identity,apiBase);headers.set('Content-Type','application/octet-stream');return headers;}
      :undefined;
    const upload=new HttpCiphertextUploadTarget(origins,async(input,init)=>{
      try{
        const response=await fetch(input,{...init,signal:init?.signal?AbortSignal.any([init.signal,abort.signal]):abort.signal});
        if(response.status!==201)reference=`audio_upload_response_${response.status}`;
        return response;
      }catch(error){reference='audio_upload_response_unconfirmed';throw error;}
    },authorizeCosmaBot);
    const captureQueue=new CaptureQueue(queue.storage),transport=new BffCaptureQueueTransport(bff,upload);
    controller=new CaptureFlowController({bff,profiles:bff,flowStore:flow,queue:captureQueue,source,
      queueTransport:transport});
    const activeFlow=await flow.getActiveCaptureState();
    if(!current())throw new QueueInvariantError('capture_access_unavailable');
    if(activeFlow&&activeFlow.sessionId!==sessionId)throw new QueueInvariantError('capture_saved_session_changed');
    let reviewOnly=false;
    let provenComplete=false;
    if(activeFlow?.reviewAfterUpload===true&&activeFlow.phase==='processing'){
      // This encrypted terminal record proves upload, not transcript readiness.
      // The mounted review panel reauthorizes every actual transcript read.
      if(activeFlow.recordedChunks!==options.chunks)
        throw new QueueInvariantError('capture_saved_session_changed');
      if(!await controller.restore()||controller.snapshot.state!=='processing'||
        controller.snapshot.sessionId!==sessionId||controller.snapshot.recordedChunks!==options.chunks)
        throw new QueueInvariantError('capture_saved_session_changed');
      provenComplete=true;
    }else{
      const view=await creatorReviewApi(workspaceId,sessionId,identity,abort.signal).read();
      if(!current())throw new QueueInvariantError('capture_access_unavailable');
      if(!await controller.restore()){
        if(!['created','capturing'].includes(view.status)){reviewOnly=true;provenComplete=true;}
        else if(view.status==='capturing')throw new QueueInvariantError('capture_saved_session_changed');
        else await controller.prepareConfigured(sessionId);
      }
    }
    if(!current())throw new QueueInvariantError('capture_access_unavailable');
    // Release only on proven completion (reviewOnly or restored processing) — never on mere admitted.
    if(provenComplete)await releaseTransferProtection();
    const selected=controller;
    /** Drop session-scoped import-queue IndexedDB only when retention is effective (identical to main when off). */
    const dropImportQueueCopy=()=>{
      if(!audioRetentionEffective(options.audioRetention))return;
      if(options.platform!=='desktop'||typeof indexedDB==='undefined')return;
      try{indexedDB.deleteDatabase(savedRecordingImportQueueDatabaseName(sessionId));}catch{/* best-effort bound */}
    };
    return {controller:selected,reviewOnly,transcribe:()=>{
      // Terminal success (review-only or imported chunks): release sweep protection when retention is on.
      // Never delete transfer:<id> — panel CAS persist/relaunch needs that row.
      if(reviewOnly)return releaseTransferProtection();
      if(!task)reference=null;
      // Outer .finally clears task so a sync rejection cannot stick on the runtime.
      return task??=(async()=>{
        if(!current())throw new QueueInvariantError('capture_access_unavailable');
        if(selected.snapshot.state==='error'||selected.snapshot.state==='uploading'){
          await captureQueue.retryRejectedUploads(sessionId,transport);
        }
        await importSavedChunks(selected,source,options.chunks,current);
        await releaseTransferProtection();
      })().finally(()=>{task=null;});
    },releaseUploadedCapture:async()=>{
      if(reviewOnly)return;
      // Switches off: identical to main — only releaseUploadedCapture, leave queue open.
      if(!audioRetentionEffective(options.audioRetention))return selected.releaseUploadedCapture();
      await selected.releaseUploadedCapture();
      queue?.close();queue=undefined;dropImportQueueCopy();
    },
    uploadProgress:async()=>{
      if(!queue)return {confirmed:0,total:options.chunks,reference:reference??null};
      const rows=await queue.storage.listMetadata();
      if(!current())throw new QueueInvariantError('capture_access_unavailable');
      const terminal=rows.flatMap(row=>[row.retry.upload.terminalCode,row.retry.registration.terminalCode])
        .find(code=>code==='upload_rejected'||code==='upload_target_rejected'||code==='chunk_receipt_reservation_mismatch'||code==='registration_receipt_mismatch');
      return {confirmed:rows.filter(row=>row.reservation.sessionId===sessionId&&(row.state==='registered'||row.state==='purged')).length,
        total:options.chunks,reference:reference??terminal??null};
    },
    close:async()=>{if(!active)return;active=false;abort.abort();await source.stop();await task?.catch(()=>{});
      try{await selected.deactivate();}finally{flow.close();profiles.close();queue?.close();queue=undefined;await unlock();}}};
  }catch(error){active=false;abort.abort();try{await controller?.deactivate();}finally{flow.close();profiles.close();queue?.close();await unlock();}throw error;}
}
