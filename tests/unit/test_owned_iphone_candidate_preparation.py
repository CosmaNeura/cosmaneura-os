"""Public candidate options cannot change the existing Beta account by default."""

import base64
import copy
import importlib.util
import json
import plistlib
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("owned_iphone_preparation", ROOT / "scripts/prepare-owned-iphone-candidate.py")
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)
NAVIGATION = PREPARE.load_module(ROOT, "cosmaneura_navigation_build")


def practice_configuration():
    host = "invented-practice.clerk.accounts.dev"
    return {
        "enabled": True,
        "accountOrigin": "https://enrollment.example.invalid",
        "realm": {
            "publishableKey": "pk_test_" + base64.b64encode((host + "$").encode()).decode(),
            "frontendOrigin": "https://" + host,
            "audience": "",
            "profile": "operational-staging-v1",
            "keychainNamespace": "a" * 64,
        },
        "apiOrigins": [],
        "registeredPracticeOrigins": "synthetic-practice-uuid-staging-v1",
    }


def production_practice_configuration():
    host = "clerk.cosmas.ai"
    return {
        "enabled": True,
        "accountOrigin": "https://enrollment-api.cosmas.ai",
        "realm": {
            "publishableKey": "pk_live_" + base64.b64encode((host + "$").encode()).decode(),
            "frontendOrigin": "https://" + host,
            "audience": "cosmabot-practice-api",
            "profile": "operational-beta-v1",
            "keychainNamespace": "c" * 64,
        },
        "apiOrigins": [],
        "registeredPracticeOrigins": "practice-uuid-production-v1",
    }


def public_beta():
    host = "clerk.synthetic.example.invalid"
    native = {
        "version": 1, "profile": "operational-beta-v1", "client": "apple",
        "apiOrigin": "https://api.synthetic.example.invalid",
        "publishableKey": "pk_live_" + base64.b64encode((host + "$").encode()).decode(),
        "frontendOrigin": "https://" + host, "organizationId": "org_invented_beta",
        "audience": "cosmas-os-beta",
    }
    auth = {"enabled": True, **{key: value for key, value in native.items()
                               if key in {"profile", "publishableKey", "frontendOrigin", "organizationId", "audience"}}}
    return {"identity": native, "auth": auth, "bundle": "com.cosmasos.beta.ios"}


def retained_beta(identity):
    return {
        "CFBundleIdentifier": identity["bundle"],
        "CosmasNativeIdentity": copy.deepcopy(identity["identity"]),
        "CosmasNativeAuth": copy.deepcopy(identity["auth"]),
        "CosmasSourceAccessGroup": "SYNTHETIC.com.cosmasos.beta.sources",
        "GoogleConnectionClientID": "invented.apps.googleusercontent.com",
        "GoogleConnectionCallbackURI": "https://api.synthetic.example.invalid/connections/google/callback",
        "CFBundleVersion": "invented-old-version",
        PREPARE.PRACTICE_KEY: practice_configuration(),
    }


def scaffold():
    return {
        "CFBundleIdentifier": "$(PRODUCT_BUNDLE_IDENTIFIER)",
        "CFBundleVersion": "$(CURRENT_PROJECT_VERSION)",
        "CFBundleURLTypes": [{"CFBundleURLSchemes": ["com.cosmasos.beta.ios"]}],
        "CosmasConfiguredCapture": {"enabled": False},
        "NSMicrophoneUsageDescription": "Existing reviewed text",
    }


def test_candidate_options_require_one_retained_app_and_do_not_enable_practice_by_default():
    common = ["--inputs", "/invented/public", "--node", "/invented/node", "--output", "/invented/new"]
    args = PREPARE.arguments([*common, "--retained-info", "/invented/Info.plist"])
    assert args.native_practice_config is None
    assert args.include_desktop_renderer is False
    assert args.retained_ipa is None
    for selection in ([], ["--retained-info", "/invented/Info.plist", "--retained-ipa", "/invented/app.ipa"]):
        with pytest.raises(SystemExit):
            PREPARE.arguments([*common, *selection])


