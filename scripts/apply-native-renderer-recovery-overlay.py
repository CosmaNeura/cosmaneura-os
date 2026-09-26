"""Apply the Swift-only renderer-loss delta to a fresh, renewable Apple archive."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

OVERLAY = Path(__file__).parents[1] / "clients/capture/native-overlays/renderer-recovery"
RENEWABLE_OVERLAY = OVERLAY.parent / "renewable-authority"
ALLOWED_FILES = frozenset({
    "apps/capture/native-plugins/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor/IOSPCMCapacitorPlugin.swift",
    "apps/capture/native-plugins/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitorTransport/IOSPCMCapacitorTransport.swift",
    "apps/capture/native-plugins/ios-pcm-capacitor/Tests/CosmaneuraIOSPCMCapacitorTransportTests/IOSPCMCapacitorTransportTests.swift",
    "apps/capture/native-plugins/ios-pcm-capture/Sources/CosmaneuraIOSPCMBridgeCore/IOSPCMBridgeCore.swift",
    "apps/capture/native-plugins/ios-pcm-capture/Tests/CosmaneuraIOSPCMBridgeCoreTests/IOSPCMBridgeCoreTests.swift",
})


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_file(output: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or str(relative) != name or ".." in relative.parts:
        raise ValueError("Invalid renderer recovery path.")
    path = output / name
    if path.resolve() != path or not path.is_relative_to(output) or not path.is_file():
        raise ValueError("Renderer recovery requires ordinary archived source files.")
    return path


def apply(output: Path, source_ref: str) -> dict[str, object]:
    output = Path(output).resolve()
    if not output.is_dir() or (output / "composition.json").exists() or (output / ".git").exists():
        raise ValueError("Renderer recovery requires a fresh, unfinalized source archive.")
    manifest = json.loads((OVERLAY / "manifest.json").read_text())
    patch = OVERLAY / "source.patch"
    renewable = json.loads((RENEWABLE_OVERLAY / "manifest.json").read_text())
    if (manifest.get("version") != 1 or manifest.get("source_ref") != source_ref
            or manifest.get("patch_sha256") != digest(patch)
            or renewable.get("source_ref") != source_ref
            or manifest.get("base_overlay_sha256") != renewable.get("patch_sha256")
            or renewable.get("patch_sha256") != digest(RENEWABLE_OVERLAY / "source.patch")):
        raise ValueError("Renderer recovery overlay identity or renewable base does not match.")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != ALLOWED_FILES:
        raise ValueError("Renderer recovery overlay changes an unexpected file set.")
    # Validate the entire prerequisite overlay, including files this delta leaves
    # unchanged. A partial or differently qualified renewable source is rejected.
    for name, hashes in renewable["files"].items():
        if digest(checked_file(output, name)) != hashes["after"]:
            raise ValueError(f"Renderer recovery renewable base changed: {name}")
    for name, hashes in files.items():
        if (not isinstance(hashes, dict) or set(hashes) != {"before", "after"}
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for value in hashes.values())):
            raise ValueError("Invalid renderer recovery hash contract.")
        if digest(checked_file(output, name)) != hashes["before"]:
            raise ValueError(f"Renderer recovery source base changed: {name}")
    listing = subprocess.run(["git", "apply", "--numstat", "-z", str(patch)],
                             cwd=output, capture_output=True, check=True)
    entries = listing.stdout.decode().strip("\0").split("\0")
    names = [entry.split("\t", 2)[2] for entry in entries]
    if len(names) != len(files) or set(names) != set(files):
        raise ValueError("Renderer recovery patch changes unlisted paths.")
    subprocess.run(["git", "apply", "--check", "--whitespace=error", str(patch)],
                   cwd=output, capture_output=True, check=True)
    subprocess.run(["git", "apply", "--whitespace=error", str(patch)],
                   cwd=output, capture_output=True, check=True)
    if any(digest(checked_file(output, name)) != hashes["after"] for name, hashes in files.items()):
        raise ValueError("Renderer recovery result differs from its hash contract.")
    return {"version": 1, "source_ref": source_ref, "patch_sha256": digest(patch),
            "base_overlay_sha256": manifest["base_overlay_sha256"], "files": files}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-ref", required=True)
    args = parser.parse_args()
    print(json.dumps(apply(args.output, args.source_ref), indent=2))
