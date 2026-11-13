from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cosmas_os.workspace_llm import DEFAULT_DEPLOYMENT, USDZ_DEPLOYMENT

STANDALONE_ENVS = frozenset({"standalone_synthetic", "standalone_clerk_synthetic"})

# Shared CosmasCode Azure OpenAI v1 origin used by staging/synth/live-today hosts.
COSMASCODE_LLM_ENDPOINT = "https://cosmascode.services.ai.azure.com/openai/v1"
# Production account from #356: name/custom_subdomain `oai-cbot-prd-${suffix}`
# with suffix `[a-z0-9]{6,10}` → classic `*.openai.azure.com` (not services.ai).
# App form appends `/openai/v1` to the Cognitive account base URL.
PROD_OPENAI_LLM_ENDPOINT_PATTERN = (
    r"https://oai-cbot-prd-[a-z0-9]{6,10}\.openai\.azure\.com/openai/v1"
)
# Exact CosmasCode or #356 production chat URL. Shared with gpt41_tools.
REVIEWED_HOSTED_CHAT_COMPLETIONS_URL_PATTERN = (
    r"(?:"
    + re.escape(COSMASCODE_LLM_ENDPOINT)
    + r"|"
    + PROD_OPENAI_LLM_ENDPOINT_PATTERN
    + r")/chat/completions"
)


def reviewed_hosted_llm_endpoint(endpoint: str) -> bool:
    """True when the endpoint form is CosmasCode or the #356 production pattern.

    Environment binding (production-review vs staging) is applied separately in
    ``Settings.workspace_llm_available`` / ``runtime_configuration_errors``.
    """
    return endpoint == COSMASCODE_LLM_ENDPOINT or bool(
        re.fullmatch(PROD_OPENAI_LLM_ENDPOINT_PATTERN, endpoint)
    )


def hosted_chat_completions_url(endpoint: str) -> str | None:
    """Resolve the hosted chat/completions URL for runtime dispatch.

    Returns None when the configured base is CosmasCode so callers keep today's
    adapter default path. Returns an explicit URL for the #356 production host.
    Raises ValueError with a non-secret code when the configured base is set but
    unusable — never silently falls back to CosmasCode.
    """
    if endpoint == COSMASCODE_LLM_ENDPOINT:
        return None
    if bool(re.fullmatch(PROD_OPENAI_LLM_ENDPOINT_PATTERN, endpoint)):
        return endpoint + "/chat/completions"
    raise ValueError("hosted_chat_endpoint_refused")


def _production_openai_endpoint(endpoint: str) -> bool:
    return bool(re.fullmatch(PROD_OPENAI_LLM_ENDPOINT_PATTERN, endpoint or ""))


def _hosted_review_profile_kind(settings: Settings) -> str | None:
    from cosmas_os.production_review_profile import classify_review_profile

    return classify_review_profile(
        policy=settings.clerk_session_policy,
        web_origin=None,
        cors=settings.cors_allowed_origins,
        issuer=settings.clerk_issuer,
    )


