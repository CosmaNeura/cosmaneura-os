import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError
from starlette.requests import Request
from tests.unit.test_hosted_workspace_config import hosted
from tests.unit.test_scheduling_actions import operation

from cosmas_os.adapters.scheduling_runtime import (
    SchedulingRuntime,
    SchedulingServiceProfile,
    SchedulingStaffCredential,
    configure_scheduling,
    scheduling_lifespan,
    scheduling_runtime,
)
from cosmas_os.config import Settings
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import (
    AvailabilityWindow,
    SchedulingSelection,
    UnconnectedScheduling,
)
from cosmas_os.ports.scheduling_actions import AppointmentSelection, UnconnectedAppointments

NOW = datetime(2026, 9, 23, 18, tzinfo=UTC)
ORIGIN = "https://scheduling.example.invalid"
WINDOW = AvailabilityWindow(starts_at=NOW, ends_at=NOW + timedelta(days=1))


@pytest.fixture
def configuration():
    return Settings(_env_file=None, workspace_enabled=True, workspace_authenticated_enabled=True,  # pyright: ignore[reportCallIssue] -- BaseSettings accepts _env_file at runtime.
        workspace_scheduling_enabled=True, workspace_appointments_enabled=True,
        database_url="postgresql+psycopg://local@127.0.0.1/w1a_runtime_unit",
        auth_mode="clerk_jwt", synth_seed=False, clerk_issuer="https://identity.example.invalid",
        clerk_jwks_url="https://identity.example.invalid/.well-known/jwks.json",
        clerk_audience="invented", clerk_organization_id="invented", beta_box_id=str(uuid4()),
        cors_allowed_origins="http://127.0.0.1:5173", clerk_authorized_parties="http://127.0.0.1:5173")


@pytest.fixture
def selection():
    return SchedulingSelection(**{name: uuid4() for name in SchedulingSelection.model_fields})


def credential(selection, **changes):
    return SchedulingStaffCredential(selection=selection, family="google_staff_identity",
        token=SecretStr("PRIVATE_invented_staff"), expires_at=NOW + timedelta(minutes=10)).model_copy(update=changes)


def runtime(configuration, provider, requests, **kwargs):
    def response(request):
        requests.append(request)
        return httpx.Response(200, json=[], headers={"Content-Type": "application/json", "Cache-Control": "no-store"})
    return SchedulingRuntime(configuration, SchedulingServiceProfile(ORIGIN, provider),
        transport_factory=lambda: httpx.MockTransport(response), now=kwargs.pop("now", lambda: NOW), **kwargs)


def test_each_read_acquires_a_new_exact_staff_credential(configuration, selection):
    acquisitions, requests = [], []
    def provider(value):
        acquisitions.append(value)
        return credential(value, token=SecretStr(f"PRIVATE_fresh_{len(acquisitions)}"))
    managed = runtime(configuration, provider, requests)
    try:
        for _ in range(2):
            assert managed.availability.availability(selection, WINDOW).slots == ()
        assert acquisitions == [selection, selection]
        assert [r.headers["authorization"] for r in requests] == ["Bearer PRIVATE_fresh_1", "Bearer PRIVATE_fresh_2"]
        assert all(r.url.host == "scheduling.example.invalid" and r.headers["x-practice-id"] == str(selection.practice_id) for r in requests)
        assert all("cookie" not in r.headers for r in requests)
    finally:
        managed.close()


@pytest.mark.parametrize("field", list(SchedulingSelection.model_fields))
def test_every_staff_selection_dimension_is_bound_before_dispatch(configuration, selection, field):
    requests = []
    wrong = selection.model_copy(update={field: uuid4()})
    managed = runtime(configuration, lambda _: credential(wrong), requests)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_identity_unavailable$"):
            managed.availability.availability(selection, WINDOW)
        assert requests == []
    finally:
        managed.close()


@pytest.mark.parametrize("seconds", [-1, 0, 29, 86401])
def test_expired_nearly_expired_or_unbounded_credential_never_dispatches(configuration, selection, seconds):
    requests = []
    managed = runtime(configuration, lambda value: credential(value, expires_at=NOW + timedelta(seconds=seconds)), requests)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_identity_unavailable$"):
            managed.availability.availability(selection, WINDOW)
        assert requests == []
    finally:
        managed.close()


