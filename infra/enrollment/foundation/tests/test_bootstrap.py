from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import prepare  # noqa: E402
import prepare_database_credentials  # noqa: E402
import seed_secret  # noqa: E402


def public_inputs(tmp_path):
    path = tmp_path / "public.json"
    path.write_text(json.dumps({"subscription_id": "00000000-0000-4000-8000-000000000001", "tenant_id": "00000000-0000-4000-8000-000000000002",
        "resource_name_suffix": "mock1234", "vnet_address_prefix": "10.248.0.0/20", "release_operator_object_id": "00000000-0000-4000-8000-000000000003", "state_operator_ipv4": "198.51.100.10"}))
    path.chmod(0o600)
    return path


def test_private_bootstrap_has_no_cloud_calls_and_detects_input_tamper(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("prepare may not invoke a cloud process"))
    directory = tmp_path / "owned"
    result = prepare.prepare(public_inputs(tmp_path), directory)
    assert result["prepared"] and not result["applied"]
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in directory.iterdir() if p.is_file())
    receipt = json.loads((directory / "bootstrap.json").read_text())
    assert "password" not in json.dumps(receipt)
    assert (directory / "postgres-admin.password").read_text() not in json.dumps(receipt)
    for key in list(os.environ):
        if key.startswith(("TF_", "ARM_")):
            monkeypatch.delenv(key)
    child = prepare.child_environment(directory)
    assert child["TF_VAR_postgres_admin_password"] == (directory / "postgres-admin.password").read_text()
    assert child["TF_DATA_DIR"].startswith(str(directory))
    values = json.loads((directory / "inputs.tfvars.json").read_text())
    values["subscription_id"] = "00000000-0000-4000-8000-000000000004"
    (directory / "inputs.tfvars.json").write_text(json.dumps(values))
    with pytest.raises(ValueError):
        prepare.child_environment(directory)


def test_credential_inputs_reject_symlink_mode_and_secret_keys(tmp_path):
    inputs = public_inputs(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(inputs)
    with pytest.raises(OSError):
        prepare.private_read(link)
    inputs.chmod(0o644)
    with pytest.raises(ValueError):
        prepare.private_read(inputs)
    inputs.chmod(0o600)
    values = json.loads(inputs.read_text())
    values["postgres_admin_password"] = "invented-value"
    inputs.write_text(json.dumps(values))
    with pytest.raises(ValueError):
        prepare.prepare(inputs, tmp_path / "owned")


def test_arm_secure_parameter_does_not_enter_arguments_output_or_receipt(tmp_path, monkeypatch):
    f = seed_secret.foundation(ROOT.parent / "database-job/tests/foundation.json")
    value = tmp_path / "secret"
    value.write_text("invented-secret-for-transport-proof")
    value.chmod(0o600)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert value.read_text() not in json.dumps(command)
        assert kwargs["capture_output"]
        if command[:3] == ["az", "account", "show"]:
            return SimpleNamespace(stdout=json.dumps({"id": f["subscription_id"], "tenantId": f["tenant_id"], "state": "Enabled"}).encode())
        if command[:4] == ["az", "deployment", "group", "create"]:
            parameter_file = Path(command[command.index("--parameters") + 1][1:])
            assert stat.S_IMODE(parameter_file.stat().st_mode) == 0o600
            assert json.loads(parameter_file.read_text())["secretValue"]["value"] == value.read_text()
            template = json.loads(Path(command[command.index("--template-file") + 1]).read_text())
            assert template["parameters"]["secretValue"]["type"] == "secureString"
            assert "outputs" not in template
            return SimpleNamespace(stdout=b"")
        return SimpleNamespace(stdout=(f["key_vault_uri"] + "secrets/enrollment-invitation-secret/" + "a" * 32).encode())

    monkeypatch.setattr(subprocess, "run", run)
    result = seed_secret.seed(f, "enrollment-invitation-secret", value, tmp_path / "reference.json")
    assert len(calls) == 3 and result["value_returned"] is False
    assert value.read_text() not in (tmp_path / "reference.json").read_text()


def test_arm_error_is_not_forwarded_even_if_provider_echoes_value(tmp_path, monkeypatch, capsys):
    value = tmp_path / "secret"
    value.write_text("invented-sensitive-value")
    value.chmod(0o600)
    monkeypatch.setattr(sys, "argv", ["seed", "--foundation", str(ROOT.parent / "database-job/tests/foundation.json"), "--secret-name", "enrollment-invitation-secret", "--value-file", str(value), "--receipt", str(tmp_path / "ref")])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.CalledProcessError(1, ["az"], stderr=value.read_bytes())))
    assert seed_secret.main() == 1
    output = capsys.readouterr()
    assert "enrollment_secret_seed_failed" in output.err
    assert value.read_text() not in output.out + output.err


def test_separate_generated_urls_are_private_and_remain_unseeded(tmp_path):
    f = seed_secret.foundation(ROOT.parent / "database-job/tests/foundation.json")
    password = tmp_path / "admin"
    password.write_text("synthetic-bootstrap-password-never-live-1234")
    password.chmod(0o600)
    result = prepare_database_credentials.prepare(f, password, tmp_path / "urls")
    assert not result["seeded"] and not result["qualified"]
    urls = [(tmp_path / "urls" / f"{role}.url").read_text() for role in ("bootstrap", "migrator", "runtime")]
    assert len(set(urls)) == 3
    assert all("sslmode=verify-full" in url for url in urls)
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in (tmp_path / "urls").iterdir())


def test_database_entrypoint_rejects_unowned_host_without_echo(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("enrollment_database_admin_test", ROOT.parent / "database-job/database.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("ENROLLMENT_DATABASE_HOST", "another-product.example.invalid")
    monkeypatch.setenv("ENROLLMENT_RUNTIME_DATABASE_URL", "postgresql://user:invented-token@another-product.example.invalid/db")
    monkeypatch.setattr(sys, "argv", ["database", "check"])
    assert module.main() == 1
    output = capsys.readouterr()
    assert "enrollment_database_preparation_failed" in output.err
    assert "invented-token" not in output.out + output.err
