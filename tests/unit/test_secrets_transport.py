"""T-PROD-3-SECRETS: prod Key Vault name → mode-0400 host file transport.

Synthetic fixtures only. Never calls Azure. Proves secret VALUES never appear
in stdout, stderr, or Refused exception messages. Collected by synth-ci.
"""
from __future__ import annotations

import importlib.util
import io
import os
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
WRONG_RG_RIGHT_NAME = (
    "/subscriptions/00000000-0000-4000-8000-000000000001"
    "/resourceGroups/rg-other-prod-eus2-01"
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


def _fake_fs(uid_map: dict[str, int] | None = None):
    """Injected chown/lstat harness so the shipping writer (with chown) is tested."""
    owners: dict[object, int] = {}
    if uid_map:
        owners.update(uid_map)

    def chown_fn(path, uid, gid):
        path_obj = Path(path)
        owners[str(path_obj)] = uid
        try:
            owners[("ino", path_obj.stat().st_ino)] = uid
        except OSError:
            pass

    def lstat_fn(path):
        real = os.lstat(path)
        uid = owners.get(str(path))
        if uid is None:
            uid = owners.get(("ino", real.st_ino), real.st_uid)
        return SimpleNamespace(
            st_mode=real.st_mode,
            st_nlink=real.st_nlink,
            st_uid=uid,
            st_gid=uid,
            st_size=real.st_size,
        )

    return chown_fn, lstat_fn, owners


def _write_llm_sidecar(staging: Path, account: str = PROD_ACCOUNT) -> None:
    (staging / f"{transport.LLM_HOST_NAME}{transport.SOURCE_ACCOUNT_SIDECAR_SUFFIX}").write_text(
        account
    )


# --- plan / CLI canaries (seeded via staging files the path must not read) ---


def test_cli_plan_only_does_not_read_or_echo_staging_secret_files(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode())
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
                "--staging-dir",
                str(staging),
                "--secret-name",
                "CLERK-SECRET-KEY",
            ]
        )
    assert code == 0
    assert "CLERK-SECRET-KEY" in out.getvalue()
    _assert_canary_absent(out.getvalue(), err.getvalue())


def test_cli_via_run_command_refuses_without_echoing_staging_secret(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode())
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
                "--staging-dir",
                str(staging),
                "--plan-only",
                "--secret-name",
                "CLERK-SECRET-KEY",
            ]
        )
    assert code == 1
    assert "run_command_secret_transport_forbidden" in err.getvalue()
    _assert_canary_absent(out.getvalue(), err.getvalue())


def test_plan_lines_never_echo_module_trap(monkeypatch):
    """If plan_lines dumped module globals / traps, a seeded canary would leak."""
    monkeypatch.setattr(transport, "_PLAN_CANARY_TRAP", CANARY, raising=False)
    mappings = transport.resolve_mappings(["HUMAN-DEPLOY-EVIDENCE-REF"])
    text = "\n".join(transport.plan_lines(mappings))
    assert "HUMAN-DEPLOY-EVIDENCE-REF" in text
    assert transport.TEMP_SSH_NSG_RULE_NAME in text
    assert "temp_ssh_nsg_rule_john_32" in text
    assert "close_and_verify=mandatory_before_terraform_plan_or_apply" in text
    assert "vm_az_login_as_secrets_officer=forbidden" in text
    assert "PENDING_JOHN_DECISION" not in text
    _assert_canary_absent(text)


# --- shipping writer with injected chown/stat ---


def test_write_secret_atomic_chown_and_owner_uid(tmp_path):
    dest = tmp_path / "CLERK_SECRET_KEY"
    chown_fn, lstat_fn, owners = _fake_fs()
    result = transport.write_secret_atomic(
        dest,
        CANARY.encode() + b"\n",
        transport.API_UID,
        chown_fn=chown_fn,
        lstat_fn=lstat_fn,
    )
    assert result["owner_uid"] == transport.API_UID
    assert result["mode"] == "0400"
    assert dest.read_bytes() == CANARY.encode()
    assert stat.S_IMODE(dest.stat().st_mode) == 0o400
    assert any(uid == transport.API_UID for uid in owners.values())
    _assert_canary_absent(str(result), repr(result))


