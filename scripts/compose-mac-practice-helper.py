#!/usr/bin/env python3
"""One-command Mac practice-helper package for signup → Open Chief.

Builds a fixed output layout with one package-manifest.json so operators are not
hunting scattered zip paths. Production Infos use --native-practice-config and
keep Connect / Open Chief fail-closed until a signed CosmasNativePracticeConnection
helper exists. Does not sign, notarize, upload to App Store Connect, or publish
download URLs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

OPERATOR = "scripts/compose-mac-practice-helper.py"
MANIFEST_NAME = "package-manifest.json"
GUIDE_NAME = "AFTER-SIGNUP-OPEN-CHIEF.md"
HELPER_NAME = "CosmasAuth.app"
COMPOSED_NAME = "composed-desktop"
PRODUCTION_ACCOUNT = "https://enrollment-api.cosmas.ai"

_practice_spec = importlib.util.spec_from_file_location(
    "native_practice_connection_info", Path(__file__).with_name("native_practice_connection_info.py"))
_practice = importlib.util.module_from_spec(_practice_spec)
_practice_spec.loader.exec_module(_practice)


def load_infos(path: Path) -> dict:
    """Load reviewed public Infos; refuse secrets-shaped paths."""
    return _practice.load_practice_config(path)


def is_production_infos(infos: dict) -> bool:
    return infos.get("realm", {}).get("profile") == "operational-beta-v1"


def derive_defaults(infos: dict, *, hosted_api_origin: str | None, data_mode: str | None) -> tuple[str, str]:
    """Pinned hosted origin + data mode from Infos, with explicit overrides checked."""
    production = is_production_infos(infos)
    default_origin = PRODUCTION_ACCOUNT if production else infos["accountOrigin"]
    default_mode = "authorized_beta" if production else "synthetic"
    origin = hosted_api_origin or default_origin
    mode = data_mode or default_mode
    if production:
        if origin != PRODUCTION_ACCOUNT:
            raise ValueError(
                "Production Infos require --hosted-api-origin https://enrollment-api.cosmas.ai "
                "(or omit the flag to use that default).")
        if mode != "authorized_beta":
            raise ValueError("Production native practice Infos require authorized_beta data mode.")
    elif origin == PRODUCTION_ACCOUNT and infos["accountOrigin"] != PRODUCTION_ACCOUNT:
        raise ValueError("Staging Infos cannot target production enrollment-api.cosmas.ai.")
    return origin, mode


def refuse_fake_with_production(infos: dict, enable_fake_practice_host: bool) -> None:
    if is_production_infos(infos) and enable_fake_practice_host:
        raise ValueError("Production Infos cannot combine with the fake/local practice host flag.")


def prepare_argv(
    *,
    repository: Path,
    web_dist: Path,
    composed_output: Path,
    helper: Path,
    identity: Path,
    practice_config: Path,
    hosted_api_origin: str,
    data_mode: str,
    enable_fake_practice_host: bool,
) -> list[str]:
    """Exact prepare-desktop-synthetic argv for the one-path Mac package."""
    argv = [
        sys.executable, str(repository / "scripts/prepare-desktop-synthetic.py"),
        "--web-dist", str(web_dist),
        "--output", str(composed_output),
        "--native-auth-helper", str(helper),
        "--native-identity-config", str(identity),
        "--installation-profile", "beta",
        "--hosted-api-origin", hosted_api_origin,
        "--data-mode", data_mode,
        "--native-practice-config", str(practice_config),
    ]
    if enable_fake_practice_host:
        argv.append("--native-practice-connection")
    return argv


def package_helper_argv(
    *,
    repository: Path,
    products: Path,
    qualification: Path,
    compiler_receipt: Path,
    identity: Path,
    practice_config: Path,
    helper_output: Path,
) -> list[str]:
    return [
        sys.executable, str(repository / "scripts/package-desktop-auth-helper.py"),
        "--products", str(products),
        "--qualification", str(qualification),
        "--compiler-receipt", str(compiler_receipt),
        "--native-identity-config", str(identity),
        "--native-practice-config", str(practice_config),
        "--output", str(helper_output),
    ]


def helper_infos_summary(helper: Path) -> dict | None:
    info_path = helper / "Contents/Info.plist"
    if not info_path.is_file():
        raise ValueError("Native auth helper is missing Contents/Info.plist.")
    info = plistlib.loads(info_path.read_bytes())
    practice = info.get(_practice.PRACTICE_KEY)
    if practice is None:
        return None
    closed = _practice.native_practice_configuration(practice)
    return {
        "profile": closed["realm"]["profile"],
        "accountOrigin": closed["accountOrigin"],
        "frontendOrigin": closed["realm"]["frontendOrigin"],
        "registeredPracticeOrigins": closed.get("registeredPracticeOrigins", "exact"),
        "audience_present": bool(closed["realm"]["audience"]),
    }


def write_guide(path: Path, *, production: bool, account_origin: str) -> None:
    env = "production" if production else "staging"
    path.write_text(
        "# After signup — open the Mac helper into Chief\n\n"
        "This directory is the **one** Mac practice-helper package for this build.\n"
        "Do not hunt other zip paths or older CFBundleVersion 1107 artifacts.\n\n"
        f"- Environment: **{env}**\n"
        f"- Enrollment origin: `{account_origin}`\n"
        f"- Manifest: `{MANIFEST_NAME}` (canonical artifact pointer)\n"
        f"- Helper app: `{HELPER_NAME}`\n"
        f"- Composed desktop input: `{COMPOSED_NAME}/`\n\n"
        "## Operator path (John / practice Mac)\n\n"
        "1. Sign and notarize on a Mac (agents do not sign).\n"
        "2. Install the notarized Mac app from this package.\n"
        "3. Finish CosmaBot signup in the browser until the practice is **ready**.\n"
        "4. Open the signed Mac helper, sign in with the same account, then **Open Chief**.\n\n"
        "Open Chief is not the install step. Without the signed practice helper,\n"
        "production Infos stay fail-closed for Clerk account sign-in / Open Chief.\n"
        "Do not combine production Infos with the fake/local practice host flag.\n"
        "Do not paste secrets, `.env` values, or patient data into this tree.\n",
        encoding="utf-8",
    )


def write_manifest(
    path: Path,
    *,
    infos: dict,
    hosted_api_origin: str,
    data_mode: str,
    helper: Path,
    composed: Path,
    helper_embedded: dict | None,
    source_commit: str | None,
) -> dict:
    production = is_production_infos(infos)
    manifest = {
        "version": 1,
        "operator": OPERATOR,
        "purpose": "mac-practice-helper-one-path",
        "signed": False,
        "notarized": False,
        "distribution_allowed": False,
        "environment": "production" if production else "staging",
        "data_mode": data_mode,
        "hosted_api_origin": hosted_api_origin,
        "infos": {
            "profile": infos["realm"]["profile"],
            "accountOrigin": infos["accountOrigin"],
            "frontendOrigin": infos["realm"]["frontendOrigin"],
            "registeredPracticeOrigins": infos.get("registeredPracticeOrigins", "exact"),
            "audience_present": bool(infos["realm"]["audience"]),
            "enabled": infos["enabled"],
        },
        "artifacts": {
            "manifest": MANIFEST_NAME,
            "guide": GUIDE_NAME,
            "helper_app": HELPER_NAME,
            "composed_desktop": COMPOSED_NAME,
            "composed_app": f"{COMPOSED_NAME}/app",
            "electron_practice_infos_bound": True,
            "helper_infos_embedded": helper_embedded is not None,
        },
        "paths": {
            "helper_app": str(helper),
            "composed_desktop": str(composed),
            "composed_app": str(composed / "app"),
        },
        "helper_infos_embedded": helper_embedded,
        "signup_to_open_chief": [
            "Practice finishes CosmaBot signup until stage ready.",
            "Install the signed Mac package from this directory (see AFTER-SIGNUP-OPEN-CHIEF.md).",
            "Open the Mac helper, sign in, then Open Chief.",
        ],
        "fail_closed_without_signed_helper": production,
        "source_commit": source_commit,
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def git_commit(repository: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return value if len(value) == 40 else None


def resolve_helper(
    *,
    repository: Path,
    output: Path,
    practice_config: Path,
    identity: Path,
    native_auth_helper: Path | None,
    products: Path | None,
    qualification: Path | None,
    compiler_receipt: Path | None,
) -> Path:
    """Place CosmasAuth.app under output/, packaging from compiler products when supplied."""
    helper_output = output / HELPER_NAME
    if products is not None:
        if qualification is None or compiler_receipt is None:
            raise ValueError("Packaging the helper requires --qualification and --compiler-receipt.")
        if native_auth_helper is not None:
            raise ValueError("Pass either --native-auth-helper or --products, not both.")
        subprocess.run(
            package_helper_argv(
                repository=repository, products=products, qualification=qualification,
                compiler_receipt=compiler_receipt, identity=identity,
                practice_config=practice_config, helper_output=helper_output),
            check=True)
        return helper_output
    if native_auth_helper is None:
        raise ValueError("Provide --native-auth-helper or --products with compiler inputs.")
    helper = native_auth_helper.resolve()
    if (helper / ".incomplete").exists() or helper.suffix != ".app" or not helper.is_dir():
        raise ValueError("Use a successfully packaged .app native auth helper.")
    if helper_output.exists():
        raise ValueError("Helper output path already exists.")
    shutil.copytree(helper, helper_output)
    return helper_output


def compose(args: argparse.Namespace) -> dict:
    repository = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(repository) or repository.is_relative_to(output):
        raise ValueError("Use a fresh output directory outside the repository source.")
    practice_config = args.native_practice_config.resolve()
    identity = args.native_identity_config.resolve()
    web_dist = args.web_dist.resolve()
    infos = load_infos(practice_config)
    refuse_fake_with_production(infos, args.enable_fake_practice_host)
    hosted_api_origin, data_mode = derive_defaults(
        infos, hosted_api_origin=args.hosted_api_origin, data_mode=args.data_mode)

    output.mkdir(parents=True)
    incomplete = output / ".incomplete"
    incomplete.write_text("Mac practice-helper packaging has not completed.\n", encoding="utf-8")
    incomplete.chmod(0o600)
    try:
        helper = resolve_helper(
            repository=repository, output=output, practice_config=practice_config,
            identity=identity, native_auth_helper=args.native_auth_helper,
            products=args.products, qualification=args.qualification,
            compiler_receipt=args.compiler_receipt)
        helper_embedded = helper_infos_summary(helper)
        composed = output / COMPOSED_NAME
        argv = prepare_argv(
            repository=repository, web_dist=web_dist, composed_output=composed,
            helper=helper, identity=identity, practice_config=practice_config,
            hosted_api_origin=hosted_api_origin, data_mode=data_mode,
            enable_fake_practice_host=args.enable_fake_practice_host)
        subprocess.run(argv, check=True)
        write_guide(output / GUIDE_NAME, production=is_production_infos(infos),
                    account_origin=infos["accountOrigin"])
        manifest = write_manifest(
            output / MANIFEST_NAME, infos=infos, hosted_api_origin=hosted_api_origin,
            data_mode=data_mode, helper=helper, composed=composed,
            helper_embedded=helper_embedded, source_commit=git_commit(repository))
        incomplete.unlink()
        return manifest
    except Exception:
        # Retain .incomplete and any partial tree for inspection; do not delete.
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-practice-config", type=Path, required=True,
                        help="Reviewed public CosmasNativePracticeConnection JSON (no secrets)")
    parser.add_argument("--native-identity-config", type=Path, required=True,
                        help="Reviewed public desktop-identity.json")
    parser.add_argument("--web-dist", type=Path, required=True,
                        help="Built desktop renderer dist matching the Infos data mode")
    parser.add_argument("--output", type=Path, required=True,
                        help="Fresh directory outside the repository for the one-path package")
    parser.add_argument("--native-auth-helper", type=Path,
                        help="Already packaged CosmasAuth.app (Debug/Release compile product)")
    parser.add_argument("--products", type=Path, help="Swift compiler products directory")
    parser.add_argument("--qualification", type=Path, help="Native auth qualification directory")
    parser.add_argument("--compiler-receipt", type=Path, help="compiler-receipt.json from the helper build")
    parser.add_argument("--hosted-api-origin",
                        help="Defaults to Infos accountOrigin (production pins enrollment-api.cosmas.ai)")
    parser.add_argument("--data-mode", choices=("synthetic", "authorized_beta"),
                        help="Defaults to authorized_beta for production Infos, synthetic for staging")
    parser.add_argument("--enable-fake-practice-host", action="store_true",
                        help="Opt in to fake/local CosmasDesktopPractice (refused with production Infos)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = compose(args)
    except ValueError as error:
        parser.error(str(error))
    except subprocess.CalledProcessError as error:
        parser.exit(error.returncode or 1, "Mac practice-helper packaging refused: child step failed.\n")
    print(
        f"Mac practice-helper package ready: {args.output.resolve() / MANIFEST_NAME}; "
        f"environment={manifest['environment']}; signed=false; Open Chief after Mac sign + install"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
