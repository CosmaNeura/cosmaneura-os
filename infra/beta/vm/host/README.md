# Initial Ubuntu host preparation

`bootstrap_host.py` is a one-time preparation step for the newly created East US 2
D2s_v5 staging host. It installs runtime dependencies and formats/mounts only the
approved new 128 GiB data disk. No application image, credential, release, service
unit, registry login or container is installed or started. It changes no Azure
resource, identity, NSG, SSH ingress or protected runner.

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
  "apply_started_utc": "<recorded start of this reviewed apply, ISO8601 with timezone>",
  "disk_created_utc": "<actual disk timeCreated, ISO8601 with timezone>",
  "apply_completed_utc": "<recorded successful end of this apply, ISO8601 with timezone>"
}
```

The disk creation time must fall within that completed apply, started less than
24 hours ago. IDs must identify only `rg-cosmas-os-vm-staging-eus2-lab01`,
`vm-cosmabot-staging-eus2-lab01` and `data-vm-cosmabot-staging-eus2-lab01`.
The receipt is operator-supplied provenance; its hash binds the reviewed bytes.
The script does not independently authenticate a fabricated receipt against ARM.

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
python3 bootstrap_host.py --vm-id <actual-vm-id> --disk-id <actual-disk-id> --expected-device <observed-lun0-device> --creation-receipt <root-owned-receipt.json> --creation-receipt-sha256 <reviewed-sha256> --format-new-empty-disk <same-exact-disk-id>
```

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
