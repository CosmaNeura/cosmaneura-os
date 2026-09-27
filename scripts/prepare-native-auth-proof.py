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
    shared_capture_packages: bool = False,
) -> None:
    root = Path(__file__).resolve().parents[1]
    archive, output = archive.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("Use a fresh qualification directory outside the source tree.")
    if shared_capture_packages and (not include_bridge or include_desktop):
        raise ValueError("Shared capture packages require an Apple bridge composition.")
    if include_bridge and include_desktop:
        raise ValueError("Qualify desktop and Apple bridge compositions separately.")
    capture_root = output.parent if shared_capture_packages else output / "Sources"
    if shared_capture_packages and (
        not (capture_root / "ios-pcm-capture/Package.swift").is_file()
        or any((capture_root / name).exists() for name in ("native-recording", "native-recording-pcm"))
    ):
        raise ValueError("Shared capture requires the PCM package and fresh native recording destinations.")
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
    if include_bridge or include_desktop:
        packages = {"native-recording": "native-recording", "native-recording-pcm": "native-recording-pcm"}
        if not shared_capture_packages:
            packages["ios-pcm-capture"] = "native-configured/ios-pcm-capture"
        for destination, source in packages.items():
            recording = root / "clients/capture" / source
            for folder in ("Sources", "Tests"):
                if (recording / folder).is_dir():
                    shutil.copytree(recording / folder, capture_root / destination / folder)
            for name in ("Package.swift", "UPSTREAM.json"):
                if (recording / name).is_file():
                    shutil.copyfile(recording / name, capture_root / destination / name)
        # Both package layouts use one PCM core. In an Apple app this is also
        # the exact package used by the existing renderer capture plugin.
        pcm_package = capture_root / "native-recording-pcm/Package.swift"
        pcm_text = pcm_package.read_text()
        marker = 'path: "../native-configured/ios-pcm-capture"'
        if pcm_text.count(marker) != 1:
            raise ValueError("Native recording PCM dependency layout changed.")
        pcm_package.write_text(pcm_text.replace(marker, 'path: "../ios-pcm-capture"'))
    if include_bridge:
        shutil.copytree(owned / "Bridge", output / "Bridge")
        shutil.copyfile(root / "clients/shared/cosmaneura-navigation-dom.js", output / "Bridge/cosmaneura-navigation-dom.js")
    if include_desktop:
        shutil.copytree(owned / "Desktop", output / "Desktop")
        for name in ("NativeProviderConnection.swift", "NativeSourceStartOwner.swift", "NativeSourceProofJournal.swift",
                     "NativeSourceRecovery.swift", "NativeCaptureProcessFence.swift", "WorkspaceSourceTransport.swift",
                     "NativeProviderRecordingService.swift"):
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
        .package(path: "__NATIVE_RECORDING__"),
        .package(path: "__NATIVE_RECORDING_PCM__"),
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", exact: "8.5.0"),
    ],''',
        ).replace(
            '        .testTarget(name: "CosmasNativeAuthTests",',
            '''        .target(name: "CosmasWorkspaceAuthPlugin", dependencies: [
            "CosmasNativeAuth", .product(name: "Capacitor", package: "capacitor-swift-pm"),
            .product(name: "CosmaneuraNativeRecording", package: "native-recording"),
            .product(name: "CosmaneuraNativeRecordingPCM", package: "native-recording-pcm"),
        ], path: "Bridge", resources: [.copy("cosmaneura-navigation-dom.js")]),
        .testTarget(name: "CosmasNativeAuthTests",''',
        )
    if include_desktop:
        package = package.replace(
            'products: [.library(name: "CosmasNativeAuth", targets: ["CosmasNativeAuth"])],',
            '''products: [
        .library(name: "CosmasNativeAuth", targets: ["CosmasNativeAuth"]),
        .executable(name: "CosmasDesktopAuth", targets: ["CosmasDesktopAuth"]),
    ],
    dependencies: [
        .package(path: "__NATIVE_RECORDING__"),
        .package(path: "__NATIVE_RECORDING_PCM__"),
    ],''',
        ).replace(
            '        .testTarget(name: "CosmasNativeAuthTests",',
            '''        .executableTarget(name: "CosmasDesktopAuth", dependencies: [
            "CosmasNativeAuth", .product(name: "CosmaneuraNativeRecording", package: "native-recording"),
            .product(name: "CosmaneuraNativeRecordingPCM", package: "native-recording-pcm"),
        ],
                          path: "Desktop"),
        .testTarget(name: "CosmasNativeAuthTests",''',
        )
    package_prefix = ".." if shared_capture_packages else "Sources"
    package = package.replace("__NATIVE_RECORDING__", f"{package_prefix}/native-recording")
    package = package.replace("__NATIVE_RECORDING_PCM__", f"{package_prefix}/native-recording-pcm")
    (output / "Package.swift").write_text(package)
    (output / "qualification.json").write_text(json.dumps({
        "purpose": "local-synthetic-native-auth-core-qualification",
        "clerk_version": CLERK_VERSION,
        "includes_capacitor_bridge": include_bridge,
        "includes_desktop_helper": include_desktop,
        "shared_capture_packages": shared_capture_packages,
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
