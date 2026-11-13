"""Mounted-file and clean-environment checks; invented configuration only."""

import importlib.util
import json
import os
from pathlib import Path

import pytest
from tests.unit import test_standalone_runtime as offline
from tests.unit.test_standalone_beta_features import google_values, microsoft_values, model_values

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


def test_audience_without_review_or_staging_refuses_account_delete_and_clerk_secret(
    mounted,
):
    """Audience on an invented origin keeps both Clerk secret names refused."""
    public, private, values, secrets = mounted
    real_profile(values, "audience")
    assert entrypoint.STAGING_WEB_ORIGIN not in values["CORS_ALLOWED_ORIGINS"]
    assert entrypoint.REVIEW_WEB_ORIGIN not in values["CORS_ALLOWED_ORIGINS"]
    public.write_text(json.dumps(values))
    for name in ("CLERK_SECRET_KEY", "ACCOUNT_DELETE_CLERK_SECRET_KEY"):
        private.write_text(json.dumps({**secrets, name: "invented-private-test-value"}))
        with pytest.raises(entrypoint.Refused):
            entrypoint.load_configuration(public, private)


def test_shared_staging_policy_alone_may_mount_account_delete_clerk_secret(mounted, monkeypatch):
    """shared_staging policy alone admits the delete secret; origin need not be staging."""
    public, private, values, secrets = mounted
    real_profile(values, entrypoint.STAGING_SESSION_POLICY)
    assert values["CLERK_SESSION_POLICY"] == entrypoint.STAGING_SESSION_POLICY
    assert entrypoint.STAGING_WEB_ORIGIN not in values["CORS_ALLOWED_ORIGINS"]
    assert "clerk.staging.cosmas.ai" not in values["CLERK_ISSUER"]
    public.write_text(json.dumps(values))
    private.write_text(json.dumps({**secrets, "CLERK_SECRET_KEY": "invented"}))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)

    monkeypatch.setenv("CLERK_SECRET_KEY", "invented-ambient")
    monkeypatch.setenv("ACCOUNT_DELETE_CLERK_SECRET_KEY", "invented-ambient-delete")
    private.write_text(json.dumps({
        **secrets,
        "ACCOUNT_DELETE_CLERK_SECRET_KEY": "sk_test_invented_account_delete_only",
    }))
    environment = entrypoint.load_configuration(public, private)
    assert environment["ACCOUNT_DELETE_CLERK_SECRET_KEY"] == "sk_test_invented_account_delete_only"
    assert "CLERK_SECRET_KEY" not in environment


def test_staging_web_origin_alone_may_mount_account_delete_clerk_secret(mounted):
    """STAGING_WEB_ORIGIN alone admits the delete secret under audience policy."""
    public, private, values, secrets = mounted
    real_profile(values, "audience")
    # Non-staging issuer pins the origin branch alone (issuer must not be required).
    values.update(
        CLERK_ISSUER="https://clerk.cosmas.ai",
        CLERK_JWKS_URL="https://clerk.cosmas.ai/.well-known/jwks.json",
        STANDALONE_CLERK_ISSUER_ALLOWLIST="https://clerk.cosmas.ai",
        CLERK_AUDIENCE="cosmas-os-beta-api",
        CORS_ALLOWED_ORIGINS=entrypoint.STAGING_WEB_ORIGIN,
        CLERK_AUTHORIZED_PARTIES=entrypoint.STAGING_WEB_ORIGIN,
    )
    assert values["CLERK_SESSION_POLICY"] == "audience"
    assert values["CORS_ALLOWED_ORIGINS"] == entrypoint.STAGING_WEB_ORIGIN
    public.write_text(json.dumps(values))
    private.write_text(json.dumps({
        **secrets,
        "ACCOUNT_DELETE_CLERK_SECRET_KEY": "sk_live_invented_staging_delete",
    }))
    environment = entrypoint.load_configuration(public, private)
    assert environment["ACCOUNT_DELETE_CLERK_SECRET_KEY"] == "sk_live_invented_staging_delete"
    assert "CLERK_SECRET_KEY" not in environment


