#!/usr/bin/env python3
"""Prove synthetic demo + XCUITest mic hooks are Debug-only and Release-unreachable."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENTS = ROOT.parent
VC = ROOT / "startup-recovery" / "CosmasWorkspaceViewController.swift"
BRIDGE = ROOT / "startup-recovery" / "CosmasBridgeViewController.swift"
GATE = ROOT / "startup-recovery" / "SyntheticDemoFixtureGate.swift"
PLUGIN = (
    CLIENTS
    / "capture/native-configured/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor"
    / "IOSPCMCapacitorPlugin.swift"
)


def main() -> int:
    vc = VC.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")
    gate = GATE.read_text(encoding="utf-8")
    plugin = PLUGIN.read_text(encoding="utf-8")

    if "#if DEBUG" not in vc:
        print("FAIL: CosmasWorkspaceViewController.swift missing #if DEBUG", file=sys.stderr)
        return 1
    if "CosmasSyntheticDemoSurface" not in vc:
        print("FAIL: demo surface type missing", file=sys.stderr)
        return 1
    if not re.search(
        r"#if DEBUG\s+.*?CosmasSyntheticDemoSurface\.isEnabled",
        vc,
        flags=re.S,
    ):
        print("FAIL: early demo return is not inside #if DEBUG", file=sys.stderr)
        return 1
    if 'Bundle.main.bundleIdentifier == "com.cosmasos.synthetic"' not in vc:
        print("FAIL: demo surface must stay on com.cosmasos.synthetic", file=sys.stderr)
        return 1
    if "skipLaunchArgument" not in vc or "-COSMAS_SKIP_SYNTHETIC_DEMO" not in vc:
        print("FAIL: skip-demo launch argument missing from workspace", file=sys.stderr)
        return 1
    if not re.search(
        r"#if DEBUG\s+.*?CosmasSyntheticDemoSurface\.skipLaunchArgument",
        vc,
        flags=re.S,
    ):
        print("FAIL: skip-demo openWorkspace path is not inside #if DEBUG", file=sys.stderr)
        return 1

    if "isCompiledIntoThisBinary" not in gate:
        print("FAIL: SyntheticDemoFixtureGate missing compile proof hook", file=sys.stderr)
        return 1
    if "#else" not in gate or "false" not in gate.split("#else", 1)[1]:
        print("FAIL: gate must compile false under #else (Release)", file=sys.stderr)
        return 1
    if "-COSMAS_SKIP_SYNTHETIC_DEMO" not in gate:
        print("FAIL: gate must honor -COSMAS_SKIP_SYNTHETIC_DEMO", file=sys.stderr)
        return 1

    if "uiTestStartRecordingThroughLoadedPlugin" not in bridge:
        print("FAIL: bridge missing uiTest start-recording call", file=sys.stderr)
        return 1
    if not re.search(
        r"#if DEBUG\s+.*?uiTestStartRecordingThroughLoadedPlugin",
        bridge,
        flags=re.S,
    ):
        print("FAIL: bridge uiTest start-recording call is not inside #if DEBUG", file=sys.stderr)
        return 1
    if "AVAudioApplication.requestRecordPermission" in bridge:
        print("FAIL: bridge must not call AVAudioApplication.requestRecordPermission", file=sys.stderr)
        return 1

    if "uiTestStartRecordingThroughLoadedPlugin" not in plugin:
        print("FAIL: plugin missing uiTestStartRecordingThroughLoadedPlugin", file=sys.stderr)
        return 1
    if not re.search(
        r"#if DEBUG\s+.*?uiTestStartRecordingThroughLoadedPlugin",
        plugin,
        flags=re.S,
    ):
        print("FAIL: plugin uiTest hook is not inside #if DEBUG", file=sys.stderr)
        return 1
    # Release must not retain the DEBUG-only method as an unprotected symbol.
    # Strip #if DEBUG ... #endif blocks and confirm the uiTest symbol disappears.
    stripped = re.sub(r"#if DEBUG[\s\S]*?#endif", "", plugin)
    if "uiTestStartRecordingThroughLoadedPlugin" in stripped:
        print("FAIL: plugin uiTest hook remains outside #if DEBUG", file=sys.stderr)
        return 1

    # Soft build-settings reminder: App Debug sets SWIFT_ACTIVE_COMPILATION_CONDITIONS=DEBUG;
    # Release clears it, so #if DEBUG strips CosmasSyntheticDemoSurface and uiTest hooks.
    print("PASS: synthetic demo fixture is #if DEBUG + com.cosmasos.synthetic only")
    print("PASS: SyntheticDemoFixtureGate compiles false in Release (#else)")
    print("PASS: bridge/plugin XCUITest mic hooks are #if DEBUG and stripped for Release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
