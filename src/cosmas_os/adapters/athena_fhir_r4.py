"""athena Certified FHIR R4 adapter for Preview practice 195900 (ticket C7).

Sandbox / synthetic only. Reuses the shared C4 FHIR R4 read client and the C2
client-credentials token provider. Every search is practice-scoped with
``ah-practice=Organization/a-1.Practice-195900``. FHIR Appointment is refused
(Encounter is the schedule source; C15 / Non-Certified appointments stay
parked). No route wiring (C8) and no live Preview calls in CI.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import SecretStr

from cosmas_os.adapters.ehr_auth import (
    ATHENA_FHIR_CLIENT_ID_REF,
    ATHENA_FHIR_CLIENT_SECRET_REF,
    ClientCredentialsAuthError,
    ClientCredentialsConfig,
    ClientCredentialsTokenClient,
    normalize_system_read_scopes,
)
from cosmas_os.ehr_real_data_gate import (
    ATHENA_PREVIEW_ORIGIN,
    EhrRealDataGateError,
    assert_ehr_request_allowed,
    normalize_ehr_origin,
)
from cosmas_os.plugins.ehr_fhir import FhirR4ReadClient, FhirReadResult

logger = logging.getLogger(__name__)

ATHENA_FHIR_R4_BASE_URL = "https://api.preview.platform.athenahealth.com/fhir/r4"
ATHENA_FHIR_TOKEN_URL = "https://api.preview.platform.athenahealth.com/oauth2/v1/token"
ATHENA_PREVIEW_PRACTICE_ID = "195900"
ATHENA_PRACTICE_PARAM = "ah-practice"
ATHENA_PRACTICE_VALUE = "Organization/a-1.Practice-195900"

# Exact SMART v1 system/<Resource>.read scopes for Cosmaneura CosmaBot FHIR.
# No wildcards, no write, no Appointment (athena does not offer it for system apps).
ATHENA_FHIR_SYSTEM_READ_SCOPES: frozenset[str] = normalize_system_read_scopes(
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

ATHENA_FHIR_RESOURCES: frozenset[str] = frozenset(
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

FORBIDDEN_FHIR_RESOURCES: frozenset[str] = frozenset({"Appointment"})

ErrorCode = Literal[
    "synthetic_transport_required",
    "resource_unsupported",
    "action_refused",
    "practice_override_refused",
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
]


class AthenaFhirR4Error(Exception):
    """Closed adapter failures; messages never carry tokens or secrets."""

    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"AthenaFhirR4Error(code={self.code!r})"


def athena_fhir_preview_client_credentials_config() -> ClientCredentialsConfig:
    """Named vault refs + Preview token URL + the 12 approved read scopes."""
    return ClientCredentialsConfig(
        client_id_ref=ATHENA_FHIR_CLIENT_ID_REF,
        client_secret_ref=ATHENA_FHIR_CLIENT_SECRET_REF,
        token_url=ATHENA_FHIR_TOKEN_URL,
        scopes=ATHENA_FHIR_SYSTEM_READ_SCOPES,
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
class AthenaFhirR4SearchRequest:
    """One practice-scoped FHIR search. ``ah-practice`` is always forced."""

    resource_type: str
    params: Mapping[str, str] | None = None


class _PracticeScopedTransport(httpx.BaseTransport):
    """Refuse search / paging requests that omit or override ah-practice."""

    def __init__(self, inner: httpx.MockTransport, *, base_url: str) -> None:
        self._inner = inner
        self._base_origin = normalize_ehr_origin(base_url)
        self._base_path = urlsplit(base_url).path.rstrip("/")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        origin = normalize_ehr_origin(str(request.url))
        if origin != self._base_origin:
            raise AthenaFhirR4Error("off_origin_refused")
        path = request.url.path.rstrip("/")
        raw_query = request.url.query
        if isinstance(raw_query, bytes):
            raw_query = raw_query.decode()
        query = parse_qs(raw_query, keep_blank_values=True)
        # Instance reads: /{Resource}/{id}. Searches: /{Resource} (+ query).
        relative = path[len(self._base_path) :] if path.startswith(self._base_path) else path
        parts = [p for p in relative.split("/") if p]
        is_search = len(parts) == 1
        if is_search:
            values = query.get(ATHENA_PRACTICE_PARAM, [])
            if len(values) != 1 or values[0] != ATHENA_PRACTICE_VALUE:
                raise AthenaFhirR4Error("practice_override_refused")
        return self._inner.handle_request(request)


class AthenaFhirR4Adapter:
    """Preview-only athena FHIR R4 reader. Mock transport required; no live CI calls."""

    def __init__(
        self,
        *,
        token_client: ClientCredentialsTokenClient,
        transport: httpx.MockTransport,
        sandbox_enabled: bool = False,
        real_data_enabled: bool = False,
        practice_baa_recorded: bool = False,
        base_url: str = ATHENA_FHIR_R4_BASE_URL,
        max_pages: int = 3,
    ) -> None:
        if type(transport) is not httpx.MockTransport:
            raise AthenaFhirR4Error("synthetic_transport_required")
        if type(token_client) is not ClientCredentialsTokenClient:
            raise AthenaFhirR4Error("not_configured")
        if type(sandbox_enabled) is not bool or type(real_data_enabled) is not bool:
            raise AthenaFhirR4Error("invalid_ehr_gate_flags")
        if type(practice_baa_recorded) is not bool:
            raise AthenaFhirR4Error("invalid_ehr_gate_flags")
        if type(max_pages) is not int or not 1 <= max_pages <= 5:
            raise AthenaFhirR4Error("invalid_request")
        if type(base_url) is not str or not base_url.startswith(ATHENA_PREVIEW_ORIGIN):
            raise AthenaFhirR4Error("off_origin_refused")
        # Requested scopes may be exact or a narrowed subset of the approved
        # list. Extra / wildcard scopes are refused (wildcards already fail in C2).
        if not token_client.requested_scopes <= ATHENA_FHIR_SYSTEM_READ_SCOPES:
            raise AthenaFhirR4Error("unsupported_scope")
        if not token_client.requested_scopes:
            raise AthenaFhirR4Error("unsupported_scope")
        self._token_client = token_client
        self._transport = transport
        self._sandbox_enabled = sandbox_enabled
        self._real_data_enabled = real_data_enabled
        self._practice_baa_recorded = practice_baa_recorded
        self._base_url = base_url.rstrip("/")
        self._max_pages = max_pages
        self._scoped_transport = _PracticeScopedTransport(transport, base_url=self._base_url)
        self._granted_scopes: frozenset[str] | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def practice_value(self) -> str:
        return ATHENA_PRACTICE_VALUE

    @property
    def approved_scopes(self) -> frozenset[str]:
        return ATHENA_FHIR_SYSTEM_READ_SCOPES

    @property
    def approved_resources(self) -> frozenset[str]:
        return ATHENA_FHIR_RESOURCES

    def refuse_write(self, action: str = "write") -> None:
        raise AthenaFhirR4Error("action_refused")

    def assert_resource_allowed(
        self, resource_type: str, *, granted_scopes: frozenset[str] | None = None
    ) -> None:
        if type(resource_type) is not str:
            raise AthenaFhirR4Error("resource_unsupported")
        if resource_type in FORBIDDEN_FHIR_RESOURCES:
            raise AthenaFhirR4Error("resource_unsupported")
        if resource_type not in ATHENA_FHIR_RESOURCES:
            raise AthenaFhirR4Error("resource_unsupported")
        scopes = granted_scopes if granted_scopes is not None else self._token_client.requested_scopes
        if f"system/{resource_type}.read" not in scopes:
            raise AthenaFhirR4Error("unsupported_scope")

    def _guard_origin(self) -> None:
        try:
            assert_ehr_request_allowed(
                vendor="athena",
                origin=ATHENA_PREVIEW_ORIGIN,
                sandbox_enabled=self._sandbox_enabled,
                real_data_enabled=self._real_data_enabled,
                practice_baa_recorded=self._practice_baa_recorded,
                mock_transport_only=True,
            )
        except EhrRealDataGateError as exc:
            raise AthenaFhirR4Error(_map_gate_error(exc)) from None

    def _access_token_and_scopes(self) -> tuple[str, frozenset[str]]:
        try:
            token = self._token_client.get_access_token()
        except ClientCredentialsAuthError as exc:
            raise AthenaFhirR4Error(_map_auth_error(exc)) from None
        if type(token) is not SecretStr:
            raise AthenaFhirR4Error("auth_unavailable")
        value = token.get_secret_value()
        if type(value) is not str or not value:
            raise AthenaFhirR4Error("auth_unavailable")
        # C2 caches granted scopes on the private cache entry after mint.
        cache = getattr(self._token_client, "_cache", None)
        granted = self._token_client.requested_scopes
        if cache is not None:
            cached_scopes = getattr(cache, "granted_scopes", None)
            if isinstance(cached_scopes, frozenset) and cached_scopes:
                granted = cached_scopes
        if not granted <= ATHENA_FHIR_SYSTEM_READ_SCOPES:
            raise AthenaFhirR4Error("unsupported_scope")
        self._granted_scopes = granted
        return value, granted

    def _client(self, access_token: str) -> FhirR4ReadClient:
        return FhirR4ReadClient(
            self._base_url,
            transport=self._scoped_transport,
            access_token=access_token,
            display_label="Athena",
            allow_production=False,
            max_pages=self._max_pages,
        )

    def _merge_practice_params(
        self, params: Mapping[str, str] | None
    ) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        if params is not None:
            if not isinstance(params, Mapping):
                raise AthenaFhirR4Error("invalid_request")
            for key, value in params.items():
                if type(key) is not str or type(value) is not str:
                    raise AthenaFhirR4Error("invalid_request")
                if key == ATHENA_PRACTICE_PARAM and value != ATHENA_PRACTICE_VALUE:
                    raise AthenaFhirR4Error("practice_override_refused")
                cleaned[key] = value
        cleaned[ATHENA_PRACTICE_PARAM] = ATHENA_PRACTICE_VALUE
        return cleaned

    def search(
        self,
        resource_type: str,
        params: Mapping[str, str] | None = None,
        *,
        follow_paging: bool = True,
    ) -> FhirReadResult:
        self._guard_origin()
        query = self._merge_practice_params(params)
        token, granted = self._access_token_and_scopes()
        self.assert_resource_allowed(resource_type, granted_scopes=granted)
        client = self._client(token)
        result = client.search(resource_type, query, follow_paging=follow_paging)
        logger.info(
            "athena_fhir_r4_search",
            extra={
                "vendor": "athena",
                "resource_type": resource_type,
                "practice_id": ATHENA_PREVIEW_PRACTICE_ID,
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
        # Instance reads go through the practice-scoped transport; ah-practice is
        # not required on /{type}/{id}, matching athena's Certified FHIR docs.
        result = client.read(resource_type, resource_id)
        logger.info(
            "athena_fhir_r4_read",
            extra={
                "vendor": "athena",
                "resource_type": resource_type,
                "practice_id": ATHENA_PREVIEW_PRACTICE_ID,
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
            "AthenaFhirR4Adapter("
            f"base_url={self._base_url!r}, "
            f"practice={ATHENA_PRACTICE_VALUE!r}, "
            f"sandbox_enabled={self._sandbox_enabled!r})"
        )


def ensure_practice_on_next_url(next_url: str, *, base_url: str = ATHENA_FHIR_R4_BASE_URL) -> str:
    """Test/helper: rebuild a Bundle next URL so ah-practice is present."""
    parts = urlsplit(next_url)
    base = urlsplit(base_url)
    if (parts.scheme, parts.netloc) != (base.scheme, base.netloc):
        raise AthenaFhirR4Error("off_origin_refused")
    query = parse_qs(parts.query, keep_blank_values=True)
    query[ATHENA_PRACTICE_PARAM] = [ATHENA_PRACTICE_VALUE]
    flat = [(k, v) for k, values in sorted(query.items()) for v in values]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(flat), ""))
