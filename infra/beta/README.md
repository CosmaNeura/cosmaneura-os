# D3 isolated early-adopter beta infrastructure

This directory is preparation for `early_adopter_beta`. It is deliberately a
new Terraform boundary; it does not promote, import, rename, or share state
with the D2 synth environment or Track A.

The owner authorized D3 planning and implementation with
`APPROVE D3 ISOLATED EARLY-ADOPTER BETA`, recorded as `DL-20260903-03`.
`DL-20260903-04` selects the first deployment as a strictly non-PHI **Cosmas
Beta Lab**. That later decision removes named-clinic and BAA prerequisites only
for the synthetic lab; it does **not** authorize PHI use, D4-D6, live
connectors, D2 destruction, or Track A integration.

## Deployment-mode contract

Both Terraform roots expose the same `deployment_mode` enum:

| Mode | Resource tag | Runtime `DATA_MODE` | Clinic / BAA / PHI evidence |
|---|---|---|---|
| `synthetic_lab` (safe default) | `data_classification=synthetic-only` | `synthetic` | Omitted; real clinic and patient data prohibited |
| `authorized_beta` | `data_classification=phi-authorized` | `authorized_beta` | Named clinic, clinic approval, applicable BAA, and separate PHI authorization all required |

The bootstrap root emits the selected mode and classification. The first-plan
wrapper validates that pair and forces the environment root to use the same
mode, even if a variable file contains a conflicting value. The environment
derives `DATA_MODE`; callers cannot independently select a wider runtime mode.
Changing an existing deployment from `synthetic_lab` to `authorized_beta`
requires a separately reviewed plan and the complete authorized-beta evidence
set. Both roots create a `prevent_destroy` mode lock after that transition, so
a normal plan cannot relabel an environment that may retain PHI as synthetic.
Downgrade requires a separately reviewed decommission/reclassification change.
A mode value is not itself PHI authorization.

The environment root also requires an explicit `registry_network_posture`:

| Registry posture | Permitted mode | ACR/network result | Required review |
|---|---|---|---|
| `private` | `synthetic_lab` or `authorized_beta` | Premium ACR, public access disabled, Azure-services bypass disabled, and a VNet-linked `privatelink.azurecr.io` private endpoint | Private DNS/routing and current Premium/Private Link cost evidence |
| `synthetic_public_exception` | `synthetic_lab` only | Basic ACR with an authenticated public endpoint; admin credentials remain disabled and workload/deployer access remains RBAC-scoped | Non-empty `synthetic_public_registry_exception_reference` accepting the exposure for image artifacts that contain no PHI |

There is no implicit Basic/public fallback. `authorized_beta` rejects the
public exception even when an exception reference is supplied. Selecting
`private` also changes the human image-push and migration path: that runner
must resolve the registry's private DNS name and reach its private endpoint.

## Hard stop before Azure mutation

Do not initialize the remote backend, plan against Azure, or apply either root
until a human has explicitly selected the mode and recorded these common
requirements without inventing values:

- one dedicated logical Box UUID and human owner/approver;
- the separate Cosmas OS Clerk development application and Beta Lab design;
- before workloads are enabled, human approval of the Terraform-derived beta
  web HTTPS origin and the production Clerk application, Organization,
  issuer/audience/origin, with that one Organization mapped to the one Box;
- a region, residency, quota, SKU, and current calculator review;
- an explicit registry network posture and its cost/routing evidence, or a
  reviewed public-registry exception for `synthetic_lab` only;
- a protected human-deploy approval and private DNS/routing paths from the
  runner to both the state endpoint and the workload data endpoints;
- server-side Clerk-to-Box/Principal authorization evidence;
- managed-identity Azure Blob adapter evidence;
- PHI-safe telemetry review and backup/restore/retention evidence;
- a reviewed D3 capability manifest with every external connector dark;
- a human-owned `alert_contact_email` before workloads, followed by a delivered
  Azure Action Group test containing no application data; and
- a reviewed Central US availability and cost record for the selected Azure
  Managed Redis `Balanced_B0` broker and its private endpoint.

For `synthetic_lab`, a named clinic, clinic approval, BAA evidence, and PHI
authorization reference are not prerequisites and must not be fabricated. The
classification remains `synthetic-only` for the deployment's lifetime; only
invented people, appointments, identifiers, images, and money may enter it.

For `authorized_beta`, all of the following are additional hard preconditions:

- the clinic's legal covered-entity or BAA-scoped name;
- a human-controlled clinic approval reference;
- applicable Microsoft Azure, Clerk, and enabled-service BAA evidence; and
- a separate human-controlled PHI release authorization reference.

Required variables and Terraform preconditions enforce these attestations.
They can prove only that evidence references were supplied, not that the
evidence is true; the human reviewer remains accountable for verification.

No coding agent may receive the real variable values, backend access, live
credentials, plan binary, state, database access, Clerk credentials, or PHI.

## Layout and state boundary

- `bootstrap/` is a one-time, human-run root. It creates a dedicated state
  resource group, private state storage, workload resource group, a deployment
  UAMI scoped only to those D3 resources, and a no-public-IP
  Trusted Launch deployment VM in a separately filtered runner subnet. Its own
  bootstrap state must be kept in a human-controlled encrypted location and
  never in git; `bootstrap-local-state.sh` refuses an implicit repository-local
  state path.
