# Private allocation host preparation

These operators prepare the already-written `hosting_worker`; they do not
provision a host, install tools or dependencies, read credentials, log in,
enable a service, start the worker, publish images, apply OpenTofu, or change
DNS. The public enrollment API remains a queue producer.

The simplest host is a dedicated non-public Linux VM in the enrollment
foundation's private network, using a dedicated user-assigned managed identity
and a persistent private disk. Reusing a public API container is insufficient:
the runtime Dockerfile removes unused tools and does not contain the Git
checkout, Azure CLI, OpenTofu, or persistent allocation journal. A Container
Apps alternative needs its own separately reviewed tool image and durable
mount; the official Azure CLI image is not evidence of Python 3.13 app support.

## Exact source transfer

Use the reviewed complete commit SHA, not an assumed current branch. `prepare`
reads Git objects from that commit only. It records any working changes but
excludes them. It enumerates the real commit, root tree, and all current tree
objects, then calls `git pack-objects` without parent traversal. It does not
copy `.git/config`, remote credentials, parent objects, or untracked files.

```sh
python infra/enrollment/allocator-host/prepare.py --source /absolute/cosmabot-checkout --source-commit REVIEWED_40_HEX_COMMIT --output /absolute/private-transfer/source-snapshot
```

Transfer the resulting `source.pack`, `source-snapshot.json`, and `bootstrap/`
operator folder through the approved private file-transfer route. The manifest
binds those two operator hashes, so no preexisting checkout is needed. On the
destination:

```sh
python /absolute/private-transfer/source-snapshot/bootstrap/bootstrap.py materialize --snapshot /absolute/private-transfer/source-snapshot/source-snapshot.json --pack /absolute/private-transfer/source-snapshot/source.pack --output /absolute/private-worker/source
```

The output must be fresh, absolute, outside the input directory, and free of
symlink parents. Materialization initializes a new credential-free Git
repository, indexes only the supplied objects, writes the real commit as the
shallow boundary, and checks out its exact tree. It verifies actual HEAD,
complete object inventory, tracked files/modes, clean status, and Git archive
equality. The materialized checkout is the worker's `source_repository`.
Do not add untracked files inside `infra/enrollment/allocated-workspace`.

## Preinstalled host toolchain

Provide existing installed executables; this preparation performs no downloads.
The app Python must be **Linux Python 3.13.15**, with this commit's locked app
dependencies already installed. The worker import is checked using the
materialized `src` directory. Its dependency installation must use `uv.lock`
with `uv sync --frozen`; reviewed uv is 0.12.5. A separately prepared offline
Linux cache or wheel set is required for a host without package egress. Mac
virtualenvs and Homebrew executable hashes cannot qualify Linux executables.

Azure CLI **2.89.1**, OpenTofu **1.12.5**, and Git must be installed. The public
tool manifest has exactly four entries: `python`, `git`, `az`, and `tofu`.
Each entry contains its actual absolute `path` and reviewed executable
`sha256`. It contains no login state, credentials, fabricated paths, or keys.
Generate its hashes from the installed Linux toolchain, then review that file.

An existing persistent state directory must be owned by the worker account,
mode **0700**, outside the source checkout, without symlink parents. It must
survive restarts and have a separately approved backup/custody policy.

```sh
python infra/enrollment/allocator-host/bootstrap.py validate --source /absolute/private-worker/source --snapshot /absolute/private-transfer/source-snapshot/source-snapshot.json --tools /absolute/private-transfer/reviewed-linux-tools.json --state-root /absolute/private-worker/state --evidence /absolute/private-worker/fresh-tool-evidence
```

Validation runs local version/import checks only. Azure CLI receives a fresh
private configuration directory for `az version`; no existing login is read.
The receipt explicitly leaves allocation, managed identity, and private
network qualification false. No worker/service command is generated or run.

## Inputs that must be real before separate activation

The local source/tool check is preparation, not an operational gate pass.
The host still needs:

- The existing full dedicated `enrollment-foundation.v1` coordinates. A
  registry-only export is insufficient. `HostingConfiguration` requires the
  exact VNet, Container Apps environment, PostgreSQL and endpoint subnets,
  private Vault/Blob/Redis DNS zone IDs, subscription/tenant, and independent
  state backend. The foundation export now includes the shared Vault, Blob and
  Redis private DNS zone IDs inside the dedicated enrollment resource group.
- A dedicated attached user-assigned worker identity, its actual client/object
  IDs, and scoped deployment/role-assignment, ACR build/push/lock, private state,
  vault-secret seeding, and hosting-receipt permissions. Public enrollment's
  existing pull/selected-secret identity has no workspace administration role.
- A nondelegated host subnet/private path to the registry PostgreSQL, state
  Blob endpoint, Box services, and required public provider APIs. Existing
  Container Apps/PostgreSQL delegated subnets are not a VM host placement.
  Default outbound access is disabled in the foundation; reviewed egress and
  state data-plane access must be provided explicitly.
- Actual source-bound, digest-pinned API and allocated-job image receipts in
  the dedicated ACR, with the unchanged security gates passed.
- Owner-controlled `0600` hosting configuration and already-protected
  enrollment runtime/DNS references. Optional Google uses the existing exact
  callback and protected client-secret reference. These helpers never open
  credential-bearing files or invent enabled settings.
- Actual managed-identity login, private PostgreSQL schema/role access, subnet
  capacity, provider response contracts, persistent-state recovery, and a held
  synthetic allocation acceptance run, each approved separately.

No Core, Scribe, Cosmaneura, existing a/b deployment, model name, or current
runtime deployment name is imported or changed by these operators.
