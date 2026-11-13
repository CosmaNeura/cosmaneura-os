"""T-PROD-1 (b): hosted AI endpoint allow-list + env binding via shared review predicate."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from tests.unit.test_hosted_workspace_config import hosted

from cosmas_os.config import (
    COSMASCODE_LLM_ENDPOINT,
    PROD_OPENAI_LLM_ENDPOINT_PATTERN,
    REVIEWED_HOSTED_CHAT_COMPLETIONS_URL_PATTERN,
    Settings,
    hosted_chat_completions_url,
    reviewed_hosted_llm_endpoint,
)
from cosmas_os.production_review_profile import classify_review_profile

PROD_ENDPOINT = "https://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1"
REVIEW_ISSUER = "https://clerk.beta.cosmas.ai"
HANDOFF_PREDICATE_SHA256 = (
    "f8417ede7a6b1ffd4dc8921dd69e6569bdb9e1f5bcf1357899f835fc4e704740"
)

LOOKALIKE_ENDPOINTS = [
    "https://oai-cbot-stg-abcd1234.openai.azure.com/openai/v1",
    "https://oai-cbot-prd-abcd1234.services.ai.azure.com/openai/v1",
    "https://xoai-cbot-prd-abcd1234.openai.azure.com/openai/v1",
    "https://oai-cbot-prd-abcd1234.openai.azure.com.evil.invalid/openai/v1",
    "https://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1/",
    "https://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1?x=1",
    "https://oai-cbot-prd-ABC123.openai.azure.com/openai/v1",
    "https://oai-cbot-prd-ab.openai.azure.com/openai/v1",
    "https://oai-cbot-prd-abcdefghijk.openai.azure.com/openai/v1",
    "https://other.openai.azure.com/openai/v1",
    "https://invented-owned-chief.openai.azure.com/openai/v1",
    "http://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1",
    "https://cosmascode.openai.azure.com/openai/v1",
    "https://cosmascode.services.ai.azure.com/openai/v1/extra",
    # Mutation: `.` → unescaped / `[a-z0-9]` → `[a-z0-9-]`
    "https://oai-cbot-prd-abcd1234xopenai.azure.com/openai/v1",
    "https://oai-cbot-prd-abcd1234.openaiXazure.com/openai/v1",
    "https://oai-cbot-prd-abc-1234.openai.azure.com/openai/v1",
    # Anchoring lookalikes
    "https://user@oai-cbot-prd-abcd1234.openai.azure.com/openai/v1",
    "https://oai-cbot-prd-abcd1234.openai.azure.com:443/openai/v1",
    "https://oai-cbot-prd-abcd1234.openai.azure.com./openai/v1",
    "https://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1#frag",
    " https://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1",
    "https://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1 ",
    "https://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1\n",
    "HTTPS://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1",
]


def _ai_on(**endpoint_or_changes):
    values = {
        "workspace_llm_backend": "azure_gpt41",
        "workspace_llm_deployment": "gpt-4.1",
        "workspace_llm_api_key": "invented-prod-or-shared-key",
        "workspace_llm_endpoint": COSMASCODE_LLM_ENDPOINT,
    }
    values.update(endpoint_or_changes)
    return hosted(**values)


def production_review(**changes):
    """#356 VM production-review surface: beta.cosmas.ai + audience + clerk.beta issuer."""
    values = {
        "cors_allowed_origins": "https://beta.cosmas.ai",
        "clerk_authorized_parties": "https://beta.cosmas.ai",
        "clerk_session_policy": "audience",
        "clerk_issuer": REVIEW_ISSUER,
        "clerk_jwks_url": REVIEW_ISSUER + "/.well-known/jwks.json",
    }
    values.update(changes)
    return _ai_on(**values)


def staging_hosted(**changes):
    # Staging web origin alone classifies as 'staging' (issuer stays invented).
    values = {
        "cors_allowed_origins": "https://staging.cosmas.ai",
        "clerk_authorized_parties": "https://staging.cosmas.ai",
    }
    values.update(changes)
    return _ai_on(**values)


def test_shared_review_predicate_file_matches_handoff_sha256():
    path = Path(__file__).resolve().parents[2] / "src/cosmas_os/production_review_profile.py"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == HANDOFF_PREDICATE_SHA256


