"""Composer must place ClerkKeychainCredentials.swift into the iPhone project."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORTABLE = ROOT / "scripts/compose-portable-iphone.py"


def _portable():
    spec = importlib.util.spec_from_file_location("compose_portable_iphone", PORTABLE)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_native_practice_additions_list_clerk_keychain_credentials():
    module = _portable()
    assert "Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift" in module.NATIVE_PRACTICE_ADDITIONS
    assert (
        "Tests/CosmasNativeAuthTests/ClerkKeychainCredentialsTests.swift"
        in module.NATIVE_PRACTICE_ADDITIONS
    )


def test_composed_file_list_includes_clerk_keychain_credentials(tmp_path):
    module = _portable()
    output = tmp_path / "iphone-project"
    module.compose(ROOT, output)
    manifest = json.loads((output / "composition.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["files"]}
    keychain = (
        "native-plugins/cosmas-native-auth/Sources/CosmasNativeAuth/"
        "ClerkKeychainCredentials.swift"
    )
    tests = (
        "native-plugins/cosmas-native-auth/Tests/CosmasNativeAuthTests/"
        "ClerkKeychainCredentialsTests.swift"
    )
    assert keychain in paths
    assert tests in paths
    assert "Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift" in manifest[
        "native_practice_additions"
    ]
    placed = output / "apps/capture" / keychain
    source = ROOT / "clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift"
    assert placed.is_file()
    assert placed.read_bytes() == source.read_bytes()
    assert "ClerkKeychainCredentials" in placed.read_text(encoding="utf-8")
