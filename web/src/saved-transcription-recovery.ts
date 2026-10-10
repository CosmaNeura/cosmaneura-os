/** Closed service codes only; private response text never reaches the screen. */
export function savedTranscriptionRecovery(code: unknown) {
  if (code === 'capture_request_conflict' || code === 'capture_session_changed') return {
    retry: false,
    message: 'Scribe cannot accept this recording for the selected visit. Your audio is saved. Return to recordings and ask for help with this visit’s recording connection.',
    reference: String(code),
  };
  if (code === 'capture_consent_required' || code === 'capture_consent_unavailable') return {
    retry: false,
    message: 'Scribe could not confirm consent for this transcription. Your audio is saved. Return to recordings; consent must be resolved before this recording can be sent.',
    reference: String(code),
  };
  return null;
}