@pytest.mark.parametrize("fault", ["exception", "raw_secret", "clerk", "workload", "malformed_time", "bad_clock", "missing_actor"])
def test_unqualified_or_malformed_credential_is_redacted_and_not_dispatched(configuration, selection, fault):
    acquisitions, requests = [], []
    def provider(value):
        acquisitions.append(value)
        if fault == "exception":
            raise RuntimeError("PRIVATE token acquisition failure")
        if fault == "raw_secret":
            return SecretStr("PRIVATE")
        if fault in {"clerk", "workload"}:
            return credential(value, family=fault)
        if fault == "malformed_time":
            return credential(value, expires_at="PRIVATE")
        return credential(value)
    managed = runtime(configuration, provider, requests, now=lambda: NOW.replace(tzinfo=None) if fault == "bad_clock" else NOW)
    try:
        current = selection.model_copy(update={"expected_actor_id": None}) if fault == "missing_actor" else selection
        with pytest.raises(ConnectorUnavailable, match="^scheduling_identity_unavailable$") as error:
            managed.availability.availability(current, WINDOW)
        assert "PRIVATE" not in str(error.value) and requests == []
        assert len(acquisitions) == (0 if fault == "missing_actor" else 1)
    finally:
        managed.close()


def test_credential_provider_never_receives_patient_identifiers(configuration, selection):
    acquisitions, requests = [], []
    patient = AppointmentSelection(**selection.model_dump(), patient_id=uuid4(), patient_link_id=uuid4())
    def provider(value):
        acquisitions.append(value)
        return credential(value)
    managed = runtime(configuration, provider, requests)
    try:
        # An empty receipt is rejected after one read, but acquisition must already
        # have stripped patient fields and used the exact reviewed staff mapping.
        with pytest.raises(ConnectorUnavailable, match="scheduling_receipt_invalid"):
            managed.appointments.read_appointment(patient, uuid4())
        assert acquisitions == [selection] and type(acquisitions[0]) is SchedulingSelection
        assert len(requests) == 1
        assert str(patient.patient_id) not in repr(acquisitions[0])
    finally:
        managed.close()


@pytest.mark.parametrize("gate", ["workspace_scheduling_enabled", "workspace_appointments_enabled"])
def test_disabling_during_acquisition_stops_dispatch(configuration, selection, gate):
    requests = []
    def provider(value):
        setattr(configuration, gate, False)
        return credential(value)
    managed = runtime(configuration, provider, requests)
    try:
        with pytest.raises(ConnectorUnavailable, match="scheduling_identity_unavailable"):
            if gate == "workspace_scheduling_enabled":
                managed.availability.availability(selection, WINDOW)
            else:
                patient = AppointmentSelection(**selection.model_dump(), patient_id=uuid4(), patient_link_id=uuid4())
                managed.appointments.read_appointment(patient, uuid4())
        assert requests == []
    finally:
        managed.close()


def test_closed_runtime_cannot_acquire_or_dispatch(configuration, selection):
    calls, requests = [], []
    managed = runtime(configuration, lambda value: calls.append(value) or credential(value), requests)
    managed.close()
    managed.close()
    assert managed.availability._client.is_closed and managed.appointments._client.is_closed
    assert managed.patient_setup._client.is_closed
    with pytest.raises(ConnectorUnavailable, match="scheduling_identity_unavailable"):
        managed.availability.availability(selection, WINDOW)
    assert calls == requests == []


def test_patient_setup_stays_closed_without_explicit_feature_gate(configuration, selection):
    from cosmas_os.ports.scheduling_patient_setup import PatientPreviewRequest

    calls, requests = [], []
    managed = runtime(configuration, lambda value: calls.append(value) or credential(value), requests)
    request = PatientPreviewRequest.model_validate(dict(request_nonce=uuid4(), expected_actor_id=selection.expected_actor_id,
        selector={"kind": "search", "query": "Invented patient", "birth_date": None}, limit=5))
    try:
        with pytest.raises(ConnectorUnavailable):
            managed.patient_setup.preview(selection, request)
        assert calls == requests == []
    finally:
        managed.close()


def test_patient_setup_disabled_during_credential_acquisition_never_dispatches(configuration, selection):
    from cosmas_os.ports.scheduling_patient_setup import PatientPreviewRequest

    configuration.workspace_scheduling_login_enabled = True
    configuration.workspace_scheduling_patient_setup_enabled = True
    calls, requests = [], []
    def provider(value):
        calls.append(value)
        configuration.workspace_scheduling_patient_setup_enabled = False
        return credential(value)
    managed = runtime(configuration, provider, requests)
    request = PatientPreviewRequest.model_validate(dict(request_nonce=uuid4(), expected_actor_id=selection.expected_actor_id,
        selector={"kind": "search", "query": "Invented patient", "birth_date": None}, limit=5))
    try:
        with pytest.raises(ConnectorUnavailable):
            managed.patient_setup.preview(selection, request)
        assert calls == [selection] and requests == []
    finally:
        managed.close()


