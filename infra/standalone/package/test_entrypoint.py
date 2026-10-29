"""Mounted-file and clean-environment checks; invented configuration only."""

import importlib.util
import json
import os
from pathlib import Path

import pytest
from tests.unit import test_standalone_runtime as offline
from tests.unit.test_standalone_beta_features import google_values, model_values

spec = importlib.util.spec_from_file_location("standalone_package_entrypoint", Path(__file__).with_name("entrypoint.py"))
assert spec and spec.loader
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)
standalone = offline.standalone


@pytest.fixture
def mounted(standalone, tmp_path):
    runtime, _, _ = standalone
    values = {name.upper(): value for name, value in runtime.model_dump().items()
              if value is not None and isinstance(value, str | int | bool)}
    values["HUMAN_DEPLOY_EVIDENCE_REF"] = "invented:package-qualification"
    private = {name: values.pop(name) for name in entrypoint.PRIVATE_NAMES}
    public_path, private_path = tmp_path / "api-public.json", tmp_path / "api-private.json"
    public_path.write_text(json.dumps(values))
    private_path.write_text(json.dumps(private))
    private_path.chmod(0o600)
    return public_path, private_path, values, private


def test_only_mounted_settings_reach_api_environment(mounted, monkeypatch):
    public, private, values, _ = mounted
    monkeypatch.setenv("COSMAS_ENV", "early_adopter_beta")
    monkeypatch.setenv("CORE_CAPTURE_ORIGIN", "https://forbidden.example.invalid")
    monkeypatch.setenv("HTTP_PROXY", "http://forbidden.example.invalid")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    result = entrypoint.load_configuration(public, private)
    assert result["COSMAS_ENV"] == "standalone_synthetic"
    assert result["PYTHONPATH"] == "/app/src"
    assert "HTTP_PROXY" not in result
    assert not result.get("CORE_CAPTURE_ORIGIN")
    assert result["STANDALONE_INSTANCE_ID"] == values["STANDALONE_INSTANCE_ID"]


def real_profile(values, policy="audience"):
    issuer = ("https://identity.invented-practice.test" if policy == "audience"
              else "https://invented-practice.clerk.accounts.dev")
    values.update(COSMAS_ENV="standalone_clerk_synthetic", STANDALONE_JWKS_PATH="",
        STANDALONE_CLERK_ISSUER_ALLOWLIST=issuer, CLERK_ISSUER=issuer,
        CLERK_JWKS_URL=issuer + "/.well-known/jwks.json", CLERK_SESSION_POLICY=policy,
        CLERK_AUDIENCE="invented-application-api" if policy == "audience" else "",
        CLERK_ORGANIZATION_ID="org_invented_practice", WORKSPACE_HOSTED_ENABLED=True,
        CORS_ALLOWED_ORIGINS="https://workspace.invented-practice.test",
        CLERK_AUTHORIZED_PARTIES="https://workspace.invented-practice.test")


@pytest.mark.parametrize("policy", ["audience", "shared_staging"])
def test_real_clerk_policy_stays_explicit_without_local_key_fallback(mounted, policy):
    public, private, values, _ = mounted
    real_profile(values, policy)
    public.write_text(json.dumps(values))
    environment = entrypoint.load_configuration(public, private)
    assert environment["CLERK_SESSION_POLICY"] == policy
    assert environment["STANDALONE_JWKS_PATH"] == ""
    assert environment["CLERK_AUDIENCE"] == values["CLERK_AUDIENCE"]


def test_exec_is_loopback_only_and_does_not_inherit_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 23017)
    monkeypatch.setattr(entrypoint.os, "environ", {"HTTP_PROXY": "invented-private", "COSMAS_ENV": "synth_os"})
    monkeypatch.setattr(entrypoint.os, "chdir", lambda _: None)
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "51887"])
    monkeypatch.setattr(entrypoint.sys, "path", list(entrypoint.sys.path))
    selected = {"COSMAS_ENV": "standalone_clerk_synthetic"}

    def loaded():
        assert entrypoint.os.environ == {}
        return selected

    calls = []
    monkeypatch.setattr(entrypoint, "load_configuration", loaded)
    monkeypatch.setattr(entrypoint.os, "execve", lambda *args: calls.append(args))
    entrypoint.main()
    assert calls[0][2] == selected
    assert calls[0][1][calls[0][1].index("--host") + 1] == "127.0.0.1"
    assert calls[0][1][calls[0][1].index("--port") + 1] == "51887"
    assert calls[0][1][calls[0][1].index("--workers") + 1] == "1"
    assert "--no-access-log" in calls[0][1]


@pytest.mark.parametrize("uid", [0, 10001])
def test_root_and_existing_staging_uid_refuse_before_configuration(monkeypatch, capsys, uid):
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: uid)
    monkeypatch.setattr(entrypoint, "load_configuration", lambda: pytest.fail("must not read mounted configuration"))
    assert entrypoint.main() == 78
    assert capsys.readouterr().err == "Standalone API configuration refused.\n"


