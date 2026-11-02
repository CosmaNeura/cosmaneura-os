#!/usr/bin/env python3
"""Prove the synthetic demo fixture is Debug-only and Release-unreachable."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VC = ROOT / "startup-recovery" / "CosmasWorkspaceViewController.swift"
GATE = ROOT / "startup-recovery" / "SyntheticDemoFixtureGate.swift"


def main() -> int:
    vc = VC.read_text()
    gate = GATE.read_text()

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

    if "isCompiledIntoThisBinary" not in gate:
        print("FAIL: SyntheticDemoFixtureGate missing compile proof hook", file=sys.stderr)
        return 1
    if "#else" not in gate or "false" not in gate.split("#else", 1)[1]:
        print("FAIL: gate must compile false under #else (Release)", file=sys.stderr)
        return 1

    # Soft build-settings reminder: App Debug sets SWIFT_ACTIVE_COMPILATION_CONDITIONS=DEBUG;
    # Release clears it, so #if DEBUG strips CosmasSyntheticDemoSurface from TestFlight.
    print("PASS: synthetic demo fixture is #if DEBUG + com.cosmasos.synthetic only")
    print("PASS: SyntheticDemoFixtureGate compiles false in Release (#else)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
