import importlib.util
from pathlib import Path

import pytest

from cosmas_os.config import Settings


def configured(**changes):
    return Settings(_env_file=None, **{
        "workspace_enabled": True, "workspace_authenticated_enabled": True,
        "workspace_apple_local_transport_enabled": True,
        "database_url": "postgresql+psycopg://invented@127.0.0.1:55439/w1a_apple_test",
        "auth_mode": "clerk_jwt", "synth_seed": False,
        "cors_allowed_origins": "capacitor://localhost",
        "clerk_authorized_parties": "capacitor://localhost",
        "clerk_issuer": "https://clerk.example.invalid",
        "clerk_jwks_url": "https://clerk.example.invalid/.well-known/jwks.json",
        "clerk_audience": "workspace-local", "clerk_organization_id": "org_invented",
        "beta_box_id": "00000000-0000-4000-8000-000000000001", **changes,
    })


def test_apple_requires_a_separate_explicit_authenticated_profile():
    assert configured().workspace_available
    assert configured().runtime_configuration_errors() == []
    assert not Settings(_env_file=None).workspace_apple_local_transport_enabled


@pytest.mark.parametrize("changes", [
    {"workspace_apple_local_transport_enabled": False},
    {"workspace_authenticated_enabled": False}, {"workspace_enabled": False},
    {"workspace_native_synthetic_enabled": True}, {"auth_mode": "synth_headers"},
    {"synth_seed": True}, {"blob_backend": "azure"}, {"data_mode": "authorized_beta"},
    {"cosmas_env": "early_adopter_beta"},
    {"database_url": "postgresql+psycopg://invented@remote.invalid/w1a_apple_test"},
    {"database_url": "postgresql+psycopg://invented@localhost/existing_data"},
    {"cors_allowed_origins": "http://localhost:5173"},
    {"clerk_authorized_parties": "http://localhost:5173"},
    {"clerk_authorized_parties": "capacitor://localhost/"},
    {"cors_allowed_origins": "capacitor://localhost:8035"},
    {"cors_allowed_origins": "capacitor://other"},
])
def test_apple_transport_cannot_widen_existing_environment_or_identity_rules(changes):
    result = configured(**changes)
    assert not result.workspace_available
    assert result.runtime_configuration_errors()


def composition_module():
    path = Path(__file__).parents[2] / "scripts/prepare-apple-synthetic.py"
    spec = importlib.util.spec_from_file_location("apple_composition", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verification_variant_has_a_distinct_app_identity():
    script = composition_module()
    assert script.build_identity() == ("com.cosmasos.synthetic", "CosmasOS Synth")
    assert script.build_identity("w8m") == ("com.cosmasos.synthetic.w8m", "CosmasOS Synth W8M")


def test_source_journal_group_can_be_bound_before_unsigned_compilation():
    script = composition_module()
    bundle = "com.cosmasos.beta.ios"
    assert script.source_access_group(bundle, "JVV65668U6." + bundle) == "JVV65668U6." + bundle
    assert script.source_access_group(bundle, None) == "$(AppIdentifierPrefix)" + bundle
    for invalid in [bundle, "other." + bundle, "JVV65668U6.com.other", "JVV65668U6.*", " JVV65668U6." + bundle]:
        with pytest.raises(ValueError):
            script.source_access_group(bundle, invalid)


@pytest.mark.parametrize("variant", ["", "com.cosmaneura.capture", "../w8m", "w8m.other", "W8M", "w0"])
def test_verification_variant_cannot_select_an_existing_product_or_path(variant):
    with pytest.raises(ValueError):
        composition_module().build_identity(variant)


def test_simulator_custody_identity_cannot_share_another_variant_keychain():
    script = composition_module()
    first = script.simulator_custody_identity("w8n")
    second = script.simulator_custody_identity("w8z")
    assert first == {
        "application-identifier": "COSMASW8NT.com.cosmasos.synthetic.w8n",
        "com.apple.developer.team-identifier": "COSMASW8NT",
        "keychain-access-groups": ["COSMASW8NT.com.cosmasos.synthetic.w8n"],
    }
    assert set(first["keychain-access-groups"]).isdisjoint(second["keychain-access-groups"])


@pytest.mark.parametrize("variant", [None, "", "../w8n", "com.cosmaneura.capture", "w8n.*"])
def test_simulator_custody_rejects_unscoped_or_product_identity_before_writing(tmp_path, variant):
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError):
        composition_module().prepare(tmp_path / "source", tmp_path / "web", output,
                                     verification_variant=variant, simulator_custody=True)
    assert not output.exists()
