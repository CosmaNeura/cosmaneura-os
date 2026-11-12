#!/usr/bin/env python3
"""Prove synthetic demo + XCUITest mic hooks are Debug-only and Release-unreachable.

Uses a conditional-compilation-aware Release view: drop `#if DEBUG` branches,
keep their `#else` branches, and handle nested `#if`. A plain strip is not enough.
"""

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

FORBIDDEN_RELEASE_MARKERS = (
    "COSMAS_SKIP_SYNTHETIC_DEMO",
    "COSMAS_UI_TEST_START_CAPTURE",
    "skipLaunchArgument",
    "startCaptureLaunchArgument",
    "uiTest",
    "cosmas.uiTest",
)

_DIRECTIVE = re.compile(
    r"^\s*#\s*(if|ifdef|ifndef|elseif|elif|else|endif)\b(.*)$"
)
_DEBUG_CONDITION = re.compile(r"^\s*DEBUG(?:\s|/|$)")


def _is_debug_if(rest: str) -> bool:
    text = rest.strip()
    if text.startswith("!"):
        return False
    return _DEBUG_CONDITION.match(text) is not None


def swift_release_view(source: str) -> str:
    """Return source as a Release compiler would see it for `#if DEBUG` gates.

    - `#if DEBUG` true-branch is dropped; matching `#else` / `#elseif` non-DEBUG
      bodies are kept.
    - Nested `#if` inside a dropped DEBUG true-branch is skipped entirely
      (including its else).
    - Nested `#if` inside a kept branch is processed recursively via the stack.
    - Non-DEBUG `#if` / `#ifdef` / `#ifndef` keep their true branch and drop
      `#else` / later `#elseif` arms (Release assumes those conditions hold for
      structural nesting inside kept DEBUG-else content; top-level non-DEBUG
      conditionals still appear so nested DEBUG inside them is evaluated).
    """

    lines = source.splitlines(keepends=True)
    out: list[str] = []
    # Each frame: kind, keeping (emit body?), depth_of_skipped_children
    # kind: "debug" | "other"
    stack: list[dict[str, object]] = []

    def emitting() -> bool:
        return all(bool(frame["keeping"]) for frame in stack)

    for line in lines:
        match = _DIRECTIVE.match(line.rstrip("\n"))
        if match is None:
            if emitting():
                out.append(line)
            continue

        directive = match.group(1)
        rest = match.group(2) or ""

        if directive in {"if", "ifdef", "ifndef"}:
            if not emitting():
                # Nested inside a dropped branch: track only to balance endif.
                stack.append({"kind": "skip", "keeping": False})
                continue
            if directive == "if" and _is_debug_if(rest):
                # DEBUG true-branch dropped in Release.
                stack.append({"kind": "debug", "keeping": False, "seen_else": False})
            else:
                # Keep the true branch of other conditionals; drop else arms.
                stack.append({"kind": "other", "keeping": True, "seen_else": False})
            continue

        if directive in {"elseif", "elif"}:
            if not stack:
                raise ValueError(f"orphan #{directive}")
            frame = stack[-1]
            if frame["kind"] == "skip":
                continue
            if frame["kind"] == "debug":
                # Still under an outer DEBUG if: only a non-DEBUG elseif body
                # would compile in Release when DEBUG is false — treat as else
                # when the condition is not DEBUG.
                if _is_debug_if(rest):
                    frame["keeping"] = False
                else:
                    frame["keeping"] = not bool(frame.get("seen_else"))
                    frame["seen_else"] = True
            else:
                # Prior true branch of a non-DEBUG if already kept; later arms drop.
                frame["keeping"] = False
                frame["seen_else"] = True
            continue

        if directive == "else":
            if not stack:
                raise ValueError("orphan #else")
            frame = stack[-1]
            if frame["kind"] == "skip":
                continue
            if frame["kind"] == "debug":
                frame["keeping"] = True
                frame["seen_else"] = True
            else:
                frame["keeping"] = False
                frame["seen_else"] = True
            continue

        if directive == "endif":
            if not stack:
                raise ValueError("orphan #endif")
            stack.pop()
            continue

        raise ValueError(f"unhandled directive #{directive}")

    if stack:
        raise ValueError("unclosed #if in Swift source")
    return "".join(out)


_COMMENT = re.compile(
    r"""
    (?P<string>"(?:\\.|[^"\\])*")
    |(?P<line_comment>//.*?$)
    |(?P<block_comment>/\*.*?\*/)
    """,
    re.S | re.M | re.X,
)


def code_without_comments(source: str) -> str:
    """Drop comments so marker scans ignore doc references; keep string literals."""

    def repl(match: re.Match[str]) -> str:
        if match.group("string") is not None:
            return match.group(0)
        text = match.group(0)
        return "\n" * text.count("\n")

    return _COMMENT.sub(repl, source)


