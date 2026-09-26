"""Public installer guards; no real users, services, credentials or cloud changes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

DIRECTORY = Path(__file__).resolve().parents[2] / "infra/beta/vm/backup"
SPEC = importlib.util.spec_from_file_location("cosmabot_backup_install", DIRECTORY / "install-host.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    # Bind small public fixture inputs. Actual pinned ELF validation is intentionally not bypassed.
    for name in installer.FILES:
        (tmp_path / name).write_bytes((DIRECTORY / name).read_bytes() if name != "wal-g" else b"wrong")
    manifest = {
        "version": 1,
        "source_commit": "a" * 40,
        "files": {
            name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
            for name in installer.FILES
        },
    }
    raw = json.dumps(manifest).encode()
    (tmp_path / "bundle.json").write_bytes(raw)
    monkeypatch.setattr(installer, "read_public", lambda path, limit: path.read_bytes())
    return tmp_path, hashlib.sha256(raw).hexdigest(), "a" * 40


@pytest.mark.parametrize("change", ["manifest", "source", "payload", "extra", "binary"])
def test_bundle_refuses_unreviewed_or_incomplete_installation(bundle, change):
    directory, digest, commit = bundle
    if change == "manifest":
        digest = "b" * 64
    elif change == "source":
        commit = "b" * 40
    elif change == "payload":
        (directory / "backup.py").write_bytes(b"changed")
    elif change == "extra":
        (directory / "writer.pem").write_bytes(b"unexpected fixture credential")
    with pytest.raises(installer.Refused):
        installer.read_bundle(directory, digest, commit)


def test_missing_host_prerequisite_precedes_every_write_or_account_change(tmp_path, monkeypatch):
    target = tmp_path / "not-created"
    monkeypatch.setattr(installer, "CODE", target)
    commands = []
    monkeypatch.setattr(installer, "command", lambda args, **kwargs: commands.append(args))

    def missing_tools():
        raise installer.Refused("installed native PostgreSQL 16 tools required")

    monkeypatch.setattr(installer, "preflight", missing_tools)
    with pytest.raises(installer.Refused, match="PostgreSQL 16"):
        installer.install({}, "a" * 64, "b" * 40)
    assert not target.exists()
    assert commands == []


def test_new_file_refuses_existing_file_and_dangling_link(tmp_path):
    original = tmp_path / "owner-data"
    original.write_bytes(b"preserve")
    link = tmp_path / "dangling"
    link.symlink_to(tmp_path / "missing-target")
    for target in (original, link):
        with pytest.raises(FileExistsError):
            installer.write_new(target, b"replacement", 0o600)
    assert original.read_bytes() == b"preserve"
    assert link.is_symlink() and not link.exists()


@pytest.mark.parametrize("field,value", [("ActiveState", "active"), ("UnitFileState", "enabled"),
                                        ("LoadState", "not-found")])
def test_running_enabled_or_unloaded_unit_is_never_accepted(monkeypatch, field, value):
    properties = {"LoadState": "loaded", "ActiveState": "inactive", "UnitFileState": "static"}
    properties[field] = value
    monkeypatch.setattr(installer, "service_properties", lambda name: properties)
    with pytest.raises(installer.Refused, match="stopped and disabled"):
        installer.verify_stopped()


def test_dedicated_accounts_cannot_share_identity_or_inherit_groups(monkeypatch):
    users = {
        name: SimpleNamespace(pw_uid=800 + index, pw_gid=800 + index,
                              pw_shell="/usr/sbin/nologin", pw_dir="/nonexistent")
        for index, name in enumerate(installer.ACCOUNTS)
    }
    monkeypatch.setattr(installer.pwd, "getpwnam", users.__getitem__)
    monkeypatch.setattr(installer.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=users[name].pw_gid))
    monkeypatch.setattr(installer.os, "getgrouplist", lambda name, gid: [gid])
    installer.verify_accounts()
    monkeypatch.setattr(installer.os, "getgrouplist", lambda name, gid: [gid, 999])
    with pytest.raises(installer.Refused, match="account scope"):
        installer.verify_accounts()
    monkeypatch.setattr(installer.os, "getgrouplist", lambda name, gid: [gid])
    users[installer.ACCOUNTS[1]] = users[installer.ACCOUNTS[0]]
    with pytest.raises(installer.Refused, match="distinct"):
        installer.verify_accounts()


def test_successful_file_install_keeps_service_and_credential_activation_separate(tmp_path, monkeypatch):
    for constant, relative in (("CODE", "code"), ("CONFIG", "config"), ("UNITS", "units"),
                               ("LOGROTATE", "logrotate"), ("RECEIPT", "receipt.json")):
        monkeypatch.setattr(installer, constant, tmp_path / relative)
    installer.UNITS.mkdir()
    monkeypatch.setattr(installer, "preflight", lambda: None)
    monkeypatch.setattr(installer, "verify_accounts", lambda: None)
    directory_roots = (tmp_path / "state", tmp_path / "logs")
    for parent in directory_roots:
        parent.mkdir()
    monkeypatch.setattr(installer, "DIRECTORY_ROOTS", directory_roots)
    monkeypatch.setattr(installer, "parent_custody", lambda path: None)
    monkeypatch.setattr(installer.pwd, "getpwnam", lambda name: SimpleNamespace(
        pw_uid=os.getuid(), pw_gid=os.getgid()))
    monkeypatch.setattr(installer, "read_public", lambda path, limit: path.read_bytes())
    commands = []

    def fake_command(args, **kwargs):
        commands.append(args)
        if args[-1] == "--version":
            return b"wal-g v3.0.9"
        if args[:2] == ["systemctl", "show"]:
            return b"LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n"
        return b""

    monkeypatch.setattr(installer, "command", fake_command)
    contents = {name: b"public fixture\n" for name in installer.FILES}
    installer.install(contents, "a" * 64, "b" * 40)
    receipt = json.loads(installer.RECEIPT.read_text())
    assert receipt["status"] == "public_software_installed_services_stopped"
    assert receipt["credentials_installed"] is receipt["database_provisioned"] is False
    assert receipt["backup_activated"] is receipt["restore_qualified"] is False
    assert list((installer.CONFIG / "secrets").iterdir()) == []
    assert len(receipt["private_directories"]) == 4
    for parent in directory_roots:
        for account in installer.ACCOUNTS:
            path = parent / account
            metadata = path.stat()
            assert metadata.st_uid == os.getuid() and metadata.st_gid == os.getgid()
            assert stat.S_IMODE(metadata.st_mode) == 0o700
            assert list(path.iterdir()) == []
    assert not any(args[0] == "systemctl" and args[1] in {"start", "enable", "restart"}
                   for args in commands)
    assert [args for args in commands if args[:2] == ["systemctl", "daemon-reload"]]


@pytest.mark.parametrize("linked", [False, True])
def test_existing_private_directory_refused_before_any_directory_creation(tmp_path, monkeypatch, linked):
    roots = (tmp_path / "state", tmp_path / "logs")
    for parent in roots:
        parent.mkdir()
    existing = roots[1] / installer.ACCOUNTS[1]
    if linked:
        existing.symlink_to(tmp_path / "missing-owner-data")
    else:
        existing.mkdir()
        (existing / "owner-data").write_bytes(b"preserve")
    monkeypatch.setattr(installer, "DIRECTORY_ROOTS", roots)
    monkeypatch.setattr(installer, "parent_custody", lambda path: None)
    with pytest.raises(installer.Refused, match="existing installation"):
        installer.initialize_directories()
    assert list(roots[0].iterdir()) == []
    assert list(roots[1].iterdir()) == [existing]
    assert existing.is_symlink() if linked else (existing / "owner-data").read_bytes() == b"preserve"


@pytest.mark.parametrize("affected", [True, False])
def test_unit_warning_with_zero_exit_is_not_silently_accepted(monkeypatch, affected):
    name = "cosmabot-backup-receive.service" if affected else "snapd.service"
    diagnostic = f"/etc/systemd/system/{name}:23: Unknown key name, ignoring.\n".encode()
    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=b"", stderr=diagnostic))
    if affected:
        with pytest.raises(installer.Refused, match="unit diagnostics"):
            installer.command(["systemd-analyze", "verify"], reject_diagnostics_for=installer.UNIT_NAMES)
    else:
        assert installer.command(["systemd-analyze", "verify"],
                                 reject_diagnostics_for=installer.UNIT_NAMES) == b""