def _incomplete_production_review(settings: Settings, kind: str | None) -> bool:
    """True when beta.cosmas.ai appears but the profile is not exclusive review.

    Staging CORS never includes beta (VM render pins one web_origin). An
    almost-review profile must not silently fall through to CosmasCode.
    """
    from cosmas_os.production_review_profile import REVIEW_WEB_ORIGIN

    return REVIEW_WEB_ORIGIN in settings.allowed_origins and kind != "review"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os"
    redis_url: str = "redis://localhost:63799/0"
    cosmas_env: str = "synth_os"
    # Offline, independent practice proof. Never an alias for hosted beta.
    standalone_instance_id: str = ""
    standalone_root: str = ""
    standalone_jwks_path: str = ""
    # Separate reviewed issuer selection; never inferred from email or an old account.
    standalone_clerk_issuer_allowlist: str = ""
    # Explicit owned model-resource selection; never inherit the legacy endpoint.
    standalone_model_origin_allowlist: str = ""
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
    clerk_session_policy: Literal["audience", "shared_staging", "enrollment_default"] = "audience"
    clerk_organization_id: str | None = None
    clerk_authorized_parties: str = ""
    # Legacy Backend secret name; CosmaBot account delete does not read it.
    # Standalone entrypoint refuses CLERK_SECRET_KEY so sign-in stays JWKS-only.
    clerk_secret_key: SecretStr | None = None
    # Dedicated Backend secret for self-serve account deletion only. Never logged
    # or committed. Staging standalone may mount ACCOUNT_DELETE_CLERK_SECRET_KEY;
    # production standalone profiles refuse it.
    account_delete_clerk_secret_key: SecretStr | None = None
    beta_box_id: str | None = None

    clinic_approval_ref: str | None = None
    baa_evidence_ref: str | None = None
    human_deploy_evidence_ref: str | None = None
    phi_authorization_ref: str | None = None
    # Process env must stay false. Real-patient recording is a Box DB switch only
    # and takes effect solely when clinic/BAA/PHI refs are present (T-REL-6).
    real_patient_recording_enabled: bool = False

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
    # Protected deployer injects exact release identity for signed enrollment
    # qualification. Empty defaults keep the additive endpoint unavailable.
    workspace_release_source_commit: str = ""
    workspace_release_image_sha256: str = ""
    workspace_enrollment_managed: bool = False
    workspace_enrollment_practice_id: str = ""
    workspace_enrollment_api_origin: str = ""
    workspace_enrollment_origin_allowlist: str = ""
    # Per-Box derived key only; the central master never enters a workspace.
    workspace_enrollment_admission_secret: SecretStr | None = None
    workspace_enrollment_account_origin: str = ""
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
    # Explicit patient correspondence only; never grants appointment execution.
    workspace_scheduling_patient_setup_enabled: bool = False
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
    workspace_microsoft_message_enabled: bool = False
    workspace_microsoft_calendar_enabled: bool = False
    # Explicitly reviewed calendar snapshots; independent from whole-message consent.
    workspace_google_calendar_enabled: bool = False
    # Staff-supplied files only; no subscription or provider activation.
    workspace_calendar_import_enabled: bool = False
    # Explicit installed synthetic Elation fixture only; no vendor activation.
    workspace_ehr_read_enabled: bool = False
    # Separate network permission: sandbox REST reads of invented records only.
    workspace_elation_sandbox_enabled: bool = False
    # Real-practice EHR origins. Default off; hosted/production configs must not
    # set it. Requires a recorded practice-BAA flag on the connection as well.
    cosmas_ehr_real_data_enabled: bool = False
    # Track 3 mock scaffolds only. Default off; hosted/production must stay off.
    # No prescribing vendor is selected; send stays refused by the scaffold.
    workspace_rx_sandbox_enabled: bool = False
    # Synthetic fax scaffold observe only. Does not flip live fax/eFax inbound
    # or outbound flags, and does not call vendor_connectors send paths.
    workspace_efax_sandbox_enabled: bool = False
    # Additional clinical read scope; appointments retain their three-scope grant.
    workspace_elation_problems_enabled: bool = False
    workspace_elation_medications_enabled: bool = False
    workspace_elation_labs_enabled: bool = False
    workspace_tebra_fhir_enabled: bool = False
    # athena Certified FHIR R4 Preview (practice 195900). Default off; hosted/prod refuse.
    workspace_athena_fhir_sandbox_enabled: bool = False
    workspace_athena_allergies_enabled: bool = False
    workspace_athena_medications_enabled: bool = False
    google_connection_client_id: str = ""
    google_connection_client_secret: SecretStr | None = None
    google_connection_callback_uri: str = ""
    google_connection_return_origin: str = ""
    google_connection_encryption_key: SecretStr | None = None
    google_connection_broker_enabled: bool = False
    google_connection_broker_origin: str = ""
    workspace_microsoft_connection_enabled: bool = False
    # Exact tenant UUID, or explicit "organizations" for work/school accounts.
    microsoft_connection_tenant_id: str = ""
    microsoft_connection_client_id: str = ""
    microsoft_connection_client_secret: SecretStr | None = None
    microsoft_connection_callback_uri: str = ""
    microsoft_connection_return_origin: str = ""
    microsoft_connection_encryption_key: SecretStr | None = None
    # F-8 proposal/review surface; hosted activation does not enable execution.
    workspace_appointments_enabled: bool = False
    # Independent delivery/custody gates. Configuration and approval never enable I/O.
    vendor_work_enabled: bool = False
    vendor_io_enabled: bool = False
    vendor_events_enabled: bool = False
    vendor_setup_enabled: bool = False
    # Independent inbound metadata/image permission; outbound flags grant none.
    fax_inbound_enabled: bool = False
    fax_inbound_source_enabled: bool = False
    fax_inbound_document_encryption_key: SecretStr | None = None
    fax_inbound_document_key_id: str = "fax-document-v1"
    efax_inbound_enabled: bool = False
    # Explicit human-reviewed fax passages remain separate from clinical notes.
    efax_inbound_source_enabled: bool = False
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
    # Independent-beta CosmaBot ciphertext upload proxy (default OFF). Maps to
    # VITE_WORKSPACE_CAPTURE_ENABLED / hosting core_capture. Never inferred from
    # workspace_capture_backend alone — Core backend with a proxy origin and this
    # flag off keeps main authorize_upload URLs byte-for-byte.
    workspace_capture_proxy_enabled: bool = False
    # CosmaBot public API origin for ciphertext proxy URLs (independent-beta only).
    # Must equal the client VITE_CAPTURE_UPLOAD_ORIGINS / hosted API origin — never
    # a Core or Scribe blob host (browser→blob would need Cosmas CORS).
    workspace_capture_proxy_origin: str = ""
    # Exact Core-issued Azure blob hostname for CosmaBot API→blob PUT
    # (`<account>.blob.core.windows.net`, lowercase). Empty when capture opt-in is off.
    core_capture_upload_host: str = ""
    # Separate activation and caller configuration for Core's prepared artifact.
    workspace_session_prep_enabled: bool = False
    core_session_prep_scope: str = ""
    core_session_prep_managed_identity_client_id: str = ""
    workspace_llm_backend: Literal["disabled", "azure_gpt41"] = "disabled"
    workspace_llm_endpoint: str = COSMASCODE_LLM_ENDPOINT
    workspace_llm_deployment: str = DEFAULT_DEPLOYMENT
    workspace_llm_api_key: SecretStr | None = None
    # T-USDZ: when true, CosmaBot chat uses Data Zone Standard US deployment
    # gpt-4.1-dzus. Default off — existing live users keep gpt-4.1.
    workspace_llm_usdz_enabled: bool = False
    # New admissions opt into the closed product reader loop; saved v1–v4
    # requests retain their original single-response contract.
    workspace_agent_tools_enabled: bool = False

    @model_validator(mode="after")
    def _sync_usdz_chat_deployment(self):
        # Flag swaps only the unset default. An explicit WORKSPACE_LLM_DEPLOYMENT
        # (including gpt-4.1) must not be rewritten.
        if (
            self.workspace_llm_usdz_enabled
            and "workspace_llm_deployment" not in self.model_fields_set
        ):
            object.__setattr__(self, "workspace_llm_deployment", USDZ_DEPLOYMENT)
        return self

    @property
    def workspace_llm_reviewed_deployments(self) -> frozenset[str]:
        # Flag off: main's reviewed set is only gpt-4.1. Flag on also reviews dzus.
        allowed = {DEFAULT_DEPLOYMENT}
        if self.workspace_llm_usdz_enabled:
            allowed.add(USDZ_DEPLOYMENT)
        return frozenset(allowed)

    @property
    def workspace_llm_chat_deployment(self) -> str:
        # Effective deployment after default-only USDZ sync; explicit values win.
        return self.workspace_llm_deployment

    @property
    def workspace_calendar_import_available(self) -> bool:
        return bool(self.workspace_calendar_import_enabled and self.workspace_available
                    and self.workspace_authenticated_enabled and self.auth_mode == "clerk_jwt"
                    and not self.workspace_hosted_enabled)

    @property
    def workspace_ehr_read_available(self) -> bool:
        return bool(self.workspace_ehr_read_enabled and self.workspace_available
                    and self.workspace_authenticated_enabled and self.auth_mode == "clerk_jwt"
                    and not self.workspace_hosted_enabled)

    @property
    def workspace_elation_sandbox_available(self) -> bool:
        return bool(self.workspace_ehr_read_available and self.workspace_elation_sandbox_enabled)

    @property
    def workspace_athena_fhir_sandbox_available(self) -> bool:
        """athena Preview FHIR reads only; never hosted and never a live production origin."""
        return bool(self.workspace_ehr_read_available and self.workspace_athena_fhir_sandbox_enabled)

    @property
    def workspace_rx_sandbox_available(self) -> bool:
        """Synthetic prescription scaffold only; never hosted and never a send path."""
        return bool(
            self.workspace_rx_sandbox_enabled
            and self.workspace_available
            and self.workspace_authenticated_enabled
            and self.auth_mode == "clerk_jwt"
            and not self.workspace_hosted_enabled
        )

    @property
    def workspace_efax_sandbox_available(self) -> bool:
        """Synthetic fax scaffold observe only; never hosted and never live send."""
        return bool(
            self.workspace_efax_sandbox_enabled
            and self.workspace_available
            and self.workspace_authenticated_enabled
            and self.auth_mode == "clerk_jwt"
            and not self.workspace_hosted_enabled
        )

    @property
    def fax_inbound_source_available(self) -> bool:
        return bool(self.workspace_available and self.workspace_authenticated_enabled
                    and self.auth_mode == "clerk_jwt" and self.fax_inbound_enabled
                    and self.fax_inbound_source_enabled)

    @property
    def efax_inbound_source_available(self) -> bool:
        return bool(self.workspace_available and self.workspace_authenticated_enabled
                    and self.auth_mode == "clerk_jwt" and self.efax_inbound_enabled
                    and self.efax_inbound_source_enabled)

    @property
    def workspace_google_message_available(self) -> bool:
        return bool(self.workspace_google_message_enabled and self.workspace_google_connection_enabled
                    and self.workspace_available and self.workspace_authenticated_enabled
                    and self.auth_mode == "clerk_jwt")

    @property
    def workspace_microsoft_message_available(self) -> bool:
        return bool(self.workspace_microsoft_message_enabled and self.workspace_microsoft_connection_enabled
                    and self.workspace_available and self.workspace_authenticated_enabled
                    and self.auth_mode == "clerk_jwt"
                    and (self.cosmas_env != "standalone_clerk_synthetic" or not self._standalone_microsoft_errors()))

    @property
    def workspace_microsoft_calendar_available(self) -> bool:
        return bool(self.workspace_microsoft_calendar_enabled and self.workspace_microsoft_connection_enabled
                    and self.workspace_available and self.workspace_authenticated_enabled
                    and self.auth_mode == "clerk_jwt"
                    and (self.cosmas_env != "standalone_clerk_synthetic" or not self._standalone_microsoft_errors()))

    @property
    def workspace_google_calendar_available(self) -> bool:
        return bool(self.workspace_google_calendar_enabled and self.workspace_google_connection_enabled
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
    def workspace_appointment_execution_available(self) -> bool:
        """Existing synthetic execution only; hosted proposals cannot dispatch."""
        return bool(self.workspace_scheduling_available and self.workspace_appointments_enabled
                    and not self.workspace_hosted_enabled)

    @property
    def workspace_scheduling_patient_setup_available(self) -> bool:
        return bool(self.workspace_scheduling_patient_setup_enabled
                    and self.workspace_scheduling_available
                    and self.workspace_scheduling_login_enabled
                    and self.workspace_appointments_enabled)

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
        if self.cosmas_env == "standalone_clerk_synthetic":
            return bool(self.workspace_llm_backend == "azure_gpt41" and self.workspace_available
                        and not self._standalone_model_errors())
        if not (
            self.workspace_available
            and self.workspace_llm_backend == "azure_gpt41"
            and self.workspace_llm_deployment in self.workspace_llm_reviewed_deployments
            and self.workspace_llm_api_key
            and self.workspace_llm_api_key.get_secret_value()
        ):
            return False
        # Production-review (#356 VM / beta.cosmas.ai) requires the production
        # pattern; every other hosted profile stays CosmasCode-only.
        kind = _hosted_review_profile_kind(self)
        if _incomplete_production_review(self, kind):
            return False
        if kind == "review":
            return _production_openai_endpoint(self.workspace_llm_endpoint)
        return self.workspace_llm_endpoint == COSMASCODE_LLM_ENDPOINT

    @property
    def workspace_available(self) -> bool:
        if self.cosmas_env in STANDALONE_ENVS:
            return not self._standalone_configuration_errors()
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
        if self.cosmas_env not in {"early_adopter_beta", "standalone_clerk_synthetic"}:
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
        if self.real_patient_recording_enabled:
            errors.append(
                "REAL_PATIENT_RECORDING_ENABLED must remain false in process "
                "configuration; enable only via Box after clinic, BAA and PHI refs"
            )
        if self.cosmas_env in STANDALONE_ENVS:
            return errors + self._standalone_configuration_errors()
        errors.extend(self.workspace_enrollment_configuration_errors())
        if (self.standalone_instance_id or self.standalone_root or self.standalone_jwks_path
                or self.standalone_clerk_issuer_allowlist or self.standalone_model_origin_allowlist):
            errors.append("Standalone settings require the explicit standalone synthetic profile")
        if self.clerk_session_policy == "shared_staging":
            errors.extend(self.clerk_session_configuration_errors())
        if self.workspace_scheduling_enrollment_enabled:
            try:
                practice = str(UUID(self.scheduling_enrollment_practice_id))
            except ValueError:
                practice = ""
            if not self.workspace_scheduling_available or not self.workspace_scheduling_login_enabled or not practice or practice != self.scheduling_enrollment_practice_id:
                errors.append("Scheduling enrollment requires configured sign-in and one reviewed practice")

        if self.workspace_scheduling_patient_setup_enabled and not self.workspace_scheduling_patient_setup_available:
            errors.append("Scheduling patient setup requires authenticated scheduling sign-in and appointment proposals")

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
        if self.cosmas_ehr_real_data_enabled and self.workspace_hosted_enabled:
            errors.append(
                "COSMAS_EHR_REAL_DATA_ENABLED must remain false when WORKSPACE_HOSTED_ENABLED is true"
            )
        if self.workspace_rx_sandbox_enabled and self.workspace_hosted_enabled:
            errors.append(
                "WORKSPACE_RX_SANDBOX_ENABLED must remain false when WORKSPACE_HOSTED_ENABLED is true"
            )
        if self.workspace_efax_sandbox_enabled and self.workspace_hosted_enabled:
            errors.append(
                "WORKSPACE_EFAX_SANDBOX_ENABLED must remain false when WORKSPACE_HOSTED_ENABLED is true"
            )
        if self.workspace_athena_fhir_sandbox_enabled and self.workspace_hosted_enabled:
            errors.append(
                "WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED must remain false when WORKSPACE_HOSTED_ENABLED is true"
            )
        if (self.workspace_apple_hosted_transport_enabled or self.workspace_desktop_hosted_transport_enabled) and not self.workspace_hosted_enabled:
            errors.append("Hosted native transport requires WORKSPACE_HOSTED_ENABLED")
        if self.workspace_capture_backend != "disabled" and not self.workspace_capture_available:
            errors.append("Workspace capture requires an authenticated workspace and complete Core workload configuration")
        if self.workspace_llm_backend == "azure_gpt41":
            kind = _hosted_review_profile_kind(self)
            prod_ep = _production_openai_endpoint(self.workspace_llm_endpoint)
            if _incomplete_production_review(self, kind):
                # beta.cosmas.ai present but not exclusive review — refuse both
                # CosmasCode and the production endpoint (no silent CosmasCode).
                errors.append(
                    "Incomplete production-review profile refuses Workspace GPT-4.1"
                )
            elif kind == "review" and not prod_ep:
                # Unset defaults to CosmasCode; production-review never accepts it.
                errors.append(
                    "Production-review requires the production Azure OpenAI endpoint"
                )
            elif kind != "review" and prod_ep:
                errors.append(
                    "Non-production profiles refuse the production Azure OpenAI endpoint"
                )
            elif not self.workspace_llm_available:
                errors.append(
                    "Workspace GPT-4.1 requires an available workspace and the exact configured deployment"
                )
        elif self.workspace_llm_backend != "disabled" and not self.workspace_llm_available:
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

    def _standalone_configuration_errors(self) -> list[str]:
        """Closed owned profiles; external identity never enables a provider or worker."""
        errors: list[str] = []
        real_clerk = self.cosmas_env == "standalone_clerk_synthetic"
        try:
            instance = UUID(self.standalone_instance_id)
            if instance.version != 4 or str(instance) != self.standalone_instance_id:
                raise ValueError
        except ValueError:
            errors.append("Standalone instance must be a canonical UUIDv4")
            instance = None
        root = Path(self.standalone_root)
        if (not self.standalone_root or not root.is_absolute()
                or str(root) != self.standalone_root or ".." in root.parts
                or self.blob_root != str(root / "blobs")
                or self.standalone_jwks_path != ("" if real_clerk else str(root / "keys" / "jwks.json"))):
            errors.append("Standalone storage and public keys require one explicit owned root")
        if (self.data_mode != "synthetic" or self.auth_mode != "clerk_jwt"
                or not self.workspace_enabled or not self.workspace_authenticated_enabled
                or not self.workspace_draft_recovery_required or self.synth_seed
                or self.sync_worker or self.execution_backend != "celery"
                or self.blob_backend != "local" or self.redis_url):
            errors.append("Standalone requires authenticated synthetic mode with local storage and no queue transport")
        try:
            database = urlparse(self.database_url)
            valid_database = (database.scheme == "postgresql+psycopg"
                and database.hostname == "127.0.0.1" and database.port is not None
                and database.username and database.password
                and re.fullmatch(r"/cosmabot_standalone_[a-z0-9_]+", database.path)
                and not database.query and not database.fragment and not database.params)
        except ValueError:
            valid_database = False
        if not valid_database:
            errors.append("Standalone requires an authenticated dedicated loopback PostgreSQL database")
        if real_clerk:
            issuer = urlparse(self.clerk_issuer or "")
            hostname = issuer.hostname or ""
            # A real issuer is one explicit reviewed selection, never a discovery
            # URL or the offline key namespace. Signature verification is unchanged.
            if (not self.clerk_issuer or self._csv(self.standalone_clerk_issuer_allowlist) != (self.clerk_issuer,)
                    or not self._is_exact_https_origin(self.clerk_issuer)
                    or self.clerk_issuer != "https://" + hostname
                    or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,63}", hostname)
                    or hostname == "cosmaneura.com"
                    or hostname.endswith((".invalid", ".localhost", ".cosmaneura.com"))):
                errors.append("Standalone Clerk requires one explicitly allowlisted HTTPS issuer")
            if ("clerk_session_policy" not in self.model_fields_set
                    or self.clerk_session_policy not in {"audience", "shared_staging"}):
                errors.append("Standalone Clerk requires an explicit existing session policy")
            # Audience selects the reviewed application, not a storage instance.
            # Exact issuer/org/owner checks and the owned database marker remain
            # independent boundaries; the same selected application contract can
            # intentionally admit its bearer session at more than one instance.
            if self.clerk_session_policy == "audience" and (
                    "clerk_audience" not in self.model_fields_set
                    or not re.fullmatch(r"[\x21-\x7e]{1,255}", self.clerk_audience or "")
                    or hostname.endswith(".clerk.accounts.dev")):
                errors.append("Standalone audience sessions require an explicit application audience and production issuer")
            if (not re.fullmatch(r"org_[A-Za-z0-9_]{1,251}", self.clerk_organization_id or "")
                    or not self.human_deploy_evidence_ref or len(self.human_deploy_evidence_ref) > 255
                    or self.human_deploy_evidence_ref != self.human_deploy_evidence_ref.strip()
                    or any(ord(c) < 32 for c in self.human_deploy_evidence_ref)):
                errors.append("Standalone Clerk requires an explicit organization and reviewed deployment reference")
            if (not self.workspace_hosted_enabled or self.workspace_apple_local_transport_enabled
                    or self.workspace_desktop_local_transport_enabled):
                errors.append("Standalone Clerk requires explicit hosted transports")
            if any((urlparse(origin).hostname or "") == "cosmaneura.com"
                   or (urlparse(origin).hostname or "").endswith(".cosmaneura.com")
                   for origin in self.allowed_origins):
                errors.append("Standalone Clerk cannot admit separate platform web origins")
        elif instance is not None:
            # Offline proof retains its original identity contract and key file.
            issuer = f"https://{instance}.cosmabot.invalid"
            if (self.clerk_issuer != issuer or self.clerk_jwks_url != issuer + "/.well-known/jwks.json"
                    or self.clerk_audience != f"cosmabot-standalone:{instance}"
                    or self.clerk_organization_id != "org_cosmabot_" + instance.hex
                    or self.clerk_session_policy != "audience"):
                errors.append("Standalone identity must use its instance-specific offline namespace")
            if self.standalone_clerk_issuer_allowlist:
                errors.append("Offline standalone identity cannot select a remote issuer")
        errors.extend(self.workspace_authentication_errors())
        if (not self.allowed_origins
                or not all(self._is_workspace_origin(origin) for origin in self.allowed_origins)):
            errors.append("Standalone origins must match its explicit workspace transports")
        # Not an *_enabled flag; refuse managed admission on standalone explicitly.
        if self.workspace_enrollment_managed:
            errors.append(
                "WORKSPACE_ENROLLMENT_MANAGED must remain false in standalone configuration"
            )
        enabled_allowlist = {"workspace_enabled", "workspace_authenticated_enabled",
            "workspace_draft_recovery_required"}
        if real_clerk:
            enabled_allowlist.update({"workspace_google_connection_enabled", "workspace_google_message_enabled",
                                      "workspace_google_calendar_enabled", "workspace_microsoft_connection_enabled",
                                      "workspace_microsoft_message_enabled", "workspace_microsoft_calendar_enabled",
                                      # Independent-beta launch: Chief tools + Core note capture only.
                                      "workspace_agent_tools_enabled", "workspace_capture_notes_enabled",
                                      "workspace_capture_proxy_enabled"})
        enabled_allowlist.update({"workspace_hosted_enabled", "workspace_apple_hosted_transport_enabled",
            "workspace_desktop_hosted_transport_enabled"} if real_clerk else {
            "workspace_apple_local_transport_enabled", "workspace_desktop_local_transport_enabled"})
        for name in type(self).model_fields:
            if name.endswith("_enabled") and name not in enabled_allowlist and getattr(self, name):
                errors.append("Standalone external features and background workers must remain disabled")
                break
        empty_prefixes = ("core_", "azure_",
            "scheduling_", "managed_services_config_")
        # Independent-beta Core capture: reviewed origin + MI identity only.
        # Never Athena, prep, or other Core callers from this allowlist.
        core_capture_fields = {
            "core_capture_origin", "core_capture_scope",
            "core_capture_managed_identity_client_id", "core_web_origin",
            "workspace_capture_proxy_enabled", "workspace_capture_proxy_origin",
            "core_capture_upload_host",
        }
        for name in type(self).model_fields:
            value = getattr(self, name)
            if name in core_capture_fields:
                if value and self.workspace_capture_backend != "core":
                    errors.append("Standalone Core capture fields require WORKSPACE_CAPTURE_BACKEND=core")
                    break
                continue
            reviewed_optional = real_clerk and name in {"workspace_llm_api_key", "google_connection_encryption_key",
                                                        "microsoft_connection_encryption_key"}
            if ((name.startswith(empty_prefixes) or (not real_clerk and name.startswith("microsoft_connection_"))
                 or name.endswith("_api_key")
                 or name.endswith("_encryption_key")) and value and not reviewed_optional):
                errors.append("Standalone cannot contain external service addresses or credentials")
                break
        if self.workspace_capture_backend == "core":
            errors.extend(self._standalone_core_capture_errors())
        elif (self.workspace_capture_backend != "disabled" or self.compact_web_root
                or self.workspace_native_synthetic_enabled):
            errors.append("Standalone capture and alternate execution paths must be disabled")
        if real_clerk:
            errors.extend(self._standalone_model_errors())
            errors.extend(self._standalone_google_errors())
            errors.extend(self._standalone_microsoft_errors())
        elif (self.workspace_llm_backend != "disabled" or self.workspace_llm_endpoint
              or self.standalone_model_origin_allowlist or any(getattr(self, name)
                    for name in type(self).model_fields if name.startswith("google_connection_"))):
            errors.append("Offline standalone models and Google credentials must remain disabled")
        return errors

    def _standalone_core_capture_errors(self) -> list[str]:
        """Independent-beta Core capture: reviewed origin + exact scope/MI only.

        Do not call workspace_capture_available here: that property reads
        workspace_available, which re-enters standalone configuration errors.
        """
        # Observed Core web/API origin: docs/beta/WEB_RELEASE.md:171-176.
        reviewed = "https://staging-app.cosmaneura.com"
        try:
            UUID(self.core_capture_managed_identity_client_id)
            origin = urlparse(self.core_capture_origin)
            valid_identity = origin.port in (None, 443) and not any(c.isspace() for c in self.core_capture_origin)
        except ValueError:
            valid_identity = False
        if (not valid_identity or not self._is_exact_https_origin(self.core_capture_origin)
                or not self.core_capture_scope.startswith("api://")
                or not self.core_capture_scope.endswith("/.default")
                or any(c.isspace() for c in self.core_capture_scope)):
            return ["Standalone Core capture requires exact CORE_CAPTURE_ORIGIN, SCOPE and managed identity"]
        if self.core_capture_origin != reviewed or self.core_web_origin != reviewed:
            return ["Standalone Core capture requires the reviewed staging-app.cosmaneura.com origin"]
        if not self.workspace_capture_notes_enabled or not self.workspace_agent_tools_enabled:
            return ["Standalone Core capture requires capture notes and agent tools together"]
        # Explicit proxy opt-in + CosmaBot API origin — never Core web or Scribe blob.
        if not self.workspace_capture_proxy_enabled:
            return ["Standalone Core capture requires the CosmaBot upload proxy opt-in"]
        proxy = self.workspace_capture_proxy_origin
        proxy_host = (urlparse(proxy).hostname or "").lower()
        if (not self._is_exact_https_origin(proxy)
                or proxy.rstrip("/") == reviewed
                or proxy_host.endswith(".blob.core.windows.net")
                or proxy_host.endswith(".cosmaneura.com")):
            return ["Standalone Core capture requires CosmaBot API proxy origin for uploads"]
        if not re.fullmatch(r"[a-z0-9]{3,24}\.blob\.core\.windows\.net", self.core_capture_upload_host or ""):
            return ["Standalone Core capture requires exact CORE_CAPTURE_UPLOAD_HOST"]
        return []

    def _standalone_model_errors(self) -> list[str]:
        if self.workspace_llm_backend == "disabled":
            return (["Disabled standalone model must have no endpoint, origin selection or key"]
                    if self.workspace_llm_endpoint or self.standalone_model_origin_allowlist or self.workspace_llm_api_key else [])
        endpoint = self.workspace_llm_endpoint
        parsed = urlparse(endpoint)
        origin = "https://" + (parsed.hostname or "")
        if (self.workspace_llm_backend != "azure_gpt41"
                or self.workspace_llm_deployment not in self.workspace_llm_reviewed_deployments
                or not re.fullmatch(r"https://[a-z0-9][a-z0-9-]{1,62}\.(?:openai\.azure\.com|services\.ai\.azure\.com)/openai/v1", endpoint)
                or self._csv(self.standalone_model_origin_allowlist) != (origin,)
                or not self.workspace_llm_api_key or not self.workspace_llm_api_key.get_secret_value()):
            return ["Standalone Chief requires one reviewed Azure OpenAI origin, GPT-4.1 and its own key"]
        return []

    def _standalone_google_errors(self) -> list[str]:
        names = [name for name in type(self).model_fields if name.startswith("google_connection_")]
        if not self.workspace_google_connection_enabled:
            return (["Disabled standalone Google connection must have no credentials or read flags"]
                    if self.workspace_google_message_enabled or self.workspace_google_calendar_enabled
                    or any(getattr(self, name) for name in names) else [])
        callback = urlparse(self.google_connection_callback_uri)
        origin = callback.scheme + "://" + callback.netloc
        hostname = callback.hostname or ""
        valid_key = False
        if self.google_connection_encryption_key:
            try:
                key = base64.b64decode(self.google_connection_encryption_key.get_secret_value(), altchars=b"-_", validate=True)
                valid_key = len(key) == 32
            except (ValueError, UnicodeError):
                pass
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com", self.google_connection_client_id)
                or not self._is_exact_https_origin(origin) or origin != "https://" + hostname
                or hostname == "cosmaneura.com" or hostname.endswith(".cosmaneura.com")
                or callback.path != "/connections/google/callback" or callback.query or callback.fragment or callback.params
                or not self._is_exact_https_origin(self.google_connection_return_origin)
                or self.google_connection_return_origin not in self.allowed_origins
                or not self.google_connection_client_secret or not self.google_connection_client_secret.get_secret_value()
                or not valid_key):
            return ["Standalone Google requires its reviewed client, exact owned callback/return origins and custody key"]
        return []

    def _standalone_microsoft_errors(self) -> list[str]:
        names = [name for name in type(self).model_fields if name.startswith("microsoft_connection_")]
        if not self.workspace_microsoft_connection_enabled:
            return (["Disabled standalone Microsoft connection must have no credentials or read flags"]
                    if self.workspace_microsoft_message_enabled or self.workspace_microsoft_calendar_enabled
                    or any(getattr(self, name) for name in names) else [])
        callback = urlparse(self.microsoft_connection_callback_uri)
        origin = callback.scheme + "://" + callback.netloc
        hostname = callback.hostname or ""
        valid_key = False
        if self.microsoft_connection_encryption_key:
            try:
                key = base64.b64decode(self.microsoft_connection_encryption_key.get_secret_value(), altchars=b"-_", validate=True)
                valid_key = len(key) == 32
            except (ValueError, UnicodeError):
                pass
        identifier = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
        if ((self.microsoft_connection_tenant_id != "organizations"
                and not re.fullmatch(identifier, self.microsoft_connection_tenant_id))
                or not re.fullmatch(identifier, self.microsoft_connection_client_id)
                or not self._is_exact_https_origin(origin) or origin != "https://" + hostname
                or hostname == "cosmaneura.com" or hostname.endswith(".cosmaneura.com")
                or callback.path != "/connections/microsoft/callback" or callback.query or callback.fragment or callback.params
                or not self._is_exact_https_origin(self.microsoft_connection_return_origin)
                or self.microsoft_connection_return_origin not in self.allowed_origins
                or not self.microsoft_connection_client_secret or not self.microsoft_connection_client_secret.get_secret_value()
                or not valid_key):
            return ["Standalone Microsoft requires its reviewed tenant/client, exact owned callback/return origins and custody key"]
        return []

    def clerk_session_configuration_errors(self) -> list[str]:
        if self.clerk_session_policy == "audience":
            return [] if self.clerk_audience else ["CLERK_AUDIENCE is required"]
        if self.clerk_session_policy == "enrollment_default":
            if (not self.workspace_enrollment_managed or type(self.clerk_audience) is not str
                    or self.clerk_audience and not re.fullmatch(r"[\x21-\x7e]{1,255}", self.clerk_audience)
                    or self.auth_mode != "clerk_jwt" or self.cosmas_env != "early_adopter_beta"
                    or not self._is_exact_https_origin(self.clerk_issuer or "")
                    or self.workspace_enrollment_configuration_errors()):
                return ["Enrollment default sessions require managed admission, exact issuer and explicit blank or bounded scalar audience"]
            return []
        if (self.clerk_session_policy != "shared_staging" or self.clerk_audience != ""
                or self.cosmas_env not in {"early_adopter_beta", "standalone_clerk_synthetic"}
                or self.data_mode != "synthetic"
                or self.auth_mode != "clerk_jwt"
                or not self._is_exact_https_origin(self.clerk_issuer or "")
                or not (urlparse(self.clerk_issuer or "").hostname or "").endswith(".clerk.accounts.dev")):
            return ["Shared Clerk sessions require synthetic beta, a development issuer and explicitly empty audience"]
        return []

    def workspace_enrollment_configuration_errors(self) -> list[str]:
        if not self.workspace_enrollment_managed:
            if self.clerk_session_policy == "enrollment_default":
                return ["Enrollment default sessions require managed runtime admission"]
            return []
        try:
            valid_practice = str(UUID(self.workspace_enrollment_practice_id)) == self.workspace_enrollment_practice_id
            valid_box = str(UUID(self.beta_box_id or "")) == self.beta_box_id
        except ValueError:
            valid_practice = valid_box = False
        origin = self.workspace_enrollment_api_origin
        allowlist = self._csv(self.workspace_enrollment_origin_allowlist)
        key = self.workspace_enrollment_admission_secret
        account = self.workspace_enrollment_account_origin
        if (self.cosmas_env != "early_adopter_beta" or self.auth_mode != "clerk_jwt"
                or not valid_practice or not valid_box or not self.clerk_organization_id
                or not self._is_exact_https_origin(origin) or origin not in allowlist
                or any(not self._is_exact_https_origin(value) for value in allowlist)
                or key is None or not re.fullmatch(r"[a-f0-9]{64}", key.get_secret_value())
                or account and (not self._is_exact_https_origin(account)
                                or account not in allowlist)):
            return ["Managed enrollment requires an immutable practice/Box/Org, exact allowed HTTPS control/account origins and a derived admission key"]
        return []

    @property
    def enrollment_account_origin(self) -> str | None:
        if self.workspace_enrollment_managed and not self.workspace_enrollment_configuration_errors() and self.workspace_enrollment_account_origin:
            return self.workspace_enrollment_account_origin
        return None

    @property
    def enrollment_recovery_url(self) -> str | None:
        origin = self.enrollment_account_origin
        return origin + "/onboarding" if origin else None

    def _beta_configuration_errors(self) -> list[str]:
        """Independent cloud prerequisites; never call workspace_available here."""
        errors = self.clerk_session_configuration_errors()
        errors.extend(self.workspace_enrollment_configuration_errors())

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
        elif not set(self.authorized_parties).issubset(set(self.allowed_origins) |
                ({self.workspace_enrollment_account_origin} if self.workspace_enrollment_managed else set())):
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
