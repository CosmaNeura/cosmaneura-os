import type { CaptureBff } from "../bff/contracts";
import { validateRecoveryState, type CaptureRecoveryBff } from "../bff/recovery-contracts";
import { QueueInvariantError } from "../queue/errors";
import { normalizedLease, requireRenewal, sameRenewalIntent, validateRenewalIntent, validateRenewalRecord,
  type CaptureRenewalIntent, type CaptureRenewalRecord, type CaptureRenewalStore } from "./renewal-contract";

/** Persists every stage before the next mutation. Never opens or extends a source. */
export async function exchangeCaptureRenewal(options: {
  intent: CaptureRenewalIntent;
  store: CaptureRenewalStore;
  bff: Pick<CaptureBff, "renewLease" | "reserveChunks">;
  now: () => Date;
  /** Must reflect this physical run, explicit Stop/interruption and old deadline. */
  requireContinuous: () => void;
}): Promise<CaptureRenewalRecord> {
  const { store, bff, now, requireContinuous } = options;
  const intent = validateRenewalIntent(options.intent);
  const current = () => {
    requireContinuous();
    if (now().getTime() >= Date.parse(intent.priorCaptureAuthorizedUntil)) {
      throw new QueueInvariantError("capture_authority_expired");
    }
  };
  current();
  let record = await store.getCaptureRenewal(intent.sessionId, intent.priorLease.lease_id, intent.priorLease.generation);
  if (record === null) {
    record = { intent, lease: null, reservations: null };
    await store.putCaptureRenewal(record);
  }
  requireRenewal(sameRenewalIntent(record.intent, intent));
  if (record.lease === null) {
    current();
    const lease = await bff.renewLease(intent.sessionId, intent.priorLease.lease_id,
      { protocol_version: "1.0", expected_generation: intent.priorLease.generation }, { idempotencyKey: intent.leaseIdempotencyKey });
    record = validateRenewalRecord({ ...record, lease }, now());
    await store.putCaptureRenewal(record);
  }
  current();
  requireRenewal(Date.parse(record.lease!.issued_at) < Date.parse(intent.priorCaptureAuthorizedUntil));
  if (record.reservations === null) {
    const lease = record.lease!;
    const reservations = await bff.reserveChunks(intent.sessionId, { protocol_version: "1.0", channel: "microphone",
      capture_lease_id: lease.lease_id, capture_lease_generation: lease.generation,
      first_sequence_number: intent.firstSequenceNumber, count: intent.count }, { idempotencyKey: intent.reservationIdempotencyKey });
    record = validateRenewalRecord({ ...record, reservations }, now());
    await store.putCaptureRenewal(record);
  }
  current();
  return record;
}

/** Recover only a renewal already committed remotely; no new reservations/start. */
type ReconciliationOptions = {
  intent: CaptureRenewalIntent; store: CaptureRenewalStore;
  bff: Pick<CaptureBff, "renewLease"> & CaptureRecoveryBff; now: () => Date; crypto?: Crypto;
};
export function reconcileInterruptedRenewal(options: ReconciliationOptions): Promise<boolean> {
  return reconcileCommittedRenewal(options, "interrupted");
}

/** A normal Stop retains its terminal segment; never manufacture a recovery gap. */
export function reconcileStoppedRenewal(options: ReconciliationOptions): Promise<boolean> {
  return reconcileCommittedRenewal(options, "stopped");
}

async function reconcileCommittedRenewal(options: ReconciliationOptions, mode: "interrupted" | "stopped"): Promise<boolean> {
  const { store, bff, now } = options;
  const intent = validateRenewalIntent(options.intent);
  let record = await store.getCaptureRenewal(intent.sessionId, intent.priorLease.lease_id, intent.priorLease.generation);
  requireRenewal(record !== null && sameRenewalIntent(record.intent, intent));
  const state = await validateRecoveryState(await bff.getCaptureRecoveryState(intent.sessionId), intent.sessionId, now(), options.crypto);
  requireRenewal(state.current_lease !== null && state.current_lease.lease_id === intent.priorLease.lease_id);
  if (state.current_lease.generation === intent.priorLease.generation) {
    requireRenewal(record.lease === null && JSON.stringify(normalizedLease(state.current_lease, intent.sessionId)) === JSON.stringify(intent.priorLease));
    // Completion may itself have committed with its reply lost. The controller
    // can retry that same completion key; this read grants no new authority.
    requireRenewal(!state.lease_closed && ["created", "capturing"].includes(state.session_status) ||
      mode === "stopped" && state.lease_closed && ["uploaded", "processing", "transcript_ready", "handed_off"].includes(state.session_status));
    return false;
  }
  requireRenewal(!state.lease_closed && ["created", "capturing"].includes(state.session_status));
  requireRenewal(state.current_lease.generation === intent.priorLease.generation + 1);
  if (record.lease === null) {
    // The generation has advanced, so an unknown key cannot create another
    // renewal. Only this request's exact committed reply can be recovered.
    const lease = await bff.renewLease(intent.sessionId, intent.priorLease.lease_id,
      { protocol_version: "1.0", expected_generation: intent.priorLease.generation }, { idempotencyKey: intent.leaseIdempotencyKey });
    record = validateRenewalRecord({ ...record, lease }, now());
    await store.putCaptureRenewal(record);
  }
  requireRenewal(JSON.stringify(record.lease) === JSON.stringify(normalizedLease(state.current_lease, intent.sessionId)));
  await store.applyCaptureRenewal(intent, mode, now());
  return true;
}
