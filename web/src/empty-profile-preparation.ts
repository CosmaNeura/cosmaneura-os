import {MAX_AGGREGATE_PLAINTEXT_BYTES} from '@cosmaneura-scribe/capture-protocol';
import {EncryptedIndexedDbFlowStore,isEmptyProfilePreparation} from '../../clients/capture/src/configured/flow/encrypted-store';
import type {ConfiguredCapturePreparationState} from '../../clients/capture/src/configured/flow/types';
import type {CaptureQueueStorage} from '../../clients/capture/src/queue/types';
import type {WorkspaceCaptureBff} from '../../clients/capture/src/bff/workspace-client';
import {validateProfileCapabilities} from '../../clients/capture/src/bff/profile-contracts';
import {BffResponseError} from '../../clients/capture/src/bff/http-client';

/** Read-only proof before offering, and again before accepting, explicit recovery.
 * Standard capabilities remain server enforced. This never selects a different
 * remote profile or replaces a remote key; an unknown binding will fail normally.
 */
export async function checkEmptyProfilePreparation(options:{sessionId:string;flow:EncryptedIndexedDbFlowStore;
  queue:CaptureQueueStorage;bff:WorkspaceCaptureBff;signal:AbortSignal}):Promise<ConfiguredCapturePreparationState>{
  const {flow,sessionId,signal}=options;
  signal.throwIfAborted();
  const [preparation,active,key,keyState,intents,rows]=await Promise.all([
    flow.getPreparationState(),flow.getActiveCaptureState(),flow.getSessionKey(sessionId),
    flow.getSessionKeyState(sessionId),flow.listReservationIntents(),options.queue.listMetadata(),
  ]);
  const conflict=()=>new BffResponseError(409,'capture_saved_session_changed',null);
  if(!isEmptyProfilePreparation(preparation)||preparation.sessionId!==sessionId||active||key||keyState||
    intents.length||rows.some(row=>row.state!=='purged'))throw conflict();
  // The standard lease-state receipt retains even expired/closed leases. A
  // created session with no issued lease cannot have acquired protocol audio.
  // Recovery history is optional and is not needed for this untouched setup.
  const state=await options.bff.getCaptureLeaseState(sessionId);
  if(Object.keys(state).sort().join(',')!=='current_lease,lease_closed,session_id,session_status'||
    state.session_id!==sessionId||state.session_status!=='created'||state.current_lease!==null||state.lease_closed!==false)
    throw conflict();
  const capabilities=validateProfileCapabilities(await options.bff.getCapabilities(sessionId),null);
  if(capabilities.remaining_aggregate_plaintext_bytes!==(capabilities.max_chunks===1000?67108864:MAX_AGGREGATE_PLAINTEXT_BYTES))
    throw conflict();
  signal.throwIfAborted();
  return preparation;
}
