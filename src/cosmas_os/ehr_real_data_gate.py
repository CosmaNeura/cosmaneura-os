"""Shared EHR real-data / production gate (ticket C14).

Every athena, Elation, and Tebra request path calls ``assert_ehr_request_allowed``
before contacting a vendor origin. Atlas.md has no practice API origin.

Rules (defaults are fail-closed):

* Sandbox / preview origins are allowed only when ``sandbox_enabled`` is true.
* Non-sandbox (production) origins are allowed only when both
  ``real_data_enabled`` (``COSMAS_EHR_REAL_DATA_ENABLED``) and
  ``practice_baa_recorded`` on the connection are true.
* Unknown origins are refused.
* Tebra has no sandbox origin in-repo. Exact ``httpx.MockTransport`` synthetic
  fixtures may still target Tebra's documented production hostname while the
  real-data switch stays off; a live transport must never set
  ``mock_transport_only``.

Hook fit for draft PR #258 (``grok/ehr-connector-contract``): that PR defines
``plugins.ehr.hooks.ProductionGate`` with::

    allow_production(*, vendor_id, target) -> bool

``CosmasEhrRealDataGate`` matches that structural Protocol. Once #258 merges,
pass an instance into ``DeclaredEhrConnector.allow_target(..., production_gate=...)``
/ ``allow_read``. This module does not import ``plugins.ehr`` so it stays usable
on main before that PR lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

Vendor = Literal["athena", "elation", "tebra", "atlas_md"]
TargetEnvironment = Literal["sandbox", "production"]

ATHENA_PREVIEW_ORIGIN = "https://api.preview.platform.athenahealth.com"
ATHENA_PRODUCTION_ORIGIN = "https://api.platform.athenahealth.com"
ELATION_SANDBOX_ORIGIN = "https://sandbox.elationemr.com"
ELATION_PRODUCTION_ORIGIN = "https://api.app.elationemr.com"
TEBRA_FHIR_ORIGIN = "https://fhir.prd.cloud.tebra.com"
TEBRA_SOAP_ORIGIN = "https://webservice.kareo.com"

SANDBOX_ORIGINS: dict[Vendor, frozenset[str]] = {
    "athena": frozenset({ATHENA_PREVIEW_ORIGIN}),
    "elation": frozenset({ELATION_SANDBOX_ORIGIN}),
    "tebra": frozenset(),
    "atlas_md": frozenset(),
}

PRODUCTION_ORIGINS: dict[Vendor, frozenset[str]] = {
    "athena": frozenset({ATHENA_PRODUCTION_ORIGIN}),
    "elation": frozenset({ELATION_PRODUCTION_ORIGIN}),
    "tebra": frozenset({TEBRA_FHIR_ORIGIN, TEBRA_SOAP_ORIGIN}),
    "atlas_md": frozenset(),
}

_VENDORS = frozenset({"athena", "elation", "tebra", "atlas_md"})


class EhrRealDataGateError(Exception):
    """Closed gate error; ``code`` carries no PHI or vendor payload."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class EhrOriginDecision:
    vendor: Vendor
    origin: str
    kind: Literal["sandbox", "production", "unknown"]
    allowed: bool
    code: str | None = None