@pytest.mark.parametrize("mode", ["submit", "reconcile"])
def test_hosted_runtime_operations_denied_before_credentials_but_patient_reads_remain(selection, mode):
    configuration = hosted(workspace_scheduling_enabled=True, workspace_appointments_enabled=True)
    assert configuration.workspace_scheduling_available
    acquisitions, requests = [], []
    managed = runtime(configuration, lambda value: acquisitions.append(value) or credential(value), requests)
    patient = AppointmentSelection(**selection.model_dump(), patient_id=uuid4(), patient_link_id=uuid4())
    try:
        assert not configuration.workspace_appointment_execution_available
        with pytest.raises(ConnectorUnavailable, match="^scheduling_execution_not_available$"):
            getattr(managed.appointments, mode)(_runtime_operation(patient))
        assert acquisitions == requests == []
        with pytest.raises(ConnectorUnavailable, match="scheduling_receipt_invalid"):
            managed.appointments.read_appointment(patient, uuid4())
        assert acquisitions == [selection] and len(requests) == 1 and requests[0].method == "GET"
    finally:
        managed.close()


@pytest.mark.parametrize("mode", ["submit", "reconcile"])
def test_hosted_mode_enabled_during_credential_acquisition_denies_operation(configuration, selection, mode):
    acquisitions, requests = [], []
    def provider(value):
        acquisitions.append(value)
        configuration.workspace_hosted_enabled = True
        return credential(value)
    managed = runtime(configuration, provider, requests)
    patient = AppointmentSelection(**selection.model_dump(), patient_id=uuid4(), patient_link_id=uuid4())
    try:
        with pytest.raises(ConnectorUnavailable):
            getattr(managed.appointments, mode)(_runtime_operation(patient))
        assert acquisitions == [selection] and requests == []
    finally:
        managed.close()


def _runtime_operation(patient):
    original = operation(patient)
    assert original.intent.slot is not None and original.intent.google is not None
    intent = original.intent.model_copy(update={"expires_at": NOW + timedelta(minutes=3),
        "slot": original.intent.slot.model_copy(update={"starts_at": NOW + timedelta(days=2),
            "ends_at": NOW + timedelta(days=2, minutes=30)}),
        "google": original.intent.google.model_copy(update={"checked_at": NOW})})
    return original.model_copy(update={"intent": intent, "approved_payload_hash": intent.approval_hash()})


@pytest.mark.parametrize("origin", ["http://127.0.0.1:9999", "https://other.invalid/path", "https://user:PRIVATE@other.invalid", "https://other.invalid:8443"])
def test_profile_cannot_redirect_staff_credentials(configuration, origin):
    calls = []
    with pytest.raises(ValueError, match="configured HTTPS origin"):
        SchedulingRuntime(configuration, SchedulingServiceProfile(origin, lambda value: calls.append(value) or credential(value)))
    assert calls == []


def test_ordinary_application_lifespan_and_dependencies_use_profile_without_overrides(configuration, selection, monkeypatch):
    from cosmas_os.api import app as api
    monkeypatch.setattr(api, "settings", configuration)
    application = FastAPI(lifespan=api.lifespan)
    calls = []
    configure_scheduling(application, SchedulingServiceProfile(ORIGIN, lambda value: calls.append(value) or credential(value)))
    request = Request({"type": "http", "app": application})
    held = []
    async def exercise():
        async with api.lifespan(application):
            current = scheduling_runtime(application)
            held.append(current)
            assert current is not None
            assert api._scheduling_connection(request) is current.availability
            assert api._appointment_connection(request) is current.appointments
            assert application.dependency_overrides == {}
            assert calls == []  # Configuration/startup never acquires a credential.
    asyncio.run(exercise())
    assert scheduling_runtime(application) is None
    assert held[0].availability._client.is_closed and held[0].appointments._client.is_closed
    assert isinstance(api._scheduling_connection(request), UnconnectedScheduling)
    assert isinstance(api._appointment_connection(request), UnconnectedAppointments)


def test_unconfigured_lifespan_stays_unconnected_and_rejects_late_install(configuration, selection):
    application = FastAPI()
    profile = SchedulingServiceProfile(ORIGIN, lambda value: credential(value))
    with scheduling_lifespan(application, configuration):
        assert scheduling_runtime(application) is None
        with pytest.raises(ValueError, match="once before startup"):
            configure_scheduling(application, profile)
    with pytest.raises(ValueError, match="once before startup"):
        configure_scheduling(application, profile)


def test_profile_replacement_is_refused_and_disabled_startup_acquires_nothing(configuration, selection):
    application = FastAPI()
    calls = []
    profile = SchedulingServiceProfile(ORIGIN, lambda value: calls.append(value) or credential(value))
    configure_scheduling(application, profile)
    with pytest.raises(ValueError, match="once before startup"):
        configure_scheduling(application, profile)
    configuration.workspace_scheduling_enabled = False
    with pytest.raises(ValueError, match="authenticated workspace gate"), scheduling_lifespan(application, configuration):
        pytest.fail("disabled profile must not start")
    assert calls == [] and scheduling_runtime(application) is None