def test_write_secret_atomic_wrong_uid_after_chown_stops(tmp_path):
    """Mutation killer: st_uid check must fail if ownership is wrong."""
    dest = tmp_path / "REDIS_PASSWORD"

    def chown_fn(path, uid, gid):
        return None  # pretend success

    def lstat_fn(path):
        real = os.lstat(path)
        return SimpleNamespace(
            st_mode=real.st_mode,
            st_nlink=real.st_nlink,
            st_uid=0,  # wrong — not ROLE uid
            st_gid=0,
            st_size=real.st_size,
        )

    with pytest.raises(transport.Refused, match="secret_file_mode_owner_failed"):
        transport.write_secret_atomic(
            dest,
            b"synthetic-redis-fixture-value-01",
            transport.DATA_UID,
            chown_fn=chown_fn,
            lstat_fn=lstat_fn,
        )


def test_write_secret_atomic_rejects_nul(tmp_path):
    with pytest.raises(transport.Refused, match="secret_value_nul_refused"):
        transport.write_secret_atomic(
            tmp_path / "X",
            b"abc\x00def",
            transport.API_UID,
            chown_fn=lambda *_: None,
            lstat_fn=os.lstat,
        )


@pytest.mark.parametrize(
    "payload",
    [b"", b"\n", b"\n\n", b"\r\n", b"   ", b"\t\t", b" \n \r\n "],
)
def test_normalize_and_write_reject_whitespace_only(tmp_path, payload):
    with pytest.raises(transport.Refused, match="secret_value_empty"):
        transport.normalize_secret_value(payload)
    with pytest.raises(transport.Refused, match="secret_value_empty"):
        transport.write_secret_atomic(
            tmp_path / "EMPTY",
            payload,
            transport.API_UID,
            chown_fn=lambda *_: None,
            lstat_fn=os.lstat,
        )


def test_install_uses_shipping_writer_chown_per_role(tmp_path):
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-1"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode())
    chown_fn, lstat_fn, owners = _fake_fs()
    mappings = transport.resolve_mappings(["CLERK-SECRET-KEY"])
    results, stdout, stderr, exc = _capture(
        transport.install_from_staging,
        mappings,
        protected_root=root,
        staging_dir=staging,
        release_id="rel-1",
        chown_fn=chown_fn,
        lstat_fn=lstat_fn,
    )
    assert exc is None
    assert results is not None
    _assert_canary_absent(stdout, stderr, also=results)
    assert {r["owner_uid"] for r in results} == {transport.API_UID}
    assert transport.API_UID in owners.values()


# --- LLM source-account on EVERY path ---


def test_install_from_staging_requires_llm_source_account_sidecar(tmp_path):
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-llm"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / transport.LLM_HOST_NAME).write_bytes(b"synthetic-llm-fixture-value")
    mappings = transport.resolve_mappings(["WORKSPACE-LLM-API-KEY"])
    chown_fn, lstat_fn, _ = _fake_fs()
    with pytest.raises(transport.Refused, match="llm_source_account_sidecar_required"):
        transport.install_from_staging(
            mappings,
            protected_root=root,
            staging_dir=staging,
            release_id="rel-llm",
            chown_fn=chown_fn,
            lstat_fn=lstat_fn,
        )


def test_install_from_staging_enforces_llm_source_account(tmp_path):
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-llm2"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / transport.LLM_HOST_NAME).write_bytes(CANARY.encode())
    _write_llm_sidecar(staging, COSMASCODE_ACCOUNT)
    mappings = transport.resolve_mappings(["WORKSPACE-LLM-API-KEY"])
    chown_fn, lstat_fn, _ = _fake_fs()
    _, stdout, stderr, exc = _capture(
        transport.install_from_staging,
        mappings,
        protected_root=root,
        staging_dir=staging,
        release_id="rel-llm2",
        chown_fn=chown_fn,
        lstat_fn=lstat_fn,
    )
    assert isinstance(exc, transport.Refused)
    _assert_canary_absent(stdout, stderr, str(exc), repr(exc))
    assert not (root / "api" / transport.LLM_HOST_NAME).exists()


