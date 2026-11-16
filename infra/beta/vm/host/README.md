# Initial Ubuntu host preparation

`bootstrap_host.py` is a one-time preparation step for the newly created East US 2
D2s_v5 host. Default `--profile cosmabot-vm-staging-v1` targets the staging RG/VM.
`--profile cosmabot-vm-prod-v1` targets production (`rg-cosmabot-prod-eus2-01` /
`vm-cosmabot-prod-eus2-01`) and refuses staging names (and the reverse). It installs
runtime dependencies and formats/mounts only the approved new 128 GiB data disk.
`format_mount` creates empty `postgres`/`redis` (UID 999) and `caddy-*` (UID 10001)
directories under `/var/lib/cosmabot`; it does not install Postgres or Redis
packages or start containers. No application image, credential, release, systemd
unit enablement, registry login or container is installed or started. Secret file
install is **T-PROD-3** (name only). It changes no Azure resource, identity, NSG,
SSH ingress or protected runner.

Run only after reviewing this source and the completed foundation apply, and
observing the actual VM, disk and Linux device. The script requires root on
Ubuntu 22.04 x86_64. A local check does not establish that the live host is ready.

## Disk provenance and explicit formatting

Create a small JSON receipt from current **ARM disk and VM reads**. Transfer it
as a root-owned regular file with mode 0600 or 0400 and retain its reviewed SHA256.
All values below describe required fields; these placeholders are not executable
inputs or evidence:

```json
{
  "version": 1,
  "source": "azure-arm-disk-and-vm-get",
  "vm_id": "<actual full new VM ARM resource ID>",
  "vm_instance_id": "<actual VM properties.vmId UUID>",
  "disk_id": "<actual full new data disk ARM resource ID>",
  "disk_unique_id": "<actual managed disk properties.uniqueId UUID>",
  "managed_by_vm_id": "<actual disk managedBy matching vm_id>",
  "create_option": "Empty",
  "size_gib": 128,
  "lun": 0,
  "apply_started_utc": "<earliest ARM timeCreated of the VM and the disk (proxy lower bound), ISO8601 with timezone>",
  "disk_created_utc": "<actual disk timeCreated, ISO8601 with timezone>",
  "apply_completed_utc": "<latest ARM timeCreated of the VM and the disk (proxy lower bound), ISO8601 with timezone>"
}
```

The disk creation time must fall within that completed apply. The 24-hour
window is the receipt field `apply_started_utc`: bootstrap refuses (and the
Sitting 2 runbook paste STOPs before any host change) when that timestamp is
older than 24 hours or in the future. If the window has passed, stop and tell
the CTO; do not invent a re-apply step in the paste path. For staging, IDs must
identify only `rg-cosmas-os-vm-staging-eus2-lab01`,
`vm-cosmabot-staging-eus2-lab01` and `data-vm-cosmabot-staging-eus2-lab01`. For
production (`--profile cosmabot-vm-prod-v1`), IDs must identify only
`rg-cosmabot-prod-eus2-01`, `vm-cosmabot-prod-eus2-01` and
`data-vm-cosmabot-prod-eus2-01` (see `creation-receipt.prod.example.json`). The
receipt is operator-supplied provenance; its hash binds the reviewed bytes. The
script does not independently authenticate a fabricated receipt against ARM.
Run from a tree that keeps `host/` beside `logging/` so
`../logging/retention.py` and `../logging/retention.json` resolve (Sitting 2
copies both under `/opt/cosmabot/vm/` before bootstrap).

### Building the receipt (`build_creation_receipt.py`)

`build_creation_receipt.py` is the one-paste workstation helper that builds that
JSON (and its sha256) from **read-only** `az vm show` and `az disk show` only.
No Azure writes. No secrets. It refuses multiple data disks, a LUN other than 0,
`createOption` other than `Empty`, a size other than 128 GiB, any missing ARM
field, or an `apply_started_utc` older than 24 hours (clear `STOP:` + exit 1).

Timestamp provenance (documented; never invented):

| Receipt field | ARM source |
| --- | --- |
| `disk_created_utc` | `az disk show` → `timeCreated` |
| `apply_started_utc` | earliest ARM `timeCreated` of the VM and the disk (ARM timeCreated **proxy**, a **lower bound**) |
| `apply_completed_utc` | latest ARM `timeCreated` of the VM and the disk (same proxy, a **lower bound**) |

One definition everywhere: these fields are an ARM `timeCreated` proxy (Azure has
no separate foundation-apply start/end on the VM or disk). Bootstrap’s 24h
window is anchored to `apply_started_utc`. If a required field cannot be read
from `az`, the tool STOPs instead of faking it.