def test_helper_accepts_cosmascode_and_narrow_prod_host_only():
    assert reviewed_hosted_llm_endpoint(COSMASCODE_LLM_ENDPOINT)
    assert reviewed_hosted_llm_endpoint(PROD_ENDPOINT)
    assert reviewed_hosted_llm_endpoint(
        "https://oai-cbot-prd-abcdefghij.openai.azure.com/openai/v1"
    )
    # Mutation: restoring CosmasCode-only equality fails the prod-endpoint acceptance above.
    assert re.fullmatch(PROD_OPENAI_LLM_ENDPOINT_PATTERN, PROD_ENDPOINT)


@pytest.mark.parametrize("endpoint", LOOKALIKE_ENDPOINTS)
def test_helper_refuses_lookalike_and_broad_openai_hosts(endpoint):
    # Mutation: broadening to any `*.openai.azure.com` fails several of these.
    assert not reviewed_hosted_llm_endpoint(endpoint)


@pytest.mark.parametrize("endpoint", LOOKALIKE_ENDPOINTS)
def test_allow_list_and_chat_url_helpers_refuse_lookalikes_in_parity(endpoint):
    assert not reviewed_hosted_llm_endpoint(endpoint)
    with pytest.raises(ValueError, match="hosted_chat_endpoint_refused"):
        hosted_chat_completions_url(endpoint)
    chat = endpoint + "/chat/completions"
    assert not re.fullmatch(REVIEWED_HOSTED_CHAT_COMPLETIONS_URL_PATTERN, chat)


def test_production_review_accepts_prod_openai_endpoint():
    assert (
        classify_review_profile(
            policy="audience",
            web_origin=None,
            cors="https://beta.cosmas.ai",
            issuer=REVIEW_ISSUER,
        )
        == "review"
    )
    config = production_review(workspace_llm_endpoint=PROD_ENDPOINT)
    config.validate_runtime_configuration()
    assert config.workspace_available
    assert config.workspace_llm_available


def test_production_review_unset_or_cosmascode_is_startup_error():
    # Default Settings value is CosmasCode; production-review must never keep it.
    config = production_review(workspace_llm_endpoint=COSMASCODE_LLM_ENDPOINT)
    assert not config.workspace_llm_available
    with pytest.raises(RuntimeError, match="Production-review requires the production"):
        config.validate_runtime_configuration()


def test_hosted_still_accepts_cosmascode_endpoint():
    config = _ai_on()
    config.validate_runtime_configuration()
    assert config.workspace_llm_available
    assert config.workspace_llm_endpoint == COSMASCODE_LLM_ENDPOINT


def test_staging_refuses_production_openai_endpoint():
    config = staging_hosted(workspace_llm_endpoint=PROD_ENDPOINT)
    assert config.workspace_available
    assert not config.workspace_llm_available
    with pytest.raises(RuntimeError, match="Non-production profiles refuse the production"):
        config.validate_runtime_configuration()


def test_staging_shared_staging_cosmascode_validates_with_ai():
    # Live staging path: shared_staging + CosmasCode + native origins in CORS.
    staging_issuer = "https://pleasant-invented.clerk.accounts.dev"
    origins = "https://staging.cosmas.ai,app://cosmas,capacitor://localhost"
    config = staging_hosted(
        clerk_session_policy="shared_staging",
        clerk_audience="",
        clerk_issuer=staging_issuer,
        clerk_jwks_url=staging_issuer + "/.well-known/jwks.json",
        cors_allowed_origins=origins,
        clerk_authorized_parties=origins,
        workspace_apple_hosted_transport_enabled=True,
        workspace_desktop_hosted_transport_enabled=True,
        workspace_llm_endpoint=COSMASCODE_LLM_ENDPOINT,
    )
    assert (
        classify_review_profile(
            policy="shared_staging",
            web_origin=None,
            cors=origins,
            issuer=staging_issuer,
        )
        == "staging"
    )
    config.validate_runtime_configuration()
    assert config.workspace_available
    assert config.workspace_llm_available


def test_non_review_hosted_refuses_production_openai_endpoint():
    config = _ai_on(workspace_llm_endpoint=PROD_ENDPOINT)
    assert not config.workspace_llm_available
    with pytest.raises(RuntimeError, match="Non-production profiles refuse the production"):
        config.validate_runtime_configuration()


