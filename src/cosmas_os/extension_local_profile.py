"""Opt-in loopback proof profile. No hosted Settings or route installation changes."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.engine import make_url

from cosmas_os.config import Settings

EXTENSION_ID = "dafmlbjpkdfjnchpcnghgkeckdbmofhf"
EXTENSION_ORIGIN = "chrome-extension://" + EXTENSION_ID
API_ORIGIN = "http://127.0.0.1:8766"


class ExtensionAuthSettings(Settings):
    """Default development sessions, isolated from the closed hosted profiles."""

    def clerk_session_configuration_errors(self) -> list[str]:
        if (self.cosmas_env != "synth_os" or self.data_mode != "synthetic"
                or self.auth_mode != "clerk_jwt" or self.synth_seed
                or self.clerk_session_policy != "shared_staging" or self.clerk_audience != ""
                or not re.fullmatch(r"https://[a-z0-9-]+\.clerk\.accounts\.dev", self.clerk_issuer or "")
                or self.allowed_origins != (EXTENSION_ORIGIN,)
                or self.authorized_parties != (EXTENSION_ORIGIN,)):
            return ["local_extension_auth_configuration_refused"]
        return []


@dataclass(frozen=True)
class LocalExtensionProfile:
    database_url: str
    issuer: str
    organization_id: str
    box_id: str

    def __post_init__(self) -> None:
        try:
            database = make_url(self.database_url)
            if (database.drivername != "postgresql+psycopg" or database.host != "127.0.0.1"
                    or database.database != "cosmabot_extension_synth" or not database.port
                    or database.query or not database.username):
                raise ValueError
            if not re.fullmatch(r"https://[a-z0-9-]+\.clerk\.accounts\.dev", self.issuer):
                raise ValueError
            if not re.fullmatch(r"org_[A-Za-z0-9_]{1,251}", self.organization_id):
                raise ValueError
            if str(UUID(self.box_id)) != self.box_id:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("local_extension_profile_refused") from None

    @classmethod
    def from_env(cls) -> LocalExtensionProfile:
        try:
            return cls(database_url=os.environ["COSMABOT_EXTENSION_DATABASE_URL"],
                       issuer=os.environ["COSMABOT_EXTENSION_CLERK_ISSUER"],
                       organization_id=os.environ["COSMABOT_EXTENSION_CLERK_ORGANIZATION_ID"],
                       box_id=os.environ["COSMABOT_EXTENSION_BOX_ID"])
        except KeyError:
            raise ValueError("local_extension_configuration_required") from None

    def auth_settings(self) -> ExtensionAuthSettings:
        # Never inherit .env, hosted flags, provider addresses or secrets.
        values = {name: field.default for name, field in Settings.model_fields.items()}
        return ExtensionAuthSettings(**{**values, "database_url": self.database_url,
            "cosmas_env": "synth_os", "data_mode": "synthetic", "auth_mode": "clerk_jwt",
            "synth_seed": False, "clerk_issuer": self.issuer,
            "clerk_jwks_url": self.issuer + "/.well-known/jwks.json",
            "clerk_session_policy": "shared_staging", "clerk_audience": "",
            "clerk_organization_id": self.organization_id, "beta_box_id": self.box_id,
            "clerk_authorized_parties": EXTENSION_ORIGIN, "cors_allowed_origins": EXTENSION_ORIGIN,
            "workspace_enrollment_managed": False}, _env_file=None)  # pyright: ignore[reportCallIssue]

    def admits_request(self, client_host: str | None, origins: list[str], hosts: list[str]) -> bool:
        return (client_host in {"127.0.0.1", "::1"}
                and origins == [EXTENSION_ORIGIN]
                and hosts == [urlparse(API_ORIGIN).netloc])
