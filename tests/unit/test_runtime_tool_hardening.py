"""Trusted build guard tested only against synthetic tmp_path roots."""
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HELPER = Path(__file__).parents[2] / "scripts/harden_runtime_tools.py"
spec = importlib.util.spec_from_file_location("runtime_tool_guard", HELPER)
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)


def synthetic_root(tmp_path):
    root = tmp_path / "root"
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/lib").mkdir()
    (root / "etc").mkdir()
    (root / "proc").mkdir()
    (root / "dev").mkdir()
    pins = []
    packages = {}
    for name in ("infocmp", "nsenter"):
        data = ("invented tool bytes: " + name).encode()
        path = root / "usr/bin" / name
        path.write_bytes(data)
        path.chmod(0o755)
        package = "invented-" + name
        pins.append(guard.ToolPin(name, len(data), hashlib.sha256(data).hexdigest(),
                                 package, "1.0", path.stat().st_uid, path.stat().st_gid))
        packages[package] = {"version": "1.0", "essential": "yes", "status": "installed"}
    (root / "bin").symlink_to("usr/bin")
    library = root / "usr/lib/required.so"
    library.write_bytes(b"invented library retained")
    library.chmod(0o644)
    special = root / "usr/bin/unrelated-helper"
    special.write_bytes(b"invented unrelated helper")
    special.chmod(0o6751)
    return root, tuple(pins), packages


def owner(pins):
    return lambda path: next(p.package for p in pins if path == "/usr/bin/" + p.name)