def test_cli_install_llm_without_sidecar_stops(tmp_path):
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-cli"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / transport.LLM_HOST_NAME).write_bytes(CANARY.encode())
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
                "--release-id",
                "rel-cli",
                "--protected-root",
                str(root),
                "--staging-dir",
                str(staging),
                "--secret-name",
                "WORKSPACE-LLM-API-KEY",
            ]
        )
    assert code == 1
    assert "llm_source_account" in err.getvalue()
    _assert_canary_absent(out.getvalue(), err.getvalue())


# --- stage-only workstation mode ---


def test_stage_from_vault_writes_mode_700_dir_and_sidecar(tmp_path):
    staging = tmp_path / "private-stage"
    reader = transport.FakeVaultReader(
        values={"WORKSPACE-LLM-API-KEY": CANARY.encode()},
        tags={"WORKSPACE-LLM-API-KEY": {transport.SOURCE_ACCOUNT_TAG: PROD_ACCOUNT}},
    )
    mappings = transport.resolve_mappings(["WORKSPACE-LLM-API-KEY"])
    results, stdout, stderr, exc = _capture(
        transport.stage_from_vault,
        mappings,
        vault_name="kv-cbot-prd-lab01",
        staging_dir=staging,
        reader=reader,
    )
    assert exc is None
    assert results is not None
    _assert_canary_absent(stdout, stderr, also=results)
    assert staging.is_dir()
    assert stat.S_IMODE(staging.stat().st_mode) == 0o700
    secret = staging / transport.LLM_HOST_NAME
    assert secret.read_bytes() == CANARY.encode()
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    sidecar = staging / f"{transport.LLM_HOST_NAME}{transport.SOURCE_ACCOUNT_SIDECAR_SUFFIX}"
    assert sidecar.read_text() == PROD_ACCOUNT


def test_stage_from_vault_refuses_cosmascode(tmp_path):
    staging = tmp_path / "private-stage"
    reader = transport.FakeVaultReader(
        values={"WORKSPACE-LLM-API-KEY": CANARY.encode()},
        tags={"WORKSPACE-LLM-API-KEY": {transport.SOURCE_ACCOUNT_TAG: COSMASCODE_ACCOUNT}},
    )
    mappings = transport.resolve_mappings(["WORKSPACE-LLM-API-KEY"])
    _, stdout, stderr, exc = _capture(
        transport.stage_from_vault,
        mappings,
        vault_name="kv-cbot-prd-lab01",
        staging_dir=staging,
        reader=reader,
    )
    assert isinstance(exc, transport.Refused)
    _assert_canary_absent(stdout, stderr, str(exc))
    assert not (staging / transport.LLM_HOST_NAME).exists()


def test_cleanup_private_dir_removes_staged_canary(tmp_path):
    staging = tmp_path / "to-clean"
    staging.mkdir(mode=0o700)
    target = staging / "CLERK_SECRET_KEY"
    target.write_bytes(CANARY.encode())
    transport.cleanup_private_dir(staging)
    assert not staging.exists()
    assert not target.exists()


def test_no_vm_az_login_variant_in_source_or_help():
    source = MODULE_PATH.read_text()
    assert "vm_az_login_as_secrets_officer=forbidden" in source
    assert transport.TEMP_SSH_NSG_RULE_NAME in source
    assert "PENDING_JOHN_DECISION" not in source
    assert "Secrets Officer token" in source
    assert "--from-vault" not in source
    assert "emit-host-script" not in source
    assert "render_names_only_host_script" not in dir(transport)
    help_out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(help_out), redirect_stderr(err):
        with pytest.raises(SystemExit) as exit_info:
            transport.main(["--help"])
    assert exit_info.value.code == 0
    text = help_out.getvalue() + err.getvalue()
    assert "stage-from-vault" in text
    assert "Workstation only" in text
    assert "ack-close-and-verify" in text
    assert "az login as" not in text.lower()


