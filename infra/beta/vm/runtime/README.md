# VM staging runtime preparation

This renders the ordinary CosmaBot API, its PostgreSQL handoff/routine workers,
the retained Celery worker, production static web, PostgreSQL 16, Redis and TLS
proxy. It does not start Docker, deploy Azure, create accounts, install secrets,
change DNS, run migrations or activate Scribe. The source and local checks are
preparation; no VM runtime, restart, identity isolation or restore is qualified.

Use the matching application's Python dependencies to run `render.py`. Its
required manifest is version 1 and contains exactly:

- `release_id`, a new lowercase identifier; `source_commit`, its reviewed source
  SHA; `image_review_reference`, the reviewed image/build/config evidence.
- `images`: API and web `dedicated.azurecr.io/repository@sha256:...` references;
  PostgreSQL `postgres:16.PATCH-bookworm@sha256:...`; Redis
  `redis:7.2.PATCH-bookworm@sha256:...` or `7.4`; Caddy
  `caddy:2.MINOR.PATCH-alpine@sha256:...`. There are no default or invented image
  digests. The review must prove the chosen digest contains the declared image,
  expected UID and matching application/web configuration. This renderer does
  not pull images or infer their provenance from their names.
- Exact `web_origin` `https://staging.cosmas.ai` and selected `api_origin`
  `https://api.staging.cosmas.ai`. DNS/control and this separate API name remain
  required deployment inputs. An alternative origin needs a reviewed change.
- `runtime`: `environment`, `secret_names`, `runtime_identity_client_id`.
  Public environment keys are actual application Settings names in uppercase.
  Every Boolean setting must be explicitly `true` or `false`, preserving the
  selected full candidate instead of silently taking disabled defaults. Hosted
  synthetic authentication, Azure Blob, asynchronous execution and draft recovery
  remain mandatory, along with the selected model, team and routine workers.
  The actual application validator runs before output and again
  inside the API/worker. Native flags require their exact CORS/authorized origins;
  OAuth callbacks must match this API and return to the approved web origin.
- `tls_sha256`: reviewed hashes for `public-roots.pem`, `private-ca.pem`,
  `postgres.crt`, `redis.crt`. Extract public roots from the exact API image and
  bind their provenance in image review. The renderer combines those public
  roots with the dedicated private CA for the mounted system store; verifies
  current server certificate chain, hostname and key pairing; and never weakens
  PostgreSQL `verify-full`/`sslrootcert=system` or Redis certificate checking.

The prepare, API and worker entrypoints set the fixed
`SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` in their clean process
environments. This directs bundled libpq/OpenSSL to the reviewed mounted CA
bundle even when its compiled default points to a build-machine path. Public
configuration and inherited environment values cannot override this path;
PostgreSQL hostname verification and `sslrootcert=system` remain enabled.

`secret_names` accepts current Settings `SecretStr` names, the required
`HUMAN_DEPLOY_EVIDENCE_REF`, and supported `COSMAS_MANAGED_SECRET_*` references.
It contains names only. `DATABASE_URL` and `REDIS_URL` cannot be supplied or
overridden: the entrypoint constructs them from protected passwords and fixed
private hosts/TLS settings. Root provisioning must retain exact Key Vault
name/version/identity custody evidence separately; file presence is not that proof.

Install the protected input directory `/etc/cosmabot/runtime/<release_id>` with
root ownership and mode 0700. Direct service subdirectories are mode 0700, owned
by their service UID. Secret files are ordinary, single-link files, mode 0400:

| Directory / UID | Required protected files |
|---|---|
| `api`, `worker` / 10001 | `DATABASE_PASSWORD`, `REDIS_PASSWORD`, and each declared secret environment name; both copies must agree |
| `prepare` / 10001 | `DATABASE_PASSWORD`, separate `POSTGRES_PASSWORD`; no model/Core/Clerk credentials |
| `postgres` / 999 | `POSTGRES_PASSWORD`, `server.key` |
| `redis` / 999 | `REDIS_PASSWORD`, `server.key`, `users.acl` |
| `tls` / root | The four public certificate files, never signing/private keys |

Database/broker passwords must be distinct, independently generated URL-safe
32–128-character values. The Redis ACL is exactly `user default reset on #<SHA256 of
the Redis password> ~* &* +@all`. It is protected alongside the password, not
included in output. Keep private CA signing keys off the runtime host. Only
per-service server keys are installed. The public release contains no credential
values; the entrypoint loads secrets into that process immediately before exec.
Do not dump container process environments or use shell tracing around provisioning.

Run, supplying actual reviewed inputs (these commands do not contain credentials):

