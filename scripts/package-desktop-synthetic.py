#!/usr/bin/env python3
"""Make a distinct local Mac app from the official pinned Electron runtime.

This is development packaging only: no developer identity, notarization, store
submission, updater or distribution action is performed.
"""

import argparse
import importlib.util
import json
import plistlib
import re
import shutil
from pathlib import Path

_spec = importlib.util.spec_from_file_location("native_identity_build", Path(__file__).with_name("native_identity_build.py"))
_identity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_identity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--electron-app", type=Path, required=True)
    parser.add_argument("--composed-app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verification-variant", default="",
                        help="Optional lowercase suffix for a side-by-side local verification app.")
    args = parser.parse_args()
    if args.verification_variant and not re.fullmatch(r"[a-z][a-z0-9]{0,19}", args.verification_variant):
        parser.error("Use a short lowercase alphanumeric verification variant.")
    runtime, app, output = (value.resolve() for value in (args.electron_app, args.composed_app, args.output))
    if output.exists() or output.suffix != ".app":
        parser.error("Use a fresh .app output path.")
    if output.is_relative_to(runtime) or runtime.is_relative_to(output) or output.is_relative_to(app):
        parser.error("The output must be separate from build inputs.")
    info = plistlib.loads((runtime / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != "com.github.Electron" or info.get("CFBundleVersion") != "43.4.1":
        parser.error("Use the official Electron 43.4.1 runtime pinned by Scribe.")
    if not (app / "synthetic-build.json").is_file() or not (app / "main.mjs").is_file():
        parser.error("Compose the local synthetic app first.")
    configuration = json.loads((app / "synthetic-build.json").read_text())
    authenticated = configuration.get("mode") in {"local-synthetic-authenticated", "hosted-beta-authenticated"}
    hosted = configuration.get("mode") == "hosted-beta-authenticated"
    operational = hosted and configuration.get("dataMode") == "authorized_beta"
    identity = _identity.validate(configuration.get("nativeIdentity"), "desktop", configuration.get("apiOrigin")) if operational else None
    if operational and args.verification_variant or not operational and configuration.get("nativeIdentity") is not None:
        parser.error("Operational identity cannot be combined with a synthetic package.")
    if hosted:
        manifest = json.loads((app / "public/cosmas-workspace-build.json").read_text())
        if (configuration.get("dataMode") not in {"synthetic", "authorized_beta"} or configuration.get("nativeAuthEnabled") is not True
                or manifest != {"version": 1, "client": "desktop", "dataMode": configuration["dataMode"],
                                "apiOrigin": configuration.get("apiOrigin"), "apiBase": "app://cosmas/api", "pageOrigin": "app://cosmas"}):
            parser.error("Hosted package configuration must match its authenticated web composition.")
    package = json.loads((app / "package.json").read_text())
    version, build = configuration.get("appVersion", package.get("version")), configuration.get("buildNumber", "1")
    if (not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,3})(?:\.(?:0|[1-9][0-9]{0,3})){2}", version)
            or not isinstance(build, str) or not re.fullmatch(r"[1-9][0-9]{0,3}", build)
            or package.get("version") != version):
        parser.error("The composition must have consistent numeric product and build versions.")
    installation = configuration.get("installation")
    if operational and (installation is None or installation.get("profile") != "beta" or
                        installation.get("bundleIdentifier") != "com.cosmasos.beta.desktop" or
                        installation.get("rendererPartition") != "persist:cosmasos-operational-beta" or
                        configuration.get("installationRoot") is not None):
        parser.error("Operational package requires its stable private installation identity.")
    if not operational and installation is not None and (not authenticated
            or not args.verification_variant or installation.get("profile") != args.verification_variant
            or installation.get("bundleIdentifier") != "com.cosmasos.synthetic.desktop." + args.verification_variant):
        parser.error("The package identity must match its stable installation profile.")
    if authenticated:
        helper = plistlib.loads((app / "native-auth/CosmasDesktopAuth.app/Contents/Info.plist").read_bytes())
        if operational and (helper.get("CosmasNativeAuth") != identity["auth"] or
                            helper.get("CosmasNativeIdentity") != identity["identity"] or
                            helper.get("CFBundleIdentifier") != identity["bundle"]):
            parser.error("Operational helper identity does not match the packaged workspace.")
        if installation is not None and installation.get("authHelperBundleIdentifier") != helper.get("CFBundleIdentifier"):
            parser.error("The installed profile must retain the packaged native helper identity.")
        versions = ["14.2" if configuration.get("nativeCaptureEnabled") else "14.0", info.get("LSMinimumSystemVersion", "12.0"), helper.get("LSMinimumSystemVersion")]
        if not all(isinstance(version, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", version) for version in versions):
            parser.error("Authenticated packaging requires explicit valid shell and helper macOS minimums.")
        # Launch Services must reject unsupported Macs before starting the shell;
        # Electron's lower minimum does not cover the bundled native auth SDK.
        info["LSMinimumSystemVersion"] = max(versions, key=lambda version: tuple(int(part) for part in version.split(".")))
    if configuration.get("microphoneCaptureEnabled") is True:
        if not authenticated or not configuration.get("captureUploadOrigins"):
            parser.error("Microphone capture requires the authenticated upload composition.")
        info["NSMicrophoneUsageDescription"] = (
            "Cosmas records visit audio after you confirm consent and choose Start recording."
        )
    shutil.copytree(runtime, output, symlinks=True)
    info["CFBundleIdentifier"] = "com.cosmasos.beta.desktop" if operational else "com.cosmasos.synthetic.desktop"
    info["CFBundleShortVersionString"] = version
    info["CFBundleVersion"] = build
    info["CosmasElectronVersion"] = "43.4.1"
    info["CFBundleName"] = "CosmasOS Beta" if hosted else "CosmasOS Synth"
    info["CFBundleDisplayName"] = info["CFBundleName"]
    if args.verification_variant:
        info["CFBundleIdentifier"] += "." + args.verification_variant
        info["CFBundleName"] += " " + args.verification_variant.upper()
        info["CFBundleDisplayName"] = info["CFBundleName"]
    info.pop("CFBundleURLTypes", None)
    (output / "Contents/Info.plist").write_bytes(plistlib.dumps(info, sort_keys=False))
    shutil.copytree(app, output / "Contents/Resources/app")
    print(f"Packaged local development app: {output}")
    print("No signing identity, notarization, or release approval was used.")


if __name__ == "__main__":
    main()
