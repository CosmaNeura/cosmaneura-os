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
(`enabled_at`). The 48h clock starts at
`max(ended_at_or_last_audio_write, box enabled_at, device first-seen armedAt)`:
a recording that ended before cutover is not wiped from an old `ended_at`
alone — the deadline is cutover (and device arm) plus 48h.

When both switches are on:

- **Audio only** (chunks + audio manifest) is deleted after 48 hours. Transcripts,
  notes, drafts, ledger / attach / finish receipts, visit bindings, and audit
  rows stay. After delete, devices may keep an `audio-deleted` stub so the
  recording still appears for transcript/ledger work.
- Devices show a long countdown label (`snapshot.retentionLabel`) and warn near
  36 hours. The panel refreshes that label on a 60s tick.
- Sweeps run **while the private-recording panel is open**: on panel open, on a
  60s timer while open, and on panel close / mic-runtime teardown. They do not
  run merely because the app process launched. An offline or never-reopened
  device deletes on its next panel open.

Parents may pass `audioRetention` (preferred for tests). When that prop is
omitted, the panel GETs
`/workspaces/{id}/private-recordings/audio-retention` once a workspace id is
known (`workspaceId` prop, notebook, or attached snapshot). Fetch failure is
treated as off (`enabled: false`). Production `WorkspaceShell` currently passes
neither `audioRetention` nor `workspaceId` into the panel; retention stays off
there until a parent wires one of those.

Saved-recording import (`openSavedRecordingRuntime`) opens a **session-scoped**
import queue / flow / profile DB (names include `sessionId`; browser queue open
uses `sessionId` as the queue namespace key). That is not a second long-lived
private-recording audio copy. The durable private-recording store remains the
retention target; the import queue is session-scoped.

Mac Electron: `DesktopProviderRecorder` sweeps a durable private-recording
namespace when the desktop recorder is open/read/deactivated and main
`fetchAudioRetentionPolicy` says enabled (with `audioRetentionRecords`
supplied). Not claimed for locked-screen or Core capture paths.

Honest limits:

- A device that is off or never reopens the panel (or Mac recorder path above)
  cannot delete anything until that path runs again.
- Server backup copies age out on the normal backup cycle under BAA 2.3
  section 4.3.3. This document does not change the BAA.
- The server holds no recording audio today (`audio_uploaded: false`), so T1
  has no server purge. T2a adds the server purge for audio it uploads.
- If device clock and `server_now` differ by more than five minutes, clients
  **refuse delete** (and expired-audio refuse) until skew recovers; labels still
  use device time.
- No compliance claim, no SOC 2 claim.

## Recording audio uploaded for transcription (48 hours)

- CosmaBot-independent transcription audio blobs are deleted **48 hours after**
  receipt (`audio_expires_at`). A worker retention sweep
  (`cosmas_os.purge_independent_recording_audio`) runs without the feature
  switch gate so leftover audio still ages out; an owner purge route remains
  for explicit runs. Tests use an injectable clock. Reads refuse expired audio
  even before purge runs.
- Purge deletes **audio blobs only**. Immutable transcript rows, transcript
  content, jobs, and audit rows stay under existing retention.
- On a failed blob delete the row keeps `blob_key`, records outcome `failed`,
  and is retried on the next sweep. Blob not-found is treated as success
  (`purged`).
- Revoke deletes the audio blob immediately (with a purge receipt) and marks
  the upload revoked. An already-written transcript remains readable; reads
  without a transcript return `revoked`.
- Purge writes a receipt with: opaque `upload_id`, retention rule
  (`audio_plus_48h` or `revoke_delete`), deletion time, outcome (`purged` or
  `failed`). No patient label, blob path, or content hash of deleted bytes.
  Audit events record `recording_audio.purged` without payload bytes.
- Account delete removes the owner's transcription blobs, then transcripts,
  uploads, and receipts (transcripts before uploads for FK safety).
- Server backup copies of purged audio age out on the normal backup cycle under
  BAA 2.3 section 4.3.3. This document does not change the BAA.
