#!/usr/bin/env python3
"""Package the source-bound, locally compiled Swift auth helper.

Copies the compiler product and its existing signature without a signing step.
No account configuration, installation or external service access.
"""
import argparse
import hashlib
import importlib.util
import plistlib
import re
import shutil
from pathlib import Path

_spec = importlib.util.spec_from_file_location("native_identity_build", Path(__file__).with_name("native_identity_build.py"))
_identity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_identity)
_spec = importlib.util.spec_from_file_location("native_auth_build_receipt", Path(__file__).with_name("native_auth_build_receipt.py"))
_binding = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_binding)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--compiler-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verification-variant", default="")
    parser.add_argument("--native-identity-config", type=Path, help="Explicit public operational identity; never read from the environment")
    parser.add_argument("--native-feature-profile", choices=("operational-beta-v1", "first-owner-staging-v1"), default="operational-beta-v1")
    args = parser.parse_args()
    products = _binding.directory(args.products)
    qualification = _binding.directory(args.qualification)
    output = args.output.resolve()
    receipt = args.compiler_receipt.absolute()
    identity = _identity.load(args.native_identity_config, "desktop")
    if identity and args.verification_variant:
        parser.error("Operational and synthetic helper identities cannot be combined.")
    if args.native_feature_profile == "first-owner-staging-v1" and not identity:
        parser.error("First-owner staging requires an operational native identity.")
    if args.output.is_symlink() or output.exists() or output.suffix != ".app" or not identity and not re.fullmatch(r"w[1-9][0-9]*[a-z]?", args.verification_variant):
        parser.error("Use a fresh .app output and a milestone verification variant.")
    if (output.is_relative_to(products) or output.is_relative_to(qualification)
            or output.is_relative_to(receipt.parent.resolve())):
        parser.error("Output must be separate from build inputs.")
    manifest = _binding.verify(receipt, qualification, products)
    receipt_hash = _binding.digest(receipt)
    files = _binding.product_inventory(products)
    if identity and manifest.get("native_identity_profile_version") != 1:
        parser.error("Rebuild the helper with operational identity support before configuring it.")
    if identity and manifest.get("native_source_version") != 1:
        parser.error("Rebuild the helper with native recording ownership before operational composition.")
    binary = products / "CosmasDesktopAuth"
    resources = products / "CosmasNativeAuthQualification_ClerkKit.bundle"
    if not binary.is_file() or not resources.is_dir():
        parser.error("Compile the native desktop executable and SDK resource bundle first.")
    (output / "Contents/MacOS").mkdir(parents=True)
    incomplete = b"Packaging has not completed.\n"
    (output / ".incomplete").write_bytes(incomplete)
    (output / ".incomplete").chmod(0o600)
    (output / "Contents/Resources").mkdir()
    shutil.copy2(binary, output / "Contents/MacOS/CosmasDesktopAuth")
    shutil.copytree(resources, output / "Contents/Resources" / resources.name)
    shutil.copyfile(qualification / "vendor/LICENSE", output / "Contents/Resources/ClerkKit-LICENSE.txt")
    (output / "Contents/Resources/ClerkKit-LICENSE.txt").chmod(0o644)
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
        info["CosmasConfiguredCapture"] = ({"enabled": False} if args.native_feature_profile == "first-owner-staging-v1"
                                           else {"enabled": True, "apiOrigin": identity["identity"]["apiOrigin"]})
        info["CFBundleURLTypes"] = [{"CFBundleURLName": identity["bundle"], "CFBundleURLSchemes": [identity["bundle"]]}]
    info_bytes = plistlib.dumps(info, sort_keys=False)
    (output / "Contents/Info.plist").write_bytes(info_bytes)
    (output / "Contents/Info.plist").chmod(0o644)
    _binding.verify(receipt, qualification, products)
    if _binding.digest(receipt) != receipt_hash:
        raise ValueError("Compiler receipt changed during packaging.")
    expected_output = {
        f"Contents/{'MacOS' if name == _binding.PRODUCT else 'Resources'}/{name}": item
        for name, item in files.items()
    }
    expected_output.update({
        ".incomplete": {"sha256": hashlib.sha256(incomplete).hexdigest(), "bytes": len(incomplete), "mode": 0o600},
        "Contents/Info.plist": {"sha256": hashlib.sha256(info_bytes).hexdigest(), "bytes": len(info_bytes), "mode": 0o644},
        "Contents/Resources/ClerkKit-LICENSE.txt": {
            "sha256": manifest["composed_sha256"]["vendor/LICENSE"],
            "bytes": (qualification / "vendor/LICENSE").stat().st_size, "mode": 0o644,
        },
    })
    if _binding.inventory(output) != expected_output:
        raise ValueError("Packaged output inventory differs from the compiler products and generated metadata.")
    (output / ".incomplete").unlink()
    print(f"Packaged native auth helper: {output}; identity {'configured' if identity else 'disabled'}; not launched")


if __name__ == "__main__":
    main()
