"""Emit only application/backup health; never forward command output or app logs."""

import datetime
import hashlib
import http.client
import json
import re
import socket
import ssl
import subprocess
import time
from pathlib import Path

SERVICES = frozenset({"api", "worker", "web", "proxy", "postgres", "redis"})
TIMERS = ("cosmabot-backup.timer", "cosmabot-backup-switch.timer", "cosmabot-backup-status.timer")
UNITS = (
    "cosmabot-staging.service",
    "cosmabot-backup-receive.service",
    "cosmabot-backup-job@status.service",
    *TIMERS,
)
PROPERTIES = (
    "Id,ActiveState,SubState,UnitFileState,Result,ExecMainStatus,ExecMainExitTimestampMonotonic"
)
PREFIX = "cosmabot-health-v1 "
POINTER = Path("/etc/cosmabot/active-release")
RELEASE_ROOT = Path("/opt/cosmabot/releases")
RELEASE_ID = re.compile(r"[a-z][a-z0-9-]{2,47}")


def command(arguments):
    result = subprocess.run(
        arguments,
        capture_output=True,
        timeout=10,
        check=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "SYSTEMD_PAGER": ""},
    )
    if len(result.stdout) > 262144:
        raise ValueError("oversized health observation")
    return result.stdout.decode("utf-8", errors="strict")


def unit_observations(raw):
    units = {}
    for block in raw.strip().split("\n\n"):
        values = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        name = values.get("Id")
        if name not in UNITS or name in units:
            raise ValueError("unexpected unit observation")
        units[name] = values
    if set(units) != set(UNITS):
        raise ValueError("incomplete unit observation")
    return units


def backup_healthy(units, monotonic):
    receiver = units["cosmabot-backup-receive.service"]
    if (receiver.get("ActiveState"), receiver.get("SubState"), receiver.get("UnitFileState")) != (
        "active",
        "running",
        "enabled",
    ):
        return False
    if any(
        (units[name].get("ActiveState"), units[name].get("UnitFileState")) != ("active", "enabled")
        for name in TIMERS
    ):
        return False
    status = units["cosmabot-backup-job@status.service"]
    # Each successful status job verifies remote base age, completed WAL and slot retention.
    # During the next short check, the preceding completion remains valid for five minutes.
    if status.get("Result") != "success" or status.get("ExecMainStatus") != "0":
        return False
    completed = int(status.get("ExecMainExitTimestampMonotonic", "0")) / 1_000_000
    return completed > 0 and 0 <= monotonic - completed <= 300


def docker_time(value):
    # Docker emits nanoseconds; Ubuntu 22.04's Python 3.10 accepts microseconds.
    normalized = re.sub(r"(\.\d{6})\d+(?=Z$|[+-]\d{2}:\d{2}$)", r"\1", value)
    return datetime.datetime.fromisoformat(normalized.replace("Z", "+00:00"))


def resolve_active_release():
    """The live pointer names one canonical release directory, or the probe fails."""
    try:
        raw = POINTER.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError("active release pointer is missing") from None
    except (OSError, UnicodeError):
        raise ValueError("active release pointer is dangling") from None
    prefix = f"RELEASE_DIR={RELEASE_ROOT}/"
    if len(raw) > 256 or raw.count("\n") != 1 or not raw.endswith("\n") or not raw.startswith(prefix):
        raise ValueError("active release pointer is dangling")
    release_id = raw[len(prefix) : -1]
    if RELEASE_ID.fullmatch(release_id) is None:
        raise ValueError("active release pointer is dangling")
    release = RELEASE_ROOT / release_id
    if release.is_symlink() or not release.is_dir():
        raise ValueError("active release pointer is dangling")
    return release


def read_bounded(path, label):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"active release {label} is missing")
    try:
        raw = path.read_bytes()
    except OSError:
        raise ValueError(f"active release {label} is missing") from None
    if len(raw) > 262144:
        raise ValueError("oversized health observation")
    return raw


def read_release(release):
    """Manifest hashes bind the compose plan this release actually published."""
    manifest_raw = read_bounded(release / "RENDER.json", "manifest")
    plan_raw = read_bounded(release / "compose.json", "plan")
    try:
        manifest = json.loads(manifest_raw)
        plan = json.loads(plan_raw)
    except json.JSONDecodeError:
        raise ValueError("active release manifest or plan is unusable") from None
    files = manifest.get("files") if isinstance(manifest, dict) else None
    expected = files.get("compose.json") if isinstance(files, dict) else None
    if expected != hashlib.sha256(plan_raw).hexdigest():
        raise ValueError("active release plan does not match its manifest")
    if not isinstance(plan, dict) or plan.get("name") != "cosmabot-staging":
        raise ValueError("active release plan is unusable")
    if not isinstance(plan.get("services"), dict) or not plan["services"]:
        raise ValueError("active release plan is unusable")
    return manifest, plan


