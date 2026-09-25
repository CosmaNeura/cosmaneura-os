"""Compiler-bound packaging regressions with an in-process fake compiler, no native build."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import plistlib
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / name)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


builder = module("build-desktop-auth-helper.py")
packager = module("package-desktop-auth-helper.py")
binding = builder.binding


def qualify(root: Path) -> Path:
    root.mkdir()
    sources = {"Package.swift": "// invented local package\n", "Sources/Auth.swift": "// auth fixture\n",
               "Desktop/main.swift": "// executable fixture\n", "vendor/LICENSE": "Invented SDK license\n",
               "vendor/Sources/ClerkKit/Core.swift": "// SDK fixture\n"}
    for name, content in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    hashes = {name: binding.digest(root / name) for name in sources}
    (root / "qualification.json").write_text(json.dumps({
        "clerk_version": "1.5.5", "archive_sha256": binding.ARCHIVE_SHA256,
        "includes_desktop_helper": True, "includes_capacitor_bridge": False,
        "native_identity_profile_version": 1, "native_source_version": 1,
        "composed_sha256": hashes,
        "sdk_source_sha256": {name.removeprefix("vendor/"): value for name, value in hashes.items()
                              if name.startswith("vendor/")},
    }))
    return root


@pytest.fixture
def compiler(tmp_path: Path, monkeypatch):
    calls = []
    swift = tmp_path / "swift"
    swift.write_text("invented compiler executable, not executed by these unit tests")
    swift.chmod(0o755)

    def run(command, output, environment, *, query=False):
        calls.append((command, environment))
        compiled = output / "scratch/target/debug"
        if query:
            return str(compiled)
        compiled.mkdir(parents=True)
        binary = compiled / binding.PRODUCT
        binary.write_bytes(b"invented compiled helper")
        binary.chmod(0o755)
        resources = compiled / binding.RESOURCES
        resources.mkdir()
        (resources / "Info.plist").write_bytes(plistlib.dumps({"CFBundleName": "Invented SDK fixture"}))
        (output / "compile.log").write_text("invented compiler success\n")
        return ""

    monkeypatch.setattr(builder, "run_compiler", run)
    return swift, calls


def compile_fixture(tmp_path: Path, compiler):
    qualified = qualify(tmp_path / "qualification")
    output = tmp_path / "build"
    receipt = builder.build(qualified, compiler[0], output)
    return qualified, output, receipt


def package(monkeypatch, qualified, output, receipt, app, *, extra=()):
    monkeypatch.setattr(sys, "argv", ["package-desktop-auth-helper.py", "--qualification", str(qualified),
                                    "--products", str(output / "products"), "--compiler-receipt", str(receipt),
                                    "--output", str(app), "--verification-variant", "w100", *extra])
    packager.main()


def test_owned_build_and_normal_packaging_preserve_products(tmp_path, compiler, monkeypatch):
    monkeypatch.setenv("SWIFT_EXEC", "/unrelated/compiler")
    qualified, output, receipt = compile_fixture(tmp_path, compiler)
    assert binding.verify(receipt, qualified, output / "products")["includes_desktop_helper"] is True
    assert len(compiler[1]) == 2
    command, environment = compiler[1][0]
    assert command[:3] == ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)"]
    assert command[-2:] == ["--product", "CosmasDesktopAuth"]
    assert "--disable-automatic-resolution" in command and "--disable-sandbox" in command
    for flag, folder in (("--scratch-path", "scratch"), ("--cache-path", "cache"),
                         ("--config-path", "config"), ("--security-path", "security")):
        assert command[command.index(flag) + 1] == str(output / folder)
    assert "SWIFT_EXEC" not in environment
    assert environment["HOME"] == str(output / "home")
    assert environment["CFFIXED_USER_HOME"] == environment["HOME"]
    assert environment["XDG_CACHE_HOME"] == str(output / "xdg-cache")
    assert environment["CLANG_MODULE_CACHE_PATH"] == str(output / "modules")
    assert compiler[1][1][0] == [*command, "--show-bin-path"]
    assert not (output / ".incomplete").exists()
    assert binding.qualification(qualified) == binding.qualification(output / "source")
    app = tmp_path / "Helper.app"
    package(monkeypatch, qualified, output, receipt, app)
    assert (app / "Contents/MacOS/CosmasDesktopAuth").read_bytes() == b"invented compiled helper"
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "com.cosmasos.synthetic.desktop.auth.w100"
    assert info["CosmasNativeAuth"] == {"enabled": False}
    assert not (app / ".incomplete").exists()
    assert not list(app.rglob(binding.RECEIPT))


@pytest.mark.parametrize("damage", ["binary", "resources", "extra-resource", "mode", "original-product", "source-copy", "log"])
def test_packaging_refuses_changed_compiler_inputs_before_creating_output(tmp_path, compiler, monkeypatch, damage):
    qualified, output, receipt = compile_fixture(tmp_path, compiler)
    paths = {"binary": output / "products" / binding.PRODUCT,
             "resources": output / "products" / binding.RESOURCES / "Info.plist",
             "extra-resource": output / "products" / binding.RESOURCES / "unqualified.txt",
             "original-product": output / "scratch/target/debug" / binding.PRODUCT,
             "source-copy": output / "source/Desktop/main.swift", "log": output / "compile.log"}
    if damage == "mode":
        (output / "products" / binding.PRODUCT).chmod(0o644)
    else:
        paths[damage].write_text("unrelated replacement")
    app = tmp_path / "Rejected.app"
    with pytest.raises(ValueError):
        package(monkeypatch, qualified, output, receipt, app)
    assert not app.exists()


def test_fresh_qualification_cannot_be_paired_with_old_compiler_receipt(tmp_path, compiler, monkeypatch):
    qualified, output, receipt = compile_fixture(tmp_path, compiler)
    source = qualified / "Desktop/main.swift"
    source.write_text("// freshly composed new source\n")
    manifest = json.loads((qualified / "qualification.json").read_text())
    manifest["composed_sha256"]["Desktop/main.swift"] = binding.digest(source)
    (qualified / "qualification.json").write_text(json.dumps(manifest))
    app = tmp_path / "Mixed.app"
    with pytest.raises(ValueError, match="different qualification"):
        package(monkeypatch, qualified, output, receipt, app)
    assert not app.exists()


def test_identical_product_copy_from_unrelated_directory_is_not_this_invocation(tmp_path, compiler):
    qualified, output, receipt = compile_fixture(tmp_path, compiler)
    other = tmp_path / "old-products"
    shutil.copytree(output / "products", other)
    with pytest.raises(ValueError, match="belonging to this compiler receipt"):
        binding.verify(receipt, qualified, other)


@pytest.mark.parametrize("damage", ["changed", "extra", "missing", "symlink", "escape"])
def test_changed_or_unsafe_qualification_never_starts_compiler(tmp_path, compiler, damage):
    qualified = qualify(tmp_path / "qualification")
    source = qualified / "Desktop/main.swift"
    if damage == "changed":
        source.write_text("// changed")
    elif damage == "extra":
        (qualified / "Desktop/unlisted.swift").write_text("// not qualified")
    elif damage == "missing":
        source.unlink()
    elif damage == "symlink":
        source.unlink()
        source.symlink_to(qualified / "Sources/Auth.swift")
    else:
        manifest = json.loads((qualified / "qualification.json").read_text())
        manifest["composed_sha256"]["../escaped.swift"] = hashlib.sha256(b"outside").hexdigest()
        (qualified / "qualification.json").write_text(json.dumps(manifest))
    output = tmp_path / "rejected-build"
    with pytest.raises(ValueError):
        builder.build(qualified, compiler[0], output)
    assert not compiler[1] and not output.exists()


@pytest.mark.parametrize("failure", ["compiler", "changed-source", "external-products"])
def test_failed_or_unbound_build_never_issues_receipt(tmp_path, compiler, monkeypatch, failure):
    qualified = qualify(tmp_path / "qualification")
    original = builder.run_compiler

    def run(command, output, environment, *, query=False):
        result = original(command, output, environment, query=query)
        if not query and failure == "compiler":
            raise ValueError("invented compiler failure")
        if not query and failure == "changed-source":
            (output / "source/Desktop/main.swift").write_text("// compiler changed source")
        if query and failure == "external-products":
            return str(tmp_path / "unrelated-products")
        return result

    monkeypatch.setattr(builder, "run_compiler", run)
    output = tmp_path / "failed-build"
    with pytest.raises(ValueError):
        builder.build(qualified, compiler[0], output)
    assert (output / ".incomplete").is_file()
    assert not (output / binding.RECEIPT).exists()
    assert len(compiler[1]) == (1 if failure == "compiler" else 2)


def test_missing_receipt_and_mixed_identity_profiles_remain_blocked(tmp_path, compiler, monkeypatch):
    qualified, output, receipt = compile_fixture(tmp_path, compiler)
    app = tmp_path / "Rejected.app"
    with pytest.raises(ValueError):
        package(monkeypatch, qualified, output, output / "missing.json", app)
    assert not app.exists()
    monkeypatch.setattr(packager._identity, "load", lambda *_: {"bundle": "com.example.invalid.auth"})
    with pytest.raises(SystemExit):
        package(monkeypatch, qualified, output, receipt, app)
    assert not app.exists()  # Operational identity cannot use a synthetic variant.


def test_incomplete_helper_cannot_continue_into_desktop_composition(tmp_path, monkeypatch, capsys):
    composer = module("prepare-desktop-synthetic.py")
    helper = tmp_path / "Incomplete.app"
    helper.mkdir()
    (helper / ".incomplete").write_text("failed packaging")
    output = tmp_path / "composed"
    monkeypatch.setattr(sys, "argv", ["prepare-desktop-synthetic.py", "--scribe-source", str(tmp_path / "unused-source"),
                                    "--web-dist", str(tmp_path / "unused-web"), "--output", str(output),
                                    "--native-auth-helper", str(helper)])
    with pytest.raises(SystemExit):
        composer.main()
    assert "packaging is incomplete" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize("damage", ["transient-extra-resource", "changed-plist"])
def test_packaging_checks_complete_destination_before_clearing_incomplete(tmp_path, compiler, monkeypatch, damage):
    qualified, output, receipt = compile_fixture(tmp_path, compiler)
    app = tmp_path / "Incomplete.app"
    if damage == "transient-extra-resource":
        original_copytree = shutil.copytree

        def copytree(source, destination, *args, **kwargs):
            extra = Path(source) / "unqualified.txt"
            extra.write_text("extra input that disappears after copying")
            try:
                return original_copytree(source, destination, *args, **kwargs)
            finally:
                extra.unlink()

        monkeypatch.setattr(packager.shutil, "copytree", copytree)
    else:
        original_write = Path.write_bytes

        def write_bytes(path, data):
            count = original_write(path, data)
            if path == app / "Contents/Info.plist":
                original_write(path, plistlib.dumps({"CFBundleExecutable": "unqualified-executable"}))
            return count

        monkeypatch.setattr(Path, "write_bytes", write_bytes)
    with pytest.raises(ValueError, match="output inventory differs"):
        package(monkeypatch, qualified, output, receipt, app)
    assert (app / ".incomplete").is_file()
    binding.verify(receipt, qualified, output / "products")  # Compiler inputs are still intact.