def test_startup_failure_after_client_creation_closes_both_clients(configuration, selection):
    application = FastAPI()
    configure_scheduling(application, SchedulingServiceProfile(ORIGIN, lambda value: credential(value)))
    held = []
    with pytest.raises(RuntimeError, match="synthetic startup failure"), scheduling_lifespan(application, configuration):
        held.append(scheduling_runtime(application))
        raise RuntimeError("synthetic startup failure")
    assert scheduling_runtime(application) is None
    assert held[0].availability._client.is_closed and held[0].appointments._client.is_closed


def test_invalid_family_and_secret_never_appear_in_validation_or_representations(selection):
    proof = credential(selection)
    profile = SchedulingServiceProfile(ORIGIN, lambda _: proof)
    assert "PRIVATE" not in repr(proof) + str(proof) + repr(profile)
    with pytest.raises(ValidationError) as error:
        SchedulingStaffCredential(**{**proof.model_dump(), "family": "PRIVATE_clerk"})
    assert "PRIVATE" not in str(error.value)


def test_overlapping_lifespan_cannot_replace_or_close_active_clients(configuration):
    application = FastAPI()
    configure_scheduling(application, SchedulingServiceProfile(ORIGIN, credential))
    with scheduling_lifespan(application, configuration):
        first = scheduling_runtime(application)
        assert first is not None
        with pytest.raises(RuntimeError, match="already active"), scheduling_lifespan(application, configuration):
            pytest.fail("overlapping startup must be refused")
        assert scheduling_runtime(application) is first
        assert not first.availability._client.is_closed
    assert first.availability._client.is_closed


def test_second_client_construction_failure_closes_first_transport(configuration):
    transports = []
    class Transport(httpx.MockTransport):
        closed = False
        def close(self):
            self.closed = True
            super().close()
    def factory():
        if transports:
            raise RuntimeError("synthetic transport construction failure")
        first = Transport(lambda _: httpx.Response(200))
        transports.append(first)
        return first
    with pytest.raises(RuntimeError, match="construction failure"):
        SchedulingRuntime(configuration, SchedulingServiceProfile(ORIGIN, credential), transport_factory=factory)
    assert transports[0].closed


def test_shutdown_failure_does_not_skip_sibling_client_cleanup(configuration, monkeypatch):
    requests = []
    managed = runtime(configuration, credential, requests)
    original = managed.appointments.close
    def broken():
        original()
        raise RuntimeError("synthetic transport cleanup failure")
    monkeypatch.setattr(managed.appointments, "close", broken)
    with pytest.raises(RuntimeError, match="cleanup failure"):
        managed.close()
    assert managed.appointments._client.is_closed and managed.availability._client.is_closed


def test_existing_worker_is_settled_if_later_worker_setup_fails(configuration, monkeypatch):
    from cosmas_os.api import app as api
    configuration.workspace_llm_backend = "azure_gpt41"
    configuration.workspace_llm_api_key = SecretStr("PRIVATE_invented")
    configuration.workspace_routines_enabled = True
    monkeypatch.setattr(api, "settings", configuration)
    settled = []
    async def worker(_sessions, stop, *, progress=None):
        await stop.wait()
        settled.append("handoff")
    def fail_sources():
        raise RuntimeError("synthetic routine startup failure")
    monkeypatch.setattr(api.handoffs, "run_worker", worker)
    monkeypatch.setattr(api, "_routine_sources", fail_sources)
    async def exercise():
        with pytest.raises(RuntimeError, match="routine startup failure"):
            async with api.lifespan(FastAPI()):
                pytest.fail("startup must fail")
        assert settled == ["handoff"]
    asyncio.run(exercise())


def test_one_worker_failure_does_not_skip_other_worker_shutdown(configuration, monkeypatch):
    from cosmas_os.api import app as api
    configuration.workspace_llm_backend = "azure_gpt41"
    configuration.workspace_llm_api_key = SecretStr("PRIVATE_invented")
    configuration.workspace_routines_enabled = True
    monkeypatch.setattr(api, "settings", configuration)
    settled = []
    async def handoff(_sessions, stop, *, progress=None):
        await stop.wait()
        raise RuntimeError("synthetic handoff shutdown failure")
    async def routine(_sessions, stop, **_kwargs):
        await stop.wait()
        await asyncio.sleep(0)
        settled.append("routine")
    monkeypatch.setattr(api.handoffs, "run_worker", handoff)
    monkeypatch.setattr(api.routines, "run_worker", routine)
    monkeypatch.setattr(api, "_routine_sources", lambda: ())
    async def exercise():
        with pytest.raises(RuntimeError, match="handoff shutdown failure"):
            async with api.lifespan(FastAPI()):
                pass
        assert settled == ["routine"]
    asyncio.run(exercise())
