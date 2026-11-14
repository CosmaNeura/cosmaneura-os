"""T-PROD-3-SECRETS: prod Key Vault name → mode-0400 host file transport.

Synthetic fixtures only. Never calls Azure. Proves secret VALUES never appear
in stdout, stderr, generated host scripts, or Refused exception messages.
Collected by synth-ci backend suites via tests/.
"""
from __future__ import annotations

import importlib.util
import io
import stat
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "infra/beta/vm/host/secrets_transport.py"
SPEC = importlib.util.spec_from_file_location("cosmabot_secrets_transport", MODULE_PATH)
transport = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = transport
SPEC.loader.exec_module(transport)

CANARY = "CANARY_SECRET_VALUE_9f3a2c7b1e8d4a06_NEVER_PRINT"
PROD_ACCOUNT = (
    "/subscriptions/00000000-0000-4000-8000-000000000001"
    "/resourceGroups/rg-cosmabot-prod-eus2-01"
    "/providers/Microsoft.CognitiveServices/accounts/oai-cbot-prd-abc123"
)
COSMASCODE_ACCOUNT = (
    "/subscriptions/00000000-0000-4000-8000-000000000001"
    "/resourceGroups/rg-shared/providers/Microsoft.CognitiveServices"
    "/accounts/cosmascode"
)


def _coords(**overrides):
    base = {
        "profile": transport.PROFILE,
        "resource_group": transport.RESOURCE_GROUP,
        "vault_name": "kv-cbot-prd-lab01",
        "vm_name": transport.VM_NAME,
    }
    base.update(overrides)
    return base


def _capture(fn, *args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            result = fn(*args, **kwargs)
            return result, out.getvalue(), err.getvalue(), None
        except Exception as exc:  # noqa: BLE001 — assert canary absent even on errors
            return None, out.getvalue(), err.getvalue(), exc


def _assert_canary_absent(*chunks: str, also: object = None) -> None:
    blob = "\n".join(chunks)
    assert CANARY not in blob
    if also is not None:
        assert CANARY not in str(also)
        assert CANARY not in repr(also)


def test_plan_prints_names_only_never_values(tmp_path):
    mappings = transport.resolve_mappings(
        ["CLERK-SECRET-KEY", "WORKSPACE-LLM-API-KEY"]
    )
    lines = transport.plan_lines(mappings)
    text = "\n".join(lines)
    assert "CLERK-SECRET-KEY" in text
    assert "WORKSPACE_LLM_API_KEY" in text
    assert "run_command=forbidden" in text
    assert "service_uid_mode_0400" in text
    assert CANARY not in text


def test_install_from_staging_atomic_0400_and_canary_never_printed(tmp_path):
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-1"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode() + b"\n")
    mappings = transport.resolve_mappings(["CLERK-SECRET-KEY"])

    results, stdout, stderr, exc = _capture(
        transport.install_from_staging,
        mappings,
        protected_root=root,
        staging_dir=staging,
        release_id="rel-1",
        chown_enabled=False,
    )
    assert exc is None
    assert results is not None
    _assert_canary_absent(stdout, stderr, also=results)

    for role in ("api", "worker"):
        path = root / role / "CLERK_SECRET_KEY"
        assert path.is_file()
        assert path.read_bytes() == CANARY.encode()
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
        assert path.stat().st_size > 0
        line = transport.format_result_line(
            {**results[0], "role": role, "host_name": "CLERK_SECRET_KEY"}
        )
        _assert_canary_absent(line)


def test_empty_staging_secret_stops(tmp_path):
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-1"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / "REDIS_PASSWORD").write_bytes(b"")
    mappings = transport.resolve_mappings(["REDIS-PASSWORD"])
    with pytest.raises(transport.Refused, match="staging_file_empty|secret_value_empty"):
        transport.install_from_staging(
            mappings,
            protected_root=root,
            staging_dir=staging,
            release_id="rel-1",
            chown_enabled=False,
        )


def test_names_only_host_script_never_embeds_canary(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "DATABASE_PASSWORD").write_bytes(CANARY.encode())
    mappings = transport.resolve_mappings(["DATABASE-PASSWORD"])
    script = transport.render_names_only_host_script(
        mappings,
        release_id="rel-1",
        staging_dir=str(staging),
    )
    assert "DATABASE_PASSWORD" in script
    assert "chmod 0400" in script
    assert "umask 077" in script
    _assert_canary_absent(script)
    # Mutation killer: if someone concatenated staging file bytes into the script.
    assert CANARY.encode() not in script.encode()


def test_run_command_transport_refused_and_canary_absent_from_error():
    _, stdout, stderr, exc = _capture(transport.refuse_run_command_transport)
    assert isinstance(exc, transport.Refused)
    assert "run_command_secret_transport_forbidden" in str(exc)
    _assert_canary_absent(stdout, stderr, str(exc), repr(exc))


def test_cli_via_run_command_refuses(tmp_path):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = transport.main(
            [
                "--profile",
                transport.PROFILE,
                "--resource-group",
                transport.RESOURCE_GROUP,
                "--vault-name",
                "kv-cbot-prd-lab01",
                "--via-run-command",
                "--plan-only",
                "--secret-name",
                "CLERK-SECRET-KEY",
            ]
        )
    stdout, stderr = out.getvalue(), err.getvalue()
    assert code == 1
    assert "run_command_secret_transport_forbidden" in stderr
    _assert_canary_absent(stdout, stderr)


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile", "staging"),
        ("profile", "cosmabot-vm-staging"),
        ("resource_group", "rg-cosmas-os-vm-staging-eus2-lab01"),
        ("vault_name", "kv-cbot-stg-lab01"),
        ("vm_name", "vm-cosmabot-staging-eus2-lab01"),
    ],
)
def test_refuses_staging_coordinates(field, value):
    coords = _coords(**{field: value})
    with pytest.raises(transport.Refused):
        transport.validate_prod_coordinates(**coords)


