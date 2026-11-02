import copy
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("health_probe", Path(__file__).with_name("probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
NOW = datetime.datetime(2026, 9, 27, 12, tzinfo=datetime.timezone.utc)


def healthy():
    units = {
        name: {"Id": name, "ActiveState": "active", "UnitFileState": "enabled", "Result": "success"}
        for name in probe.UNITS
    }
    units["cosmabot-backup-receive.service"]["SubState"] = "running"
    units["cosmabot-backup-job@status.service"].update(
        ActiveState="inactive", ExecMainStatus="0", ExecMainExitTimestampMonotonic="900000000"
    )
    containers = [
        {
            "service": name,
            "state": {
                "Running": True,
                "Status": "running",
                "Health": {"Status": "healthy", "Log": [{"End": NOW.isoformat(), "ExitCode": 0}]},
            },
        }
        for name in sorted(probe.SERVICES)
    ]
    return units, containers


def test_running_and_recently_verified_services_are_healthy():
    units, containers = healthy()
    assert probe.application_healthy(units, containers, NOW)
    assert probe.backup_healthy(units, 1000)


def test_docker_nanoseconds_are_normalized_for_the_host_python():
    assert probe.docker_time("2026-09-27T12:00:00.696014881Z") == NOW.replace(microsecond=696014)
    assert probe.docker_time("2026-09-27T14:00:00.696014881+02:00") == NOW.replace(microsecond=696014)
    units, containers = healthy()
    for item in containers:
        item["state"]["Health"]["Log"][0]["End"] = "2026-09-27T12:00:00.000000001Z"
    assert probe.application_healthy(units, containers, NOW)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "stopped",
        "paused",
        "unhealthy",
        "stale",
        "failed_check",
        "prepare_running",
    ],
)
def test_failed_or_incomplete_application_evidence_is_not_healthy(change):
    units, containers = healthy()
    state = containers[0]["state"]
    if change == "missing":
        containers.pop()
    elif change == "duplicate":
        containers.append(copy.deepcopy(containers[0]))
    elif change == "stopped":
        state["Running"] = False
    elif change == "paused":
        state["Paused"] = True
    elif change == "unhealthy":
        state["Health"]["Status"] = "unhealthy"
    elif change == "stale":
        state["Health"]["Log"][0]["End"] = (NOW - datetime.timedelta(seconds=91)).isoformat()
    elif change == "failed_check":
        state["Health"]["Log"][0]["ExitCode"] = 1
    else:
        containers.append(
            {"service": "database_prepare", "state": {"Running": True, "ExitCode": 0}}
        )
    assert not probe.application_healthy(units, containers, NOW)


@pytest.mark.parametrize(
    "unit,field,value",
    [
        ("cosmabot-backup-receive.service", "ActiveState", "failed"),
        ("cosmabot-backup-receive.service", "UnitFileState", "disabled"),
        ("cosmabot-backup-status.timer", "ActiveState", "inactive"),
        ("cosmabot-backup.timer", "UnitFileState", "disabled"),
        ("cosmabot-backup-job@status.service", "Result", "exit-code"),
        ("cosmabot-backup-job@status.service", "ExecMainStatus", "1"),
        ("cosmabot-backup-job@status.service", "ExecMainExitTimestampMonotonic", "0"),
        ("cosmabot-backup-job@status.service", "ExecMainExitTimestampMonotonic", "699000000"),
        ("cosmabot-backup-job@status.service", "ExecMainExitTimestampMonotonic", "1001000000"),
    ],
)
def test_backup_failure_disabled_schedule_missing_and_stale_checks(unit, field, value):
    units, _ = healthy()
    units[unit][field] = value
    assert not probe.backup_healthy(units, 1000)


def test_failed_collection_emits_only_fixed_health_fields(monkeypatch):
    def refused(_):
        raise RuntimeError("private credential and record must not be emitted")

    monkeypatch.setattr(probe, "command", refused)
    message = probe.encode(*probe.observe())
    assert message.startswith(probe.PREFIX)
    report = json.loads(message[len(probe.PREFIX) :])
    assert set(report) == {"application", "backup", "observed_at"}
    assert report["application"] == report["backup"] == "failed"
    assert "private" not in message


def test_missing_and_duplicate_unit_observations_refused():
    units, _ = healthy()
    raw = "\n\n".join(
        "\n".join(f"{key}={value}" for key, value in unit.items()) for unit in units.values()
    )
    assert probe.unit_observations(raw) == units
    with pytest.raises(ValueError):
        probe.unit_observations(raw + "\n\nId=cosmabot-staging.service")
    with pytest.raises(ValueError):
        probe.unit_observations("Id=cosmabot-staging.service")


def test_application_failure_does_not_erase_independent_backup_health(monkeypatch):
    units, _ = healthy()
    monkeypatch.setattr(probe, "command", lambda _: "observed")
    monkeypatch.setattr(probe, "unit_observations", lambda _: units)
    monkeypatch.setattr(probe.time, "monotonic", lambda: 1000)

    def unavailable():
        raise RuntimeError("docker unavailable")

    monkeypatch.setattr(probe, "containers", unavailable)
    application, backup, _ = probe.observe()
    assert not application and backup