def _gate_should_present_release_body(release_gate: str) -> str:
    match = re.search(
        r"func shouldPresent\s*\([^)]*\)\s*->\s*Bool\s*\{(.*?)\}",
        release_gate,
        flags=re.S,
    )
    if match is None:
        raise ValueError("shouldPresent missing from Release gate view")
    return match.group(1).strip()


def check_sources(
    *,
    workspace: str,
    bridge: str,
    gate: str,
    plugin: str,
) -> int:
    if "#if DEBUG" not in workspace:
        print("FAIL: CosmasWorkspaceViewController.swift missing #if DEBUG", file=sys.stderr)
        return 1
    if "CosmasSyntheticDemoSurface" not in workspace:
        print("FAIL: demo surface type missing", file=sys.stderr)
        return 1
    if 'Bundle.main.bundleIdentifier == "com.cosmasos.synthetic"' not in workspace:
        print("FAIL: demo surface must stay on com.cosmasos.synthetic", file=sys.stderr)
        return 1
    if "skipLaunchArgument" not in workspace or "-COSMAS_SKIP_SYNTHETIC_DEMO" not in workspace:
        print("FAIL: skip-demo launch argument missing from workspace Debug source", file=sys.stderr)
        return 1
    if "uiTestStartRecordingThroughLoadedPlugin" not in bridge:
        print("FAIL: bridge missing uiTest start-recording call", file=sys.stderr)
        return 1
    if "AVAudioApplication.requestRecordPermission" in bridge:
        print("FAIL: bridge must not call AVAudioApplication.requestRecordPermission", file=sys.stderr)
        return 1
    if "uiTestStartRecordingThroughLoadedPlugin" not in plugin:
        print("FAIL: plugin missing uiTestStartRecordingThroughLoadedPlugin", file=sys.stderr)
        return 1
    if "isCompiledIntoThisBinary" not in gate:
        print("FAIL: SyntheticDemoFixtureGate missing compile proof hook", file=sys.stderr)
        return 1
    if "-COSMAS_SKIP_SYNTHETIC_DEMO" not in gate:
        print("FAIL: gate Debug source must honor -COSMAS_SKIP_SYNTHETIC_DEMO", file=sys.stderr)
        return 1

    try:
        release_workspace = swift_release_view(workspace)
        release_bridge = swift_release_view(bridge)
        release_gate = swift_release_view(gate)
        release_plugin = swift_release_view(plugin)
    except ValueError as error:
        print(f"FAIL: Release view parse error: {error}", file=sys.stderr)
        return 1

    for label, text in (
        ("CosmasWorkspaceViewController.swift", release_workspace),
        ("CosmasBridgeViewController.swift", release_bridge),
        ("SyntheticDemoFixtureGate.swift", release_gate),
        ("IOSPCMCapacitorPlugin.swift", release_plugin),
    ):
        code = code_without_comments(text)
        for marker in FORBIDDEN_RELEASE_MARKERS:
            if marker in code:
                print(
                    f"FAIL: Release view of {label} still contains {marker!r}",
                    file=sys.stderr,
                )
                return 1

    try:
        body = _gate_should_present_release_body(release_gate)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if body != "false":
        print(
            f"FAIL: gate shouldPresent Release body must be exactly 'false', got {body!r}",
            file=sys.stderr,
        )
        return 1

    print("PASS: synthetic demo fixture is #if DEBUG + com.cosmasos.synthetic only")
    print("PASS: SyntheticDemoFixtureGate shouldPresent Release body is exactly false")
    print("PASS: Release views of Bridge/Workspace/Gate/Plugin exclude XCUITest markers")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    workspace_path = VC
    bridge_path = BRIDGE
    gate_path = GATE
    plugin_path = PLUGIN
    # Optional overrides for negative tests: --workspace PATH --bridge PATH ...
    while args:
        flag = args.pop(0)
        if flag == "--workspace" and args:
            workspace_path = Path(args.pop(0))
        elif flag == "--bridge" and args:
            bridge_path = Path(args.pop(0))
        elif flag == "--gate" and args:
            gate_path = Path(args.pop(0))
        elif flag == "--plugin" and args:
            plugin_path = Path(args.pop(0))
        else:
            print(f"FAIL: unknown argument {flag}", file=sys.stderr)
            return 2
    return check_sources(
        workspace=workspace_path.read_text(encoding="utf-8"),
        bridge=bridge_path.read_text(encoding="utf-8"),
        gate=gate_path.read_text(encoding="utf-8"),
        plugin=plugin_path.read_text(encoding="utf-8"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
