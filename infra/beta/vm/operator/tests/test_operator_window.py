"""Local fixtures only: no host accounts, SSH daemon, cloud or real credentials."""

import base64
import hashlib
import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "operator_window.py"
SPEC = importlib.util.spec_from_file_location("operator_window", SOURCE)
op = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(op)
WINDOW = "012345abcdef"


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(op, "ROOT_UID", os.getuid())
    for name in ("BASE", "SSH_DIR", "UNIT_DIR", "PROC"):
        path = tmp_path / name.lower()
        path.mkdir(mode=0o755)
        path.chmod(0o755)
        monkeypatch.setattr(op, name, path)
    boot = op.PROC / "sys/kernel/random"
    boot.mkdir(parents=True)
    (boot / "boot_id").write_text("synthetic-boot-one")
    monkeypatch.setattr(op.time, "time", lambda: 1800000000.0)
    monkeypatch.setattr(op.time, "monotonic", lambda: 100.0)
    public = base64.b64encode(
        b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes(range(32))
    ).decode()
    manifest = {
        "version": 1,
        "window": WINDOW,
        "vm_name": op.VM_NAME,
        "source_ipv4": "1.2.3.4",
        "vault_host": "synthetic-vault.vault.azure.net",
        "acr_host": "syntheticregistry.azurecr.io",
        "expires_at": datetime.fromtimestamp(1800000600, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "public_key": "ssh-ed25519 " + public + " synthetic-test-only",
    }
    return manifest


@pytest.mark.parametrize(
    "change",
    [
        {"source_ipv4": "0.0.0.0/0"},
        {"source_ipv4": "127.0.0.1"},
        {"vault_host": "evil.example"},
        {"acr_host": "syntheticregistry.azurecr.io:443\nMatch all"},
        {"window": "../escape"},
        {"public_key": "-----BEGIN OPENSSH PRIVATE KEY-----"},
        {"expires_at": "2099-01-01T00:00:00Z"},
    ],
)
def test_manifest_refuses_widened_or_unbounded_inputs(local, change):
    local.update(change)
    with pytest.raises((op.Refused, ValueError)):
        op.parse_manifest(json.dumps(local))


def prepared(local, *, uid=1501):
    state = op.parse_manifest(json.dumps(local))
    state.update(status="active", uid=uid)
    op.directory(op.window_path(WINDOW), new=True)
    op.save_state(state)
    op.write_new(op.window_path(WINDOW) / "authorized_key", op.key_line(state).encode(), 0o400)
    return state


def test_key_denied_at_expiry_on_reboot_and_during_failed_setup(local, monkeypatch):
    state = prepared(local)
    monkeypatch.setattr(op, "account_matches", lambda _: None)
    assert op.authorized_key(state["username"]).startswith(b'from="1.2.3.4/32",restrict,')
    for change in (
        {"status": "installing"},
        {"boot_id": "another-boot"},
        {"expiry": 1},
        {"monotonic_deadline": 99},
    ):
        modified = state | change
        op.save_state(modified)
        with pytest.raises(op.Refused):
            op.authorized_key(state["username"])
    assert (op.window_path(WINDOW) / "authorized_key").exists()  # Gate works before removal.


@pytest.mark.parametrize(
    ("environment_config", "refused"),
    [
        ("", False),
        ("AcceptEnv LANG LC_*\n", False),
        ("AcceptEnv PYTHONPATH\n", True),
        ("AcceptEnv LD_PRELOAD\nAcceptEnv LANG LC_*\n", True),
        ("AcceptEnv *\n", True),
        ("PermitUserEnvironment yes\n", True),
    ],
)
def test_actual_sshd_parser_proves_forwarding_command_and_environment_restrictions(
    local, tmp_path, monkeypatch, environment_config, refused
):
    sshd = shutil.which("sshd") or "/usr/sbin/sshd"
    keygen = shutil.which("ssh-keygen")
    if not Path(sshd).exists() or keygen is None:
        pytest.skip("OpenSSH configuration parser not installed")
    key = tmp_path / "synthetic-host-key"
    subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    state = op.parse_manifest(json.dumps(local))
    config = tmp_path / "sshd_config"
    config.write_text(f"HostKey {key}\nUsePAM no\n" + environment_config + op.ssh_config(state))
    result = subprocess.run(
        [
            sshd,
            "-T",
            "-f",
            str(config),
            "-C",
            f"user={state['username']},host=synthetic,addr=1.2.3.4",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    values = dict(line.split(" ", 1) for line in result.stdout.splitlines())
    assert values["allowtcpforwarding"] == "local" and values["permitlisten"] == "none"
    assert (
        values["permitopen"]
        == "synthetic-vault.vault.azure.net:443 syntheticregistry.azurecr.io:443"
    )
    assert values["forcecommand"].endswith(" session " + WINDOW)
    assert (
        values["authorizedkeysfile"] == "none"
        and values["pubkeyacceptedalgorithms"] == "ssh-ed25519"
    )
    assert all(
        values[k] == "no"
        for k in (
            "permittty",
            "permituserrc",
            "allowagentforwarding",
            "x11forwarding",
            "allowstreamlocalforwarding",
        )
    )

    def local_sshd(argv, allowed=(0,)):
        result = subprocess.run(
            [sshd, "-f", str(config), *argv[1:]], capture_output=True, text=True
        )
        assert result.returncode in allowed, result.stderr
        return result

    monkeypatch.setattr(op, "run", local_sshd)
    if refused:
        with pytest.raises(op.Refused):
            op.verify_sshd(state)
    else:
        op.verify_sshd(state)


def test_executable_and_root_entry_points_ignore_spool_python_modules(tmp_path, local):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    marker = tmp_path / "imported-untrusted-module"
    (incoming / "json.py").write_text(f"open({str(marker)!r}, 'w').write('executed')\n")
    environment = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(incoming)}

    def invoke(argv):
        result = subprocess.run(
            [*argv, "--help"], cwd=incoming, env=environment, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    # Establish that this harmless fixture actually exercises the former injection.
    invoke([sys.executable, str(SOURCE)])
    assert marker.exists()
    marker.unlink()
    for entry in ([str(SOURCE)], ["/usr/bin/python3", "-I", str(SOURCE)]):
        invoke(entry)
        assert not marker.exists()

    state = op.parse_manifest(json.dumps(local))
    service = op.unit_files(state)[op.UNIT_DIR / ("cosmabot-operator-" + WINDOW + ".service")]
    assert f"ExecStart=/usr/bin/python3 -I {op.HELPER} close {WINDOW}\n" in service
    # Both sshd commands execute the installed file, honoring the tested shebang.
    config = op.ssh_config(state)
    assert f"AuthorizedKeysCommand {op.HELPER} key %u\n" in config
    assert f"ForceCommand {op.HELPER} session {WINDOW}\n" in config


@pytest.mark.parametrize("timer_failure", [False, True])
def test_install_requires_live_timer_before_key_activation(local, monkeypatch, timer_failure):
    monkeypatch.setattr(op, "HELPER", SOURCE)
    monkeypatch.setattr(op.platform, "node", lambda: op.VM_NAME)
    monkeypatch.setattr(op.os, "chown", lambda *_: None)
    account = SimpleNamespace(
        pw_name="cmop" + WINDOW,
        pw_uid=1501,
        pw_gid=1501,
        pw_gecos="cosmabot-window-" + WINDOW,
        pw_dir=str(op.window_path(WINDOW)),
    )
    created = False
    calls = []

    def lookup(_):
        if not created:
            raise KeyError()
        return account

    def command(argv, allowed=(0,)):
        nonlocal created
        calls.append(argv)
        if argv[0].endswith("useradd"):
            comment = argv[argv.index("--comment") + 1]
            # Linux shadow's VALID() rejects these passwd field delimiters.
            assert not any(character in comment for character in ":\n")
            assert comment == account.pw_gecos
            created = True
        if argv[:3] == ["systemctl", "enable", "--now"]:
            assert op.load_state(WINDOW)["status"] == "installing"
            if timer_failure:
                raise op.Refused()
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(op.pwd, "getpwnam", lookup)
    monkeypatch.setattr(op.os, "getgrouplist", lambda *_: [1501])
    monkeypatch.setattr(op, "run", command)
    monkeypatch.setattr(op, "verify_sshd", lambda _: None)
    monkeypatch.setattr(op, "kill_sessions", lambda _: calls.append(["kill-window-sessions"]))
    raw = json.dumps(local).encode()
    if timer_failure:
        with pytest.raises(op.Refused):
            op.install(raw, hashlib.sha256(raw).hexdigest())
        assert op.load_state(WINDOW)["status"] == "closed"
        assert not (op.window_path(WINDOW) / "authorized_key").exists()
        assert ["kill-window-sessions"] in calls
        assert any(argv[0].endswith("usermod") for argv in calls)
    else:
        op.install(raw, hashlib.sha256(raw).hexdigest())
        assert op.load_state(WINDOW)["status"] == "active"
        assert op.authorized_key(account.pw_name)
        timer = (op.UNIT_DIR / ("cosmabot-operator-" + WINDOW + ".timer")).read_text()
        assert "OnBootSec=700s" in timer and "OnCalendar=" in timer


def test_failed_host_command_reports_only_fixed_operation_and_exit_code(monkeypatch, capsys):
    sensitive = "synthetic-sensitive-value-must-not-appear"
    monkeypatch.setattr(
        op.subprocess,
        "run",
        lambda *_, **__: SimpleNamespace(returncode=3, stdout=sensitive, stderr=sensitive),
    )
    with pytest.raises(op.Refused):
        op.run(["/usr/sbin/useradd", "--comment", sensitive, sensitive])
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Operator operation failed: create-account; exit=3\n"


def test_session_cleanup_kills_only_window_uid_and_its_exact_privileged_monitor(local, monkeypatch):
    state = op.parse_manifest(json.dumps(local)) | {"uid": 1501}

    def process(pid, uid, title, executable="/usr/sbin/sshd"):
        path = op.PROC / str(pid)
        path.mkdir()
        (path / "status").write_text(f"State:\tS (sleeping)\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
        (path / "cmdline").write_bytes(title.encode() + b"\0")
        (path / "exe").symlink_to(executable)

    process(101, 1501, "sshd: window@notty")
    process(102, 0, "sshd: cmop" + WINDOW + " [priv]")
    process(103, 1502, "unrelated-process")
    process(104, 0, "sshd: cosmabotops [priv]")
    process(105, 0, "sshd: cmop" + WINDOW + " [priv]", "/untrusted/binary")
    killed = []
    monkeypatch.setattr(op.os, "pidfd_open", lambda pid: pid, raising=False)
    monkeypatch.setattr(op.os, "close", lambda _: None)

    def kill(pid, sig):
        assert sig == signal.SIGKILL
        killed.append(pid)
        (op.PROC / str(pid) / "status").write_text("State:\tZ (zombie)\nUid:\t0\t0\t0\t0\n")

    monkeypatch.setattr(op.signal, "pidfd_send_signal", kill, raising=False)
    monkeypatch.setattr(op.time, "sleep", lambda _: None)
    op.kill_sessions(state)
    assert sorted(killed) == [101, 102]


def test_close_attempts_session_kill_even_when_account_lock_fails(local, monkeypatch):
    prepared(local)
    monkeypatch.setattr(op, "account_matches", lambda _: None)

    def fail(_):
        raise op.Refused()

    monkeypatch.setattr(op, "run", fail)
    calls = []
    monkeypatch.setattr(op, "kill_sessions", lambda _: calls.append("killed"))
    with pytest.raises(op.Refused):
        op.close(WINDOW)
    assert calls == ["killed"] and op.load_state(WINDOW)["status"] == "closing"
    assert not (op.window_path(WINDOW) / "authorized_key").exists()


def test_pid_reuse_cannot_signal_an_unrelated_process(local, monkeypatch):
    state = op.parse_manifest(json.dumps(local)) | {"uid": 1501}
    process = op.PROC / "101"
    process.mkdir()
    owner = [True]
    monkeypatch.setattr(op, "process_matches", lambda *_: owner[0])

    def open_reused_pid(_):
        owner[0] = False
        return 101

    monkeypatch.setattr(op.os, "pidfd_open", open_reused_pid, raising=False)
    monkeypatch.setattr(op.os, "close", lambda _: None)
    calls = []
    monkeypatch.setattr(
        op.signal, "pidfd_send_signal", lambda *_: calls.append("unsafe"), raising=False
    )
    monkeypatch.setattr(op.time, "sleep", lambda _: None)
    op.kill_sessions(state)
    assert not calls


@pytest.mark.parametrize(
    "fault", [None, "traversal", "existing", "extra", "digest", "quota", "symlink"]
)
def test_bounded_exclusive_spool_transfer(local, monkeypatch, fault):
    prepared(local, uid=os.geteuid())
    incoming = op.window_path(WINDOW) / "incoming"
    incoming.mkdir(mode=0o700)
    monkeypatch.setattr(op, "MIN_FREE", 0)
    monkeypatch.setattr(op, "MAX_BYTES", 100)
    body = b"synthetic"
    name = "image.tar"
    digest = hashlib.sha256(body).hexdigest()
    if fault == "traversal":
        name = "../escape"
    elif fault == "existing":
        (incoming / name).write_bytes(b"retain")
    elif fault == "extra":
        body += b"extra"
    elif fault == "digest":
        digest = "0" * 64
    elif fault == "quota":
        monkeypatch.setattr(op, "MAX_BYTES", 2)
    elif fault == "symlink":
        (incoming / name).symlink_to(op.window_path(WINDOW) / "authorized_key")
    command = f"receive {name} 9 {digest}"
    if fault:
        with pytest.raises((op.Refused, FileExistsError)):
            op.receive(WINDOW, command, io.BytesIO(body))
        if fault == "existing":
            assert (incoming / name).read_bytes() == b"retain"
        assert not list(incoming.glob(".partial-*"))
    else:
        op.receive(WINDOW, command, io.BytesIO(body))
        assert (incoming / name).read_bytes() == body
        assert (incoming / name).stat().st_mode & 0o777 == 0o600
