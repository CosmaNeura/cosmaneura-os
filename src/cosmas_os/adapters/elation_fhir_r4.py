"""Elation FHIR R4 sandbox adapter on the shared EHR connector core (C11 / C20 / T4).

Hybrid split (documented for the PR and ``docs/beta/``):

* **FHIR R4** for clinical chart resources Elation's ONC (g)(10) API exposes
  under exact ``system/<Resource>.read`` scopes (Patient, Encounter, Condition,
  MedicationRequest, AllergyIntolerance, Observation, DocumentReference, …).
* **REST APIv2** (existing ``adapters.elation_read`` / sandbox runtime / plugin
  tools) for appointments and practice verification. Elation's published
  ``system/*.read`` expansion does **not** include Appointment, so schedule
  reads stay on the existing client-credentials REST path rather than being
  duplicated here.

Sandbox / synthetic only. Reuses the shared C4 FHIR R4 read client and the C2
client-credentials token provider. Vendor FHIR host is opt-in via
``extra_sandbox_hosts`` only — the shared C4 default host set is never widened.
Mock transport required in CI; no live Elation calls, no new secrets, no route
wiring beyond the existing Elation REST path.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import SecretStr

from cosmas_os.adapters.ehr_auth import (
    ELATION_FHIR_CLIENT_ID_REF,
    ELATION_FHIR_CLIENT_SECRET_REF,
    ClientCredentialsAuthError,
    ClientCredentialsConfig,
    ClientCredentialsTokenClient,
    normalize_system_read_scopes,
)
from cosmas_os.ehr_real_data_gate import (
    ELATION_FHIR_SANDBOX_ORIGIN,
    EhrRealDataGateError,
    assert_ehr_request_allowed,
)
from cosmas_os.plugins.ehr_fhir import FhirR4ReadClient, FhirReadResult

logger = logging.getLogger(__name__)

# Official Elation FHIR sandbox service base (docs: Service Base URLs).
ELATION_FHIR_R4_BASE_URL = "https://sandbox.fhir.elationemr.com/fhir"
ELATION_FHIR_TOKEN_URL = "https://sandbox.fhir.elationemr.com/smart/token"
ELATION_FHIR_SANDBOX_HOST = "sandbox.fhir.elationemr.com"
# Opt-in only for the Elation adapter — never added to the shared C4 default host set.
ELATION_FHIR_EXTRA_SANDBOX_HOSTS: frozenset[str] = frozenset({ELATION_FHIR_SANDBOX_HOST})

# Exact SMART system/<Resource>.read scopes. No wildcards, no write.
# Appointment is intentionally absent — schedule stays on REST APIv2.
ELATION_FHIR_SYSTEM_READ_SCOPES: frozenset[str] = normalize_system_read_scopes(
    {
        "system/Patient.read",
        "system/Encounter.read",
        "system/AllergyIntolerance.read",
        "system/MedicationRequest.read",
        "system/Medication.read",
        "system/Condition.read",
        "system/Observation.read",
        "system/DiagnosticReport.read",
        "system/DocumentReference.read",
        "system/Binary.read",
        "system/Practitioner.read",
        "system/Organization.read",
    }
)

ELATION_FHIR_RESOURCES: frozenset[str] = frozenset(
    {
        "Patient",
        "Encounter",
        "AllergyIntolerance",
        "MedicationRequest",
        "Medication",
        "Condition",
        "Observation",
        "DiagnosticReport",
        "DocumentReference",
        "Binary",
        "Practitioner",
        "Organization",
    }
)

# FHIR Appointment is refused here; CosmaBot schedule reads use elation_read REST.
FORBIDDEN_FHIR_RESOURCES: frozenset[str] = frozenset({"Appointment"})

# REST APIv2 paths that remain the schedule / practice source of truth.
ELATION_REST_APPOINTMENT_SURFACE = "adapters.elation_read.ElationReadAdapter"

ErrorCode = Literal[
    "synthetic_transport_required",
    "resource_unsupported",
    "action_refused",
    "off_origin_refused",
    "sandbox_flag_required",
    "real_data_required",
    "unknown_ehr_origin",
    "invalid_ehr_origin",
    "invalid_ehr_gate_flags",
    "auth_unavailable",
    "not_configured",
    "unsupported_scope",
    "scope_wildcard_refused",
    "invalid_request",
    "use_rest_appointments",
]


class ElationFhirR4Error(Exception):
    """Closed adapter failures; messages never carry tokens or secrets."""

    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"ElationFhirR4Error(code={self.code!r})"


def elation_fhir_sandbox_client_credentials_config() -> ClientCredentialsConfig:
    """Named vault refs + sandbox token URL + approved read scopes."""
    return ClientCredentialsConfig(
        client_id_ref=ELATION_FHIR_CLIENT_ID_REF,
        client_secret_ref=ELATION_FHIR_CLIENT_SECRET_REF,
        token_url=ELATION_FHIR_TOKEN_URL,
        scopes=ELATION_FHIR_SYSTEM_READ_SCOPES,
    )


def _map_auth_error(exc: ClientCredentialsAuthError) -> ErrorCode:
    if exc.code in {
        "not_configured",
        "unsupported_scope",
        "scope_wildcard_refused",
        "invalid_request",
    }:
        return exc.code  # type: ignore[return-value]
    return "auth_unavailable"


def _map_gate_error(exc: EhrRealDataGateError) -> ErrorCode:
    if exc.code in {
        "sandbox_flag_required",
        "real_data_required",
        "unknown_ehr_origin",
        "invalid_ehr_origin",
        "invalid_ehr_gate_flags",
    }:
        return exc.code  # type: ignore[return-value]
    return "off_origin_refused"


@dataclass(frozen=True, slots=True, repr=False)
class ElationFhirR4SearchRequest:
    """One sandbox FHIR search."""

    resource_type: str
    params: Mapping[str, str] | None = None


class ElationFhirR4Adapter:
    """Sandbox-only Elation FHIR R4 reader. Mock transport required; no live CI calls."""

    def __init__(
        self,
        *,
        token_client: ClientCredentialsTokenClient,
        transport: httpx.MockTransport,
        sandbox_enabled: bool = False,
        real_data_enabled: bool = False,
        practice_baa_recorded: bool = False,
        base_url: str = ELATION_FHIR_R4_BASE_URL,
        max_pages: int = 3,
    ) -> None:
        if type(transport) is not httpx.MockTransport:
            raise ElationFhirR4Error("synthetic_transport_required")
        if type(token_client) is not ClientCredentialsTokenClient:
            raise ElationFhirR4Error("not_configured")
        if type(sandbox_enabled) is not bool or type(real_data_enabled) is not bool:
            raise ElationFhirR4Error("invalid_ehr_gate_flags")
        if type(practice_baa_recorded) is not bool:
            raise ElationFhirR4Error("invalid_ehr_gate_flags")
        if type(max_pages) is not int or not 1 <= max_pages <= 5:
            raise ElationFhirR4Error("invalid_request")
        if type(base_url) is not str or not base_url.startswith(ELATION_FHIR_SANDBOX_ORIGIN):
            raise ElationFhirR4Error("off_origin_refused")
        if not token_client.requested_scopes <= ELATION_FHIR_SYSTEM_READ_SCOPES:
            raise ElationFhirR4Error("unsupported_scope")
        if not token_client.requested_scopes:
            raise ElationFhirR4Error("unsupported_scope")
        self._token_client = token_client
        self._transport = transport
        self._sandbox_enabled = sandbox_enabled
        self._real_data_enabled = real_data_enabled
        self._practice_baa_recorded = practice_baa_recorded
        self._base_url = base_url.rstrip("/")
        self._max_pages = max_pages
        self._granted_scopes: frozenset[str] | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def approved_scopes(self) -> frozenset[str]:
        return ELATION_FHIR_SYSTEM_READ_SCOPES

    @property
    def approved_resources(self) -> frozenset[str]:
        return ELATION_FHIR_RESOURCES

    @property
    def rest_appointment_surface(self) -> str:
        """Import path for the REST schedule reader (not duplicated here)."""
        return ELATION_REST_APPOINTMENT_SURFACE

    def refuse_write(self, action: str = "write") -> None:
        raise ElationFhirR4Error("action_refused")

    def assert_resource_allowed(
        self, resource_type: str, *, granted_scopes: frozenset[str] | None = None
    ) -> None:
        if type(resource_type) is not str:
            raise ElationFhirR4Error("resource_unsupported")
        if resource_type in FORBIDDEN_FHIR_RESOURCES:
            # Distinct code so callers know to use the existing REST appointments path.
            raise ElationFhirR4Error("use_rest_appointments")
        if resource_type not in ELATION_FHIR_RESOURCES:
            raise ElationFhirR4Error("resource_unsupported")
        scopes = granted_scopes if granted_scopes is not None else self._token_client.requested_scopes
        if f"system/{resource_type}.read" not in scopes:
            raise ElationFhirR4Error("unsupported_scope")

    def _guard_origin(self) -> None:
        try:
            assert_ehr_request_allowed(
                vendor="elation",
                origin=ELATION_FHIR_SANDBOX_ORIGIN,
                sandbox_enabled=self._sandbox_enabled,
                real_data_enabled=self._real_data_enabled,
                practice_baa_recorded=self._practice_baa_recorded,
                mock_transport_only=True,
            )
        except EhrRealDataGateError as exc:
            raise ElationFhirR4Error(_map_gate_error(exc)) from None

    def _access_token_and_scopes(self) -> tuple[str, frozenset[str]]:
        try:
            token = self._token_client.get_access_token()
        except ClientCredentialsAuthError as exc:
            raise ElationFhirR4Error(_map_auth_error(exc)) from None
        if type(token) is not SecretStr:
            raise ElationFhirR4Error("auth_unavailable")
        value = token.get_secret_value()
        if type(value) is not str or not value:
            raise ElationFhirR4Error("auth_unavailable")
        cache = getattr(self._token_client, "_cache", None)
        granted = self._token_client.requested_scopes
        if cache is not None:
            cached_scopes = getattr(cache, "granted_scopes", None)
            if isinstance(cached_scopes, frozenset) and cached_scopes:
                granted = cached_scopes
        if not granted <= ELATION_FHIR_SYSTEM_READ_SCOPES:
            raise ElationFhirR4Error("unsupported_scope")
        self._granted_scopes = granted
        return value, granted

    def _client(self, access_token: str) -> FhirR4ReadClient:
        return FhirR4ReadClient(
            self._base_url,
            transport=self._transport,
            access_token=access_token,
            display_label="Elation",
            allow_production=False,
            extra_sandbox_hosts=ELATION_FHIR_EXTRA_SANDBOX_HOSTS,
            # Explicit Elation set: includes DiagnosticReport/Binary, excludes Appointment.
            allowed_resources=ELATION_FHIR_RESOURCES,
            max_pages=self._max_pages,
        )

    def _clean_params(self, params: Mapping[str, str] | None) -> dict[str, str] | None:
        if params is None:
            return None
        if not isinstance(params, Mapping):
            raise ElationFhirR4Error("invalid_request")
        cleaned: dict[str, str] = {}
        for key, value in params.items():
            if type(key) is not str or type(value) is not str:
                raise ElationFhirR4Error("invalid_request")
            cleaned[key] = value
        return cleaned

    def search(
        self,
        resource_type: str,
        params: Mapping[str, str] | None = None,
        *,
        follow_paging: bool = True,
    ) -> FhirReadResult:
        self._guard_origin()
        token, granted = self._access_token_and_scopes()
        self.assert_resource_allowed(resource_type, granted_scopes=granted)
        client = self._client(token)
        result = client.search(
            resource_type, self._clean_params(params), follow_paging=follow_paging
        )
        logger.info(
            "elation_fhir_r4_search",
            extra={
                "vendor": "elation",
                "resource_type": resource_type,
                "pages_read": result.pages_read,
                "result_count": len(result.resources),
                "state": result.state,
                "more_available": result.more_available,
            },
        )
        return result

    def read(self, resource_type: str, resource_id: str) -> FhirReadResult:
        self._guard_origin()
        token, granted = self._access_token_and_scopes()
        self.assert_resource_allowed(resource_type, granted_scopes=granted)
        client = self._client(token)
        result = client.read(resource_type, resource_id)
        logger.info(
            "elation_fhir_r4_read",
            extra={
                "vendor": "elation",
                "resource_type": resource_type,
                "state": result.state,
                "result_count": len(result.resources),
            },
        )
        return result

    def create(self, *args: Any, **kwargs: Any) -> None:
        self.refuse_write("create")

    def update(self, *args: Any, **kwargs: Any) -> None:
        self.refuse_write("update")

    def delete(self, *args: Any, **kwargs: Any) -> None:
        self.refuse_write("delete")

    def __repr__(self) -> str:
        return (
            "ElationFhirR4Adapter("
            f"base_url={self._base_url!r}, "
            f"sandbox_enabled={self._sandbox_enabled!r})"
        )
