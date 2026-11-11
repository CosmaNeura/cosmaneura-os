"""Linux-runnable checks for iPhone TestFlight release-config composition."""

from __future__ import annotations

import importlib.util
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "scripts/compose-portable-iphone.py"
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
EXPECTED_PRIVACY = {
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
    ],
    "NSPrivacyAccessedAPITypes": [
        {
            "NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategorySystemBootTime",
            "NSPrivacyAccessedAPITypeReasons": ["35F9.1"],
        }
    ],
}


def _compose(output: Path) -> Path:
    subprocess.run(
        [sys.executable, str(COMPOSE), "--repository", str(ROOT), "--output", str(output)],
        check=True,
        cwd=ROOT,
    )
    return output / "apps/capture"


def test_owned_privacy_manifest_declares_reviewed_coverage():
    assert plistlib.loads(OWNED_PRIVACY.read_bytes()) == EXPECTED_PRIVACY


def test_scaffold_info_plist_stays_frozen_without_false_export_claim():
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


def test_recording_path_uses_non_exempt_application_crypto():
    recording = RECORDING_ENCRYPTION.read_text(encoding="utf-8")
    queue = SECURE_QUEUE.read_text(encoding="utf-8")
    assert "AES.GCM" in recording and "rsaEncryptionOAEPSHA256" in recording
    assert "SecKeyCreateEncryptedData" in recording
    assert "AES.GCM" in queue
    assert SPEECH_PLUGIN.is_file()
    speech = SPEECH_PLUGIN.read_text(encoding="utf-8")
    assert "SFSpeechRecognizer" in speech


def test_composed_project_includes_privacy_manifest_and_usage_strings(tmp_path):
    capture = _compose(tmp_path / "composed")
    app = capture / "ios/App/App"
    privacy = app / "PrivacyInfo.xcprivacy"
    info = plistlib.loads((app / "Info.plist").read_bytes())
    project = (capture / "ios/App/App.xcodeproj/project.pbxproj").read_text(encoding="utf-8")

    assert privacy.is_file()
    assert plistlib.loads(privacy.read_bytes()) == EXPECTED_PRIVACY
    assert project.count("PrivacyInfo.xcprivacy in Resources") == 2
    assert "path = PrivacyInfo.xcprivacy" in project
    assert info["NSMicrophoneUsageDescription"] == MICROPHONE_USAGE
    assert info["NSSpeechRecognitionUsageDescription"] == SPEECH_USAGE
    assert info.get("ITSAppUsesNonExemptEncryption") is not False
    assert "ITSAppUsesNonExemptEncryption" not in info


def test_prepare_apple_synthetic_writes_reviewed_usage_strings():
    spec = importlib.util.spec_from_file_location(
        "prepare_apple_synthetic", ROOT / "scripts/prepare-apple-synthetic.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert MICROPHONE_USAGE in source
    assert "CosmaBot uses on-device speech recognition to transcribe recordings you choose to" in source
    assert "transcribe so it can draft your notes." in source
    assert "Cosmas records visit audio after you confirm consent" not in source
    assert "ITSAppUsesNonExemptEncryption=NO" in source or "ITSAppUsesNonExemptEncryption) is False" in source
