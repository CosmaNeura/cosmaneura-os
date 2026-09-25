# Temporary operator SSH window

`operator_window.py` installs one ephemeral key on a new **unprivileged** account
`cmop<12-hex-window-id>`. It changes no Azure resources, NSGs, host keys,
`cosmabotops`, sudoers, Docker groups, identities or runtime bridges. The private
key stays on the Mac; root installation commands remain on Azure Run Command.

Only `receive NAME BYTES SHA256` is accepted as a remote command, reading bytes
from stdin into a fixed spool. Local TCP forwarding allows exactly the supplied
new vault and ACR names on port 443. Shells, SFTP/SCP, arbitrary commands, PTY,
agent/X11, Unix-socket forwarding, remote forwarding and tunnels are disabled.
The server cannot enforce a client's local bind address: use `127.0.0.1` below.

## Reviewed root installation

Install the reviewed script as
`/usr/local/libexec/cosmabot-operator-window.py`, root-owned mode 0755, with
root-controlled parent directories. The target is the foundation's exact hostname
`vm-cosmabot-staging-eus2-lab01`. Ubuntu 22.04's Python 3.10, OpenSSH and systemd are required.
Unsupported or overridden live SSH restrictions cause refusal before activation.
The executable SSH entry points and root commands use Python isolated mode
(`-I`), ignoring Python environment/module search overrides. Effective `AcceptEnv`
must be empty or contain only `LANG` and `LC_*`; `PermitUserEnvironment` must be
`no`. This also blocks loader/shell overrides that run before Python. Unsupported
host settings cause refusal; the helper does not alter their global configuration.

Create a root-owned regular JSON manifest, mode 0400 or 0600, with exactly:

| Field | Required public value |
|---|---|
| `version` | Integer `1` |
| `window` | Fresh 12 lowercase hex characters |
| `vm_name` | `vm-cosmabot-staging-eus2-lab01` |
| `source_ipv4` | This Mac's verified current public IPv4, without `/32` |
| `vault_host` | Actual new vault's complete `*.vault.azure.net` hostname |
| `acr_host` | Actual new registry's complete `*.azurecr.io` hostname |
| `expires_at` | UTC `YYYY-MM-DDTHH:MM:SSZ`, 2 minutes to 3 hours ahead |
| `public_key` | Fresh `ssh-ed25519` public key, never a private key |

Hostname suffix validation does not prove ownership. Root binds these exact names,
source IP and VM to approved ARM readback and reviews the manifest SHA256.
Through authenticated Run Command on that VM:

```text
/usr/bin/python3 -I /usr/local/libexec/cosmabot-operator-window.py install /root/operator-window.json --sha256 <reviewed-manifest-sha256>
```

Existing windows/accounts refuse rather than renew or overwrite. The helper
installs a per-user sshd drop-in, key gate and expiry units. Authentication stays
disabled until effective configuration, boot cleanup enablement, timer startup
and SSH reload succeed. Failure attempts closure and leaves public state for
root inspection. Do not open the NSG after failed setup.

Root separately opens only the approved source `/32` to this VM's TCP22 and pins
its public host key, acquired through authenticated Run Command, in a dedicated
Mac known-hosts file. Do not substitute keyscan-only trust or broaden ingress.

## Transfer and forwarding

Keep the private key and temporary files in a new Mac owner-only directory.
SSH options must include `BatchMode=yes`, `IdentitiesOnly=yes`,
`StrictHostKeyChecking=yes`, `UserKnownHostsFile=<pinned-file>`,
`IdentityFile=<new-private-key>`, `ForwardAgent=no`, `ForwardX11=no`,
`RequestTTY=no` and `ExitOnForwardFailure=yes`. For forwarding use `-N -T` and:

```text
-L 127.0.0.1:18443:<exact-vault-host>:443
-L 127.0.0.1:19443:<exact-acr-host>:443
cmop<window-id>@<exact-VM-public-IP>
```

On a separate connection with the same strict options, upload a pre-hashed file:
`ssh ... 'receive image.tar <bytes> <sha256>' < image.tar`.
Never put token/secret bytes in the command. Only a complete, correct-length,
matching-hash file is published, with no overwrites. Success emits only
`{"status":"received"}`.

The spool is `/var/lib/cosmabot-operator/<window-id>/incoming/`, mode 0700 with
0600 files. Uploads are serialized, capped at **8 GiB total**, and must leave
**16 GiB free**. This uses the OS disk to preserve the runtime data mount's
root-only 0700 traversal. No mount or runtime directory permission changes are
made. Larger archives require a reviewed transport adjustment, not weaker access.

Root rechecks regular-file/no-symlink/single-link status, owner, size and hash
before consuming an upload through Run Command. Root handles Docker load/push
and protected secret installation through the separately reviewed procedures.
Keep the Azure owner token/cache on the Mac. `curl --connect-to` through the
forwards preserves HTTPS host/SNI verification; never use `--insecure`.

## Expiry and final cleanup

Every authentication checks active state, boot ID, wall-clock and monotonic
deadlines. The key also carries OpenSSH source `/32` and expiry restrictions.
A reboot immediately invalidates it even before the enabled boot cleanup runs.
The timer uses UTC and boot-relative deadlines to handle wall-clock changes.

Closure denies new authentication and removes only the exact owned key, then
locks/expires the dedicated account and kills its UID's processes plus its exact
privileged SSH monitor. PID-bound signals prevent PID-reuse mistakes. Other
operator accounts are untouched. Session termination is still attempted when key
removal or account locking fails. Any cleanup failure returns nonzero.

Through Run Command, close early or verify final closure:

```text
/usr/bin/python3 -I /usr/local/libexec/cosmabot-operator-window.py close <window-id>
```

Expiry retains uploads so root can recover an interrupted installation. After
consumption, run `purge <window-id>` through the same root route. It closes access
again and deletes only regular single-link files in that exact spool; unexpected
files/symlinks refuse deletion. It retains the locked account, small public
tombstone and closure units to prevent UID reuse and preserve boot closure.

Root also deletes its named temporary NSG rule and verifies the original
80/443-plus-deny resting policy through ARM. Stop the Mac forward and remove its
temporary registry config, token responses and transfer archives. NSG deletion
alone does not terminate established connections. If host cleanup fails, close
the NSG anyway and repair the exact window via Run Command; do not widen access.

Local tests use fixtures and the installed OpenSSH configuration parser. They
never create host users, start an SSH daemon or call Azure. The first live window
must verify actual transfer/forward termination at expiry and reboot gating;
local process models do not establish those host results.
