#!/usr/bin/env python3
"""Prepare owned iPhone project/assets from committed source and public inputs.

This Mac-only operator never compiles native code, signs, installs, downloads,
or releases. A failed attempt retains its fresh output and .incomplete marker.
"""

import argparse
import ast
import copy
import datetime
import hashlib
import html
import importlib.util
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path

OPERATOR = "scripts/prepare-owned-iphone-candidate.py"
RETAINED_FIELDS = ("CosmasSourceAccessGroup", "GoogleConnectionClientID", "GoogleConnectionCallbackURI")
INFO_LIMIT = 524288
NETWORK_DENY = "(version 1)(allow default)(deny network*)"

# One shared Infos schema with Mac auth-helper packaging; do not re-inline pins.
_practice_spec = importlib.util.spec_from_file_location(
    "native_practice_connection_info", Path(__file__).with_name("native_practice_connection_info.py"))
_practice = importlib.util.module_from_spec(_practice_spec)
_practice_spec.loader.exec_module(_practice)
PRACTICE_KEY = _practice.PRACTICE_KEY
native_practice_configuration = _practice.native_practice_configuration

_auth_profile_spec = importlib.util.spec_from_file_location(
    "native_iphone_auth_profile", Path(__file__).with_name("native_iphone_auth_profile.py"))
_auth_profile = importlib.util.module_from_spec(_auth_profile_spec)
_auth_profile_spec.loader.exec_module(_auth_profile)
INSTALLATION_PROFILES = _auth_profile.INSTALLATION_PROFILES
PRODUCTION_INSTALLATION_PROFILE = _auth_profile.PRODUCTION_INSTALLATION_PROFILE
apply_installation_profile_to_configured_info = _auth_profile.apply_installation_profile_to_configured_info
production_native_auth_stamp = _auth_profile.production_native_auth_stamp
require_installation_profile_origins = _auth_profile.require_installation_profile_origins
PRODUCTION_ORIGINS = _auth_profile.PRODUCTION_ORIGINS
STAGING_ORIGINS = _auth_profile.STAGING_ORIGINS


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular(path, limit=None):
    if path.is_symlink() or not path.is_file() or (limit is not None and path.stat().st_size > limit):
        raise ValueError("Use a bounded regular public input file, not a symlink.")
    return path.resolve()


