"""Compose Scribe's local desktop recorder and native helpers; never launch them."""
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path


def prepare(root: Path, output: Path, app: Path) -> None:
    build = output / "native-capture-build"
    build.mkdir()
    environment = {**os.environ, "CLANG_MODULE_CACHE_PATH": str(build / "modules"),
                   "SWIFTPM_MODULECACHE_OVERRIDE": str(build / "modules")}
    command = ["xcrun", "swift", "build", "--package-path", str(root / "clients/desktop/native-audio"),
               "--scratch-path", str(build / "build"), "--cache-path", str(build / "cache"),
               "--config-path", str(build / "config"), "--security-path", str(build / "security"),
               "--disable-sandbox", "--configuration", "release"]
    with (build / "compile.log").open("x") as log:
        subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    products = Path(subprocess.check_output([*command, "--show-bin-path"], env=environment, text=True).strip())
    compose(root, app, products)


def compose(root: Path, app: Path, products: Path) -> None:
    """Compose already built helpers and the current main-process recorder."""
    native = app / "native-capture"
    native.mkdir()
    for name, suffix in (("ScribeDesktopAudioHelper", "audio"), ("ScribeProviderPresentationHelper", "indicator")):
        bundle = native / (name + ".app")
        (bundle / "Contents/MacOS").mkdir(parents=True)
        shutil.copyfile(products / name, bundle / "Contents/MacOS" / name)
        (bundle / "Contents/MacOS" / name).chmod(0o755)
        (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "com.cosmasos.beta.desktop." + suffix, "CFBundleExecutable": name,
            "CFBundleName": "Cosmas Recording", "CFBundlePackageType": "APPL", "CFBundleVersion": "1",
            "CFBundleShortVersionString": "0.1.0", "LSMinimumSystemVersion": "14.2", "LSUIElement": True,
            "NSMicrophoneUsageDescription": "Record the visit microphone with your consent.",
            "NSScreenCaptureUsageDescription": "Record audio from the meeting window you select.",
        }))
    (native / "manifest.json").write_text(json.dumps({"version": 1, "files": {
        str(path.relative_to(native)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in native.rglob("*") if path.is_file()
    }}, indent=2) + "\n")
    # Use the existing pinned Vite/esbuild installation, with the capture aliases.
    subprocess.run(["node", "--input-type=module", "-e",
        "import{createRequire}from'node:module';const r=createRequire(process.argv[1]);"
        "const e=createRequire(r.resolve('vite'))('esbuild');await e.build({entryPoints:[process.argv[2]],"
        "outfile:process.argv[3],tsconfig:process.argv[4],bundle:true,platform:'node',format:'esm',target:'node24',sourcemap:false});",
        str(root / "web/package.json"), str(root / "clients/desktop/recorder/workspace-capture-host.ts"),
        str(app / "workspace-native-capture.mjs"), str(root / "clients/desktop/tsconfig.capture.json")], check=True)
    preload = app / "auth-preload.cjs"
    text = preload.read_text()
    marker = "const captureEnabled = false; // @desktop-native-capture-enabled@"
    if text.count(marker) != 1:
        raise ValueError("Desktop recording preload selector is missing.")
    preload.write_text(text.replace(marker, "const captureEnabled = true; // @desktop-native-capture-enabled@"))