Workstation paste (after `az login`, profile names fixed by `--profile`):

```text
python3 infra/beta/vm/host/build_creation_receipt.py --profile cosmabot-vm-prod-v1 --out-dir "$HOME/.cosmabot-sitting2"
```

On a non-root Mac it writes the local files for review and prints the exact
root install commands for the VM. `bootstrap_host.py` requires the receipt on
the VM to be a private **root-owned** regular file with mode `0600` or `0400`:

```text
sudo install -d -o root -g root -m 0700 /etc/cosmabot
sudo install -o root -g root -m 0600 "$HOME/.cosmabot-sitting2/creation-receipt.json" /etc/cosmabot/creation-receipt.json
```

The root-owned placement path is **not proven in CI** (agents are not root on
the runner). Unit tests cover non-root mode `0600` plus a mocked uid-0 chown/
chmod path under a permissive umask; John still runs the printed `sudo install`
on the VM.

Use the printed `sha256=…` value with `--creation-receipt-sha256`. Local proof:
`python3 -m unittest discover -s infra/beta/vm/host/tests -p 'test_build_creation_receipt.py' -v`
(and the CI re-export `tests/unit/test_build_creation_receipt.py`).

At execution it reads **compute metadata only**, without proxies or an identity
token. Actual IMDS VM instance/resource IDs, region, size, managed disk ID, size,
storage tier and LUN must match. IMDS can return an empty `isSharedDisk` field for this
nonshared disk; empty or absent values retain the ARM receipt's exact `managedBy`
and sole-attachment requirement. Explicit shared or unknown values are refused.
`/dev/disk/azure/scsi1/lun0` must resolve to the
exact `/dev/sd…` device observed by the operator. Local checks refuse partitions,
filesystem signatures, mounts, swap use, holders, read-only devices, existing
fstab entries and a nonempty destination. These checks run again immediately
before formatting. No full-device data scan is performed: the reviewed creation
receipt establishes that this is the newly created Empty disk.

Command shape, with actual reviewed public inputs:

```text
python3 bootstrap_host.py --profile cosmabot-vm-staging-v1 --vm-id <actual-vm-id> --disk-id <actual-disk-id> --expected-device <observed-lun0-device> --creation-receipt <root-owned-receipt.json> --creation-receipt-sha256 <reviewed-sha256> --format-new-empty-disk <same-exact-disk-id>
python3 bootstrap_host.py --profile cosmabot-vm-prod-v1 --vm-id <actual-vm-id> --disk-id <actual-disk-id> --expected-device <observed-lun0-device> --creation-receipt <root-owned-receipt.json> --creation-receipt-sha256 <reviewed-sha256> --format-new-empty-disk <same-exact-disk-id>
```

The prod unit **file** is `infra/beta/vm/runtime/cosmabot-prod.service`. Place it
only after secrets are on the host and runtime acceptance (same order as the
staging runtime README). **Do NOT enable** `cosmabot-prod.service` until
**T-PROD-5** (backup units) and **T-PROD-6** (probe) retarget are merged. Do not
rename or reuse `cosmabot-staging.service`. Container UID drop stays in
`render.py` compose (`user: 10001:10001` / `999:999`), not in the systemd unit
(which must stay root for `start.sh`).

Omitting the final flag or naming any other disk refuses formatting. Formatting
uses ext4 without a force flag. The script mounts by its newly created UUID at
`/var/lib/cosmabot`, with `nodev,nosuid,noexec`, records the prior fstab in
`/etc/fstab.cosmabot-before`, and creates these empty directories with mode 0700:

| Directory | UID/GID |
|---|---:|
| `postgres`, `redis` | 999 |
| `caddy-data`, `caddy-config` | 10001 |

## Runtime package boundary

Official Docker Jammy/amd64 packages are pinned to Docker Engine/CLI 29.8.1,
containerd 2.3.6 and Compose 5.5.1. The official Docker signing key is pinned by
SHA256, installed as a repository-scoped `Signed-By` key, and APT verifies the
signed repository. The source pins full Debian package version strings and
verifies installed versions. Missing/changed packages or a changed signing key
require a reviewed update; there is no unpinned fallback. Buildx/rootless extras
are not needed for this image-only runtime. Ubuntu's official repositories supply
Python 3, OpenSSL, util-linux, iptables/nftables, e2fsprogs and CA roots.
Those dependency patch versions follow the supported Ubuntu security repository.

