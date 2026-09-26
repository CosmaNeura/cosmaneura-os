"""No Linux devices, packages, metadata endpoint or cloud resources are touched."""
import copy
import datetime as dt
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap_host", MODULE / "bootstrap_host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class NewHostRefusals(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 9, 25, 20, tzinfo=dt.timezone.utc)
        base = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/" + host.RG
        self.vm = base + "/providers/Microsoft.Compute/virtualMachines/" + host.VM
        self.disk = base + "/providers/Microsoft.Compute/disks/" + host.DISK
        self.receipt = {
            "version": 1, "source": "azure-arm-disk-and-vm-get", "vm_id": self.vm,
            "disk_id": self.disk, "managed_by_vm_id": self.vm, "create_option": "Empty",
            "size_gib": 128, "lun": 0, "disk_unique_id": "00000000-0000-4000-8000-000000000002",
            "vm_instance_id": "00000000-0000-4000-8000-000000000003",
            "apply_started_utc": "2026-09-25T19:00:00Z",
            "disk_created_utc": "2026-09-25T19:02:00Z",
            "apply_completed_utc": "2026-09-25T19:05:00Z",
        }
        self.metadata = {
            "resourceId": self.vm, "vmId": self.receipt["vm_instance_id"], "location": "eastus2",
            "vmSize": "Standard_D2s_v5", "storageProfile": {"dataDisks": [{
                "lun": "0", "diskSizeGB": "128", "isSharedDisk": "false",
                "managedDisk": {"id": self.disk, "storageAccountType": "StandardSSD_LRS"},
            }]},
        }
        self.topology = {"blockdevices": [{"name": "/dev/sdc", "type": "disk", "size": host.SIZE,
            "fstype": None, "mountpoints": [None], "ro": False, "pkname": None}]}

    def test_exact_new_disk_chain_is_accepted(self):
        host.validate_receipt(self.receipt, self.vm, self.disk, self.disk, self.now)
        host.validate_metadata(self.metadata, self.receipt)
        host.validate_topology(self.topology, "/dev/sdc")

    def test_metadata_accepts_empty_or_absent_shared_flag(self):
        for absent in (False, True):
            value = copy.deepcopy(self.metadata)
            disk = value["storageProfile"]["dataDisks"][0]
            disk["isSharedDisk"] = ""
            if absent:
                del disk["isSharedDisk"]
            with self.subTest(absent=absent):
                host.validate_receipt(self.receipt, self.vm, self.disk, self.disk, self.now)
                host.validate_metadata(value, self.receipt)

    def test_formatting_needs_explicit_exact_disk_opt_in(self):
        for approval in (None, "yes", self.disk + "-other"):
            with self.subTest(approval=approval), self.assertRaises(host.Refused):
                host.validate_receipt(self.receipt, self.vm, self.disk, approval, self.now)

    def test_receipt_refuses_old_copied_wrong_sized_or_differently_attached_disk(self):
        changed = {"create_option": "Copy", "managed_by_vm_id": self.vm + "-old",
                   "disk_id": self.disk + "-old", "size_gib": 64, "lun": 1,
                   "disk_unique_id": "", "vm_instance_id": "", "source": "operator-guess"}
        for field, value in changed.items():
            with self.subTest(field=field), self.assertRaises(host.Refused):
                host.validate_receipt({**self.receipt, field: value}, self.vm, self.disk, self.disk, self.now)

    def test_creation_must_be_in_the_recent_completed_apply(self):
        for field, value in (("disk_created_utc", "2026-09-25T18:59:00Z"),
                             ("disk_created_utc", "2026-09-25T19:06:00Z"),
                             ("apply_completed_utc", "2026-09-25T20:10:00Z"),
                             ("apply_started_utc", "2026-09-23T19:00:00Z"),
                             ("disk_created_utc", "2026-09-25T19:02:00")):
            with self.subTest(field=field, value=value), self.assertRaises(host.Refused):
                host.validate_receipt({**self.receipt, field: value}, self.vm, self.disk, self.disk, self.now)

    def test_metadata_refuses_wrong_host_disk_lun_size_or_extra_disk(self):
        bad = []
        for field, value in (("resourceId", self.vm + "-old"), ("vmId", "other"), ("location", "centralus")):
            bad.append({**self.metadata, field: value})
        for field, value in (("lun", "1"), ("diskSizeGB", "64"), ("isSharedDisk", "true"),
                             ("isSharedDisk", "unknown"), ("isSharedDisk", None),
                             ("managedDisk", {"id": self.disk + "-old", "storageAccountType": "StandardSSD_LRS"})):
            item = copy.deepcopy(self.metadata)
            item["storageProfile"]["dataDisks"][0][field] = value
            bad.append(item)
        extra = copy.deepcopy(self.metadata)
        extra["storageProfile"]["dataDisks"].append(extra["storageProfile"]["dataDisks"][0])
        bad.append(extra)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(host.Refused):
                host.validate_metadata(value, self.receipt)

    def test_local_disk_rejects_existing_filesystem_partition_mount_or_readonly_device(self):
        for field, value in (("fstype", "ext4"), ("children", [{"name": "/dev/sdc1"}]),
                             ("mountpoints", ["/"]), ("ro", True), ("size", 64 * 1024**3),
                             ("type", "part"), ("pkname", "/dev/sda")):
            item = copy.deepcopy(self.topology)
            item["blockdevices"][0][field] = value
            with self.subTest(field=field), self.assertRaises(host.Refused):
                host.validate_topology(item, "/dev/sdc")

    def test_changed_device_is_refused_before_mkfs(self):
        with patch.object(host, "check_disk", return_value=99), patch.object(host, "run") as command:
            with self.assertRaises(host.Refused):
                host.format_mount("/dev/sdc", self.receipt, 98)
        command.assert_not_called()

    def test_private_and_public_files_have_intended_modes_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_mask = os.umask(0o077)
            try:
                for name, mode in (("private", 0o600), ("public-signing-key", 0o644), ("policy", 0o755)):
                    path = root / name
                    host.write_new(path, b"invented-fixture", mode)
                    self.assertEqual(path.stat().st_mode & 0o777, mode)
                    with self.assertRaises(FileExistsError):
                        host.write_new(path, b"overwrite-refused", mode)
            finally:
                os.umask(old_mask)


if __name__ == "__main__":
    unittest.main()
