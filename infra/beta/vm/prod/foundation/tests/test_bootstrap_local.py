"""Local bootstrap refusal tests and an actual OpenTofu encryption-only proof."""
from __future__ import annotations

import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap_local", MODULE / "bootstrap_local.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cosmabot-encrypted-bootstrap-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.folder = self.root / "fresh"
        self.tofu = self.root / "tofu"
        self.tofu.write_text("not executed; mocked version check\n")
        self.tofu.chmod(0o700)
        self.mirror = self.root / "provider-mirror"
        self.mirror.mkdir()
        self.inputs = {"subscription_id": "00000000-0000-4000-8000-000000000001",
                       "tenant_id": "00000000-0000-4000-8000-000000000002",
                       "resource_name_suffix": "mock1234", "vnet_address_prefix": "10.247.0.0/24",
                       "admin_username": "cosmasoperator", "admin_ssh_public_key": "ssh-ed25519 invented-public-key",
                       "release_operator_object_id": "00000000-0000-4000-8000-000000000003",
                       "alert_contact_email": "operator@example.invalid"}
        self.input_file = self.root / "inputs.json"
        self.input_file.write_text(json.dumps(self.inputs))
        self.context = {"subscription_id": self.inputs["subscription_id"], "tenant_id": self.inputs["tenant_id"],
                        "user_type": "user", "user_name_sha256": "a" * 64}
        env = {key: value for key, value in os.environ.items() if not key.startswith(("TF_", "ARM_")) and key != "AZURE_CONFIG_DIR"}
        self.environ = patch.dict(os.environ, env, clear=True)
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def prepare(self, **changed):
        fp = bootstrap.fingerprint()
        values = dict(folder=self.folder, inputs_path=self.input_file, expected_source=fp["source_sha256"],
                      expected_lock=fp["lock_sha256"], tofu=self.tofu, mirror=self.mirror)
        values.update(changed)
        with patch.object(bootstrap, "owner_context", return_value=self.context), patch.object(bootstrap, "command", return_value=subprocess.CompletedProcess([], 0, b'{"terraform_version":"1.12.5"}', b"")) as command:
            result = bootstrap.prepare(**values)
        return result, command

    def test_private_fresh_snapshot_key_and_fixed_local_backend(self):
        result, called = self.prepare()
        self.assertEqual(result["state_backend"], "local-encrypted")
        self.assertEqual(self.folder.stat().st_mode & 0o777, 0o700)
        key = self.folder / "encryption.passphrase"
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        secret = key.read_bytes().strip()
        self.assertGreaterEqual(len(secret), 64)
        for path in self.folder.rglob("*"):
            if path.is_file() and path != key:
                self.assertNotIn(secret, path.read_bytes())
        self.assertNotIn(secret.decode(), repr(called.call_args_list))
        self.assertEqual(json.loads((self.folder / "inputs.json").read_text())["state_namespace"], bootstrap.NAMESPACE)
        self.assertIn(str(self.folder / "state/foundation.tfstate"), (self.folder / "backend.hcl").read_text())
        self.assertIn('backend "local"', (self.folder / "module/versions.tf").read_text())
        self.assertEqual((self.folder / "module/encryption.tf").read_bytes(), (MODULE / "encryption.tf").read_bytes())
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_refuses_stale_source_and_lock_before_creating_any_key(self):
        for field in ("expected_source", "expected_lock"):
            with self.subTest(field=field), self.assertRaises(bootstrap.Refused):
                self.prepare(**{field: "0" * 64})
        self.assertFalse(self.folder.exists())

    def test_ambient_override_cannot_disable_encryption_or_change_identity_workspace(self):
        for name in ("TF_ENCRYPTION", "TF_CLI_ARGS", "TF_WORKSPACE", "TF_DATA_DIR", "TF_VAR_bootstrap_key_file", "ARM_CLIENT_ID", "AZURE_CONFIG_DIR"):
            with self.subTest(name=name), patch.dict(os.environ, {name: "unreviewed"}), self.assertRaises(bootstrap.Refused):
                self.prepare()
        self.assertFalse(self.folder.exists())

    def test_generated_and_secret_inputs_are_refused(self):
        for name in ("bootstrap_key_file", "state_namespace", "admin_password"):
            self.input_file.write_text(json.dumps({**self.inputs, name: "unreviewed"}))
            with self.subTest(name=name), self.assertRaises(bootstrap.Refused):
                self.prepare()
        self.assertFalse(self.folder.exists())

    def test_enable_azure_openai_bool_accepted_string_refused(self):
        self.input_file.write_text(json.dumps({**self.inputs, "enable_azure_openai": True}))
        result, _ = self.prepare()
        self.assertTrue(result["prepared"])
        written = json.loads((self.folder / "inputs.json").read_text())
        self.assertIs(written["enable_azure_openai"], True)
        shutil.rmtree(self.folder)
        self.input_file.write_text(json.dumps({**self.inputs, "enable_azure_openai": "true"}))
        with self.assertRaises(bootstrap.Refused):
            self.prepare()
        self.assertFalse(self.folder.exists())

    def test_changed_inputs_snapshot_or_existing_data_are_refused_before_azure(self):
        self.prepare()
        original = (self.folder / "inputs.json").read_bytes()
        (self.folder / "inputs.json").write_bytes(original + b" ")
        with patch.object(bootstrap, "owner_context") as azure, self.assertRaises(bootstrap.Refused):
            bootstrap.plan(self.folder)
        azure.assert_not_called()
        (self.folder / "inputs.json").write_bytes(original)
        (self.folder / "module/unreviewed.tf").write_text("# refused\n")
        with patch.object(bootstrap, "owner_context") as azure, self.assertRaises(bootstrap.Refused):
            bootstrap.plan(self.folder)
        azure.assert_not_called()
        (self.folder / "module/unreviewed.tf").unlink()
        (self.folder / "state/old.tfstate").write_text("invented old state")
        with patch.object(bootstrap, "owner_context") as azure, self.assertRaises(bootstrap.Refused):
            bootstrap.plan(self.folder)
        azure.assert_not_called()

    def test_symlink_or_permissive_key_custody_is_refused(self):
        self.prepare()
        key = self.folder / "encryption.passphrase"
        key.chmod(0o644)
        with patch.object(bootstrap, "owner_context") as azure, patch.object(bootstrap, "command") as command, self.assertRaises(bootstrap.Refused):
            bootstrap.plan(self.folder)
        azure.assert_not_called()
        command.assert_not_called()
        key.chmod(0o600)
        saved = self.folder / "moved-passphrase"
        key.rename(saved)
        key.symlink_to(saved)
        with patch.object(bootstrap, "owner_context") as azure, patch.object(bootstrap, "command") as command, self.assertRaises(bootstrap.Refused):
            bootstrap.plan(self.folder)
        azure.assert_not_called()
        command.assert_not_called()

    def test_replaced_generated_key_is_refused_before_azure_or_init(self):
        result, _ = self.prepare()
        key = self.folder / "encryption.passphrase"
        manifest = json.loads((self.folder / "manifest.json").read_text())
        self.assertEqual(manifest["protected_files"]["encryption.passphrase"], bootstrap.digest(key))
        self.assertNotIn(bootstrap.digest(key), json.dumps(result))
        key.write_bytes((secrets.token_urlsafe(48) + "\n").encode())
        with patch.object(bootstrap, "owner_context") as azure, patch.object(bootstrap, "command") as command, self.assertRaises(bootstrap.Refused):
            bootstrap.plan(self.folder)
        azure.assert_not_called()
        command.assert_not_called()

    def test_owner_context_must_be_user_and_new_resource_group_absent(self):
        account = {"id": self.inputs["subscription_id"], "tenantId": self.inputs["tenant_id"], "state": "Enabled", "user": {"type": "user", "name": "invented-owner"}}
        good = subprocess.CompletedProcess([], 0, json.dumps(account).encode(), b"")
        absent = subprocess.CompletedProcess([], 0, b"false", b"")
        with patch.object(bootstrap, "command", side_effect=[good, absent]):
            self.assertEqual(bootstrap.owner_context({}, self.inputs)["user_type"], "user")
        with patch.object(bootstrap, "command", side_effect=[good, subprocess.CompletedProcess([], 0, b"true", b"")]), self.assertRaises(bootstrap.Refused):
            bootstrap.owner_context({}, self.inputs)
        account["user"]["type"] = "servicePrincipal"
        with patch.object(bootstrap, "command", return_value=subprocess.CompletedProcess([], 0, json.dumps(account).encode(), b"")), self.assertRaises(bootstrap.Refused):
            bootstrap.owner_context({}, self.inputs)

    def test_plan_uses_real_local_init_then_plan_only_with_private_outputs(self):
        self.prepare()
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[1] == "init":
                data = self.folder / "tofu-data"
                data.mkdir(mode=0o700)
                bootstrap.write_private(data / "terraform.tfstate", bootstrap.json_bytes({"backend": {"type": "local", "config": {
                    "path": str(self.folder / "state/foundation.tfstate"), "workspace_dir": str(self.folder / "workspaces")}}}))
            elif argv[1] == "plan":
                bootstrap.write_private(self.folder / "plans/first.tfplan", bootstrap.json_bytes({"encryption_version": "v0", "encrypted_data": "invented-ciphertext-envelope", "meta": {}}))
            elif argv[1] == "show":
                return subprocess.CompletedProcess(argv, 0, json.dumps({"resource_changes": [{"type": "azurerm_resource_group", "change": {"actions": ["create"]}}]}).encode(), b"")
            return subprocess.CompletedProcess(argv, 0, b"private simulated command output", b"")
        with patch.object(bootstrap, "owner_context", return_value=self.context), patch.object(bootstrap, "command", side_effect=run):
            result = bootstrap.plan(self.folder)
        self.assertEqual([argv[1] for argv, _ in calls], ["init", "plan", "show"])
        self.assertFalse(result["applied"])
        self.assertTrue((self.folder / "plan-summary.json").is_file())
        for argv, kwargs in calls:
            self.assertNotIn("-backend=false", argv)
            self.assertEqual(kwargs["env"]["TF_WORKSPACE"], "default")
            self.assertEqual(kwargs["env"]["TF_VAR_bootstrap_key_file"], str(self.folder / "encryption.passphrase"))
            self.assertNotIn("TF_ENCRYPTION", kwargs["env"])
            self.assertEqual(kwargs["cwd"], self.folder / "module")

    def test_m9_prepare_refuses_staging_name_and_leaves_folder_absent(self):
        self.input_file.write_text(json.dumps({**self.inputs, "alert_contact_email": "ops@staging.cosmas.ai"}))
        with self.assertRaises(bootstrap.Refused):
            self.prepare()
        self.assertFalse(self.folder.exists())

    def test_module_openai_snapshot_byte_identical_and_edit_refuses_before_owner(self):
        self.prepare()
        snap = self.folder / "module/modules/azure_openai/main.tf"
        source = bootstrap.MODULE / "modules/azure_openai/main.tf"
        self.assertEqual(snap.read_bytes(), source.read_bytes())
        snap.write_bytes(snap.read_bytes() + b"\n# edited\n")
        with patch.object(bootstrap, "owner_context") as azure, patch.object(bootstrap, "command") as command, self.assertRaises(bootstrap.Refused):
            bootstrap.plan(self.folder)
        azure.assert_not_called()
        command.assert_not_called()

    def test_extra_openai_module_file_refuses_plan_before_owner(self):
        self.prepare()
        extra = self.folder / "module/modules/azure_openai/unreviewed.tf"
        bootstrap.write_private(extra, b'# unreviewed\n')
        with patch.object(bootstrap, "owner_context") as azure, patch.object(bootstrap, "command") as command, self.assertRaises(bootstrap.Refused):
            bootstrap.plan(self.folder)
        azure.assert_not_called()
        command.assert_not_called()

    def _write_plan_artifacts(self, plan_bytes=b"invented-encrypted-plan-bytes"):
        plans = self.folder / "plans"
        plans.mkdir(mode=0o700, exist_ok=True)
        plan_path = plans / "first.tfplan"
        if plan_path.exists():
            plan_path.unlink()
        for name in ("plan-summary.json", "plan-result.json"):
            path = self.folder / name
            if path.exists():
                path.unlink()
        bootstrap.write_private(plan_path, plan_bytes)
        plan_sha = bootstrap.digest(plan_path)
        plan_json = {
            "resource_changes": [
                {"type": "azurerm_resource_group", "change": {"actions": ["create"]}},
            ]
        }
        summary = bootstrap.sanitize_plan_summary(
            plan_json,
            inputs={**self.inputs, "enable_azure_openai": False},
            plan_sha256=plan_sha,
        )
        bootstrap.write_private(self.folder / "plan-summary.json", bootstrap.json_bytes(summary))
        result = {
            "planned": True,
            "plan_sha256": plan_sha,
            "summary_sha256": summary["summary_sha256"],
            "enable_azure_openai": False,
            "applied": False,
            "first_apply_only": True,
        }
        bootstrap.write_private(self.folder / "plan-result.json", bootstrap.json_bytes(result))
        return plan_sha, summary, plan_json

    def _planned(self):
        if not self.folder.exists():
            self.prepare()
        return self._write_plan_artifacts()

    def _approval(self, plan_sha: str, summary_sha: str, *, mode=0o600, inside_repo=False, symlink=False, extra=None, drop=None):
        payload = {
            "reviewer": "john@example.invalid",
            "review_reference": "ticket",
            "plan_sha256": plan_sha,
            "summary_sha256": summary_sha,
        }
        if extra:
            payload.update(extra)
        if drop:
            for key in drop:
                payload.pop(key, None)
        if inside_repo:
            path = bootstrap.REPO / f".tmp-approval-{secrets.token_hex(4)}.json"
            self.addCleanup(lambda p=path: p.unlink(missing_ok=True))
        else:
            path = self.root / f"approval-{secrets.token_hex(4)}.json"
        path.write_text(json.dumps(payload))
        path.chmod(mode)
        if symlink:
            link = self.root / f"approval-link-{secrets.token_hex(4)}.json"
            link.symlink_to(path)
            return link
        return path

    def _assert_no_apply(self, calls):
        for argv in calls:
            self.assertNotIn("apply", argv)

    def test_m13_apply_refuses_staging_rg_profile_and_missing_manifest(self):
        approval = self._approval("a" * 64, "b" * 64)
        with self.assertRaises(bootstrap.Refused) as missing:
            bootstrap.apply(self.root / "missing-folder", confirm_apply=True, approval_path=approval)
        self.assertIn("0700", str(missing.exception).lower() + "canonical" + str(missing.exception))
        self.prepare()
        manifest = json.loads((self.folder / "manifest.json").read_text())
        manifest["resource_group"] = "".join(["rg-cosmas-os-vm-", "staging", "-eus2-lab01"])
        (self.folder / "manifest.json").write_text(json.dumps(manifest))
        with patch.object(bootstrap, "owner_context") as azure, patch.object(bootstrap, "command") as command, self.assertRaises(bootstrap.Refused) as err:
            bootstrap.apply(self.folder, confirm_apply=True, approval_path=approval)
        azure.assert_not_called()
        command.assert_not_called()
        # Manifest rewrite fails verify (source/namespace/resource_group binding).
        self.assertIn("reviewed", str(err.exception).lower())

    def test_apply_name_guard_refusals_and_malformed_manifest(self):
        plan_sha, summary, _ = self._planned()
        approval = self._approval(plan_sha, summary["summary_sha256"])
        # Staging resource group in manifest after rewriting protected digest is still refused by explicit check.
        manifest_path = self.folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["resource_group"] = "rg-cosmas-os-vm-staging-eus2-lab01"
        # Restore protected digest so _verify_prepared gets past file hash... actually changing
        # manifest content breaks protected digest. Use patch on read_json for resource_group check path:
        with patch.object(bootstrap, "_verify_prepared", return_value=(manifest, {**self.inputs})), patch.object(
            bootstrap, "owner_context"
        ) as azure, patch.object(bootstrap, "command") as command, self.assertRaises(bootstrap.Refused) as err:
            bootstrap.apply(self.folder, confirm_apply=True, approval_path=approval)
        self.assertIn("production", str(err.exception).lower())
        azure.assert_not_called()
        self._assert_no_apply([c.args[0] for c in command.call_args_list] if command.call_args_list else [])
        manifest["resource_group"] = bootstrap.RESOURCE_GROUP
        manifest["profile"] = "cosmabot-vm/eastus2/lab01/local-initial"
        with patch.object(bootstrap, "_verify_prepared", return_value=(manifest, {**self.inputs})), patch.object(
            bootstrap, "owner_context"
        ) as azure, patch.object(bootstrap, "command") as command, self.assertRaises(bootstrap.Refused) as err:
            bootstrap.apply(self.folder, confirm_apply=True, approval_path=approval)
        self.assertIn("namespace", str(err.exception).lower())
        azure.assert_not_called()
        # Malformed / missing plan artifacts
        (self.folder / "plan-summary.json").unlink()
        with patch.object(bootstrap, "owner_context") as azure, patch.object(bootstrap, "command") as command, self.assertRaises(bootstrap.Refused):
            bootstrap.apply(self.folder, confirm_apply=True, approval_path=approval)
        azure.assert_not_called()
        command.assert_not_called()

    def test_apply_refuses_without_confirm_flag(self):
        approval = self._approval("a" * 64, "b" * 64)
        with self.assertRaises(bootstrap.Refused) as err:
            bootstrap.apply(self.folder, confirm_apply=False, approval_path=approval)
        self.assertIn("refusing apply without --confirm-apply", str(err.exception))

    def _refuse_apply(self, approval, *, needle: str):
        with patch.object(bootstrap, "owner_context") as azure, patch.object(
            bootstrap, "command"
        ) as command, patch.object(subprocess, "Popen") as popen, self.assertRaises(
            bootstrap.Refused
        ) as err:
            bootstrap.apply(self.folder, confirm_apply=True, approval_path=approval)
        self.assertNotIsInstance(err.exception, bootstrap.ApplyAttempted)
        self.assertIn(needle, str(err.exception).lower())
        azure.assert_not_called()
        popen.assert_not_called()
        self._assert_no_apply([c.args[0] for c in command.call_args_list])

    def test_approval_binding_refusals(self):
        plan_sha, summary, plan_json = self._planned()
        self._refuse_apply(
            self._approval("0" * 64, summary["summary_sha256"]),
            needle="plan_sha256",
        )
        self._refuse_apply(
            self._approval(plan_sha, "0" * 64),
            needle="summary_sha256",
        )
        self._refuse_apply(
            self._approval(plan_sha, summary["summary_sha256"], inside_repo=True),
            needle="outside",
        )
        self._refuse_apply(
            self._approval(plan_sha, summary["summary_sha256"], mode=0o644),
            needle="ownership or mode",
        )
        self._refuse_apply(
            self._approval(plan_sha, summary["summary_sha256"], symlink=True),
            needle="outside",
        )
        self._refuse_apply(
            self._approval(plan_sha, summary["summary_sha256"], drop=["reviewer"]),
            needle="approval file must contain",
        )
        self._refuse_apply(
            self._approval(plan_sha, summary["summary_sha256"], extra={"note": "nope"}),
            needle="approval file must contain",
        )
        # plan-result hash mismatch
        bad_result = json.loads((self.folder / "plan-result.json").read_text())
        bad_result["plan_sha256"] = "0" * 64
        (self.folder / "plan-result.json").write_text(json.dumps(bad_result))
        (self.folder / "plan-result.json").chmod(0o600)
        self._refuse_apply(
            self._approval(plan_sha, summary["summary_sha256"]),
            needle="plan-result.json",
        )
        # change plan file after review
        plan_sha, summary, plan_json = self._write_plan_artifacts()
        approval = self._approval(plan_sha, summary["summary_sha256"])
        (self.folder / "plans/first.tfplan").write_bytes(b"tampered-after-review")
        (self.folder / "plans/first.tfplan").chmod(0o600)
        self._refuse_apply(approval, needle="plan-result.json")
        # tampered plan-summary.json (body + stored hash diverge from plan-result)
        plan_sha, summary, plan_json = self._write_plan_artifacts()
        approval = self._approval(plan_sha, summary["summary_sha256"])
        summary_path = self.folder / "plan-summary.json"
        tampered = json.loads(summary_path.read_text())
        tampered["create"] = {"azurerm_resource_group": 99}
        tampered["summary_sha256"] = "0" * 64
        summary_path.write_text(json.dumps(tampered))
        summary_path.chmod(0o600)
        self._refuse_apply(approval, needle="plan-summary.json")

    def test_apply_positive_one_tofu_apply_and_recompute(self):
        plan_sha, summary, plan_json = self._planned()
        approval = self._approval(plan_sha, summary["summary_sha256"])
        popen_calls = []

        def run(argv, **kwargs):
            if argv[1] == "version":
                return subprocess.CompletedProcess(argv, 0, b'{"terraform_version":"1.12.5"}', b"")
            if argv[1] == "show":
                return subprocess.CompletedProcess(argv, 0, json.dumps(plan_json).encode(), b"")
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        class FakeProc:
            def __init__(self, argv):
                popen_calls.append(argv)

            def wait(self, timeout=None):
                return 0

            def terminate(self):
                return None

            def kill(self):
                return None

        with patch.object(bootstrap, "owner_context", return_value=self.context), patch.object(
            bootstrap, "command", side_effect=run
        ), patch.object(subprocess, "Popen", side_effect=lambda *a, **k: FakeProc(a[0])):
            result = bootstrap.apply(self.folder, confirm_apply=True, approval_path=approval)
        self.assertTrue(result["applied"])
        self.assertEqual(len(popen_calls), 1)
        self.assertEqual(popen_calls[0][1], "apply")
        self.assertEqual(popen_calls[0][-1], str(self.folder / "plans/first.tfplan"))

    def test_apply_failure_reports_attempted(self):
        plan_sha, summary, plan_json = self._planned()
        approval = self._approval(plan_sha, summary["summary_sha256"])

        def run(argv, **kwargs):
            if argv[1] == "version":
                return subprocess.CompletedProcess(argv, 0, b'{"terraform_version":"1.12.5"}', b"")
            if argv[1] == "show":
                return subprocess.CompletedProcess(argv, 0, json.dumps(plan_json).encode(), b"")
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        class FakeProc:
            def wait(self, timeout=None):
                return 1

            def terminate(self):
                return None

            def kill(self):
                return None

        with patch.object(bootstrap, "owner_context", return_value=self.context), patch.object(
            bootstrap, "command", side_effect=run
        ), patch.object(subprocess, "Popen", return_value=FakeProc()), self.assertRaises(
            bootstrap.ApplyAttempted
        ) as err:
            bootstrap.apply(self.folder, confirm_apply=True, approval_path=approval)
        self.assertIn("attempted", str(err.exception).lower())
        self.assertNotIn("No apply was attempted", str(err.exception))


