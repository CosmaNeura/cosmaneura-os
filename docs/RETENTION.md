# Retention behavior (L0)

- Insurance working copies (`Artifact` front/back) are deleted **7 days after**
  ticket `closed_at`, driven by an injectable clock in tests/demo.
- Purge writes a receipt with: opaque `artifact_id`, retention rule, deletion
  time, outcome. No patient label, blob path, or content hash of deleted bytes.
- Audit events record `artifact.purged` without payload bytes.
- Ordinary API/telemetry responses do not include blob paths or signed URLs.

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