- `environment/` is the workload root. Its partial `azurerm` backend must be
  configured only from protected bootstrap outputs. Azure AD authentication
  and blob-lease locking are required. The first-plan wrapper below derives
  the backend coordinates instead of accepting an arbitrary `backend.hcl`.

Never use Terraform workspaces to select D2 versus D3. Never initialize this
root against the D2 local state or Track A's `cosmaneura-tfstate` backend.

The backend account is private and shared-key authentication is disabled. The
bootstrap workstation creates only ARM/control-plane resources; the protected
runner creates the `tfstate` container over Private Link with its attached UAMI
after account-scope Blob RBAC propagates. Environment planning and apply then
run on that VM. Do not expose the state account or substitute an interactive
identity as a workaround.

## Provisional region

`centralus` is a provisional default because the sponsorship subscription
rejected PostgreSQL Flexible Server in `eastus`/`eastus2` during D2. D3 uses a
single region so Container Apps and private PostgreSQL can share one VNet.
The human must confirm residency, Container Apps, PostgreSQL, Redis, private
endpoint, zone, and SKU availability before any plan. A different verified
region may be supplied.

## Broker decision

The D3 source selects **Azure Managed Redis `Balanced_B0`** rather than the
retiring Azure Cache for Redis Basic C0 or a self-hosted Redis Container App.
It explicitly enables two-node high availability, encrypted client traffic,
access-key authentication through Key Vault, `NoCluster` for Celery transport
compatibility, `NoEviction` so memory pressure cannot silently discard queued
work, one-second AOF persistence, disabled public network access, and a
`redisEnterprise` private endpoint linked through
`privatelink.redis.azure.net`.

Read-only evidence collected on 2026-09-03 found the `redisEnterprise`
resource type in Central US and confirmed native `azurerm_managed_redis`
support in the pinned AzureRM 4.81 provider. Microsoft's published Central US
retail estimate for B0 was USD $0.018 per node-hour: approximately $13.14 per
month for one non-HA node or **$26.28 per month for the selected two-node HA
shape**, before Private Link data processing and other deployment costs. The
legacy Basic C0 meter was $0.022 per hour (about $16.06 per month), but all
Basic, Standard, and Premium Azure Cache for Redis instances retire on
2028-09-30. Refresh availability, quota, contract pricing, and the private
endpoint estimate immediately before planning; the protected
`broker_service_evidence_reference` records that human review.

A separate internal Redis Container App was rejected for D3. A single
0.25-vCPU/0.5-GiB replica would be roughly $5.91/month if continuously idle or
$19.71/month if continuously active before subscription-wide free grants, but
it would have no managed failover, durable volume, or TLS setup. Multiple
ordinary replicas would split broker state rather than provide Redis HA. The
application currently writes the authoritative operation row before enqueue,
but it has no scanner that re-enqueues a `PENDING` operation after complete
broker loss. That cheaper shape therefore does not meet the D3 worker
reliability requirement.

Evidence links:

