#!/usr/bin/env python3
"""Production-only CosmasNativeAuth Info.plist stamping for iPhone composition.

The frozen apps/capture Info.plist keeps CosmasNativeAuth.enabled=false with empty
origins. Default, beta, and staging composition must leave that byte-identical.
Only an explicit production installation profile stamps production Clerk/API
origins. Auth is enabled only when a validated publishable key is supplied.
Staging and production origins cannot mix.

CTO decision log, 11 Nov 2026, per John 30 Oct: production on beta.cosmas.ai,
separate Clerk. clerk.cosmas.ai stays reserved for a later enrollment design.
"""

from __future__ import annotations

import base64
import copy
import re

PRODUCTION_INSTALLATION_PROFILE = "production"
STAGING_INSTALLATION_PROFILE = "staging"
BETA_INSTALLATION_PROFILE = "beta"
INSTALLATION_PROFILES = frozenset({
    PRODUCTION_INSTALLATION_PROFILE,
    STAGING_INSTALLATION_PROFILE,
    BETA_INSTALLATION_PROFILE,
})

# Production installation profile (device App Store / review). Matches the Swift
# operational-beta-v1 Clerk pin in NativeClerkConfiguration.swift.
PRODUCTION_ORIGINS = {
    "clerk": "https://clerk.beta.cosmas.ai",
    "api": "https://api.beta.cosmas.ai",
    "web": "https://beta.cosmas.ai",
}
# Dedicated staging pair. Accounts.dev staging identities are also admitted for
# the staging installation profile (see require_installation_profile_origins).
STAGING_ORIGINS = {
    "clerk": "https://clerk.staging.cosmas.ai",
    "api": "https://api.staging.cosmas.ai",
    "web": "https://staging.cosmas.ai",
}
SWIFT_OPERATIONAL_BETA_CLERK_HOST = "clerk.beta.cosmas.ai"
ACCOUNTS_DEV_SUFFIX = ".clerk.accounts.dev"


def _exact_https_origin(value: object, label: str) -> str:
    if (not isinstance(value, str) or not value.startswith("https://")
            or "/" in value[8:] or ":" in value[8:]):
        raise ValueError(f"Use an exact HTTPS {label} origin without a path or port.")
    return value


def _absent_web_origin(value: object) -> bool:
    """Frozen Info leaves CosmaneuraWebOrigin as \"\"; treat that as unset."""
    return value is None or value == ""


def _clerk_host(frontend_origin: str) -> str:
    return frontend_origin.removeprefix("https://")


def _is_staging_clerk_frontend(frontend_origin: str) -> bool:
    host = _clerk_host(frontend_origin)
    return host == _clerk_host(STAGING_ORIGINS["clerk"]) or host.endswith(ACCOUNTS_DEV_SUFFIX)


def publishable_key_host(key: object) -> str | None:
    if not isinstance(key, str):
        return None
    for prefix in ("pk_live_", "pk_test_"):
        if not key.startswith(prefix):
            continue
        encoded = key[len(prefix):].replace("-", "+").replace("_", "/")
        if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", encoded) is None:
            return None
        try:
            decoded = base64.b64decode(encoded + "=" * ((4 - len(encoded) % 4) % 4), validate=True)
            text = decoded.decode("utf-8")
        except (ValueError, UnicodeError):
            return None
        if not text.endswith("$"):
            return None
        return text[:-1]
    return None


