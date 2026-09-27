import { creatorReviewApi } from "./creator-review-api";
import { openConfiguredWorkspaceRuntime } from "./configured-capture-runtime";
import type { PreparedCapture } from "./capture-api";
import { CaptureFlowController } from "../../clients/capture/src/flow/controller";
import { EncryptedIndexedDbFlowStore } from "../../clients/capture/src/flow/encrypted-store";
import { acquireCaptureFlowLock } from "../../clients/capture/src/flow/capture-lock";
import { CaptureQueue } from "../../clients/capture/src/queue/capture-queue";
import { BffCaptureQueueTransport } from "../../clients/capture/src/bff/queue-transport";
import { HttpCiphertextUploadTarget } from "../../clients/capture/src/bff/upload-target";
import { createCaptureSource, IOS_NATIVE_PCM_CAPTURE_ENABLED, isIosNativePlatform } from "../../clients/capture/src/capture-source-factory";
import { BffResponseError } from "../../clients/capture/src/bff/http-client";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";
import { CAPTURE_RECOVERY_BUILD, CAPTURE_SOURCE_BUILD, CAPTURE_LONG_VISITS_BUILD, workspaceCaptureBff } from "./capture-api";
import { bindCaptureQueueStorage, openCaptureQueueStorage } from "./capture-storage";
import {openDesktopCaptureRuntime} from './desktop-capture-runtime';
import {openNativeCaptureRuntime} from './native-capture-runtime';
import {EncryptedIndexedDbQueueStorage} from '../../clients/capture/src/storage/encrypted-indexeddb';
import type {NativeRecorderSnapshot} from '../../clients/capture/src/native/owned-recorder';
import type {MicrophoneInput} from '../../clients/capture/src/native/microphone-input';
import type {ProviderRecorderSnapshot} from '../../clients/capture/src/configured/provider-binding';
import {hasEmptyPreparationTransfer,transferEmptyPreparation} from '../../clients/capture/src/flow/empty-preparation-transfer';

export interface CaptureRuntime {
  controller: Pick<CaptureFlowController, "snapshot" | "subscribe" | "startRecording" |
    "stopRecording" | "resumePendingWork" | "acknowledgeGap" | "finishInterruptedCapture" | "refreshTranscriptionStatus"> & {
      pauseRecording?:()=>Promise<void>;refreshPermissions?:()=>Promise<void>;
      selectMicrophoneInput?:(input:MicrophoneInput)=>Promise<void>;
      snapshot:CaptureFlowController['snapshot'] & {desktop?:ProviderRecorderSnapshot['desktop'];native?:NativeRecorderSnapshot['native']}};
  captureMode?: 'desktop_meeting' | 'native_microphone';
  supportsContinuation?: boolean;
  recoveryOnly?: boolean;
  canFinishRecovery?: boolean;
  continuePreparation?: () => Promise<CaptureRuntime>;
  releaseUploadedCapture?: () => Promise<void>;
  sourceKind: "synthetic" | "microphone";
  close: () => Promise<void>;
}
export type CaptureRuntimeFactory = (workspaceId: string, sessionId: string,
  identity: AuthenticatedWorkspaceIdentity, configured?: PreparedCapture["configured_capture"], mode?:'desktop_meeting') => Promise<CaptureRuntime>;

