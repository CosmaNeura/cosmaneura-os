# Automatic dedicated CosmaBot practice workspaces

This is a separate, single-practice module for the private enrollment worker.
It does not import, rename, own, or modify the frozen `../workspaces` a/b
deployment, its state, or its resources. The public account API records one
durable allocation intent when a registered practice owner accepts the BAA;
the private worker performs the hosting steps without a per-customer command.

The source is prepared locally. **Publishing images, enabling the worker,
applying infrastructure, creating credentials, and changing DNS remain held.**
The local tests use invented providers and do not qualify actual Azure hosting.

## Result and boundary

Each registered canonical practice UUID receives its own UUID-derived Box,
Clerk organization, PostgreSQL database, runtime identity, vault, Redis service,
private artifact storage, and independently encrypted state key. Its paired
addresses are `https://<practice UUID>.staging.cosmas.ai/chief` and
`https://api.<practice UUID>.staging.cosmas.ai`. Only the already selected
development enrollment realm is supported by this staging implementation.

Allocation does not mark a member or workspace ready, grant admission, create
a subscription, or start the 14-day trial. After actual hosting completes, the
existing authenticated confirmation flow must measure the native transport,
verify the reserved owner binding, persist its exact proof, and then complete
the card/trial gates. Existing beta users keep their existing enrollment bypass.

## Public input contract

The private worker reads an owner-controlled, regular, mode `0600` JSON file
with `contract_version: "cosmas-private-hosting.v1"`. Its schema is validated by
`src/cosmas_os/enrollment/hosting.py`; no customer chooses these values.

| Field | Required value or reference |
| --- | --- |
| `enabled`, `synthetic_only` | Explicit host enable switch; synthetic must be `true`. Leave `enabled` false until the held prerequisites are reviewed. |
| `foundation` | The existing dedicated `enrollment-foundation.v1` staging output, including subscription, tenant, location, resource group, registry, VNet, Container Apps environment, PostgreSQL and endpoint subnet IDs, and the independent state backend. |
| `foundation.blob_private_dns_zone_id`, `redis_private_dns_zone_id`, `vault_private_dns_zone_id` | Exact existing private service zone IDs inside that dedicated resource group. These are references only. This module owns its Box endpoint records, not the existing shared zones or links. |
| `account` | Exact onboarding and enrollment API origins, development Clerk issuer, matching public key, and exact audience already selected by the enrollment host. |
| `release` | One reviewed committed source SHA and digest-pinned API and allocated-job images in the dedicated registry. Their real source/image validation and Trivy acceptance receipts must precede enablement. |
| `worker_client_id`, `worker_object_id` | The dedicated private worker user-assigned managed identity's public identifiers. |
| `source_repository` | Absolute path to a clean checkout of that exact reviewed commit. The new module must contain only committed files; no untracked files or symlinks may execute. |
| `state_root` | Persistent owner-controlled `0700` directory outside the checkout, with a durable private volume and backup/custody policy. |
| `cloudflare_zone_id`, `cloudflare_token_file` | The public `cosmas.ai` zone identifier and absolute reference to a separately authorized, protected `0600` token file. Never put a token in the JSON, repository, arguments, or logs. |
| `native_origins` | Explicit unique subset of `capacitor://localhost` and `app://cosmas`, matching the enrollment host configuration. |
| `google` (optional) | Exactly `client_id`, `callback_uri`, and `client_secret_file`. The reviewed Google web client must match the enabled enrollment broker; callback is exactly `account.api_origin + "/connections/google/callback"`. The existing client-secret file reference is absolute, outside source, owner-controlled and mode `0600`; its contents are read only by the separately enabled private seed operation. Omit the whole object to preserve allocation without Google. |

The enrollment host also needs its existing protected Clerk, Stripe, registry
database and admission-key references. The worker requires native account,
provisioning and allocation settings to be explicitly enabled together, the
existing registry schema to be current, and synthetic mode to be selected.
No new public registration endpoint can submit a Box, URL, proof, or ready bit.

With the explicit Google option, the enrollment service must have matching
`ENROLLMENT_GOOGLE_CALLBACK_BROKER_ENABLED`,
`ENROLLMENT_GOOGLE_CALLBACK_BROKER_ORIGIN`, and
`ENROLLMENT_GOOGLE_CALLBACK_CLIENT_ID` settings. The private plan contains only
the public client/callback. The worker seeds the existing client secret and a
separate-purpose per-Box token-custody key in that Box's own vault; the custody
key derives from its existing admission custody. Broker signing uses the
existing admission key, with no new relay secret. Only the Box runtime receives
the two Google secret references. Migration and owner-preparation jobs keep
their original five-secret boundary and receive no Google settings or custody.

