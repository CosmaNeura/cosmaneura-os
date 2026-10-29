"""Exercise composed and packaged identity custody with invented native metadata."""

import base64
import contextlib
import importlib.util
import io
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


composer = module("prepare-desktop-synthetic")
packager = module("package-desktop-synthetic")


class IndependentDesktopProfile(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cosmabot-independent-desktop-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.identity = {"version": 1, "profile": "operational-beta-v1", "client": "desktop",
                         "apiOrigin": "https://api.example.invalid", "frontendOrigin": "https://identity.example.invalid",
                         "publishableKey": "pk_live_" + base64.b64encode(b"identity.example.invalid$").decode(),
                         "organizationId": "org_invented_practice", "audience": "invented-cosmabot-api"}
        self.identity_path = self.root / "identity.json"
        self.identity_path.write_text(json.dumps(self.identity))
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text("<html><head></head><body>Invented test renderer</body></html>")
        self.helper = self.root / "helper.app"
        (self.helper / "Contents").mkdir(parents=True)
        validated = composer._identity.validate(self.identity, "desktop", self.identity["apiOrigin"])
        (self.helper / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": validated["bundle"], "CFBundleExecutable": "CosmasDesktopAuth",
            "CosmasNativeAuth": validated["auth"], "CosmasNativeIdentity": validated["identity"],
            "CosmasConfiguredCapture": {"enabled": False}, "LSMinimumSystemVersion": "14.0",
        }))
        self.runtime = self.root / "Electron.app"
        (self.runtime / "Contents").mkdir(parents=True)
        (self.runtime / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "com.github.Electron", "CFBundleVersion": "43.4.1", "LSMinimumSystemVersion": "12.0",
        }))

    def write_profile(self, profile="independent-beta-v1"):
        env = {"VITE_WORKSPACE_FEATURE_PROFILE": profile, "VITE_WORKSPACE_HOSTED_CLIENT": "desktop",
               "VITE_WORKSPACE_DATA_MODE": "synthetic", "VITE_WORKSPACE_HOSTED_API_ORIGIN": self.identity["apiOrigin"],
               "VITE_API_BASE": "app://cosmas/api", "VITE_WORKSPACE_WEB_ORIGIN": "", "VITE_COSMANEURA_WEB_ORIGIN": "",
               "VITE_CAPTURE_UPLOAD_ORIGINS": "", "VITE_WORKSPACE_CAPTURE_MODE": "disabled",
               "VITE_CLERK_PUBLISHABLE_KEY": self.identity["publishableKey"]}
        output = subprocess.check_output(["node", "--input-type=module", "-e",
                                          "const m=await import(process.argv[1]);process.stdout.write(JSON.stringify("
                                          "m.resolveBetaFeatureProfile(JSON.parse(process.argv[2])).manifest));",
                                          (ROOT / "clients/shared/beta-feature-profile.mjs").as_uri(), json.dumps(env)])
        manifest = json.loads(output)
        (self.web / "cosmas-beta-features.json").write_text(json.dumps(manifest))
        (self.web / "cosmas-workspace-build.json").write_text(json.dumps({
            "version": 1, **{key: manifest[key] for key in ("client", "dataMode", "apiOrigin", "apiBase", "pageOrigin")},
        }))

    def arguments(self, output, extra=()):
        return ["prepare-desktop-synthetic.py", "--scribe-source", str(self.root / "unread-template-source"),
                "--web-dist", str(self.web), "--output", str(output), "--native-auth-helper", str(self.helper),
                "--installation-profile", "beta", "--hosted-api-origin", self.identity["apiOrigin"],
                "--data-mode", "synthetic", "--native-identity-config", str(self.identity_path),
                "--app-version", "0.1.143", "--build-number", "1103", *extra]

    def compose(self, profile="independent-beta-v1"):
        self.write_profile(profile)
        output = self.root / profile
        # The three retained source templates are replaced with inert invented
        # text. Actual public validation, compilation, file copying and emitted
        # descriptors execute; no legacy source or native binary is accessed.
        def source_template(command, **_kwargs):
            self.assertEqual(command[:2], ["git", "show"])
            return b"const RENDERER_ASSETS = Object.freeze({\n});\nexport const invented = true;\n"
        provenance = {"version": 1, "commit": "1" * 40, "tree": "2" * 40, "dirty": False}
        with patch.object(sys, "argv", self.arguments(output)), \
                patch.object(composer._source_module, "provenance", return_value=provenance), \
                patch.object(composer.subprocess, "check_output", side_effect=source_template):
            composer.main()
        app = output / "app"
        return app, json.loads((app / "synthetic-build.json").read_text())

    def test_composed_and_packaged_new_beta_has_identity_scope_without_changing_old_profile(self):
        app, configuration = self.compose()
        self.assertEqual(configuration["installation"]["storageScope"], "identity-v1")
        self.assertEqual(configuration["nativeIdentity"], self.identity)
        self.assertFalse(configuration["nativeCaptureEnabled"])
        package = self.root / "independent.app"
        with patch.object(sys, "argv", ["package-desktop-synthetic.py", "--electron-app", str(self.runtime),
                                        "--composed-app", str(app), "--output", str(package)]):
            packager.main()
        saved = json.loads((package / "Contents/Resources/app/synthetic-build.json").read_text())
        self.assertEqual(saved, configuration)
        info = plistlib.loads((package / "Contents/Info.plist").read_bytes())
        self.assertEqual(info["CFBundleIdentifier"], "com.cosmasos.beta.desktop")
        self.assertEqual(info["CFBundleVersion"], "1103")
        prior_app, prior = self.compose("standalone-practice-v1")
        self.assertNotIn("storageScope", prior["installation"])
        packager.validate_storage_profile(prior, prior_app)
        prior["installation"]["storageScope"] = "identity-v1"
        with self.assertRaises(ValueError):
            packager.validate_storage_profile(prior, prior_app)

    def test_independent_package_refuses_missing_scope_or_extra_capabilities(self):
        app, configuration = self.compose()
        for scope in (None, "", "identity-v2"):
            altered = {**configuration, "installation": {**configuration["installation"], "storageScope": scope}}
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                packager.validate_storage_profile(altered, app)
        for key in ("microsoftConnectionTenantId", "microsoftConnectionClientId", "microsoftConnectionCallbackUri",
                    "schedulingGoogleClientId", "schedulingGoogleCallbackUri"):
            with self.subTest(capability=key), self.assertRaises(ValueError):
                packager.validate_storage_profile({**configuration, key: "invented-setting"}, app)
        for change in (
            {"googleConnectionClientId": "invented.apps.googleusercontent.com"},
            {"googleConnectionCallbackUri": self.identity["apiOrigin"] + "/connections/google/callback"},
            {"googleConnectionClientId": "invented.apps.googleusercontent.com",
             "googleConnectionCallbackUri": "https://other.example.invalid/connections/google/callback"},
        ):
            with self.subTest(google=change), self.assertRaises(ValueError):
                packager.validate_storage_profile({**configuration, **change}, app)

    def test_independent_preflight_refuses_unapproved_connections_before_output(self):
        self.write_profile()
        output = self.root / "never-created"
        for option in ("--microsoft-connection-tenant-id", "--microsoft-connection-client-id",
                       "--microsoft-connection-callback-uri", "--scheduling-google-client-id", "--scheduling-google-callback-uri"):
            error = io.StringIO()
            with self.subTest(option=option), patch.object(sys, "argv", self.arguments(output, [option, "invented-setting"])), \
                    contextlib.redirect_stderr(error):
                with self.assertRaises(SystemExit):
                    composer.main()
            self.assertIn("Independent beta permits only the approved Google account connection.", error.getvalue())
        self.assertFalse(output.exists())

    def test_independent_google_preflight_requires_its_own_api_callback(self):
        self.write_profile()
        output = self.root / "never-created"
        args = self.arguments(output, ["--google-connection-client-id", "invented.apps.googleusercontent.com",
                                       "--google-connection-callback-uri", "https://other.example.invalid/connections/google/callback"])
        error = io.StringIO()
        with patch.object(sys, "argv", args), contextlib.redirect_stderr(error):
            with self.assertRaises(SystemExit):
                composer.main()
        self.assertIn("Independent beta Google sign-in must return to its exact configured API.", error.getvalue())
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
