#!/usr/bin/env python3
"""Compose the OS web bundle with a pinned, read-only Scribe Apple shell.

The output is an isolated, unsigned synthetic build input. This never modifies
Scribe, reads an environment file, contacts a service, or invokes signing.
"""

import argparse
import hashlib
import html
import importlib.util
import io
import json
import plistlib
import re
import shutil
import subprocess
import tarfile
from html.parser import HTMLParser
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

SOURCE_REF = "ea7f99d0278a05706531ffb1288cb1df7acf507b"
SOURCE_PATHS = (
    "apps/capture/ios",
    "apps/capture/native-plugins/ios-pcm-capacitor",
    "apps/capture/native-plugins/ios-pcm-capture",
    "apps/capture/native-plugins/secure-queue",
)
BUNDLE_ID = "com.cosmasos.synthetic"
MINIMUM_IOS_VERSION = "17.0"
SIMULATOR_IDENTITY_PREFIX = "COSMASW8NT"  # Invented local prefix, never an Apple team.
RECOVERY_UI = Path(__file__).parents[1] / "clients/apple/startup-recovery"
RECOVERY_INPUTS = {
    "apps/capture/ios/App/App/SceneDelegate.swift": "738b9b96bb71d34d80cd8c1183cf7f8f6f2e789c64e46fb5fe6777a35ae12dfd",
    "apps/capture/ios/App/App/Base.lproj/Main.storyboard": "7b7dc7acc67134bfaa80e5ce9c9068ba53db5369b9b70248aa7439fc2b09daae",
    "apps/capture/ios/App/App.xcodeproj/project.pbxproj": "8b0b7ddb06c68e5e1ace816c1e33dc3210398cebd80db5a5ed781bed85730912",
}
RECOVERY_SOURCES = ("WorkspaceRecoveryState.swift", "CosmasBridgeViewController.swift",
                    "CosmasWorkspaceViewController.swift", "WorkspaceSceneSignalState.swift")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def include_configured_capture(output: Path) -> dict[str, object]:
    """Replace capture and secure queue sources only in this new composition."""
    owned = Path(__file__).parents[1] / "clients/capture/native-configured"
    manifest = json.loads((owned / "manifest.json").read_text())
    files = manifest["files"]
    packages = {"ios-pcm-capture", "ios-pcm-capacitor", "secure-queue"}
    privacy = Path("secure-queue/ios/Sources/CosmaneuraSecureQueue/PrivacyInfo.xcprivacy")
    destination = output / "apps/capture/native-plugins"
    for name, hashes in files.items():
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or relative.parts[0] not in packages
                or (relative.suffix != ".swift" and relative != privacy) or (owned / relative).is_symlink()
                or digest(owned / relative) != hashes["sha256"]):
            raise ValueError("Configured native source differs from its reviewed input.")
    for package in packages:
        expected = {name for name in files if name.startswith(package + "/")}
        actual = {str(path.relative_to(destination)) for path in (destination / package).rglob("*")
                  if path.is_file() and path.suffix in {".swift", ".xcprivacy"}
                  and "Tests" not in path.relative_to(destination / package).parts}
        if not expected or actual - expected:
            raise ValueError("Unlisted native source would remain in the configured app.")
    for name in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(owned / name, target)
    return manifest


