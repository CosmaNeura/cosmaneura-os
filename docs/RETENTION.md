# Retention behavior (L0)

- Insurance working copies (`Artifact` front/back) are deleted **7 days after**
  ticket `closed_at`, driven by an injectable clock in tests/demo.
- Purge writes a receipt with: opaque `artifact_id`, retention rule, deletion
  time, outcome. No patient label, blob path, or content hash of deleted bytes.
- Audit events record `artifact.purged` without payload bytes.
- Ordinary API/telemetry responses do not include blob paths or signed URLs.

## Deleting one patient's records

The practice owner deletes one patient's live rows and stored files from the
admin command. That command reads `COSMAS_ADMIN_DATABASE_URL` and refuses to
run when the setting is missing, equal to `DATABASE_URL`, or names the same
database role. It then calls the deletion function. The HTTP route only
counts; it does not delete. Visits, recording
metadata, transcripts, notes, drafts, messages, uploads, exports, and the other
clinical rows keyed to that patient are removed. Older audit events stay, with
the patient id replaced, and ticket, visit, and recording-keyed events scrubbed
the same way. The new deletion event records who deleted it, when,
and that internal id only. It does not record the patient's name or note text.
a patient delete also removes that patient's per-visit model usage rows; practice-level usage totals computed before the delete are unaffected.
Confirmed deletes refuse and change nothing when the deletion role is missing.

Confirmed deletes commit the database first, then remove stored files;
pending file paths are recorded in the same transaction so a later run can
finish leftovers for that practice. If file removal fails after the database
commit, the command reports that the database delete completed and stored
files are pending; a rerun finishes them.

Backups are not edited. Deleted data ages out of backups under the backup
retention policy. T-RETENTION adds that policy.

## John's operator setup (admin LOGIN)

Agents and CI never run these steps against a real database. Suggested example
login name only — choose any LOGIN distinct from the runtime `DATABASE_URL`
user.

1. As a Postgres role that can create logins, create the admin LOGIN (password
   never in git):

```bash
psql "$POSTGRES_ADMIN_URL" -v ON_ERROR_STOP=1 \
  -c "CREATE ROLE cosmas_patient_deletion_admin LOGIN PASSWORD '...';"
```

2. Apply the deletion role grants:

```bash
psql "$POSTGRES_ADMIN_URL" -v ON_ERROR_STOP=1 \
  -f scripts/ensure-patient-deletion-role.sql
```

3. Grant that LOGIN membership and EXECUTE on the delete + plan functions using the psql variable:

```bash
psql "$POSTGRES_ADMIN_URL" \
  -v admin_login=cosmas_patient_deletion_admin \
  -v ON_ERROR_STOP=1 \
  -f scripts/ensure-patient-deletion-admin-login.sql
```

4. Bind `session_user` to the practice owner principal (IDs only):

```sql
INSERT INTO public.patient_deletion_admin_bindings (db_role, principal_id, box_id)
VALUES (
  'cosmas_patient_deletion_admin',
  '<owner principal uuid>',
  '<box uuid>'
);
```

5. Point `COSMAS_ADMIN_DATABASE_URL` at that LOGIN. The CLI refuses when its
   user equals the runtime `DATABASE_URL` user.

6. Dry-run, then confirm:

```bash
cosmas-os delete-patient-records <patient_link_id> --dry-run
cosmas-os delete-patient-records <patient_link_id> --confirm
```

The actor is taken from the binding for `session_user`, not from a CLI flag.
The SQL function also requires `pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER')`.