- [Azure Cache for Redis retirement FAQ](https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/retirement-faq)
- [Azure Managed Redis overview and HA guidance](https://learn.microsoft.com/en-us/azure/redis/overview)
- [Azure Managed Redis Private Link](https://learn.microsoft.com/en-us/azure/redis/private-link)
- [Azure Managed Redis pricing](https://azure.microsoft.com/en-us/pricing/details/managed-redis/)
- [AzureRM 4.81 Managed Redis resource](https://registry.terraform.io/providers/hashicorp/azurerm/4.81.0/docs/resources/managed_redis)

## Intended workload boundary

In either mode, the environment root declares a dedicated resource group
containing:

- VNet-injected Container Apps web, API, and worker workloads;
- a dedicated ACR and separate immutable `cosmas-os@sha256:...` and
  `cosmas-os-web@sha256:...` image references, using
  either the private posture or the reviewed synthetic-only public exception;
- a dedicated API/worker UAMI with only ACR pull, Key Vault secret read, and
  container-scoped Blob data rights, plus a separate static-web UAMI whose only
  data-plane role is ACR pull;
- private PostgreSQL, Blob, Key Vault, and Azure Managed Redis data paths with
  private DNS;
- one dedicated database and one dedicated artifact container for the Box;
- purge-protected Key Vault and protected data resources;
- a dedicated PHI-safe Log Analytics workspace;
- a common-schema email Action Group plus symmetric API and worker
  `Replicas < 1` metric alerts, created only with workloads; and
- one subscription budget filtered to the exact state/runner and workload
  resource groups, with actual and forecast notifications to the owner.

The static web host and API have public HTTPS-only ingress. The worker has no
ingress. The only D3 peering is between the workload VNet and the bootstrap
state/protected-runner VNet, with explicit private-DNS links for the state and
workload endpoints. There is no VNet peering, shared identity, shared database,
shared storage, shared secret, or shared Terraform state with D2 or Track A.
ACR authentication is always
RBAC/managed-identity based and its admin account is disabled. Only the
reviewed `synthetic_public_exception` may expose that authenticated artifact
endpoint publicly; it never authorizes clinic data or PHI in images.

## Application readiness required before apply

Before producing the D3 digest, verify all of the following against that exact
image:

1. Validate Clerk JWTs server-side and map the token's Organization and user to
   the dedicated Box and a human Principal. Reject caller-supplied Box/actor
   authority.
2. Configure the single reviewed `WEB_ORIGIN`, reject wildcard CORS, and keep
   synthetic seed HTTP endpoints disabled outside `synth_os`. The reviewed
   human CLI seed remains limited to the fixed invented dataset and refuses
   `authorized_beta`.
3. Verify that the Azure Blob adapter uses the runtime UAMI and the dedicated
   `AZURE_STORAGE_ACCOUNT_URL` / `AZURE_BLOB_CONTAINER` rather than local disk.
4. Confirm logs never include PHI, credentials, request bodies, signed URLs, or
   blob paths. Keep opaque Box/correlation identifiers only where required.
5. Keep the isolated D3 artifact account synthetic-only. Its Blob versioning
   and Blob/container soft delete are deliberately disabled so the purge probe
   can require no exact-key object, version, snapshot, or deleted representation
   recoverable through Azure APIs. This is not physical-media erasure. The
   bootstrap tfstate account remains versioned with 30-day soft-delete
   protection, and PostgreSQL PITR remains separate.
6. Build least-privilege, non-root API/worker and static web images without
   development dependencies; scan them and pin both reviewed ACR digests. The
   web build accepts only public client configuration and never a Clerk secret.
7. Exercise the worker's private `:8001/ready` endpoint. It returns success
   only after Celery signals ready, its main-process heartbeat remains current,
   that exact worker answers a directed control ping through Redis, and the
   database reports the expected Alembic revision. Responses contain only a
   generic readiness status; the worker still has no public ingress. A worker
   bootstep also checks the database revision before Celery starts its Consumer,
   so a stale or unreachable schema exits before any task can be reserved.

The directed ping verifies the Celery control path and responsive consumer; it
does not prove application-task routing, Blob access, or completion of a real
operation. Record a separate idempotent synthetic operation smoke test after
deployment, using the PostgreSQL operation row as the authoritative result.

## Unresolved hard deployment blockers

The following items are intentionally not inferred from placeholders or
modeled as if they were complete. Keep `deploy_workloads = false` until a named
human has closed and recorded every blocker that applies:

- Execute the source-defined manual database-preparation job from the reviewed
  digest, then review its sanitized proof that the distinct non-admin runtime
  role cannot perform DDL or update/delete audit records and that Alembic
  reached the image's expected head. Supply the structured
  `database_preparation_attestation` and the separately generated
  `runner_live_network_evidence_reference` only from their completed live
  executions. The server administrator credential is
  isolated to the job and must never be mounted in the API or worker. See
  [`docs/beta/DATABASE_PREPARATION.md`](../../docs/beta/DATABASE_PREPARATION.md).
- Demonstrate the image's private worker-readiness probe against the selected
  live Managed Redis B0 broker. The source and Container Apps
  startup/readiness probes are wired, but only deployment evidence can prove
  the deployed instance supports Celery remote-control round trips and meets
  the probe timing budget.
- Build and review the production-configured web artifact after the foundation
  reveals the exact `web_origin` and `api_origin`; configure that web origin in
  the production Clerk instance, record the web release evidence, and supply
  the immutable web digest. The source path is implemented but not deployed.
- Select and review `registry_network_posture`. The source now implements both
  choices, but planning still requires either Premium/private routing evidence
  or a synthetic-only public exception reference. `authorized_beta` cannot use
  the exception.
- Add reviewed outbound egress control before any PHI authorization. Private
  data endpoints do not by themselves prevent a compromised workload from
  sending data to an arbitrary public destination.
- Apply and demonstrate the synthetic artifact account's exact-key purge proof:
  enumeration of current, version, snapshot, and deleted representations must
  return zero through Azure APIs. The source guard is implemented, but live
  evidence is still required. This deliberately gives up accidental-deletion
  recovery and does not prove physical-media erasure. Do not authorize PHI;
  `authorized_beta` needs a separately reviewed durability, backup, and legal-
  retention design.

All Athena, Acuity, email/SMS/A2P, Teams, payment, Track A, and other connector
rungs remain dark in both modes. Enabling any one requires its separate D5 gate
and capability manifest. The approved first path is `synthetic_lab`; PHI
loading requires an `authorized_beta` plan that passes the named-clinic, BAA,
and PHI-authorization preconditions.

## Human-only validation and planning path

Static validation may be run without a backend or credentials:

```bash
tofu -chdir=bootstrap init -backend=false
tofu -chdir=bootstrap fmt -check
tofu -chdir=bootstrap validate

tofu -chdir=environment init -backend=false
tofu -chdir=environment fmt -check
tofu -chdir=environment validate

tofu -chdir=bootstrap test
tofu -chdir=environment test
bash tests/deployment-guards.sh
```

After every prerequisite for the foundation is closed, a human creates an
encrypted directory outside the repository with mode `0700`. Bootstrap is
allowed only through the local-state wrapper, which refuses an implicit state
path, symlinks, repository paths, and non-private inputs. A new state must be
create-only. A canonical existing state may be reconciled only inside the two
exact D3 resource groups (plus the exact subscription budget), with its
lineage, serial, and hash bound to a non-destructive reviewed plan. It rejects
Terraform workspaces,
`TF_CLI_ARGS*`, `TF_VAR_*`, implicit/auto tfvars, or an uncommitted source tree.
The bootstrap tfvars must select the reviewed immutable Jammy Gen2 image
`runner_image_version = "22.04.202608060"`; `latest` or a different version is
not accepted:

```text
umask 077
mkdir -m 0700 /protected/ephemeral
bash ./bootstrap-local-state.sh plan \
  --state /protected/ephemeral/d3-bootstrap.tfstate \
  --var-file /protected/ephemeral/bootstrap.tfvars.json \
  --plan-out /protected/ephemeral/d3-bootstrap.tfplan \
  --review-out /protected/ephemeral/d3-bootstrap-review.json

# A named human reviews the source/tool/lock/tfvars hashes, exact boundary,
# every address/type/action, and the whitelisted before/after security posture
# for the state account, runner, networking, UAMI/RBAC, and budget. The private
# approval binds plan, review, and source.
bash ./bootstrap-local-state.sh apply \
  --state /protected/ephemeral/d3-bootstrap.tfstate \
  --var-file /protected/ephemeral/bootstrap.tfvars.json \
  --plan /protected/ephemeral/d3-bootstrap.tfplan \
  --review /protected/ephemeral/d3-bootstrap-review.json \
  --approval /protected/ephemeral/d3-bootstrap-approval.json

bash ./bootstrap-local-state.sh outputs \
  --state /protected/ephemeral/d3-bootstrap.tfstate \
  --output /protected/ephemeral/bootstrap-outputs.json
```

The bootstrap approval is a private mode-`0600` JSON object:

```json
{
  "schema_version": 1,
  "plan_sha256": "REVIEW_MANIFEST_PLAN_HASH",
  "review_sha256": "SHA256_OF_REVIEW_JSON",
  "source_sha": "FULL_REVIEWED_GIT_COMMIT",
  "reviewer": "NAMED_HUMAN",
  "review_reference": "APPROVAL_RECORD"
}
```

The bootstrap state remains local, encrypted, and private. It is never migrated
to the environment backend and never copied into the repository.

### Protected runner initialization

The bootstrap creates a `Standard_B2s` Ubuntu 22.04 Gen2 VM with secure boot,
vTPM, password login disabled, one private NIC, no public IP, an inbound-deny
NSG, explicit NAT egress, and `defaultOutboundAccess=false`. Only the exact D3
deploy UAMI is attached. The identity has workload-RG Contributor/User Access
Administrator plus narrowly scoped state-RG Reader, state-account Blob Data
Contributor, state-VNet Network Contributor, and state-zone Private DNS Zone
Contributor roles.

From an authorized workstation, use `prepare-protected-runner.sh`. It first
verifies the VM, attached identity, exact runner subnet, NSG, NAT gateway,
explicit default-outbound denial, and VM Agent state. It then uses Azure Run
Command to convert Ubuntu sources to HTTPS, install the exact reviewed apt
versions of Azure CLI, Docker, Docker Buildx, Git, and jq, install an exact
checksum-pinned OpenTofu release, log in with the attached UAMI, and
create/verify the private
`tfstate` container. Identity and Blob-RBAC propagation retries are bounded to
ten minutes. No token or secret is an argument, and the temporary Azure CLI
token cache is removed when the command exits.

```text
bash ./prepare-protected-runner.sh \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --tofu-version 1.12.5 \
  --tofu-sha256 dade9650e6b74fc7a8b986bd8717497d32f9e09cf82e479afef4977fa3085536 \
  --azure-cli-version '2.89.1-1~jammy' \
  --docker-version '29.1.3-0ubuntu3~22.04.2' \
  --docker-buildx-version '0.30.1-0ubuntu1~22.04.1' \
  --git-version '1:2.34.1-1ubuntu1.17' \
  --jq-version '1.6-2.1ubuntu3.2' \
  --trivy-version 0.74.0 \
  --trivy-sha256 2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a
```

Do not register the VM as a permanent GitHub Actions runner and do not use a
GitHub token. Create a one-use Ed25519 key locally, add only its public half as
a temporary **read-only** repository deploy key, and create a mode-`0600`
known-hosts file containing the independently verified GitHub Ed25519 host key
for `[ssh.github.com]:443`. The only implemented source ingress is the guarded
managed Run Command path below; it fixes the origin to the CosmaNeura repo,
uses SSH over the NSG-permitted port 443, checks out the exact full commit,
disables the push URL, and deletes the private key from `/run` when done:

```text
bash ./transport-to-protected-runner.sh stage-source \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --deploy-key /protected/ephemeral/github-readonly-deploy-key \
  --known-hosts /protected/ephemeral/github-known-hosts
```

Remove the public deploy key from GitHub immediately after this command
succeeds. Never reuse it and never grant write access. For each stage, prepare
a JSON tfvars object in the encrypted mode-`0700` directory and send it only as
an Azure managed Run Command **protected parameter**. The controller builds an
`@file` ARM request so secret values do not enter shell process arguments or
Azure command output:

```text
bash ./transport-to-protected-runner.sh stage-vars \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --stage foundation \
  --var-file /protected/ephemeral/foundation.tfvars.json

bash ./transport-to-protected-runner.sh plan \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --stage foundation \
  --artifact-out /protected/ephemeral/d3-beta-foundation-review.json
```

The binary plan, tfvars, logs, and backend data stay on the root-owned,
no-inbound VM. Only the compressed whitelist review/result is returned through
Run Command and written mode `0600`. Each plan/apply session creates a fresh
temporary Azure CLI cache, logs in with the attached exact UAMI, verifies its
token and the D3 boundary, forces the checksum-pinned `/usr/local/bin/tofu`,
then erases the token cache. Never hand-author backend coordinates or invoke
the environment wrappers directly from an interactive identity.

The wrapper derives the backend and deployment mode from bootstrap outputs,
rejects an invalid mode/classification pair, verifies the active Azure
subscription, tenant, and dedicated deploy identity, verifies private Blob
access, uses the create-only path only when no canonical state history exists,
and otherwise selects a lineage-bound complete-state or bounded partial-
foundation reconciliation path. It initializes with Azure AD only, forces
`enable_database_preparation_job = false` and `deploy_workloads = false`, and
rejects any managed plan action other than `create`. It performs Azure reads
and a Terraform plan when the authorized
human runs it; it is not a static/offline check. Do not bypass it with a
handwritten backend file. After reviewing its sanitized manifest, create a
private approval file that binds the named reviewer and evidence reference to
the exact hash:

```json
{
  "schema_version": 1,
  "plan_sha256": "REVIEWED_64_HEX_HASH",
  "state_lineage": null,
  "state_serial": null,
  "reviewer": "NAMED_HUMAN",
  "review_reference": "APPROVAL_RECORD"
}
```

Apply only through the corresponding protected transport. The approval file
is itself sent as a protected parameter and the result is the only returned
artifact:

```text
bash ./transport-to-protected-runner.sh apply \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --stage foundation \
  --approval /protected/ephemeral/d3-beta-foundation-approval.json \
  --artifact-out /protected/ephemeral/d3-beta-foundation-result.json
```

After each state-changing apply, create a fresh state-generation-bound network
proof. Then build both `linux/amd64` images on the protected runner from the
approved source SHA. The build uses the foundation-derived API origin, a
hash-bound pnpm toolchain, locked/offline dependency installation, the pinned
Docker Buildx `0.30.1` plugin with the Docker 29 daemon, a Docker
network that is proven unable to reach Azure IMDS/WireServer, HIGH/CRITICAL
Trivy gates, immutable source-SHA tags, and both tag-level and manifest-digest
write/delete locks with readback:

```text
bash ./transport-to-protected-runner.sh probe-network \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --artifact-out /protected/ephemeral/d3-beta-network.json

bash ./transport-to-protected-runner.sh build-push \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --web-build-config /protected/ephemeral/public-web-build.json \
  --artifact-out /protected/ephemeral/d3-beta-build.json
```

`public-web-build.json` contains only `vite_cosmas_env`,
`vite_clerk_publishable_key`, and the exact foundation `vite_api_base`. A
different state serial requires a new append-only network probe generation;
the already accepted source/digest build evidence remains reusable after its
ACR tags and digests are revalidated.

The environment is intentionally three-stage. First apply the complete
reviewed foundation with both `enable_database_preparation_job = false` and
`deploy_workloads = false`; this creates the dedicated ACR, Container Apps
environment, and private services but no application revision, database job,
artifact container, or Key Vault workload secret. Its non-secret `web_origin`
and `api_origin` outputs are the only hostnames approved for Clerk and the
browser build. Next push the reviewed application digest, plan the manual job
with `enable_database_preparation_job = true`, start it once, and retain its
sanitized successful role/migration evidence as described in
[`docs/beta/DATABASE_PREPARATION.md`](../../docs/beta/DATABASE_PREPARATION.md).
A human also configures production Clerk and follows
[`docs/beta/WEB_RELEASE.md`](../../docs/beta/WEB_RELEASE.md). Only then may a
human produce the workload plan with `deploy_workloads = true`, both immutable
image digests, exact origin and web evidence, protected runtime URL, the
structured database attestation, and live-runner network evidence. Do not use
targeted applies, the administrator
URL, or a mutable tag to bypass this ordering gate. The first-plan wrapper
deliberately refuses canonical existing state. A complete foundation retry uses
the ordinary subsequent/no-op drift path; an interrupted partial foundation
uses the explicit `foundation_reconcile` phase. Both bind the backend and
pre/post-plan state lineage, serial, and hash.

The optional web custom domain is a two-plan workload stage because the
app-specific verification value does not exist before the web Container App.
In the first plan, select a new lowercase `web_custom_domain`, keep
`web_custom_domain_dns_ready = false`, and set `web_origin` to the matching
HTTPS origin. That creates the web app but no domain binding; do not admit
testers yet. Re-run `probe-network` for the resulting state, then retrieve the
exact public DNS material through the protected runner:

```text
bash ./transport-to-protected-runner.sh domain-verification \
  --bootstrap-outputs /protected/bootstrap-outputs.json \
  --source-sha <40-hex-reviewed-sha> \
  --release-id <immutable-release-id> \
  --artifact-out /protected/evidence/domain-verification.json
```

The mode-`0600`, self-hashed artifact exposes only the selected hostname, ACA
CNAME target, `asuid` TXT name/value, and its exact source/release/state
binding. The TXT value is public DNS publication material, not an application
credential; the raw Terraform output and all unrelated state remain on the
runner. A human then creates and externally verifies those exact records in
the Cloudflare-hosted zone and adds the exact origin/redirects to Clerk. A
second state-bound plan may set `web_custom_domain_dns_ready = true` and create
the managed-certificate binding. Terraform neither selects nor mutates public
DNS, and it explicitly refuses the existing `app.cosmaneura.com`,
`staging-app.cosmaneura.com`, `chat.cosmaneura.com`, and
`staging-chat.cosmaneura.com` hosts. AzureRM 4.81 requires the managed-certificate
binding's `certificate_binding_type` and
`container_app_environment_certificate_id` to be omitted and lifecycle-
ignored because Azure populates them asynchronously.

For both the database-preparation and workload stages, use the guarded
protected transport and guarded subsequent plan flow. Continue using the same
`release-id` that produced the accepted build evidence through all stages of
that release. Each `release-id` is immutable and bound on-runner to one source
SHA, so a later source candidate uses a new ID and produces its own build
evidence instead of overwriting reviewed source, tfvars, plans, approvals, or
results:

```text
umask 077
bash ./transport-to-protected-runner.sh stage-vars \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --stage database \
  --var-file /protected/ephemeral/database.tfvars.json

bash ./transport-to-protected-runner.sh plan \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --stage database \
  --artifact-out /protected/ephemeral/d3-beta-database-review.json
```

The plan binary and raw `terraform show -json` output can contain the database
administrator password, runtime connection URL, Redis key, evidence references,
and other sensitive values. Never print, upload, or commit them.
The wrapper generates a sanitized review artifact containing only:

- Terraform version, provider-lock hash, tfvars hash, and plan hash;
- prior-state lineage, serial, and hash;
- resource address, type, and action list;
- exact add/change/destroy totals;
- critical non-secret outputs; and
- a strict before/after security-posture projection covering network exposure,
  identity/RBAC scopes, retention, SKU/scale, ingress/probes, runtime mode, and
  monitoring. Any new managed resource type fails closed until it receives an
  explicit non-secret projection.

Do not include unfiltered `before`, `after`, planned values, variables,
child-module values, secret URIs, clinic identifiers, or provider
configuration. The first foundation plan must contain creates only. Any
delete, replacement, forget action, D2 resource address, pre-existing
synth, Track A identifier, unexpected subscription, or state lineage/serial
change is a hard stop. After a named human reviews the manifest, create the same
approval JSON shape with its exact `plan_sha256`, `prior_state.lineage`, and
`prior_state.serial`, then apply that exact binary:

```text
bash ./transport-to-protected-runner.sh apply \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --stage database \
  --approval /protected/ephemeral/d3-beta-approval.json \
  --artifact-out /protected/ephemeral/d3-beta-result.json
```

The apply wrapper rechecks the UAMI token claims, actual resource-group tags,
Box/mode/network boundary, plan hash and action counts, and current remote-state
lineage/serial before applying. It requires the backend lock's own saved-plan
freshness check to pass, then records only the post-apply lineage, serial, state
hash, plan hash, reviewer, and evidence reference. The wrappers never print raw
plan/state JSON and categorically refuse delete/replacement plans; such a change
requires a separate reviewed recovery procedure and code change.

After applying the database stage, start and attest the unscheduled job through
the same protected channel; do not use `az containerapp exec` or return raw job
logs:

```text
bash ./transport-to-protected-runner.sh database-prepare \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --artifact-out /protected/ephemeral/d3-beta-database-attestation.json
```

The command checks the exact job identity, image, secret references, database
server, execution ID, and one self-hashed credential-free result. Its log
stream uses the same undocumented preview endpoints as the pinned official
Azure CLI Container Apps extension; a live preflight failure is a hard stop.

After workload apply and a fresh network probe, the first synthetic owner and
fixed invented seed are created only by `bootstrap-identity` with a protected
deployment envelope binding source SHA, release ID, state lineage/serial,
accepted API digest, Box, and Clerk values. Runtime database/Redis secrets are
read inside the runner and never returned:

```text
bash ./transport-to-protected-runner.sh bootstrap-identity \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --bootstrap-manifest /protected/ephemeral/beta-bootstrap-envelope.json \
  --artifact-out /protected/ephemeral/d3-beta-identity-bootstrap.json
```

The workload apply also creates one manual, unscheduled runtime-acceptance job
using the exact API digest and runtime UAMI. Its database, Redis, Blob, Clerk,
and acceptance-HMAC values are secret references or reviewed non-secret values;
the protected command validates the realized execution template before reading
one exact self-hashed result. Run the dependency probe first. The browser
workflow and physical-purge checks are two-phase: retain the sanitized baseline
or setup artifact outside the repository, perform the named human browser step,
then pass that artifact back only as a protected parameter. The signed state is
bounded to 16 KiB and expires after four hours:

```text
bash ./transport-to-protected-runner.sh runtime-acceptance \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --acceptance-phase runtime \
  --artifact-out /protected/ephemeral/runtime-acceptance.json

bash ./transport-to-protected-runner.sh runtime-acceptance \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --acceptance-phase workflow-baseline \
  --artifact-out /protected/ephemeral/workflow-baseline.json

# After the named human completes the reviewed browser approval:
bash ./transport-to-protected-runner.sh runtime-acceptance \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --acceptance-phase workflow-verify \
  --acceptance-state /protected/ephemeral/workflow-baseline.json \
  --artifact-out /protected/ephemeral/workflow-verified.json
```

Use the analogous `purge-setup` then `purge-verify` phases for the owner-
authorized physical-purge check. The proof means that no exact-key current
object, version, snapshot, or deleted representation remains recoverable via
Azure APIs; it does not claim physical-media erasure. The wrapper returns
opaque handles, counts, and booleans only; it never returns the HMAC key,
runtime URLs, record IDs, or Blob paths.

Alert delivery is also a two-phase protected operation. `send` first proves the
exact email-only Action Group and both enabled API/worker replica alerts, then
calls Azure's Action Group test API without putting the recipient address in an
argument or returned evidence. It returns an unpredictable confirmation
challenge, the exact send timestamp, and a hash of the Azure test operation.
The owner records receipt in a mode-`0600` JSON assertion containing exactly
`schema_version`, the returned `challenge` and `send_evidence_sha256`, a
whole-second UTC `confirmed_at`, the literal assertion
`I CONFIRM RECEIPT OF THE D3 ALERT TEST`, and a non-email
`confirmation_reference`. `confirm` accepts that assertion only within four
hours of the exact send and returns hashes of the assertion/reference, never the
recipient address:

```text
bash ./transport-to-protected-runner.sh alert-delivery \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --alert-phase send \
  --artifact-out /protected/ephemeral/alert-send.json

bash ./transport-to-protected-runner.sh alert-delivery \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --alert-phase confirm \
  --alert-test-state /protected/ephemeral/alert-send.json \
  --delivery-confirmation-reference /protected/ephemeral/alert-owner-confirmation.txt \
  --artifact-out /protected/ephemeral/alert-confirmed.json
```

Immutable release recovery is a separately owner-approved, two-phase live
test. It cannot run until **two distinct releases** have each been staged and
built by this protected runner; both API digests and both web digests must be
different, scan-clean, and locked against tag and manifest writes/deletes. Put
the following exact object in a mode-`0600` file outside the repository (using
the real values from the two sanitized build artifacts):

```json
{
  "schema_version": 1,
  "contract": "cosmas-os-d3-release-recovery-approval-v1",
  "confirmation": "AUTHORIZE D3 IMMUTABLE DIGEST ROLLBACK AND FORWARD RECOVERY",
  "approved_at": "2026-09-03T16:00:00Z",
  "reviewer_reference": "owner-ledger:release-recovery-001",
  "current": {
    "source_sha": "CURRENT_40_HEX_SHA",
    "release_id": "current-release",
    "api_digest": "sha256:CURRENT_64_HEX_API_DIGEST",
    "web_digest": "sha256:CURRENT_64_HEX_WEB_DIGEST"
  },
  "prior": {
    "source_sha": "PRIOR_40_HEX_SHA",
    "release_id": "prior-release",
    "api_digest": "sha256:PRIOR_64_HEX_API_DIGEST",
    "web_digest": "sha256:PRIOR_64_HEX_WEB_DIGEST"
  }
}
```

Run rollback, review its exact revision IDs and health evidence, and then run
forward immediately with the same approval. `release-forward` is also the
recovery command after an interrupted or unhealthy partial rollback. The
runner accepts only `registry/repository@sha256:...` image references, verifies
the current and prior ACR locks and build evidence, preserves the non-image
Container App configuration, proves the 100%-to-latest route, API `/ready`, web
`/healthz`, and the worker's healthy ready revision, then requires a final
refresh-backed Terraform plan with zero managed changes:

```text
bash ./transport-to-protected-runner.sh release-rollback \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha CURRENT_40_HEX_SHA \
  --release-id current-release \
  --prior-source-sha PRIOR_40_HEX_SHA \
  --prior-release-id prior-release \
  --approval /protected/ephemeral/release-recovery-approval.json \
  --artifact-out /protected/ephemeral/release-rollback.json

bash ./transport-to-protected-runner.sh release-forward \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha CURRENT_40_HEX_SHA \
  --release-id current-release \
  --prior-source-sha PRIOR_40_HEX_SHA \
  --prior-release-id prior-release \
  --approval /protected/ephemeral/release-recovery-approval.json \
  --artifact-out /protected/ephemeral/release-forward.json
```

Offboarding acceptance also uses two phases so no raw Clerk subject, Org ID,
Box ID, or principal ID is returned. The mode-`0600` baseline request outside
the repository contains exactly `schema_version: 1`, contract
`cosmas-os-d3-offboarding-request-v1`, the exact `box_id`, `clerk_issuer`,
`clerk_organization_id`, `clerk_subject`, and `principal_id`, plus a
whole-second UTC `approved_at` and non-email `reviewer_reference`:

```text
bash ./transport-to-protected-runner.sh offboarding-acceptance \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha CURRENT_40_HEX_SHA \
  --release-id current-release \
  --offboarding-phase baseline \
  --offboarding-request /protected/ephemeral/offboarding-request.json \
  --artifact-out /protected/ephemeral/offboarding-baseline.json
```

An authenticated active Box owner must then deactivate that exact non-owner
synthetic identity in **Manage access**, supplying the returned
`required_deactivation_evidence_ref`. In the Clerk dashboard, the owner must
remove that user's Cosmas Beta Lab Organization membership and revoke every
session, then use a fresh browser session to confirm that the user cannot
access the app or API. Those Clerk/browser steps are unavoidably human-observed;
the evidence deliberately records them as human attestations, not as a
cryptographic proof of the operator's identity.

Create a mode-`0600` confirmation outside the repository with exactly the
returned `challenge` and `baseline_evidence_sha256`, a whole-second UTC
`confirmed_at`, a non-email `confirmation_reference`, the literal
`owner_assertion: "I CONFIRM D3 CLERK OFFBOARDING AND LIVE ACCESS DENIAL"`, and
all three booleans `clerk_organization_membership_removed`,
`clerk_sessions_revoked`, and `live_access_denied` set to `true`. Then run:

```text
bash ./transport-to-protected-runner.sh offboarding-acceptance \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha CURRENT_40_HEX_SHA \
  --release-id current-release \
  --offboarding-phase verify \
  --offboarding-state /protected/ephemeral/offboarding-baseline.json \
  --offboarding-confirmation /protected/ephemeral/offboarding-confirmation.json \
  --artifact-out /protected/ephemeral/offboarding-verified.json
```

The protected verifier independently proves the exact app binding is inactive,
the non-owner principal is disabled, exactly one owner-authorized audit event
matches the challenge, and the app authentication boundary denies that binding.

PostgreSQL point-in-time restore acceptance is an explicitly downtime-bound,
protected sequence. It is synthetic-only and uses the exact immutable API image
to compare credential-free database fingerprints. `pitr-freeze` records the
single active API and worker revisions, deactivates only those revisions, proves
zero active replicas and no running database/runtime jobs, and returns the
quiet-window start. Wait at least five minutes, then select a restore timestamp
inside the returned window:

```text
bash ./transport-to-protected-runner.sh pitr-freeze \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --quiet-window-end-utc 2026-09-03T18:30:00Z \
  --artifact-out /protected/ephemeral/pitr-freeze.json

bash ./transport-to-protected-runner.sh pitr-manifest \
  --bootstrap-outputs /protected/ephemeral/bootstrap-outputs.json \
  --source-sha FULL_REVIEWED_GIT_COMMIT \
  --release-id initial-beta \
  --restore-time-utc 2026-09-03T16:00:00Z \
  --artifact-out /protected/ephemeral/pitr-manifest.json
```

Review the returned manifest evidence and create a distinct-owner mode-`0600`
approval with exactly `schema_version: 1`, its `manifest_sha256`, the literal
`confirmation: "AUTHORIZE D3 BILLABLE PITR"`, a whole-second UTC `approved_at`,
and a non-email `reviewer_reference`. Use that same approval for `pitr-start`,
repeat `pitr-complete` while its sanitized status is `restore_pending` or
`cleanup_pending`, and use `pitr-cleanup` after any interrupted/failed run. The
private manifest, state, credentials, and restored server ID never leave the
runner. Writers remain stopped until a terminal `verified` or `cleaned` record
exists; then `pitr-resume` requires a separate mode-`0600` owner assertion with
exact keys `schema_version: 1`, the freeze artifact's
`freeze_evidence_sha256`, literal `confirmation: "RESUME D3 WRITERS"`,
`approved_at`, and `reviewer_reference`. Resume activates only the two recorded
revisions and proves API health plus exact API/worker replica counts. If the
approval or quiet window expires, run guarded cleanup and resume explicitly;
never leave the beta writers stopped without an operator handoff. The primitive
contract and recovery details are in `PITR_ACCEPTANCE.md`.

If the controller loses connectivity after dispatch, use `retrieve` for the
exact review/result/network/build/database/runtime/alert/PITR/recovery/
offboarding/identity artifact; phase-specific artifacts require their exact
phase selector. Use
`cleanup-commands` only after it proves every exact `cosmas-d3-*` command on
the protected VM is terminal; it deletes stale Run Command resources without
reading their protected contents. Per-run logs, plans, approvals, and tfvars
remain root-only and release/stage scoped. A failed bootstrap or foundation
apply is recovered only by a new non-destructive, lineage/serial/hash-bound
review and approval; deletion or replacement remains refused.

## Cost controls

Security boundaries are fixed; cost choices are variables. Review at least:

- API/worker CPU, memory, and replica bounds;
- PostgreSQL SKU, storage, backup retention, and geo-redundancy;
- the fixed Managed Redis B0 two-node HA estimate, its private endpoint, and
  any contract-specific discount or charge;
- Blob replication and the synthetic artifact account's deliberate lack of
  versioning/soft-delete recovery (bootstrap tfstate protection is unchanged);
- Log Analytics retention and daily ingestion cap;
- private endpoint and DNS costs, including the materially higher recurring
  Premium ACR cost for `private` versus the broader authenticated endpoint
  exposure accepted by the lower-cost synthetic-only Basic/public exception;
  and
- the aggregate two-resource-group budget and alert recipients.

The current planning envelope is approximately **$170–260/month at low
traffic** across the state/runner and workload groups. Bootstrap creates a
**$350/month subscription budget filtered to those exact two groups**, with
actual and forecast notifications to the human-owned recipients supplied in
the private bootstrap variables. It is an alert, not a spending cap. Refresh
calculator evidence without assuming credits before approving a plan.

## Required human verification after apply

- Clerk login, membership, role, and Clerk Org -> Box/Principal mapping.
- Cross-Box and caller-supplied identity rejection.
- Database and Redis reachability with their public endpoints disabled.
- Managed-identity Blob write/read/purge plus exact-key current/version/
  snapshot/deleted absence through Azure APIs, without shared keys or SAS in
  logs.
- Audit replay and PHI-safe telemetry.
- Migration head, backup/restore, and retention/purge reconciliation.
- API health and worker readiness.
- Action Group test delivery to the exact human-owned recipient and both API
  and worker replica alerts' enabled state; record only timestamp/resource IDs
  and the owner-confirmation reference hash, never the address or message body.
- Rollback to the prior reviewed image digest.
- Exact registry posture agreement: Premium/public-disabled/Private Link for
  `private`, or the reviewed Basic/public exception for `synthetic_lab` only.
- Exact deployment mode, classification tag, and runtime `DATA_MODE` agreement;
  for `synthetic_lab`, no PHI-authorized entry path is exposed and tester
  instructions continue to prohibit real data.
- Explicit acknowledgement that D3 artifact recovery is disabled and that
  `authorized_beta` must not inherit this retention design without a new
  durability, PHI, legal-retention, and recovery review.

Record only sanitized evidence in git. D3 is not complete until every item is
demonstrated by the authorized human path.
