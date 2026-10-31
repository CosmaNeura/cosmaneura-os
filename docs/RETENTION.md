# Retention behavior (L0)

- Insurance working copies (`Artifact` front/back) are deleted **7 days after**
  ticket `closed_at`, driven by an injectable clock in tests/demo.
- Purge writes a receipt with: opaque `artifact_id`, retention rule, deletion
  time, outcome. No patient label, blob path, or content hash of deleted bytes.
- Audit events record `artifact.purged` without payload bytes.
- Ordinary API/telemetry responses do not include blob paths or signed URLs.

## Deleting one patient's records

The practice owner deletes one patient's live rows and stored files from the
admin command, which connects as the migration role and calls the deletion
function. The HTTP route only counts; it does not delete. Visits, recording
metadata, transcripts, notes, drafts, messages, uploads, exports, and the other
clinical rows keyed to that patient are removed. Older audit events stay, with
the patient id replaced. The new deletion event records who deleted it, when,
and that internal id only. It does not record the patient's name or note text.

Backups are not edited. Deleted data ages out of backups under the backup
retention policy. T-RETENTION adds that policy.
