"""Verify local desktop-auth source/product bindings; never issue build receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

PRODUCT = "CosmasDesktopAuth"
RESOURCES = "CosmasNativeAuthQualification_ClerkKit.bundle"
RECEIPT = "compiler-receipt.json"
ARCHIVE_SHA256 = "bad4b726cac296e2480c81199ef1c5b7759064d9cd0ffa10056d4f8122fcb5e4"
DENY_NETWORK = ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)"]


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_json(path: Path) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate native build metadata field.")
            value[key] = item
        return value

    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError("Native build metadata must be a bounded regular file.")
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Native build metadata must be an object.")
    return value


def directory(path: Path) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Use an existing native build directory, not a symlink.")
    return path.resolve(strict=True)


def relative_path(name: str) -> Path:
    if (not isinstance(name, str) or not name or Path(name).is_absolute()
            or any(part in ("", ".", "..") for part in name.split("/"))
            or "\\" in name):
        raise ValueError("Native build inventory paths must remain inside their directory.")
    return Path(name)


def inventory(root: Path) -> dict[str, dict]:
    root = directory(root)
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Native build inventories cannot contain symlinks.")
        info = path.stat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Native build inventories require regular files.")
        result[path.relative_to(root).as_posix()] = {
            "sha256": digest(path), "bytes": info.st_size, "mode": stat.S_IMODE(info.st_mode),
        }
    return result


def qualification(root: Path) -> tuple[dict, str]:
    root = directory(root)
    manifest = load_json(root / "qualification.json")
    if (manifest.get("clerk_version") != "1.5.5"
            or manifest.get("archive_sha256") != ARCHIVE_SHA256
            or manifest.get("includes_desktop_helper") is not True
            or manifest.get("includes_capacitor_bridge") is not False):
        raise ValueError("Use a qualified desktop-only ClerkKit 1.5.5 source composition.")
    expected = manifest.get("composed_sha256")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Qualification source inventory is missing.")
    for name, value in expected.items():
        path = relative_path(name)
        if (path.parts[0] not in {"Package.swift", "Sources", "Tests", "Desktop", "vendor"}
                or not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
            raise ValueError("Qualification source inventory is invalid.")
    if not {"Package.swift", "vendor/LICENSE"} <= expected.keys():
        raise ValueError("Qualification package or SDK license is missing.")
    if manifest.get("sdk_source_sha256") != {
        name.removeprefix("vendor/"): value for name, value in expected.items() if name.startswith("vendor/")
    }:
        raise ValueError("Qualification SDK and composed inventories differ.")
    actual = {name: item["sha256"] for name, item in inventory(root).items()
              if name != "qualification.json"}
    if actual != expected:
        raise ValueError("Qualification source inventory changed; recompose and rebuild first.")
    return manifest, digest(root / "qualification.json")


def product_inventory(products: Path) -> dict[str, dict]:
    products = directory(products)
    binary = products / PRODUCT
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("The compiler executable is missing or is not executable.")
    info = binary.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("The compiler executable must be a regular file.")
    resources = inventory(products / RESOURCES)
    if not resources:
        raise ValueError("The compiler SDK resource bundle is empty.")
    return {PRODUCT: {"sha256": digest(binary), "bytes": info.st_size,
                      "mode": stat.S_IMODE(info.st_mode)},
            **{f"{RESOURCES}/{name}": value for name, value in resources.items()}}


def build_command(swift: Path, output: Path, configuration: str = "debug") -> list[str]:
    if configuration not in ("debug", "release"):
        raise ValueError("Native build configuration must be debug or release.")
    return [*DENY_NETWORK, str(swift), "build", "--package-path", str(output / "source"),
            "--scratch-path", str(output / "scratch"), "--configuration", configuration,
            "--disable-automatic-resolution", "--disable-sandbox",
            "--cache-path", str(output / "cache"), "--config-path", str(output / "config"),
            "--security-path", str(output / "security"), "--product", PRODUCT]


def verify(receipt_path: Path, qualified: Path, products: Path) -> dict:
    """Require retained output from the owned compiler wrapper, with matching bytes.

    This checks a local build record, not a cryptographic attestation against a
    person who can rewrite that record and every input/output it describes.
    """
    receipt = load_json(receipt_path)
    root = directory(receipt_path.parent)
    if receipt_path.name != RECEIPT or (root / ".incomplete").exists():
        raise ValueError("Use a completed compiler receipt from the owned build wrapper.")
    keys = {"version", "kind", "qualification_sha256", "source_sha256", "swift",
            "command", "exit_code", "compiler_products", "product_files", "compiler_log_sha256"}
    version = receipt.get("version")
    if version == 2:
        keys.add("configuration")
    if (set(receipt) != keys or type(version) is not int or version not in (1, 2)
            or receipt["kind"] != "cosmas-desktop-auth-compiler-receipt"
            or type(receipt["exit_code"]) is not int or receipt["exit_code"] != 0):
        raise ValueError("Native compiler receipt is invalid.")
    # Version 1 was issued only by the fixed Debug builder. Never reinterpret
    # an old receipt as Release or let a new label contradict its command.
    configuration = "debug" if version == 1 else receipt["configuration"]
    manifest, source_hash = qualification(qualified)
    copied, copied_hash = qualification(root / "source")
    if (source_hash != receipt["qualification_sha256"] or copied_hash != source_hash
            or manifest["composed_sha256"] != receipt["source_sha256"] or copied != manifest):
        raise ValueError("Compiler receipt belongs to a different qualification source.")
    swift = receipt["swift"]
    if (not isinstance(swift, dict) or set(swift) != {"path", "sha256"}
            or not isinstance(swift["path"], str) or not Path(swift["path"]).is_absolute()
            or not isinstance(swift["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", swift["sha256"])
            or receipt["command"] != build_command(Path(swift["path"]), root, configuration)):
        raise ValueError("Compiler receipt does not describe the fixed local build command.")
    compiled_relative = relative_path(receipt["compiler_products"])
    compiled = root / compiled_relative
    if compiled_relative.parts[0] != "scratch" or not compiled.resolve().is_relative_to(root / "scratch"):
        raise ValueError("Compiler products are outside this build's scratch directory.")
    if directory(products) != root / "products":
        raise ValueError("Select the products directory belonging to this compiler receipt.")
    files = product_inventory(products)
    if (files != receipt["product_files"] or inventory(products) != files
            or product_inventory(compiled) != files):
        raise ValueError("Compiler products changed or were mixed with another build.")
    log = root / "compile.log"
    if log.is_symlink() or not log.is_file() or digest(log) != receipt["compiler_log_sha256"]:
        raise ValueError("Retained compiler log changed.")
    return manifest
