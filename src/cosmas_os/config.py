from __future__ import annotations

from typing import Literal
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os"
    redis_url: str = "redis://localhost:63799/0"
    cosmas_env: str = "synth_os"
    data_mode: Literal["synthetic", "authorized_beta"] = "synthetic"
    auth_mode: Literal["synth_headers", "clerk_jwt"] = "synth_headers"
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    synth_seed: bool = True

    blob_root: str = "./data/blobs"
    blob_backend: Literal["local", "azure"] = "local"
    azure_storage_account_url: str | None = None
    azure_blob_container: str | None = None

    clerk_issuer: str | None = None
    clerk_jwks_url: str | None = None
    clerk_audience: str | None = None
    clerk_organization_id: str | None = None
    clerk_authorized_parties: str = ""
    beta_box_id: str | None = None

    clinic_approval_ref: str | None = None
    baa_evidence_ref: str | None = None
    human_deploy_evidence_ref: str | None = None
    phi_authorization_ref: str | None = None

    cosmas_clock_now: str | None = None
    sync_worker: bool = True  # execute operations in-process when True (tests/demo)

    @staticmethod
    def _csv(value: str) -> tuple[str, ...]:
        return tuple(part.strip() for part in value.split(",") if part.strip())

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return self._csv(self.cors_allowed_origins)

    @property
    def authorized_parties(self) -> tuple[str, ...]:
        return self._csv(self.clerk_authorized_parties)

    @staticmethod
    def _is_exact_https_origin(value: str) -> bool:
        parsed = urlparse(value)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
        )

    def runtime_configuration_errors(self) -> list[str]:
        """Return configuration faults without exposing configured values."""

        errors: list[str] = []
        if self.cosmas_env not in {"synth_os", "early_adopter_beta"}:
            errors.append("COSMAS_ENV is not an enabled Track B environment")

        if not self.allowed_origins:
            errors.append("CORS_ALLOWED_ORIGINS must contain at least one origin")
        if "*" in self.allowed_origins:
            errors.append("CORS_ALLOWED_ORIGINS must not contain a wildcard")

        if self.cosmas_env != "early_adopter_beta":
            return errors

        required = {
            "BETA_BOX_ID": self.beta_box_id,
            "CLERK_ISSUER": self.clerk_issuer,
            "CLERK_JWKS_URL": self.clerk_jwks_url,
            "CLERK_AUDIENCE": self.clerk_audience,
            "CLERK_ORGANIZATION_ID": self.clerk_organization_id,
            "CLERK_AUTHORIZED_PARTIES": self.clerk_authorized_parties,
            "AZURE_STORAGE_ACCOUNT_URL": self.azure_storage_account_url,
            "AZURE_BLOB_CONTAINER": self.azure_blob_container,
            "HUMAN_DEPLOY_EVIDENCE_REF": self.human_deploy_evidence_ref,
        }
        errors.extend(f"{name} is required" for name, value in required.items() if not value)

        if self.auth_mode != "clerk_jwt":
            errors.append("AUTH_MODE must be clerk_jwt")
        if self.blob_backend != "azure":
            errors.append("BLOB_BACKEND must be azure")
        if self.synth_seed:
            errors.append("SYNTH_SEED must be false")
        if self.sync_worker:
            errors.append("SYNC_WORKER must be false")
        if self.data_mode == "authorized_beta":
            protected_data_requirements = {
                "CLINIC_APPROVAL_REF": self.clinic_approval_ref,
                "BAA_EVIDENCE_REF": self.baa_evidence_ref,
                "PHI_AUTHORIZATION_REF": self.phi_authorization_ref,
            }
            errors.extend(
                f"authorized_beta data requires {name}"
                for name, value in protected_data_requirements.items()
                if not value
            )

        if self.beta_box_id:
            try:
                UUID(self.beta_box_id)
            except ValueError:
                errors.append("BETA_BOX_ID must be a UUID")

        for name, value in (
            ("CLERK_ISSUER", self.clerk_issuer),
            ("CLERK_JWKS_URL", self.clerk_jwks_url),
            ("AZURE_STORAGE_ACCOUNT_URL", self.azure_storage_account_url),
        ):
            if value and urlparse(value).scheme != "https":
                errors.append(f"{name} must use https")

        if self.clerk_issuer and not self._is_exact_https_origin(self.clerk_issuer):
            errors.append("CLERK_ISSUER must be an exact https origin")
        if self.azure_storage_account_url and not self._is_exact_https_origin(
            self.azure_storage_account_url
        ):
            errors.append("AZURE_STORAGE_ACCOUNT_URL must be an exact https origin")
        if self.clerk_jwks_url:
            parsed_jwks = urlparse(self.clerk_jwks_url)
            if (
                not parsed_jwks.hostname
                or parsed_jwks.username is not None
                or parsed_jwks.password is not None
                or parsed_jwks.query
                or parsed_jwks.fragment
            ):
                errors.append("CLERK_JWKS_URL must be an https URL without credentials")

        issuer = urlparse(self.clerk_issuer or "")
        jwks = urlparse(self.clerk_jwks_url or "")
        if issuer.netloc and jwks.netloc and (
            issuer.scheme,
            issuer.hostname,
            issuer.port,
        ) != (jwks.scheme, jwks.hostname, jwks.port):
            errors.append("CLERK_JWKS_URL must use the CLERK_ISSUER origin")

        for origin in self.allowed_origins:
            if not self._is_exact_https_origin(origin):
                errors.append("beta CORS origins must be exact https origins")
                break

        if not self.authorized_parties:
            errors.append("CLERK_AUTHORIZED_PARTIES must contain at least one origin")
        elif not all(self._is_exact_https_origin(value) for value in self.authorized_parties):
            errors.append("CLERK_AUTHORIZED_PARTIES must contain exact https origins")
        elif not set(self.authorized_parties).issubset(set(self.allowed_origins)):
            errors.append("CLERK_AUTHORIZED_PARTIES must be a subset of CORS_ALLOWED_ORIGINS")

        redis = urlparse(self.redis_url)
        if redis.scheme != "rediss" or redis.hostname in {None, "localhost", "127.0.0.1", "::1"}:
            errors.append("REDIS_URL must use a non-local rediss endpoint")
        redis_query = parse_qs(redis.query, keep_blank_values=True)
        if (
            redis.username not in {None, ""}
            or not redis.password
            or redis.path != "/0"
            or redis.params
            or redis.fragment
        ):
            errors.append("REDIS_URL must use the dedicated authenticated database 0 endpoint")
        if set(redis_query) != {"ssl_cert_reqs"}:
            errors.append("REDIS_URL must contain only the required TLS parameter")
        if redis_query.get("ssl_cert_reqs") != ["required"]:
            errors.append("REDIS_URL must require certificate verification")

        database = urlparse(self.database_url)
        if database.scheme != "postgresql+psycopg" or database.hostname in {
            None,
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            errors.append("DATABASE_URL must use a non-local PostgreSQL psycopg endpoint")
        if (
            not database.username
            or not database.password
            or database.path != "/cosmas_os"
            or database.params
            or database.fragment
        ):
            errors.append("DATABASE_URL must use the dedicated authenticated cosmas_os database")
        database_query = parse_qs(database.query, keep_blank_values=True)
        if set(database_query) != {"sslmode", "sslrootcert"}:
            errors.append("DATABASE_URL must contain only the required TLS parameters")
        if database_query.get("sslmode") != ["verify-full"]:
            errors.append("DATABASE_URL must use sslmode=verify-full")
        if database_query.get("sslrootcert") != ["system"]:
            errors.append("DATABASE_URL must use sslrootcert=system")

        return errors

    def validate_runtime_configuration(self) -> None:
        errors = self.runtime_configuration_errors()
        if errors:
            raise RuntimeError("unsafe runtime configuration: " + "; ".join(errors))


settings = Settings()