Existing Docker sources, packages, configuration or container data refuse this
fresh bootstrap. A temporary service policy prevents APT from starting services;
Docker, its socket and containerd are masked before installation and remain
masked afterward. Docker configuration explicitly selects its **iptables**
firewall backend, preserving the runtime's DOCKER-USER guard contract, and bounds
local container logs. The size and file count come from
`infra/beta/vm/logging/retention.json` (default `10m` and 3 files, the same limits
as before). Journald limits in that file are not installed by this bootstrap.
See `infra/beta/vm/logging/README.md`. `dockerd --validate` checks configuration without starting
the daemon. Compose version is checked without starting containers.

The host receipt is `/etc/cosmabot/host-bootstrap.json`; private command output
is `/var/log/cosmabot-host-bootstrap.log`. A failure leaves partial work and
service masks intact for inspection. If package installation fails, the temporary
`/usr/sbin/policy-rc.d` may also remain. Do not rerun, remove that policy, force
format, or overwrite the mount automatically; inspect the precise stopping point.

After this step, root still must review the actual mount/receipt, unmask and start
the Docker daemon, verify the real iptables/DOCKER-USER behavior, and install the
reviewed runtime guard before any application container starts. The runtime's
reserved bridge ranges must be checked against host routes. Protected secrets,
image pulls, database preparation, firewall/IMDS proof, certificates and backup/
restore acceptance remain separate runtime work. The script does not install a
reboot/start unit or change the application's admission state.

Local validation is intentionally focused: Python syntax plus the refusal tests
under `tests/`, including exact provenance, metadata/device matching, changed
device rejection before mkfs, and file modes under a restrictive umask. The tests
never touch real block devices, run package operations, query IMDS or call Azure.

## Prod secrets transport (`secrets_transport.py`) — T-PROD-3-SECRETS

Separate from `bootstrap_host.py` (prod host bootstrap retarget is a different
ticket). This module stages Key Vault secret **names** on a workstation and
installs mode-0400 host files under `/etc/cosmabot/runtime/<release_id>/<role>/`.

### Access model

- **Reads the vault:** the existing off-VM release operator principal (already
  `Key Vault Secrets Officer` on `kv-cbot-prd-*`), from John's workstation
  inside the temporary `/32` public-access window. Not the VM runtime UAMI.
- **Does not widen runtime access:** no new role assignment, access policy, or
  identity for the runtime managed identity.
- **Do not** `az login` as Secrets Officer on the prod VM (would leave a
  privileged token on the host). No Bastion.
- **VM access (John, 14 Nov 2026 9:45am ET):** temporary NSG inbound Allow
  SSH TCP/22 from John's own `/32` only, fixed rule name
  `TEMP-JOHN-SSH-SECRETS-INSTALL` (priority `200`, before
  `deny-all-other-ingress` at `4000`). Pasteable fences under
  `infra/beta/vm/host/fences/`. **Close-and-verify is MANDATORY** after every
  outcome (including STOP). No permanent Terraform/NSG change. An out-of-band
  rule drifts the next plan — close before any plan or apply.
- After any vault window: restore/verify per runbook **§4.3**. After any SSH
  window: close/verify per runbook **§4.5**.
- **Ownership:** secret files are owned by the **service UID** for that role
  directory (`10001` for `api` / `worker` / `prepare`, `999` for `postgres` /
  `redis`), mode `0400`, matching `runtime/entrypoint.py` `read_private`.
- **Run Command:** refused. Values never appear in scripts or arguments
  (CTO 11 Nov 2026).

### Hard rules

- Output prints secret **names**, pass/fail, mode, owner uid, and size>0 only.
- Refuse staging names (vault, RG, host, profile). Profile must be
  `cosmabot-vm-prod-v1`.
- `WORKSPACE-LLM-API-KEY` requires tag / sidecar `source-account` matching prod
  `oai-cbot-prd-*` on **every** stage and install path. CosmasCode /
  `services.ai.azure.com` markers are refused.
- Atomic write: umask `077`, then mode `0400`. Empty or whitespace-only value
  → STOP. Private stage dirs are mode `700` and cleaned up explicitly.

### Operator shapes (names only in examples)

Plan (names / mapping only; omit `--secret-name` for the full catalog):

```text
python3 secrets_transport.py \
  --profile cosmabot-vm-prod-v1 \
  --resource-group rg-cosmabot-prod-eus2-01 \
  --vault-name "$PROD_KV_NAME" \
  --plan-only
```

