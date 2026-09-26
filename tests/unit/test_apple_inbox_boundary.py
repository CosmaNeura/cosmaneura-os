"""Read-only pinned-source compatibility; no Swift execution, keychain or app composition."""

import base64
import hashlib
import importlib.util
import json
import os
import re
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(os.environ.get("COSMAS_APPLE_QUALIFICATION_ROOT", Path(__file__).parents[2])).resolve()
REF = "ea7f99d0278a05706531ffb1288cb1df7acf507b"
SWIFT = "apps/capture/native-plugins/secure-queue/ios/Sources/CosmaneuraSecureQueue/"
PINNED = {
    "SecureQueueRecordCodec.swift": "f80a70977cd1b75553edea782e750420d28ab5725dc707925399a76b84cc5061",
    "SecureQueueStore.swift": "1441b6ab9f16c09c0a727a0f31656cddc17267ceae95c32e10cded9de8c7d7b4",
    "SecureQueuePlugin.swift": "8c646d50394161c321c482977fe4c32f0f170f290cc6e1adb1f0e4fa6388fc9c",
}
ADDRESS = ("account-editor:inbox-work", "account-editor:inbox-handoffs")


def local_evidence(variable, default):
    """Explicit local fixtures are portable across isolated qualification layouts."""
    configured = os.environ.get(variable)
    candidate = Path(configured) if configured else ROOT / default
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    if not candidate.is_file():
        if configured:
            pytest.fail(f"Configured local evidence is unavailable: {variable}")
        pytest.skip(f"Local evidence required; set {variable}")
    return candidate.resolve()


def scribe_source():
    configured = os.environ.get("COSMAS_APPLE_SCRIBE_SOURCE")
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        if not candidate.is_dir():
            pytest.fail("Configured local Scribe source is unavailable")
        return candidate.resolve()
    # Only inspect a known sibling name at repository ancestors, never search
    # the user's filesystem or infer a different source revision.
    for parent in ROOT.parents:
        candidate = parent / "cosmaneura-scribe-beta-preintegration-20260904"
        if candidate.is_dir():
            return candidate.resolve()
    pytest.skip("Read-only pinned source required; set COSMAS_APPLE_SCRIBE_SOURCE")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("Apple source qualification prohibits network access")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


