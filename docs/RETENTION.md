# Retention behavior (L0)

- Insurance working copies (`Artifact` front/back) are deleted **7 days after**
  ticket `closed_at`, driven by an injectable clock in tests/demo.
- Purge writes a receipt with: opaque `artifact_id`, retention rule, deletion
  time, outcome. No patient label, blob path, or content hash of deleted bytes.
- Audit events record `artifact.purged` without payload bytes.
- Ordinary API/telemetry responses do not include blob paths or signed URLs.

## Recording audio uploaded for transcription (48 hours)

- CosmaBot-independent transcription audio blobs are deleted **48 hours after**
  receipt (`audio_expires_at`), via an owner-triggered purge route and an
  injectable clock in tests. Reads refuse expired audio even before purge runs.
- Purge deletes **audio blobs only**. Immutable transcript rows, transcript
  content, and audit rows stay under existing retention.
- Purge writes a receipt with: opaque `upload_id`, retention rule
  (`audio_plus_48h`), deletion time, outcome. No patient label, blob path, or
  content hash of deleted bytes. Audit events record `recording_audio.purged`
  without payload bytes.
- Server backup copies of purged audio age out on the normal backup cycle under
  BAA 2.3 section 4.3.3. This document does not change the BAA.
