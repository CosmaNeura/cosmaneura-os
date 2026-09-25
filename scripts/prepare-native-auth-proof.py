#!/usr/bin/env python3
"""Compose local native-auth sources with the pinned official ClerkKit core.

This makes a fresh qualification package, without fetching dependencies,
initializing Clerk, changing an account, installing an app or signing anything.
The SDK's UI and test-only packages are not part of this core-source probe.
"""

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

CLERK_VERSION = "1.5.5"
ARCHIVE_SHA256 = "bad4b726cac296e2480c81199ef1c5b7759064d9cd0ffa10056d4f8122fcb5e4"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(
    archive: Path, output: Path, *, include_bridge: bool = False, include_desktop: bool = False,
) -> None:
    root = Path(__file__).resolve().parents[1]
    archive, output = archive.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("Use a fresh qualification directory outside the source tree.")
    if digest(archive) != ARCHIVE_SHA256:
        raise ValueError("Clerk archive does not match the qualified 1.5.5 source.")
    output.mkdir(parents=True)
    prefix = f"clerk-ios-{CLERK_VERSION}/"
    selected = (prefix + "Sources/ClerkKit/", prefix + "LICENSE")
    source_hashes: dict[str, str] = {}
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            if not any(member.name.startswith(item) for item in selected) or not member.isfile():
                continue
            relative = Path(member.name.removeprefix(prefix))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unexpected SDK archive path.")
            data = bundle.extractfile(member)
            if data is None:
                raise ValueError("SDK source file is unavailable.")
            destination = output / "vendor" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data.read())
            source_hashes[str(relative)] = digest(destination)
    if not (output / "vendor/Sources/ClerkKit/Core/Clerk.swift").is_file():
        raise ValueError("Qualified SDK core is missing.")
    owned = root / "clients/apple/native-auth"
    for folder in ("Sources", "Tests"):
        shutil.copytree(owned / folder, output / folder)
    if include_bridge:
        shutil.copytree(owned / "Bridge", output / "Bridge")
        shutil.copyfile(root / "clients/shared/cosmaneura-navigation-dom.js", output / "Bridge/cosmaneura-navigation-dom.js")
    if include_desktop:
        shutil.copytree(owned / "Desktop", output / "Desktop")
        for name in ("NativeProviderConnection.swift", "NativeSourceStartOwner.swift", "NativeSourceProofJournal.swift",
                     "NativeSourceRecovery.swift", "NativeCaptureProcessFence.swift", "WorkspaceSourceTransport.swift"):
            shutil.copyfile(owned / "Bridge" / name, output / "Desktop" / name)
    package = '''// swift-tools-version: 6.2
import PackageDescription
let package = Package(
    name: "CosmasNativeAuthQualification", defaultLocalization: "en",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "CosmasNativeAuth", targets: ["CosmasNativeAuth"])],
    targets: [
        .target(name: "ClerkKit", path: "vendor/Sources/ClerkKit",
                resources: [.process("Resources")]),
        .target(name: "CosmasNativeAuth", dependencies: ["ClerkKit"]),
        .testTarget(name: "CosmasNativeAuthTests", dependencies: ["CosmasNativeAuth"]),
    ]
)
'''
    if include_bridge:
        package = package.replace(
            'products: [.library(name: "CosmasNativeAuth", targets: ["CosmasNativeAuth"])],',
            '''products: [
        .library(name: "CosmasNativeAuth", targets: ["CosmasNativeAuth"]),
        .library(name: "CosmasWorkspaceAuthPlugin", targets: ["CosmasWorkspaceAuthPlugin"]),
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", exact: "8.5.0"),
    ],''',
        ).replace(
            '        .testTarget(name: "CosmasNativeAuthTests",',
            '''        .target(name: "CosmasWorkspaceAuthPlugin", dependencies: [
            "CosmasNativeAuth", .product(name: "Capacitor", package: "capacitor-swift-pm"),
        ], path: "Bridge", resources: [.copy("cosmaneura-navigation-dom.js")]),
        .testTarget(name: "CosmasNativeAuthTests",''',
        )
    if include_desktop:
        if include_bridge:
            raise ValueError("Qualify desktop and Apple bridge compositions separately.")
        package = package.replace(
            'products: [.library(name: "CosmasNativeAuth", targets: ["CosmasNativeAuth"])],',
            '''products: [
        .library(name: "CosmasNativeAuth", targets: ["CosmasNativeAuth"]),
        .executable(name: "CosmasDesktopAuth", targets: ["CosmasDesktopAuth"]),
    ],''',
        ).replace(
            '        .testTarget(name: "CosmasNativeAuthTests",',
            '''        .executableTarget(name: "CosmasDesktopAuth", dependencies: ["CosmasNativeAuth"],
                          path: "Desktop"),
        .testTarget(name: "CosmasNativeAuthTests",''',
        )
    (output / "Package.swift").write_text(package)
    (output / "qualification.json").write_text(json.dumps({
        "purpose": "local-synthetic-native-auth-core-qualification",
        "clerk_version": CLERK_VERSION,
        "includes_capacitor_bridge": include_bridge,
        "includes_desktop_helper": include_desktop,
        "native_identity_profile_version": 1,
        "native_source_version": 1,
        "archive_sha256": ARCHIVE_SHA256,
        "sdk_source_sha256": source_hashes,
        "composed_sha256": {
            str(path.relative_to(output)): digest(path)
            for path in sorted(output.rglob("*")) if path.is_file()
        },
        "limits": ["No live identity", "No SDK configuration or Keychain operations",
                   "No hosted browser", "No app installation or signing"],
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clerk-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-desktop", action="store_true")
    arguments = parser.parse_args()
    prepare(arguments.clerk_archive, arguments.output, include_desktop=arguments.include_desktop)
    print(f"Prepared native auth qualification package: {arguments.output}")
