# PostgreSQL workspace recovery proof

The local WAL-G 3.0.9 file-fixture proof passed on PostgreSQL 16.9: a remote
full backup plus WAL restored the complete 88-table workspace at a fixed record.
A committed change after the base backup survived; a later change after the
target was excluded. Missing and corrupt WAL were refused. Runtime backup
configuration remains Azure-only; it cannot select the fixture's file storage.

## Public host installation

`install-host.py` installs the reviewed public software and service definitions
on `vm-cosmabot-staging-eus2-lab01`, Ubuntu 22.04 amd64. Native PostgreSQL 16
`psql`, `postgres`, and `pg_controldata` must already be installed from the
reviewed package source. An existing backup installation, account, group,
state directory or loaded unit requires operator review before proceeding.
These checks run before any persistent write or account creation.

Prepare a root-owned directory beneath a root-owned, non-writable parent
(for example `/opt/cosmabot/backup-inputs/release`). It must contain exactly
the six `.service`/`.timer` files in this directory, `backup.py`, `restore.py`,
`walg.json`, `resolv.conf`, `logrotate.conf`, the pinned 3.0.9 binary named
`wal-g`, and `bundle.json`. The manifest has exactly `version: 1`, the reviewed
40-character `source_commit`, and `files`, mapping each of those 12 payload
filenames to its SHA256. Record the manifest's SHA256 in the release evidence.
Credentials and database/configuration inputs do not belong in this bundle.

Run the exact reviewed installer with the bound public values:

```sh
python3 -I install-host.py \
  --bundle "$COSMABOT_BACKUP_BUNDLE" \
  --bundle-sha256 "$COSMABOT_BACKUP_BUNDLE_SHA256" \
  --source-commit "$COSMABOT_BACKUP_SOURCE_COMMIT"
```

Installation creates distinct system accounts with no login shell, home or
supplementary groups and initializes their private state/log directories with
the matching account ownership and mode 0700. This lets the preflight run before
the first service, and lets Ubuntu 22.04 open append logs before service startup.
It installs root-owned public files, parses the units, reloads
systemd and verifies that every job/timer is inactive and disabled or static.
The receipt `/etc/cosmabot/backup-install.json` records the exact source and
installed file hashes. A partial installation is preserved for diagnosis;
rerunning cannot overwrite it or report success.

This receipt qualifies software installation only. The separate writer/reader
certificates, PostgreSQL replication role/slot/password, private DNS, TLS,
validated `backup.json`/`restore.json`, receiver/timer activation and actual
Azure backup/restore still require their reviewed deployment steps. The
installer does not place credentials or start backup, restore or application
services. The restore target always remains separate from application startup.

The host's `/opt/cosmabot` and `/etc/cosmabot` parents may remain root-only.
Each backup/restore unit mounts private read-only parent views and binds only
the public backup code and configuration beneath them. The credential-source
directory is inaccessible in that view; systemd supplies the named credentials
through `LoadCredential`. Application releases and runtime configuration are
not exposed. Do not broaden host directory permissions to make the service run.

After a verified base/WAL backup and isolated restore, explicitly enable the
receiver and the three timers. The receiver must be enabled for boot as well as
running now. The full backup runs daily at 03:00 UTC with up to five minutes of
delay; WAL switching runs every minute and status checks every two minutes.
Keep the receiver and timers in the staging service's `PartOf` lifecycle, ordered
after staging. A staging stop therefore stops scheduling before application
shutdown, while a systemd restart restores both. Otherwise a timer's job can
start its required receiver and staging service during maintenance. For a
separate stop/start sequence, explicitly start all four units after staging is
healthy. Do not treat enabled schedules as evidence of a completed backup or
successful reboot; record the service invocation, resulting receipt and actual
timer-triggered health checks.

The daily backup does not delete older base backups. Retention is a separate
dry-run plan, described below, and it is not part of this installer.

Before running `provision-postgres.sql`, activate the reviewed PostgreSQL backup
runtime profile. Provisioning refuses the default unlimited slot retention or
any limit other than 4 GiB before creating a role or reserving WAL. It also
requires replica WAL, archive mode off, and sufficient replication capacity.
Refusals raise SQL errors, so `ON_ERROR_STOP` returns a nonzero process exit.
Start the receiver promptly after installing its protected password; the cap
limits disk use but an idle slot can still lose continuity when WAL exceeds it.

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

## Retention

WAL-G keeps every base backup until an operator turns retention on. `install-host.py`
does not copy `retention.py`, `retention.json`, or `cosmabot-backup-retention.timer`.
Those units load no backup credential and have no network. Nothing in this
repository runs `wal-g delete` against a server.

Defaults in `retention.json`:

| Setting | Default | Meaning |
| --- | --- | --- |
| `policy` | `retain_count` | Use `wal-g delete retain FULL` |
| `retain_count` | 14 | Keep the 14 newest full backups |
| `retain_days` | 30 | Used when `policy` is `retain_days` |
| `dry_run` | `true` | Compute and log the delete set only |
| `enabled` | `false` | Apply refuses while this is false |

`retain_count` orders backups by sentinel `start_time`. The 14th newest is kept.
Older non-permanent backups are the delete set. The logged command is:

```text
wal-g delete retain FULL 14 --use-sentinel-time
```

`--confirm` is absent, which is WAL-G's own dry run. `retain_days` uses
`wal-g delete before <cutoff> --use-sentinel-time`, where the cutoff is now minus
`retain_days`. A backup at the cutoff is kept. If every backup is older than the
cutoff, the delete set is empty: WAL-G exits without deleting when that command
would remove the whole history. Permanent backups are never in the delete set.
If a permanent backup is older than the boundary, the plan does not call WAL-G,
because that command would also delete WAL the permanent backup still needs.

Plan reads a local JSON backup list only. It does not contact storage.

### Turn it on

1. Review this source. Leave `dry_run` true and `enabled` false.
2. Copy `retention.py` to `/opt/cosmabot/backup/retention.py` (root-owned, mode 0555)
   and `retention.json` to `/etc/cosmabot/backup/retention.json` (root-owned, mode 0644).
3. Export `wal-g backup-list --detail --json` to
   `/var/lib/cosmabot-backup/retention-backup-list.json`, owned by `cosmabot-backup`,
   mode 0600. Do not put credentials in that file or in the retention unit.
4. Install `cosmabot-backup-retention.service` and `.timer`, then enable the timer.
   It runs at 06:00 UTC and only appends a JSON plan to the journal and
   `retention.log`. Read `delete_names` there. A skipped plan means the list file
   is not installed yet; that is not a retention pass.
5. To delete, set `enabled` to true and `dry_run` to false, then run this on the
   backup host with the same credential directory the backup job uses:

```text
COSMABOT_RETENTION_APPLY=1 python3 -I /opt/cosmabot/backup/retention.py apply \
  --config /etc/cosmabot/backup/retention.json \
  --backup-list /var/lib/cosmabot-backup/retention-backup-list.json \
  --confirm-apply
```

That is the only command that adds `--confirm`. Leave the timer on `plan`.
Do not point apply at a list you have not just reviewed. Applying with an empty
delete set does not call WAL-G.