def local_workspace_policy(api_origin: str, upload_origins: tuple[str, ...] = ()) -> dict[str, object]:
    """Opt-in local policy; native fetch retains WebKit's CORS and streaming behavior."""
    def exact_loopback(value: str) -> str:
        match = re.fullmatch(r"http://(?:127\.0\.0\.1|localhost|\[::1\]):([1-9][0-9]{0,4})", value)
        if match is None or int(match[1]) > 65535:
            raise ValueError("Apple workspace policy requires an exact loopback HTTP origin and port.")
        return value

    if not isinstance(upload_origins, tuple) or len(upload_origins) > 4:
        raise ValueError("At most four exact local capture upload origins are permitted.")
    api = exact_loopback(api_origin)
    uploads = tuple(exact_loopback(value) for value in upload_origins)
    if len(set(uploads)) != len(uploads):
        raise ValueError("Duplicate local capture upload origins are not permitted.")
    origins = tuple(dict.fromkeys((api, *uploads)))
    csp = "; ".join((
        "default-src 'none'", "base-uri 'none'", "form-action 'none'", "object-src 'none'",
        "script-src 'self'", "style-src 'self' 'unsafe-inline'", "font-src 'self'",
        "img-src 'self' data: blob:", "media-src 'self' blob:", "worker-src 'self'",
        "frame-src blob:", "connect-src 'self' " + " ".join(origins),
    ))
    return {"version": 1, "purpose": "local-synthetic-only", "page_origin": "capacitor://localhost",
            "api_origin": api, "capture_upload_origins": list(uploads), "content_security_policy": csp,
            "http_transport": "WKWebView.fetch", "capacitor_http_enabled": False,
            "acceptance": "source-policy-only; actual WebKit/device acceptance remains required"}


def hosted_workspace_policy(api_origin: str, upload_origins: tuple[str, ...] = ()) -> dict[str, object]:
    """TLS-only hosted service/storage; retain normal WebKit request semantics."""
    def exact_https(value: str) -> str:
        if (not isinstance(value, str) or len(value) > 253
                or re.fullmatch(r"https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", value) is None
                or value.endswith(".localhost") or re.fullmatch(r"https://\d+(?:\.\d+){3}", value)):
            raise ValueError("Hosted Apple policy requires exact HTTPS service origins.")
        return value
    if not isinstance(upload_origins, tuple) or len(upload_origins) > 4 or len(set(upload_origins)) != len(upload_origins):
        raise ValueError("At most four distinct hosted capture upload origins are permitted.")
    api = exact_https(api_origin)
    uploads = tuple(exact_https(value) for value in upload_origins)
    policy = local_workspace_policy("http://127.0.0.1:8046")
    policy.update(purpose="hosted-synthetic-beta", api_origin=api, capture_upload_origins=list(uploads))
    policy["content_security_policy"] = str(policy["content_security_policy"]).replace(
        "http://127.0.0.1:8046", " ".join(dict.fromkeys((api, *uploads))))
    return policy


def workspace_policy_html(source: str, policy: dict[str, object]) -> str:
    """Place policy before bundled resources; never silently replace another policy."""
    class Inspect(HTMLParser):
        heads = 0
        blocked = False
        insertion = 0

        def handle_starttag(self, tag, attrs):
            if tag == "head":
                self.heads += 1
                line, column = self.getpos()
                self.insertion = sum(len(value) for value in source.splitlines(keepends=True)[:line - 1]) + column + len(self.get_starttag_text())
            if tag == "base" or tag == "meta" and any(
                name == "http-equiv" and (value or "").lower() == "content-security-policy" for name, value in attrs
            ) or not self.heads and tag in {"script", "link", "img", "iframe", "body"}:
                self.blocked = True

    parser = Inspect()
    parser.feed(source)
    if len(source.encode("utf-8")) > 1048576 or parser.heads != 1 or parser.blocked:
        raise ValueError("Apple workspace policy requires one unconfigured document head and no base URL.")
    content = html.escape(str(policy["content_security_policy"]), quote=True)
    return source[:parser.insertion] + '\n    <meta http-equiv="Content-Security-Policy" content="' + content + '" />' + source[parser.insertion:]


