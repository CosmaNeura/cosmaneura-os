"""C14: shared EHR real-data gate. Production origins refuse by default."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import httpx
import pytest
from tests.unit.test_athena_allergy_read import SCOPE as ATHENA_SCOPE
from tests.unit.test_athena_allergy_read import Harness as AthenaHarness
from tests.unit.test_athena_medication_read import SCOPE as ATHENA_MED_SCOPE
from tests.unit.test_athena_medication_read import Harness as AthenaMedHarness
from tests.unit.test_elation_lab_read import SCOPE as ELATION_LAB_SCOPE
from tests.unit.test_elation_read import SCOPE as ELATION_SCOPE

from cosmas_os.adapters.athena_allergy_read import (
    ORIGINS as ATHENA_ORIGINS,
)
from cosmas_os.adapters.athena_allergy_read import (
    AthenaAllergyError,
    AthenaAllergyReader,
)
from cosmas_os.adapters.athena_medication_read import AthenaMedicationError
from cosmas_os.adapters.elation_lab_read import ElationLabError, ElationLabReader
from cosmas_os.adapters.elation_read import ORIGIN as ELATION_SANDBOX_ORIGIN
from cosmas_os.adapters.elation_read import ElationReadAdapter, ElationReadError
from cosmas_os.adapters.tebra_fhir_read import FHIR_BASE, TebraFhirReadAdapter, TebraFhirReadError
from cosmas_os.adapters.tebra_read import ENDPOINT as TEBRA_SOAP_ENDPOINT
from cosmas_os.adapters.tebra_read import TebraReadAdapter, TebraReadError
from cosmas_os.config import Settings
from cosmas_os.ehr_real_data_gate import (
    ATHENA_PRODUCTION_ORIGIN,
    ELATION_FHIR_PRODUCTION_ORIGIN,
    ELATION_FHIR_SANDBOX_ORIGIN,
    ELATION_PRODUCTION_ORIGIN,
    PRODUCTION_ORIGINS,
    CosmasEhrRealDataGate,
    EhrRealDataGateError,
    assert_ehr_request_allowed,
    atlas_md_has_no_origin,
    classify_ehr_origin,
)
from cosmas_os.plugins import atlas_md


@pytest.mark.parametrize(
    ("vendor", "origin"),
    [
        ("athena", ATHENA_PRODUCTION_ORIGIN),
        ("elation", ELATION_PRODUCTION_ORIGIN),
        ("elation", ELATION_FHIR_PRODUCTION_ORIGIN),
        ("tebra", FHIR_BASE),
        ("tebra", TEBRA_SOAP_ENDPOINT),
    ],
)
def test_production_origins_are_refused_by_default(vendor, origin):
    with pytest.raises(EhrRealDataGateError, match="^real_data_required$"):
        assert_ehr_request_allowed(vendor=vendor, origin=origin)
    with pytest.raises(EhrRealDataGateError, match="^real_data_required$"):
        assert_ehr_request_allowed(
            vendor=vendor,
            origin=origin,
            real_data_enabled=True,
            practice_baa_recorded=False,
        )
    with pytest.raises(EhrRealDataGateError, match="^real_data_required$"):
        assert_ehr_request_allowed(
            vendor=vendor,
            origin=origin,
            real_data_enabled=False,
            practice_baa_recorded=True,
        )


def test_real_data_gate_off_by_default_refuses_every_non_sandbox_source_in_every_adapter():
    """CTO readiness: switch defaults off; every non-sandbox origin is refused.

    Covers the shared gate for every catalogued production origin, plus each
    wired adapter (athena allergy/medication, Elation visit/lab, Tebra FHIR/SOAP,
    Atlas.md with no origin).
    """
    assert Settings().cosmas_ehr_real_data_enabled is False
    closed = CosmasEhrRealDataGate()
    assert closed.real_data_enabled is False and closed.practice_baa_recorded is False
    for vendor_id in ("athena", "elation", "tebra", "atlas_md"):
        assert closed.allow_production(vendor_id=vendor_id, target="production") is False

    non_sandbox = [
        (vendor, origin)
        for vendor, origins in PRODUCTION_ORIGINS.items()
        for origin in sorted(origins)
    ]
    assert non_sandbox == [
        ("athena", ATHENA_PRODUCTION_ORIGIN),
        ("elation", ELATION_PRODUCTION_ORIGIN),
        ("elation", ELATION_FHIR_PRODUCTION_ORIGIN),
        ("tebra", "https://fhir.prd.cloud.tebra.com"),
        ("tebra", "https://webservice.kareo.com"),
    ]
    for vendor, origin in non_sandbox:
        with pytest.raises(EhrRealDataGateError, match="^real_data_required$"):
            assert_ehr_request_allowed(vendor=vendor, origin=origin)

    # athena allergy + medication adapters refuse production when flags stay default.
    allergy = AthenaHarness()
    with pytest.raises(AthenaAllergyError, match="^real_data_required$"):
        allergy.reader(replace(ATHENA_SCOPE, environment="production"), sandbox_enabled=False).read()
    assert allergy.calls == []

    medication = AthenaMedHarness()
    with pytest.raises(AthenaMedicationError, match="^real_data_required$"):
        medication.reader(
            replace(ATHENA_MED_SCOPE, environment="production"), sandbox_enabled=False
        ).read()
    assert medication.calls == []

    # Elation adapters dial only the sandbox origin; production is refused above.
    assert ELATION_SANDBOX_ORIGIN == "https://sandbox.elationemr.com"
    assert ELATION_PRODUCTION_ORIGIN not in {ELATION_SANDBOX_ORIGIN}

    async def credentials(_):
        raise AssertionError("credentials must not resolve when the real-data gate is closed")

    async def allow(_):
        return True

    def forbidden(_: httpx.Request):
        raise AssertionError("closed gate must not contact a vendor origin")

    elation = ElationReadAdapter(
        ELATION_SCOPE,
        credentials,
        enabled=True,
        authorize_read=allow,
        transport=httpx.MockTransport(forbidden),
        sandbox_enabled=False,
        real_data_enabled=False,
        practice_baa_recorded=False,
    )
    with pytest.raises(ElationReadError, match="^access_denied$"):
        elation._guard_origin()

    lab = ElationLabReader(
        ELATION_LAB_SCOPE,
        httpx.MockTransport(forbidden),
        enabled=lambda: True,
        authorize=lambda _: True,
        sandbox_enabled=False,
        real_data_enabled=False,
        practice_baa_recorded=False,
    )
    with pytest.raises(ElationLabError, match="^access_denied$"):
        lab._guard_origin()

    # Tebra has no sandbox origin. Live/non-mock transports refuse production
    # when the real-data switch stays off (MockTransport is a synthetic bypass).
    fhir = TebraFhirReadAdapter(
        enabled=True,
        transport=None,
        authorize_read=lambda _: True,
        verify_patient=lambda *_: True,
        real_data_enabled=False,
        practice_baa_recorded=False,
    )
    with pytest.raises(TebraFhirReadError, match="^real_data_required$"):
        fhir._guard_origin()

    # SOAP checks MockTransport before the gate; live transport stays dark, and
    # the gate call the adapter would make without the mock bypass refuses.
    soap = TebraReadAdapter(
        authorize_read=lambda _: True,
        enabled=True,
        transport=None,
        real_data_enabled=False,
        practice_baa_recorded=False,
    )
    from cosmas_os.adapters.tebra_read import TebraReadScope

    soap_scope = TebraReadScope(
        UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), 900, 901, "Invented Clinic"
    )
    with pytest.raises(TebraReadError, match="^provider_qualification_required$"):
        soap._guard(soap_scope)
    with pytest.raises(EhrRealDataGateError, match="^real_data_required$"):
        assert_ehr_request_allowed(
            vendor="tebra",
            origin=TEBRA_SOAP_ENDPOINT,
            sandbox_enabled=False,
            real_data_enabled=False,
            practice_baa_recorded=False,
            mock_transport_only=False,
        )

    assert atlas_md_has_no_origin() is True
    with pytest.raises(EhrRealDataGateError, match="^atlas_md_unsupported$"):
        assert_ehr_request_allowed(vendor="atlas_md", origin=ATHENA_PRODUCTION_ORIGIN)


@pytest.mark.parametrize(
    ("vendor", "origin"),
    [
        ("athena", ATHENA_ORIGINS["preview"]),
        ("elation", ELATION_SANDBOX_ORIGIN),
        ("elation", ELATION_FHIR_SANDBOX_ORIGIN),
    ],
)
def test_sandbox_origin_allowed_only_with_sandbox_flag(vendor, origin):
    assert classify_ehr_origin(vendor, origin) == "sandbox"
    with pytest.raises(EhrRealDataGateError, match="^sandbox_flag_required$"):
        assert_ehr_request_allowed(vendor=vendor, origin=origin)
    with pytest.raises(EhrRealDataGateError, match="^sandbox_flag_required$"):
        assert_ehr_request_allowed(vendor=vendor, origin=origin, sandbox_enabled=False)
    decision = assert_ehr_request_allowed(vendor=vendor, origin=origin, sandbox_enabled=True)
    assert decision.allowed is True and decision.kind == "sandbox"


def test_elation_fhir_production_origin_refused_by_default():
    assert classify_ehr_origin("elation", ELATION_FHIR_PRODUCTION_ORIGIN) == "production"
    with pytest.raises(EhrRealDataGateError, match="^real_data_required$"):
        assert_ehr_request_allowed(
            vendor="elation",
            origin=ELATION_FHIR_PRODUCTION_ORIGIN,
            sandbox_enabled=True,
            real_data_enabled=False,
            practice_baa_recorded=False,
            mock_transport_only=True,
        )
    assert ELATION_FHIR_PRODUCTION_ORIGIN in PRODUCTION_ORIGINS["elation"]


def test_production_allowed_only_with_real_data_switch_and_practice_baa():
    decision = assert_ehr_request_allowed(
        vendor="athena",
        origin=ATHENA_PRODUCTION_ORIGIN,
        real_data_enabled=True,
        practice_baa_recorded=True,
    )
    assert decision.allowed is True and decision.kind == "production"


def test_athena_adapter_refuses_production_origin_by_default():
    harness = AthenaHarness()
    scope = replace(ATHENA_SCOPE, environment="production")
    reader = harness.reader(scope, sandbox_enabled=False)
    with pytest.raises(AthenaAllergyError, match="^real_data_required$"):
        reader.read()
    assert harness.calls == []


def test_athena_adapter_refuses_preview_without_sandbox_flag():
    harness = AthenaHarness()
    reader = harness.reader(sandbox_enabled=False)
    with pytest.raises(AthenaAllergyError, match="^sandbox_flag_required$"):
        reader.read()
    assert harness.calls == []


def test_athena_adapter_allows_preview_with_sandbox_flag():
    harness = AthenaHarness()
    value = harness.reader(sandbox_enabled=True).read()
    assert value.records and harness.calls


def test_elation_adapter_refuses_sandbox_without_sandbox_flag():
    import asyncio

    async def credentials(_):
        raise AssertionError("credentials must not resolve when the sandbox flag is off")

    async def allow(_):
        return True

    def forbidden(_: httpx.Request):
        raise AssertionError("sandbox origin must not be contacted without the sandbox flag")

    port = ElationReadAdapter(
        ELATION_SCOPE,
        credentials,
        enabled=True,
        authorize_read=allow,
        transport=httpx.MockTransport(forbidden),
        sandbox_enabled=False,
    )
    with pytest.raises(ElationReadError, match="^access_denied$"):
        asyncio.run(port.patient(930))


def test_elation_production_origin_refused_by_shared_gate():
    with pytest.raises(EhrRealDataGateError, match="^real_data_required$"):
        assert_ehr_request_allowed(vendor="elation", origin=ELATION_PRODUCTION_ORIGIN)


def test_tebra_production_origins_refused_without_real_data_or_mock_bypass():
    with pytest.raises(EhrRealDataGateError, match="^real_data_required$"):
        assert_ehr_request_allowed(vendor="tebra", origin=FHIR_BASE, mock_transport_only=False)
    with pytest.raises(EhrRealDataGateError, match="^real_data_required$"):
        assert_ehr_request_allowed(vendor="tebra", origin=TEBRA_SOAP_ENDPOINT, mock_transport_only=False)
    # Live transports remain refused by the adapter before any origin contact.
    with httpx.HTTPTransport() as live:
        fhir = TebraFhirReadAdapter(
            enabled=True,
            transport=live,
            authorize_read=lambda _: True,
            verify_patient=lambda *_: True,
        )
        with pytest.raises(TebraFhirReadError, match="provider_qualification_required"):
            from pydantic import SecretStr

            from cosmas_os.adapters.tebra_fhir_read import TebraFhirCredential, TebraFhirScope

            scope = TebraFhirScope(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), "patient-A", "a" * 64)
            fhir.medication_history(scope, TebraFhirCredential(scope.commitment(), SecretStr("invented-token")))
    soap = TebraReadAdapter(authorize_read=lambda _: True, enabled=True, transport=None)
    with pytest.raises(TebraReadError, match="provider_qualification_required"):
        from cosmas_os.adapters.tebra_read import TebraCredentials, TebraReadScope

        scope = TebraReadScope(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), 900, 901, "Invented Clinic")
        soap.find_patients(
            scope,
            TebraCredentials(SecretStr("u"), SecretStr("p"), SecretStr("k")),
            last_name="Example",
            birth_date=__import__("datetime").date(1980, 1, 2),
        )


def test_atlas_md_has_no_origin_and_still_returns_unsupported():
    assert atlas_md_has_no_origin() is True
    with pytest.raises(EhrRealDataGateError, match="^atlas_md_unsupported$"):
        assert_ehr_request_allowed(vendor="atlas_md", origin=ATHENA_PRODUCTION_ORIGIN)
    result = atlas_md.call(None, "atlas_md_read_appointments", {})
    assert result["result"]["state"] == "unsupported"


def test_settings_default_real_data_switch_off_and_hosted_refuses_it():
    assert Settings().cosmas_ehr_real_data_enabled is False
    hosted = Settings(
        cosmas_env="early_adopter_beta",
        data_mode="synthetic",
        auth_mode="clerk_jwt",
        workspace_enabled=True,
        workspace_authenticated_enabled=True,
        workspace_hosted_enabled=True,
        cosmas_ehr_real_data_enabled=True,
        cors_allowed_origins="https://workspace.example.invalid",
        clerk_authorized_parties="https://workspace.example.invalid",
        clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-beta-api",
        clerk_organization_id="org_test",
        beta_box_id="00000000-0000-4000-8000-000000000001",
        human_deploy_evidence_ref="deploy:test",
        blob_backend="azure",
        azure_storage_account_url="https://storage.example.invalid",
        azure_blob_container="box-data",
        synth_seed=False,
        sync_worker=False,
        database_url=(
            "postgresql+psycopg://test:test@pg.example.invalid/cosmas_os?"
            "sslmode=verify-full&sslrootcert=system"
        ),
        redis_url="rediss://:invented-secret@redis.example.invalid:6380/0?ssl_cert_reqs=required",
    )
    assert any(
        "COSMAS_EHR_REAL_DATA_ENABLED must remain false" in error
        for error in hosted.runtime_configuration_errors()
    )


def test_production_gate_hook_shape_matches_c1_protocol():
    """#258 ProductionGate: allow_production(*, vendor_id, target) -> bool."""
    closed = CosmasEhrRealDataGate()
    assert closed.allow_production(vendor_id="athena", target="production") is False
    assert closed.allow_production(vendor_id="elation", target="production") is False
    assert closed.allow_production(vendor_id="tebra", target="production") is False
    assert closed.allow_production(vendor_id="atlas_md", target="production") is False
    # Sandbox is not authorized through the production hook.
    assert closed.allow_production(vendor_id="elation", target="sandbox") is False

    half = CosmasEhrRealDataGate(real_data_enabled=True, practice_baa_recorded=False)
    assert half.allow_production(vendor_id="athena", target="production") is False

    open_gate = CosmasEhrRealDataGate(real_data_enabled=True, practice_baa_recorded=True)
    assert open_gate.allow_production(vendor_id="athena", target="production") is True
    assert open_gate.allow_production(vendor_id="elation", target="production") is True
    assert open_gate.allow_production(vendor_id="tebra", target="production") is True
    assert open_gate.allow_production(vendor_id="atlas_md", target="production") is False


def test_athena_allergy_reader_construction_still_requires_exact_mock_transport():
    with httpx.HTTPTransport() as live:
        with pytest.raises(AthenaAllergyError, match="synthetic_transport_required"):
            AthenaAllergyReader(
                ATHENA_SCOPE,
                live,  # type: ignore[arg-type]
                expected_identity_sha256="a" * 64,
                enabled=lambda: True,
                authorize=lambda _: True,
                sandbox_enabled=True,
            )
