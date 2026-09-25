"""Linux-host checks before any VM service starts; does not contact Azure."""

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path


def main():
    release = Path(sys.argv[1])
    if not release.is_absolute() or str(release.resolve()) != str(release):
        raise ValueError
    receipt = json.loads((release / "RENDER.json").read_text())
    for name, digest in receipt["files"].items():
        if Path(name).name != name:
            raise ValueError
        path = release / name
        meta = path.lstat()
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_uid != 0
            or stat.S_IMODE(meta.st_mode) != 0o444
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError
    data = Path("/var/lib/cosmabot")
    subprocess.run(["mountpoint", "-q", str(data)], check=True)
    for name, uid in (
        ("postgres", 999),
        ("redis", 999),
        ("caddy-data", 10001),
        ("caddy-config", 10001),
    ):
        path = data / name
        meta = path.lstat()
        if (
            not stat.S_ISDIR(meta.st_mode)
            or meta.st_uid != uid
            or stat.S_IMODE(meta.st_mode) != 0o700
        ):
            raise ValueError
    if os.getuid() != 0:
        raise ValueError


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(
            "Host preflight refused: check release hashes/ownership and the mounted data disk.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