def snapshot(root):
    return {str(p.relative_to(root)): (p.lstat().st_mode,
            os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
            for p in root.rglob("*")}


def run(root, pins, packages, probe=lambda: None, get_packages=None):
    return guard.harden(root, pins, get_packages or (lambda: packages.copy()), owner(pins), probe)


def test_remove_all_bytes_aliases_and_privilege_preserving_metadata_and_libraries(tmp_path):
    root, pins, packages = synthetic_root(tmp_path)
    tool = root / "usr/bin/nsenter"
    hardlink = root / "usr/lib/loader-copy"
    os.link(tool, hardlink)
    copied = root / "usr/lib/copied-tool"
    copied.write_bytes(tool.read_bytes())
    copied.chmod(0o644)  # Dynamic loader could execute bytes even without executable mode.
    (root / "etc/namespace-tool").symlink_to("/bin/nsenter")
    (root / "etc/chained-alias").symlink_to("namespace-tool")
    (root / "etc/proc-alias").symlink_to("/proc/mounts")
    (root / "etc/dev-alias").symlink_to("/dev/null")
    (root / "usr/lib/library-alias").symlink_to("required.so")
    privileged = root / "usr/bin/unrelated-helper"
    os.link(privileged, root / "usr/lib/helper-link")
    directory = root / "usr/lib/group-directory"
    directory.mkdir()
    directory.chmod(0o2770)
    calls = []
    result = run(root, pins, packages, lambda: calls.append("imports"))
    assert result["installed_packages_unchanged"] and calls == ["imports", "imports"]
    assert result["remaining_privileged_entries"] == 0
    assert result["tool_bytes_and_aliases_absent"]
    for relative in ["usr/bin/nsenter", "usr/bin/infocmp", "usr/lib/loader-copy",
                     "usr/lib/copied-tool", "etc/namespace-tool", "etc/chained-alias"]:
        assert not (root / relative).exists() and not (root / relative).is_symlink()
    assert (root / "bin").is_symlink()
    assert (root / "usr/lib/required.so").read_bytes() == b"invented library retained"
    assert (root / "usr/lib/library-alias").read_bytes() == b"invented library retained"
    assert stat.S_IMODE(privileged.stat().st_mode) == 0o751
    assert stat.S_IMODE((root / "usr/lib/helper-link").stat().st_mode) == 0o751
    assert stat.S_IMODE(directory.stat().st_mode) == 0o770
    assert packages == {p.package: {"version": "1.0", "essential": "yes", "status": "installed"} for p in pins}


@pytest.mark.parametrize("fault", ["hash", "size", "mode", "uid", "owner", "package", "missing",
                                  "canonical_symlink", "different_named_tool", "loop", "escape",
                                  "forbidden_mount", "forbidden_umount", "forbidden_homed", "forbidden_tar",
                                  "forbidden_symlink", "fifo", "outside_hardlink",
                                  "imports", "inventory_changed"])
def test_preflight_refuses_drift_without_partial_mutation(tmp_path, fault):
    root, pins, packages = synthetic_root(tmp_path)
    path = root / "usr/bin/nsenter"
    package_owner = owner(pins)
    def probe():
        return None
    def get_packages():
        return packages.copy()
    if fault == "hash":
        path.write_bytes(b"x" * path.stat().st_size)
    elif fault == "size":
        path.write_bytes(b"changed")
    elif fault == "mode":
        path.chmod(0o775)
    elif fault == "uid":
        pins = tuple(guard.ToolPin(p.name, p.size, p.sha256, p.package, p.version,
                                 p.uid + 1, p.gid) for p in pins)
    elif fault == "owner":
        def package_owner(_):
            return "unreviewed-owner"
    elif fault == "package":
        packages[pins[0].package]["version"] = "2.0"
    elif fault == "missing":
        path.unlink()
    elif fault == "canonical_symlink":
        path.rename(root / "usr/lib/replaced")
        path.symlink_to("../lib/replaced")
    elif fault == "different_named_tool":
        (root / "usr/lib/nsenter").write_bytes(b"different entry point")
    elif fault == "loop":
        (root / "etc/loop").symlink_to("loop")
    elif fault == "escape":
        (root / "etc/escape").symlink_to("../../outside")
    elif fault.startswith("forbidden_"):
        name = {"forbidden_mount": "mount", "forbidden_umount": "umount",
                "forbidden_homed": "systemd-homed", "forbidden_tar": "Archive/Tar.pm"}.get(fault)
        if name:
            target = root / "usr/lib" / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(b"unreviewed component")
        else:
            (root / "etc/alias").symlink_to("/usr/bin/mount")
            # A named forbidden symlink is rejected even when its target is missing.
            (root / "usr/bin/mount").symlink_to("missing")
    elif fault == "fifo":
        os.mkfifo(root / "etc/pipe")
    elif fault == "outside_hardlink":
        os.link(path, tmp_path / "outside")
    elif fault == "imports":
        def probe():
            raise guard.HardeningError("missing_runtime_import")
    elif fault == "inventory_changed":
        count = []
        def get_packages():
            count.append(1)
            return packages.copy() if len(count) == 1 else {}
    # Avoid reading a FIFO in the test-only snapshot helper.
    if fault == "fifo":
        before = {p: p.stat().st_mode for p in [path, root / "usr/bin/unrelated-helper"]}
    else:
        before = snapshot(root)
    with pytest.raises(guard.HardeningError):
        guard.harden(root, pins, get_packages, package_owner, probe)
    if fault == "fifo":
        assert before == {p: p.stat().st_mode for p in before}
    else:
        assert snapshot(root) == before


def test_inode_revalidation_after_import_preflight_refuses_modified_plan(tmp_path):
    root, pins, packages = synthetic_root(tmp_path)
    changed = root / "usr/bin/infocmp"
    helper_mode = (root / "usr/bin/unrelated-helper").stat().st_mode
    def probe():
        changed.write_bytes(b"x" * changed.stat().st_size)
    with pytest.raises(guard.HardeningError, match="runtime_changed_before_mutation"):
        run(root, pins, packages, probe)
    assert (root / "usr/bin/nsenter").exists()
    assert (root / "usr/bin/unrelated-helper").stat().st_mode == helper_mode


@pytest.mark.parametrize("outside", [False, True])
def test_privileged_regular_inode_plan_on_hosts_that_clear_setid(tmp_path, monkeypatch, outside):
    root, pins, packages = synthetic_root(tmp_path)
    helper = root / "usr/bin/unrelated-helper"
    os.link(helper, tmp_path / "outside" if outside else root / "usr/lib/helper-link")
    records = guard.walk(root)
    for relative, info in list(records.items()):
        if guard.inode(info) == guard.inode(helper.stat()):
            fields = {name: getattr(info, name) for name in ("st_dev", "st_ino", "st_mode",
                      "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}
            fields["st_mode"] |= guard.PRIVILEGE
            records[relative] = SimpleNamespace(**fields)
    monkeypatch.setattr(guard, "walk", lambda _: records)
    before = snapshot(root)
    if outside:
        with pytest.raises(guard.HardeningError, match="unobserved_mutation_hardlink"):
            guard.plan(root, pins, packages, owner(pins))
    else:
        _, _, privileged = guard.plan(root, pins, packages, owner(pins))
        assert privileged == [{"paths": ["usr/bin/unrelated-helper", "usr/lib/helper-link"],
                               "mode_before": 0o6751, "mode_after": 0o751}]
    assert snapshot(root) == before


@pytest.mark.parametrize("text", ["missing-fields\n", "\t1\tyes\tinstalled\n",
                                  "pkg\t\tyes\tinstalled\n",
                                  "pkg\t1\tyes\tinstalled\npkg\t1\tyes\tinstalled\n"])
def test_package_inventory_rejects_malformed_or_duplicate_rows(monkeypatch, text):
    monkeypatch.setattr(guard.subprocess, "check_output", lambda *_, **__: text)
    with pytest.raises(guard.HardeningError):
        guard.package_inventory()


def test_package_inventory_keeps_complete_installed_metadata(monkeypatch):
    text = "pkg:amd64\t1:2.3-1\tno\tinstalled\nold\t1\tyes\tconfig-files\n"
    monkeypatch.setattr(guard.subprocess, "check_output", lambda *_, **__: text)
    assert guard.package_inventory() == {"pkg:amd64": {"version": "1:2.3-1",
                                                      "essential": "no", "status": "installed"}}


@pytest.mark.parametrize("text", ["pkg, other: /usr/bin/nsenter\n", "pkg: /usr/bin/other\n",
                                  "pkg: /usr/bin/nsenter\nother: /usr/bin/nsenter\n",
                                  "pkg: /usr/bin/nsenter", ": /usr/bin/nsenter\n"])
def test_package_owner_rejects_ambiguous_or_malformed_result(monkeypatch, text):
    monkeypatch.setattr(guard.subprocess, "check_output", lambda *_, **__: text)
    with pytest.raises(guard.HardeningError, match="ambiguous_package_owner"):
        guard.package_owner("/usr/bin/nsenter")


def test_package_owner_accepts_single_architecture_qualified_owner(monkeypatch):
    monkeypatch.setattr(guard.subprocess, "check_output", lambda *_, **__: "pkg:amd64: /usr/bin/nsenter\n")
    assert guard.package_owner("/usr/bin/nsenter") == "pkg:amd64"


@pytest.mark.parametrize("fault", [None, "mode", "hash", "owner", "symlink", "hardlink", "tool_bytes",
                                  "unreviewed_named_alias"])
def test_exact_nonexecutable_completion_metadata_only(tmp_path, fault):
    root, pins, packages = synthetic_root(tmp_path)
    relative = "usr/share/bash-completion/completions/nsenter"
    path = root / relative
    path.parent.mkdir(parents=True)
    data = b"_nsenter_module() { # invented completion metadata\n}\n"
    path.write_bytes(data)
    path.chmod(0o644)
    pin = guard.ToolPin("nsenter", len(data), hashlib.sha256(data).hexdigest(), pins[1].package,
                        pins[1].version, path.stat().st_uid, path.stat().st_gid, 0o644)
    def package_owner(candidate):
        if candidate == "/" + relative:
            return "wrong-owner" if fault == "owner" else pin.package
        return owner(pins)(candidate)
    if fault == "mode":
        path.chmod(0o755)
    elif fault == "hash":
        path.write_bytes(b"x" * len(data))
    elif fault == "symlink":
        path.unlink()
        path.symlink_to("../../../bin/nsenter")
    elif fault == "hardlink":
        os.link(path, root / "usr/lib/copied-completion")
    elif fault == "tool_bytes":
        path.write_bytes((root / "usr/bin/nsenter").read_bytes())
    elif fault == "unreviewed_named_alias":
        (root / "usr/lib/nsenter").symlink_to("../share/bash-completion/completions/nsenter")
    before = snapshot(root)
    if fault:
        with pytest.raises(guard.HardeningError):
            guard.harden(root, pins, lambda: packages.copy(), package_owner, lambda: None, {relative: pin})
        assert snapshot(root) == before
    else:
        receipt = guard.harden(root, pins, lambda: packages.copy(), package_owner, lambda: None, {relative: pin})
        assert receipt["retained_pinned_metadata"] == [relative]
        assert path.read_bytes() == data and stat.S_IMODE(path.stat().st_mode) == 0o644
        assert not (root / "usr/bin/nsenter").exists()


def test_optimized_python_still_fails_closed_without_mutation(tmp_path):
    root, pins, packages = synthetic_root(tmp_path)
    payload = {"root": str(root), "packages": packages,
               "pins": [{"name": p.name, "size": p.size, "sha256": p.sha256,
                         "package": p.package, "version": p.version, "uid": p.uid, "gid": p.gid}
                        for p in pins]}
    code = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('guard',sys.argv[1]);g=importlib.util.module_from_spec(spec);sys.modules[spec.name]=g;spec.loader.exec_module(g)
v=json.loads(sys.stdin.read());pins=tuple(g.ToolPin(**p) for p in v['pins'])
g.harden(g.Path(v['root']),pins,lambda:v['packages'],lambda _: 'wrong-owner',lambda:None)
"""
    before = snapshot(root)
    value = subprocess.run([sys.executable, "-O", "-B", "-c", code, str(HELPER)],
                           input=json.dumps(payload), capture_output=True, text=True, timeout=15)
    assert value.returncode != 0 and "pinned_tool_owner_changed" in value.stderr
    assert snapshot(root) == before
