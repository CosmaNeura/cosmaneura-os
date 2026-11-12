"""Python proof that Release strips DEBUG-only Simulator XCUITest hooks."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "clients/apple/ui-tests/prove_release_excludes_demo_fixture.py"
WORKSPACE = ROOT / "clients/apple/startup-recovery/CosmasWorkspaceViewController.swift"
BRIDGE = ROOT / "clients/apple/startup-recovery/CosmasBridgeViewController.swift"
GATE = ROOT / "clients/apple/startup-recovery/SyntheticDemoFixtureGate.swift"
PLUGIN = (
    ROOT
    / "clients/capture/native-configured/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor"
    / "IOSPCMCapacitorPlugin.swift"
)

_BRIDGE_UITEST_BLOCK = re.compile(
    r"(?ms)^(?P<indent>\s*)#if DEBUG\n"
    r"(?P<body>\s*// Synthetic Simulator XCUITest only\..*?\n)"
    r"(?P=indent)#endif\n"
)
_BRIDGE_AUTH_BYPASS_EXACT = re.compile(
    r"(?ms)^(?P<indent>            )#if DEBUG\n"
    r"(?P<body>            if uiTestSkipDemo \{\n"
    r"                // Keep the loaded IOSPCM plugin; synthetic auth is expected to\n"
    r"                // fail without real Clerk keys\. Do not quarantine XCUITest probes\.\n"
    r"                startedNavigation = true\n"
    r"                super\.viewDidLoad\(\)\n"
    r"                return\n"
    r"            \}\n)"
    r"(?P=indent)#endif\n"
)
_WORKSPACE_SKIP_BOOT = re.compile(
    r"(?ms)^(?P<indent>\s*)#if DEBUG\n"
    r"(?P<body>\s*// Synthetic Simulator XCUITest: skip practice-host boot.*?\n"
    r".*?return\n"
    r"\s*\}\n)"
    r"(?P=indent)#endif\n"
)
_RELEASE_DEMO_STUB = re.compile(
    r"(?ms)^#else\n"
    r"/// Release/TestFlight: demo surface is not compiled in\. Keep a named hook so\n"
    r"/// source audits and tests can prove the Debug-only gate without shipping UI\.\n"
    r"enum CosmasSyntheticDemoSurface \{\n"
    r"    static let isCompiledIntoThisBinary = false\n"
    r"    static var isEnabled: Bool \{ false \}\n"
    r"\}\n"
    r"#endif\n"
)


def _run_prove(*, workspace: Path, bridge: Path, gate: Path, plugin: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace",
            str(workspace),
            "--bridge",
            str(bridge),
            "--gate",
            str(gate),
            "--plugin",
            str(plugin),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_prove_release_excludes_demo_and_uitest_hooks() -> None:
    completed = _run_prove(
        workspace=WORKSPACE,
        bridge=BRIDGE,
        gate=GATE,
        plugin=PLUGIN,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    blob = completed.stdout + completed.stderr
    assert "PASS: synthetic demo fixture" in blob
    assert "PASS: SyntheticDemoFixtureGate shouldPresent Release body is exactly false" in blob
    assert "PASS: SyntheticDemoFixtureGate isCompiledIntoThisBinary Release body is exactly false" in blob
    assert "PASS: Release views of Bridge/Workspace/Gate/Plugin exclude XCUITest markers" in blob


def _copy_sources(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    workspace = tmp_path / "CosmasWorkspaceViewController.swift"
    bridge = tmp_path / "CosmasBridgeViewController.swift"
    gate = tmp_path / "SyntheticDemoFixtureGate.swift"
    plugin = tmp_path / "IOSPCMCapacitorPlugin.swift"
    shutil.copyfile(WORKSPACE, workspace)
    shutil.copyfile(BRIDGE, bridge)
    shutil.copyfile(GATE, gate)
    shutil.copyfile(PLUGIN, plugin)
    return workspace, bridge, gate, plugin


def test_negative_unfence_bridge_uitest_viewdidload_block(tmp_path: Path) -> None:
    workspace, bridge, gate, plugin = _copy_sources(tmp_path)
    text = bridge.read_text(encoding="utf-8")
    match = _BRIDGE_UITEST_BLOCK.search(text)
    assert match is not None, "expected Bridge XCUITest viewDidLoad DEBUG block"
    bridged = text[: match.start()] + match.group("body") + text[match.end() :]
    bridge.write_text(bridged, encoding="utf-8")
    completed = _run_prove(workspace=workspace, bridge=bridge, gate=gate, plugin=plugin)
    assert completed.returncode != 0, completed.stdout + completed.stderr


def test_negative_unfence_workspace_skip_practice_boot(tmp_path: Path) -> None:
    workspace, bridge, gate, plugin = _copy_sources(tmp_path)
    text = workspace.read_text(encoding="utf-8")
    match = _WORKSPACE_SKIP_BOOT.search(text)
    assert match is not None, "expected Workspace skip-practice-boot DEBUG block"
    workspace.write_text(text[: match.start()] + match.group("body") + text[match.end() :], encoding="utf-8")
    completed = _run_prove(workspace=workspace, bridge=bridge, gate=gate, plugin=plugin)
    assert completed.returncode != 0, completed.stdout + completed.stderr


def test_negative_unfence_bridge_auth_failure_bypass(tmp_path: Path) -> None:
    workspace, bridge, gate, plugin = _copy_sources(tmp_path)
    text = bridge.read_text(encoding="utf-8")
    match = _BRIDGE_AUTH_BYPASS_EXACT.search(text)
    assert match is not None, "expected Bridge auth-failure XCUITest DEBUG bypass"
    bridge.write_text(text[: match.start()] + match.group("body") + text[match.end() :], encoding="utf-8")
    completed = _run_prove(workspace=workspace, bridge=bridge, gate=gate, plugin=plugin)
    assert completed.returncode != 0, completed.stdout + completed.stderr


def test_negative_unfence_workspace_and_release_stub_skip_launch_argument(tmp_path: Path) -> None:
    workspace, bridge, gate, plugin = _copy_sources(tmp_path)
    text = workspace.read_text(encoding="utf-8")
    boot = _WORKSPACE_SKIP_BOOT.search(text)
    assert boot is not None
    text = text[: boot.start()] + boot.group("body") + text[boot.end() :]
    stub = _RELEASE_DEMO_STUB.search(text)
    assert stub is not None, "expected Release CosmasSyntheticDemoSurface stub"
    leaked_stub = (
        "#else\n"
        "/// Release/TestFlight: demo surface is not compiled in. Keep a named hook so\n"
        "/// source audits and tests can prove the Debug-only gate without shipping UI.\n"
        "enum CosmasSyntheticDemoSurface {\n"
        "    static let isCompiledIntoThisBinary = false\n"
        "    static var isEnabled: Bool { false }\n"
        '    static let skipLaunchArgument = "-COSMAS_SKIP_SYNTHETIC_DEMO"\n'
        "}\n"
        "#endif\n"
    )
    workspace.write_text(text[: stub.start()] + leaked_stub + text[stub.end() :], encoding="utf-8")
    completed = _run_prove(workspace=workspace, bridge=bridge, gate=gate, plugin=plugin)
    assert completed.returncode != 0, completed.stdout + completed.stderr


def test_negative_gate_else_not_constant_false(tmp_path: Path) -> None:
    workspace, bridge, gate, plugin = _copy_sources(tmp_path)
    text = gate.read_text(encoding="utf-8")
    mutated = text.replace(
        "    public static func shouldPresent(bundleIdentifier: String?) -> Bool {\n"
        "        #if DEBUG\n"
        '        bundleIdentifier == "com.cosmasos.synthetic"\n'
        '            && !ProcessInfo.processInfo.arguments.contains("-COSMAS_SKIP_SYNTHETIC_DEMO")\n'
        "        #else\n"
        "        false\n"
        "        #endif\n"
        "    }",
        "    public static func shouldPresent(bundleIdentifier: String?) -> Bool {\n"
        "        #if DEBUG\n"
        '        bundleIdentifier == "com.cosmasos.synthetic"\n'
        '            && !ProcessInfo.processInfo.arguments.contains("-COSMAS_SKIP_SYNTHETIC_DEMO")\n'
        "        #else\n"
        "        bundleIdentifier != nil\n"
        "        #endif\n"
        "    }",
        1,
    )
    assert mutated != text, "gate shouldPresent #else mutation did not apply"
    gate.write_text(mutated, encoding="utf-8")
    completed = _run_prove(workspace=workspace, bridge=bridge, gate=gate, plugin=plugin)
    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert "shouldPresent Release body must be exactly 'false'" in (completed.stdout + completed.stderr)


def test_negative_debug_or_true_on_bridge_uitest_block(tmp_path: Path) -> None:
    """`#if DEBUG || true` must fail closed (not treated as exact DEBUG)."""
    workspace, bridge, gate, plugin = _copy_sources(tmp_path)
    text = bridge.read_text(encoding="utf-8")
    match = _BRIDGE_UITEST_BLOCK.search(text)
    assert match is not None
    mutated = text[: match.start()] + match.group(0).replace(
        "#if DEBUG\n",
        "#if DEBUG || true\n",
        1,
    ) + text[match.end() :]
    assert "#if DEBUG || true" in mutated
    bridge.write_text(mutated, encoding="utf-8")
    completed = _run_prove(workspace=workspace, bridge=bridge, gate=gate, plugin=plugin)
    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert "ambiguous DEBUG condition" in (completed.stdout + completed.stderr)


def test_negative_forbidden_marker_in_canimport_else_arm(tmp_path: Path) -> None:
    """Non-DEBUG `#else` arms stay in the Release view; a marker there must fail."""
    workspace, bridge, gate, plugin = _copy_sources(tmp_path)
    text = bridge.read_text(encoding="utf-8")
    # Inject a forbidden marker into the existing #else of canImport in stopForPracticeConnection.
    else_arm = (
        "        #else\n"
        "        return false\n"
        "        #endif\n"
        "    }\n"
        "\n"
        "    /// Retains both old plugins until physical and configured-owner closure finish.\n"
    )
    leaked_else = (
        "        #else\n"
        '        let uiTestLeak = "cosmas.uiTest.hidden"\n'
        "        return false\n"
        "        #endif\n"
        "    }\n"
        "\n"
        "    /// Retains both old plugins until physical and configured-owner closure finish.\n"
    )
    assert else_arm in text
    bridge.write_text(text.replace(else_arm, leaked_else, 1), encoding="utf-8")
    completed = _run_prove(workspace=workspace, bridge=bridge, gate=gate, plugin=plugin)
    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert "still contains" in (completed.stdout + completed.stderr)


def test_negative_gate_compiled_into_binary_else_not_constant_false(tmp_path: Path) -> None:
    workspace, bridge, gate, plugin = _copy_sources(tmp_path)
    text = gate.read_text(encoding="utf-8")
    mutated = text.replace(
        "    public static var isCompiledIntoThisBinary: Bool {\n"
        "        #if DEBUG\n"
        "        true\n"
        "        #else\n"
        "        false\n"
        "        #endif\n"
        "    }",
        "    public static var isCompiledIntoThisBinary: Bool {\n"
        "        #if DEBUG\n"
        "        true\n"
        "        #else\n"
        "        Bundle.main.bundleIdentifier != nil\n"
        "        #endif\n"
        "    }",
        1,
    )
    assert mutated != text
    gate.write_text(mutated, encoding="utf-8")
    completed = _run_prove(workspace=workspace, bridge=bridge, gate=gate, plugin=plugin)
    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert "isCompiledIntoThisBinary Release body must be exactly 'false'" in (
        completed.stdout + completed.stderr
    )


def test_swift_release_view_handles_nested_if() -> None:
    sys.path.insert(0, str(SCRIPT.parent))
    from prove_release_excludes_demo_fixture import swift_release_view

    source = (
        "#if DEBUG\n"
        "let a = 1\n"
        "#if canImport(Foo)\n"
        "let nested = true\n"
        "#else\n"
        "let nested = false\n"
        "#endif\n"
        "let leak = \"skipLaunchArgument\"\n"
        "#else\n"
        "let releaseOnly = true\n"
        "#endif\n"
        "let always = 0\n"
    )
    view = swift_release_view(source)
    assert "let a = 1" not in view
    assert "nested" not in view
    assert "skipLaunchArgument" not in view
    assert "let releaseOnly = true" in view
    assert "let always = 0" in view

    # Non-DEBUG conditionals keep every arm (else is scanned).
    scan_all = (
        "#if canImport(Foo)\n"
        "let keepTrue = 1\n"
        "#else\n"
        "let keepElse = 2\n"
        "#endif\n"
    )
    both = swift_release_view(scan_all)
    assert "let keepTrue = 1" in both
    assert "let keepElse = 2" in both
