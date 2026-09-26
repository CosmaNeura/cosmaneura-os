# PostgreSQL workspace recovery proof

The local WAL-G 3.0.9 file-fixture proof passed on PostgreSQL 16.9: a remote
full backup plus WAL restored the complete 88-table workspace at a fixed record.
A committed change after the base backup survived; a later change after the
target was excluded. Missing and corrupt WAL were refused. Runtime backup
configuration remains Azure-only; it cannot select the fixture's file storage.

## PostgreSQL 16 restore settings

`restore.py` reads the fetched cluster's `pg_controldata` before rendering a
fresh recovery configuration. Hot standby requires each setting below to meet
the source cluster's recorded minimum; the restore preserves those values.

| `pg_controldata` label | Recovery setting |
| --- | --- |
| `max_connections setting` | `max_connections` |
| `max_worker_processes setting` | `max_worker_processes` |
| `max_wal_senders setting` | `max_wal_senders` |
| `max_prepared_xacts setting` | `max_prepared_transactions` |
| `max_locks_per_xact setting` | `max_locks_per_transaction` |

The cluster identifier must match, `wal_level` must be `replica` or `logical`,
and missing, duplicate or invalid control fields are refused. Do not reduce
these minima to fit a smaller host. PostgreSQL checks them again when replaying
parameter changes; keep source settings fixed throughout the local proof's
backup-to-target interval.

PostgreSQL 16.15 sources: [required settings and WAL level](https://github.com/postgres/postgres/blob/REL_16_15/src/backend/access/transam/xlog.c#L4994),
[control output labels](https://github.com/postgres/postgres/blob/REL_16_15/src/bin/pg_controldata/pg_controldata.c#L298),
and [checks during parameter replay](https://github.com/postgres/postgres/blob/REL_16_15/src/backend/access/transam/xlog.c#L8159).

## Fixed recovery boundary

With `recovery_target_inclusive=on`, PostgreSQL applies the first WAL record
whose **start** is at or beyond `recovery_target_lsn`, then pauses. The reported
`pg_last_wal_replay_lsn()` is that record's **end**. These LSNs need not be equal.
`pg_create_restore_point()` also returns an end LSN; using that return value as
an inclusive target can apply the next record.

Identify the chosen terminal record's start and end from its WAL, for example
with `pg_waldump`. Set the fixed target to that start, after base-backup
completion, and pass the independently identified end to the comparison.
Preserve the expected workspace through this boundary. A later committed
canary must remain absent from the restored workspace. The comparison checks
the supplied LSNs and full fingerprint; it does not decode WAL or independently
establish that the supplied addresses identify the same record.

Sources: [inclusive stop](https://github.com/postgres/postgres/blob/REL_16_15/src/backend/access/transam/xlogrecovery.c#L2730),
[replay end pointer](https://github.com/postgres/postgres/blob/REL_16_15/src/backend/access/transam/xlogrecovery.c#L1964),
and [restore-point insertion](https://github.com/postgres/postgres/blob/REL_16_15/src/backend/access/transam/xlog.c#L7680).

## Measure and compare

Run `workspace_proof.py` with the reviewed application's Python and installed
`cosmas_os` package; commands below assume the repository root. Supply
`DATABASE_URL` through the protected process environment, without putting
credentials in commands or evidence. Measurement requires
`postgresql+psycopg`, database `cosmas_os`, a certificate-matching hostname
(not a loopback IP or `localhost`), and exactly
`?sslmode=verify-full&sslrootcert=system`. The issuing CA must be trusted.

Both login and session identity must be `cosmas`, with no superuser, database
creation, role creation, replication, RLS bypass or role-membership privileges.
Measurements use read-only transactions. The source must be out of recovery;
the restored instance must still be in recovery and fully paused. The CLI has
no option to disable TLS or these role checks.

With `DATABASE_URL` selecting the source:

```sh
umask 077
python infra/beta/vm/backup/workspace_proof.py source > source.json
```

With `DATABASE_URL` selecting the isolated, paused restore:

```sh
umask 077
python infra/beta/vm/backup/workspace_proof.py restored > restored.json
```

Compare offline; set these public LSN variables from the reviewed WAL record:

```sh
python infra/beta/vm/backup/workspace_proof.py compare \
  --source source.json --restored restored.json \
  --target-lsn "$COSMABOT_TARGET_RECORD_START" \
  --replay-lsn "$COSMABOT_TARGET_RECORD_END" > comparison.json
```

Success requires the current schema revision, the complete registered table
inventory, valid evidence hashes and identical source/restored fingerprints.
It reports `workspace_restored_at_verified_record`; it does not activate an app.

A successful local WAL-G file-fixture proof establishes local backup, WAL
replay and workspace comparison only. It does **not** qualify Azure delivery,
Azure identities, systemd execution, deployed VM recovery or service activation.
This database proof does not restore external blobs, native device storage or
application capture artifacts stored outside PostgreSQL. External effects and
identity revocations newer than the backup require
reconciliation before activation; `external_state_reconciled` and
`application_activated` remain false.