def include_recovery_ui(output: Path) -> dict[str, object]:
    """Add the native recovery container only to an exact, unfinalized archive."""
    output = output.resolve()
    if (output / "composition.json").exists() or (output / ".git").exists():
        raise ValueError("Recovery UI requires a fresh source archive.")
    app = output / "apps/capture/ios/App/App"
    for name, expected in RECOVERY_INPUTS.items():
        path = output / name
        if path.resolve() != path or not path.is_file() or digest(path) != expected:
            raise ValueError(f"Recovery UI source base changed: {name}")
    for name in RECOVERY_SOURCES:
        if (app / name).exists() or (app / name).is_symlink():
            raise ValueError("Recovery UI would replace independent source work.")
    sources = {name: (RECOVERY_UI / name).read_bytes()
               for name in (*RECOVERY_SOURCES, "SceneDelegate.swift")}
    project = app.parent / "App.xcodeproj/project.pbxproj"
    text = project.read_text()
    # Exact pinned anchors keep these additions out of other targets or phases.
    for index, name in enumerate(RECOVERY_SOURCES, 1):
        file_id = f"C03100000000000000000{index:03d}"
        build_id = f"C03110000000000000000{index:03d}"
        if file_id in text or build_id in text:
            raise ValueError("Unexpected Apple recovery project identity.")
        replacements = {
            "/* End PBXBuildFile section */": f'\t\t{build_id} /* {name} in Sources */ = {{isa = PBXBuildFile; fileRef = {file_id} /* {name} */; }};\n',
            "/* End PBXFileReference section */": f'\t\t{file_id} /* {name} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {name}; sourceTree = "<group>"; }};\n',
            '\t\t\t\t9582B6822FE993A50072D4E8 /* SceneDelegate.swift */,': f'\t\t\t\t{file_id} /* {name} */,\n',
            '\t\t\t\t9582B6832FE993A70072D4E8 /* SceneDelegate.swift in Sources */,': f'\t\t\t\t{build_id} /* {name} in Sources */,\n',
        }
        for anchor, addition in replacements.items():
            if text.count(anchor) != 1:
                raise ValueError("Unexpected Apple recovery project anchors.")
            text = text.replace(anchor, addition + anchor)
    storyboard = app / "Base.lproj/Main.storyboard"
    markup = storyboard.read_text().replace(
        'customClass="CAPBridgeViewController" customModule="Capacitor"',
        'customClass="CosmasWorkspaceViewController" customModule="App" customModuleProvider="target"',
    )
    for name, data in sources.items():
        (app / name).write_bytes(data)
    project.write_text(text)
    storyboard.write_text(markup)
    changed = (*RECOVERY_INPUTS, *(str((app / name).relative_to(output)) for name in RECOVERY_SOURCES))
    return {"source_ref": SOURCE_REF,
            "files": {name: {"before": RECOVERY_INPUTS.get(name), "after": digest(output / name)} for name in changed}}


def build_identity(verification_variant: str | None = None) -> tuple[str, str]:
    if verification_variant is None:
        return BUNDLE_ID, "CosmasOS Synth"
    if not re.fullmatch(r"w[1-9][0-9]*[a-z]?", verification_variant):
        raise ValueError("Verification variant must be a milestone such as w8m.")
    return f"{BUNDLE_ID}.{verification_variant}", f"CosmasOS Synth {verification_variant.upper()}"


def simulator_custody_identity(verification_variant: str | None) -> dict[str, object]:
    if verification_variant is None:
        raise ValueError("Simulator custody requires a separate verification variant.")
    bundle_id, _ = build_identity(verification_variant)
    identity = f"{SIMULATOR_IDENTITY_PREFIX}.{bundle_id}"
    return {
        "application-identifier": identity,
        "com.apple.developer.team-identifier": SIMULATOR_IDENTITY_PREFIX,
        "keychain-access-groups": [identity],
    }