def test_default_candidate_preserves_beta_identity_source_google_and_scaffold_without_new_realm():
    identity, before = public_beta(), scaffold()
    retained = retained_beta(identity)
    original = copy.deepcopy((before, retained, identity))
    result = PREPARE.configured_info(before, retained, identity, validate_google=NAVIGATION.validate_google)
    assert PREPARE.PRACTICE_KEY not in result
    assert result["CosmasNativeIdentity"] == identity["identity"]
    assert result["CosmasNativeAuth"] == identity["auth"]
    for key in PREPARE.RETAINED_FIELDS:
        assert result[key] == retained[key]
    assert {key: result[key] for key in before} == before
    assert "invented-old-version" not in result.values()
    assert (before, retained, identity) == original


def test_explicit_practice_adds_only_owned_config_and_does_not_change_beta_credentials_or_callback():
    identity, before = public_beta(), scaffold()
    retained = retained_beta(identity)
    default = PREPARE.configured_info(before, retained, identity, validate_google=NAVIGATION.validate_google)
    config = practice_configuration()
    result = PREPARE.configured_info(before, retained, identity, config, NAVIGATION.validate_google)
    assert result.pop(PREPARE.PRACTICE_KEY) == config
    assert result == default
    config["realm"]["keychainNamespace"] = "b" * 64
    assert default["CosmasNativeIdentity"] == identity["identity"]


def test_practice_google_pin_is_optional_exact_and_keeps_the_beta_callback_unchanged():
    identity, retained = public_beta(), retained_beta(public_beta())
    value = practice_configuration()
    assert "googleConnection" not in PREPARE.native_practice_configuration(value)
    value["googleConnection"] = {
        "clientID": "invented-practice.apps.googleusercontent.com",
        "callbackURI": value["accountOrigin"] + "/connections/google/callback",
    }
    result = PREPARE.configured_info(scaffold(), retained, identity, value, NAVIGATION.validate_google)
    assert result[PREPARE.PRACTICE_KEY] == value
    assert result["GoogleConnectionClientID"] == retained["GoogleConnectionClientID"]
    assert result["GoogleConnectionCallbackURI"] == retained["GoogleConnectionCallbackURI"]
    assert result["CosmasNativeIdentity"] == identity["identity"]
    assert result["CosmasNativeAuth"] == identity["auth"]
    assert PREPARE.PRACTICE_KEY not in PREPARE.configured_info(
        scaffold(), retained, identity, validate_google=NAVIGATION.validate_google
    )
    for pair in (None, {}, {"clientID": value["googleConnection"]["clientID"]},
                 {**value["googleConnection"], "clientID": ""},
                 {**value["googleConnection"], "clientID": "invented"},
                 {**value["googleConnection"], "callbackURI": retained["GoogleConnectionCallbackURI"]},
                 {**value["googleConnection"], "callbackURI": value["googleConnection"]["callbackURI"] + "?next=other"},
                 {**value["googleConnection"], "scope": "gmail.send"}):
        rejected = copy.deepcopy(value)
        rejected["googleConnection"] = pair
        with pytest.raises(ValueError, match="pinned account-service callback"):
            PREPARE.native_practice_configuration(rejected)


@pytest.mark.parametrize("field", ["CFBundleIdentifier", "CosmasNativeIdentity", "CosmasNativeAuth"])
def test_retained_account_mismatch_is_rejected(field):
    identity, retained = public_beta(), retained_beta(public_beta())
    retained[field] = "another-app-or-account"
    with pytest.raises(ValueError, match="exactly match"):
        PREPARE.configured_info(scaffold(), retained, identity, validate_google=NAVIGATION.validate_google)