def _baseline_nsg_rules(*, with_temp: bool = True) -> list[dict]:
    rules = [
        {"name": "https", "port": "443", "access": "Allow", "priority": 100},
        {
            "name": "acme-http-and-https-redirect",
            "port": "80",
            "access": "Allow",
            "priority": 110,
        },
        {
            "name": transport.DENY_ALL_INGRESS_RULE_NAME,
            "port": "*",
            "access": "Deny",
            "priority": transport.DENY_ALL_INGRESS_PRIORITY,
        },
    ]
    if with_temp:
        rules.insert(
            2,
            {
                "name": transport.TEMP_SSH_NSG_RULE_NAME,
                "port": "22",
                "access": "Allow",
                "priority": transport.TEMP_SSH_NSG_RULE_PRIORITY,
            },
        )
    return rules


def test_temp_ssh_rule_name_and_priority_constants():
    assert transport.TEMP_SSH_NSG_RULE_NAME == "TEMP-JOHN-SSH-SECRETS-INSTALL"
    assert transport.TEMP_SSH_NSG_RULE_PRIORITY == 200
    assert transport.TEMP_SSH_NSG_RULE_PRIORITY < transport.DENY_ALL_INGRESS_PRIORITY
    assert transport.PROD_NSG_NAME == "nsg-cosmabot-prod-eus2-01"


def test_require_temp_ssh_rule_open_and_closed():
    open_rules = _baseline_nsg_rules(with_temp=True)
    transport.require_temp_ssh_rule_open(open_rules)
    closed_rules = _baseline_nsg_rules(with_temp=False)
    transport.require_temp_ssh_rule_closed(closed_rules)


def test_require_temp_ssh_rule_open_refuses_missing():
    with pytest.raises(transport.Refused, match="temp_ssh_nsg_rule_missing"):
        transport.require_temp_ssh_rule_open(_baseline_nsg_rules(with_temp=False))


def test_require_ssh_install_ready_refuses_without_ack():
    with pytest.raises(transport.Refused, match="close_and_verify_ack_required"):
        transport.require_ssh_install_ready(
            nsg_rules=_baseline_nsg_rules(with_temp=True),
            close_verify_acked=False,
        )


def test_require_ssh_install_ready_refuses_when_rule_absent():
    with pytest.raises(transport.Refused, match="temp_ssh_nsg_rule_missing"):
        transport.require_ssh_install_ready(
            nsg_rules=_baseline_nsg_rules(with_temp=False),
            close_verify_acked=True,
        )


def test_cli_check_ssh_install_ready_requires_ack_and_rule(tmp_path):
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(
        __import__("json").dumps(_baseline_nsg_rules(with_temp=True)),
        encoding="utf-8",
    )
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
                "--check-ssh-install-ready",
                "--nsg-rules-json",
                str(rules_path),
            ]
        )
    assert code == 1
    assert "close_and_verify_ack_required" in err.getvalue()
    with redirect_stdout(out), redirect_stderr(err):
        code = transport.main(
            [
                "--profile",
                transport.PROFILE,
                "--resource-group",
                transport.RESOURCE_GROUP,
                "--vault-name",
                "kv-cbot-prd-lab01",
                "--check-ssh-install-ready",
                "--ack-close-and-verify",
                "--nsg-rules-json",
                str(rules_path),
            ]
        )
    assert code == 0
    assert transport.TEMP_SSH_NSG_RULE_NAME in out.getvalue()


def test_cli_check_ssh_closed(tmp_path):
    rules_path = tmp_path / "rules-closed.json"
    rules_path.write_text(
        __import__("json").dumps(_baseline_nsg_rules(with_temp=False)),
        encoding="utf-8",
    )
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
                "--check-ssh-closed",
                "--nsg-rules-json",
                str(rules_path),
            ]
        )
    assert code == 0
    assert "mandatory before Terraform" in out.getvalue()


def test_fence_files_declare_fixed_rule_name():
    fences = REPO / "infra/beta/vm/host/fences"
    for name in (
        "fence-ssh-nsg-open.sh",
        "fence-ssh-nsg-close-verify.sh",
        "fence-ssh-nsg-recovery.sh",
        "fence-ssh-secrets-install.sh",
        "fence-ssh-secrets-session.sh",
    ):
        text = (fences / name).read_text()
        assert transport.TEMP_SSH_NSG_RULE_NAME in text or name.endswith("session.sh")
        assert "#" not in [
            line for line in text.splitlines() if line.strip().startswith("#")
        ]


# --- private work dir for transport_from_vault ---


