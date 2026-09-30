import {CaptureFlowController} from "../../clients/capture/src/configured/flow/controller";
import {EncryptedIndexedDbFlowStore,isEmptyProfilePreparation} from "../../clients/capture/src/configured/flow/encrypted-store";
import {CaptureQueue} from "../../clients/capture/src/queue/capture-queue";
import {BffCaptureQueueTransport} from "../../clients/capture/src/bff/queue-transport";
import type {CiphertextUploadTarget} from "../../clients/capture/src/bff/contracts";
import type {CaptureSource} from "../../clients/capture/src/capture";
import type {CaptureSource as ConfiguredSource} from "../../clients/capture/src/configured/capture";
import type {EncryptedIndexedDbFlowStore as QueueProfileStore} from "../../clients/capture/src/flow/encrypted-store";
import {BffResponseError} from "../../clients/capture/src/bff/http-client";
import {workspaceCaptureBff,CAPTURE_LONG_VISITS_BUILD,CAPTURE_RECOVERY_BUILD} from "./capture-api";
import {creatorReviewApi} from "./creator-review-api";
import type {openCaptureQueueStorage} from "./capture-storage";
import type {AuthenticatedWorkspaceIdentity} from "./workspace-api";
import type {CaptureRuntime} from "./capture-runtime";
import {releaseEmptyPreparationTransfer} from '../../clients/capture/src/flow/empty-preparation-transfer';
import {checkEmptyProfilePreparation} from './empty-profile-preparation';

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
    const createController=()=>new CaptureFlowController({bff,profiles:bff,flowStore:flow,queue:new CaptureQueue(queue.storage),source,
      ...(CAPTURE_LONG_VISITS_BUILD?{standardContinuousCapture:true as const}:{}),
      queueTransport:new BffCaptureQueueTransport(bff,options.upload)});
    controller=createController();
    let reviewOnly=false,recoverEmpty=false,restored=false;
    const checkEmpty=()=>checkEmptyProfilePreparation({sessionId,flow,queue:queue.storage,bff,signal:abort.signal});
    try {restored=await controller.restore();}
    catch(error){
      // Only a rejected optional-profile setup can offer this action. Network,
      // permission, receipt and later key/lease errors keep their normal recovery.
      if(options.native||!CAPTURE_LONG_VISITS_BUILD||!CAPTURE_RECOVERY_BUILD||view.status!=="created"||
        !isEmptyProfilePreparation(preparing)||!(error instanceof BffResponseError)||
        error.status!==409||error.code!=="capture_source_unavailable")throw error;
      try {await checkEmpty();} catch {throw error;}
      recoverEmpty=true;
    }
    if(!restored&&!recoverEmpty){
      if(!["created","capturing"].includes(view.status))reviewOnly=true;
      else{
        if(view.status==="capturing")throw new BffResponseError(409,"capture_saved_session_changed",null);
        // Configured Scribe provides capacity through its standard capabilities
        // and lease protocol. Fresh sessions must not require the optional
        // profile endpoint; restore above preserves any existing profile intent.
        await controller.prepareConfigured(sessionId);
      }
    }
    const unavailable=async()=>{throw new BffResponseError(409,"capture_source_unavailable",null);};
    let closed=false,closing:Promise<void>|null=null;
    let transitioned=false,continuing:Promise<CaptureRuntime>|null=null;
    const wrap=(emptyRecovery=false):CaptureRuntime=>{
      const current=controller!;
      const inertSnapshot={...current.snapshot,state:emptyRecovery?"ready" as const:"processing" as const,
        statusCode:emptyRecovery?"capture_preparation_recovery":"capture_processing",sessionId};
      return {sourceKind:source.kind,supportsContinuation:!reviewOnly&&!emptyRecovery&&options.native,
      ...(emptyRecovery?{recoveryOnly:true,continuePreparation:()=>{
        if(closed||closing)return unavailable() as Promise<CaptureRuntime>;
        return continuing??=(async()=>{
          if(!transitioned){
            const expected=await checkEmpty();
            await flow.continueEmptyProfilePreparation(expected);
            transitioned=true;
          }
          await controller!.deactivate();
          controller=createController();
          if(!await controller.restore())throw new BffResponseError(409,"capture_saved_session_changed",null);
          return wrap();
        })().finally(()=>{continuing=null;});
      }}:{}),
      controller:reviewOnly||emptyRecovery?{
        snapshot:inertSnapshot,subscribe:listener=>{listener(inertSnapshot);return()=>{};},
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
          await continuing?.catch(()=>undefined);
          if(!reviewOnly)await controller!.deactivate();
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
    };};
    return wrap(recoverEmpty);
  }catch(error){flow.close();throw error;}
}
