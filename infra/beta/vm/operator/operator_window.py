#!/usr/bin/python3 -I
"""One reviewed SSH transfer/forwarding window; no cloud, sudo or Docker access."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import ipaddress
import json
import os
import platform
import pwd
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/var/lib/cosmabot-operator")
HELPER = Path("/usr/local/libexec/cosmabot-operator-window.py")
SSH_DIR = Path("/etc/ssh/sshd_config.d")
UNIT_DIR = Path("/etc/systemd/system")
PROC = Path("/proc")
VM_NAME = "vm-cosmabot-staging-eus2-lab01"
MAX_BYTES = 8 * 1024**3
MIN_FREE = 16 * 1024**3
ROOT_UID = 0


class Refused(Exception):
    pass


def require(condition):
    if not condition:
        raise Refused("Operator window refused; inspect the named public configuration")


def run(argv, allowed=(0,)):
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode not in allowed:
        operation = {
            "/usr/sbin/useradd": "create-account",
            "/usr/sbin/usermod": "lock-account",
            "/usr/sbin/sshd": "verify-sshd",
            "systemctl": "manage-units",
        }.get(argv[0], "host-command")
        print(f"Operator operation failed: {operation}; exit={result.returncode}", file=sys.stderr)
    require(result.returncode in allowed)
    return result


def private_read(path, owner=None, modes=(0o400, 0o600, 0o444), maximum=16384):
    owner = ROOT_UID if owner is None else owner
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == owner and info.st_nlink == 1)
        require(stat.S_IMODE(info.st_mode) in modes and info.st_size <= maximum)
        return stream.read(maximum + 1)


def write_new(path, data, mode=0o444):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def directory(path, mode=0o755, *, new=False):
    try:
        path.mkdir(mode=mode)
        path.chmod(mode)
    except FileExistsError:
        require(not new)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == ROOT_UID)
    require(stat.S_IMODE(info.st_mode) == mode and path.resolve() == path)


def window_path(window):
    require(isinstance(window, str) and re.fullmatch(r"[0-9a-f]{12}", window))
    return BASE / window


def boot_id():
    return (PROC / "sys/kernel/random/boot_id").read_text().strip()


def parse_manifest(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    require(
        set(value)
        == {
            "version",
            "window",
            "vm_name",
            "source_ipv4",
            "vault_host",
            "acr_host",
            "expires_at",
            "public_key",
        }
    )
    require(type(value["version"]) is int and value["version"] == 1 and value["vm_name"] == VM_NAME)
    window_path(value["window"])
    source = ipaddress.IPv4Address(value["source_ipv4"])
    require(str(source) == value["source_ipv4"] and source.is_global and not source.is_multicast)
    require(
        re.fullmatch(r"[a-z0-9][a-z0-9-]{1,22}[a-z0-9]\.vault\.azure\.net", value["vault_host"])
    )
    require(re.fullmatch(r"[a-z0-9]{5,50}\.azurecr\.io", value["acr_host"]))
    expiry = (
        datetime.strptime(value["expires_at"], "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )
    require(120 <= expiry - time.time() <= 10800)
    parts = value["public_key"].split()
    require(len(parts) in (2, 3) and parts[0] == "ssh-ed25519" and "\n" not in value["public_key"])
    decoded = base64.b64decode(parts[1], validate=True)
    require(decoded[:19] == b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" and len(decoded) == 51)
    value["public_key"] = " ".join(parts[:2])
    value.update(
        username="cmop" + value["window"],
        expiry=expiry,
        boot_id=boot_id(),
        monotonic_deadline=time.monotonic() + expiry - time.time(),
        status="installing",
        uid=None,
    )
    return value


def save_state(state):
    folder = window_path(state["window"])
    fd, name = tempfile.mkstemp(prefix=".state-", dir=folder)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o444)
            stream.write((json.dumps(state, sort_keys=True) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, folder / "state.json")
    finally:
        temporary.unlink(missing_ok=True)


def load_state(window):
    folder = window_path(window)
    require(BASE.resolve() == BASE and folder.resolve() == folder)
    require(BASE.stat().st_uid == ROOT_UID and folder.stat().st_uid == ROOT_UID)
    require(
        stat.S_IMODE(BASE.stat().st_mode) == 0o755 and stat.S_IMODE(folder.stat().st_mode) == 0o755
    )
    state = json.loads(private_read(folder / "state.json", modes=(0o444,)))
    require(state["window"] == window and state["username"] == "cmop" + window)
    return state


def active(state):
    return (
        state["status"] == "active"
        and state["boot_id"] == boot_id()
        and time.time() < state["expiry"]
        and time.monotonic() < state["monotonic_deadline"]
    )


def key_line(state):
    stamp = datetime.fromtimestamp(state["expiry"], timezone.utc).strftime("%Y%m%d%H%M%SZ")
    return (
        f'from="{state["source_ipv4"]}/32",restrict,port-forwarding,'
        f'permitopen="{state["vault_host"]}:443",permitopen="{state["acr_host"]}:443",'
        f'expiry-time="{stamp}" {state["public_key"]} cosmabot-window-{state["window"]}\n'
    )


def ssh_config(state):
    return f"""# Public, scoped operator window {state["window"]}