def test_transport_from_vault_uses_private_work_dir_and_cleans_up(tmp_path):
    root = tmp_path / "runtime" / "rel-2"
    root.mkdir(parents=True)
    work_parent = tmp_path / "private-work"
    reader = transport.FakeVaultReader(
        values={
            "WORKSPACE-LLM-API-KEY": CANARY.encode(),
            "CLERK-SECRET-KEY": b"synthetic-clerk-fixture-not-canary",
        },
        tags={"WORKSPACE-LLM-API-KEY": {transport.SOURCE_ACCOUNT_TAG: PROD_ACCOUNT}},
    )
    mappings = transport.resolve_mappings(
        ["WORKSPACE-LLM-API-KEY", "CLERK-SECRET-KEY"]
    )
    chown_fn, lstat_fn, _ = _fake_fs()
    results, stdout, stderr, exc = _capture(
        transport.transport_from_vault,
        mappings,
        vault_name="kv-cbot-prd-lab01",
        protected_root=root,
        release_id="rel-2",
        reader=reader,
        work_parent=work_parent,
        chown_fn=chown_fn,
        lstat_fn=lstat_fn,
    )
    assert exc is None
    assert results is not None
    _assert_canary_absent(stdout, stderr, also=results)
    # Private work children cleaned up (parent may remain empty or gone).
    if work_parent.exists():
        leftovers = list(work_parent.rglob("*"))
        assert leftovers == [] or all(p.is_dir() for p in leftovers)
    llm = root / "api" / transport.LLM_HOST_NAME
    assert llm.read_bytes() == CANARY.encode()


def test_transport_from_vault_cleans_private_dir_on_exception(tmp_path):
    root = tmp_path / "runtime" / "rel-boom"
    root.mkdir(parents=True)
    work_parent = tmp_path / "private-work-boom"
    reader = transport.FakeVaultReader(
        values={"WORKSPACE-LLM-API-KEY": CANARY.encode()},
        tags={"WORKSPACE-LLM-API-KEY": {transport.SOURCE_ACCOUNT_TAG: COSMASCODE_ACCOUNT}},
    )
    mappings = transport.resolve_mappings(["WORKSPACE-LLM-API-KEY"])
    chown_fn, lstat_fn, _ = _fake_fs()
    with pytest.raises(transport.Refused):
        transport.transport_from_vault(
            mappings,
            vault_name="kv-cbot-prd-lab01",
            protected_root=root,
            release_id="rel-boom",
            reader=reader,
            work_parent=work_parent,
            chown_fn=chown_fn,
            lstat_fn=lstat_fn,
        )
    if work_parent.exists():
        for path in work_parent.rglob("*"):
            if path.is_file():
                assert CANARY.encode() not in path.read_bytes()


def test_private_work_dir_is_mode_700(tmp_path):
    with transport.private_work_dir(tmp_path / "base") as path:
        assert path.is_dir()
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
        marker = path / "x"
        marker.write_bytes(CANARY.encode())
    assert not path.exists()


# --- refusals / CosmasCode / staging ---


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


def test_staging_needle_in_staging_dir_path_refused(tmp_path):
    """Deleting refuse_staging_names must fail: path embeds kv-cbot-stg-."""
    bad = tmp_path / "contain-kv-cbot-stg-here" / "staging"
    bad.mkdir(parents=True)
    root = tmp_path / "runtime" / "rel-stg"
    root.mkdir(parents=True)
    (bad / "CLERK_SECRET_KEY").write_bytes(b"synthetic-clerk-fixture-value-01")
    mappings = transport.resolve_mappings(["CLERK-SECRET-KEY"])
    chown_fn, lstat_fn, _ = _fake_fs()
    with pytest.raises(transport.Refused, match="staging_name_refused"):
        transport.install_from_staging(
            mappings,
            protected_root=root,
            staging_dir=bad,
            release_id="rel-stg",
            chown_fn=chown_fn,
            lstat_fn=lstat_fn,
        )


def test_refuse_staging_names_raises_on_each_needle():
    """Mutation killer: empty-body refuse_staging_names fails this."""
    assert transport.STAGING_NEEDLES
    for needle in transport.STAGING_NEEDLES:
        with pytest.raises(transport.Refused, match="staging_name_refused"):
            transport.refuse_staging_names(f"prefix-{needle}-suffix")


