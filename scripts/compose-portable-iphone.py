#!/usr/bin/env python3
"""Compose iPhone project inputs from owned clients and the frozen app scaffold.

apps/capture stays frozen 1107 evidence. Shared implementation files come from
clients/apple and clients/capture. This entry does not read an external
snapshot, modify the scaffold, sign, or compile.
"""

import argparse
import hashlib
import json
import plistlib
import re
import shutil
from pathlib import Path

IMPLEMENTATION_OWNERS = ("clients/apple", "clients/capture")
SUPPORTING_CLIENT = "clients/shared"
APP_SCAFFOLD = "apps/capture"
PROVENANCE_NAME = "SOURCE_PROVENANCE.json"
OWNED_CAPACITOR_VENDOR = "clients/apple/vendor/capacitor-swift-pm-8.5.0"
COMPOSED_CAPACITOR_VENDOR = "native-plugins/capacitor-swift-pm"
REMOTE_CAPACITOR_PACKAGE_URL = "https://github.com/ionic-team/capacitor-swift-pm.git"
OWNED_CAPACITOR_RELEASE_SHA256 = {
    "Capacitor.xcframework.zip": "357220fe6dad73cb78bc1dc83e16e89d59c3d7dac8f9b17545a5be64bba25130",
    "Cordova.xcframework.zip": "a3dc72b5a559948d548f0ee2926b989492acc1023a0c86a1bf85477587f83a10",
}
OWNED_CAPACITOR_FRAMEWORK_INFO_SHA256 = {
    "Capacitor.xcframework/Info.plist": "713105ab60c0f696453457049eee406997bbe4435b8c48ae877101303c5272fe",
    "Cordova.xcframework/Info.plist": "25ef8fe4b91042eaeb5a52cafa72ad1327ac35b194f265ffc53ab269a1d8a452",
}
# Package manifests rewritten from remote Capacitor URL to the owned local path.
CAPACITOR_LOCALIZATION_TARGETS = (
    "ios/App/CapApp-SPM/Package.swift",
    "native-plugins/cosmas-native-auth/Package.swift",
    "native-plugins/ios-pcm-capacitor/Package.swift",
    "native-plugins/secure-queue/Package.swift",
)
# The frozen 1107 manifest cannot name later owned implementations. Place only
# these reviewed additions; never glob an SDK, external checkout or generated app.
NATIVE_PRACTICE_ADDITIONS = (
    "Sources/CosmasNativeAuth/NativePracticeProfile.swift",
    "Sources/CosmasNativeAuth/NativePracticeActivationOwner.swift",
    "Sources/CosmasNativeAuth/NativePracticeConnectionContracts.swift",
    "Sources/CosmasNativeAuth/NativePracticeWorkspaceBootstrap.swift",
    "Sources/CosmasNativeAuth/NativePracticeAccountTransport.swift",
    "Sources/CosmasNativeAuth/NativePracticeSelectionStore.swift",
    "Bridge/CosmasNativePracticeConnectionPlugin.swift",
    "Bridge/NativePracticeConnectionController.swift",
    "Tests/CosmasNativeAuthTests/NativePracticeProfileTests.swift",
    "Tests/CosmasNativeAuthTests/NativePracticeBootstrapTests.swift",
    "Tests/CosmasNativeAuthTests/NativePracticeConnectionContractTests.swift",
    "Tests/CosmasNativeAuthTests/NativePracticeOriginAndSelectionTests.swift",
    "Tests/CosmasNativeAuthTests/NativePracticeProductionTests.swift",
)
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