def normalize_ehr_origin(origin: str) -> str:
    """Reduce a request URL or origin to ``scheme://netloc`` (lowercase host)."""
    if type(origin) is not str or not origin or len(origin) > 2048:
        raise EhrRealDataGateError("invalid_ehr_origin")
    parts = urlsplit(origin.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise EhrRealDataGateError("invalid_ehr_origin")
    host = parts.hostname
    if host is None or any(c in origin for c in "\\\r\n\t"):
        raise EhrRealDataGateError("invalid_ehr_origin")
    netloc = host.lower()
    if parts.port and parts.port not in (80, 443):
        netloc = f"{netloc}:{parts.port}"
    return f"{parts.scheme.lower()}://{netloc}"


def classify_ehr_origin(vendor: Vendor, origin: str) -> Literal["sandbox", "production", "unknown"]:
    if vendor not in SANDBOX_ORIGINS:
        raise EhrRealDataGateError("unknown_ehr_vendor")
    normalized = normalize_ehr_origin(origin)
    if normalized in SANDBOX_ORIGINS[vendor]:
        return "sandbox"
    if normalized in PRODUCTION_ORIGINS[vendor]:
        return "production"
    return "unknown"


def atlas_md_has_no_origin() -> bool:
    """Atlas.md has no practice API; adapters must not send EHR requests."""
    return True


def assert_ehr_request_allowed(
    *,
    vendor: Vendor,
    origin: str,
    sandbox_enabled: bool = False,
    real_data_enabled: bool = False,
    practice_baa_recorded: bool = False,
    mock_transport_only: bool = False,
) -> EhrOriginDecision:
    """Refuse vendor origins that are not explicitly allowed.

    ``real_data_enabled`` must come from ``COSMAS_EHR_REAL_DATA_ENABLED``
    (default false). ``practice_baa_recorded`` is a per-connection flag; it is
    false until a practice BAA is recorded. Hosted and production configs must
    leave the real-data switch off.
    """
    if vendor == "atlas_md":
        raise EhrRealDataGateError("atlas_md_unsupported")
    if type(sandbox_enabled) is not bool or type(real_data_enabled) is not bool:
        raise EhrRealDataGateError("invalid_ehr_gate_flags")
    if type(practice_baa_recorded) is not bool or type(mock_transport_only) is not bool:
        raise EhrRealDataGateError("invalid_ehr_gate_flags")

    kind = classify_ehr_origin(vendor, origin)
    normalized = normalize_ehr_origin(origin)

    if kind == "sandbox":
        if not sandbox_enabled:
            raise EhrRealDataGateError("sandbox_flag_required")
        return EhrOriginDecision(vendor, normalized, kind, True)

    if kind == "production":
        if real_data_enabled and practice_baa_recorded:
            return EhrOriginDecision(vendor, normalized, kind, True)
        # Tebra synthetic fixtures record against the vendor production hostname
        # with an exact MockTransport only. Live transports never set this.
        if mock_transport_only and vendor == "tebra":
            return EhrOriginDecision(vendor, normalized, kind, True)
        raise EhrRealDataGateError("real_data_required")

    raise EhrRealDataGateError("unknown_ehr_origin")


@dataclass(frozen=True, slots=True)
class CosmasEhrRealDataGate:
    """C14 production gate shaped for #258's ``ProductionGate`` Protocol.

    Structural match (no import of ``plugins.ehr``)::

        def allow_production(*, vendor_id, target) -> bool

    Defaults keep production refused. Construct from settings / connection::

        CosmasEhrRealDataGate(
            real_data_enabled=settings.cosmas_ehr_real_data_enabled,
            practice_baa_recorded=connection.practice_baa_recorded,
        )

    After #258 merges, pass the instance as ``production_gate=`` into
    ``DeclaredEhrConnector.allow_target`` / ``allow_read``.
    """

    real_data_enabled: bool = False
    practice_baa_recorded: bool = False

    def __post_init__(self) -> None:
        if type(self.real_data_enabled) is not bool or type(self.practice_baa_recorded) is not bool:
            raise EhrRealDataGateError("invalid_ehr_gate_flags")

    def allow_production(self, *, vendor_id: str, target: str) -> bool:
        """Return True only when production / real-data use is explicitly authorized.

        Matches ``plugins.ehr.hooks.ProductionGate.allow_production`` once #258
        is merged. Sandbox targets are not authorized through this method; the
        connector handles sandbox separately. Atlas.md never allows production.
        """
        if type(vendor_id) is not str or type(target) is not str:
            return False
        if target != "production":
            return False
        if vendor_id not in _VENDORS or vendor_id == "atlas_md":
            return False
        return bool(self.real_data_enabled and self.practice_baa_recorded)
