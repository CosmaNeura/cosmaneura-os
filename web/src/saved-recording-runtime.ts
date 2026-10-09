import {CaptureFlowController} from '../../clients/capture/src/configured/flow/controller';
import {EncryptedIndexedDbFlowStore} from '../../clients/capture/src/configured/flow/encrypted-store';
import {EncryptedIndexedDbFlowStore as QueueProfileStore} from '../../clients/capture/src/flow/encrypted-store';
import {CaptureQueue} from '../../clients/capture/src/queue/capture-queue';
import {BffCaptureQueueTransport} from '../../clients/capture/src/bff/queue-transport';
import {HttpCiphertextUploadTarget} from '../../clients/capture/src/bff/upload-target';
import {QueueInvariantError} from '../../clients/capture/src/queue/errors';
import {workspaceCaptureBff,type PreparedCapture} from './capture-api';
import {creatorReviewApi} from './creator-review-api';
import {openCaptureQueueStorage} from './capture-storage';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {SavedRecordingSource} from './saved-recording-source';
import type {PrivateRecordingRuntime} from './private-recording-runtime';
import {acquireCaptureFlowLock} from '../../clients/capture/src/flow/capture-lock';

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

/** Separate session stores preserve the original clip and any live visit queue. */
export async function openSavedRecordingRuntime(options:{workspaceId:string;admitted:PreparedCapture;identity:AuthenticatedWorkspaceIdentity;
  scope:string;recording:PrivateRecordingRuntime;chunks:number;platform:'ios'|'desktop';isCurrent:()=>boolean}){
  const {workspaceId,admitted,identity}=options,sessionId=admitted.session_id;
  const abort=new AbortController();let active=true,task:Promise<void>|null=null;
  const current=()=>active&&!abort.signal.aborted&&options.isCurrent();
  const unlock=await acquireCaptureFlowLock();
  let flow:EncryptedIndexedDbFlowStore;
  try{flow=await EncryptedIndexedDbFlowStore.open({databaseName:`cosmas-saved-flow:v1:${options.scope}:${workspaceId}:${sessionId}`});}catch(error){await unlock();throw error;}
  let profiles:QueueProfileStore;
  try{profiles=await QueueProfileStore.open({databaseName:`cosmas-saved-profile:v1:${options.scope}:${workspaceId}:${sessionId}`});}catch(error){flow.close();await unlock();throw error;}
  let queue:Awaited<ReturnType<typeof openCaptureQueueStorage>>|undefined,controller:CaptureFlowController|undefined;
  try{
    const desired=options.platform==='ios'?'native':'browser',previous=await profiles.getQueueStorageKind(sessionId);
    if(previous&&previous!==desired)throw new QueueInvariantError('queue_storage_profile_changed');
    // The UUID namespace is the unique server session, separate from the visit's live queue.
    queue=await openCaptureQueueStorage(sessionId,sessionId,options.platform==='ios');
    await profiles.claimQueueStorageKind(sessionId,queue.kind);
    const source=new SavedRecordingSource(options.recording,current);
    const bff=workspaceCaptureBff(workspaceId,sessionId,identity,abort.signal);
    const origins=String(import.meta.env.VITE_CAPTURE_UPLOAD_ORIGINS??'').split(',').map(v=>v.trim()).filter(Boolean);
    const upload=new HttpCiphertextUploadTarget(origins,(input,init)=>fetch(input,{...init,
      signal:init?.signal?AbortSignal.any([init.signal,abort.signal]):abort.signal}));
    controller=new CaptureFlowController({bff,profiles:bff,flowStore:flow,queue:new CaptureQueue(queue.storage),source,
      queueTransport:new BffCaptureQueueTransport(bff,upload)});
    const view=await creatorReviewApi(workspaceId,sessionId,identity,abort.signal).read();
    if(!current())throw new QueueInvariantError('capture_access_unavailable');
    let reviewOnly=false;
    if(!await controller.restore()){
      if(!['created','capturing'].includes(view.status))reviewOnly=true;
      else if(view.status==='capturing')throw new QueueInvariantError('capture_saved_session_changed');
      else await controller.prepareConfigured(sessionId);
    }
    const selected=controller;
    return {controller:selected,reviewOnly,transcribe:()=>{
      if(reviewOnly)return Promise.resolve();
      return task??=(importSavedChunks(selected,source,options.chunks,current).finally(()=>{task=null;}));
    },releaseUploadedCapture:()=>reviewOnly?Promise.resolve():selected.releaseUploadedCapture(),
    close:async()=>{if(!active)return;active=false;abort.abort();await source.stop();await task?.catch(()=>{});
      try{await selected.deactivate();}finally{flow.close();profiles.close();queue?.close();await unlock();}}};
  }catch(error){active=false;abort.abort();try{await controller?.deactivate();}finally{flow.close();profiles.close();queue?.close();await unlock();}throw error;}
}