def public_json(path, limit=16384):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate public configuration fields are not permitted.")
            value[key] = item
        return value

    value = json.loads(regular(path, limit).read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Use one public configuration object.")
    return value


def retained_info(path, is_ipa=False):
    path = regular(path, None if is_ipa else INFO_LIMIT)
    if is_ipa:
        with zipfile.ZipFile(path) as archive:
            matches = [item for item in archive.infolist()
                       if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", item.filename)]
            if (len(matches) != 1 or matches[0].file_size > INFO_LIMIT
                    or matches[0].flag_bits & 1):
                raise ValueError("Retain exactly one bounded app Info.plist in the original IPA.")
            raw = archive.read(matches[0])
            member = matches[0].filename
    else:
        raw = path.read_bytes()
        member = None
    value = plistlib.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("The retained public app Info must be a dictionary.")
    return value, {"path": str(path), "sha256": digest(path), "info_member": member,
                   "info_sha256": hashlib.sha256(raw).hexdigest()}


def load_module(repository, name):
    path = repository / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(
        "owned_candidate_" + name.replace("-", "_"), path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configured_info(before, retained, identity, practice=None, validate_google=None):
    """Carry only reviewed legacy public fields, never other IPA app settings."""
    if (retained.get("CFBundleIdentifier") != identity["bundle"]
            or before.get("CFBundleIdentifier") not in {identity["bundle"], "$(PRODUCT_BUNDLE_IDENTIFIER)"}
            or retained.get("CosmasNativeIdentity") != identity["identity"]
            or retained.get("CosmasNativeAuth") != identity["auth"]):
        raise ValueError("Public identity must exactly match the retained existing Beta app.")
    group = retained.get("CosmasSourceAccessGroup")
    if (not isinstance(group, str) or len(group) > 255
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", group) is None):
        raise ValueError("Retain the existing app's exact source access group.")
    google_keys = RETAINED_FIELDS[1:]
    if any(key in retained for key in google_keys) and not all(key in retained for key in google_keys):
        raise ValueError("Retain both Google public navigation fields or omit both.")
    if all(key in retained for key in google_keys):
        if not all(isinstance(retained[key], str) for key in google_keys):
            raise ValueError("Google navigation fields must be public strings.")
        if validate_google is None:
            raise ValueError("Owned Google navigation validation is required.")
        validate_google(*(retained[key] for key in google_keys))
    result = copy.deepcopy(before)
    result.update(CosmasNativeIdentity=copy.deepcopy(identity["identity"]),
                  CosmasNativeAuth=copy.deepcopy(identity["auth"]))
    for key in RETAINED_FIELDS:
        result.pop(key, None)
        if key in retained:
            result[key] = retained[key]
    # A previously configured IPA is evidence, not permission to enable a new
    # account realm. The optional public file is the only entry for this key.
    result.pop(PRACTICE_KEY, None)
    if practice is not None:
        result[PRACTICE_KEY] = native_practice_configuration(practice)
    allowed = {"CosmasNativeIdentity", "CosmasNativeAuth", *RETAINED_FIELDS, PRACTICE_KEY}
    if any(before.get(key) != result.get(key) for key in (before.keys() | result.keys()) - allowed):
        raise ValueError("Candidate configuration changed an unrelated scaffold setting.")
    return result


def output_path(requested, protected):
    requested = requested.absolute()
    if requested.name in {"", ".", ".."} or not requested.parent.is_dir():
        raise ValueError("Use a fresh output directory with an existing parent.")
    output = requested.parent.resolve() / requested.name
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists; select a new directory.")
    for path in protected:
        resolved = path.resolve()
        if output == resolved or output.is_relative_to(resolved) or resolved.is_relative_to(output):
            raise ValueError("Keep output separate from source and public inputs.")
    return output


def git(repository, *args):
    return subprocess.check_output(["git", *args], cwd=repository)


def source_snapshot(repository):
    status = git(repository, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if status:
        raise ValueError("Commit the reviewed source before candidate preparation; the tree must be clean.")
    commit = git(repository, "rev-parse", "HEAD").decode().strip()
    tree = git(repository, "rev-parse", "HEAD^{tree}").decode().strip()
    operator = regular(repository / OPERATOR)
    if (Path(__file__).resolve() != operator
            or hashlib.sha256(git(repository, "show", commit + ":" + OPERATOR)).hexdigest() != digest(operator)):
        raise ValueError("Run the operator from the selected committed repository.")
    return {"repository": str(repository), "commit": commit, "tree": tree, "clean": True,
            "operator_sha256": digest(operator)}


def inventory(root):
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Generated output contains an unexpected symlink.")
        if path.is_file():
            files.append({"path": str(path.relative_to(root)), "sha256": digest(path), "bytes": path.stat().st_size})
    return files


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, indent=2)
        stream.write("\n")


def stage(repository, output, name, command, env):
    log = output / (name + ".private.log")
    with log.open("xb") as stream:
        os.chmod(log, 0o600)
        result = subprocess.run(["/usr/bin/sandbox-exec", "-p", NETWORK_DENY, *command],
                                cwd=repository, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=600)
    receipt = {"stage": name, "exit_code": result.returncode, "network_denied": True,
               "private_log": log.name, "log_sha256": digest(log)}
    save(output / (name + "-execution.json"), receipt)
    if result.returncode:
        raise ValueError("Local preparation stage failed; inspect its private log.")
    return receipt


def composition_bindings(repository, source, blueprint):
    composition = public_json(blueprint / "composition.json", 1048576)
    bindings = []
    scaffold = blueprint / "apps/capture"
    for item in composition["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Composition contains an unsafe destination.")
        destination = regular(scaffold / relative)
        if digest(destination) != item["sha256"]:
            raise ValueError("Composed bytes differ from the exact owned source manifest.")
        if item["role"] == "derived-app-resource-wiring":
            counterpart = "apps/capture/" + item["path"]
            original = git(repository, "show", source["commit"] + ":" + counterpart)
            without_privacy = b"".join(line for line in destination.read_bytes().splitlines(keepends=True)
                                       if b"PrivacyInfo.xcprivacy" not in line)
            if (hashlib.sha256(original).hexdigest() != item["scaffold_input_sha256"]
                    or without_privacy != original
                    or digest(repository / item["derivation_source"]) != item["derivation_source_sha256"]):
                raise ValueError("Derived privacy wiring differs from the unchanged frozen source.")
        elif item["role"] == "derived-capacitor-localization":
            counterpart = item.get("localization_input")
            if not isinstance(counterpart, str) or counterpart == "":
                raise ValueError("Capacitor localization lost its committed input path.")
            original = git(repository, "show", source["commit"] + ":" + counterpart)
            if (hashlib.sha256(original).hexdigest() != item["scaffold_input_sha256"]
                    or digest(repository / item["derivation_source"]) != item["derivation_source_sha256"]):
                raise ValueError("Derived Capacitor localization drifted from the committed input.")
            compose = load_module(repository, "compose-portable-iphone")
            text = original.decode("utf-8")
            if item["path"].endswith("Package.resolved"):
                value = json.loads(text)
                if (not isinstance(value.get("pins"), list) or len(value["pins"]) != 1
                        or "capacitor-swift-pm" not in json.dumps(value)):
                    raise ValueError("Frozen Package.resolved is not the reviewed Capacitor pin.")
                expected = {"pins": [], "version": value.get("version", 2)}
                if json.loads(destination.read_text(encoding="utf-8")) != expected:
                    raise ValueError("Localized Package.resolved is not the owned empty pin set.")
            else:
                localized = compose._localize_capacitor_package_text(
                    text, item["localized_capacitor_path"]
                )
                if destination.read_text(encoding="utf-8") != localized:
                    raise ValueError("Localized Capacitor Package.swift differs from the owned rewrite.")
            if "https://github.com/ionic-team/capacitor-swift-pm.git" in destination.read_text(encoding="utf-8"):
                raise ValueError("Localized Capacitor inputs still name the remote package URL.")
        elif item["role"] == "derived-production-native-auth":
            counterpart = "apps/capture/" + item["path"]
            original = git(repository, "show", source["commit"] + ":" + counterpart)
            auth_profile_source = item.get("auth_profile_source")
            if (not isinstance(auth_profile_source, str) or auth_profile_source == ""
                    or hashlib.sha256(original).hexdigest() != item["scaffold_input_sha256"]
                    or digest(repository / item["derivation_source"]) != item["derivation_source_sha256"]
                    or digest(repository / auth_profile_source) != item.get("auth_profile_source_sha256")):
                raise ValueError("Production native auth stamp drifted from the frozen Info.plist.")
            expected = production_native_auth_stamp(plistlib.loads(original))
            if plistlib.loads(destination.read_bytes()) != expected:
                raise ValueError("Production native auth stamp does not match the reviewed origin set.")
        else:
            counterpart = ("apps/capture/" + item["path"]
                           if item["role"] in {"app-scaffold", "scaffold-package-wiring"}
                           else item["authoritative_counterpart"])
            original = git(repository, "show", source["commit"] + ":" + counterpart)
            if hashlib.sha256(original).hexdigest() != item["sha256"]:
                raise ValueError("Owned composition is not bound to the selected Git commit.")
        bindings.append({"destination": item["path"], "role": item["role"],
                         "source": counterpart, "source_sha256": hashlib.sha256(original).hexdigest(),
                         "destination_sha256": item["sha256"]})
    return composition, bindings


def workspace_policy(repository, api_origin, upload_origins):
    """Load only the existing pure CSP functions, never a historical composer."""
    path = repository / "scripts/prepare-apple-synthetic.py"
    names = {"local_workspace_policy", "hosted_workspace_policy", "workspace_policy_html"}
    selected = [node for node in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in selected} != names or len(selected) != 3:
        raise ValueError("The reviewed pure workspace CSP helpers changed.")
    namespace = {"re": re, "html": html, "HTMLParser": HTMLParser}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    policy = namespace["hosted_workspace_policy"](api_origin, upload_origins)
    return policy, namespace["workspace_policy_html"]


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--inputs", type=Path, required=True, help="Explicit retained public client input directory")
    retained = parser.add_mutually_exclusive_group(required=True)
    retained.add_argument("--retained-ipa", type=Path, help="Original existing CosmaBot app IPA; reads only its public Info")
    retained.add_argument("--retained-info", type=Path, help="Original existing CosmaBot public Info.plist")
    parser.add_argument("--native-practice-config", type=Path, help="Optional explicit public native Info dictionary JSON")
    parser.add_argument(
        "--installation-profile",
        choices=sorted(INSTALLATION_PROFILES),
        help=(
            "Optional closed installation profile. production stamps production Clerk/API "
            "origins and enables CosmasNativeAuth only with a validated publishable key; "
            "staging refuses production origins; beta keeps the historical identity-driven "
            "default."
        ),
    )
    parser.add_argument("--node", type=Path, required=True, help="Existing local Node 24 executable; no downloads")
    parser.add_argument("--include-desktop-renderer", action="store_true")
    parser.add_argument("--output", type=Path, required=True, help="Fresh local candidate directory")
    return parser.parse_args(argv)


def prepare(args):
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise ValueError("Run local preparation on a Mac with the network-denied sandbox available.")
    if any(key.startswith("VITE_") for key in os.environ):
        raise ValueError("Remove ambient VITE settings; use explicit public input files.")
    repository = args.repository.resolve()
    source = source_snapshot(repository)
    if args.inputs.is_symlink() or not args.inputs.is_dir() or (args.inputs / ".incomplete").exists():
        raise ValueError("Use a complete regular public client input directory.")
    inputs = args.inputs.resolve()
    node = args.node.resolve()
    regular(node)
    if not os.access(node, os.X_OK):
        raise ValueError("The selected local Node executable is not executable.")
    node_version = subprocess.check_output([str(node), "--version"], text=True, timeout=15).strip()
    if re.fullmatch(r"v24\.[0-9]+\.[0-9]+", node_version) is None:
        raise ValueError("Use the existing local Node 24 runtime.")
    clients = ("apple", "desktop") if args.include_desktop_renderer else ("apple",)
    input_paths = [regular(inputs / (client + suffix), 16384)
                   for client in clients for suffix in ("-identity.json", "-build-env.json")]
    for path in input_paths:
        public_json(path)
    old_info, retained = retained_info(args.retained_ipa or args.retained_info, bool(args.retained_ipa))
    input_paths.append(Path(retained["path"]))
    practice = None
    if args.native_practice_config is not None:
        practice = native_practice_configuration(public_json(args.native_practice_config))
        input_paths.append(regular(args.native_practice_config, 16384))
    hashes = {str(path): digest(path) for path in input_paths}
    output = output_path(args.output, [repository, inputs, *input_paths])
    identity_module = load_module(repository, "native_identity_build")
    navigation = load_module(repository, "cosmaneura_navigation_build")
    previous_path = os.environ.get("PATH")
    os.environ["PATH"] = str(node.parent) + os.pathsep + (previous_path or "")
    try:
        identity = identity_module.load(inputs / "apple-identity.json", "apple")
        # Check retained custody before creating output or invoking a compiler.
        scaffold_info = plistlib.loads((repository / "apps/capture/ios/App/App/Info.plist").read_bytes())
        configured_info(scaffold_info, old_info, identity, practice, navigation.validate_google)
        output.mkdir(mode=0o700)
        (output / ".incomplete").write_text("Owned iPhone candidate preparation incomplete\n")
        env = dict(os.environ)
        stages = []
        for client in clients:
            stages.append(stage(repository, output, client + "-renderer", [str(node),
                str(repository / "scripts/build-native-renderer.mjs"), "--inputs", str(inputs),
                "--client", client, "--output", str(output / (client + "-renderer"))], env))
        blueprint = output / "iphone-project"
        compose_command = [sys.executable,
            str(repository / "scripts/compose-portable-iphone.py"), "--repository", str(repository),
            "--output", str(blueprint)]
        if args.installation_profile:
            compose_command.extend(["--installation-profile", args.installation_profile])
        stages.append(stage(repository, output, "iphone-composition", compose_command, env))
        composition, bindings = composition_bindings(repository, source, blueprint)
        candidate = output / "iphone-configured-candidate"
        shutil.copytree(blueprint, candidate)
        app = candidate / "apps/capture/ios/App/App"
        info_path = app / "Info.plist"
        before = plistlib.loads(info_path.read_bytes())
        info = configured_info(before, old_info, identity, practice, navigation.validate_google)
        info = apply_installation_profile_to_configured_info(
            info, args.installation_profile, identity=identity)
        info_path.write_bytes(plistlib.dumps(info, sort_keys=False))
        shutil.copytree(output / "apple-renderer/dist", app / "public")
        transport = public_json(app / "public/cosmas-workspace-build.json")
        feature = public_json(app / "public/cosmas-beta-features.json")
        if (transport.get("client") != "apple" or transport.get("apiOrigin") != identity["identity"]["apiOrigin"]
                or feature.get("captureMode") not in {"disabled", "synthetic"}
                or info.get("CosmasConfiguredCapture") != {"enabled": False}):
            raise ValueError("Owned project preparation requires the exact Apple API and unconfigured native capture.")
        uploads = tuple(feature["captureUploadOrigins"])
        policy, apply_policy = workspace_policy(repository, identity["identity"]["apiOrigin"], uploads)
        index = app / "public/index.html"
        index.write_text(apply_policy(index.read_text(encoding="utf-8"), policy), encoding="utf-8")
        changed = [item["path"] for item in composition["files"]
                   if digest(candidate / "apps/capture" / item["path"]) != item["sha256"]]
        if changed != ["ios/App/App/Info.plist"]:
            raise ValueError("Configured candidate changed unrelated composed native source.")
        if source_snapshot(repository) != source or any(digest(Path(path)) != value for path, value in hashes.items()):
            raise ValueError("Source or explicit public inputs changed during preparation.")
        save(output / "candidate-inventory.json", {"source": source, "files": inventory(candidate)})
        save(output / "preparation-receipt.json", {
            "contract_version": "cosmabot.owned-iphone-preparation.v1",
            "observed_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
            "source": source, "source_clean_before_and_after": True, "inputs_sha256": hashes,
            "retained_public_info": retained, "native_practice_explicitly_supplied": practice is not None,
            "native_practice_enabled": practice is not None and practice["enabled"],
            "tooling": {"node_path": str(node), "node_sha256": digest(node), "node_version": node_version,
                        "python_path": str(Path(sys.executable).resolve()), "python_sha256": digest(Path(sys.executable).resolve()),
                        "csp_source_sha256": digest(repository / "scripts/prepare-apple-synthetic.py")},
            "stages": stages, "owned_source_bindings": bindings,
            "blueprint": blueprint.name, "candidate": candidate.name,
            "composition_sha256": digest(blueprint / "composition.json"),
            "candidate_inventory_sha256": digest(output / "candidate-inventory.json"),
            "installation_profile": args.installation_profile,
            "configuration_delta": ["public legacy identity/source/Google fields", "explicit optional native practice config",
                                    "generated web assets", "exact API CSP",
                                    *(["production CosmasNativeAuth origin stamp"]
                                      if args.installation_profile == PRODUCTION_INSTALLATION_PROFILE else [])],
            "network_denied_for_build_stages": True, "native_compiled": False,
            "signed": False, "installed": False, "published": False, "deployed": False,
            "distribution_number_assigned": False, "physical_or_provider_journey_qualified": False,
        })
        (output / ".incomplete").unlink()
        return output
    finally:
        if previous_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = previous_path


if __name__ == "__main__":
    try:
        prepare(arguments())
        print("Prepared owned iPhone project and renderer assets; no native compile or release actions.")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile,
            plistlib.InvalidFileException) as error:
        print("Owned iPhone preparation refused: " + str(error), file=sys.stderr)
        sys.exit(1)