def composer():
    spec = importlib.util.spec_from_file_location("inbox_apple_composer", ROOT / "scripts/prepare-apple-synthetic.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pinned(name):
    # Fixed local commit/path only. Never checkout, compose, build or invoke a service.
    raw = subprocess.check_output(["git", "show", f"{REF}:{SWIFT}{name}"], cwd=scribe_source())
    assert hashlib.sha256(raw).hexdigest() == PINNED[name]
    return raw.decode("utf-8")


def test_current_apple_inputs_retain_the_exact_qualified_composer_and_token_burst_layer():
    provenance = json.loads(local_evidence("COSMAS_APPLE_QUALIFICATION_MANIFEST", "APPLE_QUALIFICATION_INPUTS.json").read_text())
    expected = {
        "scripts/prepare-apple-synthetic.py": "03db518d9418c0b4d36ff52716c88220769159fbf33e1c9475a529f28e8f4884",
        "clients/capture/src/native/workspace-auth-plugin.ts": "59f3739376e34743fe1762e64873cec581a4cae07e66933b64ed90613d55aa28",
        "clients/capture/src/native/workspace-auth-requests.ts": "490ccabbceffd6e66466f22f55cb87708a41094c95daa587bfa59702329929ca",
        "web/src/draft-store.ts": "c413d9da171232b89a0f374dc6e35efdc4688f7204f92bb52f9fed695a37511b",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
        assert provenance[name]["sha256"] == digest
    assert composer().SOURCE_REF == REF


@pytest.mark.parametrize("name", PINNED)
def test_queue_sources_match_the_pinned_commit_and_the_previously_qualified_package(name):
    pinned(name)
    previous = json.loads(local_evidence("COSMAS_APPLE_BASELINE_COMPOSITION", "apple-qualification-baseline/composition.json").read_text())
    assert previous["source_ref"] == REF
    assert previous["source_sha256"][SWIFT + name] == PINNED[name]
    assert previous["composed_sha256"][SWIFT + name] == PINNED[name]


def test_exact_origin_policy_keeps_webkit_fetch_and_requires_no_new_native_http_permissions():
    module = composer()
    policy = module.local_workspace_policy("http://127.0.0.1:8046")
    directives = dict(entry.split(" ", 1) for entry in policy["content_security_policy"].split("; "))
    assert policy["page_origin"] == "capacitor://localhost"
    assert policy["http_transport"] == "WKWebView.fetch"
    assert policy["capacitor_http_enabled"] is False
    assert directives["connect-src"] == "'self' http://127.0.0.1:8046"
    assert directives["default-src"] == "'none'"
    assert directives["form-action"] == directives["object-src"] == directives["base-uri"] == "'none'"
    for path in ("/inbox", "/inbox-handoffs", "/provider-team/identity"):
        target = urlsplit(policy["api_origin"] + path)
        assert f"{target.scheme}://{target.netloc}" == "http://127.0.0.1:8046"
    page = '<html><head><script src="/assets/app.js"></script></head><body></body></html>'
    protected = module.workspace_policy_html(page, policy)
    assert protected.index('http-equiv="Content-Security-Policy"') < protected.index("<script")
    assert "unsafe-eval" not in protected


@pytest.mark.parametrize("origin", [
    "http://127.0.0.1:8046/inbox", "http://127.0.0.1:8046?path=/inbox", "http://127.0.0.1:8046#inbox",
    "http://127.0.0.1:8046/", "http://outside.invalid:8046", "https://127.0.0.1:8046",
])
def test_new_routes_do_not_expand_the_exact_origin_configuration(origin):
    with pytest.raises(ValueError, match="exact loopback"):
        composer().local_workspace_policy(origin)


@pytest.mark.parametrize("address,expected_key_bytes", tuple(zip(ADDRESS, (114, 118), strict=True)))
def test_scoped_inbox_keys_fit_the_actual_native_key_limit_without_aliasing(address, expected_key_bytes):
    codec = pinned("SecureQueueRecordCodec.swift")
    key_limit = int(re.search(r"static let maximumKeyBytes = ([0-9]+)", codec)[1])
    key = "cosmas-private-draft:v1:" + "a" * 64 + ":" + address
    other_account = "cosmas-private-draft:v1:" + "b" * 64 + ":" + address
    assert len(key.encode("utf-8")) == expected_key_bytes < key_limit == 512
    assert hashlib.sha256(key.encode()).digest() != hashlib.sha256(other_account.encode()).digest()
    assert "keyData.count <= maximumKeyBytes" in codec
    assert "Data(SHA256.hash(data: try validatedKeyData(key)))" in codec


def test_root_value_and_native_frame_allowances_preserve_the_128k_record_bound():
    store = (ROOT / "web/src/draft-store.ts").read_text()
    record_bytes, value_allowance = map(int, re.search(r"const INBOX_VALUE_BYTES = ([0-9]+) \+ ([0-9]+);", store).groups())
    native_allowance = int(re.search(r"FRAME_ALLOWANCE = ([0-9]+);", store)[1])
    assert record_bytes == 131072
    assert record_bytes + value_allowance == 131584
    maximum_frame = record_bytes + value_allowance + native_allowance
    assert maximum_frame == 132096
    # Canonical base64 expansion is the only binary-to-string transport framing.
    encoded = base64.b64encode(bytes(maximum_frame))
    assert len(encoded) == 176128
    assert len(base64.b64decode(encoded, validate=True)) == maximum_frame
    for address in ADDRESS:
        assert f'id === "{address}"' in store
    assert "? INBOX_VALUE_BYTES :" in store
    assert "const frameLimit = limit(id) + FRAME_ALLOWANCE;" in store
    assert "const frame = json({ version: 1, scope, address: id, value }, limit(id) + FRAME_ALLOWANCE);" in store
    # The native queue is generic key/data storage: web validation supplies these
    # per-address limits. This source check does not claim a native body cap.
    plugin = pinned("SecureQueuePlugin.swift")
    assert plugin.count('let encoded = call.getString("data")') == 3
    assert plugin.count("data.base64EncodedString() == encoded") == 3


def test_pinned_queue_preserves_exact_cas_and_authenticated_device_custody_source():
    store = pinned("SecureQueueStore.swift")
    assert "private let operationLock = NSLock()" in store
    assert "guard current.revision == expectedRevision else" in store
    assert "guard current.key == key else" in store
    assert "throw SecureQueueError.revisionConflict" in store
    assert "AES.GCM.seal(" in store and "AES.GCM.open(" in store
    assert store.count("authenticating: Self.envelopeMagic + digest") == 2
    assert "options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]" in store
    assert "kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly" in store
    assert "kSecAttrSynchronizable: kCFBooleanFalse" in store
    assert "resourceValues.isExcludedFromBackup = true" in store
    assert "loadStorageKey(allowCreate: !hasRecords)" in store
    assert "loadStorageKey(allowCreate: false)" in store
