#!/usr/bin/python3
"""Plan retention for app, API, worker, and proxy logs. Dry-run unless an operator applies it.

Docker and journald enforce their own rotation after the rendered settings are
installed. This command logs that plan. It deletes Caddy rolled files only when
apply is explicitly confirmed against one directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name("retention.json")
SERVICES = ["web", "api", "worker", "proxy"]
DOCKER_SIZE = re.compile(r"[1-9][0-9]{0,4}[kmg]")
JOURNAL_SIZE = re.compile(r"[1-9][0-9]{0,5}[KMGT]")
JOURNAL_AGE = re.compile(r"[1-9][0-9]{0,4}(?:s|min|h|day|week|month|year)")
ROLL_SIZE = re.compile(r"[1-9][0-9]{0,4}(?:KiB|MiB|GiB)")
ROLL_FOR = re.compile(r"([1-9][0-9]{0,5})([hms])")
CADDY_PATH = re.compile(r"/data/logs/[A-Za-z0-9._-]+")
LOGROTATE_SIZE = re.compile(r"[1-9][0-9]{0,4}[KMGT]")
BLOCKED_DIRECTORIES = (
    "/var/lib/cosmabot/postgres",
    "/var/lib/cosmabot/redis",
    "/var/lib/postgresql",
    "/etc/cosmabot/backup",
    "/opt/cosmabot/backup",
)
DEFAULTS = {
    "version": 1,
    "enabled": False,
    "dry_run": True,
    "docker": {"driver": "local", "max_size": "10m", "max_file": 3},
    "services": list(SERVICES),
    "journald": {
        "system_max_use": "200M",
        "max_retention_sec": "7day",
        "max_file_sec": "1day",
    },
    "caddy": {
        "enabled": False,
        "path": "/data/logs/access.log",
        "roll_size": "10MiB",
        "roll_keep": 5,
        "roll_keep_for": "168h",
    },
    "standalone": {"rotate": 7, "max_size": "10M"},
}


class Refused(RuntimeError):
    """Operator-facing text only."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Refused(message)


def _section(value: dict, key: str, allowed: set[str]) -> dict:
    raw = value.get(key, {})
    require(type(raw) is dict and set(raw) <= allowed, key)
    return raw


def _bool(raw: dict, key: str, default: bool) -> bool:
    if key not in raw:
        return default
    require(type(raw[key]) is bool, key)
    return raw[key]


def _int(raw: dict, key: str, default: int, low: int, high: int) -> int:
    if key not in raw:
        return default
    number = raw[key]
    require(type(number) is int and low <= number <= high, key)
    return number


def _match(raw: dict, key: str, default: str, pattern: re.Pattern[str]) -> str:
    if key not in raw:
        return default
    value = raw[key]
    require(isinstance(value, str) and pattern.fullmatch(value) is not None, key)
    return value


def parse_config(value: dict | None = None) -> dict:
    """Fill omitted settings from the defaults. Unknown keys are refused."""
    if value is None:
        value = {}
    require(type(value) is dict and set(value) <= set(DEFAULTS), "configuration keys")
    if "version" in value:
        require(type(value["version"]) is int and value["version"] == 1, "configuration version")
    docker_raw = _section(value, "docker", {"driver", "max_size", "max_file"})
    journal_raw = _section(
        value, "journald", {"system_max_use", "max_retention_sec", "max_file_sec"}
    )
    caddy_raw = _section(
        value, "caddy", {"enabled", "path", "roll_size", "roll_keep", "roll_keep_for"}
    )
    standalone_raw = _section(value, "standalone", {"rotate", "max_size"})
    if "services" in value:
        require(value["services"] == SERVICES, "services")
    docker_default = DEFAULTS["docker"]
    journal_default = DEFAULTS["journald"]
    caddy_default = DEFAULTS["caddy"]
    standalone_default = DEFAULTS["standalone"]
    return {
        "version": 1,
        "enabled": _bool(value, "enabled", DEFAULTS["enabled"]),
        "dry_run": _bool(value, "dry_run", DEFAULTS["dry_run"]),
        "docker": {
            "driver": _match(docker_raw, "driver", docker_default["driver"], re.compile("local")),
            "max_size": _match(docker_raw, "max_size", docker_default["max_size"], DOCKER_SIZE),
            "max_file": _int(docker_raw, "max_file", docker_default["max_file"], 1, 50),
        },
        "services": list(SERVICES),
        "journald": {
            "system_max_use": _match(
                journal_raw, "system_max_use", journal_default["system_max_use"], JOURNAL_SIZE
            ),
            "max_retention_sec": _match(
                journal_raw,
                "max_retention_sec",
                journal_default["max_retention_sec"],
                JOURNAL_AGE,
            ),
            "max_file_sec": _match(
                journal_raw, "max_file_sec", journal_default["max_file_sec"], JOURNAL_AGE
            ),
        },
        "caddy": {
            "enabled": _bool(caddy_raw, "enabled", caddy_default["enabled"]),
            "path": _match(caddy_raw, "path", caddy_default["path"], CADDY_PATH),
            "roll_size": _match(caddy_raw, "roll_size", caddy_default["roll_size"], ROLL_SIZE),
            "roll_keep": _int(caddy_raw, "roll_keep", caddy_default["roll_keep"], 1, 100),
            "roll_keep_for": _match(
                caddy_raw, "roll_keep_for", caddy_default["roll_keep_for"], ROLL_FOR
            ),
        },
        "standalone": {
            "rotate": _int(standalone_raw, "rotate", standalone_default["rotate"], 1, 365),
            "max_size": _match(
                standalone_raw, "max_size", standalone_default["max_size"], LOGROTATE_SIZE
            ),
        },
    }


