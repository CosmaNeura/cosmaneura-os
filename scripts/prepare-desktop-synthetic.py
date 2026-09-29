#!/usr/bin/env python3
"""Compose an isolated synthetic Mac client from Scribe desktop boundaries."""

import argparse
import hashlib
import importlib.util
import json
import mimetypes
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

_beta_spec = importlib.util.spec_from_file_location("beta_profile_build", Path(__file__).with_name("beta_profile_build.py"))
if _beta_spec is None or _beta_spec.loader is None:
    raise ValueError("Beta profile validator is unavailable.")
_beta = importlib.util.module_from_spec(_beta_spec)
_beta_spec.loader.exec_module(_beta)

_navigation_spec = importlib.util.spec_from_file_location("cosmaneura_navigation_build", Path(__file__).with_name("cosmaneura_navigation_build.py"))
if _navigation_spec is None or _navigation_spec.loader is None:
    raise ValueError("Native navigation composer is unavailable.")
_navigation = importlib.util.module_from_spec(_navigation_spec)
_navigation_spec.loader.exec_module(_navigation)

_identity_spec = importlib.util.spec_from_file_location("native_identity_build", Path(__file__).with_name("native_identity_build.py"))
_identity = importlib.util.module_from_spec(_identity_spec)
_identity_spec.loader.exec_module(_identity)

