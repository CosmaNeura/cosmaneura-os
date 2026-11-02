# Log retention

The app container (`web`), API, worker, and proxy logs keep the Docker limits already used on
the VM. Journald limits, Caddy roll, and the standalone logrotate fragment are
configured here and stay off the host until an operator installs them. The plan
command only logs what it would remove. It does not vacuum the journal, delete
container logs, or contact a server.

Defaults in `retention.json`:

| Setting | Default | Where it applies |
| --- | --- | --- |
| `docker.driver` | `local` | Compose services and `/etc/docker/daemon.json` |
| `docker.max_size` | `10m` | Each container log file |
| `docker.max_file` | `3` | Rotated files kept per container |
| `services` | `web`, `api`, `worker`, `proxy` | The streams these limits cover |
| `journald.system_max_use` | `200M` | Host journal, after the drop-in is installed |
| `journald.max_retention_sec` | `7day` | Host journal age |
| `journald.max_file_sec` | `1day` | Individual journal file age |
| `caddy.enabled` | `false` | No roll block in the Caddyfile |
| `caddy.roll_size` | `10MiB` | Used only after Caddy roll is enabled |
| `caddy.roll_keep` | `5` | Rolled Caddy files to keep |
| `caddy.roll_keep_for` | `168h` | Maximum age of a rolled Caddy file |
| `standalone.rotate` | `7` | Standalone logrotate count |
| `standalone.max_size` | `10M` | Standalone logrotate size |
| `dry_run` | `true` | Do not delete rolled files |
| `enabled` | `false` | Apply refuses while this is false |

Docker itself rotates container logs once the daemon and the rendered Compose
file use these options. A fresh host bootstrap reads the same file. An existing
host keeps the daemon.json already written there until an operator changes it.
`systemd-journald` does not apply `journald` until the operator installs the
drop-in from a dry-run plan and restarts `systemd-journald`.

Caddy access logs stay on the container's stdout, which Docker rotates, until
`caddy.enabled` is true. The next runtime render then writes a global `log` block
to `/data/logs/access.log` on the existing Caddy data volume, with `roll_size`,
`roll_keep`, and `roll_keep_for`. Re-rendering does not restart a running release.

The standalone package still renders nginx with `access_log off` and does not
install logrotate. `standalone_logrotate` in the plan is a fragment for
`/var/log/cosmabot-standalone/{web,api,worker,proxy}.log`. `web` is the app container. Copy it to
`/etc/logrotate.d` only after review.

Rolled Caddy names follow lumberjack: `access-YYYY-MM-DDTHH-MM-SS.mmm.log`.
The active `access.log` is never a delete candidate. Files past `roll_keep` or
older than `roll_keep_for` are the delete set. Any other name is ignored.
The plan prints that set and does not unlink anything.

`cosmabot-log-retention.timer` is not installed by host bootstrap. It runs at
06:15 UTC, with no network, and only executes `plan`.

### Turn log cleanup on

1. Review `retention.json`. Run:

```text
python3 infra/beta/vm/logging/retention.py plan --config infra/beta/vm/logging/retention.json
```

2. To bound the host journal, install the `journald_dropin` from that JSON at
   `/etc/systemd/journald.conf.d/cosmabot-retention.conf` and restart
   `systemd-journald`.
3. To change Docker rotation, edit `docker.max_size` or `docker.max_file`,
   re-render the runtime, and update `/etc/docker/daemon.json` on the host to the
   same `log-opts`. Restarting Docker is a separate host change; this repository
   does not do it.
4. To roll Caddy logs to disk, set `caddy.enabled` to true and render a new
   release. The previous release's Caddyfile is unchanged.
5. To schedule the dry-run record, copy `retention.py` to
   `/opt/cosmabot/logging/retention.py` and the unit files into
   `/etc/systemd/system/`, then enable `cosmabot-log-retention.timer`.
6. To delete rolled files, set `enabled` to true and `dry_run` to false, pass a
   JSON file list and an explicit directory, and set the apply environment.
   The directory must not be a database, broker, or backup path. Symlinks are
   refused before any unlink:

```text
COSMABOT_LOG_RETENTION_APPLY=1 python3 -I infra/beta/vm/logging/retention.py apply \
  --config infra/beta/vm/logging/retention.json \
  --files /protected/synthetic-log-list.json \
  --directory /protected/caddy-log-directory \
  --confirm-apply
```

Leave the timer on `plan`. Do not point apply at a directory you have not listed.