def load_config(path: Path | None = None) -> dict:
    selected = DEFAULT_PATH if path is None else path
    require(not selected.is_symlink(), "configuration symlink")
    if not selected.exists():
        return parse_config({})
    raw = selected.read_bytes()
    require(len(raw) <= 65536, "configuration size")
    loaded = json.loads(raw)
    require(type(loaded) is dict, "configuration keys")
    return parse_config(loaded)


def docker_log_options(config: dict | None = None) -> dict[str, str]:
    chosen = parse_config({}) if config is None else config
    docker = chosen["docker"]
    return {"max-size": docker["max_size"], "max-file": str(docker["max_file"])}


def docker_compose_logging(config: dict | None = None) -> dict:
    chosen = parse_config({}) if config is None else config
    return {"driver": chosen["docker"]["driver"], "options": docker_log_options(chosen)}


def journald_dropin(config: dict | None = None) -> str:
    chosen = parse_config({}) if config is None else config
    journal = chosen["journald"]
    return (
        "[Journal]\n"
        f"SystemMaxUse={journal['system_max_use']}\n"
        f"MaxRetentionSec={journal['max_retention_sec']}\n"
        f"MaxFileSec={journal['max_file_sec']}\n"
    )


def caddy_global_lines(config: dict | None = None) -> str:
    """Empty until caddy.enabled is true, so the current Caddyfile stays unchanged."""
    chosen = parse_config({}) if config is None else config
    caddy = chosen["caddy"]
    if not caddy["enabled"]:
        return ""
    return (
        "\n"
        "    log {\n"
        f"        output file {caddy['path']} {{\n"
        f"            roll_size {caddy['roll_size']}\n"
        f"            roll_keep {caddy['roll_keep']}\n"
        f"            roll_keep_for {caddy['roll_keep_for']}\n"
        "        }\n"
        "        format json\n"
        "    }"
    )


def standalone_logrotate(config: dict | None = None) -> str:
    chosen = parse_config({}) if config is None else config
    standalone = chosen["standalone"]
    paths = " ".join(f"/var/log/cosmabot-standalone/{name}.log" for name in SERVICES)
    return (
        f"{paths} {{\n"
        "    daily\n"
        f"    rotate {standalone['rotate']}\n"
        f"    maxsize {standalone['max_size']}\n"
        "    missingok\n"
        "    notifempty\n"
        "    copytruncate\n"
        "    compress\n"
        "    delaycompress\n"
        "}\n"
    )


def parse_time(value: object) -> dt.datetime:
    require(isinstance(value, str), "log time")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Refused("log time") from None
    require(parsed.tzinfo is not None, "log time")
    return parsed.astimezone(dt.timezone.utc)


def roll_keep_for(config: dict) -> dt.timedelta:
    match = ROLL_FOR.fullmatch(config["caddy"]["roll_keep_for"])
    require(match is not None, "roll_keep_for")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "h":
        return dt.timedelta(hours=amount)
    if unit == "m":
        return dt.timedelta(minutes=amount)
    return dt.timedelta(seconds=amount)


def _rolled_pattern(path: str) -> re.Pattern[str]:
    filename = path.rsplit("/", 1)[-1]
    stem, extension = filename.rsplit(".", 1)
    return re.compile(
        rf"{re.escape(stem)}-\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}-\d{{2}}-\d{{2}}\.\d{{3}}\.{re.escape(extension)}"
    )


