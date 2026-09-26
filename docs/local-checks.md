# Local backend checks

Use Python 3.13+ with the project's existing development dependencies and a local
PostgreSQL installation. The checker uses its own Python interpreter, starts a
fresh PostgreSQL cluster bound to an available loopback port, and stops that
cluster in `finally`. It installs nothing and uses no Docker, GitHub, Redis, or
cloud service. A checkout containing `.env` is refused; ambient credentials and
application settings are not passed to child processes.

From the repository root, with PostgreSQL's `pg_ctl` on `PATH`:

```sh
uv run --no-sync python scripts/check-backend-local.py
```

Alternatively, use an already prepared Python environment and identify the
PostgreSQL executable directory explicitly:

```sh
python scripts/check-backend-local.py --postgres-bin /path/to/postgresql/bin \
  --profile workspace tests/integration/test_beta_bootstrap.py
```

`--profile all` is the default. Workspace tests use `w1a_local_checks`; only
`tests/integration/test_database_fingerprint.py` and
`tests/integration/test_database_preparation.py` use `cosmas_os`, since those
tests validate that exact deployment database name and authenticated access.
The compact execution tests use a third database, `compact_test`, owned by
`compact_synth`, matching their existing local-only guard. Select just those with
`--profile compact`. The databases are separate and freshly migrated. Test paths
and pytest node IDs may be selected; the checker assigns them to their matching
profile.

The explicit process profile is synthetic, with `WORKSPACE_ENABLED=false`,
`SYNTH_SEED=true`, and `SYNC_WORKER=true`. The integration fixture enables the
workspace singleton per test; constructor defaults and explicit disabled-gate
tests retain their meaning. Model/routine evidence and pytest temporary storage
are confined to the run directory. No actual model, identity, native-device, or
external-service acceptance is established by these tests.

The checker prints its evidence directory. Supply `--evidence-dir /new/path` to
choose one outside the repository; an existing directory is refused. It retains command logs, JUnit
results, source hashes before/after, commit and dirty-tree state, command exit
codes, and proof that its cluster's PID file and listening port are gone.
The run fails if source changes during validation or cleanup cannot be proved.
Synthetic cluster data remains there for inspection; its generated password file
is removed at shutdown. After inspection, the entire run directory may be removed.

Each test emits a Python stack dump after 60 seconds; each pytest process has a
30-minute limit. Adjust with `--stack-dump-after` and `--pytest-timeout`. A timeout
interrupts the owned process group, escalates if needed, records failure, and
stops the database. PostgreSQL also enforces 5-second lock waits, 60-second
statements, and 90-second idle transactions. On macOS,
`--sandbox-profile /path/to/loopback-only.sb` wraps
child commands with `sandbox-exec`; use a reviewed profile to block non-loopback
network access. Without it, network isolation is not enforced by this script.

Read `results.json` and the logs before recording a passing check. Optional
device-dependent tests may report skips; those are not device qualification.