SOURCE_REF = "fe22a435b6201c2d8013348927ea6a349e0b48c6"
SOURCES = {
    "electron-security.ts": "scribe-security.mjs",
    "electron-diagnostics.ts": "scribe-diagnostics.mjs",
    "electron-app.ts": "static-assets.mjs",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scribe-source", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-auth-helper", type=Path,
                        help="Separately packaged, disabled Swift helper for authenticated local composition")
    parser.add_argument("--capture-upload-origin", action="append", default=[],
                        help="Exact HTTPS upload origin for authenticated capture; absent by default")
    parser.add_argument("--microphone-capture", action="store_true",
                        help="Stage audio-only permissions for an authenticated capture build; hardware testing needs authority")
    parser.add_argument("--cosmaneura-web-origin", default="",
                        help="Exact approved HTTPS Core web origin; record navigation is disabled when empty")
    parser.add_argument('--scheduling-google-client-id', default='')
    parser.add_argument('--scheduling-google-callback-uri', default='')
    parser.add_argument("--google-connection-client-id", default="")
    parser.add_argument("--google-connection-callback-uri", default="")
    parser.add_argument("--microsoft-connection-tenant-id", default="")
    parser.add_argument("--microsoft-connection-client-id", default="")
    parser.add_argument("--microsoft-connection-callback-uri", default="")
    parser.add_argument("--app-version", default="0.1.0", help="Numeric product version, independent of Electron")
    parser.add_argument("--build-number", default="1", help="Positive local build number, at most four digits")
    parser.add_argument("--installation-profile", help="Stable isolated authenticated installation, e.g. w19")
    parser.add_argument("--installation-root", type=Path,
                        help="Optional separate local test storage root; otherwise Application Support/CosmasOS Synthetic")
    parser.add_argument("--hosted-api-origin", help="Pin a hosted synthetic beta API matching the web build manifest")
    parser.add_argument("--native-identity-config", type=Path, help="Explicit public operational identity; separate stable app/storage")
    parser.add_argument("--data-mode", choices=("synthetic", "authorized_beta"), help="Explicit hosted data classification; synthetic for staging with a real identity")
    args = parser.parse_args()
    source, web, output = (value.resolve() for value in (args.scribe_source, args.web_dist, args.output))
    root = Path(__file__).resolve().parents[1]
    hosted = args.hosted_api_origin is not None
    identity = _identity.load(args.native_identity_config, "desktop", args.hosted_api_origin)
    operational = identity is not None
    if operational and (not hosted or args.installation_profile != "beta" or args.installation_root is not None):
        parser.error("Operational desktop composition requires hosted API, the beta installation profile and default private storage.")
    try:
        data_mode = _identity.data_mode(identity, args.data_mode)
    except ValueError as error:
        parser.error(str(error))
    if hosted:
        manifest = json.loads((web / "cosmas-workspace-build.json").read_text())
        if (not args.native_auth_helper or not args.installation_profile
                or manifest != {"version": 1, "client": "desktop", "dataMode": data_mode,
                                "apiOrigin": args.hosted_api_origin, "apiBase": "app://cosmas/api",
                                "pageOrigin": "app://cosmas"}):
            parser.error("Hosted composition requires the matching desktop web build, native helper and isolated installation profile.")
        subprocess.run(["node", "--input-type=module", "-e",
                        "const m=await import(process.argv[1]);if(!m.exactHostedApiOrigin(process.argv[2]))process.exit(1)",
                        (root / "clients/desktop/hosted-auth-http.mjs").as_uri(), args.hosted_api_origin], check=True)
    elif (web / "cosmas-workspace-build.json").exists():
        parser.error("A hosted web build requires its explicit hosted API origin.")
    feature_manifest = None
    if hosted:
        feature_manifest = _beta.validate_native(web, client="desktop", apiOrigin=args.hosted_api_origin,
                              coreWebOrigin=args.cosmaneura_web_origin,
                              captureUploadOrigins=args.capture_upload_origin,
                              microphoneCapture=args.microphone_capture)
    staging = feature_manifest is not None and feature_manifest["profile"] == _beta.NATIVE_STAGING_PROFILE
    if staging and (not operational or data_mode != "synthetic"):
        parser.error("First-owner staging requires the operational native identity and synthetic data.")
    if staging and any((args.google_connection_client_id, args.google_connection_callback_uri,
                        args.microsoft_connection_tenant_id, args.microsoft_connection_client_id,
                        args.microsoft_connection_callback_uri, args.scheduling_google_client_id,
                        args.scheduling_google_callback_uri)):
        parser.error("External account connections are disabled for first-owner staging.")
    native_capture = operational and not staging
    _navigation.validate_google(args.google_connection_client_id, args.google_connection_callback_uri)
    if args.google_connection_client_id and not args.native_auth_helper:
        parser.error("Google connection requires authenticated desktop composition.")
    _navigation.validate_microsoft(args.microsoft_connection_tenant_id, args.microsoft_connection_client_id, args.microsoft_connection_callback_uri)
    if args.microsoft_connection_tenant_id and not args.native_auth_helper:
        parser.error("Microsoft connection requires authenticated desktop composition.")
    _navigation.validate_scheduling(args.scheduling_google_client_id, args.scheduling_google_callback_uri)
    if args.scheduling_google_client_id and not args.native_auth_helper:
        parser.error('Scheduling sign-in requires authenticated desktop composition.')
    _navigation.validate_origin(args.cosmaneura_web_origin)
    if args.cosmaneura_web_origin and not args.native_auth_helper:
        parser.error("Cosmaneura navigation requires authenticated desktop composition.")
    if (not re.fullmatch(r"(?:0|[1-9][0-9]{0,3})(?:\.(?:0|[1-9][0-9]{0,3})){2}", args.app_version)
            or not re.fullmatch(r"[1-9][0-9]{0,3}", args.build_number)):
        parser.error("Use a numeric three-part app version and a build number from 1 to 9999.")
    if args.installation_profile and (not args.native_auth_helper
            or not operational and not re.fullmatch(r"w[1-9][0-9]*[a-z]?", args.installation_profile)):
        parser.error("A stable installation requires an authenticated helper and separate milestone profile.")
    if args.installation_root and not args.installation_profile:
        parser.error("An installation root requires an explicit installation profile.")
    installation_root = args.installation_root.resolve() if args.installation_root else None
    if installation_root and any(installation_root.is_relative_to(path) or path.is_relative_to(installation_root)
                                 for path in (source, web, output, root)):
        parser.error("Keep installation storage separate from source, web and versioned build directories.")
    if args.microphone_capture and (not args.native_auth_helper or not args.capture_upload_origin):
        parser.error("Microphone capture requires authenticated composition and exact upload origins.")
    if args.capture_upload_origin:
        if not args.native_auth_helper:
            parser.error("Capture upload origins require the authenticated desktop composition.")
        subprocess.run(["node", "--input-type=module", "-e",
                        "const m=await import(process.argv[1]);"
                        "m.captureContentSecurityPolicy(\"connect-src 'self'\",JSON.parse(process.argv[2]));",
                        (root / "clients/desktop/capture-content-security.mjs").as_uri(),
                        json.dumps(args.capture_upload_origin)], check=True)
    if args.native_auth_helper:
        helper = args.native_auth_helper.resolve()
        if (helper / ".incomplete").exists() or (helper / ".incomplete").is_symlink():
            parser.error("Native auth helper packaging is incomplete; use a successfully packaged helper.")
        info = plistlib.loads((helper / "Contents/Info.plist").read_bytes())
        expected_capture = {"enabled": True, "apiOrigin": args.hosted_api_origin} if native_capture else {"enabled": False}
        if operational and info.get("CosmasConfiguredCapture") != expected_capture:
            parser.error("The operational desktop helper must include matching native recording ownership.")
        valid_identity = (info.get("CosmasNativeAuth") == identity["auth"] and
                          info.get("CosmasNativeIdentity") == identity["identity"] and
                          info.get("CFBundleIdentifier") == identity["bundle"]) if operational else (
                          info.get("CosmasNativeAuth") == {"enabled": False} and
                          re.fullmatch(r"com\.cosmasos\.synthetic\.desktop\.auth\.w[1-9][0-9]*[a-z]?", info.get("CFBundleIdentifier", "")))
        if not valid_identity or info.get("CFBundleExecutable") != "CosmasDesktopAuth":
            parser.error("Use the separately packaged, disabled synthetic auth helper.")
        for path in helper.rglob("*"):
            if path.is_symlink() or path.name.startswith(".env") or path.suffix == ".map":
                parser.error("Native helper cannot contain links or environment/source-map files.")
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        parser.error("Use a fresh output directory outside the read-only Scribe source.")
    if output.is_relative_to(web) or web.is_relative_to(output) or not (web / "index.html").is_file():
        parser.error("Use a separately built synthetic web bundle.")
    files = []
    for path in sorted(web.rglob("*")):
        if path.is_symlink() or path.name.startswith(".env") or path.suffix == ".map":
            parser.error("The web bundle must contain only deployable static assets.")
        if path.is_file():
            files.append(path)
    output.mkdir(parents=True)
    app = output / "app"
    app.mkdir()
    extracted = output / "source"
    extracted.mkdir()
    hashes = {}
    assets = {}
    for file in files:
        relative = file.relative_to(web).as_posix()
        mime = 'text/javascript' if file.suffix == '.js' else mimetypes.guess_type(relative)[0] or 'application/octet-stream'
        assets['/' + relative] = {"file": "public/" + relative, "contentType": mime}
    assets['/'] = assets['/index.html']
    for filename, compiled in SOURCES.items():
        path = "apps/desktop-companion/src/" + filename
        text = subprocess.check_output(["git", "show", f"{SOURCE_REF}:{path}"], cwd=source)
        hashes[path] = hashlib.sha256(text).hexdigest()
        code = text.decode()
        if filename == "electron-app.ts":
            code, count = re.subn(
                r"const RENDERER_ASSETS = Object.freeze\([\s\S]+?\n\}\);",
                "const RENDERER_ASSETS = Object.freeze(" + json.dumps(assets, indent=2) + ");",
                code, count=1,
            )
            if count != 1:
                raise ValueError("Pinned asset resolver no longer matches its reviewed shape.")
            code = code.replace("resolvePackagedRendererAsset", "resolveStaticAsset")
        file = extracted / filename
        file.write_text(code)
        subprocess.run(
            ["node", "-e",
             "const ts=require(process.argv[1]),fs=require('node:fs');"
             "const result=ts.transpileModule(fs.readFileSync(process.argv[2],'utf8'),"
             "{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}});"
             "fs.writeFileSync(process.argv[3],result.outputText);",
             str(root / "web/node_modules/typescript/lib/typescript.js"),
             str(file), str(app / compiled)], check=True,
        )
    for filename in ("main.mjs", "api-proxy.mjs", "close-protection.mjs", "startup-recovery.mjs",
                     "workspace-lifecycle.mjs", "preload.cjs"):
        shutil.copyfile(root / "clients/desktop" / filename, app / filename)
    if args.native_auth_helper:
        native = app / "native-auth"
        destination = native / "CosmasDesktopAuth.app"
        shutil.copytree(helper, destination)
        (native / "manifest.json").write_text(json.dumps({
            "version": 1, "executable": "CosmasDesktopAuth.app/Contents/MacOS/CosmasDesktopAuth",
            "files": {str(p.relative_to(native)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(destination.rglob("*")) if p.is_file()},
        }, indent=2) + "\n")
        for filename in ("auth-helper-client.mjs", "auth-access-store.mjs", "auth-session.mjs",
                         "auth-ipc.mjs", "sign-in-presentation.mjs", "auth-preload.cjs", "workspace-auth-proxy.mjs", "connector-api-routes.mjs",
                         "spawn-auth-helper.mjs", "local-auth-http.mjs", "hosted-auth-http.mjs", "capture-content-security.mjs",
                         "microphone-permissions.mjs", "installation-state.mjs", "native-capture-package.mjs"):
            shutil.copyfile(root / "clients/desktop" / filename, app / filename)
        shutil.copyfile(root / "clients/desktop/cosmaneura-navigation.mjs", app / "cosmaneura-navigation.mjs")
        shutil.copyfile(root / "clients/desktop/native-identity-config.mjs", app / "native-identity-config.mjs")
        shutil.copyfile(root / 'clients/desktop/scheduling-navigation.mjs', app / 'scheduling-navigation.mjs')
        shutil.copyfile(root / 'clients/desktop/google-navigation.mjs', app / 'google-navigation.mjs')
        shutil.copyfile(root / 'clients/desktop/microsoft-navigation.mjs', app / 'microsoft-navigation.mjs')
        _navigation.compose_preload(root, app / "auth-preload.cjs")
        shutil.copyfile(root / "clients/desktop/main-authenticated.mjs", app / "main.mjs")
    if native_capture:
        from native_capture_build import prepare as prepare_native_capture
        prepare_native_capture(root, output, app)
    (app / "package.json").write_text(json.dumps({
        "name": "cosmas-os-beta" if operational else "cosmas-os-synthetic", "version": args.app_version, "private": True,
        "type": "module", "main": "main.mjs", "productName": "CosmaBot" if operational else "CosmasOS Synth",
    }, indent=2) + "\n")
    (app / "synthetic-build.json").write_text(json.dumps({
        "mode": "hosted-beta-authenticated" if hosted else "local-synthetic-authenticated" if args.native_auth_helper else "local-synthetic",
        "apiOrigin": args.hosted_api_origin if hosted else "http://127.0.0.1:8046" if args.native_auth_helper else "http://127.0.0.1:8018",
        **({"dataMode": data_mode} if hosted else {}),
        **({"nativeIdentity": identity["identity"]} if operational else {}),
        **({"nativeCaptureEnabled": native_capture} if operational else {}),
        "appVersion": args.app_version,
        "buildNumber": args.build_number,
        "cosmaneuraWebOrigin": args.cosmaneura_web_origin,
        "googleConnectionClientId": args.google_connection_client_id,
        "googleConnectionCallbackUri": args.google_connection_callback_uri,
        "microsoftConnectionTenantId": args.microsoft_connection_tenant_id,
        "microsoftConnectionClientId": args.microsoft_connection_client_id,
        "microsoftConnectionCallbackUri": args.microsoft_connection_callback_uri,
        'schedulingGoogleClientId': args.scheduling_google_client_id,
        'schedulingGoogleCallbackUri': args.scheduling_google_callback_uri,
        **({"installation": {
            "version": 1, "profile": args.installation_profile,
            "bundleIdentifier": "com.cosmasos.beta.desktop" if operational else "com.cosmasos.synthetic.desktop." + args.installation_profile,
            "storageGeneration": 1, "electronVersion": "43.4.1",
            "rendererPartition": "persist:cosmasos-operational-beta" if operational else "persist:cosmasos-authenticated-local",
            "authHelperBundleIdentifier": info["CFBundleIdentifier"],
        }} if args.installation_profile else {"stateDirectory": str(output / "user-data")}),
        **({"installationRoot": str(installation_root)} if installation_root else {}),
        **({"nativeAuthEnabled": True} if args.native_auth_helper else {}),
        **({"captureUploadOrigins": args.capture_upload_origin} if args.capture_upload_origin else {}),
        **({"microphoneCaptureEnabled": True} if args.microphone_capture else {}),
    }, indent=2) + "\n")
    shutil.copytree(web, app / "public")
    (output / "composition.json").write_text(json.dumps({
        "source_ref": SOURCE_REF, "source_sha256": hashes,
        "purpose": "operational-beta-build-input" if operational else "local-synthetic-unsigned", "electron_version": "43.4.1",
        "composed_sha256": {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in sorted(output.rglob("*")) if path.is_file()},
    }, indent=2) + "\n")
    print(f"Prepared synthetic desktop app: {app}")


if __name__ == "__main__":
    main()
