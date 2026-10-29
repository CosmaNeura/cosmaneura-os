"""Check native standalone preflight/metadata without compiling or reading Scribe."""

import base64
import importlib.util
import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


desktop = module("prepare-desktop-synthetic")
apple = module("prepare-apple-synthetic")
helper = module("package-desktop-auth-helper")


class PreflightComplete(Exception):
    pass


class StandaloneNativeProfile(unittest.TestCase):
    feature_profile = "standalone-practice-v1"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cosmabot-standalone-native-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.identity = {
            "version": 1, "profile": "operational-beta-v1", "client": "desktop",
            "apiOrigin": "https://api.example.invalid", "frontendOrigin": "https://identity.example.invalid",
            "publishableKey": "pk_live_" + base64.b64encode(b"identity.example.invalid$").decode(),
            "organizationId": "org_invented_standalone", "audience": "cosmabot-standalone-api",
        }
        result = subprocess.run([
            "node", "--input-type=module", "-e",
            "const m=await import(process.argv[1]);process.stdout.write(JSON.stringify(m.workspaceIdentityInputs("
            "JSON.parse(process.argv[2]),{webOrigin:'https://workspace.example.invalid',coreWebOrigin:'',"
            "captureUploadOrigins:[],dataMode:'synthetic',featureProfile:process.argv[3]})));",
            (ROOT / "scripts/prepare-workspace-identity.mjs").as_uri(), json.dumps(self.identity), self.feature_profile,
        ], capture_output=True, text=True, check=True)
        files = json.loads(result.stdout)
        for client in ("desktop", "apple"):
            web = self.root / client
            web.mkdir()
            (web / "index.html").write_text("<html><head></head><body></body></html>")
            manifest = files["standalone-profile.json"]["clients"][client]
            (web / "cosmas-beta-features.json").write_text(json.dumps(manifest))
            (web / "cosmas-workspace-build.json").write_text(json.dumps({
                "version": 1, **{key: manifest[key] for key in
                                  ("client", "dataMode", "apiOrigin", "apiBase", "pageOrigin")},
            }))
            (self.root / f"{client}-identity.json").write_text(json.dumps(files[f"{client}-identity.json"]))

    def desktop_args(self, output, extra=()):
        return ["prepare-desktop-synthetic.py", "--scribe-source", str(self.root / "unread-source"),
                "--web-dist", str(self.root / "desktop"), "--output", str(output),
                "--native-auth-helper", str(self.root / "helper.app"), "--installation-profile", "beta",
                "--hosted-api-origin", self.identity["apiOrigin"], "--data-mode", "synthetic",
                "--native-identity-config", str(self.root / "desktop-identity.json"), *extra]

    def apple_options(self):
        return {"native_auth_clerk_archive": self.root / "unread-archive",
                "renewable_native_capture": True, "native_renderer_recovery": True,
                "hosted_workspace": True, "workspace_api_origin": self.identity["apiOrigin"],
                "native_identity_config": self.root / "apple-identity.json", "data_mode": "synthetic"}

    def test_own_account_connections_pass_both_native_preflights(self):
        output = self.root / "never-created"
        google_id = "invented-standalone.apps.googleusercontent.com"
        callback = self.identity["apiOrigin"] + "/connections/google/callback"
        args = self.desktop_args(output, ["--google-connection-client-id", google_id,
                                         "--google-connection-callback-uri", callback])
        with patch.object(sys, "argv", args), patch.object(desktop._navigation, "validate_scheduling", side_effect=PreflightComplete):
            with self.assertRaises(PreflightComplete):
                desktop.main()
        with patch.object(apple, "workspace_policy_html", side_effect=PreflightComplete):
            with self.assertRaises(PreflightComplete):
                apple.prepare(self.root / "unread-source", self.root / "apple", output,
                              **self.apple_options(), google_connection_client_id=google_id,
                              google_connection_callback_uri=callback)
        self.assertFalse(output.exists())

    def test_both_native_preflights_reject_platform_or_capture_origin(self):
        output = self.root / "never-created"
        for extra in (["--cosmaneura-web-origin", "https://app.cosmaneura.com"],
                      ["--capture-upload-origin", "https://uploads.example.invalid"], ["--microphone-capture"]):
            with self.subTest(desktop=extra), patch.object(sys, "argv", self.desktop_args(output, extra)):
                with self.assertRaises((subprocess.CalledProcessError, ValueError, SystemExit)):
                    desktop.main()
        for change in ({"cosmaneura_web_origin": "https://staging-app.cosmaneura.com"},
                       {"capture_upload_origins": ("https://uploads.example.invalid",)}):
            with self.subTest(apple=change):
                with self.assertRaises((subprocess.CalledProcessError, ValueError)):
                    apple.prepare(self.root / "unread-source", self.root / "apple", output,
                                  **{**self.apple_options(), **change})
        self.assertFalse(output.exists())

    def test_helper_metadata_keeps_auth_and_disables_capture_and_composer_checks_it(self):
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
                    "composed_sha256": {"vendor/LICENSE": helper._binding.digest(license_file)}}
        output = self.root / "helper.app"
        args = ["package-desktop-auth-helper.py", "--products", str(products), "--qualification", str(qualification),
                "--compiler-receipt", str(receipt), "--output", str(output),
                "--native-identity-config", str(self.root / "desktop-identity.json"),
                "--native-feature-profile", self.feature_profile]
        # Compiler/signature validation is outside this configuration test. The
        # real copy, output inventory, identity validation and plist checks run.
        with patch.object(sys, "argv", args), patch.object(helper._binding, "verify", return_value=manifest):
            helper.main()
        plist = output / "Contents/Info.plist"
        info = plistlib.loads(plist.read_bytes())
        self.assertEqual(info["CosmasConfiguredCapture"], {"enabled": False})
        self.assertTrue(info["CosmasNativeAuth"]["enabled"])
        self.assertEqual(info["CosmasNativeIdentity"], self.identity)
        self.assertFalse((output / ".incomplete").exists())
        composed = self.root / "never-created"
        with patch.object(sys, "argv", self.desktop_args(composed)), patch.object(desktop._source_module, "provenance", side_effect=PreflightComplete):
            with self.assertRaises(PreflightComplete):
                desktop.main()
        info["CosmasConfiguredCapture"] = {"enabled": True, "apiOrigin": self.identity["apiOrigin"]}
        plist.write_bytes(plistlib.dumps(info))
        with patch.object(sys, "argv", self.desktop_args(composed)):
            with self.assertRaises(SystemExit):
                desktop.main()
        self.assertFalse(composed.exists())


if __name__ == "__main__":
    unittest.main()
