import { registerPlugin } from "@capacitor/core";
import type { CaptureSource } from "../capture";
import type { CaptureFlowStore } from "../flow/types";
import { CaptureStopAcknowledgementPending } from "../capture/stop-confirmation";
import { QueueInvariantError } from "../../queue/errors";

interface NativeSourcePlugin {
  prepareProviderSource(value: {revision:string;workspaceId:string;sessionId:string;leaseId:string;
    leaseReceiptId:string;leaseGeneration:number;captureAuthorizedUntil:string;firstSequenceNumber?:number}):Promise<unknown>;
  closeProviderSource(value:{sessionId:string}):Promise<void>;
}
const plugin = registerPlugin<NativeSourcePlugin>("CosmasWorkspaceAuth");

/** Scribe's native host lifecycle, bound to the combined workspace's saved flow.
 * JS passes lease metadata only; the native owner generates and retains its proof.
 */
export function ownedWorkspaceSource(source:CaptureSource, flow:Pick<CaptureFlowStore,"getActiveCaptureState">,
  workspaceId:string, sessionId:string, identity:{revision:string;isCurrent:()=>boolean},
  native:NativeSourcePlugin=plugin):CaptureSource {
  let stopping:Promise<void>|null=null;
  const current=()=>{if(!identity.isCurrent())throw new QueueInvariantError("capture_access_unavailable");};
  return {
    kind:source.kind,
    supportsContinuousCapture:async()=>{current();return source.supportsContinuousCapture?.()??false;},
    ...(source.extend?{extend:async(value:Parameters<NonNullable<CaptureSource['extend']>>[0])=>{
      current();if(stopping)throw new QueueInvariantError("capture_state_conflict");
      await source.extend!(value);current();
    }}:{}),
    start:async options=>{
      current();if(stopping||options.signal?.aborted)throw new QueueInvariantError("capture_state_conflict");
      const active=await flow.getActiveCaptureState();current();
      if(!active||active.sessionId!==sessionId||active.phase!=="recording"||active.reviewAfterUpload!==true||
        (active.channel??"microphone")!=="microphone"||active.lease.session_id!==sessionId||
        !active.captureAuthorizedUntil||Date.parse(active.captureAuthorizedUntil)<=Date.now()||
        Date.parse(active.captureAuthorizedUntil)>Date.parse(active.lease.expires_at))throw new QueueInvariantError("capture_state_conflict");
      const prepared={revision:identity.revision,workspaceId,sessionId,leaseId:active.lease.lease_id,
        leaseReceiptId:active.lease.receipt_id,leaseGeneration:active.lease.generation,
        captureAuthorizedUntil:active.captureAuthorizedUntil,
        ...(active.continuation?.firstSequenceNumber?{firstSequenceNumber:active.continuation.firstSequenceNumber}:{})};
      const reply=await native.prepareProviderSource(prepared);current();
      if(!reply||typeof reply!=="object"||Array.isArray(reply)||Object.keys(reply).sort().join(",")!=="revision,sessionId"||
        (reply as {revision:unknown}).revision!==identity.revision||(reply as {sessionId:unknown}).sessionId!==sessionId)
        throw new QueueInvariantError("capture_state_conflict");
      const checked=await flow.getActiveCaptureState();current();
      if(stopping||options.signal?.aborted||!checked||checked.phase!=="recording"||checked.sessionId!==sessionId||
        checked.lease.lease_id!==prepared.leaseId||checked.lease.receipt_id!==prepared.leaseReceiptId||
        checked.lease.generation!==prepared.leaseGeneration||checked.captureAuthorizedUntil!==prepared.captureAuthorizedUntil||
        (checked.continuation?.firstSequenceNumber??0)!==(prepared.firstSequenceNumber??0))throw new QueueInvariantError("capture_state_conflict");
      await source.start(options);
    },
    stop:()=>stopping??=(async()=>{
      await source.stop();
      try{await native.closeProviderSource({sessionId});}
      catch{throw new CaptureStopAcknowledgementPending();}
    })().finally(()=>{stopping=null;}),
  };
}
