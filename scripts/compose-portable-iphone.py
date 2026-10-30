#!/usr/bin/env python3
"""Compose iPhone project inputs from owned clients and the frozen app scaffold.

apps/capture stays frozen 1107 evidence. Shared implementation files come from
clients/apple and clients/capture. This entry does not read an external
snapshot, modify the scaffold, sign, or compile.
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

IMPLEMENTATION_OWNERS = ("clients/apple", "clients/capture")
SUPPORTING_CLIENT = "clients/shared"
APP_SCAFFOLD = "apps/capture"
PROVENANCE_NAME = "SOURCE_PROVENANCE.json"
# These composed manifests are scaffold wiring. The owned package files describe
# a library layout, so replacing them would drop the iPhone target graph.
SCAFFOLD_PACKAGE_WIRING = frozenset({
    "native-plugins/cosmas-native-auth/Package.swift",
    "native-plugins/native-recording-pcm/Package.swift",
})
WIRING_NOTES = {
    "native-plugins/cosmas-native-auth/Package.swift": (
        "clients/apple/native-auth/Package.swift is the library package. "
        "The iPhone target keeps the scaffold manifest so the Bridge, vendored "
        "ClerkKit, and sibling plugins stay on the composed graph."
    ),
    "native-plugins/native-recording-pcm/Package.swift": (
        "clients/capture/native-recording-pcm/Package.swift points at "
        "native-configured/ios-pcm-capture. The scaffold manifest points at "
        "the composed ios-pcm-capture package."
    ),
}
MAC_BEFORE_QUALIFIED_INSTALL = (
    "Regenerate the web renderer with scripts/build-native-renderer.mjs.",
    "Select explicit retained public native identity and profile inputs.",
    "Populate fresh generated app assets before native compilation.",
    "Review required-reason API privacy declarations, including ProcessInfo.systemUptime.",
    "On a Mac, compile, sign, and install against the same reviewed commit.",
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value == "" or value.endswith("/"):
        raise ValueError(f"Refusing an unsafe composition path: {value}")
    return path


def _owner(path: str) -> str:
    for owner in (*IMPLEMENTATION_OWNERS, SUPPORTING_CLIENT):
        if path == owner or path.startswith(owner + "/"):
            return owner
    raise ValueError(f"Composition source is outside the owned clients: {path}")


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _discard(output: Path, repository: Path) -> None:
    if _inside(output, repository) or _inside(repository, output):
        raise ValueError("Refusing to remove a path inside the repository.")
    if output.exists():
        shutil.rmtree(output)


def _regular_file(repository: Path, path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Composition source is not a regular file: {path}")
    resolved = path.resolve()
    if not _inside(resolved, repository):
        raise ValueError(f"Composition source escaped the repository: {path}")
    return resolved


def compose(repository: Path, output: Path) -> Path:
    """Copy the frozen scaffold and overlay owned client implementations."""
    repository = repository.resolve()
    output = output.resolve()
    scaffold = repository / APP_SCAFFOLD
    provenance_path = scaffold / PROVENANCE_NAME
    if provenance_path.is_symlink() or not provenance_path.is_file():
        raise ValueError("The frozen app scaffold provenance is unavailable.")
    for owner in IMPLEMENTATION_OWNERS:
        root = repository / owner
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"Implementation owner is missing: {owner}")
    if output.exists() or output.is_symlink():
        raise ValueError("Output must not exist; use a fresh directory.")
    if _inside(output, repository) or _inside(repository, output):
        raise ValueError("Output must stay outside the repository so the frozen scaffold is unchanged.")
    record = json.loads(provenance_path.read_text(encoding="utf-8"))
    files = record.get("files")
    if not isinstance(files, list) or len(files) != record.get("native_source_file_count"):
        raise ValueError("Frozen scaffold provenance does not match its file count.")

    plan: list[dict[str, object]] = []
    seen: set[str] = set()
    owners_used: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("Frozen scaffold provenance has an unreadable file entry.")
        relative = _relative(item["path"])
        key = relative.as_posix()
        if key in seen:
            raise ValueError(f"Duplicate scaffold path: {key}")
        seen.add(key)
        equivalent = item.get("tracked_equivalent")
        counterpart = None
        note = None
        if key in SCAFFOLD_PACKAGE_WIRING:
            if not isinstance(equivalent, dict) or not isinstance(equivalent.get("path"), str):
                raise ValueError(f"Scaffold wiring lost its owned counterpart: {key}")
            counterpart = _relative(equivalent["path"]).as_posix()
            if _owner(counterpart) not in IMPLEMENTATION_OWNERS:
                raise ValueError(f"Scaffold wiring counterpart is not an implementation owner: {key}")
            source = _regular_file(repository, scaffold / relative)
            role = "scaffold-package-wiring"
            owner = APP_SCAFFOLD
            note = WIRING_NOTES[key]
        elif equivalent is None:
            source = _regular_file(repository, scaffold / relative)
            role = "app-scaffold"
            owner = APP_SCAFFOLD
        else:
            if not isinstance(equivalent, dict) or not isinstance(equivalent.get("path"), str):
                raise ValueError(f"Owned source mapping is unreadable: {key}")
            counterpart = _relative(equivalent["path"]).as_posix()
            owner = _owner(counterpart)
            source = _regular_file(repository, repository / counterpart)
            if owner in IMPLEMENTATION_OWNERS:
                role = "implementation"
                owners_used.add(owner)
            else:
                role = "supporting-client"
        plan.append({
            "path": key,
            "role": role,
            "owner": owner,
            "source": source,
            "authoritative_counterpart": counterpart,
            "wiring_note": note,
        })
    if owners_used != set(IMPLEMENTATION_OWNERS):
        raise ValueError("Portable composition must select both client implementation owners.")

    output.mkdir(parents=True)
    try:
        placed: list[dict[str, object]] = []
        for entry in plan:
            destination = output / APP_SCAFFOLD / str(entry["path"])
            if _inside(destination.resolve(), repository):
                raise ValueError("Refusing to write the frozen scaffold.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry["source"], destination)
            digest = _digest(destination)
            if digest != _digest(entry["source"]):
                raise ValueError(f"Copied composition input changed: {entry['path']}")
            placed.append({
                "path": entry["path"],
                "role": entry["role"],
                "owner": entry["owner"],
                "sha256": digest,
                "authoritative_counterpart": entry["authoritative_counterpart"],
                "wiring_note": entry["wiring_note"],
            })
        project = output / APP_SCAFFOLD / "ios/App/App.xcodeproj"
        if not project.is_dir():
            raise ValueError("Portable composition did not include the app scaffold project.")
        public = output / APP_SCAFFOLD / "ios/App/App/public"
        if public.exists():
            raise ValueError("Generated web assets do not belong in this source composition.")
        manifest = {
            "purpose": "portable-iphone-project-inputs",
            "qualified_install": False,
            "compiled_signed_or_installed": False,
            "external_snapshot_required": False,
            "app_scaffold": APP_SCAFFOLD,
            "scaffold_role": "frozen-1107-evidence",
            "implementation_owners": list(IMPLEMENTATION_OWNERS),
            "supporting_clients": [SUPPORTING_CLIENT],
            "scaffold_package_wiring": sorted(SCAFFOLD_PACKAGE_WIRING),
            "generated_web_assets": "absent",
            "mac_before_qualified_install": list(MAC_BEFORE_QUALIFIED_INSTALL),
            "project": f"{APP_SCAFFOLD}/ios/App/App.xcodeproj",
            "files": placed,
        }
        (output / "composition.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except Exception:
        _discard(output, repository)
        raise
    return project


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        project = compose(args.repository, args.output)
    except ValueError as error:
        parser.exit(2, f"{error}\n")
    print(f"Prepared portable iPhone project inputs: {project}")
    print("The frozen app scaffold was not modified.")
    print("This entry did not compile, sign, or install.")
    print("A Mac must still regenerate the renderer, select public identity,")
    print("review privacy declarations, then compile and sign.")


if __name__ == "__main__":
    main()
