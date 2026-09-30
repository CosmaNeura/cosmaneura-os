// UI rehearsal only. Vite aliases this module only in the isolated clinician lab.
// No microphone, audio files or provider requests are used by these scripted steps.
import type {CaptureAttestation, PreparedCapture} from '../src/capture-api';
import type {CaptureRuntimeFactory} from '../src/capture-runtime';
import type {AuthenticatedWorkspaceIdentity} from '../src/workspace-api';
import type {CaptureFlowSnapshot} from '../../clients/capture/src/flow/controller';
export * from '../src/capture-api';
export type {CaptureRuntime, CaptureRuntimeFactory} from '../src/capture-runtime';

const sessions = new Map<string, {receipt: PreparedCapture; snapshot: CaptureFlowSnapshot}>();
export async function prepareCapture(workspaceId: string, _identity: AuthenticatedWorkspaceIdentity, attestation: CaptureAttestation | null): Promise<PreparedCapture> {
  const prior = sessions.get(workspaceId);
  if (prior) return prior.receipt;
  if (!attestation?.all_parties_consented || !attestation.participant_regions.length) throw {code: 'capture_consent_required'};
  const sessionId = crypto.randomUUID();
  const receipt = {status: 'prepared' as const, workspace_id: workspaceId, session_id: sessionId, consent_record_id: crypto.randomUUID()};
  sessions.set(workspaceId, {receipt, snapshot: {state: 'ready', statusCode: 'ready', sessionId,
    recordedChunks: 0, queuedChunks: 0, elapsedSeconds: 0, remainingBudgetSeconds: 3600,
    remainingAuthoritySeconds: 3600, transcriptionStatus: null, transcript: null}});
  return receipt;
}

export const openCaptureRuntime: CaptureRuntimeFactory = async (workspaceId, sessionId) => {
  const session = sessions.get(workspaceId);
  if (!session || session.receipt.session_id !== sessionId) throw {code: 'capture_saved_session_changed'};
  const listeners = new Set<(snapshot: CaptureFlowSnapshot) => void>();
  let timer: ReturnType<typeof setInterval> | undefined;
  const update = (changes: Partial<CaptureFlowSnapshot>) => {
    session.snapshot = {...session.snapshot, ...changes};
    listeners.forEach(listener => listener(session.snapshot));
  };
  const stopTimer = () => {clearInterval(timer); timer = undefined;};
  const unsupported = async () => {throw new Error('This recovery action is unavailable in the scripted UI rehearsal.');};
  return {sourceKind: 'synthetic', controller: {
    get snapshot() {return session.snapshot;},
    subscribe(listener) {listeners.add(listener); listener(session.snapshot); return () => {listeners.delete(listener);};},
    async startRecording() {
      if (session.snapshot.state !== 'ready') return;
      update({state: 'recording', statusCode: 'recording'});
      timer = setInterval(() => update({elapsedSeconds: session.snapshot.elapsedSeconds + 1}), 1000);
    },
    async stopRecording() {stopTimer(); update({state: 'processing', statusCode: 'capture_processing', recordedChunks: 1});},
    async refreshTranscriptionStatus() {update({state: 'complete', statusCode: 'capture_complete', transcript: {
      id: crypto.randomUUID(), session_id: sessionId, language_code: 'en-US', stt_provider: 'synthetic-fixture', created_at: new Date().toISOString(),
      segments: [{content: 'Scripted example: Jordan prefers an afternoon follow-up. The medication list still needs confirmation. No appointment has been booked.',
        start_ms: 0, end_ms: 1000, speaker_id: 'example', speaker_role: 'clinician', confidence: null}],
    }});},
    resumePendingWork: unsupported, acknowledgeGap: unsupported, finishInterruptedCapture: unsupported,
  }, async close() {stopTimer(); if (session.snapshot.state === 'recording') update({state: 'paused'}); listeners.clear();}};
};