def test_google_pair_is_preserved_as_omitted_or_disabled_but_partial_configuration_is_rejected():
    identity, retained = public_beta(), retained_beta(public_beta())
    for key in PREPARE.RETAINED_FIELDS[1:]:
        retained.pop(key)
    result = PREPARE.configured_info(scaffold(), retained, identity, validate_google=NAVIGATION.validate_google)
    assert all(key not in result for key in PREPARE.RETAINED_FIELDS[1:])
    retained.update(GoogleConnectionClientID="", GoogleConnectionCallbackURI="")
    result = PREPARE.configured_info(scaffold(), retained, identity, validate_google=NAVIGATION.validate_google)
    assert result["GoogleConnectionClientID"] == result["GoogleConnectionCallbackURI"] == ""
    retained.pop("GoogleConnectionCallbackURI")
    with pytest.raises(ValueError, match="both Google"):
        PREPARE.configured_info(scaffold(), retained, identity, validate_google=NAVIGATION.validate_google)


@pytest.mark.parametrize("change", [
    lambda value: value.update(callbackURL="invented://callback"),
    lambda value: value.update(enabled="true"),
    lambda value: value.update(accountOrigin="https://enrollment.example.invalid/path"),
    lambda value: value["realm"].update(profile="operational-beta-v1"),
    lambda value: value["realm"].update(audience="cosmas-os-beta"),
    lambda value: value["realm"].update(keychainNamespace="not-a-fixed-namespace"),
    lambda value: value["realm"].update(frontendOrigin="https://other.clerk.accounts.dev"),
    lambda value: value["realm"].update(publishableKey="pk_live_invented"),
    lambda value: value.update(apiOrigins=["https://api.example.invalid", "https://api.example.invalid"]),
    lambda value: value.update(apiOrigins=["https://api.example.invalid:443"]),
    lambda value: value.update(apiOrigins=[f"https://api-{index}.example.invalid" for index in range(33)]),
    lambda value: value.update(registeredPracticeOrigins="*"),
    lambda value: value.update(registeredPracticeOrigins="exact"),
    lambda value: value.update(registeredPracticeOrigins="practice-uuid-production-v1"),
])
def test_practice_config_rejects_unreviewed_account_callback_namespace_and_origin_inputs(change):
    value = practice_configuration()
    change(value)
    with pytest.raises(ValueError):
        PREPARE.native_practice_configuration(value)


def test_production_practice_config_is_accepted_and_embedded_without_changing_beta_identity():
    identity, before = public_beta(), scaffold()
    retained = retained_beta(identity)
    default = PREPARE.configured_info(before, retained, identity, validate_google=NAVIGATION.validate_google)
    config = production_practice_configuration()
    assert PREPARE.native_practice_configuration(config) == config
    result = PREPARE.configured_info(before, retained, identity, config, NAVIGATION.validate_google)
    assert result.pop(PREPARE.PRACTICE_KEY) == config
    assert result == default


@pytest.mark.parametrize("change", [
    lambda value: value.update(accountOrigin="https://enrollment.example.invalid"),
    lambda value: value.update(registeredPracticeOrigins="synthetic-practice-uuid-staging-v1"),
    lambda value: value.update(registeredPracticeOrigins="exact"),
    lambda value: value["realm"].update(audience=""),
    lambda value: value["realm"].update(profile="operational-staging-v1"),
    lambda value: value["realm"].update(frontendOrigin="https://invented.clerk.accounts.dev"),
    lambda value: value["realm"].update(
        publishableKey="pk_test_" + base64.b64encode(b"clerk.cosmas.ai$").decode()),
    lambda value: value["realm"].update(keychainNamespace="not-a-fixed-namespace"),
    lambda value: value.update(apiOrigins=["https://api.example.invalid", "https://api.example.invalid"]),
])
def test_production_practice_config_rejects_staging_mix_and_unreviewed_inputs(change):
    value = production_practice_configuration()
    change(value)
    with pytest.raises(ValueError):
        PREPARE.native_practice_configuration(value)


