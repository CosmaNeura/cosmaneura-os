#!/usr/bin/env python3
"""Test the actual encrypted queue with isolated synthetic files and unique test keys.

The Capacitor wrapper is compiled by the separate iPhone archive qualification.
This offline Swift harness compiles the same storage sources without that wrapper.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--filter")
    parser.add_argument("--scribe-source", type=Path,
                        default=root.parents[2] / "cosmaneura-scribe-beta-preintegration-20260904")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("Use a fresh test directory outside the source checkout.")
    output.mkdir(parents=True)
    package = output / "package"
    sources = package / "Sources/CosmaneuraSecureQueue"
    tests = package / "Tests/CosmaneuraSecureQueueTests"
    sources.mkdir(parents=True)
    tests.mkdir(parents=True)
    owned = root / "clients/capture/native-configured/secure-queue/ios/Sources/CosmaneuraSecureQueue"
    inputs = {}
    for path in sorted(owned.glob("*.swift")):
        if path.name == "SecureQueuePlugin.swift":
            continue
        shutil.copyfile(path, sources / path.name)
        inputs[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted((root / "tests/native/secure-queue").glob("*.swift")):
        shutil.copyfile(path, tests / path.name)
        inputs[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    # Exercise the actual retained app's previous storage implementation. It is
    # read from an immutable commit into a distinct test-only module, never run
    # against an installed app's directory or keychain namespace.
    legacy_ref = "ea7f99d0278a05706531ffb1288cb1df7acf507b"
    legacy = package / "Sources/CosmaBotLegacySecureQueue"
    legacy.mkdir()
    legacy_hashes = {}
    for name in ("SecureQueueStore.swift", "SecureQueueRecordCodec.swift", "SecureQueueError.swift"):
        path = "apps/capture/native-plugins/secure-queue/ios/Sources/CosmaneuraSecureQueue/" + name
        data = subprocess.check_output(["git", "show", legacy_ref + ":" + path], cwd=args.scribe_source)
        (legacy / name).write_bytes(data)
        legacy_hashes[path] = hashlib.sha256(data).hexdigest()
    native = root / "clients/capture/native-recording"
    (package / "Package.swift").write_text('''// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "CosmaBotSecureQueueQualification", platforms: [.macOS(.v14)],
    dependencies: [.package(path: ''' + json.dumps(str(native)) + ''')],
    targets: [
        .target(name: "CosmaBotLegacySecureQueue"),
        .target(name: "CosmaneuraSecureQueue", dependencies: [
            .product(name: "CosmaneuraNativeRecording", package: "native-recording")]),
        .testTarget(name: "CosmaneuraSecureQueueTests", dependencies: [
            "CosmaneuraSecureQueue", "CosmaBotLegacySecureQueue",
            .product(name: "CosmaneuraNativeRecording", package: "native-recording")]),
    ])
''')
    for folder in ("tmp", "modules"):
        (output / folder).mkdir()
    env = dict(os.environ, TMPDIR=str(output / "tmp"),
               CLANG_MODULE_CACHE_PATH=str(output / "modules"),
               SWIFTPM_MODULECACHE_OVERRIDE=str(output / "modules"))
    command = ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)",
               "/usr/bin/xcrun", "swift", "test", "--configuration", "release",
               "--package-path", str(package), "--scratch-path", str(output / "build"),
               "--cache-path", str(output / "cache"), "--config-path", str(output / "config"),
               "--security-path", str(output / "security"), "--disable-sandbox"]
    if args.filter:
        command += ["--filter", args.filter]
    with (output / "tests.log").open("w") as log:
        completed = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600)
    assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
               for name, digest in inputs.items()), "Sources changed during test execution."
    result = {"command": command, "exit_code": completed.returncode, "source_sha256": inputs,
              "legacy_ref": legacy_ref, "legacy_source_sha256": legacy_hashes,
              "storage": "fresh temporary directories and uniquely named test-only Keychain items",
              "phone_or_live_service_acceptance": False}
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"exit_code": completed.returncode, "result": str(output / "RESULT.json")}))
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
