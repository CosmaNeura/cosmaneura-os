#!/usr/bin/env python3
"""Prove synthetic demo + XCUITest mic hooks are Debug-only and Release-unreachable.

Uses a conditional-compilation-aware Release view: drop only exact `#if DEBUG`
branches, keep exact `#if !DEBUG` branches, keep every arm of non-DEBUG
conditionals (so hooks cannot hide in `#else`), and fail closed on any other
condition that mentions DEBUG.
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
_TRAILING_LINE_COMMENT = re.compile(r"//.*$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _normalize_condition(rest: str) -> str:
    text = _BLOCK_COMMENT.sub("", rest)
    text = _TRAILING_LINE_COMMENT.sub("", text)
    return text.strip()


def _classify_condition(rest: str) -> str:
    """Classify a preprocessor condition for Release-view handling.

    Returns:
      exact_debug — drop this arm in Release
      exact_not_debug — keep this arm in Release
      non_debug — keep for scanning (all arms of the conditional stay visible)
    Raises ValueError for any other condition that mentions DEBUG (fail-closed).
    """
    text = _normalize_condition(rest)
    if text == "DEBUG":
        return "exact_debug"
    if text == "!DEBUG":
        return "exact_not_debug"
    if re.search(r"\bDEBUG\b", text):
        raise ValueError(f"ambiguous DEBUG condition (fail-closed): {rest!r}")
    return "non_debug"


def swift_release_view(source: str) -> str:
    """Return a fail-closed Release scan view of Swift preprocessor gates.

    - Exact `#if DEBUG` true-branch is dropped; its `#else` is kept.
    - Exact `#if !DEBUG` true-branch is kept; its `#else` is dropped.
    - Any other condition mentioning `DEBUG` raises (caller exits non-zero).
    - Non-DEBUG conditionals keep **all** arms so markers cannot hide in `#else`.
    - Nested `#if` inside a dropped arm is skipped entirely (balanced).
    """

    lines = source.splitlines(keepends=True)
    out: list[str] = []
    # kind: debug | not_debug | scan_all | skip
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
                stack.append({"kind": "skip", "keeping": False})
                continue
            if directive != "if":
                # ifdef/ifndef never name DEBUG as a bare flag here; keep all arms.
                stack.append({"kind": "scan_all", "keeping": True})
                continue
            kind = _classify_condition(rest)
            if kind == "exact_debug":
                stack.append({"kind": "debug", "keeping": False, "seen_else": False})
            elif kind == "exact_not_debug":
                stack.append({"kind": "not_debug", "keeping": True, "seen_else": False})
            else:
                stack.append({"kind": "scan_all", "keeping": True})
            continue

        if directive in {"elseif", "elif"}:
            if not stack:
                raise ValueError(f"orphan #{directive}")
            frame = stack[-1]
            if frame["kind"] == "skip":
                continue
            if frame["kind"] == "scan_all":
                # Keep every arm for marker scanning.
                _classify_condition(rest)  # still fail-closed if DEBUG appears
                frame["keeping"] = True
                continue
            if frame["kind"] == "debug":
                kind = _classify_condition(rest)
                if kind == "exact_debug":
                    frame["keeping"] = False
                else:
                    # Release: DEBUG is false, so first non-DEBUG elseif is active;
                    # keep it and any later arms for scanning.
                    frame["keeping"] = True
                    frame["seen_else"] = True
                continue
            if frame["kind"] == "not_debug":
                # True arm already kept for !DEBUG; later arms drop.
                _classify_condition(rest)
                frame["keeping"] = False
                frame["seen_else"] = True
                continue
            raise ValueError(f"unhandled frame kind {frame['kind']!r}")

        if directive == "else":
            if not stack:
                raise ValueError("orphan #else")
            frame = stack[-1]
            if frame["kind"] == "skip":
                continue
            if frame["kind"] == "scan_all":
                frame["keeping"] = True
                continue
            if frame["kind"] == "debug":
                frame["keeping"] = True
                frame["seen_else"] = True
                continue
            if frame["kind"] == "not_debug":
                frame["keeping"] = False
                frame["seen_else"] = True
                continue
            raise ValueError(f"unhandled frame kind {frame['kind']!r}")

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


def _gate_bool_property_release_body(release_gate: str, name: str) -> str:
    match = re.search(
        rf"(?:func|var)\s+{re.escape(name)}\b[^{{]*\{{(.*?)\}}",
        release_gate,
        flags=re.S,
    )
    if match is None:
        raise ValueError(f"{name} missing from Release gate view")
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
    if 'return allowed ? "granted" : "denied"' not in plugin:
        print(
            "FAIL: uiTestStartRecordingThroughLoadedPlugin must return "
            "granted/denied tokens (Don't Allow → cosmas.uiTest.micPermission.denied)",
            file=sys.stderr,
        )
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
        present_body = _gate_bool_property_release_body(release_gate, "shouldPresent")
        compiled_body = _gate_bool_property_release_body(release_gate, "isCompiledIntoThisBinary")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if present_body != "false":
        print(
            f"FAIL: gate shouldPresent Release body must be exactly 'false', got {present_body!r}",
            file=sys.stderr,
        )
        return 1
    if compiled_body != "false":
        print(
            "FAIL: gate isCompiledIntoThisBinary Release body must be exactly "
            f"'false', got {compiled_body!r}",
            file=sys.stderr,
        )
        return 1

    print("PASS: synthetic demo fixture is #if DEBUG + com.cosmasos.synthetic only")
    print("PASS: SyntheticDemoFixtureGate shouldPresent Release body is exactly false")
    print("PASS: SyntheticDemoFixtureGate isCompiledIntoThisBinary Release body is exactly false")
    print("PASS: Release views of Bridge/Workspace/Gate/Plugin exclude XCUITest markers")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    workspace_path = VC
    bridge_path = BRIDGE
    gate_path = GATE
    plugin_path = PLUGIN
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