def running_services(plan):
    running = []
    optional = False
    for name, service in plan["services"].items():
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{1,40}", name) is None
            or not isinstance(service, dict)
        ):
            raise ValueError("active release plan is unusable")
        if service.get("profiles") == ["prepare"]:
            optional = True
            continue
        running.append(name)
    if not running:
        raise ValueError("active release plan is unusable")
    return frozenset(running), optional


def published_ports(plan):
    ports = []
    for service in plan["services"].values():
        for item in service.get("ports", []):
            if not isinstance(item, str) or re.fullmatch(r"[0-9]{1,5}:[0-9]{1,5}", item) is None:
                raise ValueError("active release plan is unusable")
            host = int(item.split(":", 1)[0])
            if not 1 <= host <= 65535:
                raise ValueError("active release plan is unusable")
            ports.append(host)
    if not ports:
        raise ValueError("active release plan is unusable")
    return tuple(ports)


def application_healthy(units, containers, now, *, expected=SERVICES):
    staging = units["cosmabot-staging.service"]
    if (staging.get("ActiveState"), staging.get("Result")) != ("active", "success"):
        return False
    observed = set()
    for container in containers:
        name, state = container["service"], container["state"]
        if name == "database_prepare":
            if state.get("Running") or state.get("ExitCode") != 0:
                return False
            continue
        if name not in expected or name in observed:
            return False
        observed.add(name)
        if (
            state.get("Status") != "running"
            or not state.get("Running")
            or state.get("Paused")
            or state.get("Restarting")
            or state.get("Dead")
        ):
            return False
        if name != "proxy":
            health = state.get("Health", {})
            if health.get("Status") != "healthy" or not health.get("Log"):
                return False
            last = health["Log"][-1]
            ended = docker_time(last["End"])
            if last.get("ExitCode") != 0 or not -5 <= (now - ended).total_seconds() <= 90:
                return False
    return observed == expected


def containers(release, plan):
    # Stopped leftovers from older releases share the project name. The compose
    # file path is what makes this release's containers distinct.
    compose_file = str(release / "compose.json")
    running, optional = running_services(plan)
    ids = command(
        [
            "/usr/bin/docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=" + plan["name"],
            "--filter",
            "label=com.docker.compose.project.config_files=" + compose_file,
        ]
    ).splitlines()
    low, high = len(running), len(running) + (1 if optional else 0)
    if not low <= len(ids) <= high or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in ids):
        raise ValueError("unexpected container inventory")
    template = (
        '{"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
        '"config":{{json (index .Config.Labels "com.docker.compose.project.config_files")}},'
        '"state":{{json .State}}}'
    )
    raw = command(["/usr/bin/docker", "container", "inspect", "--format", template, *ids])
    observed = [json.loads(line) for line in raw.splitlines()]
    if any(row.get("config") != compose_file for row in observed):
        raise ValueError("container is outside the active release")
    return observed


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=4):
            return True
    except OSError:
        return False


def ports_healthy(plan):
    for port in published_ports(plan):
        if port == 443:
            if not web_healthy():
                return False
        elif not port_open(port):
            return False
    return True


def web_healthy():
    # Exercise the host's actual TLS listener and certificate without public-IP hairpin routing.
    context = ssl.create_default_context()
    with socket.create_connection(("127.0.0.1", 443), timeout=4) as connection:
        with context.wrap_socket(connection, server_hostname="staging.cosmas.ai") as secured:
            secured.sendall(
                b"GET / HTTP/1.1\r\nHost: staging.cosmas.ai\r\nConnection: close\r\n\r\n"
            )
            response = http.client.HTTPResponse(secured)
            response.begin()
            return response.status == 200 and response.getheader("Content-Type", "").startswith(
                "text/html"
            )


def observe():
    application = backup = False
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        units = unit_observations(
            command(["/usr/bin/systemctl", "show", *UNITS, "--property=" + PROPERTIES])
        )
    except Exception:
        return application, backup, now
    try:
        backup = backup_healthy(units, time.monotonic())
    except Exception:
        pass
    try:
        release = resolve_active_release()
        _manifest, plan = read_release(release)
        observed = containers(release, plan)
        application = application_healthy(
            units,
            observed,
            datetime.datetime.now(datetime.timezone.utc),
            expected=running_services(plan)[0],
        ) and ports_healthy(plan)
    except Exception:
        pass
    return application, backup, datetime.datetime.now(datetime.timezone.utc)


def encode(application, backup, now):
    # Fixed enums and a generated timestamp are the entire outbound payload.
    return PREFIX + json.dumps(
        {
            "application": "ok" if application else "failed",
            "backup": "ok" if backup else "failed",
            "observed_at": now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def main():
    # systemd supplies the journal stream even inside the private device namespace.
    print(encode(*observe()))


if __name__ == "__main__":
    main()