Match User {state["username"]}
    AuthenticationMethods publickey
    PubkeyAuthentication yes
    PubkeyAcceptedAlgorithms ssh-ed25519
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthorizedKeysFile none
    AuthorizedKeysCommand {HELPER} key %u
    AuthorizedKeysCommandUser root
    AllowTcpForwarding local
    AllowStreamLocalForwarding no
    PermitOpen {state["vault_host"]}:443 {state["acr_host"]}:443
    PermitListen none
    PermitTTY no
    PermitUserRC no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    GatewayPorts no
    ForceCommand {HELPER} session {state["window"]}
Match all
"""


def unit_files(state):
    name = "cosmabot-operator-" + state["window"]
    service = f"""[Unit]
Description=Close CosmaBot operator window {state["window"]}
After=local-fs.target
Before=ssh.service sshd.service ssh.socket
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I {HELPER} close {state["window"]}
[Install]
WantedBy=multi-user.target
"""
    expiry = datetime.fromtimestamp(state["expiry"], timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    timer = f"""[Unit]
Description=Expire CosmaBot operator window {state["window"]}
[Timer]
OnCalendar={expiry}
OnBootSec={max(1, int(state["monotonic_deadline"]))}s
AccuracySec=1s
RandomizedDelaySec=0
Persistent=yes
Unit={name}.service
[Install]
WantedBy=timers.target
"""
    return {
        SSH_DIR / ("00-" + name + ".conf"): ssh_config(state),
        UNIT_DIR / (name + ".service"): service,
        UNIT_DIR / (name + ".timer"): timer,
    }


def verify_sshd(state):
    run(["/usr/sbin/sshd", "-t"])
    result = run(
        [
            "/usr/sbin/sshd",
            "-T",
            "-C",
            f"user={state['username']},host={VM_NAME},addr={state['source_ipv4']}",
        ]
    )
    entries = [line.split(" ", 1) for line in result.stdout.splitlines()]
    config = dict(entries)
    # Inspect every AcceptEnv entry: sshd may emit multiple lines for this option.
    # Loader/shell variables take effect before the isolated Python entry point.
    require(
        all(
            name in {"LANG", "LC_*"}
            for key, value in entries
            if key == "acceptenv"
            for name in value.split()
        )
    )
    expected = {
        "authenticationmethods": "publickey",
        "pubkeyauthentication": "yes",
        "pubkeyacceptedalgorithms": "ssh-ed25519",
        "passwordauthentication": "no",
        "kbdinteractiveauthentication": "no",
        "authorizedkeysfile": "none",
        "authorizedkeyscommand": f"{HELPER} key %u",
        "authorizedkeyscommanduser": "root",
        "allowtcpforwarding": "local",
        "allowstreamlocalforwarding": "no",
        "permitlisten": "none",
        "permittty": "no",
        "permituserrc": "no",
        "permituserenvironment": "no",
        "allowagentforwarding": "no",
        "x11forwarding": "no",
        "permittunnel": "no",
        "gatewayports": "no",
        "forcecommand": f"{HELPER} session {state['window']}",
        "permitopen": f"{state['vault_host']}:443 {state['acr_host']}:443",
    }
    require(all(config.get(key) == value for key, value in expected.items()))
    require(config.get("allowusers") in (None, state["username"]))
    require(config.get("allowgroups") in (None, state["username"]))
    require(not config.get("denyusers") and not config.get("denygroups"))


def account_matches(state):
    account = pwd.getpwnam(state["username"])
    require(account.pw_uid == state["uid"] and account.pw_uid >= 1000)
    require(account.pw_gecos == "cosmabot-window-" + state["window"])
    require(account.pw_dir == str(window_path(state["window"])))
    require(set(os.getgrouplist(account.pw_name, account.pw_gid)) == {account.pw_gid})
    return account


def process_matches(pid, state):
    try:
        folder = PROC / str(pid)
        status = dict(
            line.split(":", 1)
            for line in (folder / "status").read_text().splitlines()
            if ":" in line
        )
        if status["State"].strip().startswith("Z"):
            return False
        uids = [int(value) for value in status["Uid"].split()]
        if state["uid"] in uids:
            return True
        title = (folder / "cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
        executable = os.readlink(folder / "exe")
        return (
            uids == [0, 0, 0, 0]
            and executable in {"/usr/sbin/sshd", "/usr/lib/openssh/sshd-session"}
            and title
            in {f"sshd: {state['username']} [priv]", f"sshd-session: {state['username']} [priv]"}
        )
    except FileNotFoundError:
        return False


def kill_sessions(state):
    # pidfds bind the signal to the inspected process, avoiding PID-reuse races.
    for _ in range(3):
        targets = [
            int(path.name)
            for path in PROC.iterdir()
            if path.name.isdigit() and process_matches(int(path.name), state)
        ]
        if not targets:
            return
        for pid in targets:
            try:
                fd = os.pidfd_open(pid)
                try:
                    if process_matches(pid, state):
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                finally:
                    os.close(fd)
            except ProcessLookupError:
                pass
        time.sleep(0.1)
    require(
        not any(
            path.name.isdigit() and process_matches(int(path.name), state)
            for path in PROC.iterdir()
        )
    )


def close(window):
    state = load_state(window)
    require(isinstance(state["uid"], int) and state["uid"] >= 1000)
    account_matches(state)
    state["status"] = "closing"
    errors = []
    try:
        save_state(state)  # Deny new auth before attempting any external cleanup.
    except Exception:
        errors.append("state")
    key = window_path(window) / "authorized_key"
    try:
        if key.exists() or key.is_symlink():
            require(private_read(key) == key_line(state).encode())
            key.unlink()
    except Exception:
        errors.append("key")
    try:
        run(["/usr/sbin/usermod", "--lock", "--expiredate", "1970-01-02", state["username"]])
    except Exception:
        errors.append("lock")
    try:
        kill_sessions(state)
    except Exception:
        errors.append("sessions")
    require(not errors)
    state["status"] = "closed"
    save_state(state)
    return state


def install(raw, expected_sha):
    require(hashlib.sha256(raw).hexdigest() == expected_sha)
    state = parse_manifest(raw)
    require(Path(__file__).resolve() == HELPER and platform.node() == VM_NAME)
    require(HELPER.stat().st_uid == ROOT_UID and stat.S_IMODE(HELPER.stat().st_mode) == 0o755)
    try:
        pwd.getpwnam(state["username"])
    except KeyError:
        pass
    else:
        raise Refused("Window account already exists")
    directory(BASE)
    folder = window_path(state["window"])
    directory(folder, new=True)
    save_state(state)
    try:
        run(
            [
                "/usr/sbin/useradd",
                "--user-group",
                "--no-create-home",
                "--shell",
                "/bin/sh",
                "--home-dir",
                str(folder),
                "--comment",
                "cosmabot-window-" + state["window"],
                state["username"],
            ]
        )
        state["uid"] = pwd.getpwnam(state["username"]).pw_uid
        account = account_matches(state)
        save_state(state)
        incoming = folder / "incoming"
        incoming.mkdir(mode=0o700)
        os.chown(incoming, account.pw_uid, account.pw_gid)
        write_new(folder / "authorized_key", key_line(state).encode(), 0o400)
        files = unit_files(state)
        state["files"] = {
            str(path): hashlib.sha256(text.encode()).hexdigest() for path, text in files.items()
        }
        save_state(state)
        for path, text in files.items():
            write_new(path, text.encode(), 0o644)
        verify_sshd(state)
        run(["systemctl", "daemon-reload"])
        name = "cosmabot-operator-" + state["window"]
        # Enable boot closure, but do not start it during this installation.
        run(["systemctl", "enable", name + ".service"])
        run(["systemctl", "enable", "--now", name + ".timer"])
        run(["systemctl", "is-enabled", "--quiet", name + ".service"])
        run(["systemctl", "is-active", "--quiet", name + ".timer"])
        run(["systemctl", "reload", "ssh.service"])
        require(time.time() < state["expiry"] - 5 and boot_id() == state["boot_id"])
        require(time.monotonic() < state["monotonic_deadline"] - 5)
        require(load_state(state["window"])["status"] == "installing")
        state["status"] = "active"  # The key command refuses until every check passed.
        save_state(state)
        return state
    except Exception:
        if isinstance(state.get("uid"), int):
            try:
                close(state["window"])
            except Exception:
                pass  # Installing/closing states remain ineligible for authentication.
        raise


def receive(window, command, stream):
    state = load_state(window)
    require(active(state) and os.geteuid() == state["uid"])
    args = shlex.split(command)
    require(len(args) == 4 and args[0] == "receive")
    name, length, expected = args[1:]
    require(re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", name) and re.fullmatch(r"[0-9]{1,11}", length))
    require(re.fullmatch(r"[a-f0-9]{64}", expected))
    count = int(length)
    require(0 < count <= MAX_BYTES)
    folder = window_path(window) / "incoming"
    require(folder.resolve() == folder and folder.stat().st_uid == state["uid"])
    require(stat.S_IMODE(folder.stat().st_mode) == 0o700)
    lock = os.open(folder / ".upload.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == state["uid"] and info.st_nlink == 1)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        used = 0
        for path in folder.iterdir():
            info = path.lstat()
            require(
                stat.S_ISREG(info.st_mode) and info.st_uid == state["uid"] and info.st_nlink == 1
            )
            used += info.st_size
        space = os.statvfs(folder)
        require(used + count <= MAX_BYTES and space.f_bavail * space.f_frsize - count >= MIN_FREE)
        destination = folder / name
        require(not destination.exists())
        temporary = folder / (".partial-" + name)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            digest = hashlib.sha256()
            remaining = count
            with os.fdopen(fd, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                while remaining:
                    require(active(state))
                    chunk = stream.read(min(1024 * 1024, remaining))
                    require(bool(chunk))
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                require(not stream.read(1) and digest.hexdigest() == expected and active(state))
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, destination, follow_symlinks=False)  # Exclusive final publication.
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        os.close(lock)


def purge(window):
    state = close(window)
    folder = window_path(window)
    incoming = folder / "incoming"
    for path in incoming.iterdir():
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == state["uid"] and info.st_nlink == 1)
    for path in incoming.iterdir():
        path.unlink()
    incoming.rmdir()
    # Keep the locked account, boot/expiry units and small public tombstone. No UID reuse.
    state["spool_purged"] = True
    save_state(state)


def authorized_key(username):
    require(re.fullmatch(r"cmop[0-9a-f]{12}", username))
    state = load_state(username[4:])
    require(active(state))
    account_matches(state)
    key = private_read(window_path(state["window"]) / "authorized_key")
    require(key == key_line(state).encode())
    return key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "key", "session", "close", "purge"))
    parser.add_argument("value")
    parser.add_argument("--sha256")
    args = parser.parse_args()
    require(platform.system() == "Linux")
    if args.action == "session":
        receive(args.value, os.environ.get("SSH_ORIGINAL_COMMAND", ""), sys.stdin.buffer)
        print('{"status":"received"}')
        return
    require(os.geteuid() == ROOT_UID)
    if args.action == "key":
        sys.stdout.buffer.write(authorized_key(args.value))
    elif args.action == "install":
        state = install(private_read(Path(args.value), modes=(0o400, 0o600)), args.sha256)
        print(
            json.dumps(
                {
                    "status": "active",
                    "username": state["username"],
                    "expires_at": state["expires_at"],
                }
            )
        )
    elif args.action == "close":
        close(args.value)
        print('{"status":"closed"}')
    else:
        purge(args.value)
        print('{"status":"closed_spool_purged"}')


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Operator window refused; no values emitted", file=sys.stderr)
        raise SystemExit(1) from None
