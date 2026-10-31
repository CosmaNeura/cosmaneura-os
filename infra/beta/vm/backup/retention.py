#!/usr/bin/python3
"""Plan WAL-G backup retention from a local backup list. Dry-run unless an operator applies it.

The plan reads JSON only. It does not open a storage connection. Apply is a separate
command and still refuses unless retention.json enables it, dry_run is false, the
process environment sets COSMABOT_RETENTION_APPLY=1, and the operator passes
--confirm-apply. The scheduled unit runs plan only and has no backup credential.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

WALG = "/opt/cosmabot/backup/wal-g"
WALG_CONFIG = "/etc/cosmabot/backup/walg.json"
DEFAULT_PATH = Path(__file__).with_name("retention.json")
NAME = re.compile(r"base_[0-9A-F]{24}")
KEYS = {"version", "enabled", "dry_run", "policy", "retain_count", "retain_days"}
DEFAULTS = {
    "version": 1,
    "enabled": False,
    "dry_run": True,
    "policy": "retain_count",
    "retain_count": 14,
    "retain_days": 30,
}


class Refused(RuntimeError):
    """Operator-facing text only. No storage payload or credential is included."""


class ListedBackup(NamedTuple):
    name: str
    start: dt.datetime
    permanent: bool


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Refused(message)


def parse_time(value: object) -> dt.datetime:
    require(isinstance(value, str) and "T" in value, "backup time")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Refused("backup time") from None
    require(parsed.tzinfo is not None, "backup time")
    return parsed.astimezone(dt.timezone.utc)


def format_time(value: dt.datetime) -> str:
    utc = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    precision = "seconds" if utc.microsecond == 0 else "microseconds"
    return utc.isoformat(timespec=precision) + "Z"


def parse_config(value: dict | None = None) -> dict:
    """Fill omitted settings from the defaults. Unknown keys are refused."""
    if value is None:
        value = {}
    require(type(value) is dict and set(value) <= KEYS, "configuration keys")
    parsed = dict(DEFAULTS)
    if "version" in value:
        require(type(value["version"]) is int and value["version"] == 1, "configuration version")
    for key in ("enabled", "dry_run"):
        if key in value:
            require(type(value[key]) is bool, key)
            parsed[key] = value[key]
    if "policy" in value:
        require(value["policy"] in {"retain_count", "retain_days"}, "policy")
        parsed["policy"] = value["policy"]
    if "retain_count" in value:
        count = value["retain_count"]
        require(type(count) is int and 1 <= count <= 10000, "retain_count")
        parsed["retain_count"] = count
    if "retain_days" in value:
        days = value["retain_days"]
        require(type(days) is int and 1 <= days <= 3650, "retain_days")
        parsed["retain_days"] = days
    return parsed


def load_config(path: Path | None = None) -> dict:
    selected = DEFAULT_PATH if path is None else path
    require(not selected.is_symlink(), "configuration symlink")
    if not selected.exists():
        return parse_config({})
    raw = selected.read_bytes()
    require(len(raw) <= 65536, "configuration size")
    return parse_config(json.loads(raw))


def parse_backup_list(value: object) -> list[ListedBackup]:
    """Accept WAL-G backup-list JSON. Extra metadata keys are ignored."""
    require(isinstance(value, list) and len(value) <= 100000, "backup list")
    found: list[ListedBackup] = []
    seen: set[str] = set()
    for item in value:
        require(isinstance(item, dict), "backup list")
        name = item.get("backup_name")
        require(isinstance(name, str) and NAME.fullmatch(name) is not None, "backup name")
        require("_D_" not in name, "incremental backups are outside this retention policy")
        if "is_full" in item:
            require(item["is_full"] is True, "incremental backups are outside this retention policy")
        require(name not in seen, "duplicate backup")
        seen.add(name)
        permanent = item.get("is_permanent", False)
        require(type(permanent) is bool, "permanent flag")
        found.append(ListedBackup(name, parse_time(item.get("start_time")), permanent))
    return found


def load_backup_list(path: Path) -> list[ListedBackup]:
    require(path.is_absolute() and not path.is_symlink(), "backup list path")
    raw = path.read_bytes()
    require(len(raw) <= 8 * 1024 * 1024, "backup list size")
    return parse_backup_list(json.loads(raw))


def cutoff(config: dict, now: dt.datetime) -> dt.datetime:
    return (now - dt.timedelta(days=config["retain_days"])).replace(microsecond=0)


def wal_g_argv(config: dict, now: dt.datetime) -> list[str]:
    """The WAL-G delete command without --confirm. Dry-run is WAL-G's own default."""
    command = [WALG, "--config", WALG_CONFIG, "delete"]
    if config["policy"] == "retain_count":
        command.extend(["retain", "FULL", str(config["retain_count"]), "--use-sentinel-time"])
    else:
        command.extend(["before", format_time(cutoff(config, now)), "--use-sentinel-time"])
    return command


def _boundary(
    backups: list[ListedBackup], config: dict, now: dt.datetime
) -> tuple[ListedBackup | None, str | None]:
    if config["policy"] == "retain_count":
        ordered = sorted(backups, key=lambda item: (item.start, item.name), reverse=True)
        if len(ordered) <= config["retain_count"]:
            return None, None
        return ordered[config["retain_count"] - 1], None
    eligible = [item for item in backups if item.start >= cutoff(config, now)]
    if not eligible:
        # WAL-G `delete before` exits without deleting when no backup remains
        # at or after the cutoff. Matching that avoids wiping the only history.
        return None, "cutoff_after_every_backup"
    return min(eligible, key=lambda item: (item.start, item.name)), None


