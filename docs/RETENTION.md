# Retention behavior (L0)

- Insurance working copies (`Artifact` front/back) are deleted **7 days after**
  ticket `closed_at`, driven by an injectable clock in tests/demo.
- Purge writes a receipt with: opaque `artifact_id`, retention rule, deletion
  time, outcome. No patient label, blob path, or content hash of deleted bytes.
- Audit events record `artifact.purged` without payload bytes.
- Ordinary API/telemetry responses do not include blob paths or signed URLs.

## Recording audio (48 hours, default off)

Dual switch, both default **off**:

1. Process / Settings: `RECORDING_AUDIO_48H_RETENTION_ENABLED` (standalone
   packages render this explicitly `false`).
2. Per-Box opt-in: `recording_audio_48h_retention_enabled` on `BoxContext`.

With either switch off, devices do not delete audio and do not show a countdown
label. Existing live users are unchanged until both are on.

When a Box opts in, Postgres stamps `recording_audio_48h_retention_enabled_at`
(`enabled_at`). Clients grandfather recordings that already existed: the 48h
clock starts at `max(ended_at_or_last_audio_write, enabled_at)`, so a 30-day-old
clip is not wiped 48h after an old `ended_at` — it waits until flip+48h.

When both switches are on:

- **Audio only** (chunks + audio manifest) is deleted after 48 hours. Transcripts,
  notes, drafts, ledger / attach / finish receipts, visit bindings, and audit
  rows stay. After delete, devices may keep an `audio-deleted` stub so the
  recording still appears for transcript/ledger work.
- Devices show a long countdown label (`snapshot.retentionLabel`) and warn near
  36 hours. The panel refreshes that label on a 60s tick.
- Sweeps run on app open, on a timer while open, and after mic/runtime close
  (sign-out / panel teardown). An offline device deletes on its next launch.

Parents may pass `audioRetention` (preferred for tests). When that prop is
omitted, the panel GETs
`/workspaces/{id}/private-recordings/audio-retention` once a workspace id is
known (`workspaceId` prop, notebook, or attached snapshot). Fetch failure is
treated as off (`enabled: false`). WorkspaceShell does not yet pass the policy;
pass the prop or `workspaceId` from a thin parent when wiring production home.

Honest limits:

- A device that is off or never reopened cannot delete anything until it runs
  again.
- Server backup copies age out on the normal backup cycle under BAA 2.3
  section 4.3.3. This document does not change the BAA.
- The server holds no recording audio today (`audio_uploaded: false`), so T1
  has no server purge. T2a adds the server purge for audio it uploads.
- There is **no** separate capture-queue copy of private-recording audio today.
  Transcripts remain via ledger / private-transcript / audio-deleted stub.
- If device clock and `server_now` differ by more than five minutes, clients
  **refuse delete** (and expired-audio refuse) until skew recovers; labels still
  use device time.
- No compliance claim, no SOC 2 claim.
