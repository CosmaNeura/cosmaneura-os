"""UNSIGNED synthetic Simulator configuration for composed iPhone projects."""

from __future__ import annotations

import importlib.util
import json
import plistlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "scripts/compose-portable-iphone.py"
CONFIGURE = ROOT / "scripts/configure-synthetic-iphone-simulator.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def composed(tmp_path: Path):
    compose = _load(COMPOSE, "compose_portable_iphone")
    output = tmp_path / "composed"
    compose.compose(ROOT, output)
    return output


def test_configure_sets_synthetic_bundle_and_copies_public(composed: Path, tmp_path: Path):
    configure = _load(CONFIGURE, "configure_synthetic_iphone_simulator")
    web = tmp_path / "dist"
    web.mkdir()
    (web / "index.html").write_text("<html>synthetic</html>\n", encoding="utf-8")
    project = configure.configure(composed, web)
    assert project.is_dir()
    pbx = (composed / "apps/capture/ios/App/App.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
    assert "PRODUCT_BUNDLE_IDENTIFIER = com.cosmasos.synthetic;" in pbx
    assert "PRODUCT_BUNDLE_IDENTIFIER = com.cosmasos.beta.ios;" not in pbx
    assert 'DEVELOPMENT_TEAM = "";' in pbx
    public = composed / "apps/capture/ios/App/App/public/index.html"
    assert public.read_text(encoding="utf-8") == "<html>synthetic</html>\n"
    info = plistlib.loads((composed / "apps/capture/ios/App/App/Info.plist").read_bytes())
    assert info["CFBundleURLTypes"][0]["CFBundleURLSchemes"] == ["com.cosmasos.synthetic"]
    receipt = json.loads((composed / "synthetic-simulator.json").read_text(encoding="utf-8"))
    assert receipt["bundle_id"] == "com.cosmasos.synthetic"
    assert receipt["signed"] is False
    assert receipt["code_signing_allowed"] is False


def test_configure_refuses_existing_public(composed: Path, tmp_path: Path):
    configure = _load(CONFIGURE, "configure_synthetic_iphone_simulator")
    web = tmp_path / "dist"
    web.mkdir()
    (web / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (composed / "apps/capture/ios/App/App/public").mkdir()
    with pytest.raises(ValueError, match="public must be absent"):
        configure.configure(composed, web)
