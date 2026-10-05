"""Build-only removal of pinned unused tools and runtime privilege bits.

The read-only preflight completes before writes. Package metadata and required
shared libraries stay installed. Any failure aborts the image build.
Pins deliberately qualify only the reviewed Debian linux/amd64 base; changed
architecture, package versions or executable bytes require renewed review.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class HardeningError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise HardeningError(message)


@dataclass(frozen=True)
class ToolPin:
    name: str
    size: int
    sha256: str
    package: str
    version: str
    uid: int = 0
    gid: int = 0
    mode: int = 0o755


PINS = (
    ToolPin("infocmp", 67904, "934ce418360bd162a188f22310509640f3b0c14a858ec4ec04c25df64f97feb0",
            "ncurses-bin", "6.5+20250216-2"),
    ToolPin("nsenter", 88728, "09ea3a612a16b59c04aa55d894a1e868deaddb8a6a9927c4f1993827a3554de1",
            "util-linux", "2.41.5-0+deb13u1"),
)
# Exact non-executable package metadata, distinct from the removed ELF binary.
METADATA = {"usr/share/bash-completion/completions/nsenter":
            ToolPin("nsenter", 1288, "e9cd4e7d9bd2f3fd09f220b4b108558ee61e642465f3e72f49b03d1644cf6d8e",
                    "util-linux", "2.41.5-0+deb13u1", mode=0o644)}
DYNAMIC = {"proc", "sys", "dev"}
PRIVILEGE = stat.S_ISUID | stat.S_ISGID
MODULES = ("_uuid", "_curses", "_curses_panel", "ssl", "sqlite3", "cryptography",
           "pypdf", "psycopg", "psycopg_binary", "fastapi", "cosmas_os.api.app")


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def inode(info):
    return (info.st_dev, info.st_ino)


def walk(root):
    """Visit actual entries once; never enter directory symlinks or virtual roots."""
    records = {}
    pending = [root]
    while pending:
        path = pending.pop()
        relative = path.relative_to(root).as_posix()
        if relative.split("/", 1)[0] in DYNAMIC:
            continue
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode), "unsupported_runtime_entry:" + relative)
        records[relative] = info
        require(len(records) <= 200000, "runtime_inventory_limit")
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(path) as entries:
                pending.extend(path / entry.name for entry in entries)
    return records


def resolve_link(root, relative):
    """Interpret absolute links inside the image root, rejecting lexical escapes."""
    todo = list(PurePosixPath(relative).parts)
    resolved = []
    hops = 0
    while todo:
        part = todo.pop(0)
        if part in ("", ".", "/"):
            continue
        if part == "..":
            require(bool(resolved), "escaping_runtime_symlink")
            resolved.pop()
            continue
        resolved.append(part)
        if resolved[0] in DYNAMIC:
            return None
        path = root.joinpath(*resolved)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            hops += 1
            require(hops <= 40, "runtime_symlink_cycle")
            target = PurePosixPath(os.readlink(path))
            resolved.pop()
            if target.is_absolute():
                resolved = []
            todo = list(target.parts) + todo
    return "/".join(resolved) or "."


def digest(path, expected):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(fd, "rb", closefd=False) as stream:
            require(fingerprint(os.fstat(fd)) == fingerprint(expected), "file_changed_before_hash")
            result = hashlib.file_digest(stream, "sha256").hexdigest()
            require(fingerprint(os.fstat(fd)) == fingerprint(expected), "file_changed_during_hash")
            return result
    finally:
        os.close(fd)


def forbidden(relative):
    parts = PurePosixPath(relative).parts
    return (bool(parts) and parts[-1] in {"mount", "umount", "systemd-homed"}
            or len(parts) >= 2 and parts[-2:] == ("Archive", "Tar.pm"))


def validate_metadata(root, metadata, records, packages, owner):
    for relative, pin in metadata.items():
        require(relative in records, "missing_pinned_metadata:" + relative)
        info = records[relative]
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and not info.st_mode & (0o111 | PRIVILEGE), "unsafe_pinned_metadata:" + relative)
        require((info.st_size, stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid)
                == (pin.size, pin.mode, pin.uid, pin.gid), "pinned_metadata_layout_changed:" + relative)
        require(digest(root / relative, info) == pin.sha256, "pinned_metadata_bytes_changed:" + relative)
        require(packages.get(pin.package) == {"version": pin.version, "essential": "yes", "status": "installed"}
                and owner("/" + relative) == pin.package, "pinned_metadata_owner_changed:" + relative)


def plan(root, pins, packages, owner, metadata=None):
    metadata = metadata or {}
    records = walk(root)
    removed = set()
    tool_names = {p.name for p in pins}
    for relative in records:
        require(not forbidden(relative), "unexpected_forbidden_component:" + relative)
    for pin in pins:
        canonical = "usr/bin/" + pin.name
        require(canonical in records, "missing_pinned_tool:" + pin.name)
        info = records[canonical]
        require(stat.S_ISREG(info.st_mode), "pinned_tool_not_regular:" + pin.name)
        require((info.st_size, stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid)
                == (pin.size, pin.mode, pin.uid, pin.gid), "pinned_tool_layout_changed:" + pin.name)
        require(digest(root / canonical, info) == pin.sha256, "pinned_tool_bytes_changed:" + pin.name)
        require(packages.get(pin.package) == {"version": pin.version, "essential": "yes", "status": "installed"},
                "pinned_package_changed:" + pin.package)
        require(owner("/" + canonical) == pin.package, "pinned_tool_owner_changed:" + pin.name)
    validate_metadata(root, metadata, records, packages, owner)
    for relative, info in records.items():
        if stat.S_ISREG(info.st_mode):
            matches = [p for p in pins if p.size == info.st_size]
            if matches and digest(root / relative, info) in {p.sha256 for p in matches}:
                removed.add(relative)
            require(PurePosixPath(relative).name not in tool_names or relative in removed or relative in metadata,
                    "unexpected_named_tool:" + relative)
    for relative, info in records.items():
        if stat.S_ISLNK(info.st_mode):
            target = resolve_link(root, relative)
            require(target is None or not forbidden(target), "forbidden_component_alias:" + relative)
            if target in removed:
                removed.add(relative)
            require(PurePosixPath(relative).name not in tool_names or relative in removed,
                    "unexpected_tool_alias:" + relative)
    grouped = {}
    for relative, info in records.items():
        if not stat.S_ISLNK(info.st_mode):
            grouped.setdefault(inode(info), []).append(relative)
    privileged = []
    for paths in grouped.values():
        info = records[paths[0]]
        if any(path in removed for path in paths) or info.st_mode & PRIVILEGE:
            if stat.S_ISREG(info.st_mode):
                require(info.st_nlink == len(paths), "unobserved_mutation_hardlink")
        if info.st_mode & PRIVILEGE and not all(path in removed for path in paths):
            privileged.append({"paths": sorted(paths), "mode_before": stat.S_IMODE(info.st_mode),
                               "mode_after": stat.S_IMODE(info.st_mode) & ~PRIVILEGE})
    return records, sorted(removed), privileged


def harden(root, pins, package_inventory, owner, import_probe, metadata=None):
    metadata = metadata or {}
    require(root.is_absolute() and not root.is_symlink(), "unsafe_runtime_root")
    root = root.resolve(strict=True)
    before = package_inventory()
    records, removed, privileged = plan(root, pins, before, owner, metadata)
    import_probe()  # Import declarations only; no lifespan, database or provider calls.
    require(package_inventory() == before, "packages_changed_before_mutation")
    for relative, info in records.items():
        require(fingerprint((root / relative).lstat()) == fingerprint(info), "runtime_changed_before_mutation")
    # All validation above precedes unlink/chmod. A failed build never produces a runtime image.
    for relative in removed:
        (root / relative).unlink()
    for entry in privileged:
        path = root / entry["paths"][0]
        if path.is_dir():
            os.chmod(path, entry["mode_after"], follow_symlinks=False)
        else:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fchmod(fd, entry["mode_after"])
            finally:
                os.close(fd)
    after = walk(root)
    require(not any(info.st_mode & PRIVILEGE for info in after.values()), "privilege_bits_remain")
    for relative, info in after.items():
        require(not forbidden(relative), "forbidden_component_remains")
        if stat.S_ISREG(info.st_mode):
            matches = [p for p in pins if p.size == info.st_size]
            require(not matches or digest(root / relative, info) not in {p.sha256 for p in matches},
                    "tool_bytes_remain")
        if stat.S_ISLNK(info.st_mode):
            require(resolve_link(root, relative) not in removed, "tool_alias_remains")
        require(PurePosixPath(relative).name not in {p.name for p in pins} or relative in metadata,
                "tool_name_remains")
    validate_metadata(root, metadata, after, before, owner)
    require(package_inventory() == before, "installed_packages_changed")
    import_probe()
    return {"schema": "cosmabot.runtime-tool-hardening.v1", "removed_paths": removed,
            "privileged_inodes": privileged, "remaining_privileged_entries": 0,
            "scanned_entries_before": len(records), "scanned_entries_after": len(after),
            "installed_packages_unchanged": True, "installed_package_count": len(before),
            "required_imports_passed": True, "tool_bytes_and_aliases_absent": True,
            "retained_pinned_metadata": sorted(metadata)}


def package_inventory():
    text = subprocess.check_output(["dpkg-query", "-W",
        "-f=${binary:Package}\t${Version}\t${Essential}\t${db:Status-Status}\n"], text=True, timeout=15)
    result = {}
    seen = set()
    for line in text.splitlines():
        row = line.split("\t")
        require(len(row) == 4 and bool(row[0]) and bool(row[1]), "invalid_package_inventory")
        require(row[0] not in seen, "duplicate_package_inventory")
        seen.add(row[0])
        if row[3] == "installed":
            result[row[0]] = dict(zip(("version", "essential", "status"), row[1:], strict=True))
    return result


def package_owner(path):
    text = subprocess.check_output(["dpkg-query", "-S", path], text=True, timeout=15)
    require(text.endswith(": " + path + "\n") and text.count("\n") == 1, "ambiguous_package_owner")
    owner = text[:-(len(path) + 3)]
    require(re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?", owner) is not None,
            "ambiguous_package_owner")
    return owner


def import_probe():
    for module in MODULES:
        importlib.import_module(module)


if __name__ == "__main__":
    require(sys.platform == "linux" and os.geteuid() == 0, "build_root_linux_required")
    require(platform.machine() == "x86_64", "reviewed_amd64_base_required")
    print(json.dumps(harden(Path("/"), PINS, package_inventory, package_owner, import_probe, METADATA)))
