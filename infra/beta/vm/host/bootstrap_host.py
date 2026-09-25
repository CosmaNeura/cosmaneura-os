#!/usr/bin/env python3
"""Prepare only the newly created CosmaBot Ubuntu host; never start containers."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import urllib.request

RG = "rg-cosmas-os-vm-staging-eus2-lab01"
VM = "vm-cosmabot-staging-eus2-lab01"
DISK = "data-" + VM
SIZE = 128 * 1024**3
LUN = Path("/dev/disk/azure/scsi1/lun0")
DATA = Path("/var/lib/cosmabot")
LOG = Path("/var/log/cosmabot-host-bootstrap.log")
PACKAGES = {
    "docker-ce": "5:29.8.1-1~ubuntu.22.04~jammy",
    "docker-ce-cli": "5:29.8.1-1~ubuntu.22.04~jammy",
    "containerd.io": "2.3.6-1~ubuntu.22.04~jammy",
    "docker-compose-plugin": "5.5.1-1~ubuntu.22.04~jammy",
}
KEY_SHA256 = "1500c1f56fa9e26b9b8f42452a553675796ade0807cdce11975eb98170b3a570"
POLICY = b"#!/bin/sh\n# Temporary CosmaBot bootstrap: do not start services during package installation.\nexit 101\n"
ENV = {key: os.environ[key] for key in ("HOME",) if key in os.environ}
ENV.update({"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "DEBIAN_FRONTEND": "noninteractive"})


class Refused(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Refused(reason)


def timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "Creation times must include a timezone")
    return parsed


def validate_receipt(value: dict, vm_id: str, disk_id: str, approval: str | None,
                     now: dt.datetime) -> None:
    require(isinstance(value, dict), "Creation receipt must be an object")
    vm_pattern = rf"/subscriptions/[0-9a-f-]{{36}}/resourceGroups/{RG}/providers/Microsoft.Compute/virtualMachines/{VM}"
    require(re.fullmatch(vm_pattern, vm_id, re.I) is not None, "Unexpected VM identity")
    expected_disk = vm_id.rsplit("/providers/", 1)[0] + "/providers/Microsoft.Compute/disks/" + DISK
    require(disk_id.lower() == expected_disk.lower(), "Unexpected data disk identity")
    require(approval == disk_id, "Explicit formatting approval must repeat the exact new disk ID")
    require(value.get("version") == 1 and value.get("source") == "azure-arm-disk-and-vm-get",
            "A current ARM creation receipt is required")
    require(value.get("vm_id", "").lower() == vm_id.lower()
            and value.get("disk_id", "").lower() == disk_id.lower()
            and value.get("managed_by_vm_id", "").lower() == vm_id.lower(),
            "Creation receipt belongs to a different disk or VM")
    require(value.get("create_option") == "Empty" and value.get("size_gib") == 128
            and value.get("lun") == 0, "Only the new Empty 128 GiB LUN 0 disk is accepted")
    require(re.fullmatch(r"[0-9a-f-]{36}", value.get("disk_unique_id", ""), re.I) is not None
            and re.fullmatch(r"[0-9a-f-]{36}", value.get("vm_instance_id", ""), re.I) is not None,
            "Unique disk and VM instance identifiers are required")
    started = timestamp(value["apply_started_utc"])
    created = timestamp(value["disk_created_utc"])
    completed = timestamp(value["apply_completed_utc"])
    require(started <= created <= completed <= now + dt.timedelta(minutes=1)
            and dt.timedelta(0) <= now - started <= dt.timedelta(hours=24),
            "Disk creation must belong to this recent completed apply")


def validate_metadata(value: dict, receipt: dict) -> None:
    require(value.get("resourceId", "").lower() == receipt["vm_id"].lower()
            and value.get("vmId", "").lower() == receipt["vm_instance_id"].lower()
            and value.get("location") == "eastus2"
            and value.get("vmSize") == "Standard_D2s_v5", "IMDS does not identify the approved new host")
    disks = value.get("storageProfile", {}).get("dataDisks", [])
    require(len(disks) == 1, "Exactly one data disk must be attached")
    disk = disks[0]
    # IMDS returns an empty shared-disk flag on this ARM-verified nonshared disk.
    require(str(disk.get("lun")) == "0" and str(disk.get("diskSizeGB")) == "128"
            and disk.get("managedDisk", {}).get("id", "").lower() == receipt["disk_id"].lower()
            and disk.get("managedDisk", {}).get("storageAccountType") == "StandardSSD_LRS"
            and str(disk.get("isSharedDisk", "false")).lower() in {"false", ""},
            "IMDS data disk does not match the creation receipt")


def validate_topology(value: dict, device: str) -> None:
    disks = value.get("blockdevices", [])
    require(len(disks) == 1, "Ambiguous local data disk")
    disk = disks[0]
    require(disk.get("name") == device and disk.get("type") == "disk"
            and int(disk.get("size", 0)) == SIZE and not disk.get("ro")
            and not disk.get("pkname") and not disk.get("children")
            and not disk.get("fstype") and not any(disk.get("mountpoints") or []),
            "Data disk has unexpected size, filesystem, partitions or mounts")


def run(argv: list[str], *, allowed=(0,), timeout=120) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, env=ENV, stdin=subprocess.DEVNULL, capture_output=True,
                            timeout=timeout, umask=0o077)
    if LOG.exists():
        with LOG.open("ab") as stream:
            stream.write(("\n" + " ".join(argv) + "\n").encode() + result.stdout + result.stderr)
    require(result.returncode in allowed, "Host command failed: " + argv[0] + "; inspect private bootstrap log")
    return result


def metadata() -> dict:
    # Compute metadata only: no token endpoint, credential or proxy is used.
    request = urllib.request.Request(
        "http://169.254.169.254/metadata/instance/compute?api-version=2021-12-13",
        headers={"Metadata": "true"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        return json.loads(response.read(256 * 1024))


def check_disk(device: str, receipt: dict) -> int:
    validate_metadata(metadata(), receipt)
    require(re.fullmatch(r"/dev/sd[a-z]+", device) is not None and LUN.is_symlink()
            and str(LUN.resolve(strict=True)) == device, "Exact observed Azure SCSI LUN 0 device is required")
    info = Path(device).lstat()
    require(stat.S_ISBLK(info.st_mode), "Data path must be a direct block device")
    topology = json.loads(run(["lsblk", "--json", "--bytes", "--paths", "--output",
                              "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,RO,PKNAME", device]).stdout)
    validate_topology(topology, device)
    signatures = json.loads(run(["wipefs", "--no-act", "--json", device]).stdout)
    require(signatures.get("signatures") == [], "Existing disk signatures are refused")
    holders = Path(f"/sys/dev/block/{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}/holders")
    require(holders.is_dir() and not any(holders.iterdir()), "Data disk has active holders")
    swaps = run(["swapon", "--show", "--noheadings", "--raw", "--output", "NAME"]).stdout.decode().splitlines()
    require(all(str(Path(item).resolve()) != device for item in swaps), "Data disk is used for swap")
    require(not DATA.is_symlink() and (not DATA.exists() or (DATA.is_dir() and not any(DATA.iterdir()))),
            "Data mount destination must be absent or empty")
    require(run(["mountpoint", "-q", str(DATA)], allowed=(0, 1, 32)).returncode != 0,
            "Data mount already exists")
    for line in Path("/etc/fstab").read_text().splitlines():
        fields = line.split("#", 1)[0].split()
        require(not fields or (len(fields) > 1 and fields[1] != str(DATA)
                              and fields[0] not in {device, str(LUN)}), "Existing data disk fstab entry is refused")
    return info.st_rdev


def fresh_host() -> None:
    require(os.geteuid() == 0 and platform.system() == "Linux" and platform.machine() == "x86_64",
            "Bootstrap requires root on the approved Ubuntu x86_64 host")
    release = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
    require(release.get("ID", "").strip('"') == "ubuntu"
            and release.get("VERSION_ID", "").strip('"') == "22.04", "Only Ubuntu 22.04 is supported")
    for path in (LOG, Path("/usr/sbin/policy-rc.d"), Path("/etc/docker/daemon.json"),
                 Path("/etc/apt/keyrings/docker.asc"), Path("/etc/apt/sources.list.d/docker.sources"),
                 Path("/etc/fstab.cosmabot-before"), Path("/etc/cosmabot/host-bootstrap.json")):
        require(not path.exists() and not path.is_symlink(), "Existing or interrupted bootstrap needs review")
    for path in (Path("/var/lib/docker"), Path("/var/lib/containerd")):
        require(not path.exists() or (path.is_dir() and not path.is_symlink() and not any(path.iterdir())),
                "Existing container runtime data is refused")
    for path in Path("/etc/apt/sources.list.d").iterdir():
        if path.is_file():
            require(b"download.docker.com" not in path.read_bytes(), "Existing Docker package source is refused")
    packages = set(PACKAGES) | {"docker.io", "docker-compose", "docker-compose-v2", "podman-docker", "containerd", "runc"}
    for package in sorted(packages):
        result = run(["dpkg-query", "-W", "-f=${db:Status-Status}", package], allowed=(0, 1))
        require(result.stdout.strip() != b"installed", "Existing container packages need explicit review")


def write_new(path: Path, content: bytes, mode=0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def install_packages() -> None:
    write_new(Path("/usr/sbin/policy-rc.d"), POLICY, 0o755)
    run(["systemctl", "mask", "docker.service", "docker.socket", "containerd.service"])
    run(["apt-get", "update"], timeout=600)
    run(["apt-get", "install", "--yes", "--no-install-recommends", "ca-certificates", "python3",
         "openssl", "util-linux", "iptables", "nftables", "e2fsprogs"], timeout=900)
    with urllib.request.urlopen("https://download.docker.com/linux/ubuntu/gpg", timeout=30) as response:
        key = response.read(65536)
    require(hashlib.sha256(key).hexdigest() == KEY_SHA256, "Docker signing key differs from reviewed public source")
    Path("/etc/apt/keyrings").mkdir(mode=0o755, exist_ok=True)
    Path("/etc/apt/keyrings").chmod(0o755)
    write_new(Path("/etc/apt/keyrings/docker.asc"), key, 0o644)
    source = b"Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: jammy\nComponents: stable\nArchitectures: amd64\nSigned-By: /etc/apt/keyrings/docker.asc\n"
    write_new(Path("/etc/apt/sources.list.d/docker.sources"), source, 0o644)
    run(["apt-get", "update"], timeout=600)
    run(["apt-get", "install", "--yes", "--no-install-recommends",
         *[name + "=" + version for name, version in PACKAGES.items()]], timeout=1200)
    for name, version in PACKAGES.items():
        require(run(["dpkg-query", "-W", "-f=${Version}", name]).stdout.decode() == version,
                "Installed vendor package version does not match the reviewed pin")
    require(run(["docker", "compose", "version", "--short"]).stdout.decode().strip().lstrip("v") == "5.5.1",
            "Unexpected Compose version")
    for unit in ("docker.service", "docker.socket", "containerd.service"):
        require(run(["systemctl", "is-enabled", unit], allowed=(0, 1)).stdout.strip() == b"masked",
                "Runtime service must remain masked")
        require(run(["systemctl", "is-active", unit], allowed=(0, 3)).stdout.strip() == b"inactive",
                "Runtime service unexpectedly started")
    Path("/etc/docker").mkdir(mode=0o755, exist_ok=True)
    Path("/etc/docker").chmod(0o755)
    daemon = {"firewall-backend": "iptables", "iptables": True, "ip6tables": True,
              "live-restore": False, "log-driver": "local", "log-opts": {"max-size": "10m", "max-file": "3"}}
    write_new(Path("/etc/docker/daemon.json"), (json.dumps(daemon, indent=2) + "\n").encode(), 0o644)
    run(["dockerd", "--validate", "--config-file=/etc/docker/daemon.json"])
    require(Path("/usr/sbin/policy-rc.d").read_bytes() == POLICY, "Temporary service policy changed")
    Path("/usr/sbin/policy-rc.d").unlink()


def format_mount(device: str, receipt: dict, original_device_number: int) -> str:
    require(check_disk(device, receipt) == original_device_number, "Device changed during package installation")
    # No force flag: the new Empty-disk receipt and repeated live checks are mandatory.
    run(["mkfs.ext4", "-L", "cosmabot-data", "-m", "0", "-E",
         "lazy_itable_init=0,lazy_journal_init=0", device], timeout=600)
    uuid = run(["blkid", "-s", "UUID", "-o", "value", device]).stdout.decode().strip()
    require(re.fullmatch(r"[0-9a-f-]{36}", uuid) is not None, "Expected one new ext4 UUID")
    original = Path("/etc/fstab").read_bytes()
    require(uuid.encode() not in original, "New filesystem UUID already appears in fstab")
    write_new(Path("/etc/fstab.cosmabot-before"), original)
    DATA.mkdir(mode=0o700, exist_ok=True)
    entry = f"\nUUID={uuid} {DATA} ext4 defaults,nodev,nosuid,noexec,x-systemd.device-timeout=90s 0 2\n"
    with Path("/etc/fstab").open("ab") as stream:
        stream.write(entry.encode())
        stream.flush()
        os.fsync(stream.fileno())
    run(["systemctl", "daemon-reload"])
    run(["mount", "--target", str(DATA)])
    mounted = json.loads(run(["findmnt", "--json", "--target", str(DATA), "--output", "SOURCE,TARGET,FSTYPE,UUID"]).stdout)
    filesystems = mounted.get("filesystems", [])
    require(len(filesystems) == 1 and filesystems[0].get("target") == str(DATA)
            and filesystems[0].get("uuid") == uuid and filesystems[0].get("fstype") == "ext4",
            "Mounted data filesystem does not match the new disk")
    DATA.chmod(0o700)
    for name, uid in (("postgres", 999), ("redis", 999), ("caddy-data", 10001), ("caddy-config", 10001)):
        path = DATA / name
        path.mkdir(mode=0o700)
        os.chown(path, uid, uid)
    return uuid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-id", required=True)
    parser.add_argument("--disk-id", required=True)
    parser.add_argument("--expected-device", required=True)
    parser.add_argument("--creation-receipt", type=Path, required=True)
    parser.add_argument("--creation-receipt-sha256", required=True)
    parser.add_argument("--format-new-empty-disk")
    args = parser.parse_args()
    os.umask(0o077)
    fresh_host()
    meta = args.creation_receipt.lstat()
    require(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0 and meta.st_nlink == 1
            and stat.S_IMODE(meta.st_mode) in (0o400, 0o600) and meta.st_size < 16384,
            "Creation receipt must be a private root-owned regular file")
    raw = args.creation_receipt.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == args.creation_receipt_sha256, "Creation receipt differs from reviewed hash")
    receipt = json.loads(raw)
    validate_receipt(receipt, args.vm_id, args.disk_id, args.format_new_empty_disk, dt.datetime.now(dt.timezone.utc))
    with Path("/run/lock/cosmabot-host-bootstrap.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        device_number = check_disk(args.expected_device, receipt)
        write_new(LOG, b"CosmaBot new-host bootstrap; public resource coordinates only.\n")
        print("New host and Empty-disk provenance verified; installing pinned runtime packages.", flush=True)
        install_packages()
        print("Packages installed with services masked; rechecking exact new disk before formatting.", flush=True)
        uuid = format_mount(args.expected_device, receipt, device_number)
        result = {"version": 1, "vm_id": args.vm_id, "disk_id": args.disk_id, "filesystem_uuid": uuid,
                  "data_mount": str(DATA), "packages": PACKAGES, "creation_receipt_sha256": args.creation_receipt_sha256,
                  "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "docker_services_masked": True, "containers_started": False, "application_installed": False}
        Path("/etc/cosmabot").mkdir(mode=0o700, exist_ok=True)
        write_new(Path("/etc/cosmabot/host-bootstrap.json"), (json.dumps(result, indent=2) + "\n").encode())
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, Refused) else "Invalid input or interrupted host operation"
        print("Host bootstrap refused: " + message + ". No containers were started by this script.", file=sys.stderr)
        raise SystemExit(1) from None
