"""Synthetic az fixtures only. No real Azure IDs, secrets, or PHI."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

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
        self.now = dt.datetime(2026, 11, 16, 15, 0, tzinfo=dt.UTC)
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

    def test_writes_sha256_and_prints_root_install_when_not_root(self):
        fake = FakeAz(_vm_payload(), _disk_payload())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
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
            receipt = json.loads(raw)
            host.validate_receipt(
                receipt, self.vm_id, self.disk_id, self.disk_id, self.now,
                profile=self.profile,
            )

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

    def test_az_runner_refuses_write_verb(self):
        with self.assertRaises(builder.Stop) as ctx:
            builder.default_az_runner(["az", "vm", "create", "-g", "x", "-n", "y"])
        self.assertIn("Refused non-read az verb", str(ctx.exception))

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

    def test_root_uid_sets_mode_0600(self):
        if os.geteuid() != 0:
            self.skipTest("mode/owner check for uid 0 requires a root-capable harness")
        fake = FakeAz(_vm_payload(), _disk_payload())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            code = builder.main(
                ["--profile", self.profile, "--out-dir", str(out)],
                runner=fake,
                now=self.now,
                uid=0,
            )
            self.assertEqual(code, 0)
            mode = out.joinpath("creation-receipt.json").stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