Workstation stage-only (John `/32` vault window; never on the prod VM). Omit
`--secret-name` so the full catalog is staged (required for
`--check-staging-complete` / the §4.5 session gate). Use the same
`$LOCAL_STAGING` folder the runbook creates with
`mktemp -d /tmp/cosmabot-staging.XXXXXX`:

```text
LOCAL_STAGING=$(mktemp -d /tmp/cosmabot-staging.XXXXXX)
python3 secrets_transport.py \
  --profile cosmabot-vm-prod-v1 \
  --resource-group rg-cosmabot-prod-eus2-01 \
  --vault-name "$PROD_KV_NAME" \
  --stage-from-vault \
  --staging-dir "$LOCAL_STAGING"
```

Then restore vault public access per **§4.3**. LLM installs also write a
non-secret sidecar `WORKSPACE_LLM_API_KEY.source-account`.

**One order** (runbook Sitting 2 row 5 / after format-disk yes + continue-prep
yes / checklist): workstation receipt-tool paste
(`build_creation_receipt.py --profile cosmabot-vm-prod-v1 --out-dir
"$HOME/.cosmabot-sitting2"`) → open temporary SSH `/32` with the existing open
fence → root shell → copy `host/` + sibling `logging/` to `/opt/cosmabot/vm/`
→ place the receipt root-owned on the VM with the printed `sudo install`
commands → `#389` bootstrap so `/etc/cosmabot` exists (`apply_started_utc`
under 24 hours, or STOP and tell the CTO) → close-and-verify that SSH rule →
second vault window → `LOCAL_STAGING=$(mktemp -d /tmp/cosmabot-staging.XXXXXX)`
→ `--stage-from-vault` without `--secret-name` (path shape + all expected names
present and non-empty, or STOP before SSH) → `TEMP-JOHN-SSH-SECRETS-INSTALL` →
ssh-stdin install → close-and-verify. John's hands-on: `/32`, vault window,
SSH key.

SSH install window (John `/32` only; see runbook §4.5 and `fences/`):

1. Source define-only fences, then invoke `cosmabot_ssh_secrets_session`
   (traps EXIT/INT/TERM so close-and-verify always runs). Session checks
   staging path shape and `--check-staging-complete` before OPEN.
2. OPEN creates `TEMP-JOHN-SSH-SECRETS-INSTALL` (Tcp, John's `/32`, priority 200).
3. INSTALL ships `secrets_transport.py` (sha256 pin
   `secrets_transport.sha256`), pins the VM ed25519 host key via Run Command
   (public key only), pre-checks `/etc/cosmabot`, then
   `install -d -o root -g root -m 0700` for the release root, pipes each secret
   value over `ssh` stdin into `--install-from-stdin` as root. No `scp` of
   values; no VM `/tmp` or `/root` secret staging. Local staging remove is
   guarded (`/tmp` or `/private/tmp` `cosmabot-staging.XXXXXX` with 6 random
   chars, mode 0700, owned by us — never `/var/folders`).
4. CLOSE AND VERIFY deletes the rule, requires deny-all at 4000, runs
   `--check-ssh-closed`, and probes SSH (connection refused or
   connect/operation timeout PASS; banner-exchange / auth / password prompt
   FAIL).
5. If the terminal closed partway: source only
   `fence-ssh-nsg-recovery.sh` (self-contained guarded rm) then
   `cosmabot_ssh_nsg_recovery_if_stranded` — always deletes then verifies NSG.
   Wrong-shape `LOCAL_STAGING` → STOP before recovery runs. Unset
   `LOCAL_STAGING` → NOTE that any leftover staging folder must be checked and
   removed by hand, then still run recovery so the SSH `/32` rule is deleted.
   Valid shape → guarded staging rm as now; leftover staging → STOP not PASS.

Sourcing a fence file has zero side effects (never opens or closes the NSG).

Workstation gate before stdin install:

```text
python3 secrets_transport.py \
  --profile cosmabot-vm-prod-v1 \
  --resource-group rg-cosmabot-prod-eus2-01 \
  --vault-name kv-cbot-prd-<suffix> \
  --check-ssh-install-ready \
  --ack-close-and-verify \
  --expected-source-cidr <john-ip>/32 \
  --nsg-rules-json /path/to/nsg-rules-names-ports-only.json
```

CI proof: `tests/unit/test_secrets_transport.py` and
`tests/unit/test_secrets_transport_fences.py` (canary value never appears in
stdout/stderr/argv/exception text). Local refusals also under
`host/tests/test_secrets_transport.py`.
