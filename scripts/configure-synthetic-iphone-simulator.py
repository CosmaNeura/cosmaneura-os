#!/usr/bin/env python3
"""Configure a composed portable iPhone project as an UNSIGNED Debug Simulator app.

Sets PRODUCT_BUNDLE_IDENTIFIER=com.cosmasos.synthetic, clears the signing team,
and copies a synthetic web bundle into App/public. Does not compile, sign,
install, or contact a network.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import shutil
from pathlib import Path

BUNDLE_ID = "com.cosmasos.synthetic"


def configure(project_root: Path, web_dist: Path) -> Path:
    app = project_root / "apps/capture/ios/App/App"
    project = project_root / "apps/capture/ios/App/App.xcodeproj/project.pbxproj"
    if not app.is_dir() or not project.is_file():
        raise ValueError("Composed iPhone project is missing App sources.")
    if not web_dist.is_dir() or not (web_dist / "index.html").is_file():
        raise ValueError("Synthetic web dist must contain index.html.")
    public = app / "public"
    if public.exists() or public.is_symlink():
        raise ValueError("App/public must be absent before configuration.")
    text = project.read_text(encoding="utf-8")
    text = re.sub(r"DEVELOPMENT_TEAM = [^;]+;", 'DEVELOPMENT_TEAM = "";', text)
    if "PRODUCT_BUNDLE_IDENTIFIER = com.cosmasos.beta.ios;" not in text:
        raise ValueError("Expected scaffold bundle id com.cosmasos.beta.ios to rewrite.")
    text = text.replace(
        "PRODUCT_BUNDLE_IDENTIFIER = com.cosmasos.beta.ios;",
        f"PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE_ID};",
    )
    project.write_text(text, encoding="utf-8")
    shutil.copytree(web_dist, public)
    info_path = app / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info["NSMicrophoneUsageDescription"] = (
        "Record an invented encounter only after you explicitly start a synthetic capture test."
    )
    info["CFBundleURLTypes"] = [
        {"CFBundleURLName": BUNDLE_ID, "CFBundleURLSchemes": [BUNDLE_ID]}
    ]
    info_path.write_bytes(plistlib.dumps(info, sort_keys=False))
    (app / "capacitor.config.json").write_text(
        json.dumps(
            {
                "appId": BUNDLE_ID,
                "appName": "CosmaBot Synthetic",
                "webDir": "public",
                "loggingBehavior": "none",
                "packageClassList": [
                    "IOSPCMCapacitorPlugin",
                    "SecureQueuePlugin",
                    "CosmasWorkspaceAuthPlugin",
                    "CosmasNativePracticeConnectionPlugin",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    receipt = {
        "purpose": "unsigned-synthetic-iphone-simulator",
        "bundle_id": BUNDLE_ID,
        "signed": False,
        "code_signing_allowed": False,
        "web_dist": str(web_dist),
        "project": str(project_root / "apps/capture/ios/App/App.xcodeproj"),
    }
    (project_root / "synthetic-simulator.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return project_root / "apps/capture/ios/App/App.xcodeproj"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--composed", type=Path, required=True, help="compose-portable-iphone output")
    parser.add_argument("--web-dist", type=Path, required=True, help="synthetic renderer dist/")
    args = parser.parse_args()
    try:
        project = configure(args.composed.resolve(), args.web_dist.resolve())
    except ValueError as error:
        parser.exit(2, f"{error}\n")
    print(f"Configured UNSIGNED synthetic Simulator project: {project}")
    print(f"Bundle id {BUNDLE_ID}; CODE_SIGNING_ALLOWED=NO at build time.")


if __name__ == "__main__":
    main()
