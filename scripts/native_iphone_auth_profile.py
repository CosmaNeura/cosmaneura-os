#!/usr/bin/env python3
"""Production-only CosmasNativeAuth Info.plist stamping for iPhone composition.

The frozen apps/capture Info.plist keeps CosmasNativeAuth.enabled=false with empty
origins. Default, beta, and staging composition must leave that byte-identical.
Only an explicit production installation profile stamps enabled=true and the
reviewed production Clerk/API/web origins. Staging and production origins cannot
mix.
"""

from __future__ import annotations

import copy

PRODUCTION_INSTALLATION_PROFILE = "production"
STAGING_INSTALLATION_PROFILE = "staging"
BETA_INSTALLATION_PROFILE = "beta"
INSTALLATION_PROFILES = frozenset({
    PRODUCTION_INSTALLATION_PROFILE,
    STAGING_INSTALLATION_PROFILE,
    BETA_INSTALLATION_PROFILE,
})

# App Store / production review build still targets the beta.cosmas.ai Clerk+API
# hosts. Staging keeps staging.cosmas.ai. These closed sets cannot mix.
PRODUCTION_ORIGINS = {
    "clerk": "https://clerk.beta.cosmas.ai",
    "api": "https://api.beta.cosmas.ai",
    "web": "https://beta.cosmas.ai",
}
STAGING_ORIGINS = {
    "clerk": "https://clerk.staging.cosmas.ai",
    "api": "https://api.staging.cosmas.ai",
    "web": "https://staging.cosmas.ai",
}


def _exact_https_origin(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://") or "/" in value[8:]:
        raise ValueError(f"Use an exact HTTPS {label} origin without a path or port.")
    return value


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
    expected = PRODUCTION_ORIGINS if profile == PRODUCTION_INSTALLATION_PROFILE else STAGING_ORIGINS
    other = STAGING_ORIGINS if profile == PRODUCTION_INSTALLATION_PROFILE else PRODUCTION_ORIGINS
    if frontend == other["clerk"] or api == other["api"] or (
            web_origin is not None and web_origin == other["web"]):
        if profile == PRODUCTION_INSTALLATION_PROFILE:
            raise ValueError("Production profile refuses staging origins.")
        raise ValueError("Staging profile refuses production origins.")
    if frontend != expected["clerk"] or api != expected["api"]:
        if profile == PRODUCTION_INSTALLATION_PROFILE:
            raise ValueError(
                "Production profile requires clerk.beta.cosmas.ai, api.beta.cosmas.ai, "
                "and beta.cosmas.ai origins.")
        raise ValueError(
            "Staging profile requires clerk.staging.cosmas.ai, api.staging.cosmas.ai, "
            "and staging.cosmas.ai origins.")
    if web_origin is not None and web_origin != expected["web"]:
        if profile == PRODUCTION_INSTALLATION_PROFILE:
            raise ValueError("Production profile refuses staging origins.")
        raise ValueError("Staging profile refuses production origins.")


def production_native_auth_stamp(info: dict) -> dict:
    """Stamp CosmasNativeAuth.enabled and production origins onto a composed Info dict.

    Does not invent publishable keys, organization IDs, or audiences. Callers that
    hold a reviewed identity still supply those separately. Frozen scaffold keys
    stay untouched until this is explicitly applied for the production profile.
    """
    if not isinstance(info, dict):
        raise ValueError("Info.plist must be a dictionary.")
    require_installation_profile_origins(
        PRODUCTION_INSTALLATION_PROFILE,
        frontend_origin=PRODUCTION_ORIGINS["clerk"],
        api_origin=PRODUCTION_ORIGINS["api"],
        web_origin=PRODUCTION_ORIGINS["web"],
    )
    result = copy.deepcopy(info)
    auth = result.get("CosmasNativeAuth")
    if not isinstance(auth, dict):
        auth = {}
    else:
        auth = copy.deepcopy(auth)
    auth["enabled"] = True
    auth["frontendOrigin"] = PRODUCTION_ORIGINS["clerk"]
    result["CosmasNativeAuth"] = auth
    identity = result.get("CosmasNativeIdentity")
    if not isinstance(identity, dict):
        identity = {}
    else:
        identity = copy.deepcopy(identity)
    identity["frontendOrigin"] = PRODUCTION_ORIGINS["clerk"]
    identity["apiOrigin"] = PRODUCTION_ORIGINS["api"]
    result["CosmasNativeIdentity"] = identity
    result["CosmaneuraWebOrigin"] = PRODUCTION_ORIGINS["web"]
    return result


def apply_installation_profile_to_configured_info(
    info: dict,
    profile: str | None,
    *,
    identity: dict | None = None,
) -> dict:
    """Apply production stamping / origin refusal after owned candidate configuration.

    beta and omitted profiles leave the configured Info unchanged. staging only
    validates origins against the identity (or already-configured Info). production
    stamps enabled=true and the production origins, then re-validates.
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
    # production: stamp first so empty frozen origins become the production set,
    # then refuse any leftover staging values from a mismatched identity.
    stamped = production_native_auth_stamp(info)
    if isinstance(identity, dict) and isinstance(identity.get("identity"), dict):
        require_installation_profile_origins(
            PRODUCTION_INSTALLATION_PROFILE,
            frontend_origin=identity["identity"].get("frontendOrigin"),
            api_origin=identity["identity"].get("apiOrigin"),
            web_origin=identity.get("webOrigin", PRODUCTION_ORIGINS["web"]),
        )
        # Keep reviewed identity credentials; only force the closed origin set and
        # enabled flag so a production candidate cannot ship auth disabled.
        auth = copy.deepcopy(stamped["CosmasNativeAuth"])
        source_auth = identity.get("auth")
        if isinstance(source_auth, dict):
            for key in ("profile", "publishableKey", "organizationId", "audience"):
                if key in source_auth:
                    auth[key] = copy.deepcopy(source_auth[key])
        auth["enabled"] = True
        auth["frontendOrigin"] = PRODUCTION_ORIGINS["clerk"]
        stamped["CosmasNativeAuth"] = auth
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
