"""T-PROD-1 (b): hosted AI may use CosmasCode or the #356 prod OpenAI host only."""

from __future__ import annotations

import re

import pytest
from tests.unit.test_hosted_workspace_config import hosted

from cosmas_os.config import (
    COSMASCODE_LLM_ENDPOINT,
    PROD_OPENAI_LLM_ENDPOINT_PATTERN,
    Settings,
    reviewed_hosted_llm_endpoint,
)

PROD_ENDPOINT = "https://oai-cbot-prd-abcd1234.openai.azure.com/openai/v1"


def _ai_on(**endpoint_or_changes):
    values = {
        "workspace_llm_backend": "azure_gpt41",
        "workspace_llm_deployment": "gpt-4.1",
        "workspace_llm_api_key": "invented-prod-or-shared-key",
        "workspace_llm_endpoint": COSMASCODE_LLM_ENDPOINT,
    }
    values.update(endpoint_or_changes)
    return hosted(**values)


def test_helper_accepts_cosmascode_and_narrow_prod_host_only():
    assert reviewed_hosted_llm_endpoint(COSMASCODE_LLM_ENDPOINT)
    assert reviewed_hosted_llm_endpoint(PROD_ENDPOINT)
    assert reviewed_hosted_llm_endpoint(
        "https://oai-cbot-prd-abcdefghij.openai.azure.com/openai/v1"
    )
    # Mutation: restoring CosmasCode-only equality fails the next assertion.
    assert COSMASCODE_LLM_ENDPOINT != PROD_ENDPOINT
    assert re.fullmatch(PROD_OPENAI_LLM_ENDPOINT_PATTERN, PROD_ENDPOINT)


@pytest.mark.parametrize(
    "endpoint",
    [
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
    ],
)
def test_helper_refuses_lookalike_and_broad_openai_hosts(endpoint):
    # Mutation: broadening to any `*.openai.azure.com` fails several of these.
    assert not reviewed_hosted_llm_endpoint(endpoint)


def test_hosted_production_accepts_prod_openai_endpoint():
    config = _ai_on(workspace_llm_endpoint=PROD_ENDPOINT)
    config.validate_runtime_configuration()
    assert config.workspace_available
    assert config.workspace_llm_available


def test_hosted_still_accepts_cosmascode_endpoint():
    config = _ai_on()
    config.validate_runtime_configuration()
    assert config.workspace_llm_available
    assert config.workspace_llm_endpoint == COSMASCODE_LLM_ENDPOINT


def test_hosted_lookalike_endpoint_refuses_ai_and_runtime():
    config = _ai_on(
        workspace_llm_endpoint="https://oai-cbot-stg-abcd1234.openai.azure.com/openai/v1"
    )
    assert config.workspace_available
    assert not config.workspace_llm_available
    with pytest.raises(RuntimeError, match="Workspace GPT-4.1"):
        config.validate_runtime_configuration()


def test_hosted_generic_openai_host_still_refused():
    # Staging/beta must not gain a wildcard; only the #356 naming pattern.
    config = _ai_on(
        workspace_llm_endpoint="https://invented-owned-chief.openai.azure.com/openai/v1"
    )
    assert not config.workspace_llm_available
    assert config.runtime_configuration_errors()


def test_synth_os_still_requires_cosmascode_or_prod_pattern_not_arbitrary():
    # Non-standalone path is shared; synth refuses lookalikes the same way.
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


def test_backend_disabled_stays_unavailable_even_with_prod_endpoint():
    config = hosted(
        workspace_llm_backend="disabled",
        workspace_llm_endpoint=PROD_ENDPOINT,
        workspace_llm_api_key=None,
    )
    config.validate_runtime_configuration()
    assert not config.workspace_llm_available


def test_model_and_deployment_pins_unchanged_with_prod_endpoint():
    config = _ai_on(workspace_llm_endpoint=PROD_ENDPOINT)
    assert config.workspace_llm_deployment == "gpt-4.1"
    assert "gpt-4.1" in config.workspace_llm_reviewed_deployments
    assert config.workspace_llm_usdz_enabled is False
