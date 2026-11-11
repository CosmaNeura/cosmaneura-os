"""Qualify independent main iPhone input guards without reading or building a shell."""

import json
import plistlib
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_standalone_native_profile as fixtures


class IndependentAppleProfile(fixtures.StandaloneNativeProfile):
    feature_profile = "independent-beta-v1"
    # Existing independent Apple qualification keeps the Core capture opt-in ON.
    core_capture_enabled = True

    def apple_options(self):
        return {**super().apple_options(),
                "cosmaneura_web_origin": "https://staging-app.cosmaneura.com",
                "capture_upload_origins": (self.identity["apiOrigin"],)}

    def desktop_args(self, output, extra=()):
        return super().desktop_args(output, [
            "--cosmaneura-web-origin", "https://staging-app.cosmaneura.com",
            "--capture-upload-origin", self.identity["apiOrigin"], "--microphone-capture", *extra])

    def test_helper_metadata_keeps_auth_and_disables_capture_and_composer_checks_it(self):
        # Independent-beta keeps helper capture dark by default (opt-in is profile/env, not helper packaging).
        products = self.root / "products"
        resources = products / "CosmasNativeAuthQualification_ClerkKit.bundle"
        resources.mkdir(parents=True)
        (resources / "fixture.txt").write_text("invented SDK resource")
        binary = products / "CosmasDesktopAuth"
        binary.write_bytes(b"invented executable bytes; never launched")
        binary.chmod(0o755)
        qualification = self.root / "qualification"
        (qualification / "vendor").mkdir(parents=True)
        license_file = qualification / "vendor/LICENSE"
        license_file.write_text("invented test license")
        receipts = self.root / "receipts"
        receipts.mkdir()
        receipt = receipts / "compiler.json"
        receipt.write_text("invented compiler receipt; verification replaced for metadata-only test")
        manifest = {"native_identity_profile_version": 1, "native_source_version": 1,
                    "composed_sha256": {"vendor/LICENSE": fixtures.helper._binding.digest(license_file)}}
        output = self.root / "helper.app"
        args = ["package-desktop-auth-helper.py", "--products", str(products), "--qualification", str(qualification),
                "--compiler-receipt", str(receipt), "--output", str(output),
                "--native-identity-config", str(self.root / "desktop-identity.json"),
                "--native-feature-profile", self.feature_profile]
        with patch.object(sys, "argv", args), patch.object(fixtures.helper._binding, "verify", return_value=manifest):
            fixtures.helper.main()
        info = plistlib.loads((output / "Contents/Info.plist").read_bytes())
        self.assertEqual(info["CosmasConfiguredCapture"], {"enabled": False})
        self.assertTrue(info["CosmasNativeAuth"]["enabled"])

    def test_main_bundle_and_explicit_google_pair_reach_the_native_policy_boundary(self):
        identity = fixtures.apple._identity.load(self.root / "apple-identity.json", "apple", self.identity["apiOrigin"])
        self.assertEqual(identity["bundle"], "com.cosmasos.beta.ios")
        manifest = json.loads((self.root / "apple/cosmas-beta-features.json").read_text())
        self.assertEqual(manifest["profile"], self.feature_profile)
        self.assertEqual(manifest["captureMode"], "ios_native")
        self.assertEqual(manifest["coreWebOrigin"], "https://staging-app.cosmaneura.com")
        self.assertEqual(manifest["captureUploadOrigins"], [self.identity["apiOrigin"]])
        self.assertEqual(fixtures.apple.source_access_group(identity["bundle"], None), "$(AppIdentifierPrefix)com.cosmasos.beta.ios")
        for google in ({}, {"google_connection_client_id": "invented.apps.googleusercontent.com",
                            "google_connection_callback_uri": self.identity["apiOrigin"] + "/connections/google/callback"}):
            output = self.root / "never-created"
            with self.subTest(google=bool(google)), patch.object(fixtures.apple, "workspace_policy_html", side_effect=fixtures.PreflightComplete):
                with self.assertRaises(fixtures.PreflightComplete):
                    fixtures.apple.prepare(self.root / "unread-source", self.root / "apple", output,
                                           **self.apple_options(), **google)
            self.assertFalse(output.exists())

    def test_missing_keyboard_host_and_unqualified_connections_refuse_before_shell_access(self):
        forbidden = [
            {"native_renderer_recovery": False},
            {"microsoft_connection_tenant_id": "00000000-0000-4000-8000-000000000001",
             "microsoft_connection_client_id": "00000000-0000-4000-8000-000000000002",
             "microsoft_connection_callback_uri": self.identity["apiOrigin"] + "/connections/microsoft/callback"},
            {"scheduling_google_client_id": "invented.apps.googleusercontent.com",
             "scheduling_google_callback_uri": self.identity["apiOrigin"] + "/connections/scheduling/google/callback"},
            {"google_connection_client_id": "invented.apps.googleusercontent.com",
             "google_connection_callback_uri": "https://other.example.invalid/connections/google/callback"},
            {"google_connection_client_id": "invented.apps.googleusercontent.com"},
            {"google_connection_callback_uri": self.identity["apiOrigin"] + "/connections/google/callback"},
        ]
        output = self.root / "never-created"
        for change in forbidden:
            with self.subTest(change=change), patch.object(fixtures.apple.subprocess, "check_output") as archive:
                with self.assertRaisesRegex(ValueError, "Independent beta|exact Gmail|fixed Gmail|Cosmaneura navigation|native recovery"):
                    fixtures.apple.prepare(self.root / "unread-source", self.root / "apple", output,
                                           **{**self.apple_options(), **change})
                archive.assert_not_called()
            self.assertFalse(output.exists())

    def test_main_profile_cannot_use_preview_or_simulator_identity(self):
        output = self.root / "never-created"
        for change in ({"verification_variant": "w206"}, {"simulator_custody": True}, {"data_mode": "authorized_beta"}):
            with self.subTest(change=change):
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    fixtures.apple.prepare(self.root / "unread-source", self.root / "apple", output,
                                           **{**self.apple_options(), **change})
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