def test_refuses_wrong_prod_profile():
    with pytest.raises(transport.Refused, match="profile_required"):
        transport.validate_prod_coordinates(**_coords(profile="cosmabot-vm-prod-v0"))


def test_llm_source_account_requires_oai_cbot_prd():
    assert (
        transport.validate_llm_source_account(
            {transport.SOURCE_ACCOUNT_TAG: PROD_ACCOUNT}
        )
        == PROD_ACCOUNT
    )


def test_llm_refuses_right_name_wrong_resource_group():
    with pytest.raises(transport.Refused, match="llm_source_account_must_be_oai-cbot-prd"):
        transport.validate_llm_source_account(
            {transport.SOURCE_ACCOUNT_TAG: WRONG_RG_RIGHT_NAME}
        )


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


def test_az_reader_failure_never_prints_canary_from_stdout_or_stderr():
    def fake_run(argv, capture_output=True, check=False, text=False):
        return SimpleNamespace(
            returncode=1,
            stdout=CANARY.encode() if not text else CANARY,
            stderr=CANARY.encode() if not text else CANARY,
        )

    reader = transport.AzCliVaultReader(runner=fake_run)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        with pytest.raises(transport.Refused, match="vault_read_failed"):
            reader.read_value("kv-cbot-prd-lab01", "CLERK-SECRET-KEY")
    _assert_canary_absent(out.getvalue(), err.getvalue())


def test_az_reader_success_captures_without_printing():
    def fake_run(argv, capture_output=True, check=False, text=False):
        if "tags" in argv:
            return SimpleNamespace(
                returncode=0,
                stdout=f'{{"source-account": "{PROD_ACCOUNT}"}}',
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout=CANARY.encode(), stderr=b"")

    reader = transport.AzCliVaultReader(runner=fake_run)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        value = reader.read_value("kv-cbot-prd-lab01", "WORKSPACE-LLM-API-KEY")
        tags = reader.read_tags("kv-cbot-prd-lab01", "WORKSPACE-LLM-API-KEY")
    assert value == CANARY.encode()
    transport.validate_llm_source_account(tags)
    _assert_canary_absent(out.getvalue(), err.getvalue())


def test_overwrite_refused(tmp_path):
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-6"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / "POSTGRES_PASSWORD").write_bytes(b"synthetic-postgres-fixture-01")
    mappings = transport.resolve_mappings(["POSTGRES-PASSWORD"])
    chown_fn, lstat_fn, _ = _fake_fs()
    transport.install_from_staging(
        mappings,
        protected_root=root,
        staging_dir=staging,
        release_id="rel-6",
        chown_fn=chown_fn,
        lstat_fn=lstat_fn,
    )
    with pytest.raises(transport.Refused, match="secret_file_exists"):
        transport.install_from_staging(
            mappings,
            protected_root=root,
            staging_dir=staging,
            release_id="rel-6",
            chown_fn=chown_fn,
            lstat_fn=lstat_fn,
        )


def test_exception_message_scrub_on_failed_install(tmp_path):
    staging = tmp_path / "staging"
    root = tmp_path / "runtime" / "rel-5"
    staging.mkdir()
    root.mkdir(parents=True)
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode())
    role = root / "api"
    role.mkdir()
    (role / "CLERK_SECRET_KEY").write_bytes(b"prior")
    mappings = transport.resolve_mappings(["CLERK-SECRET-KEY"])
    chown_fn, lstat_fn, _ = _fake_fs({str(role / "CLERK_SECRET_KEY"): transport.API_UID})
    _, stdout, stderr, exc = _capture(
        transport.install_from_staging,
        mappings,
        protected_root=root,
        staging_dir=staging,
        release_id="rel-5",
        chown_fn=chown_fn,
        lstat_fn=lstat_fn,
    )
    assert isinstance(exc, transport.Refused)
    _assert_canary_absent(stdout, stderr, str(exc), repr(exc))


def test_module_source_never_hardcodes_live_secret_values():
    source = MODULE_PATH.read_text()
    assert "sk_live_" not in source
    assert "sk_test_" not in source
    assert CANARY not in source
    assert "§4.3" in source or "4.3" in source
