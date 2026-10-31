"""Pinned CosmaBot Azure OpenAI chat deployment selection.

The underlying model remains gpt-4.1 (2025-04-14). Only the Azure deployment
name is pinned here so Chief, tools and note drafting share one default.
Endpoint and API key defaults stay in Settings / adapters; do not move them.
"""

# Data Zone Standard (US) deployment name on the reviewed Azure OpenAI resource.
DEPLOYMENT = "gpt-4.1-dzus"
