# Saved recording transcription

Open a saved recording, choose **Transcribe recording**, confirm its patient and visit, confirm transcription consent, then send it to Scribe. Review the transcript, continue to the note, choose a template, create the note, correct its fields and save. Home retains the original recording. Reopening the same clip recovers its transcript and saved note without starting a microphone or creating another transfer.

The API pins the immutable local-recording finish and patient-link receipts, the exact consent/language/Scribe selection and one remote session. Each service boundary rechecks current account, patient and source access. A retry preserves the original admission intent, encrypted audio queue and completion request. Saved-source operations cannot request native microphone authority or complete fewer/different channels. All-zero PCM is rejected before transcription admission. Note saving preserves a draft and does not sign it.

The service requires additive schema `f97c2d5e3468` before this renderer is released. It adds immutable transfer-intent and session-receipt tables; runtime readiness rejects older databases. Upgrading only a client cannot upgrade the service.

## Repeatable local walkthrough

Run `node node_modules/vite/bin/vite.js --config vite.transcription-lab.config.ts` from `web/`, then open http://127.0.0.1:5191/. The lab reuses the production recording storage, visit controls, transcription panel and editable-note components with generated PCM and scripted service replies. It performs no microphone capture, patient-data processing or live speech recognition.

Two UI walkthroughs completed on October 9, 2026: one to simplify the flow and one at 390 × 844 as a first-time provider. Both saved edited note text and reopened the same result. Findings applied: automatic visit loading, plain patient/visit wording, larger touch targets, shorter first screen, percent progress, processing refresh, explicit note creation, immediate editing, focus on the note, collapsed transcript after review and recovery controls shown when needed. These are agent walkthroughs; they do not establish usability with human practitioners or live iPhone transcription.

## Focused verification

From `web/`, run `node node_modules/vitest/vitest.mjs run --config vitest.transcription.config.ts`. These checks use actual encrypted audio import, configured Scribe queue protocol, partial chunk preservation, 91-chunk continuation and exact lost-completion recovery against an owned loopback service. They do not provide live STT evidence. Relevant web API, recording and draft checks remain in the normal suite.

Run `scripts/check-backend-local.py` with the saved-recording, private-recording, workspace-capture and capture-note integration selections, plus database preparation/fingerprint and schema-readiness selections, using an owned PostgreSQL cluster. Record exact source SHA, commands and results before release.
