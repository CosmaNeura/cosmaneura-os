#!/usr/bin/python3
"""Install a reviewed public backup bundle on the separate VM; never activate it."""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import platform
import pwd
import re
import stat
import subprocess
from pathlib import Path

WALG_SHA256 = 'd6795c663894d836ba20840bffe8970aed81bbe25d3151bd4951f6f9c362def9'
CODE = Path('/opt/cosmabot/backup')
CONFIG = Path('/etc/cosmabot/backup')
UNITS = Path('/etc/systemd/system')
LOGROTATE = Path('/etc/logrotate.d/cosmabot-backup')
RECEIPT = Path('/etc/cosmabot/backup-install.json')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
ACCOUNTS = ('cosmabot-backup', 'cosmabot-restore')
UNIT_NAMES = (
    'cosmabot-backup-receive.service', 'cosmabot-backup-job@.service',
    'cosmabot-restore.service', 'cosmabot-backup.timer',
    'cosmabot-backup-status.timer', 'cosmabot-backup-switch.timer',
)
FILES = frozenset((*UNIT_NAMES, 'backup.py', 'restore.py', 'wal-g',
                   'walg.json', 'resolv.conf', 'logrotate.conf'))


class Refused(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Refused(message)


def read_public(path: Path, limit: int) -> bytes:
    require(path.is_absolute() and path.resolve() == path, 'canonical public input required')
    for parent in path.parents:
        metadata = parent.stat()
        require(metadata.st_uid == 0 and not metadata.st_mode & 0o022,
                'public input parent custody')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0
                and metadata.st_nlink == 1 and not metadata.st_mode & 0o022
                and metadata.st_size <= limit, 'public input custody')
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'public input size')
    return raw


def read_bundle(directory: Path, expected_sha256: str, source_commit: str) -> dict[str, bytes]:
    require(re.fullmatch(r'[a-f0-9]{64}', expected_sha256) is not None
            and re.fullmatch(r'[a-f0-9]{40}', source_commit) is not None, 'review binding')
    raw = read_public(directory / 'bundle.json', 16384)
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'reviewed bundle digest')
    manifest = json.loads(raw)
    require(type(manifest) is dict and set(manifest) == {'version', 'source_commit', 'files'}
            and type(manifest['version']) is int and manifest['version'] == 1
            and manifest['source_commit'] == source_commit
            and type(manifest['files']) is dict and set(manifest['files']) == FILES,
            'closed public bundle manifest')
    require({p.name for p in directory.iterdir()} == FILES | {'bundle.json'},
            'unexpected bundle files')
    contents = {}
    for name in sorted(FILES):
        digest = manifest['files'][name]
        require(isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest) is not None,
                'public file digest')
        data = read_public(directory / name, 70 * 1024 * 1024 if name == 'wal-g' else 256 * 1024)
        require(hashlib.sha256(data).hexdigest() == digest, 'public bundle changed')
        contents[name] = data
    binary = contents['wal-g']
    require(hashlib.sha256(binary).hexdigest() == WALG_SHA256 and len(binary) == 61326184
            and binary[:6] == b'\x7fELF\x02\x01'
            and int.from_bytes(binary[18:20], 'little') == 62, 'pinned native WAL-G required')
    require(contents['walg.json'] == b'{}\n', 'closed WAL-G configuration')
    return contents


def command(argv: list[str], *, timeout: int = 30,
            reject_diagnostics_for: tuple[str, ...] = ()) -> bytes:
    result = subprocess.run(argv, env=ENV, stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=timeout, check=False)
    require(result.returncode == 0, 'host command failed; installation not qualified')
    require(not any(name.encode() in result.stdout + result.stderr for name in reject_diagnostics_for),
            'backup unit diagnostics require review')
    return result.stdout


def absent(path: Path) -> None:
    require(not path.exists() and not path.is_symlink(), 'existing installation requires review')


def parent_custody(path: Path) -> None:
    require(path.resolve() == path, 'canonical installation path required')
    for parent in (path, *path.parents):
        metadata = parent.stat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0
                and not metadata.st_mode & 0o022, 'installation parent custody')


