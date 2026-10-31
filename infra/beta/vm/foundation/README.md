# East US 2 VM staging foundation

The owner selected this dedicated synthetic staging path on September 25, 2026.
This module creates its Azure foundation. It does not install or launch CosmaBot,
format disks, read application secrets, configure DNS at the registrar, connect
Core/Scribe, migrate a database, or modify the existing managed environment,
protected runner, bootstrap network or Terraform state.

The selected shape is a new `rg-cosmas-os-vm-staging-eus2-lab01` resource group and
`vm-cosmabot-staging-eus2-lab01` host: East US 2, D2s_v5 (2 CPU/8 GiB), 64 GiB OS
and 128 GiB persistent data disks. Both disks use Standard SSD LRS. OpenTofu is
pinned to 1.12.5, AzureRM to 4.81.0, and the Ubuntu Gen2 image to
`Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:22.04.202608060`.
The existing reviewed provider checksums are retained in the lock file.

One new VNet has workload/private-endpoint subnets. The Standard static public
IPv4 provides explicit outbound access. Only TCP 443 and 80 are admitted from
the Internet; the explicit deny also overrides Azure's default VNet ingress.
There is no SSH ingress. Port 80 is reserved for the later host's ACME handler
and HTTPS redirect. No listener is installed here. Azure Run Command is the
management path; its VM agent is enabled. Container-aware host firewall and
IMDS isolation must be installed before any application container starts.

Private Premium ACR, private RBAC Key Vault, and distinct Hot LRS application/
backup storage accounts use four private endpoints and three private DNS zones.
The two Blob endpoints share one zone. Only this new VNet receives DNS links.
There is no connection to or alteration of the protected runner's network.
The module also creates a 30-day Log Analytics workspace, three platform metric
alerts (VM availability, CPU, OS-disk IOPS), and the supplied alert recipient's
action group. Guest telemetry, application readiness and backup-freshness alerts
still belong to runtime integration; platform metrics do not prove those.

## Inputs and state

Supply actual reviewed subscription/tenant IDs, a unique resource suffix, the
non-overlapping RFC1918 VNet prefix, operator Linux username/public SSH key,
off-VM release principal's object ID and alert recipient. The committed tests
use invented values only; never copy them into an actual plan. Image/region
inputs are locked to the selected values. No password, token, private key,
application configuration or secret value is accepted by this module.

This root now uses a **fresh local backend**, encrypted by OpenTofu itself with
PBKDF2 (600,000 SHA-512 iterations) and AES-GCM. Both state and saved plans set
`enforced = true`; no unencrypted fallback exists. This selected initial path
requires no old runner identity, old storage access or expansion of their roles.
A future dedicated remote backend migration is optional later work.

`bootstrap_local.py fingerprint` reports the current source and provider-lock
hashes for local review. After review, `prepare` requires those exact hashes,
actual public inputs, a pinned OpenTofu executable, the verified provider mirror
and a **fresh absolute directory outside the repository**. The script verifies
the enabled subscription/tenant against the current owner CLI user session,
refuses service principals and confirms the new resource group is still absent.
It creates a 0700 directory, a random 0600 passphrase file, a private source
snapshot and an isolated local backend. The passphrase is never a CLI argument,
environment value, repository file or printed result. OpenTofu reads its file;
only that file's path is supplied through `TF_VAR_bootstrap_key_file`.

The fixed namespace is `cosmabot-vm/eastus2/lab01/local-initial`. Within the new
private directory the state is `state/foundation.tfstate`, the first saved plan
is `plans/first.tfplan`, and provider/backend working data is `tofu-data`.
`plan --private-dir <absolute-new-directory>` checks the source snapshot, input
hashes, executable hash and unchanged owner context, then runs actual **local
backend init** followed by the read-only Azure plan. The private manifest also
binds the exact generated key's hash; replacing the key is refused before any
Azure or initialization call. It validates the initialized
backend paths and default workspace and verifies the encrypted plan envelope.
It rejects ambient TF/ARM overrides, `AZURE_CONFIG_DIR`, changed source/inputs,
existing state/plans/workspaces and a reused working-data directory. There is no
`apply` operation or plaintext fallback in this helper. Do not use
`-backend=false` as a replacement for this actual bootstrap.

Prepare/plan command shape (substitute reviewed public paths and hashes; this
text is not an executed plan):

```text
python3 bootstrap_local.py prepare --private-dir <new-absolute-private-dir> --inputs <actual-public-inputs.json> --source-sha256 <reviewed-source-hash> --lock-sha256 <reviewed-lock-hash> --tofu <pinned-tofu-path> --provider-mirror <verified-cache-root>
python3 bootstrap_local.py plan --private-dir <same-private-dir>
```

