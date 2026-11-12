"""The recovered iPhone tree is frozen 1107 evidence, not a qualified new build."""

import hashlib
import importlib.util
import json
import plistlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROVENANCE = ROOT / "apps/capture/SOURCE_PROVENANCE.json"
APPLE_PREPARE = ROOT / "scripts/prepare-apple-synthetic.py"
PORTABLE_COMPOSE = ROOT / "scripts/compose-portable-iphone.py"
APP_INFO = ROOT / "apps/capture/ios/App/App/Info.plist"
OWNED_PRIVACY = ROOT / "clients/apple/startup-recovery/PrivacyInfo.xcprivacy"
RECORDING_ENCRYPTION = (
    ROOT
    / "clients/capture/native-recording/Sources/CosmaneuraNativeRecording/NativeRecordingEncryption.swift"
)
SECURE_QUEUE = (
    ROOT
    / "clients/capture/native-configured/secure-queue/ios/Sources/CosmaneuraSecureQueue/SecureQueueStore.swift"
)
SPEECH_PLUGIN = ROOT / "clients/apple/native-auth/Bridge/CosmasPrivateSpeechPlugin.swift"
MICROPHONE_USAGE = (
    "CosmaBot uses the microphone to record visits you choose to capture so it can draft your notes."
)
SPEECH_USAGE = (
    "CosmaBot uses on-device speech recognition to transcribe recordings you choose to "
    "transcribe so it can draft your notes."
)
EXPECTED_APP_PRIVACY = {
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
SYNTHETIC_MICROPHONE_USAGE = (
    "CosmaBot uses the microphone only after you start a synthetic capture test with "
    "invented encounter audio."
)
EXTERNAL_CAPTURE_SNAPSHOT = "ea7f99d0278a05706531ffb1288cb1df7acf507b"
FROZEN_CAPTURE_PROVENANCE_SHA256 = "7b036ef60bf1141b575dad0f8c46dc4cdc1dfa01b7b4ac7e3276ff06b0e17c54"

# Reviewed owned-source evolution for the native practice connection. These
# exact current bytes supplement, never rewrite, frozen 1107 provenance. Every
# unlisted counterpart retains its original recorded SHA assertion below.
REVIEWED_PRACTICE_CONNECTION_COUNTERPART_SHA256 = {
    "clients/apple/startup-recovery/CosmasBridgeViewController.swift": "43529246e2049613e96162591dfa9aef10652957f7c987d29db0f416343fb385",
    "clients/apple/startup-recovery/CosmasWorkspaceViewController.swift": "3ed5a94c6ccfc309ee60b49c1e46aebf07b603a3168fc80583a5811bae19fe65",
    "clients/apple/startup-recovery/WorkspaceRecoveryState.swift": "c07f68af3d311b75890108c4fc5c04b5e38eeeda11cb0047f25424a04531cfd1",
    "clients/apple/native-auth/Bridge/CosmasWorkspaceAuthPlugin.swift": "8132283f189b8cd0497957326fbcc020efc44e7c4b9fe2327ce0248b44d9494f",
    "clients/apple/native-auth/Bridge/NativeProviderConnection.swift": "61b1c30c279a940f3ffab824a74fe21aba01cdc053d63ed59530b9d12bde2ce9",
    "clients/apple/native-auth/Bridge/NativeProviderRecordingRuntime.swift": "c0e570f99371e1fa07ccac58db1a56db0c7994323fb50d1f8af5d98d462279c4",
    "clients/apple/native-auth/Bridge/NativeSourceProofJournal.swift": "851c0e23018aab0c898bd8563108aabfcf0ce07a4925af161e6d2fbda43e7c39",
    "clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKitWorkspaceDriver.swift": "7713db8afa3959ac9c936a4008aecb2144d4d62dedc9649fd21490fbdbcb88af",
    "clients/apple/native-auth/Sources/CosmasNativeAuth/DesktopAuthProtocol.swift": "4a870405efcc894c7e1769c4a04c6a238ef3389767aa3c630ac24bc7cf0cca22",
    "clients/apple/native-auth/Sources/CosmasNativeAuth/GoogleConnectionNavigation.swift": "f5e7b2606ed7972d9f96ea1cb8631c0fed84e902477d34f0946e13d639f4bdb5",
    "clients/apple/native-auth/Sources/CosmasNativeAuth/KeychainAccessBlock.swift": "9c0db1b40bba34d2be169f0dff57bfd9a59ae3f3115a98b25153e9636429a6b3",
    "clients/apple/native-auth/Sources/CosmasNativeAuth/MicrosoftConnectionNavigation.swift": "aecc572273fd6a83ba2f328273389c91f74368d781c31f7be8eb435e0d9a49b0",
    "clients/apple/native-auth/Sources/CosmasNativeAuth/NativeAuthAwait.swift": "48f59a9ade9ceca9e30c82c13c4bccbea0c69a45d26c9fefa2d4eaabc9a8501d",
    "clients/apple/native-auth/Sources/CosmasNativeAuth/NativeClerkConfiguration.swift": "d95000893180707983b2b244bdbfdc3f8b4f69bf2e693e0cc4ba31dc542e81c6",
    "clients/apple/native-auth/Sources/CosmasNativeAuth/NativeTokenPolicy.swift": "f951145dbfabb7bc7244633b60267ddd65ba31ff378613f1fb75360f9a890298",
    "clients/apple/native-auth/Sources/CosmasNativeAuth/NativeWorkspaceAuth.swift": "c777eeac82ccc9cc54e9b400ee2eefd1761dca74ca156355dc64da041699b717",
    "clients/apple/native-auth/Tests/CosmasNativeAuthTests/DesktopAuthProtocolTests.swift": "2833750395acfdd6d0becc3779322538aa375a1e2fe79ff27d04c82b6b820d81",
    "clients/apple/native-auth/Tests/CosmasNativeAuthTests/GoogleConnectionNavigationTests.swift": "7f25b506b325cfbf76e7fc4ad1082c2406ca238f5ef054793de8213dda3c8eba",
    "clients/apple/native-auth/Tests/CosmasNativeAuthTests/KeychainInteractionPolicyTests.swift": "56391c581b190e2e7a1176a874925219d41ae99a8c494028830a5eeaa6b58af4",
    "clients/apple/native-auth/Tests/CosmasNativeAuthTests/NativeClerkConfigurationTests.swift": "2f73afb1229e55dad9b29845a1721fecb444647aeae211c5f0ae3c009861c597",
    "clients/apple/native-auth/Tests/CosmasNativeAuthTests/NativePrivateRecordingGateTests.swift": "64f3e14a85b5ea321acedb01526ef6aa1f253dfe43266c349fec58ef2473b984",
    "clients/apple/native-auth/Tests/CosmasNativeAuthTests/NativeWorkspaceAuthTests.swift": "dda52ed7cbf2976050d93be2a97de0f4474ba7ea348e1bb967cf94603f62c83a",
}

# Owned Capacitor path pins in capture package manifests. Historical recovery
# still records the remote binary package URL; current owners use the reviewed
# local mirror under clients/apple/vendor/capacitor-swift-pm-8.5.1.
REVIEWED_OWNED_CAPACITOR_COUNTERPART_SHA256 = {
    "clients/capture/native-configured/ios-pcm-capacitor/Package.swift": "33d141a2d7abe06f71ad8ae5b92a6f6893598bba21d78c490e4833a1329f5f2b",
    "clients/capture/native-configured/secure-queue/Package.swift": "31981af9e8ec7723052bd187ddee047bf73a8614637ec9213c4ea56f4ddb4ce1",
}

# Reviewed owned IOSPCM plugin evolution (DEBUG synthetic XCUITest start path).
# Supplements frozen 1107 provenance; does not rewrite apps/capture copies.
REVIEWED_OWNED_IOSPCM_PLUGIN_SHA256 = {
    "clients/capture/native-configured/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor/IOSPCMCapacitorPlugin.swift": (
        "444387e76a6e5099766f70cf3ff79c28b01bb4204f6a49016e38ef40914f3db9"
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_recovered_capture_matches_its_recorded_evidence_and_stays_unqualified():
    assert _sha256(PROVENANCE) == FROZEN_CAPTURE_PROVENANCE_SHA256
    record = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert record["compiled_signed_or_installed_by_this_change"] is False
    assert record["native_current_source_build_qualification"].startswith("PENDING")
    assert EXTERNAL_CAPTURE_SNAPSHOT in APPLE_PREPARE.read_text(encoding="utf-8")

    treatments = {item["treatment"] for item in record["files"]}
    assert treatments == {"exact-released-source", "unconfigured-public-settings-template"}
    redacted = [
        item["path"] for item in record["files"]
        if item["treatment"] == "unconfigured-public-settings-template"
    ]
    assert redacted == ["ios/App/App/Info.plist"]

    differed = []
    reviewed_current = set()
    reviewed_capacitor = set()
    reviewed_iospcm = set()
    for item in record["files"]:
        recovered = ROOT / "apps/capture" / item["path"]
        assert _sha256(recovered) == item["repository_sha256"]
        equivalent = item["tracked_equivalent"]
        if equivalent is None:
            continue
        live = ROOT / equivalent["path"]
        if equivalent["path"] == "clients/apple/native-auth/Bridge/NativeCaptureProcessFence.swift":
            current = live.read_text(encoding="utf-8")
            old_header = "// INERT PROPOSAL: not part of any selected app or source package."
            new_header = "// Desktop process fencing; iOS metadata operations are compiled out and fail closed."
            assert current.startswith(new_header + "\n")
            assert current.count("#if os(macOS)") == 4
            fallbacks = re.findall(r"#else\n(.*?)#endif", current, re.DOTALL)
            assert len(fallbacks) == 4
            assert all(part.strip() == "throw NativeFenceError.unavailable" for part in fallbacks)
            macos = re.sub(r"#if os\(macOS\)\n(.*?)#else\n.*?#endif\n", r"\1", current, flags=re.DOTALL)
            assert macos.replace(new_header, old_header, 1) == recovered.read_text(encoding="utf-8")
            iphone = re.sub(r"#if os\(macOS\)\n.*?#else\n(.*?)#endif\n", r"\1", current, flags=re.DOTALL)
            assert re.search(r"\bfstat(?:at)?\s*\(", iphone) is None
        else:
            expected = REVIEWED_PRACTICE_CONNECTION_COUNTERPART_SHA256.get(
                equivalent["path"],
                REVIEWED_OWNED_CAPACITOR_COUNTERPART_SHA256.get(
                    equivalent["path"],
                    REVIEWED_OWNED_IOSPCM_PLUGIN_SHA256.get(
                        equivalent["path"], equivalent["sha256"]
                    ),
                ),
            )
            assert _sha256(live) == expected
            if equivalent["path"] in REVIEWED_PRACTICE_CONNECTION_COUNTERPART_SHA256:
                assert expected != equivalent["sha256"]
                reviewed_current.add(equivalent["path"])
            if equivalent["path"] in REVIEWED_OWNED_CAPACITOR_COUNTERPART_SHA256:
                assert expected != equivalent["sha256"]
                reviewed_capacitor.add(equivalent["path"])
            if equivalent["path"] in REVIEWED_OWNED_IOSPCM_PLUGIN_SHA256:
                assert expected != equivalent["sha256"]
                reviewed_iospcm.add(equivalent["path"])
        same = equivalent["sha256"] == item["repository_sha256"]
        if equivalent["status"] == "byte-identical":
            assert same
        elif equivalent["status"] == "differs":
            assert not same
            differed.append(item["path"])
        else:
            raise AssertionError(equivalent["status"])
    assert reviewed_current == set(REVIEWED_PRACTICE_CONNECTION_COUNTERPART_SHA256)
    assert reviewed_capacitor == set(REVIEWED_OWNED_CAPACITOR_COUNTERPART_SHA256)
    assert reviewed_iospcm == set(REVIEWED_OWNED_IOSPCM_PLUGIN_SHA256)
    assert differed == [
        "native-plugins/cosmas-native-auth/Package.swift",
        "native-plugins/cosmas-native-auth/Sources/CosmasNativeAuth/NativeClerkConfiguration.swift",
        "native-plugins/ios-pcm-capture/Sources/CosmaneuraIOSAVFoundationDriver/AVFoundationPCMDriver.swift",
        "native-plugins/ios-pcm-capture/Sources/CosmaneuraIOSAVFoundationDriver/LiveAVFoundationSystem.swift",
        "native-plugins/native-recording-pcm/Package.swift",
    ]


def test_reviewed_native_counterpart_pins_cover_only_exact_modified_owned_sources():
    record = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    counterparts = [item["tracked_equivalent"] for item in record["files"]
                    if item["tracked_equivalent"] is not None]
    for name, digest in REVIEWED_PRACTICE_CONNECTION_COUNTERPART_SHA256.items():
        assert name.startswith(("clients/apple/startup-recovery/", "clients/apple/native-auth/"))
        assert "/vendor/" not in name.lower() and "/sdk/" not in name.lower()
        assert not name.endswith("Package.swift")
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        historical = [item for item in counterparts if item["path"] == name]
        assert len(historical) == 1
        assert historical[0]["sha256"] != digest
        assert _sha256(ROOT / name) == digest


def test_reviewed_owned_capacitor_package_pins_retire_remote_binary_urls():
    record = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    counterparts = [item["tracked_equivalent"] for item in record["files"]
                    if item["tracked_equivalent"] is not None]
    vendor = ROOT / "clients/apple/vendor/capacitor-swift-pm-8.5.1"
    assert (vendor / "Package.swift").is_file()
    assert (vendor / "Capacitor.xcframework/Info.plist").is_file()
    assert (vendor / "Cordova.xcframework/Info.plist").is_file()
    manifest = json.loads((vendor / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["remote_binary_targets_retired"] is True
    assert manifest["version"] == "8.5.1"
    assert manifest["upstream_revision"] == "6afa7424fd2fcd8ca1e577478e8a00af284b7e82"
    for name, digest in REVIEWED_OWNED_CAPACITOR_COUNTERPART_SHA256.items():
        assert name.startswith("clients/capture/native-configured/")
        assert name.endswith("Package.swift")
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        historical = [item for item in counterparts if item["path"] == name]
        assert len(historical) == 1
        assert historical[0]["sha256"] != digest
        text = (ROOT / name).read_text(encoding="utf-8")
        assert _sha256(ROOT / name) == digest
        assert "https://github.com/ionic-team/capacitor-swift-pm.git" not in text
        assert "clients/apple/vendor/capacitor-swift-pm-8.5.1" in text or \
            "../../../apple/vendor/capacitor-swift-pm-8.5.1" in text


def test_reviewed_owned_iospcm_plugin_pin_covers_synthetic_uitest_start_path():
    record = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    counterparts = [item["tracked_equivalent"] for item in record["files"]
                    if item["tracked_equivalent"] is not None]
    for name, digest in REVIEWED_OWNED_IOSPCM_PLUGIN_SHA256.items():
        assert name.startswith(
            "clients/capture/native-configured/ios-pcm-capacitor/Sources/"
        )
        assert name.endswith("IOSPCMCapacitorPlugin.swift")
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        historical = [item for item in counterparts if item["path"] == name]
        assert len(historical) == 1
        assert historical[0]["sha256"] != digest
        text = (ROOT / name).read_text(encoding="utf-8")
        assert _sha256(ROOT / name) == digest
        assert "uiTestStartRecordingThroughLoadedPlugin" in text
        assert "#if DEBUG" in text
        assert "-COSMAS_UI_TEST_START_CAPTURE" in text


def test_new_account_org_activation_uses_public_sdk_refresh_before_membership_and_fences_each_await():
    """Supported SDK source and await fences; no live sign-in/build claim."""
    sdk = ROOT / "apps/capture/native-plugins/cosmas-native-auth/vendor/Sources/ClerkKit"
    clerk = (sdk / "Core/Clerk.swift").read_text(encoding="utf-8")
    client = (sdk / "Domains/Client/Client.swift").read_text(encoding="utf-8")
    session = (sdk / "Domains/Auth/Session/Session.swift").read_text(encoding="utf-8")
    assert "public func refreshClient() async throws -> Client?" in clerk
    refresh = clerk.split("func refreshClient(skipClientId: Bool)", 1)[1].split(
        "/// Refreshes the current environment", 1
    )[0]
    assert refresh.index("dependencies.clientService.getResponse") < refresh.index("runtime.validateStableRuntime()")
    assert "identityController.applyDecodedClientFallback(" in refresh
    assert "public var sessions: [Session]" in client
    assert "public var lastActiveSessionId: String?" in client
    assert "public var user: User?" in session

    driver = (ROOT / "clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKitWorkspaceDriver.swift").read_text(
        encoding="utf-8"
    )
    activation = driver.split(
        "public func activateOrganization(_ selection: NativePracticeOrganizationSelection) async throws {", 1
    )[1].split("    /// Scoped only", 1)[0]
    prefix, after_refresh = activation.split("let refreshed = try await clerk.refreshClient()", 1)
    before_active, after_active = after_refresh.split("try await clerk.auth.setActive(", 1)
    assert "organizationMemberships" not in prefix
    assert "guard !retired, pending == 0, identity == expected" in prefix
    assert "selection.binding.realm == configuration" in prefix
    assert "pending += 1; defer { pending -= 1 }" in prefix
    assert "try Task.checkCancellation()" in prefix
    for boundary in (before_active, after_active):
        assert boundary.index("try Task.checkCancellation()") < boundary.index("guard !retired, pending == 1")
        assert "identity == expected" in boundary
        assert "selection.binding.realm == configuration" in boundary
        assert "organizationMemberships?.contains(where:" in boundary
        assert "$0.organization.id == selection.receipt.organizationID" in boundary
    assert "refreshed.lastActiveSessionId == expected.sessionID" in before_active
    assert "refreshedSession.user?.id == expected.userID" in before_active
    assert "refreshedSession.user?.organizationMemberships" in before_active
    assert "sessionId: expected.sessionID, organizationId: selection.receipt.organizationID" in after_active
    assert "clerk.session?.lastActiveOrganizationId == selection.receipt.organizationID" in after_active
    assert "catch" not in activation and "Clerk.shared" not in activation
    assert "refreshed?.currentSession" not in activation


def _portable():
    spec = importlib.util.spec_from_file_location("portable_iphone_compose", PORTABLE_COMPOSE)
    if spec is None or spec.loader is None:
        raise AssertionError("portable iPhone composition entry is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_portable_iphone_entry_selects_owned_clients_without_the_external_snapshot(tmp_path):
    text = PORTABLE_COMPOSE.read_text(encoding="utf-8")
    assert "ea7f99d" not in text
    assert EXTERNAL_CAPTURE_SNAPSHOT not in text
    module = _portable()
    assert module.IMPLEMENTATION_OWNERS == ("clients/apple", "clients/capture")

    before = _sha256(ROOT / "apps/capture/ios/App/App/Info.plist")
    output = tmp_path / "iphone-inputs"
    project = module.compose(ROOT, output)
    assert project == output / "apps/capture/ios/App/App.xcodeproj"
    assert project.is_dir()
    assert _sha256(ROOT / "apps/capture/ios/App/App/Info.plist") == before

    manifest_text = (output / "composition.json").read_text(encoding="utf-8")
    assert "ea7f99d" not in manifest_text
    manifest = json.loads(manifest_text)
    assert manifest["implementation_owners"] == ["clients/apple", "clients/capture"]
    assert manifest["app_scaffold"] == "apps/capture"
    assert manifest["scaffold_role"] == "frozen-1107-evidence"
    assert manifest["external_snapshot_required"] is False
    assert manifest["remote_capacitor_package_required"] is False
    assert manifest["owned_capacitor_vendor"] == "clients/apple/vendor/capacitor-swift-pm-8.5.1"
    assert manifest["composed_capacitor_vendor"] == "apps/capture/native-plugins/capacitor-swift-pm"
    assert manifest["qualified_install"] is False
    assert manifest["compiled_signed_or_installed"] is False
    assert manifest["generated_web_assets"] == "absent"
    assert not (output / "apps/capture/ios/App/App/public").exists()
    frozen_count = json.loads(PROVENANCE.read_text(encoding="utf-8"))["native_source_file_count"]
    # Explicit literal: must stay in lockstep with compose-portable-iphone.py.
    # ClerkKeychainCredentials.swift (+ tests) are required by the owned
    # ClerkKitWorkspaceDriver overlay (clearStoredCredentials) and are absent
    # from the frozen 1107 provenance; every composed iPhone app — including
    # prepare-owned-iphone-candidate.py — receives them via NATIVE_PRACTICE_ADDITIONS.
    additions = (
        "Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift",
        "Sources/CosmasNativeAuth/NativePracticeProfile.swift",
        "Sources/CosmasNativeAuth/NativePracticeActivationOwner.swift",
        "Sources/CosmasNativeAuth/NativePracticeConnectionContracts.swift",
        "Sources/CosmasNativeAuth/NativePracticeWorkspaceBootstrap.swift",
        "Sources/CosmasNativeAuth/NativePracticeAccountTransport.swift",
        "Sources/CosmasNativeAuth/NativePracticeSelectionStore.swift",
        "Bridge/CosmasNativePracticeConnectionPlugin.swift",
        "Bridge/NativePracticeConnectionController.swift",
        "Tests/CosmasNativeAuthTests/ClerkKeychainCredentialsTests.swift",
        "Tests/CosmasNativeAuthTests/NativePracticeProfileTests.swift",
        "Tests/CosmasNativeAuthTests/NativePracticeBootstrapTests.swift",
        "Tests/CosmasNativeAuthTests/NativePracticeConnectionContractTests.swift",
        "Tests/CosmasNativeAuthTests/NativePracticeOriginAndSelectionTests.swift",
        "Tests/CosmasNativeAuthTests/NativePracticeProductionTests.swift",
    )
    assert module.NATIVE_PRACTICE_ADDITIONS == additions
    assert tuple(manifest["native_practice_additions"]) == additions
    vendor_files = [
        item for item in manifest["files"]
        if str(item["path"]).startswith("native-plugins/capacitor-swift-pm/")
    ]
    assert len(vendor_files) >= 4
    assert len(manifest["files"]) == frozen_count + 1 + len(additions) + len(vendor_files)
    assert "https://github.com/ionic-team/capacitor-swift-pm.git" not in manifest_text
    assert "remoteSourceControl" not in manifest_text
    capapp = (output / "apps/capture/ios/App/CapApp-SPM/Package.swift").read_text(encoding="utf-8")
    assert 'path: "../../../native-plugins/capacitor-swift-pm"' in capapp
    assert "https://github.com/ionic-team/capacitor-swift-pm.git" not in capapp
    resolved = json.loads(
        (output / "apps/capture/ios/App/App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved")
        .read_text(encoding="utf-8")
    )
    assert resolved["pins"] == []
    assert (output / "apps/capture/native-plugins/capacitor-swift-pm/Package.swift").is_file()
    assert (output / "apps/capture/native-plugins/capacitor-swift-pm/Capacitor.xcframework/Info.plist").is_file()
    assert (output / "apps/capture/native-plugins/capacitor-swift-pm/Cordova.xcframework/Info.plist").is_file()
    for name in additions:
        destination = "native-plugins/cosmas-native-auth/" + name
        records = [item for item in manifest["files"] if item["path"] == destination]
        assert len(records) == 1
        assert records[0]["role"] == "implementation"
        assert records[0]["authoritative_counterpart"] == "clients/apple/native-auth/" + name
    assert len({item["path"] for item in manifest["files"]}) == len(manifest["files"])
    privacy = [item for item in manifest["files"] if item["path"] == "ios/App/App/PrivacyInfo.xcprivacy"]
    assert len(privacy) == 1
    assert privacy[0]["role"] == "implementation"
    assert privacy[0]["owner"] == "clients/apple"
    assert privacy[0]["authoritative_counterpart"] == "clients/apple/startup-recovery/PrivacyInfo.xcprivacy"
    assert plistlib.loads((output / "apps/capture/ios/App/App/PrivacyInfo.xcprivacy").read_bytes()) == (
        EXPECTED_APP_PRIVACY
    )
    default_info = plistlib.loads((output / "apps/capture/ios/App/App/Info.plist").read_bytes())
    assert default_info["CosmasNativeAuth"]["enabled"] is False
    assert default_info["CosmasConfiguredCapture"]["enabled"] is False
    assert default_info["NSMicrophoneUsageDescription"] == MICROPHONE_USAGE
    assert default_info["NSSpeechRecognitionUsageDescription"] == SPEECH_USAGE
    assert "ITSAppUsesNonExemptEncryption" not in default_info
    derived = [item for item in manifest["files"] if item["role"] == "derived-app-resource-wiring"]
    assert len(derived) == 1
    assert derived[0]["path"] == "ios/App/App.xcodeproj/project.pbxproj"
    usage = [item for item in manifest["files"] if item["role"] == "derived-owned-info-plist"]
    assert len(usage) == 1
    assert usage[0]["path"] == "ios/App/App/Info.plist"
    assert usage[0]["scaffold_input_sha256"] == _sha256(ROOT / "apps/capture/ios/App/App/Info.plist")
    assert usage[0]["derivation_source"] == "scripts/compose-portable-iphone.py"
    assert usage[0]["derivation_source_sha256"] == _sha256(PORTABLE_COMPOSE)
    assert usage[0]["auth_profile_source"] == "scripts/native_iphone_auth_profile.py"
    assert usage[0].get("production_native_auth") is False
    assert (output / "apps/capture/ios/App/App/Info.plist").read_bytes() != (
        ROOT / "apps/capture/ios/App/App/Info.plist"
    ).read_bytes()

    owners = set()
    for item in manifest["files"]:
        placed = output / "apps/capture" / item["path"]
        assert _sha256(placed) == item["sha256"]
        if item["role"] == "implementation":
            owners.add(item["owner"])
            counterpart = ROOT / item["authoritative_counterpart"]
            assert item["owner"] in {"clients/apple", "clients/capture"}
            assert str(counterpart.relative_to(ROOT)).startswith(item["owner"] + "/")
            assert placed.read_bytes() == counterpart.read_bytes()
        elif item["role"] == "supporting-client":
            counterpart = ROOT / item["authoritative_counterpart"]
            assert str(counterpart.relative_to(ROOT)).startswith("clients/shared/")
            assert placed.read_bytes() == counterpart.read_bytes()
        elif item["role"] == "scaffold-package-wiring":
            assert item["owner"] == "apps/capture"
            assert placed.read_bytes() == (ROOT / "apps/capture" / item["path"]).read_bytes()
            counterpart = item["authoritative_counterpart"]
            assert counterpart.startswith("clients/apple/") or counterpart.startswith("clients/capture/")
        elif item["role"] == "derived-app-resource-wiring":
            assert item["owner"] == "apps/capture"
            assert item["path"] == "ios/App/App.xcodeproj/project.pbxproj"
            original = ROOT / "apps/capture" / item["path"]
            assert item["scaffold_input_sha256"] == _sha256(original)
            assert item["derivation_source"] == "scripts/compose-portable-iphone.py"
            assert item["derivation_source_sha256"] == _sha256(PORTABLE_COMPOSE)
            text = placed.read_text(encoding="utf-8")
            privacy_lines = [line for line in text.splitlines(keepends=True) if "PrivacyInfo.xcprivacy" in line]
            assert len(privacy_lines) == 4
            assert "".join(line for line in text.splitlines(keepends=True) if "PrivacyInfo.xcprivacy" not in line) == original.read_text(encoding="utf-8")
        elif item["role"] == "derived-owned-info-plist":
            assert item["owner"] == "apps/capture"
            assert item["path"] == "ios/App/App/Info.plist"
            original = ROOT / "apps/capture" / item["path"]
            assert item["scaffold_input_sha256"] == _sha256(original)
            assert item["derivation_source"] == "scripts/compose-portable-iphone.py"
            assert item["derivation_source_sha256"] == _sha256(PORTABLE_COMPOSE)
            assert item["auth_profile_source"] == "scripts/native_iphone_auth_profile.py"
            assert item["auth_profile_source_sha256"] == _sha256(
                ROOT / "scripts/native_iphone_auth_profile.py")
            assert item.get("production_native_auth") is False
            info = plistlib.loads(placed.read_bytes())
            scaffold = plistlib.loads(original.read_bytes())
            assert info["NSMicrophoneUsageDescription"] != scaffold["NSMicrophoneUsageDescription"]
            assert info["NSSpeechRecognitionUsageDescription"] != scaffold["NSSpeechRecognitionUsageDescription"]
            assert info["CosmasNativeAuth"]["enabled"] is False
            assert info["CosmasNativeAuth"]["frontendOrigin"] == ""
            assert "ITSAppUsesNonExemptEncryption" not in info
            assert "ITSAppUsesNonExemptEncryption" not in scaffold
        elif item["role"] == "derived-capacitor-localization":
            assert item["derivation_source"] == "scripts/compose-portable-iphone.py"
            assert item["derivation_source_sha256"] == _sha256(PORTABLE_COMPOSE)
            assert item["scaffold_input_sha256"] == _sha256(ROOT / item["localization_input"])
            assert "https://github.com/ionic-team/capacitor-swift-pm.git" not in placed.read_text(encoding="utf-8")
            if item["path"].endswith("Package.resolved"):
                assert json.loads(placed.read_text(encoding="utf-8"))["pins"] == []
            else:
                assert f'path: "{item["localized_capacitor_path"]}"' in placed.read_text(encoding="utf-8")
        elif item["role"] == "app-scaffold":
            assert item["owner"] == "apps/capture"
            assert placed.read_bytes() == (ROOT / "apps/capture" / item["path"]).read_bytes()
        else:
            raise AssertionError(item["role"])
    assert owners == {"clients/apple", "clients/capture"}
    localized = [item["path"] for item in manifest["files"] if item["role"] == "derived-capacitor-localization"]
    assert set(localized) == {
        "ios/App/CapApp-SPM/Package.swift",
        "native-plugins/cosmas-native-auth/Package.swift",
        "native-plugins/ios-pcm-capacitor/Package.swift",
        "native-plugins/secure-queue/Package.swift",
        "ios/App/App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
    }
    apple = output / "apps/capture/ios/App/App/SceneDelegate.swift"
    capture = output / "apps/capture/native-plugins/ios-pcm-capture/Sources/CosmaneuraIOSPCMCore/IOSPCMCore.swift"
    assert apple.read_bytes() == (ROOT / "clients/apple/startup-recovery/SceneDelegate.swift").read_bytes()
    assert capture.read_bytes() == (
        ROOT / "clients/capture/native-configured/ios-pcm-capture/Sources/CosmaneuraIOSPCMCore/IOSPCMCore.swift"
    ).read_bytes()


def test_portable_iphone_compose_refuses_to_rewrite_the_frozen_scaffold(tmp_path):
    inside = ROOT / "apps/capture/not-an-output"
    with pytest.raises(ValueError, match="outside the repository"):
        _portable().compose(ROOT, inside)
    assert not inside.exists()
    existing = tmp_path / "already"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not exist"):
        _portable().compose(ROOT, existing)
    assert list(existing.iterdir()) == []


def test_portable_iphone_requires_every_reviewed_native_practice_addition_before_output(tmp_path, monkeypatch):
    module = _portable()
    monkeypatch.setattr(module, "NATIVE_PRACTICE_ADDITIONS", (
        *module.NATIVE_PRACTICE_ADDITIONS, "Sources/CosmasNativeAuth/MissingReviewedPracticeHost.swift",
    ))
    output = tmp_path / "missing-owned-source"
    with pytest.raises(ValueError, match="not a regular file"):
        module.compose(ROOT, output)
    assert not output.exists()


def test_owned_privacy_manifest_declares_reviewed_coverage():
    assert plistlib.loads(OWNED_PRIVACY.read_bytes()) == EXPECTED_APP_PRIVACY


def test_scaffold_info_plist_stays_frozen_export_key_left_for_owner_decision():
    info = plistlib.loads(APP_INFO.read_bytes())
    # Frozen 1107 scaffold keeps historical copy; composer derives reviewed wording.
    assert info["NSMicrophoneUsageDescription"] == (
        "Cosmas records visit audio after you confirm consent and choose Start recording."
    )
    assert info["NSSpeechRecognitionUsageDescription"] == (
        "Transcribe your saved recording on this iPhone only when you choose Transcribe. "
        "Your audio is not sent to a speech server."
    )
    assert info.get("ITSAppUsesNonExemptEncryption") is not False
    assert "ITSAppUsesNonExemptEncryption" not in info


def test_recording_path_retains_native_crypto_and_speech_symbols():
    recording = RECORDING_ENCRYPTION.read_text(encoding="utf-8")
    queue = SECURE_QUEUE.read_text(encoding="utf-8")
    assert "AES.GCM" in recording and "rsaEncryptionOAEPSHA256" in recording
    assert "SecKeyCreateEncryptedData" in recording
    assert "AES.GCM" in queue
    assert SPEECH_PLUGIN.is_file()
    speech = SPEECH_PLUGIN.read_text(encoding="utf-8")
    assert "SFSpeechRecognizer" in speech


def test_composed_project_includes_privacy_manifest_and_usage_strings(tmp_path):
    output = tmp_path / "composed"
    subprocess.run(
        [sys.executable, str(PORTABLE_COMPOSE), "--repository", str(ROOT), "--output", str(output)],
        check=True,
        cwd=ROOT,
    )
    app = output / "apps/capture/ios/App/App"
    privacy = app / "PrivacyInfo.xcprivacy"
    info = plistlib.loads((app / "Info.plist").read_bytes())
    project = (output / "apps/capture/ios/App/App.xcodeproj/project.pbxproj").read_text(encoding="utf-8")

    assert privacy.is_file()
    assert plistlib.loads(privacy.read_bytes()) == EXPECTED_APP_PRIVACY
    assert project.count("PrivacyInfo.xcprivacy in Resources") == 2
    assert "path = PrivacyInfo.xcprivacy" in project
    assert info["NSMicrophoneUsageDescription"] == MICROPHONE_USAGE
    assert info["NSSpeechRecognitionUsageDescription"] == SPEECH_USAGE
    assert info.get("ITSAppUsesNonExemptEncryption") is not False
    assert "ITSAppUsesNonExemptEncryption" not in info


def test_compose_refuses_non_true_export_compliance_key(tmp_path, monkeypatch):
    module = _portable()
    original_apply = module._derive_owned_info_plist

    def inject_false_then_apply(repository, output, placed, *, installation_profile=None):
        destination = output / module.APP_SCAFFOLD / "ios/App/App/Info.plist"
        info = plistlib.loads(destination.read_bytes())
        info["ITSAppUsesNonExemptEncryption"] = False
        destination.write_bytes(plistlib.dumps(info, sort_keys=False))
        return original_apply(
            repository, output, placed, installation_profile=installation_profile)

    monkeypatch.setattr(module, "_derive_owned_info_plist", inject_false_then_apply)
    output = tmp_path / "refused-export"
    with pytest.raises(ValueError, match="Refusing"):
        module.compose(ROOT, output)
    assert not output.exists()


@pytest.mark.parametrize("value", [False, 0, "NO", "false", "YES", 1])
def test_refuse_non_true_export_compliance_rejects_non_true_values(value):
    module = _portable()
    with pytest.raises(ValueError, match="Refusing"):
        module.refuse_non_true_export_compliance({"ITSAppUsesNonExemptEncryption": value})


def test_refuse_non_true_export_compliance_allows_absent_or_true():
    module = _portable()
    module.refuse_non_true_export_compliance({})
    module.refuse_non_true_export_compliance({"ITSAppUsesNonExemptEncryption": True})


def test_apply_reviewed_apple_info_usage_covers_operational_and_synthetic_paths():
    spec = importlib.util.spec_from_file_location("prepare_apple_synthetic", APPLE_PREPARE)
    assert spec is not None and spec.loader is not None
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)

    operational = prepare.apply_reviewed_apple_info_usage(
        {}, operational=True, simulator_staging_auth=False
    )
    assert operational["NSMicrophoneUsageDescription"] == MICROPHONE_USAGE
    assert operational["NSSpeechRecognitionUsageDescription"] == SPEECH_USAGE
    assert "ITSAppUsesNonExemptEncryption" not in operational

    synthetic = prepare.apply_reviewed_apple_info_usage(
        {}, operational=False, simulator_staging_auth=False
    )
    assert synthetic["NSMicrophoneUsageDescription"] == SYNTHETIC_MICROPHONE_USAGE
    assert synthetic["NSSpeechRecognitionUsageDescription"] == SPEECH_USAGE

    simulator = prepare.apply_reviewed_apple_info_usage(
        {}, operational=True, simulator_staging_auth=True
    )
    assert simulator["NSMicrophoneUsageDescription"] == SYNTHETIC_MICROPHONE_USAGE

    with pytest.raises(ValueError, match="Refusing"):
        prepare.apply_reviewed_apple_info_usage(
            {"ITSAppUsesNonExemptEncryption": False},
            operational=True,
            simulator_staging_auth=False,
        )
    absent = prepare.apply_reviewed_apple_info_usage(
        {}, operational=True, simulator_staging_auth=False
    )
    assert "ITSAppUsesNonExemptEncryption" not in absent
