"""No Linux devices, packages, metadata endpoint or cloud resources are touched."""
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
RUNTIME = MODULE.parent / "runtime"
PROD_ROOT = MODULE.parent / "prod"
spec = importlib.util.spec_from_file_location("bootstrap_host", MODULE / "bootstrap_host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)

guards_spec = importlib.util.spec_from_file_location(
    "cosmabot_name_guards_for_host", PROD_ROOT / "name_guards.py"
)
guards = importlib.util.module_from_spec(guards_spec)
assert guards_spec.loader is not None
guards_spec.loader.exec_module(guards)


def _ids_for(profile: str) -> tuple[str, str, str]:
    spec = host.resolve_profile(profile)
    base = (
        "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/"
        + spec["rg"]
    )
    vm = base + "/providers/Microsoft.Compute/virtualMachines/" + spec["vm"]
    disk = base + "/providers/Microsoft.Compute/disks/" + spec["disk"]
    return vm, disk, spec["disk"]


def _parse_systemd_unit(text: str) -> dict[str, dict[str, str]]:
    """Parse active (non-comment) KEY=value lines under [Section] headers."""
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        sections[current][key.strip()] = value.strip()
    return sections


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


class ProdProfileBootstrap(unittest.TestCase):
    """Prod profile accepts only cosmabot-vm-prod-v1 coordinates; cross names refuse."""

    def setUp(self):
        self.now = dt.datetime(2026, 9, 25, 20, tzinfo=dt.timezone.utc)
        self.vm, self.disk, _ = _ids_for(host.PROD_PROFILE)
        self.receipt = {
            "version": 1, "source": "azure-arm-disk-and-vm-get", "profile": host.PROD_PROFILE,
            "vm_id": self.vm, "disk_id": self.disk, "managed_by_vm_id": self.vm,
            "create_option": "Empty", "size_gib": 128, "lun": 0,
            "disk_unique_id": "00000000-0000-4000-8000-000000000012",
            "vm_instance_id": "00000000-0000-4000-8000-000000000013",
            "apply_started_utc": "2026-09-25T19:00:00Z",
            "disk_created_utc": "2026-09-25T19:02:00Z",
            "apply_completed_utc": "2026-09-25T19:05:00Z",
        }

    def test_prod_profile_accepts_exact_prod_receipt(self):
        host.validate_receipt(
            self.receipt, self.vm, self.disk, self.disk, self.now, profile=host.PROD_PROFILE
        )
        spec = host.resolve_profile(host.PROD_PROFILE)
        self.assertEqual(spec["rg"], "rg-cosmabot-prod-eus2-01")
        self.assertEqual(spec["vm"], "vm-cosmabot-prod-eus2-01")
        self.assertEqual(spec["disk"], "data-vm-cosmabot-prod-eus2-01")
        self.assertEqual(spec["unit"], "cosmabot-prod.service")

    def test_prod_unit_and_example_receipt_exist_beside_staging_unit(self):
        staging_unit = RUNTIME / "cosmabot-staging.service"
        prod_unit = RUNTIME / "cosmabot-prod.service"
        example = MODULE / "creation-receipt.prod.example.json"
        self.assertTrue(staging_unit.is_file())
        self.assertTrue(prod_unit.is_file())
        self.assertTrue(example.is_file())
        self.assertIn("CosmaBot synthetic production runtime", prod_unit.read_text())
        self.assertNotEqual(staging_unit.read_bytes(), prod_unit.read_bytes())
        payload = json.loads(example.read_text())
        self.assertEqual(payload["profile"], host.PROD_PROFILE)
        self.assertEqual(payload["source"], "azure-arm-disk-and-vm-get")
        joined = json.dumps(payload)
        self.assertNotRegex(joined, r"/subscriptions/[0-9a-f-]{36}/")
        self.assertIn(host.SECRETS_TRANSPORT_TICKET, joined)

    def test_prod_unit_service_section_hardening_and_runtime_directory(self):
        text = (RUNTIME / "cosmabot-prod.service").read_text()
        parsed = _parse_systemd_unit(text)
        service = parsed["Service"]
        expected = {
            "NoNewPrivileges": "yes",
            "ProtectSystem": "strict",
            "ProtectHome": "yes",
            "PrivateTmp": "yes",
            "ProtectKernelTunables": "yes",
            "ProtectKernelLogs": "yes",
            "ProtectControlGroups": "yes",
            "RestrictSUIDSGID": "yes",
            "LockPersonality": "yes",
            "ReadWritePaths": "/var/lib/cosmabot /run/cosmabot",
            "UMask": "0077",
            "RuntimeDirectory": "cosmabot",
            "RuntimeDirectoryMode": "0700",
            "RuntimeDirectoryPreserve": "yes",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(service.get(key), value)
        self.assertNotIn("User", service)
        self.assertNotIn("PrivateNetwork", service)
        self.assertNotIn("PrivateDevices", service)
        # Dropped: iptables in imds-guard.sh may need xt_* autoload.
        self.assertNotIn("ProtectKernelModules", service)
        self.assertTrue(
            any(
                line.lstrip().startswith("#") and "ProtectKernelModules" in line
                for line in text.splitlines()
            ),
            "omission of ProtectKernelModules must stay documented in a comment",
        )
        # Mutation target: commenting out RuntimeDirectory= would leave parser empty.
        self.assertTrue(
            any(
                line.strip() == "RuntimeDirectory=cosmabot"
                for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
        )
        # Mutation target: dropping RuntimeDirectoryPreserve=yes lets systemd wipe
        # /run/cosmabot (and runtime.lock) on stop/fail/restart.
        self.assertTrue(
            any(
                line.strip() == "RuntimeDirectoryPreserve=yes"
                for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
        )

    def test_protect_home_is_safe_for_start_and_imds_guard_scripts(self):
        # Static proof: neither script references home paths ProtectHome hides.
        for name in ("start.sh", "imds-guard.sh"):
            body = (RUNTIME / name).read_text()
            with self.subTest(script=name):
                self.assertNotRegex(body, r"(?m)(\$HOME|/home/|/root\b|~/)")
        self.assertIn("iptables", (RUNTIME / "imds-guard.sh").read_text())

    def test_host_profile_names_stay_in_parity_with_name_guards(self):
        staging = host.resolve_profile(host.STAGING_PROFILE)
        production = host.resolve_profile(host.PROD_PROFILE)
        self.assertEqual(staging["rg"], guards.STAGING["resource_group"])
        self.assertEqual(staging["vm"], guards.STAGING["vm_name"])
        self.assertEqual(staging["web_host"], guards.STAGING["web_host"])
        self.assertEqual(staging["api_host"], guards.STAGING["api_host"])
        self.assertEqual(production["rg"], guards.PRODUCTION["resource_group"])
        self.assertEqual(production["vm"], guards.PRODUCTION["vm_name"])
        self.assertEqual(production["web_host"], guards.PRODUCTION["web_host"])
        self.assertEqual(production["api_host"], guards.PRODUCTION["api_host"])
        # Cross-refuse needles must include the other side's RG/VM/hosts.
        for needle in (
            guards.STAGING["resource_group"],
            guards.STAGING["vm_name"],
            guards.STAGING["web_host"],
            guards.STAGING["api_host"],
        ):
            self.assertIn(needle.lower(), host.forbidden_needles(host.PROD_PROFILE))
        for needle in (
            guards.PRODUCTION["resource_group"],
            guards.PRODUCTION["vm_name"],
            guards.PRODUCTION["web_host"],
            guards.PRODUCTION["api_host"],
        ):
            self.assertIn(needle.lower(), host.forbidden_needles(host.STAGING_PROFILE))

    def test_default_profile_remains_staging(self):
        self.assertEqual(host.resolve_profile(None)["profile"], host.STAGING_PROFILE)
        self.assertEqual(host.RG, host.PROFILES[host.STAGING_PROFILE]["rg"])
        self.assertEqual(host.VM, host.PROFILES[host.STAGING_PROFILE]["vm"])

    def test_argparse_profile_defaults_to_staging(self):
        staging_vm, staging_disk, _ = _ids_for(host.STAGING_PROFILE)
        argv = [
            "bootstrap_host.py",
            "--vm-id", staging_vm,
            "--disk-id", staging_disk,
            "--expected-device", "/dev/sdc",
            "--creation-receipt", "/tmp/synthetic-receipt.json",
            "--creation-receipt-sha256", "ab" * 32,
        ]
        with patch.object(sys, "argv", argv), patch.object(
            host, "fresh_host", side_effect=host.Refused("stop-after-parse")
        ) as fresh:
            with self.assertRaises(host.Refused) as raised:
                host.main()
        self.assertEqual(str(raised.exception), "stop-after-parse")
        fresh.assert_called_once()

    def test_main_preflight_refuses_cross_environment_before_fresh_host(self):
        staging_vm, staging_disk, _ = _ids_for(host.STAGING_PROFILE)
        argv = [
            "bootstrap_host.py",
            "--profile", host.PROD_PROFILE,
            "--vm-id", staging_vm,
            "--disk-id", staging_disk,
            "--expected-device", "/dev/sdc",
            "--creation-receipt", "/tmp/synthetic-receipt.json",
            "--creation-receipt-sha256", "ab" * 32,
        ]
        with patch.object(sys, "argv", argv), patch.object(host, "fresh_host") as fresh:
            with self.assertRaises(host.Refused) as raised:
                host.main()
        self.assertIn("Cross-environment", str(raised.exception))
        fresh.assert_not_called()

    def test_main_preflight_refuses_staging_name_in_receipt_path_only(self):
        # Prod VM/disk IDs are valid; only the creation-receipt path embeds staging.
        prod_vm, prod_disk, _ = _ids_for(host.PROD_PROFILE)
        receipt_path = (
            "/tmp/review/"
            + host.PROFILES[host.STAGING_PROFILE]["unit"]
            + "/creation-receipt.json"
        )
        argv = [
            "bootstrap_host.py",
            "--profile", host.PROD_PROFILE,
            "--vm-id", prod_vm,
            "--disk-id", prod_disk,
            "--expected-device", "/dev/sdc",
            "--creation-receipt", receipt_path,
            "--creation-receipt-sha256", "ab" * 32,
            "--format-new-empty-disk", prod_disk,
        ]
        with patch.object(sys, "argv", argv), patch.object(host, "fresh_host") as fresh:
            with self.assertRaises(host.Refused) as raised:
                host.main()
        self.assertIn("Cross-environment", str(raised.exception))
        fresh.assert_not_called()

    def test_unknown_profile_is_refused(self):
        with self.assertRaises(host.Refused):
            host.resolve_profile("cosmabot-vm-unknown-v9")

    def test_prod_refuses_staging_resource_group_host_unit_and_profile(self):
        staging_vm, staging_disk, _ = _ids_for(host.STAGING_PROFILE)
        needles = (
            staging_vm,
            staging_disk,
            host.PROFILES[host.STAGING_PROFILE]["unit"],
            host.STAGING_PROFILE,
            host.PROFILES[host.STAGING_PROFILE]["web_host"],
            host.PROFILES[host.STAGING_PROFILE]["api_host"],
            host.PROFILES[host.STAGING_PROFILE]["rg"],
        )
        for needle in needles:
            with self.subTest(needle=needle), self.assertRaises(host.Refused):
                host.refuse_cross_environment(host.PROD_PROFILE, [needle])

    def test_staging_refuses_prod_resource_group_host_unit_and_profile(self):
        needles = (
            self.vm,
            self.disk,
            host.PROFILES[host.PROD_PROFILE]["unit"],
            host.PROD_PROFILE,
            host.PROFILES[host.PROD_PROFILE]["web_host"],
            host.PROFILES[host.PROD_PROFILE]["api_host"],
            host.PROFILES[host.PROD_PROFILE]["rg"],
        )
        for needle in needles:
            with self.subTest(needle=needle), self.assertRaises(host.Refused):
                host.refuse_cross_environment(host.STAGING_PROFILE, [needle])

    def test_prod_validate_receipt_refuses_staging_vm_id(self):
        staging_vm, staging_disk, _ = _ids_for(host.STAGING_PROFILE)
        bad = {**self.receipt, "vm_id": staging_vm, "disk_id": staging_disk,
               "managed_by_vm_id": staging_vm}
        with self.assertRaises(host.Refused):
            host.validate_receipt(
                bad, staging_vm, staging_disk, staging_disk, self.now, profile=host.PROD_PROFILE
            )

    def test_staging_validate_receipt_refuses_prod_vm_id(self):
        with self.assertRaises(host.Refused):
            host.validate_receipt(
                self.receipt, self.vm, self.disk, self.disk, self.now, profile=host.STAGING_PROFILE
            )

    def test_prod_refuses_mismatched_receipt_profile_field(self):
        bad = {**self.receipt, "profile": host.STAGING_PROFILE}
        with self.assertRaises(host.Refused):
            host.validate_receipt(
                bad, self.vm, self.disk, self.disk, self.now, profile=host.PROD_PROFILE
            )

    def test_prod_refuses_non_staging_wrong_receipt_profile_field(self):
        # Mutation target: deleting the explicit profile equality require.
        # Value is not a staging/prod needle, so cross-refuse alone would miss it.
        bad = {**self.receipt, "profile": "cosmabot-vm-other-v1"}
        with self.assertRaises(host.Refused):
            host.validate_receipt(
                bad, self.vm, self.disk, self.disk, self.now, profile=host.PROD_PROFILE
            )

    def test_prod_receipt_without_profile_field_is_refused(self):
        receipt = {key: value for key, value in self.receipt.items() if key != "profile"}
        self.assertNotIn("profile", receipt)
        with self.assertRaises(host.Refused):
            host.validate_receipt(
                receipt, self.vm, self.disk, self.disk, self.now, profile=host.PROD_PROFILE
            )

    def test_staging_receipt_without_profile_field_is_accepted(self):
        staging_vm, staging_disk, _ = _ids_for(host.STAGING_PROFILE)
        receipt = {
            "version": 1, "source": "azure-arm-disk-and-vm-get",
            "vm_id": staging_vm, "disk_id": staging_disk, "managed_by_vm_id": staging_vm,
            "create_option": "Empty", "size_gib": 128, "lun": 0,
            "disk_unique_id": "00000000-0000-4000-8000-000000000022",
            "vm_instance_id": "00000000-0000-4000-8000-000000000023",
            "apply_started_utc": "2026-09-25T19:00:00Z",
            "disk_created_utc": "2026-09-25T19:02:00Z",
            "apply_completed_utc": "2026-09-25T19:05:00Z",
        }
        self.assertNotIn("profile", receipt)
        host.validate_receipt(
            receipt, staging_vm, staging_disk, staging_disk, self.now,
            profile=host.STAGING_PROFILE,
        )

    def test_staging_receipt_with_matching_profile_field_is_accepted(self):
        staging_vm, staging_disk, _ = _ids_for(host.STAGING_PROFILE)
        receipt = {
            "version": 1, "source": "azure-arm-disk-and-vm-get",
            "profile": host.STAGING_PROFILE,
            "vm_id": staging_vm, "disk_id": staging_disk, "managed_by_vm_id": staging_vm,
            "create_option": "Empty", "size_gib": 128, "lun": 0,
            "disk_unique_id": "00000000-0000-4000-8000-000000000024",
            "vm_instance_id": "00000000-0000-4000-8000-000000000025",
            "apply_started_utc": "2026-09-25T19:00:00Z",
            "disk_created_utc": "2026-09-25T19:02:00Z",
            "apply_completed_utc": "2026-09-25T19:05:00Z",
        }
        host.validate_receipt(
            receipt, staging_vm, staging_disk, staging_disk, self.now,
            profile=host.STAGING_PROFILE,
        )

    def test_staging_receipt_with_non_prod_mismatched_profile_is_refused(self):
        # Mutation target: deleting the staging elif profile equality require.
        staging_vm, staging_disk, _ = _ids_for(host.STAGING_PROFILE)
        receipt = {
            "version": 1, "source": "azure-arm-disk-and-vm-get",
            "profile": "cosmabot-vm-other-v1",
            "vm_id": staging_vm, "disk_id": staging_disk, "managed_by_vm_id": staging_vm,
            "create_option": "Empty", "size_gib": 128, "lun": 0,
            "disk_unique_id": "00000000-0000-4000-8000-000000000026",
            "vm_instance_id": "00000000-0000-4000-8000-000000000027",
            "apply_started_utc": "2026-09-25T19:00:00Z",
            "disk_created_utc": "2026-09-25T19:02:00Z",
            "apply_completed_utc": "2026-09-25T19:05:00Z",
        }
        with self.assertRaises(host.Refused):
            host.validate_receipt(
                receipt, staging_vm, staging_disk, staging_disk, self.now,
                profile=host.STAGING_PROFILE,
            )

    def test_prod_receipt_with_staging_unit_field_is_refused(self):
        # Mutation target: deleting the receipt unit equality require.
        # Prod VM/disk IDs are otherwise valid; only the staging unit name must refuse.
        bad = {**self.receipt, "unit": host.PROFILES[host.STAGING_PROFILE]["unit"]}
        with self.assertRaises(host.Refused):
            host.validate_receipt(
                bad, self.vm, self.disk, self.disk, self.now, profile=host.PROD_PROFILE
            )

    def test_receipt_unit_field_uses_equality_not_substring(self):
        # Mutation target: reverting unit check to substring-only cross-env needles
        # would accept a wrong unit that does not embed the other environment name.
        wrong = {**self.receipt, "unit": "cosmabot-other.service"}
        self.assertNotIn(
            host.PROFILES[host.STAGING_PROFILE]["unit"].lower(),
            wrong["unit"].lower(),
        )
        with self.assertRaises(host.Refused):
            host.validate_receipt(
                wrong, self.vm, self.disk, self.disk, self.now, profile=host.PROD_PROFILE
            )
        good = {**self.receipt, "unit": host.PROFILES[host.PROD_PROFILE]["unit"]}
        host.validate_receipt(
            good, self.vm, self.disk, self.disk, self.now, profile=host.PROD_PROFILE
        )

    def test_cross_refuse_catches_embedded_other_environment_name(self):
        # Mutation target: equality-only checks would miss path embeds.
        embedded = "/tmp/review/" + host.PROFILES[host.STAGING_PROFILE]["unit"] + "/notes"
        with self.assertRaises(host.Refused):
            host.refuse_cross_environment(host.PROD_PROFILE, [embedded])
        embedded_prod = "notes-about-" + host.PROD_PROFILE
        with self.assertRaises(host.Refused):
            host.refuse_cross_environment(host.STAGING_PROFILE, [embedded_prod])

    def test_same_environment_names_are_allowed(self):
        host.refuse_cross_environment(
            host.PROD_PROFILE,
            [
                host.PROFILES[host.PROD_PROFILE]["rg"],
                host.PROFILES[host.PROD_PROFILE]["vm"],
                host.PROFILES[host.PROD_PROFILE]["unit"],
                host.PROD_PROFILE,
                host.SECRETS_TRANSPORT_TICKET,
            ],
        )
        host.refuse_cross_environment(
            host.STAGING_PROFILE,
            [
                host.PROFILES[host.STAGING_PROFILE]["rg"],
                host.PROFILES[host.STAGING_PROFILE]["unit"],
                host.STAGING_PROFILE,
            ],
        )

    def test_format_mount_creates_empty_postgres_and_redis_dirs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "var-lib-cosmabot"
            fstab = root / "fstab"
            fstab_before = root / "fstab.cosmabot-before"
            fstab.write_bytes(b"# synthetic-fstab\n")
            fs_uuid = "00000000-0000-4000-8000-000000000099"
            original_path = host.Path
            chowns: list[tuple[str, int, int]] = []

            def path_factory(*args, **kwargs):
                if args and str(args[0]) == "/etc/fstab":
                    return fstab
                if args and str(args[0]) == "/etc/fstab.cosmabot-before":
                    return fstab_before
                return original_path(*args, **kwargs)

            def fake_run(argv, *, allowed=(0,), timeout=120):
                if argv[0] == "mkfs.ext4":
                    return subprocess.CompletedProcess(argv, 0, b"", b"")
                if argv[:4] == ["blkid", "-s", "UUID", "-o"]:
                    return subprocess.CompletedProcess(argv, 0, (fs_uuid + "\n").encode(), b"")
                if argv[0] == "systemctl":
                    return subprocess.CompletedProcess(argv, 0, b"", b"")
                if argv[0] == "mount":
                    data.mkdir(mode=0o700, exist_ok=True)
                    return subprocess.CompletedProcess(argv, 0, b"", b"")
                if argv[0] == "findmnt":
                    payload = {
                        "filesystems": [{
                            "target": str(data),
                            "uuid": fs_uuid,
                            "fstype": "ext4",
                        }]
                    }
                    return subprocess.CompletedProcess(
                        argv, 0, json.dumps(payload).encode(), b""
                    )
                raise AssertionError("unexpected command: " + " ".join(argv))

            def fake_write_new(path, content, mode=0o600):
                path = original_path(path)
                path.write_bytes(content)
                os.chmod(path, mode)

            with patch.object(host, "DATA", data), patch.object(host, "Path", path_factory), \
                 patch.object(host, "check_disk", return_value=7), \
                 patch.object(host, "run", side_effect=fake_run), \
                 patch.object(host, "write_new", side_effect=fake_write_new), \
                 patch.object(host.os, "chown", side_effect=lambda p, u, g: chowns.append(
                     (original_path(p).name, u, g)
                 )):
                got = host.format_mount("/dev/sdc", self.receipt, 7)
            self.assertEqual(got, fs_uuid)
            self.assertTrue((data / "postgres").is_dir())
            self.assertTrue((data / "redis").is_dir())
            self.assertEqual((data / "postgres").stat().st_mode & 0o777, 0o700)
            self.assertEqual((data / "redis").stat().st_mode & 0o777, 0o700)
            self.assertIn(("postgres", 999, 999), chowns)
            self.assertIn(("redis", 999, 999), chowns)


if __name__ == "__main__":
    unittest.main()