def test_refuses_wrong_prod_profile():
    with pytest.raises(transport.Refused, match="profile_required"):
        transport.validate_prod_coordinates(**_coords(profile="cosmabot-vm-prod-v0"))


def test_llm_source_account_requires_oai_cbot_prd():
    assert transport.validate_llm_source_account(
        {transport.SOURCE_ACCOUNT_TAG: PROD_ACCOUNT}
    ) == PROD_ACCOUNT


def test_llm_refuses_cosmascode_source_account():
    with pytest.raises(transport.Refused, match="cosmascode_key_refused|llm_source_account"):
        transport.validate_llm_source_account(
            {transport.SOURCE_ACCOUNT_TAG: COSMASCODE_ACCOUNT}
        )


def test_llm_refuses_services_ai_azure_marker():
    with pytest.raises(transport.Refused, match="cosmascode_key_refused"):
        transport.validate_llm_source_account(
            {
                transport.SOURCE_ACCOUNT_TAG: (
                    "https://cosmascode.services.ai.azure.com/openai/v1"
                )
            }
        )


def test_transport_from_vault_fake_installs_and_never_prints_canary(tmp_path):
    root = tmp_path / "runtime" / "rel-2"
    root.mkdir(parents=True)
    reader = transport.FakeVaultReader(
        values={
            "WORKSPACE-LLM-API-KEY": CANARY.encode(),
            "CLERK-SECRET-KEY": b"synthetic-clerk-fixture-not-canary",
        },
        tags={
            "WORKSPACE-LLM-API-KEY": {transport.SOURCE_ACCOUNT_TAG: PROD_ACCOUNT},
        },
    )
    mappings = transport.resolve_mappings(
        ["WORKSPACE-LLM-API-KEY", "CLERK-SECRET-KEY"]
    )
    results, stdout, stderr, exc = _capture(
        transport.transport_from_vault,
        mappings,
        vault_name="kv-cbot-prd-lab01",
        protected_root=root,
        release_id="rel-2",
        reader=reader,
        chown_enabled=False,
    )
    assert exc is None
    assert results is not None
    _assert_canary_absent(stdout, stderr, also=results)
    for line in (transport.format_result_line(item) for item in results):
        _assert_canary_absent(line)
    llm = root / "api" / "WORKSPACE_LLM_API_KEY"
    assert llm.read_bytes() == CANARY.encode()
    assert stat.S_IMODE(llm.stat().st_mode) == 0o400


def test_transport_refuses_cosmascode_tagged_llm_before_write(tmp_path):
    root = tmp_path / "runtime" / "rel-3"
    root.mkdir(parents=True)
    reader = transport.FakeVaultReader(
        values={"WORKSPACE-LLM-API-KEY": CANARY.encode()},
        tags={
            "WORKSPACE-LLM-API-KEY": {
                transport.SOURCE_ACCOUNT_TAG: COSMASCODE_ACCOUNT
            }
        },
    )
    mappings = transport.resolve_mappings(["WORKSPACE-LLM-API-KEY"])
    _, stdout, stderr, exc = _capture(
        transport.transport_from_vault,
        mappings,
        vault_name="kv-cbot-prd-lab01",
        protected_root=root,
        release_id="rel-3",
        reader=reader,
        chown_enabled=False,
    )
    assert isinstance(exc, transport.Refused)
    _assert_canary_absent(stdout, stderr, str(exc), repr(exc))
    assert not (root / "api" / "WORKSPACE_LLM_API_KEY").exists()


