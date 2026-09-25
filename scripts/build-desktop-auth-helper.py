#!/usr/bin/env python3
"""Compile the qualified desktop auth helper locally; never package, sign or launch it."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import signal
import subprocess
from pathlib import Path

_spec = importlib.util.spec_from_file_location("native_auth_build_receipt", Path(__file__).with_name("native_auth_build_receipt.py"))
binding = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(binding)


def run_compiler(command: list[str], output: Path, environment: dict[str, str], *, query=False) -> str:
    if not Path(binding.DENY_NETWORK[0]).is_file():
        raise ValueError("The macOS sandbox-exec network boundary is required.")
    with (output / "compile.log").open("ab") as log:
        process = subprocess.Popen(command, cwd=output, env=environment, start_new_session=True,
                                   stdout=subprocess.PIPE if query else log, stderr=log)
        try:
            stdout, _ = process.communicate(timeout=900)
        except BaseException:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            raise
        if process.returncode:
            raise ValueError("Swift compilation failed; inspect compile.log. No compiler receipt issued.")
        return stdout.decode("utf-8").strip() if query else ""


def build(qualified: Path, swift: Path, output: Path) -> Path:
    repo = Path(__file__).resolve().parents[1]
    qualified = binding.directory(qualified)
    manifest, qualification_hash = binding.qualification(qualified)
    # Keep the selected invocation name: Xcode's swift is a symlink to
    # swift-frontend, whose behavior depends on argv[0].
    if not swift.is_absolute() or not swift.is_file() or not os.access(swift, os.X_OK):
        raise ValueError("Select an installed Swift executable by absolute path.")
    swift = swift.absolute()
    swift_hash = binding.digest(swift)
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("Use a fresh output directory with an existing parent.")
    output = output.resolve()
    if output.is_relative_to(repo) or output.is_relative_to(qualified) or qualified.is_relative_to(output):
        raise ValueError("Build output must be separate from the repository and qualification.")
    output.mkdir(mode=0o700)
    (output / ".incomplete").write_text("No completed compiler receipt; inspect compile.log before selecting a new output.\n")
    source = output / "source"
    source.mkdir()
    for name in [*manifest["composed_sha256"], "qualification.json"]:
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(qualified / name, destination)
    if binding.qualification(source) != (manifest, qualification_hash):
        raise ValueError("Qualification changed while copying source.")
    for name in ("scratch", "cache", "config", "security", "modules", "tmp", "home", "xdg-cache", "xdg-config"):
        (output / name).mkdir()
    environment = {"PATH": f"{swift.parent}:/usr/bin:/bin:/usr/sbin:/sbin",
                   "HOME": str(output / "home"), "CFFIXED_USER_HOME": str(output / "home"),
                   "XDG_CACHE_HOME": str(output / "xdg-cache"), "XDG_CONFIG_HOME": str(output / "xdg-config"),
                   "TMPDIR": str(output / "tmp"), "CLANG_MODULE_CACHE_PATH": str(output / "modules"),
                   "SWIFTPM_MODULECACHE_OVERRIDE": str(output / "modules")}
    for parent in swift.parents:
        if parent.name == "Developer" and (parent / "Toolchains").is_dir():
            environment["DEVELOPER_DIR"] = str(parent)
            break
    command = binding.build_command(swift, output)
    (output / "command.json").write_text(json.dumps({"argv": command, "environment": environment}, indent=2) + "\n")
    run_compiler(command, output, environment)
    reported = run_compiler([*command, "--show-bin-path"], output, environment, query=True)
    compiled = Path(reported)
    if not compiled.is_absolute() or not compiled.resolve().is_relative_to(output / "scratch"):
        raise ValueError("Swift did not report products inside this invocation's fresh scratch directory.")
    compiled = compiled.resolve(strict=True)
    files = binding.product_inventory(compiled)
    products = output / "products"
    products.mkdir()
    shutil.copy2(compiled / binding.PRODUCT, products / binding.PRODUCT)
    shutil.copytree(compiled / binding.RESOURCES, products / binding.RESOURCES)
    if (binding.inventory(products) != files or binding.product_inventory(compiled) != files
            or binding.qualification(qualified) != (manifest, qualification_hash)
            or binding.qualification(source) != (manifest, qualification_hash)
            or binding.digest(swift) != swift_hash):
        raise ValueError("Source, compiler or products changed during the build; no compiler receipt issued.")
    receipt = {"version": 1, "kind": "cosmas-desktop-auth-compiler-receipt", "exit_code": 0,
               "qualification_sha256": qualification_hash, "source_sha256": manifest["composed_sha256"],
               "swift": {"path": str(swift), "sha256": swift_hash}, "command": command,
               "compiler_products": compiled.relative_to(output).as_posix(), "product_files": files,
               "compiler_log_sha256": binding.digest(output / "compile.log")}
    receipt_path = output / binding.RECEIPT
    with receipt_path.open("x") as handle:
        handle.write(json.dumps(receipt, indent=2) + "\n")
    (output / ".incomplete").unlink()
    return receipt_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--swift", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = build(args.qualification, args.swift, args.output)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"Desktop auth build refused: {error}\n")
    print(f"Compiled desktop auth helper; local compiler receipt: {receipt}; not packaged or launched")


if __name__ == "__main__":
    main()
