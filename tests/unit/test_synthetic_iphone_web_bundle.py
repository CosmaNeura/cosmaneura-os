"""CI-runnable checks for the synthetic iPhone web-bundle generator."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/prepare-synthetic-iphone-web-bundle.mjs"
TEST = ROOT / "scripts/prepare-synthetic-iphone-web-bundle.test.mjs"
TARGET_IDENTITY_FIXTURE = (
    ROOT / "tests/fixtures/iphone-sim/operational-native-identity-179e739f.mjs"
)
TOOLING_IDENTITY = ROOT / "clients/shared/operational-native-identity.mjs"


def _require_node() -> str:
    found = shutil.which("node")
    if found is None:
        raise AssertionError("node is required for synthetic iPhone web-bundle checks")
    return found


def _collect_prepare_deps() -> set[str]:
    """Closure of relative ESM imports starting at the prepare script."""
    needed: set[str] = set()
    queue = ["scripts/prepare-synthetic-iphone-web-bundle.mjs"]
    while queue:
        rel = queue.pop()
        if rel in needed:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        needed.add(rel)
        base = str(Path(rel).parent)
        for match in re.findall(r"from ['\"](\.[^'\"]+)['\"]", path.read_text(encoding="utf-8")):
            resolved = str(PurePosixPath(base).joinpath(match))
            if not resolved.endswith(".mjs"):
                resolved += ".mjs"
            parts: list[str] = []
            for part in resolved.split("/"):
                if part == "..":
                    if parts:
                        parts.pop()
                elif part != ".":
                    parts.append(part)
            queue.append("/".join(parts))
    return needed


def _apply_overlay_patch(src_root: Path, rel: str, tooling_file: Path) -> None:
    """Mirror run-iphone-sim-record-test.sh overlay_patch_or_absent for one file."""
    target = src_root / rel
    assert target.is_file()
    if target.read_bytes() == tooling_file.read_bytes():
        return
    diff = subprocess.run(
        ["diff", "-u", str(target), str(tooling_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    # diff returns 1 when files differ.
    assert diff.returncode == 1, diff.stderr
    lines = diff.stdout.splitlines(True)
    assert len(lines) >= 2
    lines[0] = f"--- a/{rel}\n"
    lines[1] = f"+++ b/{rel}\n"
    patch_file = src_root / ".overlay.patch"
    patch_file.write_text("".join(lines), encoding="utf-8")
    dry = subprocess.run(
        ["patch", "--batch", "--forward", "--dry-run", "-p1", "-i", str(patch_file)],
        cwd=src_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert dry.returncode == 0, dry.stdout + dry.stderr
    applied = subprocess.run(
        ["patch", "--batch", "--forward", "-p1", "-i", str(patch_file)],
        cwd=src_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr


def test_overlay_patches_target_179e739f_identity_so_synthetic_bundle_succeeds(
    tmp_path: Path,
) -> None:
    """Mac regression: PR #349 tip kept pre-synthetic.example identity.

    Runner overlays prepare-synthetic-iphone-web-bundle.mjs (absent on target)
    but used to keep target clients/shared/operational-native-identity.mjs, so
    `node scripts/prepare-synthetic-iphone-web-bundle.mjs` failed with
    'Operational native identity configuration is incomplete or inconsistent'.
    """
    node = _require_node()
    assert TARGET_IDENTITY_FIXTURE.is_file()
    fixture = TARGET_IDENTITY_FIXTURE.read_text(encoding="utf-8")
    assert ".synthetic.example" not in fixture
    assert "developmentFrontend" in fixture

    work = tmp_path / "overlay-work"
    for rel in sorted(_collect_prepare_deps()):
        dest = work / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)

    # Target tip keeps the older identity module (exact 179e739f bytes).
    identity_rel = "clients/shared/operational-native-identity.mjs"
    (work / identity_rel).write_text(fixture, encoding="utf-8")
    # Tooling overlays the absent prepare script (already copied from tip).

    before = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            "import {syntheticIphoneRendererInputs} from "
            "'./scripts/prepare-synthetic-iphone-web-bundle.mjs';"
            "syntheticIphoneRendererInputs();",
        ],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert before.returncode != 0
    assert "Operational native identity configuration is incomplete or inconsistent" in (
        before.stderr + before.stdout
    )

    _apply_overlay_patch(work, identity_rel, TOOLING_IDENTITY)

    out = tmp_path / "bundle-out"
    driver = work / "scripts" / "_overlay_synthetic_bundle_driver.mjs"
    driver.write_text(
        "\n".join(
            [
                "import {readFile} from 'node:fs/promises';",
                "import {join} from 'node:path';",
                "import {prepareSyntheticIphoneWebBundle} from "
                "'./prepare-synthetic-iphone-web-bundle.mjs';",
                "import {resolveBetaFeatureProfile} from "
                "'../clients/shared/beta-feature-profile.mjs';",
                "import {resolveHostedWorkspace} from "
                "'../clients/shared/hosted-workspace-config.mjs';",
                f"const output = {json.dumps(str(out))};",
                "const prepared = await prepareSyntheticIphoneWebBundle({output}, {",
                "  build: async (config) => {",
                "    const {mkdir, writeFile} = await import('node:fs/promises');",
                "    const env = JSON.parse(await readFile(join(output, 'inputs', 'apple-build-env.json'), 'utf8'));",
                "    await mkdir(config.build.outDir, {recursive: true});",
                "    await writeFile(join(config.build.outDir, 'index.html'), '<html></html>');",
                "    await writeFile(",
                "      join(config.build.outDir, 'cosmas-beta-features.json'),",
                "      JSON.stringify(resolveBetaFeatureProfile(env).manifest),",
                "    );",
                "    await writeFile(",
                "      join(config.build.outDir, 'cosmas-workspace-build.json'),",
                "      JSON.stringify({version: 1, ...resolveHostedWorkspace(env)}),",
                "    );",
                "  },",
                "});",
                "console.log('synthetic-bundle-ok');",
                "console.log(prepared.dist);",
                "",
            ]
        ),
        encoding="utf-8",
    )
    after = subprocess.run(
        [node, str(driver)],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={k: v for k, v in os.environ.items() if not k.startswith("VITE_")},
    )
    assert after.returncode == 0, after.stdout + "\n" + after.stderr
    assert "synthetic-bundle-ok" in after.stdout
    identity = json.loads((out / "inputs" / "apple-identity.json").read_text(encoding="utf-8"))
    assert identity["publishableKey"].startswith("pk_test_")
    assert identity["frontendOrigin"].endswith(".synthetic.example")
    assert identity["apiOrigin"].endswith(".synthetic.example")


def test_synthetic_web_bundle_generator_unit_suite() -> None:
    node = _require_node()
    result = subprocess.run(
        [node, "--test", str(TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    blob = result.stdout + result.stderr
    assert "staging accepts *.synthetic.example" in blob or "synthetic.example" in blob


def test_synthetic_inputs_are_pk_test_and_synthetic_example_only() -> None:
    node = _require_node()
    result = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            "import {syntheticIphoneRendererInputs} from "
            f"'file://{SCRIPT.as_posix()}';"
            "console.log(JSON.stringify(syntheticIphoneRendererInputs()));",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={k: v for k, v in os.environ.items() if not k.startswith("VITE_")},
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    files = json.loads(result.stdout)
    identity = files["apple-identity.json"]
    env = files["apple-build-env.json"]
    blob = json.dumps(files)
    assert identity["publishableKey"].startswith("pk_test_")
    assert identity["apiOrigin"].endswith(".synthetic.example")
    assert identity["frontendOrigin"].endswith(".synthetic.example")
    assert env["VITE_WORKSPACE_HOSTED_API_ORIGIN"].endswith(".synthetic.example")
    assert env["VITE_WORKSPACE_DATA_MODE"] == "synthetic"
    for forbidden in ("pk_live_", "sk_live_", "sk_test_", "cosmas.ai", "cosmaneura.com"):
        assert forbidden not in blob


def test_documented_prepare_command_exists() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "prepare-synthetic-iphone-web-bundle.mjs" in text
    assert "--output" in text
    assert "*.synthetic.example" in text or ".synthetic.example" in text
    assert "pk_test_" in text