def _review_public(values):
    real_profile(values, "audience")
    values.update(
        CLERK_ISSUER=entrypoint.REVIEW_CLERK_ISSUER,
        CLERK_JWKS_URL=entrypoint.REVIEW_CLERK_ISSUER.rstrip("/") + "/.well-known/jwks.json",
        STANDALONE_CLERK_ISSUER_ALLOWLIST=entrypoint.REVIEW_CLERK_ISSUER,
        CLERK_AUDIENCE="cosmas-os-beta-api",
        CORS_ALLOWED_ORIGINS=entrypoint.REVIEW_WEB_ORIGIN,
        CLERK_AUTHORIZED_PARTIES=entrypoint.REVIEW_WEB_ORIGIN,
    )


def test_review_requires_clerk_beta_issuer_to_mount_account_delete(mounted):
    """Exclusive review: audience + beta CORS + clerk.beta issuer admits the env name."""
    public, private, values, secrets = mounted
    _review_public(values)
    public.write_text(json.dumps(values))
    private.write_text(json.dumps({**secrets, "CLERK_SECRET_KEY": "invented"}))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)
    private.write_text(json.dumps({
        **secrets,
        entrypoint.ACCOUNT_DELETE_ENV_NAME: "sk_live_invented_review_delete",
    }))
    environment = entrypoint.load_configuration(public, private)
    assert environment[entrypoint.ACCOUNT_DELETE_ENV_NAME] == "sk_live_invented_review_delete"
    assert "CLERK_SECRET_KEY" not in environment
    assert entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY not in environment


@pytest.mark.parametrize(
    "issuer",
    ["https://clerk.staging.cosmas.ai", "https://clerk.cosmas.ai"],
    ids=["clerk_staging_issuer", "clerk_prod_issuer"],
)
def test_review_refuses_account_delete_when_issuer_is_not_clerk_beta(mounted, issuer):
    """Issuer alone never admits; wrong issuer on beta refuses the delete name."""
    public, private, values, secrets = mounted
    real_profile(values, "audience")
    values.update(
        CLERK_ISSUER=issuer,
        CLERK_JWKS_URL=issuer.rstrip("/") + "/.well-known/jwks.json",
        STANDALONE_CLERK_ISSUER_ALLOWLIST=issuer,
        CLERK_AUDIENCE="cosmas-os-beta-api",
        CORS_ALLOWED_ORIGINS=entrypoint.REVIEW_WEB_ORIGIN,
        CLERK_AUTHORIZED_PARTIES=entrypoint.REVIEW_WEB_ORIGIN,
    )
    public.write_text(json.dumps(values))
    private.write_text(json.dumps({
        **secrets,
        entrypoint.ACCOUNT_DELETE_ENV_NAME: "sk_live_must_refuse_wrong_issuer",
    }))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)


def test_review_remaps_host_key_into_account_delete_env(mounted):
    """Production-review maps host key CLERK_ACCOUNT_DELETION_SECRET → env name."""
    public, private, values, secrets = mounted
    _review_public(values)
    public.write_text(json.dumps(values))
    private.write_text(json.dumps({
        **secrets,
        entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY: "sk_live_invented_from_host_key",
    }))
    environment = entrypoint.load_configuration(public, private)
    assert environment[entrypoint.ACCOUNT_DELETE_ENV_NAME] == "sk_live_invented_from_host_key"
    assert entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY not in environment
    private.write_text(json.dumps({
        **secrets,
        entrypoint.ACCOUNT_DELETE_ENV_NAME: "sk_live_invented_env",
        entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY: "sk_live_invented_alias",
    }))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)


def test_review_loads_without_account_delete_key(mounted):
    """Review profile with the key absent still loads; delete stays fail-closed at the API."""
    public, private, values, secrets = mounted
    _review_public(values)
    public.write_text(json.dumps(values))
    private.write_text(json.dumps(secrets))
    environment = entrypoint.load_configuration(public, private)
    assert entrypoint.ACCOUNT_DELETE_ENV_NAME not in environment
    assert entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY not in environment


def test_review_empty_or_whitespace_host_key_alias_treated_as_absent(mounted):
    """Empty/whitespace host-key alias is absent, not a boot refusal."""
    public, private, values, secrets = mounted
    _review_public(values)
    public.write_text(json.dumps(values))
    for bad in ("", "   ", "\t"):
        private.write_text(json.dumps({
            **secrets,
            entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY: bad,
        }))
        environment = entrypoint.load_configuration(public, private)
        assert entrypoint.ACCOUNT_DELETE_ENV_NAME not in environment
        assert entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY not in environment


