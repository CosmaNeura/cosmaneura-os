"""Exercise real native composition preflight; never compile, copy or launch a shell."""

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
native = module("native_identity_build")
packager = module("package-desktop-synthetic")


class PreflightComplete(Exception):
    pass


class NativeDataMode(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cosmas-native-mode-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.identity = {
            "version": 1, "profile": "operational-beta-v1", "client": "desktop",
            "apiOrigin": "https://api.example.invalid",
            "frontendOrigin": "https://identity.example.invalid",
            "publishableKey": "pk_live_" + base64.b64encode(b"identity.example.invalid$").decode(),
            "organizationId": "org_invented_mode_test", "audience": "cosmas-beta-api",
        }

    def inputs(self, client, data_mode):
        result = subprocess.run([
            "node", "--input-type=module", "-e",
            "const m=await import(process.argv[1]);"
            "const f=m.workspaceIdentityInputs(JSON.parse(process.argv[2]),{"
            "webOrigin:'https://workspace.example.invalid',coreWebOrigin:'https://core.example.invalid',"
            "captureUploadOrigins:['https://uploads.example.invalid'],dataMode:process.argv[3]});"
            "const p=await import(process.argv[4]);"
            "process.stdout.write(JSON.stringify({identity:f[process.argv[5]+'-identity.json'],"
            "manifest:p.resolveBetaFeatureProfile(f[process.argv[5]+'-build-env.json']).manifest}));",
            (ROOT / "scripts/prepare-workspace-identity.mjs").as_uri(), json.dumps(self.identity), data_mode,
            (ROOT / "clients/shared/beta-feature-profile.mjs").as_uri(), client,
        ], capture_output=True, text=True, check=True)
        values = json.loads(result.stdout)
        web = self.root / "web"
        web.mkdir(exist_ok=True)
        manifest = values["manifest"]
        (web / "cosmas-beta-features.json").write_text(json.dumps(manifest))
        (web / "cosmas-workspace-build.json").write_text(json.dumps({
            "version": 1, **{key: manifest[key] for key in ("client", "dataMode", "apiOrigin", "apiBase", "pageOrigin")},
        }))
        path = self.root / "identity.json"
        path.write_text(json.dumps(values["identity"]))
        return web, path

    def invoke(self, client, web, identity, selected):
        target = desktop if client == "desktop" else apple
        validate = target._beta.validate_native

        def finish_preflight(*args, **kwargs):
            validate(*args, **kwargs)
            raise PreflightComplete()

        with patch.object(target._beta, "validate_native", side_effect=finish_preflight):
            if client == "desktop":
                argv = ["prepare-desktop-synthetic.py", "--scribe-source", str(self.root / "unread-source"),
                        "--web-dist", str(web), "--output", str(self.root / "never-created"),
                        "--native-auth-helper", str(self.root / "unread-helper"), "--installation-profile", "beta",
                        "--hosted-api-origin", self.identity["apiOrigin"], "--native-identity-config", str(identity),
                        "--cosmaneura-web-origin", "https://core.example.invalid",
                        "--capture-upload-origin", "https://uploads.example.invalid", "--microphone-capture"]
                if selected is not None:
                    argv += ["--data-mode", selected]
                with patch.object(sys, "argv", argv):
                    desktop.main()
            else:
                apple.prepare(self.root / "unread-source", web, self.root / "never-created",
                    native_auth_clerk_archive=self.root / "unread-archive", renewable_native_capture=True,
                    native_renderer_recovery=True, hosted_workspace=True, workspace_api_origin=self.identity["apiOrigin"],
                    capture_upload_origins=("https://uploads.example.invalid",), cosmaneura_web_origin="https://core.example.invalid",
                    google_connection_client_id="invented-profile.apps.googleusercontent.com",
                    google_connection_callback_uri=self.identity["apiOrigin"] + "/connections/google/callback",
                    native_identity_config=identity, data_mode=selected)

    def test_both_composers_accept_authenticated_synthetic_and_legacy_authorized_inputs(self):
        for client in ("desktop", "apple"):
            for selected in ("synthetic", "authorized_beta", None):
                with self.subTest(client=client, selected=selected):
                    web, identity = self.inputs(client, selected or "authorized_beta")
                    with self.assertRaises(PreflightComplete):
                        self.invoke(client, web, identity, selected)
                    self.assertFalse((self.root / "never-created").exists())

    def test_composers_refuse_mode_mismatch_and_changed_identity(self):
        for client in ("desktop", "apple"):
            with self.subTest(client=client):
                web, identity = self.inputs(client, "synthetic")
                with self.assertRaises((ValueError, SystemExit)):
                    self.invoke(client, web, identity, "authorized_beta")
                value = json.loads(identity.read_text())
                value["apiOrigin"] = "https://other.example.invalid"
                identity.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    self.invoke(client, web, identity, "synthetic")
                self.assertFalse((self.root / "never-created").exists())

    def test_data_selection_keeps_legacy_profiles_and_requires_identity_for_authorized_data(self):
        self.assertEqual(native.data_mode(None), "synthetic")
        self.assertEqual(native.data_mode({"identity": self.identity}), "authorized_beta")
        self.assertEqual(native.data_mode({"identity": self.identity}, "synthetic"), "synthetic")
        for identity, mode in ((None, "authorized_beta"), ({}, ""), ({}, "invalid")):
            with self.assertRaises(ValueError):
                native.data_mode(identity, mode)

    def test_desktop_packager_keeps_beta_bundle_and_identity_for_both_modes(self):
        for data_mode in ("synthetic", "authorized_beta"):
            with self.subTest(data_mode=data_mode):
                web, identity_path = self.inputs("desktop", data_mode)
                identity = native.load(identity_path, "desktop", self.identity["apiOrigin"])
                runtime = self.root / data_mode / "Electron.app"
                (runtime / "Contents").mkdir(parents=True)
                (runtime / "Contents/Info.plist").write_bytes(plistlib.dumps({
                    "CFBundleIdentifier": "com.github.Electron", "CFBundleVersion": "43.4.1",
                    "LSMinimumSystemVersion": "14.0",
                }))
                app = self.root / data_mode / "composed"
                helper = app / "native-auth/CosmasDesktopAuth.app/Contents"
                helper.mkdir(parents=True)
                (helper / "Info.plist").write_bytes(plistlib.dumps({
                    "CFBundleIdentifier": identity["bundle"], "CosmasNativeAuth": identity["auth"],
                    "CosmasNativeIdentity": identity["identity"], "LSMinimumSystemVersion": "14.0",
                }))
                (app / "public").mkdir()
                (app / "public/cosmas-workspace-build.json").write_bytes((web / "cosmas-workspace-build.json").read_bytes())
                (app / "main.mjs").write_text("// Invented packaging fixture; never executed.\n")
                (app / "package.json").write_text(json.dumps({"version": "0.1.0"}))
                config = {"mode": "hosted-beta-authenticated", "dataMode": data_mode,
                    "apiOrigin": self.identity["apiOrigin"], "nativeIdentity": identity["identity"],
                    "nativeAuthEnabled": True, "appVersion": "0.1.0", "buildNumber": "1",
                    "installation": {"profile": "beta", "bundleIdentifier": "com.cosmasos.beta.desktop",
                        "rendererPartition": "persist:cosmasos-operational-beta", "authHelperBundleIdentifier": identity["bundle"]}}
                (app / "synthetic-build.json").write_text(json.dumps(config))
                output = self.root / data_mode / "Packaged.app"
                with patch.object(sys, "argv", ["package-desktop-synthetic.py", "--electron-app", str(runtime),
                    "--composed-app", str(app), "--output", str(output)]):
                    packager.main()
                plist = plistlib.loads((output / "Contents/Info.plist").read_bytes())
                self.assertEqual(plist["CFBundleIdentifier"], "com.cosmasos.beta.desktop")
                retained = json.loads((output / "Contents/Resources/app/synthetic-build.json").read_text())
                self.assertEqual(retained["dataMode"], data_mode)
                self.assertEqual(retained["nativeIdentity"], identity["identity"])


if __name__ == "__main__":
    unittest.main()
