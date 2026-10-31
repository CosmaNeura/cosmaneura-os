"""Retention plans use synthetic lists only. No storage client, host, or delete runs."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "infra/beta/vm/backup"
LOGGING = ROOT / "infra/beta/vm/logging"
NOW = datetime(2026, 10, 30, 3, tzinfo=UTC)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = load("retention_backup_plan", BACKUP / "retention.py")
logs = load("retention_log_plan", LOGGING / "retention.py")
installer = load("retention_backup_install", BACKUP / "install-host.py")
controller = load("retention_backup_controller", BACKUP / "backup.py")


def listed(segment: int, month: int, day: int, *, permanent: bool = False) -> dict:
    return {
        "backup_name": f"base_{1:08X}{segment:08X}{0:08X}",
        "start_time": f"2026-{month:02d}-{day:02d}T03:00:00Z",
        "is_permanent": permanent,
        "hostname": "synthetic-host",
    }


def october(count: int, *, permanent_segments: set[int] | None = None) -> list[dict]:
    permanent_segments = permanent_segments or set()
    return [
        listed(segment, 10, segment, permanent=segment in permanent_segments)
        for segment in range(1, count + 1)
    ]


def names(plan: dict) -> list[str]:
    return plan["delete_names"]


def test_backup_defaults_match_the_committed_file_and_wal_g_paths():
    committed = json.loads((BACKUP / "retention.json").read_text())
    assert backup.parse_config({}) == backup.parse_config(committed)
    assert backup.load_config()["dry_run"] is True
    assert backup.load_config()["enabled"] is False
    assert backup.load_config()["policy"] == "retain_count"
    assert backup.load_config()["retain_count"] == 14
    assert backup.load_config()["retain_days"] == 30
    assert backup.WALG == str(controller.WALG)
    assert backup.WALG_CONFIG == str(controller.ROOT / "walg.json")


@pytest.mark.parametrize(
    "value",
    [
        {"policy": "forever"},
        {"retain_count": 0},
        {"retain_count": True},
        {"retain_days": "30"},
        {"enabled": 1},
        {"version": 2},
        {"storage_account": "synthetic"},
    ],
)
def test_backup_config_refuses_unknown_or_unsafe_values(value):
    with pytest.raises(backup.Refused):
        backup.parse_config(value)


def test_partial_backup_config_keeps_safe_defaults():
    parsed = backup.parse_config({"policy": "retain_days"})
    assert parsed["policy"] == "retain_days"
    assert parsed["retain_days"] == 30
    assert parsed["dry_run"] is True
    assert parsed["enabled"] is False


def test_retain_count_dry_run_selects_only_backups_older_than_the_newest_14():
    config = backup.load_config()
    plan = backup.build_plan(backup.parse_backup_list(october(16)), config, now=NOW)
    expected = [listed(segment, 10, segment)["backup_name"] for segment in (1, 2)]
    assert names(plan) == expected
    assert plan["keep_names"][0] == listed(3, 10, 3)["backup_name"]
    assert plan["boundary_name"] == listed(3, 10, 3)["backup_name"]
    assert plan["dry_run"] is True and plan["confirm"] is False and plan["applied"] is False
    assert plan["invoke"] is True
    assert plan["wal_g_argv"] == [
        "/opt/cosmabot/backup/wal-g",
        "--config",
        "/etc/cosmabot/backup/walg.json",
        "delete",
        "retain",
        "FULL",
        "14",
        "--use-sentinel-time",
    ]
    assert "--confirm" not in plan["wal_g_argv"]
    short = backup.build_plan(backup.parse_backup_list(october(3)), config, now=NOW)
    assert short["delete_names"] == [] and short["invoke"] is False


def test_permanent_backup_before_the_boundary_is_kept_and_not_submitted():
    config = backup.load_config()
    rows = october(16, permanent_segments={1})
    plan = backup.build_plan(backup.parse_backup_list(rows), config, now=NOW)
    assert names(plan) == [listed(2, 10, 2)["backup_name"]]
    assert listed(1, 10, 1)["backup_name"] in plan["keep_names"]
    assert plan["hold"] == "permanent_backup_before_boundary"
    assert plan["invoke"] is False


def test_retain_days_matches_delete_before_and_will_not_remove_every_backup():
    config = backup.parse_config({"policy": "retain_days"})
    rows = [
        listed(1, 9, 1),
        listed(2, 9, 30),
        listed(3, 10, 15),
    ]
    plan = backup.build_plan(backup.parse_backup_list(rows), config, now=NOW)
    assert backup.format_time(backup.cutoff(config, NOW)) == "2026-09-30T03:00:00Z"
    assert names(plan) == [listed(1, 9, 1)["backup_name"]]
    assert listed(2, 9, 30)["backup_name"] in plan["keep_names"]
    assert plan["wal_g_argv"][-3:] == ["before", "2026-09-30T03:00:00Z", "--use-sentinel-time"]
    assert "--confirm" not in plan["wal_g_argv"]
    older = [listed(1, 8, 1), listed(2, 9, 29)]
    held = backup.build_plan(backup.parse_backup_list(older), config, now=NOW)
    assert held["delete_names"] == []
    assert held["hold"] == "cutoff_after_every_backup"
    assert held["invoke"] is False


@pytest.mark.parametrize(
    "rows",
    [
        [listed(1, 10, 1), listed(1, 10, 2)],
        [{"backup_name": "base_000000010000000000000001_D_000000010000000000000002",
          "start_time": "2026-10-01T03:00:00Z"}],
        [{"backup_name": "base_000000010000000100000000", "time": "2026-10-01T03:00:00Z"}],
        [{"backup_name": "not-a-backup", "start_time": "2026-10-01T03:00:00Z"}],
    ],
)
def test_backup_list_refuses_duplicates_incrementals_and_bad_names(rows):
    with pytest.raises(backup.Refused):
        backup.parse_backup_list(rows)


def test_apply_gates_do_not_call_the_delete_runner(monkeypatch):
    config = backup.load_config()
    plan = backup.build_plan(backup.parse_backup_list(october(16)), config, now=NOW)
    called = []
    monkeypatch.delenv("COSMABOT_RETENTION_APPLY", raising=False)

    def runner(argv):
        called.append(argv)

    with pytest.raises(backup.Refused):
        backup.apply_plan(plan, confirm_apply=True, runner=runner)
    opened = backup.parse_config({"enabled": True, "dry_run": False})
    opened_plan = backup.build_plan(backup.parse_backup_list(october(16)), opened, now=NOW)
    with pytest.raises(backup.Refused):
        backup.apply_plan(opened_plan, confirm_apply=False, runner=runner)
    with pytest.raises(backup.Refused):
        backup.apply_plan(opened_plan, confirm_apply=True, runner=runner)
    assert called == []


def test_apply_submits_one_confirmed_command_and_skips_an_empty_set(monkeypatch):
    monkeypatch.setenv("COSMABOT_RETENTION_APPLY", "1")
    config = backup.parse_config({"enabled": True, "dry_run": False})
    plan = backup.build_plan(backup.parse_backup_list(october(16)), config, now=NOW)
    called = []
    applied = backup.apply_plan(plan, confirm_apply=True, runner=called.append)
    assert called == [plan["wal_g_argv"] + ["--confirm"]]
    assert applied["applied"] is True and applied["confirm"] is True
    assert "--confirm" not in plan["wal_g_argv"]
    empty = backup.build_plan(backup.parse_backup_list(october(2)), config, now=NOW)
    skipped = backup.apply_plan(empty, confirm_apply=True, runner=called.append)
    assert skipped["applied"] is False and skipped["status"] == "not_invoked"
    assert len(called) == 1


def test_plan_command_logs_the_dry_run_and_does_not_touch_a_sentinel_file(tmp_path, monkeypatch):
    def boom(argv):
        raise AssertionError(argv)

    monkeypatch.setattr(backup, "run_delete", boom)
    monkeypatch.setattr(backup, "host_delete_environment", boom)
    sentinel = tmp_path / "staging-backup-must-remain"
    sentinel.write_text("keep")
    listing = tmp_path / "backups.json"
    listing.write_text(json.dumps(october(16)))
    log_file = tmp_path / "retention.log"
    code = backup.main(
        [
            "plan",
            "--config",
            str(BACKUP / "retention.json"),
            "--backup-list",
            str(listing),
            "--now",
            "2026-10-30T03:00:00Z",
            "--log-file",
            str(log_file),
        ]
    )
    assert code == 0
    recorded = json.loads(log_file.read_text())
    assert recorded["delete_names"] == [listed(segment, 10, segment)["backup_name"] for segment in (1, 2)]
    assert recorded["applied"] is False and recorded["confirm"] is False
    assert sentinel.read_text() == "keep"
    missing = backup.main(["plan", "--config", str(BACKUP / "retention.json"), "--backup-list", str(tmp_path / "absent.json")])
    assert missing == 0
    refused = backup.main(
        [
            "apply",
            "--config",
            str(BACKUP / "retention.json"),
            "--backup-list",
            str(listing),
            "--confirm-apply",
        ]
    )
    assert refused == 1


def test_backup_schedule_is_outside_the_installer_and_cannot_confirm():
    unit = (BACKUP / "cosmabot-backup-retention.service").read_text()
    timer = (BACKUP / "cosmabot-backup-retention.timer").read_text()
    assert " plan " in unit
    assert "apply" not in unit and "--confirm" not in unit and "LoadCredential" not in unit
    assert "PrivateNetwork=yes" in unit
    assert "06:00:00 UTC" in timer
    assert "cosmabot-backup-retention.service" not in installer.FILES
    assert "cosmabot-backup-retention.timer" not in installer.FILES
    assert "retention.py" not in installer.FILES
    assert "retention.json" not in installer.FILES


def test_log_defaults_match_the_committed_file():
    committed = json.loads((LOGGING / "retention.json").read_text())
    parsed = logs.parse_config({})
    assert logs.parse_config(committed) == parsed
    assert parsed["dry_run"] is True and parsed["enabled"] is False
    assert parsed["services"] == ["web", "api", "worker", "proxy"]
    assert logs.docker_compose_logging(parsed) == {
        "driver": "local",
        "options": {"max-size": "10m", "max-file": "3"},
    }
    dropin = logs.journald_dropin(parsed)
    assert "SystemMaxUse=200M" in dropin
    assert "MaxRetentionSec=7day" in dropin
    assert "MaxFileSec=1day" in dropin
    assert logs.caddy_global_lines(parsed) == ""
    rotate = logs.standalone_logrotate(parsed)
    for name in ("web", "api", "worker", "proxy"):
        assert f"/var/log/cosmabot-standalone/{name}.log" in rotate
    assert "rotate 7" in rotate and "maxsize 10M" in rotate


@pytest.mark.parametrize(
    "value",
    [
        {"docker": {"driver": "json-file"}},
        {"docker": {"max_size": "10M"}},
        {"docker": {"max_file": 0}},
        {"services": ["api"]},
        {"caddy": {"path": "/tmp/access.log"}},
        {"caddy": {"roll_keep_for": "7day"}},
        {"journald": {"system_max_use": "10m"}},
        {"extra": True},
    ],
)
def test_log_config_refuses_unknown_or_unsafe_values(value):
    with pytest.raises(logs.Refused):
        logs.parse_config(value)


def test_caddy_roll_dry_run_computes_the_delete_set_without_removing_files(tmp_path):
    config = logs.parse_config({"caddy": {"roll_keep": 2}})
    files = [
        {"name": "access.log", "modified": "2026-10-30T00:00:00Z", "active": True},
        {"name": "access-2026-10-29T00-00-00.000.log", "modified": "2026-10-29T00:00:00Z"},
        {"name": "access-2026-10-28T00-00-00.000.log", "modified": "2026-10-28T00:00:00Z"},
        {"name": "access-2026-10-27T00-00-00.000.log", "modified": "2026-10-27T00:00:00Z"},
        {"name": "access-2026-10-20T00-00-00.000.log", "modified": "2026-10-20T00:00:00Z"},
        {"name": "notes.txt", "modified": "2026-01-01T00:00:00Z"},
    ]
    directory = tmp_path / "caddy-logs"
    directory.mkdir()
    for item in files:
        (directory / item["name"]).write_text("synthetic")
    now = datetime(2026, 10, 30, tzinfo=UTC)
    plan = logs.build_plan(config, files, now=now)
    assert plan["delete_names"] == [
        "access-2026-10-27T00-00-00.000.log",
        "access-2026-10-20T00-00-00.000.log",
    ]
    assert "access.log" in plan["keep_names"]
    assert "access-2026-10-29T00-00-00.000.log" in plan["keep_names"]
    assert plan["ignored_names"] == ["notes.txt"]
    assert plan["applied"] is False and plan["caddy_enabled"] is False
    with pytest.raises(logs.Refused):
        logs.apply_log_deletions(plan, directory, confirm_apply=True)
    assert sorted(path.name for path in directory.iterdir()) == sorted(item["name"] for item in files)


def test_log_apply_removes_only_the_computed_rolled_files(tmp_path, monkeypatch):
    monkeypatch.setenv("COSMABOT_LOG_RETENTION_APPLY", "1")
    config = logs.parse_config({"enabled": True, "dry_run": False, "caddy": {"roll_keep": 1}})
    files = [
        {"name": "access.log", "modified": "2026-10-30T00:00:00Z", "active": True},
        {"name": "access-2026-10-29T00-00-00.000.log", "modified": "2026-10-29T00:00:00Z"},
        {"name": "access-2026-10-27T00-00-00.000.log", "modified": "2026-10-27T00:00:00Z"},
        {"name": "notes.txt", "modified": "2026-01-01T00:00:00Z"},
    ]
    directory = tmp_path / "caddy-logs"
    directory.mkdir()
    for item in files:
        (directory / item["name"]).write_text("synthetic")
    plan = logs.build_plan(config, files, now=datetime(2026, 10, 30, tzinfo=UTC))
    applied = logs.apply_log_deletions(plan, directory, confirm_apply=True)
    assert applied["removed"] == ["access-2026-10-27T00-00-00.000.log"]
    assert (directory / "access.log").read_text() == "synthetic"
    assert (directory / "notes.txt").read_text() == "synthetic"
    assert not (directory / "access-2026-10-27T00-00-00.000.log").exists()


def test_log_apply_stops_before_unlinking_when_a_candidate_is_a_symlink(tmp_path, monkeypatch):
    monkeypatch.setenv("COSMABOT_LOG_RETENTION_APPLY", "1")
    config = logs.parse_config({"enabled": True, "dry_run": False, "caddy": {"roll_keep": 1}})
    files = [
        {"name": "access-2026-10-28T00-00-00.000.log", "modified": "2026-10-28T00:00:00Z"},
        {"name": "access-2026-10-27T00-00-00.000.log", "modified": "2026-10-27T00:00:00Z"},
        {"name": "access-2026-10-20T00-00-00.000.log", "modified": "2026-10-20T00:00:00Z"},
    ]
    directory = tmp_path / "caddy-logs"
    directory.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("keep")
    (directory / files[0]["name"]).write_text("keep")
    (directory / files[1]["name"]).symlink_to(outside)
    (directory / files[2]["name"]).write_text("synthetic")
    plan = logs.build_plan(config, files, now=datetime(2026, 10, 30, tzinfo=UTC))
    with pytest.raises(logs.Refused, match="symlink"):
        logs.apply_log_deletions(plan, directory, confirm_apply=True)
    assert outside.read_text() == "keep"
    assert (directory / files[2]["name"]).read_text() == "synthetic"
    with pytest.raises(logs.Refused, match="log directory"):
        logs.apply_log_deletions(plan, Path("/var/lib/cosmabot/postgres"), confirm_apply=True)


def test_runtime_and_host_keep_the_current_docker_limits(tmp_path):
    host = load("retention_bootstrap_host", ROOT / "infra/beta/vm/host/bootstrap_host.py")
    document = host.docker_daemon_document()
    assert document["log-driver"] == "local"
    assert document["log-opts"] == {"max-size": "10m", "max-file": "3"}
    assert document["firewall-backend"] == "iptables"
    runtime = ROOT / "infra/beta/vm/runtime"
    sys.path.insert(0, str(runtime))
    try:
        vm = load("retention_vm_renderer", runtime / "render.py")
    finally:
        sys.path.remove(str(runtime))
    assert vm.LOGS.docker_compose_logging(vm.LOG_CONFIG)["options"] == document["log-opts"]
    sample = {
        "web_origin": "https://staging.cosmas.ai",
        "api_origin": "https://api.staging.cosmas.ai",
    }
    assert "roll_size" not in vm.caddy(sample)
    assert "http_port 8080" in vm.caddy(sample)
    enabled = logs.parse_config({"caddy": {"enabled": True}})
    renderer: Any = vm
    renderer.LOG_CONFIG = enabled
    rolled = renderer.caddy(sample)
    assert "roll_size 10MiB" in rolled
    assert "roll_keep 5" in rolled
    assert "roll_keep_for 168h" in rolled
    assert "output file /data/logs/access.log" in rolled
    assert not (tmp_path / "unexpected-delete").exists()


def test_log_schedule_is_plan_only():
    unit = (LOGGING / "cosmabot-log-retention.service").read_text()
    timer = (LOGGING / "cosmabot-log-retention.timer").read_text()
    assert " plan " in unit
    assert "apply" not in unit and "--confirm" not in unit and "--directory" not in unit
    assert "PrivateNetwork=yes" in unit
    assert "06:15:00 UTC" in timer