@pytest.mark.parametrize("field,value", [("COSMAS_ENV", "early_adopter_beta"),
    ("WORKSPACE_CORE_CONNECTION_ENABLED", True), ("UNKNOWN_SETTING", "value"),
    ("DATABASE_URL", "invented"), ("WORKSPACE_LLM_API_KEY", "invented")])
def test_refuses_mixed_or_secret_public_configuration(mounted, field, value):
    public, private, values, _ = mounted
    values[field] = value
    public.write_text(json.dumps(values))
    with pytest.raises((entrypoint.Refused, RuntimeError)):
        entrypoint.load_configuration(public, private)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o666])
def test_private_input_permissions_are_not_optional(mounted, mode):
    public, private, _, _ = mounted
    private.chmod(mode)
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)


def test_refuses_extra_private_inputs_and_duplicate_json_fields(mounted):
    public, private, _, values = mounted
    private.write_text(json.dumps({**values, "CLERK_SECRET_KEY": "invented"}))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)
    private.write_text('{"DATABASE_URL":"invented","DATABASE_URL":"invented"}')
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)


def test_refuses_fifo_symlink_hardlink_and_oversize_before_parsing(mounted, tmp_path):
    public, private, _, _ = mounted
    for kind in ("fifo", "symlink", "hardlink", "oversize"):
        path = tmp_path / kind
        if kind == "fifo":
            os.mkfifo(path, 0o600)
        elif kind == "symlink":
            path.symlink_to(private)
        elif kind == "hardlink":
            path.hardlink_to(private)
        else:
            path.write_bytes(b" " * 32769)
            path.chmod(0o600)
        with pytest.raises((entrypoint.Refused, OSError)):
            entrypoint.load_configuration(public, path)
        path.unlink()


def feature_inputs(mounted, feature, policy="audience"):
    public, private, values, secrets = mounted
    real_profile(values, policy)
    changes = (model_values() if feature == "model" else google_values() if feature == "google"
               else model_values() | google_values())
    for name, value in changes.items():
        if hasattr(value, "get_secret_value"):
            secrets[name.upper()] = value.get_secret_value()
        else:
            values[name.upper()] = value
    if feature in {"google", "both"}:
        values["GOOGLE_CONNECTION_RETURN_ORIGIN"] = values["CORS_ALLOWED_ORIGINS"]
    public.write_text(json.dumps(values))
    private.write_text(json.dumps(secrets))
    return public, private, values, secrets


@pytest.mark.parametrize("policy", ["audience", "shared_staging"])
@pytest.mark.parametrize("feature", ["model", "google", "both"])
def test_only_selected_optional_credentials_enter_runtime(mounted, monkeypatch, policy, feature):
    public, private, values, secrets = feature_inputs(mounted, feature, policy)
    monkeypatch.setenv("CLERK_SECRET_KEY", "invented-unrelated")
    monkeypatch.setenv("MICROSOFT_CONNECTION_CLIENT_SECRET", "invented-unrelated")
    monkeypatch.setenv("WORKSPACE_LLM_API_KEY", "invented-ambient-model-key")
    environment = entrypoint.load_configuration(public, private)
    for name in entrypoint.OPTIONAL_PRIVATE_NAMES:
        assert (name in environment) == (name in secrets)
        if name in secrets:
            assert environment[name] == secrets[name]
    assert "CLERK_SECRET_KEY" not in environment
    assert "MICROSOFT_CONNECTION_CLIENT_SECRET" not in environment
    assert environment["COSMAS_ENV"] == "standalone_clerk_synthetic"
    assert environment["STANDALONE_INSTANCE_ID"] == values["STANDALONE_INSTANCE_ID"]


@pytest.mark.parametrize("missing", sorted(entrypoint.OPTIONAL_PRIVATE_NAMES))
def test_enabled_feature_requires_each_exact_private_input(mounted, missing):
    public, private, _, secrets = feature_inputs(mounted, "both")
    secrets.pop(missing)
    private.write_text(json.dumps(secrets))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)


@pytest.mark.parametrize("name", sorted(entrypoint.OPTIONAL_PRIVATE_NAMES))
def test_disabled_feature_and_public_file_cannot_carry_optional_secrets(mounted, name):
    public, private, values, secrets = mounted
    real_profile(values)
    public.write_text(json.dumps(values))
    private.write_text(json.dumps(secrets | {name: "invented"}))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)
    private.write_text(json.dumps(secrets))
    public.write_text(json.dumps(values | {name: "invented"}))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)


def test_boolean_string_feature_flags_cannot_bypass_required_secrets(mounted):
    public, private, values, secrets = feature_inputs(mounted, "google")
    values["WORKSPACE_GOOGLE_CONNECTION_ENABLED"] = "true"
    public.write_text(json.dumps(values))
    assert entrypoint.load_configuration(public, private)["WORKSPACE_GOOGLE_CONNECTION_ENABLED"] == "true"
    secrets.pop("GOOGLE_CONNECTION_ENCRYPTION_KEY")
    private.write_text(json.dumps(secrets))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)