def use_release(monkeypatch, tmp_path, release_id="stg-active-release"):
    root = tmp_path / "releases"
    root.mkdir()
    monkeypatch.setattr(probe, "RELEASE_ROOT", root)
    monkeypatch.setattr(probe, "POINTER", tmp_path / "active-release")
    return root, root / release_id


def point_at(release):
    probe.POINTER.write_text(f"RELEASE_DIR={release}\n")


def write_release(release):
    release.mkdir(exist_ok=True)
    services = {name: {} for name in sorted(probe.SERVICES)}
    services["proxy"] = {"ports": ["80:8080", "443:8443"]}
    services["database_prepare"] = {"profiles": ["prepare"]}
    plan = {"name": "cosmabot-staging", "services": services}
    raw = json.dumps(plan, indent=2).encode() + b"\n"
    (release / "compose.json").write_bytes(raw)
    manifest = {"version": 1, "files": {"compose.json": hashlib.sha256(raw).hexdigest()}}
    (release / "RENDER.json").write_bytes(json.dumps(manifest).encode() + b"\n")
    return plan


def prepare_units(monkeypatch):
    units, _ = healthy()
    monkeypatch.setattr(probe, "unit_observations", lambda _: units)
    monkeypatch.setattr(probe.time, "monotonic", lambda: 1000)
    return units


def test_missing_active_release_pointer_fails_clearly(monkeypatch, tmp_path):
    use_release(monkeypatch, tmp_path)
    prepare_units(monkeypatch)
    monkeypatch.setattr(probe, "command", lambda _: "observed")
    with pytest.raises(ValueError, match="^active release pointer is missing$"):
        probe.resolve_active_release()
    application, backup, _ = probe.observe()
    assert application is False and backup is True


@pytest.mark.parametrize("shape", ["absent", "symlink"])
def test_dangling_active_release_pointer_fails_clearly(monkeypatch, tmp_path, shape):
    root, release = use_release(monkeypatch, tmp_path, "stg-dangling-release")
    prepare_units(monkeypatch)
    monkeypatch.setattr(probe, "command", lambda _: "observed")
    if shape == "symlink":
        release.symlink_to(root / "stg-missing-target")
    point_at(release)
    with pytest.raises(ValueError, match="^active release pointer is dangling$"):
        probe.resolve_active_release()
    application, backup, _ = probe.observe()
    assert application is False and backup is True


def test_present_pointer_checks_only_that_release_and_ignores_stopped_leftovers(monkeypatch, tmp_path):
    _root, release = use_release(monkeypatch, tmp_path)
    plan = write_release(release)
    point_at(release)
    prepare_units(monkeypatch)
    _manifest, loaded = probe.read_release(release)
    assert loaded["name"] == plan["name"]
    assert probe.published_ports(loaded) == (80, 443)
    (release / "compose.json").write_bytes(b'{"name":"tampered"}\n')
    with pytest.raises(ValueError, match="active release plan does not match its manifest"):
        probe.read_release(release)
    write_release(release)

    end = datetime.datetime.now(datetime.timezone.utc).isoformat()
    active = {
        f"{index:064x}": {
            "service": name,
            "config": str(release / "compose.json"),
            "state": {
                "Running": True,
                "Status": "running",
                "Health": {"Status": "healthy", "Log": [{"End": end, "ExitCode": 0}]},
            },
        }
        for index, name in enumerate(sorted(probe.SERVICES), start=1)
    }
    leftover = "f" * 64
    active[leftover] = {
        "service": "api",
        "config": str(release.parent / "stg-older-release" / "compose.json"),
        "state": {"Running": False, "Status": "exited", "ExitCode": 0},
    }
    checked = []

    def command(arguments):
        if arguments[0] == "/usr/bin/systemctl":
            return ""
        if arguments[:3] == ["/usr/bin/docker", "container", "ls"]:
            selected = ""
            prefix = "label=com.docker.compose.project.config_files="
            for item in arguments:
                if item.startswith(prefix):
                    selected = item[len(prefix) :]
            assert selected == str(release / "compose.json")
            matched = [cid for cid, row in active.items() if row["config"] == selected]
            assert leftover not in matched
            return "\n".join(matched) + "\n"
        if arguments[:3] == ["/usr/bin/docker", "container", "inspect"]:
            assert leftover not in arguments
            rows = []
            for cid in arguments[5:]:
                row = active[cid]
                rows.append(
                    json.dumps(
                        {"service": row["service"], "config": row["config"], "state": row["state"]}
                    )
                )
            return "\n".join(rows) + "\n"
        raise AssertionError(arguments)

    def healthy_web():
        checked.append(443)
        return True

    def open_port(port):
        checked.append(port)
        return True

    monkeypatch.setattr(probe, "command", command)
    monkeypatch.setattr(probe, "web_healthy", healthy_web)
    monkeypatch.setattr(probe, "port_open", open_port)
    application, backup, _ = probe.observe()
    assert application is True and backup is True
    assert checked == [80, 443]
