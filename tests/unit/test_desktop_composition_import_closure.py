"""Exercise the real authenticated copy step without Scribe source or an app launch."""

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSER = ROOT / "scripts/prepare-desktop-synthetic.py"
NODE = shutil.which("node")


def staged_auth_modules(tmp_path: Path) -> Path:
    tree = ast.parse(COMPOSER.read_text())
    loops = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple)
        and any(isinstance(item, ast.Constant) and item.value == "workspace-auth-proxy.mjs"
                for item in node.iter.elts)
    ]
    assert len(loops) == 1, "Authenticated composition must have one explicit module copy step"
    app = tmp_path / "staged app"
    app.mkdir()
    # Execute only the production copy loop. No source extraction, native helper,
    # build provenance, Electron runtime or installed application is fabricated.
    document_copy = [node for node in ast.walk(tree) if isinstance(node, ast.Expr)
                     and isinstance(node.value, ast.Call)
                     and any(isinstance(child, ast.Constant)
                             and child.value == "clients/shared/workspace-document.mjs"
                             for child in ast.walk(node))]
    assert len(document_copy) == 1, "The shared document guard must be staged inside the package"
    step = ast.fix_missing_locations(ast.Module(body=loops + document_copy, type_ignores=[]))
    exec(compile(step, str(COMPOSER), "exec"), {"root": ROOT, "app": app, "shutil": shutil})
    return app


def import_staged_proxy(app: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [NODE, "--input-type=module", "-e",
         "const proxy=await import(process.argv[1]);"
         "if(typeof proxy.proxyAuthenticatedWorkspaceRequest!=='function')process.exit(2);",
         (app / "workspace-auth-proxy.mjs").as_uri()],
        capture_output=True, text=True, timeout=10,
    )


@pytest.mark.skipif(NODE is None, reason="Node is required for Desktop module linking")
def test_authenticated_composition_links_proxy_from_only_staged_modules(tmp_path: Path):
    result = import_staged_proxy(staged_auth_modules(tmp_path))
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(NODE is None, reason="Node is required for Desktop module linking")
def test_staged_proxy_cannot_fall_back_to_unpackaged_checkout_modules(tmp_path: Path):
    app = staged_auth_modules(tmp_path)
    assert (ROOT / "clients/desktop/clinical-team-requests.mjs").is_file()
    (app / "clinical-team-requests.mjs").unlink(missing_ok=True)
    result = import_staged_proxy(app)
    assert result.returncode != 0
    assert "ERR_MODULE_NOT_FOUND" in result.stderr
    assert "clinical-team-requests.mjs" in result.stderr


@pytest.mark.skipif(NODE is None, reason="Node is required for Desktop module linking")
def test_staged_auth_uses_packaged_shared_document_guard_without_checkout_imports(tmp_path: Path):
    app = staged_auth_modules(tmp_path)
    assert (app / "workspace-document.mjs").read_bytes() == (
        ROOT / "clients/shared/workspace-document.mjs").read_bytes()
    result = subprocess.run(
        [NODE, "--input-type=module", "-e",
         "const auth=await import(process.argv[1]);const document=await import(process.argv[2]);"
         "if(typeof auth.installAuthIpc!=='function'||"
         "!document.isPackagedWorkspaceDocument('app://cosmas/index.html#cosmas/home')||"
         "document.isPackagedWorkspaceDocument('app://other/index.html#cosmas/home'))process.exit(2);",
         (app / "auth-ipc.mjs").as_uri(), (app / "workspace-document.mjs").as_uri()],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