def test_exact_origin_policy_requires_unique_explicit_https_apis_and_disabled_is_not_omission():
    value = practice_configuration()
    value.pop("registeredPracticeOrigins")
    value["apiOrigins"] = ["https://api.invented.example.invalid"]
    assert PREPARE.native_practice_configuration(value) == value
    value["enabled"] = False
    assert PREPARE.native_practice_configuration(value)["enabled"] is False
    value.pop("realm")
    with pytest.raises(ValueError, match="owned Info schema"):
        PREPARE.native_practice_configuration(value)


def test_public_inputs_reject_duplicate_json_fields_and_symlinks(tmp_path):
    path = tmp_path / "public.json"
    path.write_text('{"enabled": false, "enabled": true}')
    with pytest.raises(ValueError, match="Duplicate"):
        PREPARE.public_json(path)
    path.write_text(json.dumps(practice_configuration()))
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        PREPARE.public_json(link)


def test_output_refuses_overwrite_source_or_input_overlap_and_creates_nothing(tmp_path):
    repository, inputs = tmp_path / "source", tmp_path / "public"
    repository.mkdir()
    inputs.mkdir()
    existing = tmp_path / "existing"
    existing.mkdir()
    for requested in (existing, repository / "candidate", inputs / "candidate"):
        with pytest.raises(ValueError):
            PREPARE.output_path(requested, [repository, inputs])
    link = tmp_path / "link"
    link.symlink_to(inputs, target_is_directory=True)
    with pytest.raises(ValueError):
        PREPARE.output_path(link, [repository, inputs])
    new = tmp_path / "new"
    assert PREPARE.output_path(new, [repository, inputs]) == new
    assert not new.exists()


def test_source_snapshot_refuses_uncommitted_source_before_preparing_a_candidate(tmp_path):
    repository = tmp_path / "source"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True, capture_output=True)
    (repository / "unreviewed-source").write_text("synthetic change")
    with pytest.raises(ValueError, match="tree must be clean"):
        PREPARE.source_snapshot(repository)


def test_retained_ipa_reads_only_one_public_info_and_refuses_ambiguous_apps(tmp_path):
    raw = plistlib.dumps(retained_beta(public_beta()))
    info = tmp_path / "Info.plist"
    info.write_bytes(raw)
    ipa = tmp_path / "old.ipa"
    with zipfile.ZipFile(ipa, "w") as archive:
        archive.writestr("Payload/Invented.app/Info.plist", raw)
        archive.writestr("Payload/Invented.app/unread-data", b"not-public-info")
    assert PREPARE.retained_info(ipa, True)[0] == PREPARE.retained_info(info)[0]
    assert PREPARE.retained_info(ipa, True)[1]["info_member"] == "Payload/Invented.app/Info.plist"
    with zipfile.ZipFile(ipa, "a") as archive:
        archive.writestr("Payload/Another.app/Info.plist", raw)
    with pytest.raises(ValueError, match="exactly one"):
        PREPARE.retained_info(ipa, True)


def test_existing_pure_policy_adds_only_exact_api_csp_and_refuses_configured_html():
    policy, apply = PREPARE.workspace_policy(ROOT, "https://api.synthetic.example.invalid", ())
    source = '<html><head><script type="module" src="/assets/app.js"></script></head><body></body></html>'
    result = apply(source, policy)
    assert result.index("Content-Security-Policy") < result.index("<script")
    assert "connect-src &#x27;self&#x27; https://api.synthetic.example.invalid" in result
    assert result.replace(result[result.index("\n    <meta"):result.index("<script")], "") == source
    with pytest.raises(ValueError, match="unconfigured"):
        apply(result, policy)
    with pytest.raises(ValueError, match="exact HTTPS"):
        PREPARE.workspace_policy(ROOT, "https://api.synthetic.example.invalid/unsafe", ())
