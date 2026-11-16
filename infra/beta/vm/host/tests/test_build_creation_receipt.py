"""Synthetic az fixtures only. No real Azure IDs, secrets, or PHI."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "build_creation_receipt", MODULE / "build_creation_receipt.py"
)
builder = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules[_spec.name] = builder
_spec.loader.exec_module(builder)

_host_spec = importlib.util.spec_from_file_location(
    "bootstrap_host_receipt_rt", MODULE / "bootstrap_host.py"
)
host = importlib.util.module_from_spec(_host_spec)
assert _host_spec.loader is not None
sys.modules[_host_spec.name] = host
_host_spec.loader.exec_module(host)


def _synthetic_ids(profile: str) -> tuple[str, str, str, str]:
    spec = host.resolve_profile(profile)
    sub = "00000000-0000-4000-8000-0000000000aa"
    base = f"/subscriptions/{sub}/resourceGroups/{spec['rg']}"
    vm_id = f"{base}/providers/Microsoft.Compute/virtualMachines/{spec['vm']}"
    disk_id = f"{base}/providers/Microsoft.Compute/disks/{spec['disk']}"
    return vm_id, disk_id, "00000000-0000-4000-8000-0000000000bb", "00000000-0000-4000-8000-0000000000cc"


def _vm_payload(
    *,
    profile: str = host.PROD_PROFILE,
    lun: int = 0,
    extra_disks: list[dict] | None = None,
    vm_time_created: str | None = "2026-11-16T14:00:00Z",
    disk_id: str | None = None,
    vm_id: str | None = None,
    vm_instance_id: str | None = None,
    omit_vm_id: bool = False,
) -> dict:
    vid, did, vmuuid, _ = _synthetic_ids(profile)
    vm_id = vm_id or vid
    disk_id = disk_id or did
    vm_instance_id = vm_instance_id or vmuuid
    disks = [{
        "lun": lun,
        "managedDisk": {"id": disk_id, "storageAccountType": "StandardSSD_LRS"},
        "diskSizeGB": 128,
    }]
    if extra_disks:
        disks.extend(extra_disks)
    payload = {
        "id": vm_id,
        "name": host.resolve_profile(profile)["vm"],
        "vmId": None if omit_vm_id else vm_instance_id,
        "storageProfile": {"dataDisks": disks},
    }
    if vm_time_created is not None:
        payload["timeCreated"] = vm_time_created
    return payload


def _disk_payload(
    *,
    profile: str = host.PROD_PROFILE,
    create_option: str = "Empty",
    size_gib: int = 128,
    time_created: str = "2026-11-16T14:05:00Z",
    managed_by: str | None = None,
    disk_id: str | None = None,
    unique_id: str | None = None,
    omit_unique_id: bool = False,
    omit_time_created: bool = False,
) -> dict:
    vid, did, _, duuid = _synthetic_ids(profile)
    payload = {
        "id": disk_id or did,
        "name": host.resolve_profile(profile)["disk"],
        "managedBy": managed_by if managed_by is not None else vid,
        "diskSizeGb": size_gib,
        "creationData": {"createOption": create_option},
        "uniqueId": None if omit_unique_id else (unique_id or duuid),
    }
    if not omit_time_created:
        payload["timeCreated"] = time_created
    return payload


class FakeAz:
    def __init__(self, vm: dict, disk: dict):
        self.vm = vm
        self.disk = disk
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> dict:
        self.calls.append(list(argv))
        if argv[1:3] == ["vm", "show"]:
            return copy.deepcopy(self.vm)
        if argv[1:3] == ["disk", "show"]:
            return copy.deepcopy(self.disk)
        raise builder.Stop(f"unexpected az argv: {argv}")


class BuildCreationReceiptTests(unittest.TestCase):
    def setUp(self):
        # Prefer timezone.utc over the 3.11+ UTC alias so stock macOS python3 (3.9) works.
        self.now = dt.datetime(2026, 11, 16, 15, 0, tzinfo=dt.timezone.utc)  # noqa: UP017
        self.profile = host.PROD_PROFILE
        self.vm_id, self.disk_id, self.vm_uuid, self.disk_uuid = _synthetic_ids(self.profile)

    def test_round_trip_passes_bootstrap_validate_receipt(self):
        fake = FakeAz(_vm_payload(), _disk_payload())
        receipt = builder.build_receipt(
            profile=self.profile, runner=fake, now=self.now
        )
        # Call the real validator (not a copy).
        host.validate_receipt(
            receipt, self.vm_id, self.disk_id, self.disk_id, self.now,
            profile=self.profile,
        )
        self.assertEqual(receipt["create_option"], "Empty")
        self.assertEqual(receipt["size_gib"], 128)
        self.assertEqual(receipt["lun"], 0)
        self.assertEqual(receipt["apply_started_utc"], "2026-11-16T14:00:00Z")
        self.assertEqual(receipt["disk_created_utc"], "2026-11-16T14:05:00Z")
        self.assertEqual(receipt["apply_completed_utc"], "2026-11-16T14:05:00Z")
        self.assertEqual(receipt["source"], "azure-arm-disk-and-vm-get")
        self.assertEqual(receipt["version"], 1)
        self.assertEqual(receipt["profile"], self.profile)
        # Only read-only az show calls.
        self.assertEqual([c[1:3] for c in fake.calls], [["vm", "show"], ["disk", "show"]])

    def test_prewrite_validate_receipt_refusal_writes_nothing(self):
        # Mutation: deleting the pre-write validate_receipt call must make this fail.
        fake = FakeAz(_vm_payload(), _disk_payload())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                builder,
                "validate_receipt",
                side_effect=builder.Refused("synthetic refusal"),
            ):
                code = builder.main(
                    ["--profile", self.profile, "--out-dir", str(out)],
                    runner=fake,
                    now=self.now,
                    uid=501,
                )
            self.assertEqual(code, 1)
            self.assertFalse((out / "creation-receipt.json").exists())
            self.assertFalse((out / "creation-receipt.sha256").exists())

    def test_writes_sha256_and_prints_root_install_when_not_root(self):
        fake = FakeAz(_vm_payload(), _disk_payload())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                code = builder.main(
                    ["--profile", self.profile, "--out-dir", str(out)],
                    runner=fake,
                    now=self.now,
                    uid=501,  # non-root (macOS-style)
                )
            self.assertEqual(code, 0)
            receipt_path = out / "creation-receipt.json"
            sha_path = out / "creation-receipt.sha256"
            raw = receipt_path.read_bytes()
            digest = sha_path.read_text(encoding="utf-8").strip()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
            mode = stat.S_IMODE(receipt_path.stat().st_mode)
            self.assertEqual(mode, 0o600)
            printed = stdout.getvalue()
            self.assertIn("NOTE: this workstation is not root", printed)
            self.assertIn("sudo install -o root -g root -m 0600", printed)
            self.assertIn(digest, printed)
            receipt = json.loads(raw)
            host.validate_receipt(
                receipt, self.vm_id, self.disk_id, self.disk_id, self.now,
                profile=self.profile,
            )

    def test_root_uid_sets_owner_and_mode_0600_under_permissive_umask(self):
        """Prove 0600 comes from explicit chmod, not umask; owner via chown."""
        fake = FakeAz(_vm_payload(), _disk_payload())
        receipt = builder.build_receipt(
            profile=self.profile, runner=fake, now=self.now
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipt_path = out / "creation-receipt.json"
            sha_path = out / "creation-receipt.sha256"
            previous_umask = os.umask(0o000)

            def permissive_umask(_mask: int) -> int:
                # Ignore the code's restrictive umask so mode must come from chmod.
                return 0o000

            real_lstat = os.lstat

            def lstat_as_root(path):
                st = real_lstat(path)
                return os.stat_result((
                    st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                    0, 0, st.st_size, st.st_atime, st.st_mtime, st.st_ctime,
                ))

            try:
                with (
                    patch("os.umask", side_effect=permissive_umask),
                    patch("os.chown") as mock_chown,
                    patch("os.lstat", side_effect=lstat_as_root),
                ):
                    digest = builder.write_receipt_files(
                        receipt,
                        receipt_path=receipt_path,
                        sha256_path=sha_path,
                        uid=0,
                    )
            finally:
                os.umask(previous_umask)

            self.assertEqual(len(digest), 64)
            mode = stat.S_IMODE(receipt_path.stat().st_mode)
            self.assertEqual(mode, 0o600)
            mock_chown.assert_any_call(receipt_path, 0, 0)
            mock_chown.assert_any_call(sha_path, 0, 0)

    def test_stop_multiple_data_disks(self):
        extra = [{
            "lun": 1,
            "managedDisk": {
                "id": self.disk_id + "-other",
                "storageAccountType": "StandardSSD_LRS",
            },
        }]
        fake = FakeAz(_vm_payload(extra_disks=extra), _disk_payload())
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("Multiple data disks", str(ctx.exception))

    def test_stop_wrong_lun(self):
        fake = FakeAz(_vm_payload(lun=1), _disk_payload())
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("LUN is 1", str(ctx.exception))

    def test_stop_create_option_not_empty(self):
        fake = FakeAz(_vm_payload(), _disk_payload(create_option="Copy"))
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("createOption is 'Copy'", str(ctx.exception))

    def test_stop_wrong_size(self):
        fake = FakeAz(_vm_payload(), _disk_payload(size_gib=64))
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("64 GiB", str(ctx.exception))

    def test_stop_missing_field_disk_time_created(self):
        fake = FakeAz(_vm_payload(), _disk_payload(omit_time_created=True))
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("disk.timeCreated", str(ctx.exception))

    def test_stop_missing_field_vm_instance_id(self):
        fake = FakeAz(_vm_payload(omit_vm_id=True), _disk_payload())
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("vm.vmId", str(ctx.exception))

    def test_stop_disk_id_mismatch(self):
        wrong_disk = self.disk_id + "-other"
        fake = FakeAz(
            _vm_payload(disk_id=wrong_disk),
            _disk_payload(disk_id=wrong_disk),
        )
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("does not match the selected profile data disk", str(ctx.exception))

    def test_stop_cross_environment_staging_id_under_prod(self):
        staging_vm, staging_disk, _, _ = _synthetic_ids(host.STAGING_PROFILE)
        fake = FakeAz(
            _vm_payload(vm_id=staging_vm, disk_id=staging_disk),
            _disk_payload(disk_id=staging_disk, managed_by=staging_vm),
        )
        with self.assertRaises((builder.Stop, builder.Refused)) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        message = str(ctx.exception).lower()
        self.assertIn("cross-environment", message)

    def test_stop_vm_id_pattern_mismatch(self):
        bad_vm = self.vm_id.replace("vm-cosmabot-prod-eus2-01", "vm-cosmabot-other-eus2-01")
        fake = FakeAz(
            _vm_payload(vm_id=bad_vm),
            _disk_payload(managed_by=bad_vm),
        )
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("does not match the selected profile VM identity", str(ctx.exception))

    def test_stop_managed_by_mismatch(self):
        fake = FakeAz(
            _vm_payload(),
            _disk_payload(managed_by=self.vm_id + "-other"),
        )
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("disk.managedBy does not match vm.id", str(ctx.exception))

    def test_stop_receipt_just_past_24h(self):
        started = "2026-11-15T14:59:00Z"  # 24h + 1m before self.now (15:00)
        fake = FakeAz(
            _vm_payload(vm_time_created=started),
            _disk_payload(time_created="2026-11-15T15:00:00Z"),
        )
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("older than 24 hours", str(ctx.exception))

    def test_accepts_receipt_just_inside_24h(self):
        started = "2026-11-15T15:01:00Z"  # 24h - 1m before self.now
        fake = FakeAz(
            _vm_payload(vm_time_created=started),
            _disk_payload(time_created="2026-11-15T15:02:00Z"),
        )
        receipt = builder.build_receipt(
            profile=self.profile, runner=fake, now=self.now
        )
        self.assertEqual(receipt["apply_started_utc"], started)
        host.validate_receipt(
            receipt, self.vm_id, self.disk_id, self.disk_id, self.now,
            profile=self.profile,
        )

    def test_stop_future_apply_started(self):
        future = "2026-11-16T16:00:00Z"  # after self.now
        fake = FakeAz(
            _vm_payload(vm_time_created=future),
            _disk_payload(time_created=future),
        )
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("in the future", str(ctx.exception))

    def test_vm_time_created_absent_uses_disk_only(self):
        fake = FakeAz(
            _vm_payload(vm_time_created=None),
            _disk_payload(time_created="2026-11-16T14:05:00Z"),
        )
        receipt = builder.build_receipt(
            profile=self.profile, runner=fake, now=self.now
        )
        self.assertEqual(receipt["apply_started_utc"], "2026-11-16T14:05:00Z")
        self.assertEqual(receipt["disk_created_utc"], "2026-11-16T14:05:00Z")
        self.assertEqual(receipt["apply_completed_utc"], "2026-11-16T14:05:00Z")
        host.validate_receipt(
            receipt, self.vm_id, self.disk_id, self.disk_id, self.now,
            profile=self.profile,
        )

    def test_stop_receipt_older_than_24h(self):
        old = "2026-11-14T14:00:00Z"
        fake = FakeAz(
            _vm_payload(vm_time_created=old),
            _disk_payload(time_created="2026-11-14T14:05:00Z"),
        )
        with self.assertRaises(builder.Stop) as ctx:
            builder.build_receipt(profile=self.profile, runner=fake, now=self.now)
        self.assertIn("older than 24 hours", str(ctx.exception))

    def test_main_nonzero_on_stop(self):
        fake = FakeAz(_vm_payload(lun=1), _disk_payload())
        with tempfile.TemporaryDirectory() as tmp:
            code = builder.main(
                ["--profile", self.profile, "--out-dir", tmp],
                runner=fake,
                now=self.now,
                uid=501,
            )
        self.assertEqual(code, 1)

    def test_mac_stock_python39_uses_timezone_utc_not_datetime_UTC(self):
        """Fail if the 3.11+ UTC alias is reintroduced — stock macOS python3 is 3.9."""
        source = Path(builder.__file__).read_text(encoding="utf-8")
        # Drop comments so this pin targets call sites only.
        code = re.sub(r"#.*", "", source)
        self.assertIn("dt.timezone.utc", code)
        self.assertNotIn("dt.UTC", code)
        self.assertNotIn("datetime.UTC", code)
        aware = dt.datetime.now(dt.timezone.utc)  # noqa: UP017
        self.assertIsNotNone(aware.tzinfo)

    def test_az_runner_requires_argv0_az(self):
        with self.assertRaises(builder.Stop) as ctx:
            builder.default_az_runner(["azure", "vm", "show", "-g", "x", "-n", "y"])
        self.assertIn("refused non-az argv", str(ctx.exception).lower())

    def test_az_allowlist_refuses_verbs_absent_from_denylist(self):
        """Fail if the argv[2] allowlist layer is deleted.

        These verbs are NOT in _AZ_WRITE_VERBS, so only Layer B (allowlist) stops them.
        """
        for argv in (
            ["az", "disk", "grant-access", "-g", "x", "-n", "y", "--duration-in-seconds", "1"],
            ["az", "vm", "open-port", "-g", "x", "-n", "y", "--port", "22"],
            ["az", "vm", "generalize", "-g", "x", "-n", "y"],
        ):
            with self.subTest(argv=argv):
                self.assertNotIn(argv[2].lower(), builder._AZ_WRITE_VERBS)
                with self.assertRaises(builder.Stop) as ctx:
                    builder.default_az_runner(argv)
                # Allowlist message names group+verb (denylist message names the token only).
                self.assertIn(f"Refused non-read az verb: az {argv[1]} {argv[2]}", str(ctx.exception))

    def test_az_denylist_refuses_write_token_when_argv2_is_read_verb(self):
        """Fail if the denylist layer is deleted.

        argv[2] is an allowed read verb, so Layer B passes; a denylisted token
        later in argv is what Layer A alone must refuse.
        """
        argv = ["az", "vm", "show", "-g", "x", "-n", "y", "delete"]
        self.assertIn(argv[2].lower(), builder._AZ_READ_VERBS)
        self.assertIn("delete", builder._AZ_WRITE_VERBS)
        with self.assertRaises(builder.Stop) as ctx:
            builder.default_az_runner(argv)
        self.assertIn("Refused non-read az verb in argv: delete", str(ctx.exception))

    def test_az_denylist_refuses_vm_delete_and_disk_update(self):
        # Also covered when argv[2] itself is denylisted (both layers would refuse;
        # denylist message fires first).
        for argv in (
            ["az", "vm", "delete", "-g", "x", "-n", "y", "--yes"],
            ["az", "disk", "update", "-g", "x", "-n", "y"],
            ["az", "vm", "run-command", "invoke", "-g", "x", "-n", "y"],
        ):
            with self.subTest(argv=argv):
                with self.assertRaises(builder.Stop) as ctx:
                    builder.default_az_runner(argv)
                self.assertIn("Refused non-read az verb in argv:", str(ctx.exception))

    def test_az_runner_refuses_write_verb(self):
        with self.assertRaises(builder.Stop) as ctx:
            builder.default_az_runner(["az", "vm", "create", "-g", "x", "-n", "y"])
        self.assertIn("Refused non-read az verb", str(ctx.exception))

    def test_az_failure_output_capped_to_first_stderr_line_200_chars(self):
        line1 = "E" * 250
        line2 = "SECOND LINE MUST NEVER APPEAR"
        completed = subprocess.CompletedProcess(
            args=["az", "vm", "show"],
            returncode=1,
            stdout="",
            stderr=line1 + "\n" + line2 + "\n",
        )
        with patch("subprocess.run", return_value=completed):
            with self.assertRaises(builder.Stop) as ctx:
                builder.default_az_runner(
                    ["az", "vm", "show", "--resource-group", "rg", "--name", "vm", "-o", "json"]
                )
        message = str(ctx.exception)
        self.assertNotIn(line2, message)
        self.assertNotIn("E" * 201, message)
        self.assertIn("E" * 200, message)
        self.assertEqual(message.count("E"), 200)

    def test_root_lstat_fail_closed_stops(self):
        fake = FakeAz(_vm_payload(), _disk_payload())
        receipt = builder.build_receipt(
            profile=self.profile, runner=fake, now=self.now
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            receipt_path = out / "creation-receipt.json"
            sha_path = out / "creation-receipt.sha256"
            real_lstat = os.lstat

            def lstat_wrong_owner(path):
                st = real_lstat(path)
                # uid 501 → fail-closed (must be root-owned).
                return os.stat_result((
                    st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                    501, 0, st.st_size, st.st_atime, st.st_mtime, st.st_ctime,
                ))

            with (
                patch("os.chown"),
                patch("os.lstat", side_effect=lstat_wrong_owner),
                self.assertRaises(builder.Stop) as ctx,
            ):
                builder.write_receipt_files(
                    receipt,
                    receipt_path=receipt_path,
                    sha256_path=sha_path,
                    uid=0,
                )
            self.assertIn("Failed to write a private root-owned receipt file", str(ctx.exception))

    def test_az_runner_subprocess_shell_false_list_argv_and_secret_env_dropped(self):
        captured: dict = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout="{}", stderr=""
            )

        poisoned = {
            "HOME": "/tmp/synthetic-home",
            "PATH": "/usr/bin",
            "AZURE_CLIENT_SECRET": "synthetic-secret-value",
            "AZURE_CLIENT_ID": "synthetic-client-id",
            "AZURE_TENANT_ID": "synthetic-tenant-id",
            "AZURE_SUBSCRIPTION_ID": "00000000-0000-4000-8000-0000000000aa",
        }
        with (
            patch.dict(os.environ, poisoned, clear=False),
            patch("subprocess.run", side_effect=fake_run) as run_mock,
        ):
            payload = builder.default_az_runner(
                ["az", "vm", "show", "--resource-group", "rg", "--name", "vm", "-o", "json"]
            )
        self.assertEqual(payload, {})
        run_mock.assert_called_once()
        argv = captured["argv"]
        kwargs = captured["kwargs"]
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[0], "az")
        self.assertIs(kwargs.get("shell"), False)
        env = kwargs["env"]
        self.assertNotIn("AZURE_CLIENT_SECRET", env)
        self.assertNotIn("AZURE_CLIENT_ID", env)
        self.assertNotIn("AZURE_TENANT_ID", env)
        self.assertEqual(env.get("AZURE_SUBSCRIPTION_ID"), poisoned["AZURE_SUBSCRIPTION_ID"])
        self.assertEqual(env.get("HOME"), poisoned["HOME"])

    def test_az_subprocess_env_helper_drops_secrets(self):
        source = {
            "HOME": "/tmp/x",
            "PATH": "/bin",
            "AZURE_CLIENT_SECRET": "nope",
            "AZURE_CLIENT_ID": "nope",
            "AZURE_TENANT_ID": "nope",
        }
        env = builder.az_subprocess_env(source)
        self.assertEqual(env["HOME"], "/tmp/x")
        self.assertNotIn("AZURE_CLIENT_SECRET", env)
        self.assertNotIn("AZURE_CLIENT_ID", env)
        self.assertNotIn("AZURE_TENANT_ID", env)

    def test_timestamp_provenance_uses_earliest_and_latest_time_created(self):
        # Disk created before VM: started=disk, completed=vm.
        fake = FakeAz(
            _vm_payload(vm_time_created="2026-11-16T14:10:00Z"),
            _disk_payload(time_created="2026-11-16T14:01:00Z"),
        )
        receipt = builder.build_receipt(
            profile=self.profile, runner=fake, now=self.now
        )
        self.assertEqual(receipt["apply_started_utc"], "2026-11-16T14:01:00Z")
        self.assertEqual(receipt["disk_created_utc"], "2026-11-16T14:01:00Z")
        self.assertEqual(receipt["apply_completed_utc"], "2026-11-16T14:10:00Z")
        host.validate_receipt(
            receipt, self.vm_id, self.disk_id, self.disk_id, self.now,
            profile=self.profile,
        )


if __name__ == "__main__":
    unittest.main()
