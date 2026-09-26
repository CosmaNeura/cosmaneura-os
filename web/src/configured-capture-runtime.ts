import {CaptureFlowController} from "../../clients/capture/src/configured/flow/controller";
import {EncryptedIndexedDbFlowStore} from "../../clients/capture/src/configured/flow/encrypted-store";
import {CaptureQueue} from "../../clients/capture/src/queue/capture-queue";
import {BffCaptureQueueTransport} from "../../clients/capture/src/bff/queue-transport";
import type {CiphertextUploadTarget} from "../../clients/capture/src/bff/contracts";
import type {CaptureSource} from "../../clients/capture/src/capture";
import type {CaptureSource as ConfiguredSource} from "../../clients/capture/src/configured/capture";
import type {EncryptedIndexedDbFlowStore as QueueProfileStore} from "../../clients/capture/src/flow/encrypted-store";
import {BffResponseError} from "../../clients/capture/src/bff/http-client";
import {workspaceCaptureBff,CAPTURE_LONG_VISITS_BUILD} from "./capture-api";
import {creatorReviewApi} from "./creator-review-api";
import type {openCaptureQueueStorage} from "./capture-storage";
import type {AuthenticatedWorkspaceIdentity} from "./workspace-api";
import type {CaptureRuntime} from "./capture-runtime";
import {releaseEmptyPreparationTransfer} from '../../clients/capture/src/flow/empty-preparation-transfer';

/** The current Scribe recorder owns configured sessions; legacy recordings keep
 * their existing store/controller. Both use the same authenticated OS transport.
 */
export async function openConfiguredWorkspaceRuntime(options:{workspaceId:string;sessionId:string;
  identity:AuthenticatedWorkspaceIdentity;native:boolean;source:CaptureSource;profiles:QueueProfileStore;
  queue:Awaited<ReturnType<typeof openCaptureQueueStorage>>;upload:CiphertextUploadTarget;
  abort:AbortController;unlock:()=>Promise<void>}):Promise<CaptureRuntime>{
  const {workspaceId,sessionId,identity,profiles,queue,abort}=options;
  const flow=await EncryptedIndexedDbFlowStore.open({databaseName:`cosmas-configured-flow:v1:${workspaceId}`});
  let controller:CaptureFlowController|undefined;
  try{
    const active=await flow.getActiveCaptureState(), preparing=await flow.getPreparationState();
    if(active&&(active.sessionId!==sessionId||active.reviewAfterUpload!==true)||
      preparing&&(preparing.sessionId!==sessionId||preparing.mode!=="configured_core"))
      throw new BffResponseError(409,"capture_saved_session_changed",null);
    await profiles.claimConfiguredCaptureStorage(sessionId,queue.kind);
    const view=await creatorReviewApi(workspaceId,sessionId,identity,abort.signal).read();
    let source:ConfiguredSource={kind:options.source.kind,start:options.source.start.bind(options.source),stop:options.source.stop.bind(options.source)};
    if(options.native){
      if(identity.mode!=="clerk_jwt"||!identity.nativeSession?.isCurrent())
        throw new BffResponseError(401,"capture_access_unavailable",null);
      const [{createCapacitorIosNativeMicrophoneCaptureSource},{ownedWorkspaceSource}]=await Promise.all([
        import("../../clients/capture/src/configured/native/capacitor-ios-native-pcm-bridge"),
        import("../../clients/capture/src/configured/native/workspace-source"),
      ]);
      source=ownedWorkspaceSource(createCapacitorIosNativeMicrophoneCaptureSource(),flow,workspaceId,sessionId,identity.nativeSession);
    }
    const bff=workspaceCaptureBff(workspaceId,sessionId,identity,abort.signal);
    controller=new CaptureFlowController({bff,profiles:bff,flowStore:flow,queue:new CaptureQueue(queue.storage),source,
      queueTransport:new BffCaptureQueueTransport(bff,options.upload)});
    let reviewOnly=false;
    if(!await controller.restore()){
      if(!["created","capturing"].includes(view.status))reviewOnly=true;
      else{
        if(view.status==="capturing")throw new BffResponseError(409,"capture_saved_session_changed",null);
        await controller.prepareConfigured(sessionId,CAPTURE_LONG_VISITS_BUILD?{
          schema_version:"1.0",profile_id:"visit-60m-v1",channels:["microphone"],
        }:undefined);
      }
    }
    const current=controller;
    const unavailable=async()=>{throw new BffResponseError(409,"capture_source_unavailable",null);};
    const reviewSnapshot={...current.snapshot,state:"processing" as const,statusCode:"capture_processing",sessionId};
    let closed=false,closing:Promise<void>|null=null;
    return {sourceKind:source.kind,supportsContinuation:!reviewOnly&&options.native,
      controller:reviewOnly?{
        snapshot:reviewSnapshot,subscribe:listener=>{listener(reviewSnapshot);return()=>{};},
        startRecording:unavailable,stopRecording:unavailable,acknowledgeGap:unavailable,
        finishInterruptedCapture:unavailable,resumePendingWork:async()=>{},refreshTranscriptionStatus:async()=>{},
      }:{
        get snapshot(){return current.snapshot;},subscribe:listener=>current.subscribe(listener),
        startRecording:()=>current.startRecording(),pauseRecording:()=>current.pauseRecording(),
        stopRecording:()=>current.stopRecording(),acknowledgeGap:()=>options.native?current.prepareContinuation():unavailable(),
        finishInterruptedCapture:()=>options.native?current.stopRecording():unavailable(),resumePendingWork:()=>current.resumePendingWork(),
        refreshTranscriptionStatus:()=>current.refreshTranscriptionStatus(),
      },
      releaseUploadedCapture:()=>reviewOnly?Promise.resolve():current.releaseUploadedCapture(),
      close:()=>{
        if(closed)return Promise.resolve();
        return closing??=(async()=>{
          // The native source confirms physical stop and server retirement before
          // releasing storage or the shared recorder lock. Failure stays retryable.
          if(!reviewOnly)await current.deactivate();
          abort.abort();
          if(await flow.getActiveCaptureState()===null&&await flow.getPreparationState()===null&&
            (await queue.storage.listMetadata()).every(record=>record.state==="purged")){
            await releaseEmptyPreparationTransfer(`cosmas-capture-flow:${workspaceId}`,
              `cosmas-configured-flow:v1:${workspaceId}`,sessionId);
            await profiles.releaseQueueStorageKind(sessionId,queue.kind);
          }
          flow.close();profiles.close();queue.close();await options.unlock();closed=true;
        })().catch(error=>{closing=null;throw error;});
      },
    };
  }catch(error){flow.close();throw error;}
}