```sh
python infra/beta/vm/runtime/render.py \
  --manifest /protected/reviewed-runtime-input.json \
  --protected-root /etc/cosmabot/runtime/RELEASE_ID \
  --output /opt/cosmabot/releases/RELEASE_ID
```

The output directory must be new. Output files are read-only public files and
`RENDER.json` binds their hashes and declared image/source identities. Render on
the prepared host, or stage protected inputs securely with the required numeric
owners. Do not copy a test renderer output into staging: local tests explicitly
use invented images/identity and substitute local fixture UIDs.

The Linux host must have Docker's **iptables backend / DOCKER-USER chain**,
Compose with `up --wait`, Python 3, OpenSSL, `flock` and an approved persistent data disk
mounted at `/var/lib/cosmabot`. Create mode-0700 subdirectories `postgres` and
`redis` owned by 999, and `caddy-data`/`caddy-config` owned by 10001. They must be
empty only for initial deployment; never reinitialize existing data. The host
preflight refuses a missing data mount or altered/non-root-owned release files.
API/worker limits retain 0.5 CPU / 1 GiB each; the static web retains 0.25 / 0.5.
Database/broker/proxy allocations are provisional and need real measurements.

The topology uses three reserved bridge subnets: `172.30.240.0/24` (private
backend), `172.30.241.0/24` (egress), `172.30.242.0/24` (private frontend).
Check for host/VNet overlap before installation. PostgreSQL/Redis/web/preparer
have no egress network. The host guard denies container IMDS except API/worker
at `.241.10/.11` on the exact `br-cm-egress` bridge. Replacement first installs a
temporary deny, and failure leaves access denied. The guard must run before
every start and after reboot; no broader identity may be attached to the VM.
It preserves unrelated host firewall rules. Verify the actual denied/allowed
paths from each container before admission; the local stub check is not proof
of real Linux networking. Root host compromise remains outside this isolation.

Only proxy 80/443 are published; private database/broker/health/management ports
are not. Preserve the foundation NSG and narrow administrative access. Caddy uses
unprivileged internal ports and durable certificate storage; no administrator API
is enabled. Its official binary carries `cap_net_bind_service=ep`, which Linux
refuses to execute when that capability is outside the bounding set. Only the
proxy adds `NET_BIND_SERVICE` after dropping all capabilities; it retains UID
10001, `no-new-privileges`, a read-only root filesystem and ports 8080/8443.
Every other service drops all capabilities and adds none. Native amd64 execution
of Caddy 2.11.4 confirmed this requirement; full proxy/TLS operation still needs
runtime acceptance. Public certificate issuance/renewal and private certificate rotation
must be exercised and monitored. Registry pulls and backup custody are host-only;
the runtime identity must not acquire deployment, registry-admin or backup powers.

Once the exact host/configuration is reviewed, `start.sh` is the operator entry:
`data` starts the databases, `prepare` runs the existing forward-only schema and
non-admin denial checks in its manual profile, and `run` starts the full runtime.
`prepare` checks all containers bearing the exact Compose project label, including
one-off and orphan containers. Except for PostgreSQL/Redis, every container must
be exited or dead; paused/restarting services and a surviving earlier preparer
refuse the maintenance action. Inventory errors and malformed/unknown states
also refuse it. All wrapper actions share an exclusive host lock, so preparation
and startup cannot race through this wrapper. The database
administrator owns the database; application migrations/privileges use the existing preparation
implementation, with append-only audit/schema restrictions retained. Keep its
sanitized receipt with image/schema/plan evidence. `stop` gracefully stops without
deleting data and remains available if startup preflight fails. Do not use raw
Compose commands to bypass host preflight/IMDS setup.

After initial preparation and acceptance, install `cosmabot-staging.service` with
a root-owned `/etc/cosmabot/active-release` containing only the canonical public
`RELEASE_DIR`. The unit orders startup after Docker/network/data mount. Container
restart is bounded `on-failure:3`; it does not start containers automatically on a
Docker-daemon restart before the guard. A daemon restart needs the unit restarted.
Docker health status does not itself restart an unhealthy process; alert on it.

**Still required before admission:** host provisioning and actual identity grant;
exact digest/config/public trust provenance; secret installation/rotation; DNS,
Clerk/Core configuration; manual database preparation; certificate renewal and
IMDS/firewall proof; and off-host PostgreSQL base/WAL backup plus an isolated
restore. Backup/WAL archiving is deliberately not claimed or enabled by these
files until its independent custody/storage and restore path are installed. A
persistent disk and Redis AOF do not supply PostgreSQL PITR or high availability.
Keep synthetic tester admission closed until those checks and the connected
handoff/restart/uncertain-outcome acceptance sequence pass.
