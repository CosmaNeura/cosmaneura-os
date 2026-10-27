from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "infra/beta/validate_web_build.py"
SPEC = importlib.util.spec_from_file_location("cosmas_web_build_validator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
web_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web_build)


def configuration() -> dict[str, str]:
    return {
        "VITE_CLERK_PUBLISHABLE_KEY": "pk_live_aWRlbnRpdHkuZXhhbXBsZS5pbnZhbGlkJA==",
        "VITE_WORKSPACE_HOSTED_API_ORIGIN": "https://api.example.invalid",
        "VITE_WORKSPACE_WEB_ORIGIN": "https://workspace.example.invalid",
        "VITE_WORKSPACE_DATA_MODE": "synthetic",
        "VITE_COSMANEURA_WEB_ORIGIN": "https://core.example.invalid",
        "VITE_CAPTURE_UPLOAD_ORIGINS": "https://uploads.example.invalid",
        "VITE_WORKSPACE_CAPTURE_MODE": "browser_microphone",
    }


def write_config(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "public web build.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_generated_key_contract_matches_current_docker_arguments(tmp_path: Path) -> None:
    config = configuration()
    assert web_build.load_config(write_config(tmp_path, config)) == config
    docker_args = dict(re.findall(r"^ARG (VITE_[A-Z_]+)(?:=([^\n]*))?$",
                                 (REPO / "Dockerfile.web").read_text(), re.M))
    # The locked runner retains seven inputs. Other clients may explicitly opt
    # into Messages or a standalone profile with its reviewed organization.
    assert set(docker_args) == set(config) | {
        "VITE_MESSAGES_ENABLED", "VITE_WORKSPACE_FEATURE_PROFILE", "VITE_WORKSPACE_ORGANIZATION_ID",
    }
    assert docker_args["VITE_MESSAGES_ENABLED"] == "false"
    assert docker_args["VITE_WORKSPACE_FEATURE_PROFILE"] == "operational-beta-v1"
    assert docker_args["VITE_WORKSPACE_ORGANIZATION_ID"] == ""
    assert web_build.docker_argument_lines(config) == [f"{key}={value}" for key, value in config.items()]


@pytest.mark.parametrize("missing", list(configuration()))
def test_missing_input_is_rejected(tmp_path: Path, missing: str) -> None:
    config = configuration()
    del config[missing]
    with pytest.raises(web_build.WebBuildError, match="seven"):
        web_build.load_config(write_config(tmp_path, config))


@pytest.mark.parametrize("extra", ["VITE_WORKSPACE_FEATURE_PROFILE", "VITE_WORKSPACE_ORGANIZATION_ID", "VITE_WORKSPACE_HOSTED_CLIENT",
                                  "VITE_API_BASE", "CLERK_SECRET_KEY", "NODE_BUILD_IMAGE",
                                  "VITE_MESSAGES_ENABLED"])
def test_extra_fields_cannot_override_fixed_build_or_carry_secrets(tmp_path: Path, extra: str) -> None:
    with pytest.raises(web_build.WebBuildError, match="seven"):
        web_build.load_config(write_config(tmp_path, configuration() | {extra: "unexpected"}))


@pytest.mark.parametrize("raw", [b"[]", b"null", b"{", b"\xff", b" " * 8193])
def test_invalid_or_overlarge_json_is_rejected(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises(web_build.WebBuildError):
        web_build.load_config(path)


def test_duplicate_decoded_field_is_rejected(tmp_path: Path) -> None:
    raw = json.dumps(configuration())
    path = tmp_path / "duplicate.json"
    path.write_text(raw[:-1] + ', "\\u0056ITE_WORKSPACE_DATA_MODE": "synthetic"}')
    with pytest.raises(web_build.WebBuildError, match="duplicate"):
        web_build.load_config(path)


def test_nonregular_and_symbolic_inputs_are_rejected(tmp_path: Path) -> None:
    config_path = write_config(tmp_path, configuration())
    linked = tmp_path / "linked.json"
    linked.symlink_to(config_path)
    pipe = tmp_path / "pipe.json"
    os.mkfifo(pipe)
    for path in (linked, pipe, tmp_path):
        with pytest.raises(web_build.WebBuildError):
            web_build.load_config(path)


@pytest.mark.parametrize("key,value", [
    ("VITE_CLERK_PUBLISHABLE_KEY", "pk_test_invented"),
    ("VITE_CLERK_PUBLISHABLE_KEY", "sk_live_must_not_be_disclosed"),
    ("VITE_CLERK_PUBLISHABLE_KEY", "pk_live_bad\nvalue"),
    ("VITE_CLERK_PUBLISHABLE_KEY", "pk_live_" + "x" * 513),
    ("VITE_WORKSPACE_DATA_MODE", "authorized_beta"),
    ("VITE_WORKSPACE_CAPTURE_MODE", "ios_native"),
    ("VITE_WORKSPACE_CAPTURE_MODE", False),
    ("VITE_CAPTURE_UPLOAD_ORIGINS", ""),
    ("VITE_CAPTURE_UPLOAD_ORIGINS", "https://upload.example.invalid,https://upload.example.invalid"),
    ("VITE_CAPTURE_UPLOAD_ORIGINS", ",".join(f"https://upload{i}.example.invalid" for i in range(5))),
    ("VITE_CAPTURE_UPLOAD_ORIGINS", "https://upload.example.invalid, https://other.example.invalid"),
])
def test_profile_and_public_value_limits_are_enforced(tmp_path: Path, key: str, value: object) -> None:
    with pytest.raises(web_build.WebBuildError):
        web_build.load_config(write_config(tmp_path, configuration() | {key: value}))


@pytest.mark.parametrize("origin", [
    "http://api.example.invalid", "https://user:password@api.example.invalid",
    "https://api.example.invalid:443", "https://api.example.invalid/",
    "https://api.example.invalid/path", "https://api.example.invalid?token=hidden",
    "https://api.example.invalid#fragment", "https://API.example.invalid",
    "https://localhost", "https://api.localhost", "https://127.0.0.1", "https://127.1",
    "https://0x7f.0x1", "https://[::1]", "https://*.example.invalid", "https://api.example.invalid\n",
])
@pytest.mark.parametrize("key", ["VITE_WORKSPACE_HOSTED_API_ORIGIN", "VITE_WORKSPACE_WEB_ORIGIN",
                                  "VITE_COSMANEURA_WEB_ORIGIN", "VITE_CAPTURE_UPLOAD_ORIGINS"])
def test_origins_are_exact_and_credential_free(tmp_path: Path, key: str, origin: str) -> None:
    with pytest.raises(web_build.WebBuildError):
        web_build.load_config(write_config(tmp_path, configuration() | {key: origin}))


def test_hash_covers_complete_canonical_input_and_ordered_uploads() -> None:
    config = configuration()
    expected = hashlib.sha256((json.dumps(config, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
    assert web_build.config_sha256(config) == expected
    assert web_build.config_sha256(dict(reversed(list(config.items())))) == expected
    replacements = {
        "VITE_CLERK_PUBLISHABLE_KEY": "pk_live_changed",
        "VITE_WORKSPACE_HOSTED_API_ORIGIN": "https://other-api.example.invalid",
        "VITE_WORKSPACE_WEB_ORIGIN": "https://other-web.example.invalid",
        "VITE_COSMANEURA_WEB_ORIGIN": "https://other-core.example.invalid",
        "VITE_CAPTURE_UPLOAD_ORIGINS": "https://other-upload.example.invalid",
        "VITE_WORKSPACE_CAPTURE_MODE": "synthetic",
    }
    for key, value in replacements.items():
        changed = web_build.validate_config(config | {key: value})
        assert web_build.config_sha256(changed) != expected
    first = config | {"VITE_CAPTURE_UPLOAD_ORIGINS": "https://one.example.invalid,https://two.example.invalid"}
    reversed_origins = first | {"VITE_CAPTURE_UPLOAD_ORIGINS": "https://two.example.invalid,https://one.example.invalid"}
    assert web_build.config_sha256(first) != web_build.config_sha256(reversed_origins)


def test_both_foundation_origins_are_required_and_bound() -> None:
    config = configuration()
    bindings = {"api_origin": config["VITE_WORKSPACE_HOSTED_API_ORIGIN"],
                "web_origin": config["VITE_WORKSPACE_WEB_ORIGIN"]}
    assert web_build.validate_config(config, **bindings) == config
    for key in bindings:
        with pytest.raises(web_build.WebBuildError, match="foundation"):
            web_build.validate_config(config, **(bindings | {key: "https://different.example.invalid"}))
        with pytest.raises(web_build.WebBuildError, match="both foundation"):
            web_build.validate_config(config, **{key: bindings[key]})


def run_mocked_build(tmp_path: Path, config: dict[str, str]) -> tuple[subprocess.CompletedProcess, Path]:
    source = (REPO / "infra/beta/protected-runner-command.sh").read_text()
    start = source.index('    web_build_argument_lines="$(')
    preparation = source[start:source.index('    acr_host=', start)]
    hash_start = source.index('    public_config_hash="$(python3 "$web_build_validator"')
    preparation += source[hash_start:source.index("\n", hash_start)] + "\n"
    branch = source.index('    if [[ -z "$web_existing_digest" ]]; then')
    command_start = source.index('      if ! docker buildx build --load', branch)
    command_end = source.index('; then', command_start)
    command = source[command_start:command_end].removeprefix('      if ! ')
    captured = tmp_path / "docker-argv"
    shell = '''set -euo pipefail
python3() { "$TEST_PYTHON" "$@"; }
die() { printf '%s\\n' "$*" >&2; exit 1; }
docker() { printf '%s\\0' "$@" > "$CAPTURED"; }
''' + preparation + command
    env = {"PATH": os.defpath, "TEST_PYTHON": sys.executable, "CAPTURED": str(captured),
           "web_build_validator": str(SCRIPT), "payload_file": str(write_config(tmp_path, config)),
           "api_origin": configuration()["VITE_WORKSPACE_HOSTED_API_ORIGIN"],
           "web_origin": configuration()["VITE_WORKSPACE_WEB_ORIGIN"],
           "repository_root": str(REPO), "source_sha": "a" * 40,
           "web_image": "invented.azurecr.io/cosmas-os-web:git-" + "a" * 40,
           "build_log": str(tmp_path / "build.log"), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([shutil.which("bash") or "/bin/bash", "-c", shell],
                            env=env, capture_output=True, text=True, timeout=15)
    return result, captured


def test_protected_docker_command_forwards_all_validated_arguments_and_hash(tmp_path: Path) -> None:
    config = configuration()
    result, captured = run_mocked_build(tmp_path, config)
    assert result.returncode == 0, result.stderr
    argv = captured.read_bytes().decode().split("\0")[:-1]
    assert argv[:3] == ["buildx", "build", "--load"]
    forwarded = [argv[index + 1] for index, value in enumerate(argv) if value == "--build-arg"]
    assert forwarded == [f"{key}={value}" for key, value in config.items()]
    assert "com.cosmaneura.cosmas-os.public-config-sha256=" + web_build.config_sha256(config) in argv
    assert argv[-1] == str(REPO)


@pytest.mark.parametrize("key,value", [
    ("VITE_WORKSPACE_HOSTED_API_ORIGIN", "https://other.example.invalid"),
    ("VITE_WORKSPACE_WEB_ORIGIN", "https://other.example.invalid"),
    ("VITE_WORKSPACE_DATA_MODE", "authorized_beta"),
    ("VITE_WORKSPACE_FEATURE_PROFILE", "unexpected"),
])
def test_rejected_build_never_invokes_mock_docker(tmp_path: Path, key: str, value: str) -> None:
    result, captured = run_mocked_build(tmp_path, configuration() | {key: value})
    assert result.returncode != 0
    assert not captured.exists()