def test_padded_account_delete_secret_is_stripped_not_refused(mounted):
    """Padded ACCOUNT_DELETE_CLERK_SECRET_KEY is stripped; whitespace-only is absent."""
    public, private, values, secrets = mounted
    real_profile(values, entrypoint.STAGING_SESSION_POLICY)
    public.write_text(json.dumps(values))
    private.write_text(json.dumps({
        **secrets,
        entrypoint.ACCOUNT_DELETE_ENV_NAME: " sk_test_pad ",
    }))
    environment = entrypoint.load_configuration(public, private)
    assert environment[entrypoint.ACCOUNT_DELETE_ENV_NAME] == "sk_test_pad"
    for blank in ("   ", "\t\n"):
        private.write_text(json.dumps({
            **secrets,
            entrypoint.ACCOUNT_DELETE_ENV_NAME: blank,
        }))
        environment = entrypoint.load_configuration(public, private)
        assert entrypoint.ACCOUNT_DELETE_ENV_NAME not in environment


def test_staging_padded_non_delete_private_value_still_boots(mounted):
    """Staging wall: trailing whitespace on DATABASE_URL must not refuse boot."""
    public, private, values, secrets = mounted
    real_profile(values, entrypoint.STAGING_SESSION_POLICY)
    public.write_text(json.dumps(values))
    padded = {**secrets, "DATABASE_URL": secrets["DATABASE_URL"] + "\n"}
    private.write_text(json.dumps(padded))
    environment = entrypoint.load_configuration(public, private)
    assert environment["DATABASE_URL"].endswith("\n")
    assert environment["CLERK_SESSION_POLICY"] == entrypoint.STAGING_SESSION_POLICY


def test_main_isolated_import_failure_exits_78(tmp_path, monkeypatch, capsys):
    """python -I image-like layout: missing shared predicate → fixed refusal 78."""
    app = tmp_path / "app"
    src = app / "src"
    src.mkdir(parents=True)
    (src / "cosmas_os").mkdir()
    (src / "cosmas_os" / "__init__.py").write_text("")
    # No production_review_profile.py → ImportError inside main()'s try.
    monkeypatch.setattr(entrypoint, "APP_ROOT", app)
    monkeypatch.setattr(entrypoint, "APP_SRC", src)
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 23017)
    monkeypatch.setattr(entrypoint.sys, "argv", ["entrypoint.py", "51887"])
    monkeypatch.setattr(entrypoint, "_SHARED_BOUND", False)
    monkeypatch.setattr(entrypoint, "classify_review_profile", None)
    # Force re-bind from the empty image src, not the installed package.
    monkeypatch.setattr(entrypoint.sys, "path", [str(src)])
    # main() clears os.environ; restore so later tests still have PATH.
    saved_environ = dict(os.environ)
    try:
        assert entrypoint.main() == 78
    finally:
        os.environ.clear()
        os.environ.update(saved_environ)
    assert capsys.readouterr().err == "Standalone API configuration refused.\n"


def test_python_dash_I_image_layout_missing_predicate_exits_78(tmp_path):
    """Subprocess python -I with image-like /app/src layout expects exit 78."""
    import subprocess
    import sys
    from pathlib import Path

    app = tmp_path / "app"
    (app / "src" / "cosmas_os").mkdir(parents=True)
    (app / "src" / "cosmas_os" / "__init__.py").write_text("")
    # No production_review_profile.py under src.
    source = Path(entrypoint.__file__).read_text(encoding="utf-8")
    source = source.replace('APP_ROOT = Path("/app")', f"APP_ROOT = Path({str(app)!r})")
    # Cloud agent UIDs are often <= 10001; pin runtime UID so refusal is the import.
    source = source.replace(
        "if os.geteuid() <= 10001 or len(sys.argv) != 2",
        "if False or len(sys.argv) != 2",
    )
    script = app / "standalone-entrypoint.py"
    script.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", str(script), "51887"],
        cwd=str(app),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 78, result.stdout + result.stderr
    assert result.stderr.strip() == "Standalone API configuration refused."


