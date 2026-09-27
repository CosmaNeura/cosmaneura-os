"""Emit only application/backup health; never forward command output or app logs."""

import datetime
import http.client
import json
import re
import socket
import ssl
import subprocess
import time

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


def application_healthy(units, containers, now):
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
        if name not in SERVICES or name in observed:
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
    return observed == SERVICES


def containers():
    ids = command(
        [
            "/usr/bin/docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=cosmabot-staging",
        ]
    ).splitlines()
    if not 6 <= len(ids) <= 7 or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in ids):
        raise ValueError("unexpected container inventory")
    template = '{"service":{{json (index .Config.Labels "com.docker.compose.service")}},"state":{{json .State}}}'
    raw = command(["/usr/bin/docker", "container", "inspect", "--format", template, *ids])
    return [json.loads(line) for line in raw.splitlines()]


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
        observed = containers()
        application = (
            application_healthy(units, observed, datetime.datetime.now(datetime.timezone.utc))
            and web_healthy()
        )
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
