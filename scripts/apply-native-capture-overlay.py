"""Apply the exact local PCM delta only to a separately archived Apple shell."""

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

OVERLAY = Path(__file__).parents[1] / "clients/capture/native-overlays/renewable-authority"
PREFIXES = ("apps/capture/native-plugins/ios-pcm-capture/",
            "apps/capture/native-plugins/ios-pcm-capacitor/")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(output: Path, source_ref: str) -> dict[str, object]:
    output = output.resolve()
    manifest = json.loads((OVERLAY / "manifest.json").read_text())
    patch = OVERLAY / "source.patch"
    if (manifest.get("version") != 1 or manifest.get("source_ref") != source_ref
            or manifest.get("patch_sha256") != digest(patch)):
        raise ValueError("Native capture overlay identity does not match the pinned source.")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Native capture overlay has no file contract.")
    for name, hashes in files.items():
        relative = PurePosixPath(name)
        if (str(relative) != name or ".." in relative.parts
                or not name.startswith(PREFIXES) or relative.suffix != ".swift"
                or any(part.startswith(".env") for part in relative.parts)
                or set(hashes) != {"before", "after"}
                or not re.fullmatch(r"[0-9a-f]{64}", hashes["after"])):
            raise ValueError("Invalid native capture overlay file contract.")
        path = output / name
        if path.resolve() != path or not path.is_relative_to(output):
            raise ValueError("Native capture overlay cannot follow links.")
        if hashes["before"] is None:
            valid = not path.exists()
        else:
            valid = path.is_file() and digest(path) == hashes["before"]
        if not valid:
            raise ValueError(f"Native capture overlay base changed: {name}")
    # Ask Git to enumerate the complete patch before any mutation; do not
    # permit an unlisted change or a deletion outside the hash contract.
    result = subprocess.run(["git", "apply", "--numstat", "-z", str(patch)],
                            cwd=output, capture_output=True, check=True)
    entries = result.stdout.decode().strip("\0").split("\0")
    names = [entry.split("\t", 2)[2] for entry in entries]
    if len(names) != len(files) or set(names) != set(files):
        raise ValueError("Native capture overlay patch changes unlisted paths.")
    subprocess.run(["git", "apply", "--check", "--whitespace=error", str(patch)],
                   cwd=output, check=True, capture_output=True)
    subprocess.run(["git", "apply", "--whitespace=error", str(patch)],
                   cwd=output, check=True, capture_output=True)
    if any(digest(output / name) != hashes["after"] for name, hashes in files.items()):
        raise ValueError("Native capture overlay result differs from its contract.")
    return {"version": 1, "patch_sha256": digest(patch), "files": files}