def require_validated_production_auth(auth: object) -> dict:
    """Require enabled production auth whose publishable key encodes the pinned Clerk host."""
    if not isinstance(auth, dict) or auth.get("enabled") is not True:
        raise ValueError("Production profile refuses to enable CosmasNativeAuth without a validated key.")
    frontend = _exact_https_origin(auth.get("frontendOrigin"), "Clerk frontend")
    if frontend != PRODUCTION_ORIGINS["clerk"]:
        raise ValueError("Production profile requires clerk.beta.cosmas.ai origins.")
    key = auth.get("publishableKey")
    host = publishable_key_host(key)
    if host != SWIFT_OPERATIONAL_BETA_CLERK_HOST:
        raise ValueError(
            "Production profile refuses to enable CosmasNativeAuth without a validated key "
            "whose publishable-key host equals clerk.beta.cosmas.ai.")
    if not isinstance(auth.get("organizationId"), str) or not auth["organizationId"]:
        raise ValueError("Production profile requires a non-empty organizationId with the validated key.")
    if not isinstance(auth.get("audience"), str) or not auth["audience"]:
        raise ValueError("Production profile requires a non-empty audience with the validated key.")
    if auth.get("profile") != "operational-beta-v1":
        raise ValueError("Production profile requires operational-beta-v1 with the validated key.")
    return copy.deepcopy(auth)


def require_installation_profile_origins(
    profile: str,
    *,
    frontend_origin: object,
    api_origin: object,
    web_origin: object | None = None,
) -> None:
    """Refuse staging origins on production and production origins on staging."""
    if profile not in INSTALLATION_PROFILES:
        raise ValueError("Use the production, beta, or staging installation profile.")
    if profile == BETA_INSTALLATION_PROFILE:
        # Beta composition keeps historical identity-driven defaults; no new pin.
        return
    frontend = _exact_https_origin(frontend_origin, "Clerk frontend")
    api = _exact_https_origin(api_origin, "API")
    web = None if _absent_web_origin(web_origin) else _exact_https_origin(web_origin, "web")

    if profile == PRODUCTION_INSTALLATION_PROFILE:
        if (frontend == STAGING_ORIGINS["clerk"] or api == STAGING_ORIGINS["api"]
                or (web is not None and web == STAGING_ORIGINS["web"])
                or _clerk_host(frontend).endswith(ACCOUNTS_DEV_SUFFIX)):
            raise ValueError("Production profile refuses staging origins.")
        if frontend != PRODUCTION_ORIGINS["clerk"] or api != PRODUCTION_ORIGINS["api"]:
            raise ValueError(
                "Production profile requires clerk.beta.cosmas.ai, api.beta.cosmas.ai, "
                "and beta.cosmas.ai origins.")
        if web is not None and web != PRODUCTION_ORIGINS["web"]:
            raise ValueError(
                "Production profile requires clerk.beta.cosmas.ai, api.beta.cosmas.ai, "
                "and beta.cosmas.ai origins.")
        return

    # staging installation profile
    if (frontend == PRODUCTION_ORIGINS["clerk"] or api == PRODUCTION_ORIGINS["api"]
            or (web is not None and web == PRODUCTION_ORIGINS["web"])):
        raise ValueError("Staging profile refuses production origins.")
    if not _is_staging_clerk_frontend(frontend) or api != STAGING_ORIGINS["api"]:
        raise ValueError(
            "Staging profile requires clerk.staging.cosmas.ai or a *.clerk.accounts.dev "
            "frontend, api.staging.cosmas.ai, and staging.cosmas.ai origins.")
    if web is not None and web != STAGING_ORIGINS["web"]:
        raise ValueError(
            "Staging profile requires clerk.staging.cosmas.ai or a *.clerk.accounts.dev "
            "frontend, api.staging.cosmas.ai, and staging.cosmas.ai origins.")