def build_plan(backups: list[ListedBackup], config: dict, *, now: dt.datetime) -> dict:
    require(now.tzinfo is not None, "clock")
    now = now.astimezone(dt.timezone.utc)
    boundary, hold = _boundary(backups, config, now)
    if boundary is None:
        doomed: list[ListedBackup] = []
    else:
        doomed = [item for item in backups if item.start < boundary.start and not item.permanent]
        permanent_before = [
            item for item in backups if item.permanent and item.start < boundary.start
        ]
        if permanent_before:
            # `delete retain` / `delete before` also remove WAL older than the
            # boundary. Keep that WAL while a permanent backup still needs it.
            hold = "permanent_backup_before_boundary"
    delete_names = [item.name for item in sorted(doomed, key=lambda item: (item.start, item.name))]
    deleted = set(delete_names)
    keep_names = [
        item.name
        for item in sorted(backups, key=lambda item: (item.start, item.name))
        if item.name not in deleted
    ]
    active = config["retain_count"] if config["policy"] == "retain_count" else config["retain_days"]
    warnings = ["retention_below_7"] if active < 7 else []
    return {
        "event": "backup_retention_plan",
        "status": "planned",
        "at": format_time(now),
        "dry_run": config["dry_run"],
        "enabled": config["enabled"],
        "policy": config["policy"],
        "retain_count": config["retain_count"],
        "retain_days": config["retain_days"],
        "backup_count": len(backups),
        "boundary_name": None if boundary is None else boundary.name,
        "hold": hold,
        "keep_names": keep_names,
        "delete_names": delete_names,
        "permanent_names": [item.name for item in backups if item.permanent],
        "wal_g_argv": wal_g_argv(config, now),
        "confirm": False,
        "applied": False,
        "invoke": bool(delete_names) and hold is None,
        "warnings": warnings,
    }


def apply_plan(plan: dict, *, confirm_apply: bool, runner) -> dict:
    """Submit the planned WAL-G delete. The runner is called only after every gate."""
    require(plan["enabled"] is True, "retention is disabled")
    require(plan["dry_run"] is False, "dry-run does not delete")
    require(confirm_apply is True, "confirm-apply required")
    require(os.environ.get("COSMABOT_RETENTION_APPLY") == "1", "apply environment is not set")
    require(plan["confirm"] is False, "plan must not already confirm")
    require("--confirm" not in plan["wal_g_argv"], "plan must not already confirm")
    if not plan["invoke"]:
        skipped = dict(plan)
        skipped["applied"] = False
        skipped["status"] = "not_invoked"
        return skipped
    argv = [*plan["wal_g_argv"], "--confirm"]
    runner(argv)
    applied = dict(plan)
    applied.update(applied=True, confirm=True, status="delete_submitted", wal_g_argv=argv)
    return applied


def _load_backup():
    path = Path(__file__).with_name("backup.py")
    spec = importlib.util.spec_from_file_location("cosmabot_backup_retention_host", path)
    require(spec is not None and spec.loader is not None, "backup controller")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def host_delete_environment() -> dict[str, str]:
    """Reuse the backup controller's closed environment so delete hits that prefix only."""
    module = _load_backup()
    config = module.validate_config(json.loads(module.read_file(module.ROOT / "backup.json")))
    require(config["mode"] == "backup", "backup configuration required")
    credentials = Path(os.environ.get("CREDENTIALS_DIRECTORY", ""))
    require(str(credentials).startswith("/run/credentials/"), "systemd credential path")
    return module.clean_environment(config, credentials)


def run_delete(argv: list[str]) -> None:
    require(argv[-1] == "--confirm", "refusing an unconfirmed delete")
    require(os.environ.get("COSMABOT_RETENTION_APPLY") == "1", "apply environment is not set")
    completed = subprocess.run(
        argv,
        env=host_delete_environment(),
        cwd="/var/lib/cosmabot-backup",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=600,
        check=False,
    )
    require(completed.returncode == 0, "wal-g delete failed")


def skipped_plan(config: dict) -> dict:
    return {
        "event": "backup_retention_plan",
        "status": "skipped",
        "reason": "backup list is not installed",
        "dry_run": config["dry_run"],
        "enabled": config["enabled"],
        "delete_names": [],
        "confirm": False,
        "applied": False,
        "invoke": False,
    }


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("plan", "apply"), default="plan")
    parser.add_argument("--config", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--backup-list", type=Path)
    parser.add_argument("--now", help="UTC RFC3339 clock for the plan")
    parser.add_argument("--confirm-apply", action="store_true")
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        config = load_config(args.config)
        now = parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
        if args.backup_list is None or not args.backup_list.exists():
            require(args.action == "plan", "backup list is required")
            emit(skipped_plan(config), args.log_file)
            return 0
        plan = build_plan(load_backup_list(args.backup_list), config, now=now)
        if args.action == "plan":
            emit(plan, args.log_file)
            return 0
        emit(apply_plan(plan, confirm_apply=args.confirm_apply, runner=run_delete), args.log_file)
        return 0
    except Refused as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