@pytest.mark.parametrize(
    "profile",
    [
        # Wrong issuer (beta first, audience) → kind None
        {
            "cors_allowed_origins": "https://beta.cosmas.ai",
            "clerk_authorized_parties": "https://beta.cosmas.ai",
            "clerk_session_policy": "audience",
            "clerk_issuer": "https://identity.example.invalid",
            "clerk_jwks_url": "https://identity.example.invalid/.well-known/jwks.json",
        },
        # Beta not first in CORS
        {
            "cors_allowed_origins": "capacitor://localhost,https://beta.cosmas.ai",
            "clerk_authorized_parties": "capacitor://localhost,https://beta.cosmas.ai",
            "clerk_session_policy": "audience",
            "clerk_issuer": REVIEW_ISSUER,
            "clerk_jwks_url": REVIEW_ISSUER + "/.well-known/jwks.json",
            "workspace_apple_hosted_transport_enabled": True,
        },
        # Beta plus staging
        {
            "cors_allowed_origins": "https://beta.cosmas.ai,https://staging.cosmas.ai",
            "clerk_authorized_parties": "https://beta.cosmas.ai,https://staging.cosmas.ai",
            "clerk_session_policy": "audience",
            "clerk_issuer": REVIEW_ISSUER,
            "clerk_jwks_url": REVIEW_ISSUER + "/.well-known/jwks.json",
        },
        # shared_staging plus beta
        {
            "cors_allowed_origins": "https://beta.cosmas.ai",
            "clerk_authorized_parties": "https://beta.cosmas.ai",
            "clerk_session_policy": "shared_staging",
            "clerk_audience": "",
            "clerk_issuer": "https://pleasant-invented.clerk.accounts.dev",
            "clerk_jwks_url": (
                "https://pleasant-invented.clerk.accounts.dev/.well-known/jwks.json"
            ),
        },
    ],
)
@pytest.mark.parametrize(
    "endpoint",
    [COSMASCODE_LLM_ENDPOINT, PROD_ENDPOINT],
)
def test_almost_review_beta_profile_refuses_both_endpoints(profile, endpoint):
    config = _ai_on(workspace_llm_endpoint=endpoint, **profile)
    assert not config.workspace_llm_available
    with pytest.raises(RuntimeError, match="Incomplete production-review profile"):
        config.validate_runtime_configuration()


def test_hosted_lookalike_endpoint_refuses_ai_and_runtime():
    config = _ai_on(
        workspace_llm_endpoint="https://oai-cbot-stg-abcd1234.openai.azure.com/openai/v1"
    )
    assert config.workspace_available
    assert not config.workspace_llm_available
    with pytest.raises(RuntimeError, match="Workspace GPT-4.1"):
        config.validate_runtime_configuration()


def test_hosted_generic_openai_host_still_refused():
    config = _ai_on(
        workspace_llm_endpoint="https://invented-owned-chief.openai.azure.com/openai/v1"
    )
    assert not config.workspace_llm_available
    assert config.runtime_configuration_errors()


def test_synth_os_still_requires_cosmascode_not_prod_or_arbitrary():
    config = Settings(  # pyright: ignore[reportCallIssue]
        _env_file=None,
        workspace_enabled=True,
        database_url="postgresql+psycopg://invented@127.0.0.1:55439/w1a_unit",
        workspace_llm_backend="azure_gpt41",
        workspace_llm_api_key="invented-test-only",
        workspace_llm_endpoint="https://other.services.ai.azure.com/openai/v1",
    )
    assert not config.workspace_llm_available
    assert config.runtime_configuration_errors()
    prod = Settings(  # pyright: ignore[reportCallIssue]
        _env_file=None,
        workspace_enabled=True,
        database_url="postgresql+psycopg://invented@127.0.0.1:55439/w1a_unit",
        workspace_llm_backend="azure_gpt41",
        workspace_llm_api_key="invented-test-only",
        workspace_llm_endpoint=PROD_ENDPOINT,
    )
    assert not prod.workspace_llm_available
    with pytest.raises(RuntimeError, match="Non-production profiles refuse the production"):
        prod.validate_runtime_configuration()


def test_backend_disabled_stays_unavailable_even_with_prod_endpoint():
    config = hosted(
        workspace_llm_backend="disabled",
        workspace_llm_endpoint=PROD_ENDPOINT,
        workspace_llm_api_key=None,
    )
    config.validate_runtime_configuration()
    assert not config.workspace_llm_available


def test_model_and_deployment_pins_unchanged_with_prod_endpoint():
    config = production_review(workspace_llm_endpoint=PROD_ENDPOINT)
    assert config.workspace_llm_deployment == "gpt-4.1"
    assert "gpt-4.1" in config.workspace_llm_reviewed_deployments
    assert config.workspace_llm_usdz_enabled is False