def preflight() -> None:
    require(os.geteuid() == 0 and platform.system() == 'Linux'
            and platform.machine() == 'x86_64'
            and platform.node() == 'vm-cosmabot-staging-eus2-lab01', 'exact staging host required')
    release_file = Path('/etc/os-release').resolve()
    require(release_file in {Path('/etc/os-release'), Path('/usr/lib/os-release')},
            'standard OS release path required')
    release = dict(line.split('=', 1) for line in read_public(release_file, 8192)
                   .decode().splitlines() if '=' in line)
    require(release.get('ID', '').strip('"') == 'ubuntu'
            and release.get('VERSION_ID', '').strip('"') == '22.04', 'Ubuntu 22.04 required')
    active = read_public(Path('/etc/cosmabot/active-release'), 256).decode()
    require(re.fullmatch(r'RELEASE_DIR=/opt/cosmabot/releases/stg-owner-20260925-r[1-9][0-9]*\n',
                         active) is not None, 'separate staging release required')
    for parent in (CODE.parent, CONFIG.parent, UNITS, LOGROTATE.parent):
        parent_custody(parent)
    for path in (CODE, CONFIG, LOGROTATE, RECEIPT, *(UNITS / name for name in UNIT_NAMES)):
        absent(path)
    for name in service_names():
        properties = service_properties(name)
        require(properties.get('LoadState') == 'not-found'
                and properties.get('ActiveState') == 'inactive'
                and not properties.get('UnitFileState'), 'existing backup unit requires review')
    for account in ACCOUNTS:
        try:
            pwd.getpwnam(account)
        except KeyError:
            pass
        else:
            raise Refused('existing backup account requires review')
        try:
            grp.getgrnam(account)
        except KeyError:
            pass
        else:
            raise Refused('existing backup group requires review')
        absent(Path('/var/lib') / account)
        absent(Path('/var/log') / account)
    for executable in ('psql', 'postgres', 'pg_controldata'):
        path = Path('/usr/lib/postgresql/16/bin') / executable
        require(path.is_file() and not path.is_symlink(), 'installed native PostgreSQL 16 tools required')
        read_public(path, 32 * 1024 * 1024)
        require(re.search(rb'\(PostgreSQL\) 16\.[0-9]+', command([str(path), '--version']))
                is not None, 'installed native PostgreSQL 16 tools required')
    for executable in ('/usr/sbin/useradd', '/usr/sbin/groupadd', '/usr/sbin/nologin',
                       '/usr/bin/systemctl', '/usr/bin/systemd-analyze', '/usr/bin/openssl'):
        require(os.access(executable, os.X_OK), 'missing host prerequisite')


def write_new(path: Path, raw: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, 'wb') as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def verify_accounts() -> None:
    identities = []
    for account in ACCOUNTS:
        user = pwd.getpwnam(account)
        group = grp.getgrnam(account)
        require(user.pw_uid != 0 and user.pw_gid == group.gr_gid != 0
                and user.pw_shell == '/usr/sbin/nologin' and user.pw_dir == '/nonexistent'
                and set(os.getgrouplist(account, user.pw_gid)) == {user.pw_gid},
                'dedicated account scope')
        identities.append((user.pw_uid, user.pw_gid))
    require(identities[0][0] != identities[1][0] and identities[0][1] != identities[1][1],
            'distinct backup and restore accounts required')


def service_names() -> tuple[str, ...]:
    return (*[n for n in UNIT_NAMES if '@' not in n],
            *(f'cosmabot-backup-job@{action}.service'
              for action in ('backup', 'switch', 'status')))


def service_properties(name: str) -> dict[str, str]:
    result = command(['systemctl', 'show', name,
                      '--property=LoadState,ActiveState,UnitFileState']).decode()
    return dict(line.split('=', 1) for line in result.splitlines() if '=' in line)


def verify_stopped() -> None:
    for name in service_names():
        properties = service_properties(name)
        require(properties.get('LoadState') == 'loaded'
                and properties.get('ActiveState') == 'inactive'
                and properties.get('UnitFileState') in {'disabled', 'static'},
                'backup services must remain stopped and disabled')


def install(contents: dict[str, bytes], bundle_digest: str, source_commit: str) -> None:
    # Every prerequisite and reviewed byte is checked before the first persistent mutation.
    preflight()
    CODE.mkdir(mode=0o755)
    CONFIG.mkdir(mode=0o755)
    (CONFIG / 'secrets').mkdir(mode=0o700)
    for name in ('backup.py', 'restore.py', 'wal-g'):
        write_new(CODE / name, contents[name], 0o555)
    for name in ('walg.json', 'resolv.conf'):
        write_new(CONFIG / name, contents[name], 0o644)
    # Missing shared libraries or a foreign binary fail before account/unit creation.
    require(b'3.0.9' in command([str(CODE / 'wal-g'), '--version']), 'WAL-G version')
    for account in ACCOUNTS:
        command(['groupadd', '--system', account])
        command(['useradd', '--system', '--gid', account, '--home-dir', '/nonexistent',
                 '--no-create-home', '--shell', '/usr/sbin/nologin', account])
    verify_accounts()
    for name in UNIT_NAMES:
        write_new(UNITS / name, contents[name], 0o644)
    write_new(LOGROTATE, contents['logrotate.conf'], 0o644)
    command(['systemd-analyze', 'verify', *[str(UNITS / name) for name in UNIT_NAMES]],
            reject_diagnostics_for=UNIT_NAMES)
    command(['systemctl', 'daemon-reload'])
    verify_stopped()
    for name, raw in contents.items():
        target = (UNITS / name if name in UNIT_NAMES else
                  CONFIG / name if name in {'walg.json', 'resolv.conf'} else
                  LOGROTATE if name == 'logrotate.conf' else CODE / name)
        require(read_public(target, 70 * 1024 * 1024) == raw, 'installed content changed')
    write_new(RECEIPT, (json.dumps({
        'status': 'public_software_installed_services_stopped', 'source_commit': source_commit,
        'bundle_sha256': bundle_digest,
        'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()},
        'accounts': list(ACCOUNTS), 'credentials_installed': False,
        'database_provisioned': False, 'backup_activated': False,
        'restore_qualified': False,
    }, sort_keys=True, indent=2) + '\n').encode(), 0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--bundle-sha256', required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    os.umask(0o022)
    contents = read_bundle(args.bundle, args.bundle_sha256, args.source_commit)
    install(contents, args.bundle_sha256, args.source_commit)
    print('Public backup software installed; services stopped. Credentials and activation remain required.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit(
            'Backup installation refused or incomplete; preserve files for operator review.') from None