def log_delete_set(files: list[dict], config: dict, *, now: dt.datetime) -> dict:
    """Caddy/lumberjack rolls. The active file is kept. Other names are ignored."""
    require(now.tzinfo is not None, "clock")
    now = now.astimezone(dt.timezone.utc)
    active = config["caddy"]["path"].rsplit("/", 1)[-1]
    pattern = _rolled_pattern(config["caddy"]["path"])
    rolled = []
    ignored = []
    seen: set[str] = set()
    for item in files:
        require(isinstance(item, dict) and isinstance(item.get("name"), str), "log file")
        name = item["name"]
        require("/" not in name and name not in {".", ".."}, "log file")
        require(name not in seen, "duplicate log file")
        seen.add(name)
        if name == active or item.get("active") is True:
            continue
        if pattern.fullmatch(name) is None:
            ignored.append(name)
            continue
        rolled.append((name, parse_time(item.get("modified"))))
    rolled.sort(key=lambda item: item[1], reverse=True)
    age = now - roll_keep_for(config)
    delete_names = [
        name
        for index, (name, modified) in enumerate(rolled)
        if index >= config["caddy"]["roll_keep"] or modified < age
    ]
    kept = {name for name, _modified in rolled} - set(delete_names)
    if active in seen:
        kept.add(active)
    return {
        "delete_names": delete_names,
        "keep_names": sorted(kept),
        "ignored_names": sorted(ignored),
    }


def build_plan(config: dict, files: list[dict] | None, *, now: dt.datetime) -> dict:
    chosen = log_delete_set(files or [], config, now=now)
    return {
        "event": "log_retention_plan",
        "status": "planned",
        "dry_run": config["dry_run"],
        "enabled": config["enabled"],
        "services": list(config["services"]),
        "docker_logging": docker_compose_logging(config),
        "journald_dropin": journald_dropin(config),
        "caddy_lines": caddy_global_lines(config),
        "caddy_enabled": config["caddy"]["enabled"],
        "standalone_logrotate": standalone_logrotate(config),
        "delete_names": chosen["delete_names"],
        "keep_names": chosen["keep_names"],
        "ignored_names": chosen["ignored_names"],
        "applied": False,
        "notes": [
            "docker rotation is enforced by the daemon and compose logging options",
            "journald vacuum is enforced only after the drop-in is installed",
            "caddy roll stays off until caddy.enabled is true and a release is re-rendered",
        ],
    }


def _allowed_directory(directory: Path) -> Path:
    require(directory.is_absolute() and not directory.is_symlink(), "log directory")
    resolved = directory.resolve()
    text = str(resolved)
    require(text not in {"/", "/var", "/var/lib", "/etc", "/opt", "/tmp"}, "log directory")
    require(
        not any(text == item or text.startswith(item + "/") for item in BLOCKED_DIRECTORIES),
        "log directory",
    )
    require(resolved.is_dir() and not resolved.is_symlink(), "log directory")
    return resolved


def apply_log_deletions(plan: dict, directory: Path, *, confirm_apply: bool) -> dict:
    require(plan["enabled"] is True, "retention is disabled")
    require(plan["dry_run"] is False, "dry-run does not delete")
    require(confirm_apply is True, "confirm-apply required")
    require(os.environ.get("COSMABOT_LOG_RETENTION_APPLY") == "1", "apply environment is not set")
    root = _allowed_directory(directory)
    targets = []
    for name in plan["delete_names"]:
        require("/" not in name and name not in {".", ".."}, "log file")
        path = root / name
        require(path.parent == root, "log file")
        if not path.exists():
            continue
        require(path.is_file() and not path.is_symlink(), "refusing a symlink")
        targets.append(path)
    removed = []
    for path in targets:
        path.unlink()
        removed.append(path.name)
    applied = dict(plan)
    applied.update(applied=True, removed=removed, status="logs_removed")
    return applied


def emit(record: dict, log_file: Path | None) -> None:
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    sys.stdout.write(line)
    if log_file is None:
        return
    require(log_file.is_absolute() and not log_file.is_symlink(), "log path")
    descriptor = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, line.encode())
    finally:
        os.close(descriptor)


def _load_files(path: Path | None) -> list[dict] | None:
    if path is None:
        return None
    require(path.is_absolute() and not path.is_symlink(), "log file list")
    raw = path.read_bytes()
    require(len(raw) <= 8 * 1024 * 1024, "log file list size")
    value = json.loads(raw)
    require(isinstance(value, list), "log file list")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("plan", "apply"), default="plan")
    parser.add_argument("--config", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--files", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--now", help="UTC RFC3339 clock for the plan")
    parser.add_argument("--confirm-apply", action="store_true")
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        config = load_config(args.config)
        now = parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
        plan = build_plan(config, _load_files(args.files), now=now)
        if args.action == "plan":
            emit(plan, args.log_file)
            return 0
        require(args.directory is not None, "log directory")
        emit(
            apply_log_deletions(plan, args.directory, confirm_apply=args.confirm_apply),
            args.log_file,
        )
        return 0
    except Refused as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
