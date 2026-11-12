"""Closed CosmasNativePracticeConnection Info schema for owned native packaging.

Validates explicit public JSON before it is embedded in an iPhone app Info or
Mac auth-helper Info. Does not enable a missing option, change Beta identity,
or perform signing. Staging and production are closed realms and cannot mix.
"""

from __future__ import annotations

import base64
import copy
import json
import re
from pathlib import Path

PRACTICE_KEY = "CosmasNativePracticeConnection"
ORIGIN_HOST = r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}"
PRODUCTION_PRACTICE_FRONTEND = "https://clerk.cosmas.ai"
PRODUCTION_PRACTICE_ACCOUNT = "https://enrollment-api.cosmas.ai"
PRODUCTION_PRACTICE_POLICY = "practice-uuid-production-v1"
STAGING_PRACTICE_ACCOUNT = "https://enrollment-api.staging.cosmas.ai"
STAGING_PRACTICE_POLICIES = frozenset({"exact", "synthetic-practice-uuid-staging-v1"})


def exact_origin(value: object) -> str:
    if (not isinstance(value, str) or len(value.encode("utf-8")) > 253
            or re.fullmatch("https://" + ORIGIN_HOST, value) is None
            or value.endswith(".localhost") or re.fullmatch(r"https://[0-9.]+", value)):
        raise ValueError("Use an exact canonical HTTPS origin without a path or port.")
    return value


def _practice_publishable_key(key: object, host: str, *, live: bool) -> None:
    prefix = "pk_live_" if live else "pk_test_"
    if (not isinstance(key, str) or len(key.encode("utf-8")) > 1024 or not key.startswith(prefix)
            or re.fullmatch(r"[A-Za-z0-9+/_-]+={0,2}", key[len(prefix):]) is None):
        raise ValueError("The account realm requires its exact Clerk frontend and public key.")
    encoded = key[len(prefix):].replace("-", "+").replace("_", "/")
    try:
        decoded = base64.b64decode(encoded + "=" * ((4 - len(encoded) % 4) % 4), validate=True).decode("utf-8")
    except (ValueError, UnicodeError) as error:
        raise ValueError("The account public key must encode its exact Clerk frontend.") from error
    if decoded != host + "$":
        raise ValueError("The account public key must encode its exact Clerk frontend.")


def _practice_realm_and_policy(value: dict) -> str:
    """Admit one closed staging realm or the production practice realm, never a mix."""
    realm = value["realm"]
    if (not isinstance(realm, dict)
            or set(realm) != {"publishableKey", "frontendOrigin", "audience", "profile", "keychainNamespace"}
            or not isinstance(realm["keychainNamespace"], str)
            or re.fullmatch(r"[a-f0-9]{64}", realm["keychainNamespace"]) is None):
        raise ValueError("The explicit account realm requires a reviewed profile and namespace.")
    frontend = exact_origin(realm["frontendOrigin"])
    host = frontend.removeprefix("https://")
    if len(host.encode("utf-8")) > 245:
        raise ValueError("The account realm requires its exact Clerk frontend and public key.")
    policy = value.get("registeredPracticeOrigins", "exact")
    profile = realm["profile"]
    audience = realm["audience"]
    if profile == "operational-staging-v1":
        # Staging Infos pin the reviewed enrollment API origin so a staging Clerk
        # realm cannot quietly wire Connect to production enrollment-api.cosmas.ai.
        if (audience != "" or not host.endswith(".clerk.accounts.dev")
                or value["accountOrigin"] != STAGING_PRACTICE_ACCOUNT
                or not isinstance(policy, str) or policy not in STAGING_PRACTICE_POLICIES):
            raise ValueError(
                "Staging native practice requires enrollment-api.staging.cosmas.ai "
                "and the reviewed exact or synthetic practice UUID origin policy.")
        _practice_publishable_key(realm["publishableKey"], host, live=False)
        return policy
    if profile == "operational-beta-v1":
        # Real-data production: one enrollment account origin, live Clerk, non-empty
        # session audience, and the practice-UUID production origin policy only.
        if (not isinstance(audience, str) or not audience or len(audience.encode("utf-8")) > 255
                or any(ord(character) < 33 or ord(character) > 126 for character in audience)
                or frontend != PRODUCTION_PRACTICE_FRONTEND
                or value["accountOrigin"] != PRODUCTION_PRACTICE_ACCOUNT
                or policy != PRODUCTION_PRACTICE_POLICY):
            raise ValueError(
                "Production native practice requires enrollment-api.cosmas.ai, clerk.cosmas.ai, "
                "a non-empty Clerk audience, and practice-uuid-production-v1.")
        _practice_publishable_key(realm["publishableKey"], host, live=True)
        return policy
    raise ValueError("The explicit account realm requires the native staging or production profile.")


def native_practice_configuration(value: object) -> dict:
    """Match NativePracticeBundleConfiguration's closed staging or production schema.

    This validates explicit public inputs; it neither enables a missing option
    nor changes the compiled Beta identity, callback or native request origin.
    Staging keeps operational-staging-v1 with an empty audience and pins
    accountOrigin to enrollment-api.staging.cosmas.ai. Production binds
    operational-beta-v1 to enrollment-api.cosmas.ai, clerk.cosmas.ai, a non-empty
    audience, and practice-uuid-production-v1. Runtime acceptance of that
    production policy also requires the matching native-auth / shared-profile
    changes (#311 / #315).
    """
    required = {"enabled", "accountOrigin", "realm", "apiOrigins"}
    if (not isinstance(value, dict) or not required <= value.keys()
            or value.keys() - required - {"registeredPracticeOrigins", "googleConnection"}
            or type(value["enabled"]) is not bool):
        raise ValueError("Native practice configuration must match the owned Info schema.")
    exact_origin(value["accountOrigin"])
    policy = _practice_realm_and_policy(value)
    origins = value["apiOrigins"]
    if (not isinstance(origins, list) or len(origins) > 32
            or policy == "exact" and not origins):
        raise ValueError("Use the reviewed exact, synthetic staging, or production practice UUID origin policy.")
    checked = [exact_origin(origin) for origin in origins]
    if len(set(checked)) != len(checked):
        raise ValueError("Duplicate native API origins are not permitted.")
    if "googleConnection" in value:
        pair = value["googleConnection"]
        if (not isinstance(pair, dict) or set(pair) != {"clientID", "callbackURI"}
                or not isinstance(pair["clientID"], str)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com", pair["clientID"]) is None
                or pair["callbackURI"] != value["accountOrigin"] + "/connections/google/callback"):
            raise ValueError(
                "Native practice Google requires an exact public client and the pinned account-service callback.")
    return copy.deepcopy(value)


def load_practice_config(path) -> dict:
    """Load and validate a reviewed public native-practice JSON file."""
    file = Path(path)
    if not file.is_file() or file.is_symlink():
        raise ValueError("Native practice configuration must be a regular reviewed public JSON file.")
    raw = file.read_bytes()
    if len(raw) > 64 * 1024:
        raise ValueError("Native practice configuration is too large.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Native practice configuration must be UTF-8 JSON.") from error
    return native_practice_configuration(value)
