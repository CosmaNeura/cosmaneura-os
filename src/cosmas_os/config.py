from __future__ import annotations

from typing import Literal
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from pydantic import SecretStr
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
    clerk_session_policy: Literal["audience", "shared_staging"] = "audience"
    clerk_organization_id: str | None = None
    clerk_authorized_parties: str = ""
    beta_box_id: str | None = None

    clinic_approval_ref: str | None = None
    baa_evidence_ref: str | None = None
    human_deploy_evidence_ref: str | None = None
    phi_authorization_ref: str | None = None

    cosmas_clock_now: str | None = None
    sync_worker: bool = True  # execute operations in-process when True (tests/demo)
    execution_backend: Literal["celery", "postgres_local"] = "celery"
    compact_web_root: str | None = None
    workspace_enabled: bool = False
    # Private preset/rehearsal UI only; stored capability denies remain enforced when off.
    workspace_team_setup_enabled: bool = False
    # Private read-only admission/usage history; independent from model execution.
    workspace_ai_activity_enabled: bool = False
    # Public research is independent from private chat and external clinical writes.
    workspace_research_enabled: bool = False
    workspace_research_io_enabled: bool = False
    research_sources: str = "pubmed,clinical_trials,dailymed,rxnorm,openfda,npi_registry"
    # Closed source-specific dataset mappings; never a browser-supplied URL or query language.
    research_dataset_mappings: str = "{}"
    research_openfda_api_key: SecretStr | None = None
    workspace_authenticated_enabled: bool = False
    # Hosted workspace is explicit and retains all early-adopter deployment gates.
    workspace_hosted_enabled: bool = False
    workspace_apple_hosted_transport_enabled: bool = False
    workspace_desktop_hosted_transport_enabled: bool = False
    # Paired client/backend gate; hosted profiles also require the workspace protocol.
    # Grants no identity or action authority.
    workspace_draft_recovery_required: bool = False
    workspace_native_synthetic_enabled: bool = False
    # Local Apple transport rehearsal only; does not enable a native login provider.
    workspace_apple_local_transport_enabled: bool = False
    # Direct main-process loopback transport; no hosted/native identity activation.
    workspace_desktop_local_transport_enabled: bool = False
    workspace_capture_backend: Literal["disabled", "core"] = "disabled"
    workspace_capture_notes_enabled: bool = False
    # Open the existing Cosmaneura record; no clinical write or EHR authority.
    workspace_core_record_enabled: bool = False
    core_web_origin: str = ""
    workspace_core_connection_enabled: bool = False
    workspace_athena_connection_enabled: bool = False
    workspace_athena_visit_link_enabled: bool = False
    workspace_core_appointment_setup_enabled: bool = False
    # Reviewed deployment correspondence for this Box; never supplied by a client.
    core_connection_tenant_ref: str = ""
    workspace_prep_enabled: bool = False
    # Internal F-8 preparation work only; no patient channel or Core write authority.
    workspace_prep_work_enabled: bool = False
    workspace_scheduling_enabled: bool = False
    workspace_scheduling_login_enabled: bool = False
    workspace_scheduling_enrollment_enabled: bool = False
    scheduling_enrollment_practice_id: str = ""
    scheduling_origin: str = ""
    scheduling_google_client_id: str = ""
    scheduling_google_client_secret: SecretStr | None = None
    scheduling_google_callback_uri: str = ""
    scheduling_login_return_origin: str = ""
    scheduling_login_encryption_key: SecretStr | None = None
    workspace_google_connection_enabled: bool = False
    # Separate opt-in for explicit selected whole-message custody and review.
    workspace_google_message_enabled: bool = False
    google_connection_client_id: str = ""
    google_connection_client_secret: SecretStr | None = None
    google_connection_callback_uri: str = ""
    google_connection_return_origin: str = ""
    google_connection_encryption_key: SecretStr | None = None
    workspace_microsoft_connection_enabled: bool = False
    microsoft_connection_tenant_id: str = ""
    microsoft_connection_client_id: str = ""
    microsoft_connection_client_secret: SecretStr | None = None
    microsoft_connection_callback_uri: str = ""
    microsoft_connection_return_origin: str = ""
    microsoft_connection_encryption_key: SecretStr | None = None
    # Local F-8 proposal/review surface only; no appointment execution activation.
    workspace_appointments_enabled: bool = False
    # Independent delivery/custody gates. Configuration and approval never enable I/O.
    vendor_work_enabled: bool = False
    vendor_io_enabled: bool = False
    vendor_events_enabled: bool = False
    vendor_setup_enabled: bool = False
    # Deployment-owned, hash-pinned account catalog; secrets are separate process inputs.
    managed_services_config_path: str = ""
    managed_services_config_json: SecretStr | None = None
    managed_services_config_sha256: str = ""
    # Reviewed portal mappings; provider IO additionally requires an installed service profile.
    portal_setup_enabled: bool = False
    portal_work_enabled: bool = False
    portal_io_enabled: bool = False
    finance_work_enabled: bool = False
    finance_setup_enabled: bool = False
    membership_work_enabled: bool = False
    inbox_work_enabled: bool = False
    # Explicit internal handoffs also require current independently reviewed Inbox authority.
    inbox_handoff_enabled: bool = False
    finance_io_enabled: bool = False
    finance_events_enabled: bool = False
    # Local deterministic F-8 briefs only; grants no model or external authority.
    workspace_routines_enabled: bool = False
    # Founder-owned, no active cohort; review by 2026-09-30.
    workspace_capture_corrections_enabled: bool = False
    # Founder-owned, no active cohort; review by 2026-09-30.
    workspace_capture_recovery_enabled: bool = False
    # Founder-owned, no released cohort; review by 2026-09-30.
    workspace_capture_source_enabled: bool = False
    # Founder-owned local cohort only; review by 2026-10-20. Retain admitted profiles on disable.
    workspace_capture_long_visits_enabled: bool = False
    core_capture_origin: str = ""
    core_capture_scope: str = ""
    core_capture_managed_identity_client_id: str = ""
    # Separate activation and caller configuration for Core's prepared artifact.
    workspace_session_prep_enabled: bool = False
    core_session_prep_scope: str = ""
    core_session_prep_managed_identity_client_id: str = ""
    workspace_llm_backend: Literal["disabled", "azure_gpt41"] = "disabled"
    workspace_llm_endpoint: str = "https://cosmascode.services.ai.azure.com/openai/v1"
    workspace_llm_deployment: str = "gpt-4.1"
    workspace_llm_api_key: SecretStr | None = None
    # New admissions opt into the closed product reader loop; saved v1–v4
    # requests retain their original single-response contract.
    workspace_agent_tools_enabled: bool = False

    @property
    def workspace_google_message_available(self) -> bool:
        return bool(self.workspace_google_message_enabled and self.workspace_google_connection_enabled
                    and self.workspace_available and self.workspace_authenticated_enabled
                    and self.auth_mode == "clerk_jwt")

    @property
    def workspace_research_available(self) -> bool:
        return bool(self.workspace_research_enabled and self.workspace_available
                    and self.workspace_authenticated_enabled and self.auth_mode == "clerk_jwt")

    @property
    def research_configured_sources(self) -> frozenset[str]:
        from cosmas_os.ports.research import SOURCES
        values = frozenset(part.strip() for part in self.research_sources.split(",") if part.strip())
        if not values <= SOURCES.keys():
            raise ValueError("unknown research source")
        return values

    @property
    def workspace_scheduling_available(self) -> bool:
        return bool(self.workspace_scheduling_enabled and self.workspace_available
                    and self.workspace_authenticated_enabled and self.auth_mode == "clerk_jwt")

    @property
    def workspace_capture_available(self) -> bool:
        try:
            UUID(self.core_capture_managed_identity_client_id)
            origin = urlparse(self.core_capture_origin)
            if origin.port not in (None, 443) or any(c.isspace() for c in self.core_capture_origin):
                return False
        except ValueError:
            return False
        return bool(
            self.workspace_available and self.workspace_authenticated_enabled
            and self.workspace_capture_backend == "core"
            and self._is_exact_https_origin(self.core_capture_origin)
            and self.core_capture_scope.startswith("api://")
            and self.core_capture_scope.endswith("/.default")
            and not any(c.isspace() for c in self.core_capture_scope)
        )

    @property
    def workspace_session_prep_available(self) -> bool:
        try:
            UUID(self.core_session_prep_managed_identity_client_id)
        except ValueError:
            return False
        return bool(self.workspace_session_prep_enabled and self.workspace_capture_available
                    and self.workspace_prep_enabled and self.auth_mode == "clerk_jwt"
                    and self.core_session_prep_scope.startswith("api://")
                    and self.core_session_prep_scope.endswith("/.default")
                    and not any(c.isspace() for c in self.core_session_prep_scope))

    @property
    def workspace_core_connection_available(self) -> bool:
        import re

        from cosmas_os.ports.core_record_location import valid_core_web_origin
        return bool(self.workspace_core_connection_enabled and self.workspace_available
                    and self.workspace_authenticated_enabled and self.auth_mode == "clerk_jwt"
                    and valid_core_web_origin(self.core_capture_origin)
                    and not self.core_capture_origin.endswith(".localhost")
                    and re.fullmatch(r"authority_tenant_[0-7][0-9a-hjkmnp-tv-z]{25}", self.core_connection_tenant_ref))

    @property
    def workspace_core_appointment_setup_available(self) -> bool:
        return bool(self.workspace_core_appointment_setup_enabled and self.workspace_core_connection_available)

    @property
    def workspace_athena_connection_available(self) -> bool:
        return bool(self.workspace_athena_connection_enabled and self.workspace_core_connection_available)

    @property
    def workspace_athena_visit_link_available(self) -> bool:
        return bool(self.workspace_athena_visit_link_enabled and self.workspace_athena_connection_available)

    @property
    def workspace_core_record_available(self) -> bool:
        from cosmas_os.ports.core_record_location import valid_core_web_origin
        return bool(self.workspace_core_record_enabled and self.workspace_capture_available
                    and valid_core_web_origin(self.core_web_origin))

    @property
    def workspace_llm_available(self) -> bool:
        return bool(self.workspace_available and self.workspace_llm_backend == "azure_gpt41"
                    and self.workspace_llm_endpoint == "https://cosmascode.services.ai.azure.com/openai/v1"
                    and self.workspace_llm_deployment == "gpt-4.1"
                    and self.workspace_llm_api_key and self.workspace_llm_api_key.get_secret_value())

    @property
    def workspace_available(self) -> bool:
        if self.workspace_hosted_enabled:
            return bool(
                self.workspace_enabled and self.workspace_authenticated_enabled
                and self.cosmas_env == "early_adopter_beta"
                and not self.workspace_native_synthetic_enabled
                and not self.workspace_apple_local_transport_enabled
                and not self.workspace_desktop_local_transport_enabled
                and not self.workspace_authentication_errors()
                and not self._beta_configuration_errors()
            )
        if self.workspace_apple_hosted_transport_enabled or self.workspace_desktop_hosted_transport_enabled:
            return False
        database = urlparse(self.database_url)
        origins = self.allowed_origins
        return bool(
            self.workspace_enabled
            and self.cosmas_env == "synth_os"
            and self.data_mode == "synthetic"
            and (
                self.auth_mode == "synth_headers" and not self.workspace_authenticated_enabled
                and not self.workspace_apple_local_transport_enabled
                and not self.workspace_desktop_local_transport_enabled
                or self.auth_mode == "clerk_jwt" and self.workspace_authenticated_enabled
                and not self.workspace_authentication_errors()
            )
            and self.blob_backend == "local"
            and database.scheme == "postgresql+psycopg"
            and database.hostname in {"127.0.0.1", "localhost", "::1"}
            and database.path.startswith("/w1a_")
            and not database.query and not database.fragment
            and bool(origins)
            and all(self._is_workspace_origin(origin) for origin in origins)
        )

    def workspace_authentication_errors(self) -> list[str]:
        """Validate the identity boundary for the selected workspace profile."""
        errors: list[str] = []
        if self.auth_mode != "clerk_jwt" or self.synth_seed:
            errors.append("Authenticated workspace requires Clerk JWTs with synthetic seeding disabled")
        if self.workspace_native_synthetic_enabled:
            errors.append("Authenticated native workspace transport is not yet qualified")
        if self.workspace_apple_local_transport_enabled and (
            "capacitor://localhost" not in self.allowed_origins
            or "capacitor://localhost" not in self.authorized_parties
        ):
            errors.append("Local Apple transport requires its exact origin and authorized party")
        if self.workspace_desktop_local_transport_enabled and (
            "app://cosmas" not in self.allowed_origins
            or "app://cosmas" not in self.authorized_parties
        ):
            errors.append("Local desktop transport requires its exact origin and authorized party")
        for enabled, origin in (
            (self.workspace_apple_hosted_transport_enabled, "capacitor://localhost"),
            (self.workspace_desktop_hosted_transport_enabled, "app://cosmas"),
        ):
            if enabled and (not self.workspace_hosted_enabled
                            or origin not in self.allowed_origins
                            or origin not in self.authorized_parties):
                errors.append("Hosted native transport requires its exact origin and authorized party")
        try:
            UUID(self.beta_box_id or "")
        except ValueError:
            errors.append("Authenticated workspace requires a configured Box UUID")
        if not self.clerk_organization_id or self.clerk_session_configuration_errors():
            errors.append("Authenticated workspace requires a Clerk organization and audience")
        issuer = urlparse(self.clerk_issuer or "")
        jwks = urlparse(self.clerk_jwks_url or "")
        if not self.clerk_issuer or not self._is_exact_https_origin(self.clerk_issuer):
            errors.append("Authenticated workspace requires an exact HTTPS Clerk issuer")
        if (
            jwks.scheme != "https" or not jwks.netloc or jwks.netloc != issuer.netloc
            or jwks.path != "/.well-known/jwks.json" or jwks.params
            or jwks.username is not None or jwks.password is not None
            or jwks.query or jwks.fragment
        ):
            errors.append("Authenticated workspace requires the issuer's fixed JWKS URL")
        if (
            not self.authorized_parties
            or not all(self._is_workspace_origin(value) for value in self.authorized_parties)
            or not set(self.authorized_parties).issubset(set(self.allowed_origins))
        ):
            errors.append("Authenticated workspace requires explicitly allowed authorized parties")
        return errors

    def _is_workspace_origin(self, value: str) -> bool:
        if self.workspace_hosted_enabled:
            return self._is_hosted_workspace_origin(value)
        if self.workspace_desktop_local_transport_enabled and value == "app://cosmas":
            return True
        if (self.workspace_native_synthetic_enabled or self.workspace_apple_local_transport_enabled) and value == "capacitor://localhost":
            return True
        origin = urlparse(value)
        return bool(
            origin.scheme == "http" and origin.hostname in {"127.0.0.1", "localhost", "::1"}
            and origin.username is None and origin.password is None
            and origin.path in {"", "/"} and not origin.query
            and not origin.fragment and not origin.params
        )

    def _is_hosted_workspace_origin(self, value: str) -> bool:
        if self.cosmas_env != "early_adopter_beta":
            return False
        if value == "app://cosmas":
            return self.workspace_desktop_hosted_transport_enabled
        if value == "capacitor://localhost":
            return self.workspace_apple_hosted_transport_enabled
        try:
            parsed = urlparse(value)
            return bool(
                self._is_exact_https_origin(value) and parsed.port is None
                and value == "https://" + (parsed.hostname or "")
                and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                and "." in (parsed.hostname or "") and not any(c.isspace() for c in value)
            )
        except ValueError:
            return False

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
        if self.clerk_session_policy == "shared_staging":
            errors.extend(self.clerk_session_configuration_errors())
        if self.workspace_scheduling_enrollment_enabled:
            try:
                practice = str(UUID(self.scheduling_enrollment_practice_id))
            except ValueError:
                practice = ""
            if not self.workspace_scheduling_available or not self.workspace_scheduling_login_enabled or not practice or practice != self.scheduling_enrollment_practice_id:
                errors.append("Scheduling enrollment requires configured sign-in and one reviewed practice")

        if self.workspace_core_appointment_setup_enabled and not self.workspace_core_appointment_setup_available:
            errors.append("Appointment setup requires an authenticated, configured Core connection")
        if self.workspace_athena_visit_link_enabled and not self.workspace_athena_visit_link_available:
            errors.append("Athena visit linking requires a configured, read-only Athena connection")
        if self.workspace_athena_connection_enabled and not self.workspace_athena_connection_available:
            errors.append("Athena connection requires an authenticated, configured Core connection")
        if self.workspace_core_connection_enabled and not self.workspace_core_connection_available:
            errors.append("Core connection requires an authenticated workspace, exact HTTPS origin and reviewed tenant correspondence")
        if self.workspace_hosted_enabled and not self.workspace_available:
            errors.append("Hosted workspace requires authenticated early_adopter_beta and complete deployment configuration")
        if (self.workspace_apple_hosted_transport_enabled or self.workspace_desktop_hosted_transport_enabled) and not self.workspace_hosted_enabled:
            errors.append("Hosted native transport requires WORKSPACE_HOSTED_ENABLED")
        if self.workspace_capture_backend != "disabled" and not self.workspace_capture_available:
            errors.append("Workspace capture requires an authenticated workspace and complete Core workload configuration")
        if self.workspace_llm_backend != "disabled" and not self.workspace_llm_available:
            errors.append("Workspace GPT-4.1 requires an available workspace and the exact configured deployment")
        if self.workspace_enabled and not self.workspace_available:
            errors.append("WORKSPACE_ENABLED requires the dedicated local synthetic or hosted beta profile")
        if self.workspace_authenticated_enabled:
            errors.extend(self.workspace_authentication_errors())
            if not self.workspace_available:
                errors.append("Authenticated workspace requires a complete workspace profile")
        if self.workspace_draft_recovery_required and (not self.workspace_available or not self.workspace_authenticated_enabled):
            errors.append("Required draft recovery needs the authenticated workspace profile")
        if self.workspace_native_synthetic_enabled and not self.workspace_available:
            errors.append("Native workspace access requires the dedicated local synthetic workspace")
        if self.workspace_apple_local_transport_enabled and (
            not self.workspace_authenticated_enabled or not self.workspace_available
        ):
            errors.append("Local Apple transport requires the dedicated authenticated synthetic workspace")
        if self.workspace_desktop_local_transport_enabled and (
            not self.workspace_authenticated_enabled or not self.workspace_available
        ):
            errors.append("Local desktop transport requires the dedicated authenticated synthetic workspace")
        if self.cosmas_env not in {"synth_os", "early_adopter_beta"}:
            errors.append("COSMAS_ENV is not an enabled Track B environment")

        if not self.allowed_origins:
            errors.append("CORS_ALLOWED_ORIGINS must contain at least one origin")
        if "*" in self.allowed_origins:
            errors.append("CORS_ALLOWED_ORIGINS must not contain a wildcard")

        if self.compact_web_root and self.execution_backend != "postgres_local":
            errors.append("COMPACT_WEB_ROOT requires the local execution experiment")
        if self.execution_backend == "postgres_local":
            if (
                self.cosmas_env != "synth_os"
                or self.data_mode != "synthetic"
                or self.auth_mode != "synth_headers"
                or self.blob_backend != "local"
                or self.sync_worker
            ):
                errors.append("postgres_local requires asynchronous local synthetic mode; beta is not enabled")
            database = urlparse(self.database_url)
            if (
                database.scheme != "postgresql+psycopg"
                or database.hostname not in {"127.0.0.1", "localhost", "::1", "compact-db"}
                or database.path not in {"/compact_test", "/compact_demo"}
                or database.username != "compact_synth"
                or database.query or database.fragment or database.params
            ):
                errors.append("postgres_local requires a dedicated local compact database")
            for origin in self.allowed_origins:
                parsed = urlparse(origin)
                if (
                    parsed.scheme != "http"
                    or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path not in {"", "/"}
                ):
                    errors.append("postgres_local origins must be exact loopback HTTP origins")
                    break

        if self.cosmas_env != "early_adopter_beta":
            return errors

        return errors + self._beta_configuration_errors()

    def clerk_session_configuration_errors(self) -> list[str]:
        if self.clerk_session_policy == "audience":
            return [] if self.clerk_audience else ["CLERK_AUDIENCE is required"]
        if (self.clerk_session_policy != "shared_staging" or self.clerk_audience != ""
                or self.cosmas_env != "early_adopter_beta" or self.data_mode != "synthetic"
                or self.auth_mode != "clerk_jwt"
                or not self._is_exact_https_origin(self.clerk_issuer or "")
                or not (urlparse(self.clerk_issuer or "").hostname or "").endswith(".clerk.accounts.dev")):
            return ["Shared Clerk sessions require synthetic beta, a development issuer and explicitly empty audience"]
        return []

    def _beta_configuration_errors(self) -> list[str]:
        """Independent cloud prerequisites; never call workspace_available here."""
        errors = self.clerk_session_configuration_errors()

        required = {
            "BETA_BOX_ID": self.beta_box_id,
            "CLERK_ISSUER": self.clerk_issuer,
            "CLERK_JWKS_URL": self.clerk_jwks_url,
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
            if not (self._is_hosted_workspace_origin(origin) if self.workspace_hosted_enabled
                    else self._is_exact_https_origin(origin)):
                errors.append("beta CORS origins must be exact https origins")
                break

        if not self.authorized_parties:
            errors.append("CLERK_AUTHORIZED_PARTIES must contain at least one origin")
        elif not all((self._is_hosted_workspace_origin(value) if self.workspace_hosted_enabled
                      else self._is_exact_https_origin(value)) for value in self.authorized_parties):
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
