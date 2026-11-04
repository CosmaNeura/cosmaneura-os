"""Staging and production hosting coordinates for automatic practice workspaces.

Every value that differs between the synthetic staging foundation and the
production foundation lives here, so one environment never borrows another's
origins, identity, names or data mode.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class HostingEnvironment:
    """Every environment-specific hosting value, so staging and production never mix."""

    name: str
    short: str
    app_origin: str
    api_origin: str
    workspace_domain: str
    enrollment_data_mode: str
    runtime_data_mode: str
    synthetic_only: bool

    def workspace_origin(self, practice_id: str) -> str:
        return "https://" + practice_id + "." + self.workspace_domain

    def workspace_api_origin(self, practice_id: str) -> str:
        return "https://api." + practice_id + "." + self.workspace_domain

    def issuer_allowed(self, issuer: str) -> bool:
        if self.name == "production":
            return issuer == PRODUCTION_CLERK_ISSUER
        return bool(re.fullmatch(r"https://[a-z0-9-]+[.]clerk[.]accounts[.]dev", issuer))

    def publishable_key(self, issuer: str) -> str:
        kind = "live" if self.name == "production" else "test"
        return f"pk_{kind}_" + base64.b64encode((issuer[8:] + "$").encode()).decode()


PRODUCTION_CLERK_ISSUER = "https://clerk.cosmas.ai"
HOSTING_ENVIRONMENTS = {
    "staging": HostingEnvironment("staging", "stg", "https://onboarding.staging.cosmas.ai",
                                  "https://enrollment-api.staging.cosmas.ai", "staging.cosmas.ai",
                                  "synthetic", "synthetic", True),
    "production": HostingEnvironment("production", "prd", "https://app.cosmas.ai",
                                     "https://enrollment-api.cosmas.ai", "workspace.cosmas.ai",
                                     "production", "authorized_beta", False),
}


def hosting_environment_for_data_mode(data_mode: str) -> HostingEnvironment | None:
    return next((env for env in HOSTING_ENVIRONMENTS.values() if env.enrollment_data_mode == data_mode), None)
