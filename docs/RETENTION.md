# Retention behavior (L0)

- Insurance working copies (`Artifact` front/back) are deleted **7 days after**
  ticket `closed_at`, driven by an injectable clock in tests/demo.
- Purge writes a receipt with: opaque `artifact_id`, retention rule, deletion
  time, outcome. No patient label, blob path, or content hash of deleted bytes.
- Audit events record `artifact.purged` without payload bytes.
- Ordinary API/telemetry responses do not include blob paths or signed URLs.

## Recording audio (48 hours, default off)

Existing live users: no change tonight. The process switch
`recording_audio_48h_retention_enabled` and the per-Box opt-in both default
false. With either one off, device behavior is unchanged: nothing is deleted
and no countdown label is shown. Only John turns this on.

When both switches are on:

- Recording **audio** (chunks and the audio manifest) is deleted 48 hours after
  the recording ended (sealed), or after the last audio write if it never
  finished. Transcripts, notes, drafts, ledger/attach/finish receipts, visit
  bindings, and audit rows are **not** deleted by this rule.
- Devices show a "deletes in N h" label and warn at 36 hours.
- Sweeps run on app open, on a timer while open, and on sign-out (expired audio
  only). An offline device deletes on its next launch.

Honest limits:

- A device that is off or never reopened cannot delete anything until it runs
  again.
- Server backup copies age out on the normal backup cycle under BAA 2.3
  section 4.3.3. This document does not change the BAA.
- The server holds no recording audio today (`audio_uploaded: false`), so T1
  has no server purge. T2a adds the server purge for audio it uploads.
- No compliance claim, no SOC 2 claim.
