# Guarded D3 PostgreSQL PITR acceptance

`pitr_acceptance.py` is the protected-runner primitive for the D3 backup/restore
acceptance gate. It is intentionally not scheduled. It may operate only on the
exact synthetic-only Beta Lab PostgreSQL source and an ephemeral, manifest-bound
target in the same resource group, region, delegated subnet, and private DNS
zone.

The script writes identifiers and database fingerprints only to root-owned
private files. Standard output is exactly one small, self-hashed, sanitized JSON
record. Provider errors, URLs, credentials, database rows, raw resource IDs, and
the raw Box ID are never copied to that record.

## Protected-runner sequence

1. Stop all API ingress, workers, schedulers, and operator writes for the
   synthetic Box. Record a sanitized write-freeze attestation and its SHA-256.
   The freeze must begin before the chosen restore timestamp and remain in force
   until F4 completes.
2. Run the existing protected-runner Docker isolation setup. It installs exact
   `DOCKER-USER` rejection rules for Azure IMDS (`169.254.169.254`) and
   WireServer (`168.63.129.16`). The PITR script independently checks those
   rules and executes an active network-denial probe through the exact
   digest-pinned fingerprint image before every database fingerprint.
3. Invoke `manifest`. This performs only ARM GETs: it validates the exact live
   source, backup boundary, private network, region, tags, and target absence;
   then writes a mode-0400 manifest. The restore timestamp must be within the
   provider's `earliestRestoreDate`, at least five minutes old, and within the
   declared write-freeze window. At least fifteen minutes must remain in that
   window.
4. Present only the sanitized manifest evidence to an owner whose asserted
   ledger reference differs from the manifest preparer's private reference. The
   wrapper enforces that the two bounded references differ before it accepts the
   exact `manifest_sha256`. Do not derive approval from a release label or a
   prior approval.
5. Invoke `start` with that exact approved hash. This is the first billable
   operation. It verifies the approval and live source, captures F1, and sends
   one exact private `PointInTimeRestore` PUT whose request hash is persisted in
   mode-0600 state.
6. Invoke `complete` until it returns `verified`, `failed`, or requires operator
   attention. While the quiet window is active it validates the distinct tagged
   target, captures F2 from the restore and F3 from the source, compares
   `F1 == F2 == F3`, validates the exact target again, deletes only that target,
   proves a strict 404, then captures F4 and compares `F4 == F1`.
7. Invoke `cleanup` with the same approved manifest hash after any interrupted
   run. Cleanup does not require the database credential or an active quiet
   window, but it will delete only a live target whose exact ID, name, tags,
   region, network, version, and manifest binding validate. It then requires a
   strict 404.
8. Resume application writes only after `complete` reports `verified` or after
   `cleanup` proves the target absent. A fingerprint mismatch is a failed
   acceptance result even when cleanup succeeds.

`restore_pending` and `cleanup_pending` are resumable checkpoints, not completed
acceptance; they return exit code 2. The wrapper must preserve the private
manifest and state and invoke the corresponding operation again. A generic
`failed` record and exit code 1 require private-log review plus `cleanup`; they
never authorize deployment. Exit code 0 means only that the requested phase
reached its named terminal status; only `complete` with status `verified` is the
PITR acceptance result.

## Invocation contract

All operations require these exact environment values:

- `COSMAS_PITR_OPERATION`: `manifest`, `start`, `complete`, or `cleanup`.
- `COSMAS_PITR_SUBSCRIPTION_ID`: canonical lowercase UUID.
- `COSMAS_PITR_RESOURCE_GROUP`: exact D3 workload resource group.
- `COSMAS_PITR_LOCATION`: exact lowercase source region.
- `COSMAS_PITR_SOURCE_SERVER_ID`: full Flexible Server resource ID in that
  subscription/resource group.
- `COSMAS_PITR_SOURCE_FQDN`: exact lowercase source FQDN.
- `COSMAS_PITR_POSTGRES_SUBNET_ID`: exact delegated subnet resource ID in the
  same subscription/resource group.
- `COSMAS_PITR_PRIVATE_DNS_ZONE_ID`: exact private PostgreSQL DNS-zone resource
  ID in the same subscription/resource group.
- `COSMAS_PITR_SOURCE_SHA`: reviewed 40-character lowercase commit SHA.
- `COSMAS_PITR_RELEASE_ID`: reviewed lowercase release identifier.
- `COSMAS_PITR_API_IMAGE_DIGEST` and `COSMAS_PITR_WEB_IMAGE_DIGEST`: exact
  lowercase 64-character digest bodies, without `sha256:`.