REVIEWED_MICROPHONE_USAGE = (
    "CosmaBot uses the microphone to record visits you choose to capture so it can draft your notes."
)
REVIEWED_SPEECH_USAGE = (
    "CosmaBot uses on-device speech recognition to transcribe recordings you choose to "
    "transcribe so it can draft your notes."
)
REVIEWED_SYNTHETIC_MICROPHONE_USAGE = (
    "CosmaBot uses the microphone only after you start a synthetic capture test with "
    "invented encounter audio."
)
REVIEWED_APP_PRIVACY = {
    "NSPrivacyTracking": False,
    "NSPrivacyCollectedDataTypes": [
        {
            "NSPrivacyCollectedDataType": "NSPrivacyCollectedDataTypeAudioData",
            "NSPrivacyCollectedDataTypeLinked": True,
            "NSPrivacyCollectedDataTypeTracking": False,
            "NSPrivacyCollectedDataTypePurposes": [
                "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
        },
        {
            "NSPrivacyCollectedDataType": "NSPrivacyCollectedDataTypeUserID",
            "NSPrivacyCollectedDataTypeLinked": True,
            "NSPrivacyCollectedDataTypeTracking": False,
            "NSPrivacyCollectedDataTypePurposes": [
                "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
        },
        {
            "NSPrivacyCollectedDataType": "NSPrivacyCollectedDataTypeEmailAddress",
            "NSPrivacyCollectedDataTypeLinked": True,
            "NSPrivacyCollectedDataTypeTracking": False,
            "NSPrivacyCollectedDataTypePurposes": [
                "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
        },
        {
            "NSPrivacyCollectedDataType": "NSPrivacyCollectedDataTypeName",
            "NSPrivacyCollectedDataTypeLinked": True,
            "NSPrivacyCollectedDataTypeTracking": False,
            "NSPrivacyCollectedDataTypePurposes": [
                "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
        },
        {
            "NSPrivacyCollectedDataType": "NSPrivacyCollectedDataTypeHealth",
            "NSPrivacyCollectedDataTypeLinked": True,
            "NSPrivacyCollectedDataTypeTracking": False,
            "NSPrivacyCollectedDataTypePurposes": [
                "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
        },
        {
            "NSPrivacyCollectedDataType": "NSPrivacyCollectedDataTypeOtherUserContent",
            "NSPrivacyCollectedDataTypeLinked": True,
            "NSPrivacyCollectedDataTypeTracking": False,
            "NSPrivacyCollectedDataTypePurposes": [
                "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
        },
        {
            "NSPrivacyCollectedDataType": "NSPrivacyCollectedDataTypeDeviceID",
            "NSPrivacyCollectedDataTypeLinked": True,
            "NSPrivacyCollectedDataTypeTracking": False,
            "NSPrivacyCollectedDataTypePurposes": [
                "NSPrivacyCollectedDataTypePurposeAppFunctionality",
            ],
        },
    ],
    "NSPrivacyAccessedAPITypes": [
        {
            "NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategorySystemBootTime",
            "NSPrivacyAccessedAPITypeReasons": ["35F9.1"],
        }
    ],
}


def refuse_non_true_export_compliance(info: dict) -> None:
    """Refuse any present export-compliance value that is not boolean True.

    A pre-existing boolean true is preserved. The key is never written. The
    YES/NO answer and questionnaire remain an owner decision outside composition.
    """
    if "ITSAppUsesNonExemptEncryption" not in info:
        return
    if info["ITSAppUsesNonExemptEncryption"] is True:
        return
    raise ValueError(
        "Refusing ITSAppUsesNonExemptEncryption value that is not boolean true; "
        "export-compliance key is owner-controlled."
    )


def _apply_owned_usage_descriptions(
    repository: Path, output: Path, placed: list[dict[str, object]]
) -> None:
    """Derive reviewed permission copy without changing the frozen scaffold Info.plist."""
    info_path = "ios/App/App/Info.plist"
    destination = output / APP_SCAFFOLD / info_path
    if not destination.is_file() or destination.is_symlink():
        raise ValueError("Composed app Info.plist is missing.")
    project_text = (output / APP_SCAFFOLD / "ios/App/App.xcodeproj/project.pbxproj").read_text(
        encoding="utf-8"
    )
    if "INFOPLIST_KEY_ITSAppUsesNonExemptEncryption" in project_text:
        raise ValueError(
            "Refusing INFOPLIST_KEY_ITSAppUsesNonExemptEncryption in the composed project; "
            "export-compliance key is owner-controlled."
        )
    original_sha256 = _digest(destination)
    info = plistlib.loads(destination.read_bytes())
    # Export-compliance key intentionally not set by this script; owner decision pending.
    refuse_non_true_export_compliance(info)
    info["NSMicrophoneUsageDescription"] = REVIEWED_MICROPHONE_USAGE
    info["NSSpeechRecognitionUsageDescription"] = REVIEWED_SPEECH_USAGE
    destination.write_bytes(plistlib.dumps(info, sort_keys=False))
    record = next(item for item in placed if item["path"] == info_path)
    derivation_path = "scripts/compose-portable-iphone.py"
    derivation = _regular_file(repository, repository / derivation_path)
    record.update(
        {
            "role": "derived-usage-description",
            "sha256": _digest(destination),
            "scaffold_input_sha256": original_sha256,
            "derivation_source": derivation_path,
            "derivation_source_sha256": _digest(derivation),
            "wiring_note": (
                "Derived microphone and speech usage descriptions; frozen scaffold "
                "Info.plist unchanged. Export-compliance key intentionally not set by "
                "this script; owner decision pending."
            ),
        }
    )


def _add_owned_app_privacy(repository: Path, output: Path, placed: list[dict[str, object]]) -> None:
    """Derive app privacy resources without changing the frozen scaffold."""
    source_path = "clients/apple/startup-recovery/PrivacyInfo.xcprivacy"
    source = _regular_file(repository, repository / source_path)
    expected = REVIEWED_APP_PRIVACY
    if plistlib.loads(source.read_bytes()) != expected:
        raise ValueError(
            "Owned app privacy manifest differs from reviewed collected-data and "
            "required-reason coverage."
        )
    app = output / APP_SCAFFOLD / "ios/App/App"
    destination = app / "PrivacyInfo.xcprivacy"
    if destination.exists() or destination.is_symlink():
        raise ValueError("App privacy resource already exists in the derived scaffold.")
    project_path = "ios/App/App.xcodeproj/project.pbxproj"
    project = output / APP_SCAFFOLD / project_path
    original_sha256 = _digest(project)
    text = project.read_text(encoding="utf-8")
    replacements = [
        (
            "\t\tC03110000000000000000004 /* WorkspaceSceneSignalState.swift in Sources */ = {isa = PBXBuildFile; fileRef = C03100000000000000000004 /* WorkspaceSceneSignalState.swift */; };",
            "\t\tC03110000000000000000004 /* WorkspaceSceneSignalState.swift in Sources */ = {isa = PBXBuildFile; fileRef = C03100000000000000000004 /* WorkspaceSceneSignalState.swift */; };\n\t\tC03110000000000000000005 /* PrivacyInfo.xcprivacy in Resources */ = {isa = PBXBuildFile; fileRef = C03100000000000000000005 /* PrivacyInfo.xcprivacy */; };",
        ),
        (
            '\t\tC03100000000000000000004 /* WorkspaceSceneSignalState.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = WorkspaceSceneSignalState.swift; sourceTree = "<group>"; };',
            '\t\tC03100000000000000000004 /* WorkspaceSceneSignalState.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = WorkspaceSceneSignalState.swift; sourceTree = "<group>"; };\n\t\tC03100000000000000000005 /* PrivacyInfo.xcprivacy */ = {isa = PBXFileReference; lastKnownFileType = text.xml; path = PrivacyInfo.xcprivacy; sourceTree = "<group>"; };',
        ),
        (
            "\t\t\t\tC03100000000000000000004 /* WorkspaceSceneSignalState.swift */,",
            "\t\t\t\tC03100000000000000000004 /* WorkspaceSceneSignalState.swift */,\n\t\t\t\tC03100000000000000000005 /* PrivacyInfo.xcprivacy */,",
        ),
        (
            "\t\t\t\t2FAD9763203C412B000D30F8 /* config.xml in Resources */,",
            "\t\t\t\t2FAD9763203C412B000D30F8 /* config.xml in Resources */,\n\t\t\t\tC03110000000000000000005 /* PrivacyInfo.xcprivacy in Resources */,",
        ),
    ]
    for anchor, replacement in replacements:
        if text.count(anchor) != 1:
            raise ValueError("App privacy resource wiring differs from the reviewed scaffold.")
        text = text.replace(anchor, replacement, 1)
    project_record = next(item for item in placed if item["path"] == project_path)
    derivation_path = "scripts/compose-portable-iphone.py"
    derivation = _regular_file(repository, repository / derivation_path)
    shutil.copyfile(source, destination)
    project.write_text(text, encoding="utf-8")
    project_record.update(
        {
            "role": "derived-app-resource-wiring",
            "sha256": _digest(project),
            "scaffold_input_sha256": original_sha256,
            "derivation_source": derivation_path,
            "derivation_source_sha256": _digest(derivation),
            "wiring_note": "Derived app-owned privacy resource wiring; frozen scaffold source unchanged.",
        }
    )
    placed.append(
        {
            "path": "ios/App/App/PrivacyInfo.xcprivacy",
            "role": "implementation",
            "owner": "clients/apple",
            "sha256": _digest(destination),
            "authoritative_counterpart": source_path,
            "wiring_note": (
                "App-owned privacy resource: system boot time required-reason, "
                "tracking=false, and collected-data declarations for audio, user ID, "
                "email, name, health, other user content, and device ID."
            ),
        }
    )


def _capacitor_local_path(package_swift: str) -> str:
    if package_swift.startswith("ios/App/"):
        return "../../../" + COMPOSED_CAPACITOR_VENDOR
    if package_swift.startswith("native-plugins/"):
        return "../capacitor-swift-pm"
    raise ValueError(f"No owned Capacitor path for {package_swift}")


def _localize_capacitor_package_text(text: str, local_path: str) -> str:
    """Replace remote or clients-tree Capacitor pins with the composed local path."""
    if local_path in text and text.count(f'path: "{local_path}"') == 1 and REMOTE_CAPACITOR_PACKAGE_URL not in text:
        raise ValueError("Capacitor package already names the composed local path.")
    clients_vendor = "../../../apple/vendor/capacitor-swift-pm-8.5.0"
    replacement = f'.package(name: "capacitor-swift-pm", path: "{local_path}")'
    candidates = [
        f'.package(url: "{REMOTE_CAPACITOR_PACKAGE_URL}", exact: "8.5.0")',
        f'.package(name: "capacitor-swift-pm", path: "{clients_vendor}")',
    ]
    multiline_remote = re.compile(
        r'\.package\(\s*url:\s*"'
        + re.escape(REMOTE_CAPACITOR_PACKAGE_URL)
        + r'"\s*,\s*exact:\s*"8\.5\.0"\s*\)',
        re.MULTILINE,
    )
    multiline_clients = re.compile(
        r'\.package\(\s*name:\s*"capacitor-swift-pm"\s*,\s*path:\s*"'
        + re.escape(clients_vendor)
        + r'"\s*\)',
        re.MULTILINE,
    )
    updated = None
    for single in candidates:
        if text.count(single) == 1:
            updated = text.replace(single, replacement, 1)
            break
    if updated is None:
        for pattern in (multiline_remote, multiline_clients):
            matches = list(pattern.finditer(text))
            if len(matches) == 1:
                updated = pattern.sub(replacement, text, count=1)
                break
    if updated is None:
        raise ValueError("Capacitor package declaration is not exactly one reviewed pin.")
    if (
        REMOTE_CAPACITOR_PACKAGE_URL in updated
        or clients_vendor in updated
        or updated.count(replacement) != 1
    ):
        raise ValueError("Failed to localize the Capacitor package to the owned path.")
    return updated


def _add_owned_capacitor_vendor(repository: Path, output: Path, placed: list[dict[str, object]]) -> None:
    """Copy the owned Capacitor mirror and retire remote binary package URLs."""
    vendor = repository / OWNED_CAPACITOR_VENDOR
    manifest_path = vendor / "SOURCE_MANIFEST.json"
    manifest = json.loads(_regular_file(repository, manifest_path).read_text(encoding="utf-8"))
    if (
        manifest.get("version") != "8.5.0"
        or manifest.get("upstream_revision") != "4f71d0b979f2f957326f04353eca7604ee937e1e"
        or manifest.get("remote_binary_targets_retired") is not True
    ):
        raise ValueError("Owned Capacitor vendor manifest is not the reviewed 8.5.0 mirror.")
    assets = {
        item["name"]: item["sha256"]
        for item in manifest.get("release_assets", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if assets != OWNED_CAPACITOR_RELEASE_SHA256:
        raise ValueError("Owned Capacitor release asset digests drifted from the reviewed mirror.")
    for relative, digest in OWNED_CAPACITOR_FRAMEWORK_INFO_SHA256.items():
        info = _regular_file(repository, vendor / relative)
        if _digest(info) != digest:
            raise ValueError(f"Owned Capacitor framework identity drifted: {relative}")

    destination_root = output / APP_SCAFFOLD / COMPOSED_CAPACITOR_VENDOR
    if destination_root.exists() or destination_root.is_symlink():
        raise ValueError("Owned Capacitor vendor destination already exists.")
    destination_root.mkdir(parents=True)
    for path in sorted(vendor.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Owned Capacitor vendor contains a symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(vendor).as_posix()
        if relative.startswith(".") or ".." in Path(relative).parts:
            raise ValueError(f"Refusing an unsafe Capacitor vendor path: {relative}")
        source = _regular_file(repository, path)
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if _digest(destination) != _digest(source):
            raise ValueError(f"Owned Capacitor copy changed: {relative}")
        placed.append(
            {
                "path": f"{COMPOSED_CAPACITOR_VENDOR}/{relative}",
                "role": "implementation",
                "owner": "clients/apple",
                "sha256": _digest(destination),
                "authoritative_counterpart": f"{OWNED_CAPACITOR_VENDOR}/{relative}",
                "wiring_note": "Owned Capacitor 8.5.0 mirror; remote binary zip downloads retired.",
            }
        )

    derivation_path = "scripts/compose-portable-iphone.py"
    derivation = _regular_file(repository, repository / derivation_path)
    for package_path in CAPACITOR_LOCALIZATION_TARGETS:
        package = output / APP_SCAFFOLD / package_path
        record = next(item for item in placed if item["path"] == package_path)
        prior_role = record["role"]
        if prior_role == "implementation" and isinstance(record.get("authoritative_counterpart"), str):
            localization_input = record["authoritative_counterpart"]
        elif prior_role in {"app-scaffold", "scaffold-package-wiring"}:
            localization_input = f"{APP_SCAFFOLD}/{package_path}"
        else:
            raise ValueError(f"Capacitor localization lost its input owner: {package_path}")
        original = package.read_text(encoding="utf-8")
        original_sha256 = _digest(package)
        if _digest(repository / localization_input) != original_sha256:
            raise ValueError(f"Capacitor localization input drifted: {localization_input}")
        local_path = _capacitor_local_path(package_path)
        updated = _localize_capacitor_package_text(original, local_path)
        package.write_text(updated, encoding="utf-8")
        record.update(
            {
                "role": "derived-capacitor-localization",
                "sha256": _digest(package),
                "scaffold_input_sha256": original_sha256,
                "localization_input": localization_input,
                "localized_capacitor_path": local_path,
                "derivation_source": derivation_path,
                "derivation_source_sha256": _digest(derivation),
                "wiring_note": (
                    "Localized Capacitor dependency from remote or clients-tree pin "
                    "to the owned composed Capacitor vendor path."
                ),
            }
        )

    resolved_path = "ios/App/App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
    resolved = output / APP_SCAFFOLD / resolved_path
    record = next(item for item in placed if item["path"] == resolved_path)
    original_sha256 = _digest(resolved)
    localization_input = f"{APP_SCAFFOLD}/{resolved_path}"
    if _digest(repository / localization_input) != original_sha256:
        raise ValueError("Package.resolved localization input drifted from the frozen scaffold.")
    original = json.loads(resolved.read_text(encoding="utf-8"))
    pins = original.get("pins")
    if not isinstance(pins, list) or len(pins) != 1:
        raise ValueError("Frozen Package.resolved must pin only Capacitor before localization.")
    pin = pins[0]
    if (
        not isinstance(pin, dict)
        or pin.get("identity") != "capacitor-swift-pm"
        or pin.get("kind") != "remoteSourceControl"
        or not isinstance(pin.get("location"), str)
        or REMOTE_CAPACITOR_PACKAGE_URL not in pin["location"]
    ):
        raise ValueError("Frozen Package.resolved is not the reviewed Capacitor remote pin.")
    localized = {"pins": [], "version": original.get("version", 2)}
    resolved.write_text(json.dumps(localized, indent=2) + "\n", encoding="utf-8")
    record.update(
        {
            "role": "derived-capacitor-localization",
            "sha256": _digest(resolved),
            "scaffold_input_sha256": original_sha256,
            "localization_input": localization_input,
            "derivation_source": derivation_path,
            "derivation_source_sha256": _digest(derivation),
            "wiring_note": "Cleared remote Capacitor pin; owned local package path supplies Capacitor/Cordova.",
        }
    )

    composed_text = "\n".join(
        (output / APP_SCAFFOLD / path).read_text(encoding="utf-8")
        for path in (*CAPACITOR_LOCALIZATION_TARGETS, resolved_path)
    )
    if REMOTE_CAPACITOR_PACKAGE_URL in composed_text or "remoteSourceControl" in composed_text:
        raise ValueError("Composed iPhone inputs still name the remote Capacitor package.")


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

    for addition in NATIVE_PRACTICE_ADDITIONS:
        relative = _relative(addition)
        key = (Path("native-plugins/cosmas-native-auth") / relative).as_posix()
        if key in seen:
            raise ValueError(f"Owned native practice addition duplicates frozen wiring: {key}")
        seen.add(key)
        counterpart = (Path("clients/apple/native-auth") / relative).as_posix()
        source = _regular_file(repository, repository / counterpart)
        plan.append({
            "path": key,
            "role": "implementation",
            "owner": "clients/apple",
            "source": source,
            "authoritative_counterpart": counterpart,
            "wiring_note": "Explicit owned native practice addition; frozen scaffold unchanged.",
        })

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
        _add_owned_app_privacy(repository, output, placed)
        _apply_owned_usage_descriptions(repository, output, placed)
        _add_owned_capacitor_vendor(repository, output, placed)
        manifest = {
            "purpose": "portable-iphone-project-inputs",
            "qualified_install": False,
            "compiled_signed_or_installed": False,
            "external_snapshot_required": False,
            "remote_capacitor_package_required": False,
            "owned_capacitor_vendor": OWNED_CAPACITOR_VENDOR,
            "composed_capacitor_vendor": f"{APP_SCAFFOLD}/{COMPOSED_CAPACITOR_VENDOR}",
            "app_scaffold": APP_SCAFFOLD,
            "scaffold_role": "frozen-1107-evidence",
            "implementation_owners": list(IMPLEMENTATION_OWNERS),
            "supporting_clients": [SUPPORTING_CLIENT],
            "scaffold_package_wiring": sorted(SCAFFOLD_PACKAGE_WIRING),
            "native_practice_additions": list(NATIVE_PRACTICE_ADDITIONS),
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
