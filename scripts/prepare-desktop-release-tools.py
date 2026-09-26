"""Materialize only Scribe's pinned public build packages from a verified npm cache.

No network, npm lifecycle scripts, installation into a project, or native signing.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def prepare(cache: Path, output: Path):
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "clients/desktop/release/build-tools-lock.json").read_text())
    if output.exists() or output.is_symlink() or output.is_relative_to(root) or output.is_relative_to(cache):
        raise ValueError("Use a fresh, separate build-tools output directory.")
    archives = {}
    for name, item in lock["packages"].items():
        algorithm, encoded = item["integrity"].split("-", 1)
        if algorithm != "sha512":
            raise ValueError("Expected the pinned npm SHA512 integrity.")
        value = base64.b64decode(encoded, validate=True).hex()
        path = cache / "content-v2/sha512" / value[:2] / value[2:4] / value[4:]
        if not path.is_file() or path.stat().st_size > 10_000_000:
            raise ValueError(f"Missing pinned public package in npm cache: {name}")
        data = path.read_bytes()
        if hashlib.sha512(data).hexdigest() != value:
            raise ValueError("Cached package differs from its pinned integrity.")
        archives[name] = data
    expected = lock["files"]
    verified = {}
    for name, data in archives.items():
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if not path.parts or path.parts[0] != "package" or path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                    raise ValueError("Unexpected path or link in pinned package archive.")
                if member.isdir():
                    continue
                relative = str(PurePosixPath(name, *path.parts[1:]))
                if relative not in expected or relative in verified or member.size != expected[relative]["bytes"]:
                    raise ValueError("Unexpected or duplicate file in pinned package archive.")
                content = archive.extractfile(member).read()
                if hashlib.sha256(content).hexdigest() != expected[relative]["sha256"]:
                    raise ValueError("Pinned package file integrity differs.")
                verified[relative] = (content, 0o555 if member.mode & 0o111 else 0o444)
    if set(verified) != set(expected):
        raise ValueError("Incomplete pinned package inventory.")
    output.mkdir(parents=True)
    for relative, (content, mode) in verified.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)
    (output / "package.json").write_text('{"name":"cosmas-local-release-build-tools","private":true,"type":"module"}\n')
    print(f"Prepared {len(archives)} pinned public packages / {len(verified)} files; no lifecycle scripts executed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npm-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.npm_cache.resolve(), args.output.resolve())