The unchanged shared runtime module still requires both versioned Google
references before enabling its three Google flags. Only the reviewed broker
callback overrides the module's default callback; other environment merge
rules remain intact. The public web builder reuses its existing feature-profile
argument to select `independent-beta-v1` after those runtime settings and exact
Box-vault references are present. This includes only the existing standalone
features plus Google, with the same synthetic/Org/origin guards. Omission keeps
`standalone-practice-v1`; no secret or protected-file reference enters build
arguments, public renderer assets, or provider logs. Native and web account
consent and actual Google grant verification remain separate from allocation.

## Execution requirements still to qualify

1. Publish and validate the exact new API and `Dockerfile.job` images through
   the existing uncompromised security gates. The old fa5 publication is not
   evidence that this new source is installed.
2. Review and provide the private worker's managed identity and dedicated
   resource-group/ACR permissions. It must create only this module's resources,
   assign the declared Box identities, deploy scoped vault secrets, start and
   inspect its jobs, build and lock the per-practice web image, and read only
   the host-only receipt container. State access uses managed identity, not
   storage keys. No runtime identity reads hosting receipts.
3. Give that host private network access to the enrollment registry, state
   storage, Box vault/Blob endpoints and PostgreSQL network. Preserve all
   existing a/b resources and zone/link ownership. Supply actual available
   subnet capacity: this worker measures at least eight PostgreSQL and four
   endpoint addresses before initial creation and leaves the operation pending
   if capacity is unavailable. It does not enlarge a subnet.
4. Separately authorize a `cosmas.ai` DNS credential scoped as narrowly as the
   provider supports. The worker validates the zone and every exact UUID CNAME
   and verification TXT record before writing; foreign or ambiguous existing
   records stop the operation. It checks propagation before certificate binding.
5. Qualify the actual Azure CLI commands and provider/API contracts in this
   foundation. OpenTofu 1.12.5 and the locked AzureRM 4.81.0 module validate
   locally. Read-only Azure provider metadata confirms Microsoft.App jobs,
   container apps and managed environments support `2025-07-01`. The Redis
   Enterprise database ListKeys request uses its documented stable `2024-10-01`
   contract; `2024-11-01` belongs to classic Redis, not this database resource.
   See the [official Enterprise API specification](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/redisenterprise/resource-manager/Microsoft.Cache/RedisEnterprise/stable/2024-10-01/redisenterprise.json).
   Actual request-body/response compatibility, the Key Vault
   `2024-11-01` call, DNS, private connectivity, jobs, RBAC propagation and managed
   TLS still require a real held staging acceptance run.

## Private worker recipe, after those holds are released

The public API queues intent only. A separately hosted private worker runs:

```text
python -m cosmas_os.enrollment.hosting_worker --configuration /protected/host-configuration.json --run --once
```

Omit `--once` for the reviewed continuous worker. `--run` is mandatory; source
preparation or API startup cannot launch allocation. Never run this command
against a clinical or legacy service or with production credentials.

For each intent it rechecks the active owner, registered practice and acceptance,
reuses the saved immutable plan, and acquires the existing private PostgreSQL
allocation lock. The real adapter then checks source and subnet capacity,
creates private infrastructure in an independent state key, persists scoped
credentials, measures the existing migration and owner-reservation jobs,
builds the exact per-practice web client, runs actual image validation and the
unchanged CI-pinned Trivy scanner, pushes/locks its digest, deploys workloads,
and checks owned DNS, managed certificates and HTTPS health.

## Recovery and custody

The encrypted per-practice backend key is
`cosmabot-enrollment/staging/allocated/<practice UUID>.tfstate`; it never imports
an a/b or clinical state. The persistent worker directory retains exact plans,
first owner reservation manifests, credential files, provider execution IDs,
image digests and receipts. These private files must survive worker restarts.
No bearer JWT or customer patient data belongs in them.

Lost job start replies recover the observed original execution. A confirmed
failed job permits at most three retained attempts; stopped/canceled jobs and
unresolved or ambiguous execution handles remain pending for review. Failed
image/security gates never produce an allocated result. Existing owned
certificates are reused; failed or ambiguous certificates are retained without
creating a duplicate. A lost final registry reply rechecks actual TLS/health
before acknowledging the same allocation.

Keep partial resources and custody files when recovery is needed. The module
protects storage, vault and database resources from destruction. Do not remove
state, rotate credentials, delete resources, or bypass a proof as a retry.
