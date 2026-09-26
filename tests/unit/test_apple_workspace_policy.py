"""Source-only mobile packaging checks; no app launch or device acceptance claim."""
import hashlib
import importlib.util
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SOURCE = ROOT.parent / "cosmaneura-scribe-beta-preintegration-20260904"


def composer():
    spec = importlib.util.spec_from_file_location("apple_policy_composer", ROOT / "scripts/prepare-apple-synthetic.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_local_csp_preserves_bundled_capture_and_verified_pdf_without_remote_permissions():
    policy = composer().local_workspace_policy("http://127.0.0.1:8046", ("http://127.0.0.1:8246",))
    directives = dict(part.split(" ", 1) for part in policy["content_security_policy"].split("; "))
    assert directives == {
        "default-src": "'none'", "base-uri": "'none'", "form-action": "'none'", "object-src": "'none'",
        "script-src": "'self'", "style-src": "'self' 'unsafe-inline'", "font-src": "'self'",
        "img-src": "'self' data: blob:", "media-src": "'self' blob:", "worker-src": "'self'",
        "frame-src": "blob:", "connect-src": "'self' http://127.0.0.1:8046 http://127.0.0.1:8246",
    }
    assert policy["http_transport"] == "WKWebView.fetch"
    assert policy["capacitor_http_enabled"] is False


def test_hosted_policy_pins_tls_api_and_uploads_without_allowing_loopback_or_native_http():
    policy = composer().hosted_workspace_policy("https://api.example.invalid", ("https://storage.example.invalid",))
    assert policy["purpose"] == "hosted-synthetic-beta"
    assert "connect-src 'self' https://api.example.invalid https://storage.example.invalid" in policy["content_security_policy"]
    assert "http://" not in policy["content_security_policy"]
    assert policy["capacitor_http_enabled"] is False
    for origin in ("http://api.example.invalid", "https://127.0.0.1", "https://api.example.invalid/", "https://api.example.invalid:443"):
        with pytest.raises(ValueError):
            composer().hosted_workspace_policy(origin)


@pytest.mark.parametrize("origin", [
    "http://127.0.0.1", "http://127.0.0.1:0", "http://127.0.0.1:08046", "http://127.0.0.1:65536",
    "http://127.0.0.1:8046/", "http://127.0.0.1:8046/path", "http://127.0.0.1:8046?token=secret",
    "http://127.0.0.1:8046#fragment", "http://user@127.0.0.1:8046", "http://127.1:8046",
    "https://127.0.0.1:8046", "http://remote.invalid:8046", "http://localhost.evil:8046",
    "http://*:8046", "http://127.0.0.1:8046; script-src *", " http://127.0.0.1:8046",
])
def test_invalid_policy_fails_before_source_or_output_access(tmp_path, origin):
    output = tmp_path / "unchanged"
    with pytest.raises(ValueError, match="exact loopback"):
        composer().prepare(tmp_path / "missing-source", tmp_path / "missing-web", output,
                           verification_variant="w36p", workspace_api_origin=origin)
    assert not output.exists()


def test_upload_policy_requires_explicit_separate_package_and_bounded_exact_origins(tmp_path):
    module = composer()
    with pytest.raises(ValueError, match="explicit Apple"):
        module.prepare(SOURCE, tmp_path, tmp_path / "missing", capture_upload_origins=("http://localhost:8246",))
    with pytest.raises(ValueError, match="separate verification"):
        module.prepare(SOURCE, tmp_path, tmp_path / "missing", workspace_api_origin="http://localhost:8046")
    with pytest.raises(ValueError, match="At most four"):
        module.local_workspace_policy("http://localhost:8046", tuple(f"http://localhost:{8200 + i}" for i in range(5)))
    with pytest.raises(ValueError, match="Duplicate"):
        module.local_workspace_policy("http://localhost:8046", ("http://localhost:8246",) * 2)
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("page", [
    "<title>no head</title>", "<head></head><head></head>", "<head><base href='/other/'></head>",
    '<head><meta http-equiv="Content-Security-Policy" content="default-src *"></head>',
    "<script src='/before.js'></script><head></head>",
])
def test_document_conflicts_fail_without_replacing_policy(page):
    module = composer()
    with pytest.raises(ValueError, match="unconfigured document"):
        module.workspace_policy_html(page, module.local_workspace_policy("http://localhost:8046"))


def test_csp_is_inserted_in_actual_head_before_resources_not_comment():
    module = composer()
    page = '<!-- <head> remains a comment -->\n<html><HEAD><script src="/assets/app.js"></script></HEAD></html>'
    value = module.workspace_policy_html(page, module.local_workspace_policy("http://[::1]:8046"))
    assert value.startswith('<!-- <head> remains a comment -->\n<html><HEAD>\n    <meta ')
    assert value.index('http-equiv="Content-Security-Policy"') < value.index('<script')


@pytest.mark.skipif(not SOURCE.is_dir(), reason="Read-only pinned Scribe source required")
def test_fresh_composition_copies_all_assets_and_keeps_legacy_profile_unchanged(tmp_path):
    module = composer()
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    page = '<!doctype html><html><head><script type="module" src="/assets/app.js"></script></head><body></body></html>'
    assets = {"index.html": page.encode(), "assets/app.js": b"/* synthetic module */",
              "assets/pcm-worklet.js": b"/* bundled audio worklet */", "assets/bot.webp": b"invented image bytes"}
    for name, data in assets.items():
        (web / name).write_bytes(data)
    before = {name: hashlib.sha256(data).hexdigest() for name, data in assets.items()}
    for selected in (False, True):
        output = tmp_path / ("policy" if selected else "legacy")
        module.prepare(SOURCE, web, output, verification_variant="w36p", **({
            "workspace_api_origin": "http://127.0.0.1:8046", "capture_upload_origins": ("http://127.0.0.1:8246",),
        } if selected else {}))
        app = output / "apps/capture/ios/App/App"
        config = json.loads((app / "capacitor.config.json").read_text())
        manifest = json.loads((output / "composition.json").read_text())
        if selected:
            assert config["server"] == {"hostname": "localhost", "iosScheme": "capacitor"}
            assert config["plugins"] == {"CapacitorHttp": {"enabled": False}}
            assert "allowNavigation" not in config["server"]
            assert manifest["local_workspace_policy"]["page_origin"] == "capacitor://localhost"
            class Meta(HTMLParser):
                policies = []

                def handle_starttag(self, tag, attrs):
                    attrs = dict(attrs)
                    if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy":
                        self.policies.append(attrs["content"])
            parsed = Meta()
            parsed.feed((app / "public/index.html").read_text())
            assert parsed.policies == [manifest["local_workspace_policy"]["content_security_policy"]]
        else:
            assert "server" not in config and "plugins" not in config
            assert manifest["local_workspace_policy"] is None
            assert (app / "public/index.html").read_bytes() == assets["index.html"]
        for name, expected in before.items():
            assert hashlib.sha256((web / name).read_bytes()).hexdigest() == expected
            if name != "index.html":
                assert (app / "public" / name).read_bytes() == assets[name]
        assert config["packageClassList"] == ["IOSPCMCapacitorPlugin", "SecureQueuePlugin"]
        for name, expected in manifest["composed_sha256"].items():
            assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