export const openCaptureRuntime: CaptureRuntimeFactory = async (workspaceId, sessionId, identity, configured, mode) => {
  const origins = String(import.meta.env.VITE_CAPTURE_UPLOAD_ORIGINS ?? "").split(",").map(value => value.trim()).filter(Boolean);
  if (!origins.length) throw new BffResponseError(503, "capture_connection_required", null);
  const abort = new AbortController();
  const uploadTarget = new HttpCiphertextUploadTarget(origins, (input, init) => fetch(input, {
    ...init, signal: init?.signal ? AbortSignal.any([init.signal, abort.signal]) : abort.signal,
  }));
  const release = await acquireCaptureFlowLock();
  let flow: EncryptedIndexedDbFlowStore | undefined;
  let queueStore: Awaited<ReturnType<typeof openCaptureQueueStorage>> | undefined;
  let controller: CaptureFlowController | undefined;
  try {
    const native = IOS_NATIVE_PCM_CAPTURE_ENABLED && await isIosNativePlatform();
    const source = await createCaptureSource({iosNativePlatformEligible: native});
    flow = await EncryptedIndexedDbFlowStore.open({ databaseName: `cosmas-capture-flow:${workspaceId}` });
    const sourceDatabase=`cosmas-capture-flow:${workspaceId}`, destinationDatabase=`cosmas-configured-flow:v1:${workspaceId}`;
    if(await hasEmptyPreparationTransfer(sourceDatabase,sessionId,destinationDatabase)){
      if(!configured||mode==='desktop_meeting')throw new BffResponseError(409,'capture_saved_session_changed',null);
      await bindCaptureQueueStorage(flow,workspaceId,sessionId,native,false);
      queueStore=await openCaptureQueueStorage(workspaceId,sessionId,native);
      await transferEmptyPreparation({source:sourceDatabase,destination:destinationDatabase,sessionId,kind:queueStore.kind,
        queue:queueStore.storage,bff:workspaceCaptureBff(workspaceId,sessionId,identity,abort.signal)});
      return await openConfiguredWorkspaceRuntime({workspaceId,sessionId,identity,native,source,
        profiles:flow,queue:queueStore,upload:uploadTarget,abort,unlock:release});
    }
    const active = await flow.getActiveCaptureState();
    const preparation = await flow.getPreparationState();
    if (active && active.sessionId !== sessionId || preparation?.sessionId && preparation.sessionId !== sessionId) {
      throw new BffResponseError(409, "capture_saved_session_changed", null);
    }
    const owner = await flow.getCaptureStorageOwner(sessionId);
    if (owner === 'owned:native' || configured && native && owner === null && !active && !preparation && mode !== 'desktop_meeting') {
      if (!native || !configured || active || preparation || mode === 'desktop_meeting')
        throw new BffResponseError(409, 'capture_saved_session_changed', null);
      const {EncryptedIndexedDbFlowStore:ConfiguredStore}=await import('../../clients/capture/src/configured/flow/encrypted-store');
      const prior=await ConfiguredStore.open({databaseName:`cosmas-configured-flow:v1:${workspaceId}`});
      let priorWork: boolean;
      try { priorWork = !!(await prior.getActiveCaptureState() || await prior.getPreparationState()); }
      finally { prior.close(); }
      if (owner === 'owned:native' && priorWork) throw new BffResponseError(409, 'capture_saved_session_changed', null);
      if (!priorWork) {
        if (owner === null) {
          // No old journal/marker is enough only when both old queues are empty.
          const browser = await EncryptedIndexedDbQueueStorage.open({databaseName:`cosmas-capture-queue:${workspaceId}`});
          try {
            if ((await browser.listMetadata()).some(row => row.reservation.sessionId === sessionId && row.state !== 'purged'))
              throw new BffResponseError(409, 'capture_saved_session_changed', null);
          } finally { browser.close(); }
          const previous = await openCaptureQueueStorage(workspaceId, sessionId, true);
          try {
            if ((await previous.storage.listMetadata()).some(row => row.state !== 'purged'))
              throw new BffResponseError(409, 'capture_saved_session_changed', null);
          } finally { previous.close(); }
        }
        await flow.claimNativeRecordingStorage(sessionId);
        const profiles = flow;
        return await openNativeCaptureRuntime({workspaceId, sessionId, identity, upload:uploadTarget, abort,
          release:async()=>{profiles.close();await release();}});
      }
    }
    if(mode==='desktop_meeting'||await flow.usesDesktopCaptureStorage(sessionId)){
      if(!configured||active||preparation)throw new BffResponseError(409,'capture_saved_session_changed',null);
      const {EncryptedIndexedDbFlowStore:ConfiguredStore}=await import('../../clients/capture/src/configured/flow/encrypted-store');
      const prior=await ConfiguredStore.open({databaseName:`cosmas-configured-flow:v1:${workspaceId}`});
      try{if(await prior.getActiveCaptureState()||await prior.getPreparationState())throw new BffResponseError(409,'capture_saved_session_changed',null);}
      finally{prior.close();}
      await flow.claimDesktopCaptureStorage(sessionId);
      const profiles=flow;
      return await openDesktopCaptureRuntime(workspaceId,sessionId,identity,async()=>{profiles.close();await release();});
    }
    await bindCaptureQueueStorage(flow, workspaceId, sessionId, native, active !== null || preparation !== null);
    queueStore = await openCaptureQueueStorage(workspaceId, sessionId, native);
    if(configured&&!active&&!preparation){
      return await openConfiguredWorkspaceRuntime({workspaceId,sessionId,identity,native,source,
        profiles:flow,queue:queueStore,upload:uploadTarget,abort,unlock:release});
    }
    const bff = workspaceCaptureBff(workspaceId, sessionId, identity, abort.signal);
    // Existing journals retain their original key/queue and finish protocol.
    // Physical recording belongs to the configured native-owner flow.
    const recoveryOnly = active !== null || preparation !== null;
    controller = new CaptureFlowController({ bff, profiles: bff, flowStore: flow, renewals: flow, queue: new CaptureQueue(queueStore.storage),
      recoveryOnly,
      ...(CAPTURE_RECOVERY_BUILD ? { recovery: bff } : {}),
      ...(!configured && CAPTURE_SOURCE_BUILD ? { qualifiedSource: bff } : {}),
      queueTransport: new BffCaptureQueueTransport(bff, uploadTarget), source });
    if (configured) {
      if ((active && active.reviewAfterUpload !== true) || (preparation && (preparation.mode !== "core_admitted" || preparation.reviewAfterUpload !== true))) {
        throw new BffResponseError(409, "capture_saved_session_changed", null);
      }
      const view = await creatorReviewApi(workspaceId, sessionId, identity, abort.signal).read();
      if (!await controller.restore()) {
        if (!["created", "capturing"].includes(view.status)) await controller.restoreConfiguredResult(sessionId);
        else {
          // Server capture without this device's journal cannot start a second recorder.
          if (view.status === "capturing") throw new BffResponseError(409, "capture_saved_session_changed", null);
          await controller.prepareAdmitted(sessionId, undefined, true);
        }
      }
    } else if (!await controller.restoreAdmittedResult(sessionId) && !await controller.restore()) {
      await controller.prepareAdmitted(sessionId, CAPTURE_LONG_VISITS_BUILD ? {
        schema_version: "1.0", profile_id: "visit-60m-v1", channels: ["microphone"],
      } : undefined);
    }
    let closed = false;
    const current = controller;
    let transferred=false;
    let transferTask:Promise<CaptureRuntime>|null=null;
    let retiringTransfer:CaptureRuntime|null=null;
    const emptyRecovery=await flow.getCaptureRecoveryState(sessionId);
    const continuePreparation=configured&&recoveryOnly&&CAPTURE_RECOVERY_BUILD&&current.snapshot.recordedChunks===0&&
      (!emptyRecovery||emptyRecovery.phase==='ready'&&emptyRecovery.segments.length===0&&emptyRecovery.gaps.length===0) ? async()=>{
      if(transferred||closed)throw new BffResponseError(409,'capture_saved_session_changed',null);
      return transferTask??=(async()=>{
      await current.close();
      await transferEmptyPreparation({source:sourceDatabase,destination:destinationDatabase,sessionId,kind:queueStore!.kind,
        queue:queueStore!.storage,bff});
      const opened=await openConfiguredWorkspaceRuntime({workspaceId,sessionId,identity,native,source,
        profiles:flow!,queue:queueStore!,upload:uploadTarget,abort,unlock:release});
      transferred=true;return opened;
      })().catch(error=>{transferTask=null;throw error;});
    }:undefined;
    return { controller, recoveryOnly, canFinishRecovery: CAPTURE_RECOVERY_BUILD,
      ...(continuePreparation?{continuePreparation}:{}),
      sourceKind: source.kind, releaseUploadedCapture: () => current.releaseUploadedCapture(), close: async () => {
      if(closed)return;
      if(retiringTransfer){await retiringTransfer.close();closed=true;return;}
      if(transferred)return;
      if(transferTask){
        try{retiringTransfer=await transferTask;}
        catch{/* Failed transfer retains the fence; release this old runtime's handles. */}
        if(retiringTransfer){await retiringTransfer.close();closed=true;return;}
      }
      abort.abort();
      await current.close();
      if (flow && queueStore && !await hasEmptyPreparationTransfer(sourceDatabase,sessionId,destinationDatabase) && await flow.getActiveCaptureState() === null && await flow.getPreparationState() === null &&
          (await queueStore.storage.listMetadata()).every(record => record.state === "purged")) {
        await flow.releaseQueueStorageKind(sessionId, queueStore.kind);
      }
      flow?.close(); queueStore?.close(); await release(); closed = true;
    } };
  } catch (error) {
    abort.abort();
    // Factory setup/restore cannot start a physical source. Release this failed
    // setup's local handles while retaining every encrypted record.
    try { if (controller) await controller.close(); }
    finally { flow?.close(); queueStore?.close(); await release(); }
    throw error;
  }
};