def production_native_auth_stamp(info: dict, *, auth: dict | None = None) -> dict:
    """Stamp production Clerk/API origins onto a composed Info dict.

    Does not enable CosmasNativeAuth unless a validated auth dictionary is
    supplied. Compose-only / identity-free paths therefore keep enabled=false.
    Does not stamp CosmaneuraWebOrigin (record-navigation policy stays unchanged).
    """
    if not isinstance(info, dict):
        raise ValueError("Info.plist must be a dictionary.")
    require_installation_profile_origins(
        PRODUCTION_INSTALLATION_PROFILE,
        frontend_origin=PRODUCTION_ORIGINS["clerk"],
        api_origin=PRODUCTION_ORIGINS["api"],
    )
    result = copy.deepcopy(info)
    existing = result.get("CosmasNativeAuth")
    stamped_auth = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    stamped_auth["frontendOrigin"] = PRODUCTION_ORIGINS["clerk"]
    if auth is None:
        stamped_auth["enabled"] = False
    else:
        validated = require_validated_production_auth(auth)
        stamped_auth.update(validated)
        stamped_auth["enabled"] = True
        stamped_auth["frontendOrigin"] = PRODUCTION_ORIGINS["clerk"]
    result["CosmasNativeAuth"] = stamped_auth
    identity = result.get("CosmasNativeIdentity")
    if not isinstance(identity, dict):
        identity = {}
    else:
        identity = copy.deepcopy(identity)
    identity["frontendOrigin"] = PRODUCTION_ORIGINS["clerk"]
    identity["apiOrigin"] = PRODUCTION_ORIGINS["api"]
    if auth is not None:
        for key in ("profile", "publishableKey", "organizationId", "audience"):
            if key in auth:
                identity[key] = copy.deepcopy(auth[key])
        identity["profile"] = "operational-beta-v1"
    result["CosmasNativeIdentity"] = identity
    return result


def apply_installation_profile_to_configured_info(
    info: dict,
    profile: str | None,
    *,
    identity: dict | None = None,
) -> dict:
    """Apply production stamping / origin refusal after owned candidate configuration.

    beta and omitted profiles leave the configured Info unchanged. staging validates
    Clerk/API origins (accounts.dev or dedicated staging) and ignores an empty web
    origin. production stamps origins and enables auth only with a validated key.
    """
    if profile is None or profile == BETA_INSTALLATION_PROFILE:
        return info
    if profile not in INSTALLATION_PROFILES:
        raise ValueError("Use the production, beta, or staging installation profile.")
    record = identity.get("identity") if isinstance(identity, dict) else None
    if not isinstance(record, dict):
        record = info.get("CosmasNativeIdentity") if isinstance(info.get("CosmasNativeIdentity"), dict) else {}
    frontend = record.get("frontendOrigin", "")
    api = record.get("apiOrigin", "")
    web = info.get("CosmaneuraWebOrigin")
    if profile == STAGING_INSTALLATION_PROFILE:
        require_installation_profile_origins(
            profile, frontend_origin=frontend, api_origin=api, web_origin=web)
        return info
    if not isinstance(identity, dict) or not isinstance(identity.get("auth"), dict):
        raise ValueError("Production profile refuses to enable CosmasNativeAuth without a validated key.")
    identity_record = identity.get("identity") if isinstance(identity.get("identity"), dict) else {}
    require_installation_profile_origins(
        PRODUCTION_INSTALLATION_PROFILE,
        frontend_origin=identity_record.get("frontendOrigin", frontend),
        api_origin=identity_record.get("apiOrigin", api),
        web_origin=identity.get("webOrigin", web),
    )
    stamped = production_native_auth_stamp(info, auth=identity["auth"])
    if isinstance(identity.get("identity"), dict):
        native = copy.deepcopy(stamped["CosmasNativeIdentity"])
        for key, value in identity["identity"].items():
            native[key] = copy.deepcopy(value)
        native["frontendOrigin"] = PRODUCTION_ORIGINS["clerk"]
        native["apiOrigin"] = PRODUCTION_ORIGINS["api"]
        stamped["CosmasNativeIdentity"] = native
    require_installation_profile_origins(
        PRODUCTION_INSTALLATION_PROFILE,
        frontend_origin=stamped["CosmasNativeAuth"]["frontendOrigin"],
        api_origin=stamped["CosmasNativeIdentity"]["apiOrigin"],
        web_origin=stamped.get("CosmaneuraWebOrigin"),
    )
    return stamped