def test_transport_empty_vault_value_stops(tmp_path):
    root = tmp_path / "runtime" / "rel-4"
    root.mkdir(parents=True)
    reader = transport.FakeVaultReader(values={"REDIS-PASSWORD": b"\n"})
    mappings = transport.resolve_mappings(["REDIS-PASSWORD"])
    with pytest.raises(transport.Refused, match="vault_secret_empty"):
        transport.transport_from_vault(
            mappings,
            vault_name="kv-cbot-prd-lab01",
            protected_root=root,
            release_id="rel-4",
            reader=reader,
            chown_enabled=False,
        )


def test_az_reader_captures_value_without_printing_it():
    """AzCliVaultReader returns bytes to caller; subprocess stdout is not printed."""

    def fake_run(argv, capture_output=True, check=False, text=False):
        assert argv[0] == "az"
        assert "keyvault" in argv
        if "tags" in argv:
            return SimpleNamespace(
                returncode=0,
                stdout=f'{{"source-account": "{PROD_ACCOUNT}"}}',
                stderr="",
            )
        return SimpleNamespace(
            returncode=0,
            stdout=CANARY.encode(),
            stderr=b"",
        )

    reader = transport.AzCliVaultReader(runner=fake_run)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        value = reader.read_value("kv-cbot-prd-lab01", "WORKSPACE-LLM-API-KEY")
        tags = reader.read_tags("kv-cbot-prd-lab01", "WORKSPACE-LLM-API-KEY")
    assert value == CANARY.encode()
    transport.validate_llm_source_account(tags)
    _assert_canary_absent(out.getvalue(), err.getvalue())


def test_exception_message_scrub_on_failed_install(tmp_path):
    """If install raises, the Refused / SystemExit path must not echo the canary."""
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-5"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode())
    # Create destination first so write_secret refuses (exists).
    role = root / "api"
    role.mkdir()
    (role / "CLERK_SECRET_KEY").write_bytes(b"prior")
    mappings = transport.resolve_mappings(["CLERK-SECRET-KEY"])
    _, stdout, stderr, exc = _capture(
        transport.install_from_staging,
        mappings,
        protected_root=root,
        staging_dir=staging,
        release_id="rel-5",
        chown_enabled=False,
    )
    assert isinstance(exc, transport.Refused)
    _assert_canary_absent(stdout, stderr, str(exc), repr(exc))


def test_cli_plan_only_exit_zero():
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = transport.main(
            [
                "--profile",
                transport.PROFILE,
                "--resource-group",
                transport.RESOURCE_GROUP,
                "--vault-name",
                "kv-cbot-prd-lab01",
                "--plan-only",
                "--secret-name",
                "HUMAN-DEPLOY-EVIDENCE-REF",
            ]
        )
    assert code == 0
    assert "HUMAN-DEPLOY-EVIDENCE-REF" in out.getvalue()
    assert "HUMAN_DEPLOY_EVIDENCE_REF" in out.getvalue()
    assert CANARY not in out.getvalue()
    assert CANARY not in err.getvalue()


def test_overwrite_refused(tmp_path):
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-6"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / "POSTGRES_PASSWORD").write_bytes(b"synthetic-postgres-fixture-01")
    mappings = transport.resolve_mappings(["POSTGRES-PASSWORD"])
    transport.install_from_staging(
        mappings,
        protected_root=root,
        staging_dir=staging,
        release_id="rel-6",
        chown_enabled=False,
    )
    with pytest.raises(transport.Refused, match="secret_file_exists"):
        transport.install_from_staging(
            mappings,
            protected_root=root,
            staging_dir=staging,
            release_id="rel-6",
            chown_enabled=False,
        )


def test_mutation_removing_empty_check_is_caught(tmp_path):
    """Kills mutation that skips empty-value STOP."""
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-7"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / "REDIS_PASSWORD").write_bytes(b"\n")
    mappings = transport.resolve_mappings(["REDIS-PASSWORD"])
    with pytest.raises(transport.Refused):
        transport.install_from_staging(
            mappings,
            protected_root=root,
            staging_dir=staging,
            release_id="rel-7",
            chown_enabled=False,
        )


def test_module_source_never_hardcodes_live_secret_values():
    source = MODULE_PATH.read_text()
    assert "sk_live_" not in source
    assert "sk_test_" not in source
    assert CANARY not in source