def test_staging_refuses_clerk_account_deletion_secret_alias(mounted):
    """Staging keeps #375 behavior: only ACCOUNT_DELETE_CLERK_SECRET_KEY, not the host key."""
    public, private, values, secrets = mounted
    real_profile(values, entrypoint.STAGING_SESSION_POLICY)
    public.write_text(json.dumps(values))
    private.write_text(json.dumps({
        **secrets,
        entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY: "sk_test_must_refuse_on_staging",
    }))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)
    private.write_text(json.dumps({
        **secrets,
        entrypoint.ACCOUNT_DELETE_ENV_NAME: "sk_test_invented_staging_unchanged",
    }))
    environment = entrypoint.load_configuration(public, private)
    assert environment[entrypoint.ACCOUNT_DELETE_ENV_NAME] == "sk_test_invented_staging_unchanged"


@pytest.mark.parametrize("profile", ["review", "staging"], ids=["review", "staging"])
def test_host_key_in_public_json_is_refused_on_review_and_staging(mounted, profile):
    """CLERK_ACCOUNT_DELETION_SECRET must never appear in the public mount."""
    public, private, values, secrets = mounted
    if profile == "review":
        _review_public(values)
    else:
        real_profile(values, entrypoint.STAGING_SESSION_POLICY)
    values[entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY] = "sk_test_must_not_be_public"
    public.write_text(json.dumps(values))
    private.write_text(json.dumps(secrets))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)


def test_audience_non_review_origin_still_refuses_account_delete(mounted):
    """Audience + non-staging/non-review origin keeps refusing the delete key."""
    public, private, values, secrets = mounted
    real_profile(values, "audience")
    values.update(
        CLERK_ISSUER="https://clerk.cosmas.ai",
        CLERK_JWKS_URL="https://clerk.cosmas.ai/.well-known/jwks.json",
        STANDALONE_CLERK_ISSUER_ALLOWLIST="https://clerk.cosmas.ai",
        CLERK_AUDIENCE="cosmas-os-beta-api",
        CORS_ALLOWED_ORIGINS="https://cosmas.ai",
        CLERK_AUTHORIZED_PARTIES="https://cosmas.ai",
    )
    public.write_text(json.dumps(values))
    private.write_text(json.dumps({
        **secrets,
        "ACCOUNT_DELETE_CLERK_SECRET_KEY": "sk_test_must_refuse_outside_review",
    }))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)
    private.write_text(json.dumps({
        **secrets,
        entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY: "sk_test_must_refuse_outside_review_alias",
    }))
    with pytest.raises(entrypoint.Refused):
        entrypoint.load_configuration(public, private)


def test_account_delete_clerk_secret_in_public_file_is_refused(mounted):
    """ACCOUNT_DELETE_CLERK_SECRET_KEY must never appear in the public mount."""
    public, private, values, secrets = mounted
    real_profile(values, entrypoint.STAGING_SESSION_POLICY)
    values["ACCOUNT_DELETE_CLERK_SECRET_KEY"] = "sk_test_must_not_be_public"
    public.write_text(json.dumps(values))
    private.write_text(json.dumps(secrets))
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
    changes = {"model": model_values(), "google": google_values(), "microsoft": microsoft_values(),
        "both": model_values() | google_values(), "all": model_values() | google_values() | microsoft_values()}[feature]
    for name, value in changes.items():
        if hasattr(value, "get_secret_value"):
            secrets[name.upper()] = value.get_secret_value()
        else:
            values[name.upper()] = value
    if feature in {"google", "both", "all"}:
        values["GOOGLE_CONNECTION_RETURN_ORIGIN"] = values["CORS_ALLOWED_ORIGINS"]
    if feature in {"microsoft", "all"}:
        values["MICROSOFT_CONNECTION_RETURN_ORIGIN"] = values["CORS_ALLOWED_ORIGINS"]
    public.write_text(json.dumps(values))
    private.write_text(json.dumps(secrets))
    return public, private, values, secrets


@pytest.mark.parametrize("policy", ["audience", "shared_staging"])
@pytest.mark.parametrize("feature", ["model", "google", "both", "microsoft", "all"])
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
    assert ("MICROSOFT_CONNECTION_CLIENT_SECRET" in environment) == (feature in {"microsoft", "all"})
    assert environment["COSMAS_ENV"] == "standalone_clerk_synthetic"
    assert environment["STANDALONE_INSTANCE_ID"] == values["STANDALONE_INSTANCE_ID"]


@pytest.mark.parametrize("missing", sorted(entrypoint.OPTIONAL_PRIVATE_NAMES))
def test_enabled_feature_requires_each_exact_private_input(mounted, missing):
    public, private, _, secrets = feature_inputs(mounted, "all")
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