def prepare(
    source: Path, web: Path, output: Path, verification_variant: str | None = None,
    native_auth_clerk_archive: Path | None = None,
    simulator_custody: bool = False,
    renewable_native_capture: bool = False,
    app_version: str = "0.1.0", build_number: str = "1",
    native_renderer_recovery: bool = False,
    workspace_api_origin: str | None = None,
    capture_upload_origins: tuple[str, ...] = (),
    cosmaneura_web_origin: str = "",
    hosted_workspace: bool = False,
    scheduling_google_client_id: str = "", scheduling_google_callback_uri: str = "",
    microsoft_connection_tenant_id: str = "", microsoft_connection_client_id: str = "", microsoft_connection_callback_uri: str = "",
    google_connection_client_id: str = "", google_connection_callback_uri: str = "",
    native_identity_config: Path | None = None,
    data_mode: str | None = None,
) -> Path:
    identity = _identity.load(native_identity_config, "apple", workspace_api_origin)
    operational = identity is not None
    if operational and (not hosted_workspace or verification_variant is not None or simulator_custody):
        raise ValueError("Operational Apple composition requires hosted services and device custody, without a synthetic variant or Simulator identity.")
    data_mode = _identity.data_mode(identity, data_mode)
    _navigation.validate_google(google_connection_client_id, google_connection_callback_uri)
    if google_connection_client_id and (native_auth_clerk_archive is None or not native_renderer_recovery):
        raise ValueError("Google connection requires the authenticated native host.")
    _navigation.validate_microsoft(microsoft_connection_tenant_id, microsoft_connection_client_id, microsoft_connection_callback_uri)
    if microsoft_connection_tenant_id and (native_auth_clerk_archive is None or not native_renderer_recovery):
        raise ValueError("Microsoft connection requires the authenticated native host.")
    _navigation.validate_scheduling(scheduling_google_client_id, scheduling_google_callback_uri)
    if scheduling_google_client_id and (native_auth_clerk_archive is None or not native_renderer_recovery):
        raise ValueError("Scheduling sign-in requires the authenticated native host.")
    _navigation.validate_origin(cosmaneura_web_origin)
    if cosmaneura_web_origin and (native_auth_clerk_archive is None or not native_renderer_recovery):
        raise ValueError("Cosmaneura navigation requires the native auth and recovery host composition.")
    if native_renderer_recovery and not renewable_native_capture:
        raise ValueError("Native renderer recovery requires the renewable native capture overlay.")
    if capture_upload_origins and workspace_api_origin is None:
        raise ValueError("Capture upload origins require the explicit Apple workspace policy.")
    if workspace_api_origin is not None and verification_variant is None and not operational:
        raise ValueError("Apple workspace policy requires a separate verification variant.")
    if hosted_workspace:
        manifest = json.loads((web / "cosmas-workspace-build.json").read_text())
        if (workspace_api_origin is None or native_auth_clerk_archive is None
                or manifest != {"version": 1, "client": "apple", "dataMode": data_mode,
                                "apiOrigin": workspace_api_origin, "apiBase": workspace_api_origin,
                                "pageOrigin": "capacitor://localhost"}):
            raise ValueError("Hosted composition requires the matching Apple web build and native sign-in adapter.")
    elif (web / "cosmas-workspace-build.json").exists():
        raise ValueError("A hosted web build requires explicit hosted composition.")
    feature_manifest = None
    if hosted_workspace:
        feature_manifest = _beta.validate_native(web, client="apple", apiOrigin=workspace_api_origin,
                              coreWebOrigin=cosmaneura_web_origin,
                              captureUploadOrigins=list(capture_upload_origins),
                              renewableNativeCapture=renewable_native_capture,
                              nativeRendererRecovery=native_renderer_recovery,
                              simulatorCustody=simulator_custody, deviceCustody=operational)
    staging = feature_manifest is not None and feature_manifest["profile"] == _beta.NATIVE_STAGING_PROFILE
    if staging and (not operational or data_mode != "synthetic"):
        raise ValueError("First-owner staging requires the operational native identity and synthetic data.")
    if staging and any((google_connection_client_id, google_connection_callback_uri,
                        microsoft_connection_tenant_id, microsoft_connection_client_id,
                        microsoft_connection_callback_uri, scheduling_google_client_id,
                        scheduling_google_callback_uri)):
        raise ValueError("External account connections are disabled for first-owner staging.")
    policy = ((hosted_workspace_policy if hosted_workspace else local_workspace_policy)(workspace_api_origin, capture_upload_origins)
              if workspace_api_origin is not None else None)
    if operational:
        policy["purpose"] = "operational-beta-build-input"
    if (not re.fullmatch(r"(?:0|[1-9][0-9]{0,3})(?:\.(?:0|[1-9][0-9]{0,3})){2}", app_version)
            or not re.fullmatch(r"[1-9][0-9]{0,3}", build_number)):
        raise ValueError("Use a numeric three-part app version and a build number from 1 to 9999.")
    bundle_id, display_name = (identity["bundle"], "CosmaBot") if operational else build_identity(verification_variant)
    simulator_identity = simulator_custody_identity(verification_variant) if simulator_custody else None
    source, web, output = source.resolve(), web.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Output must not exist; use a fresh isolated build directory.")
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Output must be separate from the read-only source checkout.")
    if output.is_relative_to(web) or web.is_relative_to(output):
        raise ValueError("Output must be separate from the web bundle.")
    if not (web / "index.html").is_file():
        raise ValueError("Build the synthetic OS web bundle first.")
    for path in web.rglob("*"):
        if path.is_symlink() or path.name.startswith(".env") or path.suffix == ".map":
            raise ValueError("The web bundle must contain only deployable static assets.")
    policy_index = workspace_policy_html((web / "index.html").read_text(), policy) if policy else None
    archive = subprocess.check_output(
        ["git", "archive", "--format=tar", SOURCE_REF, *SOURCE_PATHS], cwd=source
    )
    output.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
        if any(member.issym() or member.islnk() for member in contents.getmembers()):
            raise ValueError("Unexpected links in the pinned client source.")
        contents.extractall(output, filter="data")
    original = {
        str(path.relative_to(output)): digest(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    native_capture_overlay = None
    native_renderer_overlay = None
    native_recovery_ui = None
    if renewable_native_capture:
        spec = importlib.util.spec_from_file_location(
            "native_capture_overlay", Path(__file__).with_name("apply-native-capture-overlay.py")
        )
        if spec is None or spec.loader is None:
            raise ValueError("Native capture overlay is unavailable.")
        overlay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(overlay)
        native_capture_overlay = overlay.apply(output, SOURCE_REF)
        if native_renderer_recovery:
            spec = importlib.util.spec_from_file_location(
                "native_renderer_overlay", Path(__file__).with_name("apply-native-renderer-recovery-overlay.py")
            )
            if spec is None or spec.loader is None:
                raise ValueError("Native renderer recovery overlay is unavailable.")
            renderer_overlay = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(renderer_overlay)
            native_renderer_overlay = renderer_overlay.apply(output, SOURCE_REF)
            native_recovery_ui = include_recovery_ui(output)
    app = output / "apps/capture/ios/App/App"
    # Replace only the inherited catalog in this fresh, isolated shell copy.
    # iOS applies its own corner mask to the opaque square artwork.
    app_icon = app / "Assets.xcassets/AppIcon.appiconset"
    shutil.rmtree(app_icon)
    shutil.copytree(Path(__file__).parents[1] / "clients/shared/branding/AppIcon.appiconset", app_icon)
    project = app.parent / "App.xcodeproj/project.pbxproj"
    text = project.read_text()
    text = re.sub(r"DEVELOPMENT_TEAM = [^;]+;", 'DEVELOPMENT_TEAM = "";', text)
    text = text.replace(
        "PRODUCT_BUNDLE_IDENTIFIER = com.cosmaneura.capture;",
        f"PRODUCT_BUNDLE_IDENTIFIER = {bundle_id};",
    )
    text, deployment_targets = re.subn(
        r"IPHONEOS_DEPLOYMENT_TARGET = [^;]+;",
        f"IPHONEOS_DEPLOYMENT_TARGET = {MINIMUM_IOS_VERSION};",
        text,
    )
    if deployment_targets != 4:
        raise ValueError("Pinned Apple project has unexpected deployment-target declarations.")
    for key, value in (("MARKETING_VERSION", app_version), ("CURRENT_PROJECT_VERSION", build_number)):
        text, count = re.subn(rf"{key} = [^;]+;", f"{key} = {value};", text)
        if count != 2:
            raise ValueError("Pinned Apple project has unexpected product-version declarations.")
    if simulator_identity is not None:
        # Xcode's Embedded-Simulator.xcspec embeds this in the Mach-O section.
        # Restricted simulator entitlements cannot go in an ad-hoc signature.
        # Scope to the app target and simulator SDK, never package libraries or devices.
        marker = "INFOPLIST_FILE = App/Info.plist;"
        if text.count(marker) != 2 or "LD_ENTITLEMENTS_SECTION" in text:
            raise ValueError("Pinned Apple app has unexpected entitlement settings.")
        text = text.replace(marker, marker + '\n\t\t\t\t"LD_ENTITLEMENTS_SECTION[sdk=iphonesimulator*]" = "$(SRCROOT)/App/CosmasSimulator.entitlements";')
        (app / "CosmasSimulator.entitlements").write_bytes(plistlib.dumps(simulator_identity))
    if operational:
        marker = "INFOPLIST_FILE = App/Info.plist;"
        if text.count(marker) != 2 or "CODE_SIGN_ENTITLEMENTS" in text or "SUPPORTED_PLATFORMS" in text:
            raise ValueError("Pinned Apple app has unexpected device-signing settings.")
        text = text.replace(marker, marker + '\n\t\t\t\tSUPPORTED_PLATFORMS = iphoneos;\n\t\t\t\tCODE_SIGN_ENTITLEMENTS = App/CosmasDevice.entitlements;')
        # Provisioning supplies the actual AppIdentifierPrefix at the later signing
        # step. Never put an invented Simulator team identity in a device product.
        (app / "CosmasDevice.entitlements").write_bytes(plistlib.dumps({
            "keychain-access-groups": ["$(AppIdentifierPrefix)$(PRODUCT_BUNDLE_IDENTIFIER)"],
        }))
    project.write_text(text)
    package_path = app.parent / "CapApp-SPM/Package.swift"
    package = package_path.read_text()
    if package.count("platforms: [.iOS(.v15)]") != 1:
        raise ValueError("Pinned Apple package has an unexpected platform declaration.")
    package_path.write_text(package.replace("platforms: [.iOS(.v15)]", "platforms: [.iOS(.v17)]"))
    info_path = app / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    if native_renderer_recovery:
        # SceneDelegate creates the one recovery-owned bridge. Avoid UIKit
        # instantiating a second storyboard bridge before scene connection.
        info.pop("UIMainStoryboardFile", None)
        scenes = info["UIApplicationSceneManifest"]["UISceneConfigurations"]["UIWindowSceneSessionRoleApplication"]
        for scene in scenes:
            scene.pop("UISceneStoryboardFile", None)
    info["CFBundleDisplayName"] = display_name
    info["NSMicrophoneUsageDescription"] = (
        "Cosmas records visit audio after you confirm consent and choose Start recording."
        if operational else "Record an invented encounter only after you explicitly start a synthetic capture test."
    )
    info["NSAppTransportSecurity"] = {} if hosted_workspace else {"NSAllowsLocalNetworking": True}
    info_path.write_bytes(plistlib.dumps(info, sort_keys=False))
    (app / "capacitor.config.json").write_text(
        json.dumps(
            {
                "appId": bundle_id,
                "appName": display_name,
                "webDir": "public",
                "loggingBehavior": "none",
                "packageClassList": ["IOSPCMCapacitorPlugin", "SecureQueuePlugin"],
                **({"server": {"hostname": "localhost", "iosScheme": "capacitor"},
                    "plugins": {"CapacitorHttp": {"enabled": False}}} if policy else {}),
            },
            indent=2,
        ) + "\n"
    )
    (app / "config.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<widget xmlns="http://www.w3.org/ns/widgets" id="{bundle_id}" version="{app_version}"/>\n'
    )
    public = app / "public"
    if public.exists():
        raise ValueError("Pinned shell unexpectedly contains a generated web bundle.")
    shutil.copytree(web, public)
    if policy_index is not None:
        (public / "index.html").write_text(policy_index)
    configured_native = None
    if native_auth_clerk_archive is not None:
        # Compile the local auth adapter without configuring or initializing Clerk.
        spec = importlib.util.spec_from_file_location(
            "native_auth_proof", Path(__file__).with_name("prepare-native-auth-proof.py")
        )
        if spec is None or spec.loader is None:
            raise ValueError("Native auth composer is unavailable.")
        composer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(composer)
        # The auth host and existing PCM plugin must resolve the same audio
        # package. Including the code does not enable capture in a disabled app.
        configured_native = include_configured_capture(output)
        composer.prepare(native_auth_clerk_archive,
                         output / "apps/capture/native-plugins/cosmas-native-auth", include_bridge=True,
                         shared_capture_packages=True)
        package = package_path.read_text()
        package = package.replace(
            '    dependencies: [\n',
            '    dependencies: [\n'
            '        .package(name: "CosmasNativeAuthQualification", '
            'path: "../../../native-plugins/cosmas-native-auth"),\n',
            1,
        ).replace(
            '            dependencies: [\n',
            '            dependencies: [\n'
            '                .product(name: "CosmasWorkspaceAuthPlugin", '
            'package: "CosmasNativeAuthQualification"),\n',
            1,
        )
        package_path.write_text(package)
        info["CosmasNativeAuth"] = identity["auth"] if operational else {"enabled": False}
        if operational:
            info["CosmasNativeIdentity"] = identity["identity"]
            info["CosmasConfiguredCapture"] = {"enabled": False} if staging else {"enabled": True, "apiOrigin": workspace_api_origin}
            info["CosmasSourceAccessGroup"] = "$(AppIdentifierPrefix)" + bundle_id
            info["CFBundleURLTypes"] = [{"CFBundleURLName": bundle_id, "CFBundleURLSchemes": [bundle_id]}]
        info["CosmaneuraWebOrigin"] = cosmaneura_web_origin
        info["GoogleConnectionClientID"] = google_connection_client_id
        info["GoogleConnectionCallbackURI"] = google_connection_callback_uri
        info["MicrosoftConnectionTenantID"] = microsoft_connection_tenant_id
        info["MicrosoftConnectionClientID"] = microsoft_connection_client_id
        info["MicrosoftConnectionCallbackURI"] = microsoft_connection_callback_uri
        info["SchedulingGoogleClientID"] = scheduling_google_client_id
        info["SchedulingGoogleCallbackURI"] = scheduling_google_callback_uri
        info_path.write_bytes(plistlib.dumps(info, sort_keys=False))
        config_path = app / "capacitor.config.json"
        config = json.loads(config_path.read_text())
        config["packageClassList"].append("CosmasWorkspaceAuthPlugin")
        config_path.write_text(json.dumps(config, indent=2) + "\n")
    manifest = {
        "purpose": "operational-beta-build-input" if operational else "local-synthetic-unsigned",
        "source_ref": SOURCE_REF,
        "source_paths": SOURCE_PATHS,
        "bundle_id": bundle_id,
        "app_version": app_version,
        "build_number": build_number,
        "minimum_ios_version": MINIMUM_IOS_VERSION,
        "verification_variant": verification_variant,
        "native_auth": "configured-operational" if operational else "compiled-disabled" if native_auth_clerk_archive else "not-included",
        "configured_native_capture": configured_native,
        "device_custody": {"enabled": operational, "requires_provisioning": operational},
        "local_workspace_policy": policy,
        "renewable_native_capture": native_capture_overlay,
        "native_renderer_recovery": native_renderer_overlay,
        "native_recovery_ui": native_recovery_ui,
        "simulator_custody": {
            "enabled": simulator_identity is not None,
            "entitlement_location": "__TEXT,__entitlements" if simulator_identity else None,
            "sdk": "iphonesimulator" if simulator_identity else None,
            "identity_prefix": SIMULATOR_IDENTITY_PREFIX if simulator_identity else None,
        },
        "source_sha256": original,
        "composed_sha256": {
            str(path.relative_to(output)): digest(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    (output / "composition.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return project.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scribe-source", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verification-variant", help="Separate bundle and app storage, e.g. w8m")
    parser.add_argument("--app-version", default="0.1.0", help="Numeric product version")
    parser.add_argument("--build-number", default="1", help="Positive local build number, at most four digits")
    parser.add_argument("--native-auth-clerk-archive", type=Path,
                        help="Pinned public 1.5.5 archive; compile the disabled native auth adapter")
    parser.add_argument("--cosmaneura-web-origin", default="",
                        help="Exact approved HTTPS Core web origin; record navigation is disabled when empty")
    parser.add_argument("--scheduling-google-client-id", default="")
    parser.add_argument("--scheduling-google-callback-uri", default="")
    parser.add_argument("--google-connection-client-id", default="")
    parser.add_argument("--google-connection-callback-uri", default="")
    parser.add_argument("--microsoft-connection-tenant-id", default="")
    parser.add_argument("--microsoft-connection-client-id", default="")
    parser.add_argument("--microsoft-connection-callback-uri", default="")
    parser.add_argument("--simulator-custody", action="store_true",
                        help="Embed local test identity for simulator key persistence; requires a verification variant")
    parser.add_argument("--renewable-native-capture", action="store_true",
                        help="Apply the exact pinned native authority/renewal overlay; default off")
    parser.add_argument("--native-renderer-recovery", action="store_true",
                        help="Include native startup/renderer recovery; requires renewable native capture")
    parser.add_argument("--workspace-api-origin",
                        help="Opt-in Apple CSP for one exact loopback API origin; requires a separate variant")
    parser.add_argument("--capture-upload-origin", action="append", default=[],
                        help="Exact loopback ciphertext upload origin for the opt-in Apple CSP; at most four")
    parser.add_argument("--hosted-workspace", action="store_true",
                        help="Use HTTPS service policy matching the hosted synthetic Apple web build")
    parser.add_argument("--native-identity-config", type=Path, help="Explicit public operational identity; stages a device-only project")
    parser.add_argument("--data-mode", choices=("synthetic", "authorized_beta"), help="Explicit hosted data classification; synthetic for staging with a real identity")
    args = parser.parse_args()
    try:
        project = prepare(args.scribe_source, args.web_dist, args.output, args.verification_variant,
                          args.native_auth_clerk_archive, args.simulator_custody,
                          args.renewable_native_capture, args.app_version, args.build_number,
                          args.native_renderer_recovery, args.workspace_api_origin, tuple(args.capture_upload_origin),
                          args.cosmaneura_web_origin, args.hosted_workspace,
                          args.scheduling_google_client_id, args.scheduling_google_callback_uri,
                          args.microsoft_connection_tenant_id, args.microsoft_connection_client_id, args.microsoft_connection_callback_uri,
                          args.google_connection_client_id, args.google_connection_callback_uri, args.native_identity_config, args.data_mode)
    except ValueError as error:
        parser.exit(2, f"{error}\n")
    print(f"Prepared synthetic Apple project: {project}")
    print("Source is unchanged. Build with CODE_SIGNING_ALLOWED=NO; do not use for release.")


if __name__ == "__main__":
    main()