Inputs omit generated `state_namespace` and `bootstrap_key_file`; the preparer
supplies them. No application secret is accepted. Provider-generated sensitive
attributes can still exist inside encrypted state/plans. Keep the whole folder
private, retain the key with a separately protected recovery copy, and never
print or commit decrypted state/plans or private command logs. Losing the key
makes these artifacts unrecoverable. Encryption does not protect against a
compromised operator account that can also read the key. No old state is read,
migrated or reused. Failed initial attempts remain intact for inspection; the
helper does not delete them or quietly choose another namespace.

The caller must review the saved plan against the actual account, identities,
new names, address overlap, source lock, image, allocation, costs and backend
coordinates before apply. Prevent-destroy guards protect the RG, VM, data disk,
registry, vault, storage accounts and containers. A later decommission is an
explicit reviewed change, not a convenient plan cleanup.

## Runtime and operator identities

Exactly one user-assigned runtime identity is attached to the VM. Its only role
created here is `Storage Blob Data Contributor` on the **application container**.
It has no Key Vault, ACR publication/pull, backup or deployment role. No secret
or backup identity is attached to IMDS. Core must separately authorize this
identity for its reviewed API scope; this module grants no Core authority.

The supplied off-VM release principal gets `AcrPush` on the dedicated registry
and `Key Vault Secrets Officer` on the dedicated vault. A case-insensitive guard
refuses to grant these to the runtime identity. This principal is not attached
to the host. These role grants alone do not make private data endpoints reachable:
a reviewed release/secret-installation network path is still required. Runtime
integration must deliver scoped host-only image-pull/backup credentials and
per-service secret files through that separate authority, retain exact version
references, and keep them out of scripts, logs, user data and images. The host
must deny IMDS to web/proxy/database/broker containers and permit only the
intended API/worker access before launch.

## Storage and recovery handoff

The data disk is attached at **LUN 0**, unformatted. Bootstrap must identify the
exact disk ID/LUN from the foundation output, refuse unexpected existing data,
and mount its filesystem at `/var/lib/cosmabot`. The runtime paths are
`/var/lib/cosmabot/{postgres,redis,caddy}`, immutable release files are under
`/opt/cosmabot/releases/<release-id>`, and protected configuration is under
`/etc/cosmabot/runtime/<release-id>`. Never use the OS or ephemeral container
filesystem as the database/broker persistence fallback.

The application account keeps versioning off to preserve existing exact-deletion
behavior. The backup account enables versioning and seven-day blob/container
soft deletion. This is **not** an immutable backup or an installed backup job.
The host integration must still provide the scoped writer/restore credential
separation, database base backups plus WAL, retention cleanup (the dry-run
WAL-G plan under `vm/backup`; this module does not enable it), deletion
protection, freshness alerts and a measured isolated restore before acceptance.
Single-VM availability remains distinct from the managed HA design.

AzureRM 4.81's `azurerm_storage_container` uses ARM BlobContainers create/read
when given `storage_account_id`, as this module does. Its deprecated
`storage_account_name` path uses the storage data plane and must not be used
here. The provider also explicitly sets `storage.data_plane_available = false`
to skip its default account readiness and queue/static-website data-plane calls.
Blob service properties and containers use ARM, so this private foundation's
account/container provisioning does not need initial Blob data-plane reachability.
Application uploads, backups, registry pulls and secret retrieval
still need the completed private network and scoped identity path. This finding
was checked in the pinned provider's public storage account, container and
feature-schema source. Queue properties and static websites must not be added
under this ARM-only feature setting.

The new resource group is outside the earlier budget's existing RG filters.
Review/update that scope with the actual plan; this module changes no budget.
The 0.1 GB/day log quota is an ingestion setting, not a spending cap.

## Local validation

Use the existing verified local provider mirror and the pinned executable.
Schema/format checks and `tofu test` use a separate disposable private local
backend and generated encryption key; the mock plan tests supply invented
Azure values. `tests/test_bootstrap_local.py` checks path/hash/context/input
refusals and executes a tiny **built-in `terraform_data` fixture only** using
OpenTofu 1.12.5. That local fixture proves state and plan ciphertext, correct-key
roundtrips, wrong-key failures, rejection of deliberately unencrypted fixture
state and plans, and absence of the passphrase from other generated artifacts. It does
not call Azure or install any software. The helper itself never applies.

`tests/foundation.tftest.hcl` mocks every Azure resource and all runs are plans.
They check the private resource shape, identity scopes, disk/image/region pins,
web-only ingress and explicit bootstrap handoff. No local check proves Azure
allocation, real role permissions, metric delivery, running software, recovery
or beta acceptance. A real saved plan must be reviewed before any separate
apply. Native and application acceptance remain distinct work.
