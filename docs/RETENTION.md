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
user. The admin LOGIN needs membership in `cosmas_patient_deletion` plus
`EXECUTE` on the public delete/plan/helper functions only. Binding reads,
pending-file DML, and patient-box lookup run inside SECURITY DEFINER helpers.
Never grant the LOGIN table DML on `audit_events`,
`patient_deletion_admin_bindings`, or other clinical tables.

Which account runs each step:

| Step | Runs as |
|------|---------|
| 1 Create LOGIN | Database owner / superuser with `CREATEROLE` (creates the chosen admin LOGIN, e.g. `cosmas_patient_deletion_admin`) |
| 2 Role grants (`ensure-patient-deletion-role.sql`) | Database owner / superuser with `CREATEROLE` (creates/updates NOLOGIN role `cosmas_patient_deletion` and REVOKE/GRANTs) |
| 3 Admin LOGIN grants (`ensure-patient-deletion-admin-login.sql`) | Database owner / superuser with `CREATEROLE` (membership + EXECUTE for `-v admin_login=...`) |
| 4 Binding INSERT | Database owner / superuser |
| 5–6 CLI dry-run / confirm | The admin LOGIN from step 1 (`COSMAS_ADMIN_DATABASE_URL`) |

Steps 1–3 require `CREATEROLE` on the account that runs them (database owner /
superuser). `CREATEROLE` alone without ownership of the SECURITY DEFINER
functions and tables is not enough for the REVOKE/GRANT statements in the
ensure scripts. Exact roles involved: NOLOGIN `cosmas_patient_deletion`, and
the LOGIN named by `-v admin_login=...` (example only:
`cosmas_patient_deletion_admin`).

1. As the database owner / superuser with `CREATEROLE`, create the admin LOGIN
   (password never in git):

```bash
psql "$POSTGRES_ADMIN_URL" -v ON_ERROR_STOP=1 \
  -c "CREATE ROLE cosmas_patient_deletion_admin LOGIN PASSWORD '...';"
```

2. As the database owner / superuser with `CREATEROLE`, apply the deletion role
   grants for `cosmas_patient_deletion`:

```bash
psql "$POSTGRES_ADMIN_URL" -v ON_ERROR_STOP=1 \
  -f scripts/ensure-patient-deletion-role.sql
```

3. As the database owner / superuser with `CREATEROLE`, grant that LOGIN
   membership and EXECUTE only (psql variable; do not hard-code a single
   product role name):

```bash
psql "$POSTGRES_ADMIN_URL" \
  -v admin_login=cosmas_patient_deletion_admin \
  -v ON_ERROR_STOP=1 \
  -f scripts/ensure-patient-deletion-admin-login.sql
```

4. As the database owner / superuser, bind `session_user` to the practice owner
   principal (IDs only):

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

6. As that admin LOGIN, dry-run, then confirm:

```bash
cosmas-os delete-patient-records <patient_link_id> --dry-run
cosmas-os delete-patient-records <patient_link_id> --confirm
```

The actor is taken from the binding for `session_user`, not from a CLI flag.
The SQL helpers also require `pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER')`.