class EncryptionProof(unittest.TestCase):
    def test_actual_pinned_tofu_encrypts_state_and_plan_and_rejects_wrong_key_or_plaintext(self):
        tofu = shutil.which("tofu")
        self.assertIsNotNone(tofu, "Pinned OpenTofu 1.12.5 is required for this local encryption proof")
        with tempfile.TemporaryDirectory(prefix="cosmabot-tofu-encryption-") as directory:
            root = Path(directory).resolve()
            key = root / "encryption.passphrase"
            bootstrap.write_private(key, (secrets.token_urlsafe(48) + "\n").encode())
            wrong = root / "wrong"
            wrong.mkdir(mode=0o700)
            wrong_key = wrong / "encryption.passphrase"
            bootstrap.write_private(wrong_key, (secrets.token_urlsafe(48) + "\n").encode())
            module = root / "module"
            module.mkdir(mode=0o700)
            bootstrap.write_private(module / "encryption.tf", (MODULE / "encryption.tf").read_bytes())
            marker = "invented-roundtrip-proof-value"
            bootstrap.write_private(module / "main.tf", ('terraform {\n required_version = "= 1.12.5"\n backend "local" {}\n}\nresource "terraform_data" "proof" { input = "' + marker + '" }\noutput "proof" { value = terraform_data.proof.output }\n').encode())
            bootstrap.write_private(root / "backend.hcl", ('path = ' + json.dumps(str(root / "foundation.tfstate")) + '\n').encode())
            env = {key: value for key, value in os.environ.items() if not key.startswith(("TF_", "ARM_"))}
            env.update({"TF_VAR_bootstrap_key_file": str(key), "TF_DATA_DIR": str(root / "tofu-data"), "TF_WORKSPACE": "default", "TF_INPUT": "0", "TF_IN_AUTOMATION": "1"})
            def run(args, changes=None):
                return subprocess.run([tofu, *args], cwd=module, env={**env, **(changes or {})}, stdin=subprocess.DEVNULL, capture_output=True, timeout=60, umask=0o077)
            for args in (["init", "-input=false", "-backend-config=" + str(root / "backend.hcl")],
                         ["plan", "-input=false", "-out=" + str(root / "first.tfplan")],
                         ["apply", "-input=false", "-auto-approve", str(root / "first.tfplan")]):
                result = run(args)
                self.assertEqual(result.returncode, 0, "Local encryption fixture command failed")
            for name in ("first.tfplan", "foundation.tfstate"):
                path = root / name
                bootstrap.ciphertext(path)
                self.assertNotIn(marker.encode(), path.read_bytes())
                clear = run(["show", "-json", str(path)])
                self.assertEqual(clear.returncode, 0)
                self.assertIn(marker.encode(), clear.stdout)
                wrong_result = run(["show", "-json", str(path)], {"TF_VAR_bootstrap_key_file": str(wrong_key)})
                self.assertNotEqual(wrong_result.returncode, 0)
                self.assertNotIn(marker.encode(), wrong_result.stdout)
            plain = root / "deliberately-unencrypted-fixture.tfstate"
            bootstrap.write_private(plain, bootstrap.json_bytes({"version": 4, "terraform_version": "1.12.5", "serial": 1,
                "lineage": "00000000-0000-4000-8000-000000000009", "outputs": {"proof": {"value": marker, "type": "string"}}, "resources": []}))
            self.assertNotEqual(run(["show", "-json", str(plain)]).returncode, 0)
            plain_module = root / "plain-module"
            plain_module.mkdir(mode=0o700)
            bootstrap.write_private(plain_module / "main.tf", (module / "main.tf").read_bytes())
            plain_plan = root / "deliberately-unencrypted-fixture.tfplan"
            for args in (["init", "-input=false"], ["plan", "-input=false", "-out=" + str(plain_plan)]):
                result = subprocess.run([tofu, *args], cwd=plain_module,
                    env={**env, "TF_DATA_DIR": str(root / "plain-data")}, stdin=subprocess.DEVNULL,
                    capture_output=True, timeout=60, umask=0o077)
                self.assertEqual(result.returncode, 0, "Unencrypted local comparison fixture failed")
            refused = run(["show", "-json", str(plain_plan)])
            self.assertNotEqual(refused.returncode, 0)
            self.assertNotIn(marker.encode(), refused.stdout)
            secret = key.read_bytes().strip()
            for path in root.rglob("*"):
                if path.is_file() and path != key:
                    self.assertNotIn(secret, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
