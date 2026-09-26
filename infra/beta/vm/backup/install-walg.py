#!/usr/bin/python3
"""Install only the reviewed, already downloaded WAL-G binary; no network/package changes."""

import argparse
import hashlib
import os
import platform
import stat
import subprocess
from pathlib import Path

EXPECTED = 'd6795c663894d836ba20840bffe8970aed81bbe25d3151bd4951f6f9c362def9'
DESTINATION = Path('/opt/cosmabot/backup/wal-g')


def verify_artifact(raw: bytes) -> None:
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        raise ValueError('binary digest')
    if raw[:6] != b'\x7fELF\x02\x01' or int.from_bytes(raw[18:20], 'little') != 62:
        raise ValueError('native ELF format')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('downloaded_binary', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0 or platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('Linux amd64 root required')
    source = args.downloaded_binary
    if not source.is_absolute() or source.resolve() != source:
        raise ValueError('artifact path')
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError('artifact custody')
        if metadata.st_size != 61326184:
            raise ValueError('artifact length')
        raw = stream.read()
    verify_artifact(raw)
    parent = DESTINATION.parent
    if parent.resolve() != parent or parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022:
        raise ValueError('install parent custody')
    # Refuse replacement; failed dynamic/version checks leave this exact binary for diagnosis.
    descriptor = os.open(DESTINATION, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o555)
    with os.fdopen(descriptor, 'wb') as stream:
        os.fchmod(stream.fileno(), 0o555)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'HOME': '/nonexistent'}
    linked = subprocess.run(['/usr/bin/ldd', str(DESTINATION)], capture_output=True, env=env, timeout=30)
    # Static or dynamically complete binaries are valid; missing libraries never get auto-installed.
    if b'not found' in linked.stdout + linked.stderr or (linked.returncode != 0 and
            b'not a dynamic executable' not in linked.stdout + linked.stderr):
        raise ValueError('native dynamic library compatibility')
    result = subprocess.run([str(DESTINATION), '--version'], capture_output=True, env=env, timeout=30)
    if result.returncode != 0 or b'3.0.9' not in result.stdout + result.stderr:
        raise ValueError('native version check')
    print('Installed pinned WAL-G 3.0.9; backup/restore services remain stopped.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit(
            'WAL-G installation refused or incomplete; inspect the exact install path.') from None
