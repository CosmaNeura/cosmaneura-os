# Retention behavior (L0)

- Insurance working copies (`Artifact` front/back) are deleted **7 days after**
  ticket `closed_at`, driven by an injectable clock in tests/demo.
- Purge writes a receipt with: opaque `artifact_id`, retention rule, deletion
  time, outcome. No patient label, blob path, or content hash of deleted bytes.
- Audit events record `artifact.purged` without payload bytes.
- Ordinary API/telemetry responses do not include blob paths or signed URLs.

## Deleting one patient's records

An admin (the practice owner) can delete one patient's live database rows and
stored files: visits, recording metadata, transcripts, notes, drafts, messages,
uploads, exports, and the other rows keyed to that patient's internal id.
The audit event records who deleted it, when, and that internal id only. It
does not record the patient's name or note text.

Backups are not edited. Deleted data ages out of backups under the backup
retention policy. T-RETENTION adds that policy.
