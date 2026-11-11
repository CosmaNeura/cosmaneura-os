"""CosmaBot Azure OpenAI chat deployment selection (T-USDZ).

The underlying model remains gpt-4.1 (2025-04-14). Only the Azure deployment
name may switch to the Data Zone Standard US deployment when the USDZ flag is
on. Endpoint and API key defaults stay in Settings / adapters; do not move them.

With the flag off, the chat deployment name stays the historical GlobalStandard
name so existing live users are unchanged.
"""

from __future__ import annotations

# Historical GlobalStandard deployment — default when the USDZ flag is off.
DEFAULT_DEPLOYMENT = "gpt-4.1"
# Data Zone Standard (US) deployment on the reviewed Azure OpenAI resource.
USDZ_DEPLOYMENT = "gpt-4.1-dzus"

REQUEST_DEPLOYMENTS = frozenset({DEFAULT_DEPLOYMENT, USDZ_DEPLOYMENT})
# Responses may echo the deployment name or the underlying gpt-4.1 version id.
RESPONSE_MODELS = frozenset({DEFAULT_DEPLOYMENT, USDZ_DEPLOYMENT, "gpt-4.1-2025-04-14"})


def chat_deployment(*, usdz_enabled: bool = False) -> str:
    """Return the Azure OpenAI request `model` (deployment name) for CosmaBot chat."""
    return USDZ_DEPLOYMENT if usdz_enabled else DEFAULT_DEPLOYMENT
