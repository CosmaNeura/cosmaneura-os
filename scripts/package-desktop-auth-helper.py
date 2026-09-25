#!/usr/bin/env python3
"""Package the locally compiled Swift auth helper with the SDK disabled.

Copies the compiler product and its existing signature without a signing step.
No account configuration, installation or external service access.
"""
import argparse
import hashlib
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
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verification-variant", default="")
    parser.add_argument("--native-identity-config", type=Path, help="Explicit public operational identity; never read from the environment")
    args = parser.parse_args()
    products, qualification, output = (p.resolve() for p in (args.products, args.qualification, args.output))
    identity = _identity.load(args.native_identity_config, "desktop")
    if identity and args.verification_variant:
        parser.error("Operational and synthetic helper identities cannot be combined.")
    if output.exists() or output.suffix != ".app" or not identity and not re.fullmatch(r"w[1-9][0-9]*[a-z]?", args.verification_variant):
        parser.error("Use a fresh .app output and a milestone verification variant.")
    if output.is_relative_to(products) or output.is_relative_to(qualification):
        parser.error("Output must be separate from build inputs.")
    manifest = json.loads((qualification / "qualification.json").read_text())
    if manifest.get("clerk_version") != "1.5.5" or manifest.get("includes_desktop_helper") is not True:
        parser.error("Use a qualified native desktop helper composition.")
    if identity and manifest.get("native_identity_profile_version") != 1:
        parser.error("Rebuild the helper with operational identity support before configuring it.")
    if identity and manifest.get("native_source_version") != 1:
        parser.error("Rebuild the helper with native recording ownership before operational composition.")
    for name, expected in manifest["composed_sha256"].items():
        if hashlib.sha256((qualification / name).read_bytes()).hexdigest() != expected:
            parser.error("Qualification source has changed; recompose and rebuild first.")
    binary = products / "CosmasDesktopAuth"
    resources = products / "CosmasNativeAuthQualification_ClerkKit.bundle"
    if not binary.is_file() or not resources.is_dir():
        parser.error("Compile the native desktop executable and SDK resource bundle first.")
    (output / "Contents/MacOS").mkdir(parents=True)
    (output / "Contents/Resources").mkdir()
    shutil.copy2(binary, output / "Contents/MacOS/CosmasDesktopAuth")
    shutil.copytree(resources, output / "Contents/Resources" / resources.name)
    shutil.copyfile(qualification / "vendor/LICENSE", output / "Contents/Resources/ClerkKit-LICENSE.txt")
    info = {
        "CFBundleIdentifier": identity["bundle"] if identity else "com.cosmasos.synthetic.desktop.auth." + args.verification_variant,
        "CFBundleName": "Cosmas Secure Sign-In", "CFBundleDisplayName": "Cosmas Secure Sign-In",
        "CFBundleExecutable": "CosmasDesktopAuth", "CFBundlePackageType": "APPL",
        "CFBundleVersion": "0.1.0", "CFBundleShortVersionString": "0.1.0",
        "LSMinimumSystemVersion": "14.0", "LSUIElement": True,
        "NSHighResolutionCapable": True, "CosmasNativeAuth": identity["auth"] if identity else {"enabled": False},
    }
    if identity:
        info["CosmasNativeIdentity"] = identity["identity"]
        info["CosmasConfiguredCapture"] = {"enabled": True, "apiOrigin": identity["identity"]["apiOrigin"]}
        info["CFBundleURLTypes"] = [{"CFBundleURLName": identity["bundle"], "CFBundleURLSchemes": [identity["bundle"]]}]
    (output / "Contents/Info.plist").write_bytes(plistlib.dumps(info, sort_keys=False))
    print(f"Packaged native auth helper: {output}; identity {'configured' if identity else 'disabled'}; not launched")


if __name__ == "__main__":
    main()