- `COSMAS_PITR_FINGERPRINT_IMAGE`: exact ACR image reference ending in
  `@sha256:${COSMAS_PITR_API_IMAGE_DIGEST}`. A mutable tag is rejected.
- `COSMAS_PITR_BOX_ID`: canonical lowercase UUID for the dedicated synthetic
  Beta Lab Box.
- `COSMAS_PITR_QUIET_WINDOW_START_UTC` and
  `COSMAS_PITR_QUIET_WINDOW_END_UTC`: whole-second UTC timestamps ending in
  `Z`; the window must be positive and no longer than four hours.
- `COSMAS_PITR_WRITE_FREEZE_EVIDENCE_SHA256`: SHA-256 of the separate sanitized
  protected-runner attestation proving ingress/workers/schedulers were stopped.
- `COSMAS_PITR_MANIFEST_PATH`: absolute path below a root-owned mode-0700
  directory. A new manifest is mode 0400.
- `COSMAS_PITR_POLL_ATTEMPTS`: optional integer 1-60; default 1.
- `COSMAS_PITR_POLL_INTERVAL_SECONDS`: optional integer 0-30; default 0.

`manifest` additionally requires `COSMAS_PITR_RESTORE_TIME_UTC` and rejects a
set `COSMAS_PITR_APPROVED_MANIFEST_SHA256`.

The protected transport also requires `--preparer-reference` to name a
mode-`0600` file containing one non-email operator-ledger reference. The wrapper
retains that value privately and returns only its SHA-256. `start`, `complete`,
and `cleanup` reject an approval with the same `reviewer_reference`.

`start` and `complete` additionally require:

- `COSMAS_PITR_APPROVED_MANIFEST_SHA256`: the exact owner-approved manifest
  hash.
- `COSMAS_PITR_STATE_PATH`: absolute mode-0600 state path below the same
  root-owned private directory.
- `COSMAS_PITR_DATABASE_URL_FILE`: absolute root-owned mode-0600 file containing
  one source URL of the exact form
  `postgresql+psycopg://...@<source>:5432/cosmas_os?sslmode=verify-full&sslrootcert=system`.
  The URL is supplied to Docker through a short-lived mode-0600 env file and
  never through argv.

`cleanup` requires the approved hash but intentionally does not require the
database URL or state file, so an exact-target cleanup remains available after
an interrupted or partially lost run.

Run `python3 infra/beta/pitr_acceptance.py` as root from the protected runner.
The wrapper should capture stdout as the public attestation and retain all
command diagnostics only in its existing root-only private log boundary.

## Azure interface notes and fail-closed limitations

The implementation uses the `Microsoft.DBforPostgreSQL/flexibleServers`
`2024-08-01` ARM endpoint. Local Azure CLI 2.89.1 help confirms that `az rest`
accepts an `@file` JSON body and `none` output, and the installed Flexible Server
client models confirm `createMode=PointInTimeRestore`,
`sourceServerResourceId`, `pointInTimeUTC`, and private network properties.
Direct REST is used because the high-level restore command does not provide an
atomic tags argument.

Azure's read model documents `sourceServerResourceId` as returned only for a
read replica, so a restored server GET cannot reliably prove the PITR source.
This implementation does not pretend otherwise: source provenance is bound by
the owner-approved manifest, the exact self-hashed PUT body, protected state,
and atomic target tags. The live target GET independently validates the exact
target, manifest hash, hashed source ID, Box boundary, region, private subnet,
private DNS zone, public-network denial, and PostgreSQL version.

Azure CLI does not expose the HTTP status as a separate `az rest` output field.
Absence accepts only a leading legacy `(ResourceNotFound)` diagnostic or Azure
CLI 2.89.1's exact `ERROR: Not Found(<JSON>)` envelope after parsing it and
verifying `error.code == ResourceNotFound`. Generic `Not Found`, malformed JSON,
and any other provider/CLI failure fail closed instead of being treated as
deletion.

The script cannot itself prove that all application writers remain stopped or
cryptographically authenticate the human identities represented by operator
ledger references. The wrapper requires distinct manifest-preparer and
billable-operation reviewer references, creates the write-freeze attestation
from observed API/worker/scheduler state, preserves the owner's separate
approval evidence, serializes PITR invocations, and resumes writers only after
terminal cleanup. The script binds the attestation hash and checks the bounded
quiet window on every start/complete invocation;
`F1 == F2 == F3` also fails safely on intervening persisted writes, but it is
verification rather than a substitute for the operational freeze.

The database fingerprint covers the expected Alembic head plus counts and
deterministic full-row hashes for the application's listed tables. It does not
claim to compare PostgreSQL sequences, arbitrary DDL, indexes, roles, or server
configuration; those remain infrastructure/schema drift controls rather than
this restore-data acceptance proof.
