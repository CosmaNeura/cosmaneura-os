"""Signed Tebra SOAP-to-source journey; all provider traffic is invented in-process."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from tests.integration.test_ehr_reads import ehr_case
from tests.integration.test_elation_sandbox_installation import install_body, installed, sandbox
from tests.integration.test_handoff_review import isolate_http_request, request_sessions
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace
from tests.unit.test_tebra_read import SECURITY, envelope

from cosmas_os.adapters.ehr_read_runtime import EhrReadRuntimes
from cosmas_os.adapters.elation_read import ElationReadScope
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.adapters.elation_sandbox_runtime import ManagedElationSandboxReads
from cosmas_os.adapters.tebra_read_runtime import SyntheticTebraReads, TebraWorkspaceScope
from cosmas_os.api import app as api_module
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application import provider_team
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ehr_read_models import EhrReadBinding, EhrReadRequest, EhrReadSnapshot
from cosmas_os.elation_sandbox_models import ElationSandboxInstallationReceipt

signed_workspace = _signed_workspace
__all__ = ["signed_workspace", "ehr_case", "sandbox"]


class InventedTebra:
    def __init__(self, session):
        self.session, self.calls = session, []
        self.fail = False
        self.after = lambda: None
        self.patient_id = 910
        self.patient_name = "Alex Example"
        self.status = "Scheduled"
        self.extra_patient = False
        self.naive = False
        self.row_count = 1
        self.starts_at = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)

    def __call__(self, request):
        assert not self.session.in_transaction(), "No SQL transaction may cross provider I/O"
        assert request.url.host == "webservice.kareo.com" and request.method == "POST"
        operation = request.headers["soapaction"].split("/")[-1].rstrip('"')
        self.calls.append(operation)
        self.after()
        if self.fail:
            raise httpx.ReadTimeout("invented provider failure", request=request)
        xml = ET.fromstring(request.content)
        def field(name):
            value = xml.find(".//{http://www.kareo.com/api/schemas/}Filter/{http://www.kareo.com/api/schemas/}" + name)
            assert value is not None and value.text is not None
            return value.text
        practice = "Invented Tebra Clinic"
        if operation == "GetPractices":
            rows = f"<PracticeData><ID>901</ID><PracticeName>{practice}</PracticeName></PracticeData>"
        elif operation == "GetAppointments":
            self.starts_at = datetime.fromisoformat(field("StartDate")) + timedelta(minutes=30)
            start, end = self.starts_at, self.starts_at + timedelta(minutes=30)
            if self.naive:
                start, end = start.replace(tzinfo=None), end.replace(tzinfo=None)
            rows = f"<AppointmentData><ID>920</ID><PatientID>910</PatientID><PracticeID>901</PracticeID><PracticeName>{practice}</PracticeName><ConfirmationStatus>{self.status}</ConfirmationStatus><StartDate>{start.isoformat()}</StartDate><EndDate>{end.isoformat()}</EndDate></AppointmentData>"
            rows = "".join(rows.replace("<ID>920</ID>", f"<ID>{920 + i}</ID>") for i in range(self.row_count))
        else:
            assert operation == "GetPatients"
            rows = ""
            if field("LastName") == "Example" and field("FromDateOfBirth") == "1980-01-02":
                rows = f"<PatientData><DOB>1980-01-02</DOB><ID>{self.patient_id}</ID><LastName>Example</LastName><PatientFullName>{escape(self.patient_name)}</PatientFullName><PracticeName>{practice}</PracticeName></PatientData>"
                if self.extra_patient:
                    rows += rows.replace(f"<ID>{self.patient_id}</ID>", "<ID>911</ID>").replace(escape(self.patient_name), "Other Example")
        return httpx.Response(200, stream=httpx.ByteStream(envelope(operation, rows, security=SECURITY)),
            headers={"Content-Type": "text/xml; charset=utf-8"})


@pytest.fixture
def tebra_case(signed_workspace, session, monkeypatch):
    f = signed_workspace
    monkeypatch.setattr(f.configuration, "workspace_ehr_read_enabled", True)
    monkeypatch.setattr(provider_team, "runtime_settings", f.configuration)
    scope = TebraWorkspaceScope(UUID(f.box), UUID(f.actor), uuid4(), uuid4(), 900, 901,
        "Invented Tebra Clinic", "America/New_York")
    binding = EhrReadBinding(box_id=f.box, owner_id=f.actor, account_id=f.binding.id, vendor="tebra",
        connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
        customer_id="900", practice_id="901", practice_name=scope.practice_name, practice_timezone=scope.timezone,
        environment="synthetic", binding_digest=scope.commitment(), state="active")
    session.add(binding)
    session.commit()
    provider = InventedTebra(session)
    port = SyntheticTebraReads((scope,), httpx.MockTransport(provider), enabled=lambda: f.configuration.workspace_ehr_read_available)
    monkeypatch.setattr(api_module.app.state, "ehr_reads", port, raising=False)
    fresh_sessions = request_sessions(session)
    def request_session():
        for owned in fresh_sessions():
            provider.session = owned
            try:
                yield owned
            finally:
                provider.session = session
    overrides = api_module.app.dependency_overrides
    previous_session = overrides[api_module.get_session]
    overrides[api_module.get_session] = request_session
    monkeypatch.setattr(f.client, "request", isolate_http_request(f.client, session))
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = SimpleNamespace(client=f.client, token=f.token, workspace=f.workspace, box=f.box, owner=f.actor,
        account=f.binding.id, configuration=f.configuration, binding=binding, binding_id=binding.id, scope=scope,
        port=port, provider=provider, s=session, starts_at=start, ends_at=start+timedelta(days=1),
        patient_query={"last_name": "Example", "birth_date": "1980-01-02"}, patient_name=provider.patient_name)
    result.headers = lambda: {"Authorization": "Bearer " + f.token(), "X-Cosmas-Ehr-Read": "1"}
    try:
        with ehr.install_runtime_reader(lambda: port):
            yield result
    finally:
        overrides[api_module.get_session] = previous_session


def action(f, body):
    return f.client.post("/connections/ehr/reads", headers=f.headers(), json=body)


def observe_body(f, key="tebra-observe-1"):
    return dict(action="observe", provider="tebra", connection_id=str(f.scope.connection_id),
        binding_sha256=f.scope.commitment(), starts_at=f.starts_at.isoformat(), ends_at=f.ends_at.isoformat(), idempotency_key=key)


def observed(f, key="tebra-observe-1"):
    response = action(f, observe_body(f, key))
    assert response.status_code == 200, response.text
    return response.json()


def verify_body(f, receipt, key="tebra-verify-1"):
    item = receipt["observation"]["items"][0]
    return dict(action="verify", provider="tebra", connection_id=str(f.scope.connection_id),
        binding_sha256=f.scope.commitment(), observation_id=receipt["observation_id"], observation_sha256=receipt["source_sha256"],
        item_handle=item["handle"], item_sha256=item["sha256"], idempotency_key=key, **f.patient_query)


def verified(f, receipt=None, key="tebra-verify-1"):
    response = action(f, verify_body(f, receipt or observed(f), key))
    assert response.status_code == 200, response.text
    return response.json()


def review_body(f, receipt, key="tebra-review-1"):
    item = receipt["observation"]["item"]
    return dict(provider="tebra", expected_revision=f.workspace["revision"], idempotency_key=key,
        observation_id=receipt["observation_id"], observation_sha256=receipt["source_sha256"],
        item_handle=item["handle"], item_sha256=item["sha256"], reviewed_visit=True,
        reviewed_patient_identity=True, reviewed_exact_snapshot=True, reviewed_untrusted_source=True)


def review(f, receipt, key="tebra-review-1"):
    return f.client.post(f"/workspaces/{f.workspace['id']}/ehr-read/review", headers=f.headers(), json=review_body(f, receipt, key))


def revoke(f):
    f.s.execute(text("UPDATE ehr_read_bindings SET state='revoked', revoked_at=clock_timestamp() WHERE id=:id"), {"id": f.binding_id})
    f.s.commit()


def test_signed_tebra_observe_verify_review_and_exact_recovery(tebra_case):
    f = tebra_case
    status = action(f, {"action": "status", "provider": "tebra"}).json()
    assert status["status"] == "ready" and status["installation"] is None and status["transport"] == "mock"
    assert not f.provider.calls
    window = observed(f)
    assert window["observation"]["coverage"] == "returned_rows_only"
    assert "patient" not in window["observation"]["items"][0]
    receipt = verified(f, window)
    assert receipt["observation"]["item"]["patient"] == {"full_name": f.patient_name, "birth_date": "1980-01-02"}
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    entry = next(e for e in saved.json()["workspace"]["entries"] if e["id"] == saved.json()["entry_id"])
    assert entry["source_label"] == "Tebra: reviewed appointment"
    assert "not a complete schedule" in entry["content"]
    assert f.provider.calls == ["GetPractices", "GetAppointments", "GetPatients", "GetAppointments"]
    for command in ({"action": "inspect", "observation_id": receipt["observation_id"]},
                    {"action": "resolve", "idempotency_key": "tebra-verify-1"}):
        recovered = action(f, {**command, "provider": "tebra"})
        assert recovered.status_code == 200 and recovered.json() == receipt
        assert action(f, {**command, "provider": "elation"}).status_code in (404, 409)
    assert review(f, receipt).json()["entry_id"] == saved.json()["entry_id"]
    assert len(f.provider.calls) == 4
    assert f.s.scalar(select(func.count()).select_from(EhrReadRequest).where(EhrReadRequest.account_id == f.account)) == 2


@pytest.mark.parametrize("change", ["patient", "appointment", "naive"])
def test_no_substituted_patient_or_changed_appointment_can_be_reviewed(tebra_case, change):
    f = tebra_case
    window = observed(f)
    if change == "patient":
        f.provider.patient_id = 999
    elif change == "appointment":
        f.provider.status = "Confirmed"
    else:
        f.provider.naive = True
    failed = action(f, verify_body(f, window))
    assert failed.status_code == (409 if change == "appointment" else 503), failed.text
    calls = len(f.provider.calls)
    assert action(f, {"action": "resolve", "provider": "tebra", "idempotency_key": "tebra-verify-1"}).json()["status"] == "unconfirmed"
    assert action(f, verify_body(f, window)).status_code == 503
    assert len(f.provider.calls) == calls


def test_demographic_candidates_never_replace_the_appointment_patient(tebra_case):
    f = tebra_case
    f.provider.extra_patient = True
    receipt = verified(f)
    assert receipt["observation"]["item"]["patient"]["full_name"] == f.patient_name
    assert "Other" not in str(receipt)


def test_exact_query_hash_and_explicit_provider_are_required(tebra_case):
    f = tebra_case
    window = observed(f)
    body = verify_body(f, window)
    for bad in ({k: v for k, v in body.items() if k != "provider"}, {**body, "birth_date": "19800102"}):
        assert action(f, bad).status_code == 422
    assert len(f.provider.calls) == 2
    verified(f, window)
    assert action(f, {**body, "last_name": "Different"}).status_code == 409
    stored = f.s.scalar(select(EhrReadRequest).where(EhrReadRequest.idempotency_key == body["idempotency_key"]))
    assert stored.request_hash == payload_hash(body)


def test_revocation_withholds_recovered_patient_and_saved_source(tebra_case):
    f = tebra_case
    receipt = verified(f)
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    revoke(f)
    assert action(f, {"action": "inspect", "provider": "tebra", "observation_id": receipt["observation_id"]}).status_code == 409
    replay = review(f, receipt)
    assert replay.status_code == 200 and replay.json()["source_withheld"]
    entry = next(e for e in replay.json()["workspace"]["entries"] if e["id"] == saved.json()["entry_id"])
    assert entry["content"] == "" and entry["ehr_source_state"] == "unavailable"
    assert len(f.provider.calls) == 4


def test_large_window_requires_resolved_new_narrower_intent(tebra_case):
    f = tebra_case
    f.provider.row_count = 26
    failed = action(f, observe_body(f))
    assert failed.status_code == 503 and failed.json()["detail"] == "ehr_read_too_many_results"
    assert action(f, {"action": "resolve", "provider": "tebra", "idempotency_key": "tebra-observe-1"}).json()["status"] == "unconfirmed"
    assert len(f.provider.calls) == 2
    f.provider.row_count = 1
    body = observe_body(f, "tebra-narrowed-1")
    body["ends_at"] = (f.starts_at + timedelta(hours=2)).isoformat()
    assert action(f, body).status_code == 200
    assert len(f.provider.calls) == 4
    assert action(f, {"action": "resolve", "provider": "tebra", "idempotency_key": "tebra-observe-1"}).json()["detail"] == "ehr_read_superseded"


def test_both_providers_coexist_but_keys_and_recovery_never_cross(tebra_case, monkeypatch):
    f = tebra_case
    scope = ElationReadScope(UUID(f.box), UUID(f.owner), uuid4(), uuid4(), 700, "Invented Other EHR")
    binding = EhrReadBinding(box_id=f.box, owner_id=f.owner, account_id=f.account, vendor="elation",
        connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
        practice_id="700", practice_name=scope.practice_name, binding_digest=scope.commitment())
    f.s.add(binding)
    f.s.commit()
    elation = SyntheticElationReads((scope,), httpx.MockTransport(lambda _: pytest.fail("wrong provider must do no IO")), enabled=lambda: True)
    registry = EhrReadRuntimes(elation=elation, tebra=f.port)
    monkeypatch.setattr(api_module.app.state, "ehr_reads", registry)
    with ehr.install_runtime_reader(lambda: registry):
        assert action(f, {"action": "status"}).json()["status"] == "ready"
        assert action(f, {"action": "status", "provider": "tebra"}).json()["status"] == "ready"
        receipt = verified(f)
        for body in ({"action": "resolve", "idempotency_key": "tebra-verify-1"},
                     {"action": "inspect", "observation_id": receipt["observation_id"]}):
            wrong = action(f, body)
            assert wrong.status_code == 409 and wrong.json()["detail"] == "ehr_read_provider_mismatch"
        body = observe_body(f, "tebra-observe-1")
        body.update(provider="elation", connection_id=str(scope.connection_id), binding_sha256=scope.commitment())
        assert action(f, body).status_code == 409
        body = review_body(f, receipt)
        body.pop("provider")
        assert f.client.post(f"/workspaces/{f.workspace['id']}/ehr-read/review", headers=f.headers(), json=body).status_code == 409
        assert review(f, receipt).status_code == 200
    assert len(f.provider.calls) == 4


@pytest.mark.parametrize("mutation", ["provider", "physician", "patient_shape", "birth_date", "coverage", "transport", "status"])
def test_sql_payload_guard_rejects_provider_shape_and_provenance_substitution(tebra_case, mutation):
    f = tebra_case
    receipt = verified(f)
    snap = f.s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == receipt["observation_id"]))
    payload = deepcopy(snap.payload)
    def valid(value):
        return f.s.scalar(text("SELECT public.ehr_read_payload_valid(CAST(:payload AS jsonb), r) FROM ehr_read_requests r WHERE r.id=:id"),
            {"payload": json.dumps(value), "id": receipt["observation_id"]})
    assert valid(payload) is True
    if mutation == "provider":
        payload["public"]["provider"] = "elation"
    elif mutation == "physician":
        payload["private"]["items"][0]["appointment"]["physician_id"] = "123"
    elif mutation == "patient_shape":
        payload["private"]["items"][0]["patient"]["first_name"] = "Alex"
    elif mutation == "birth_date":
        payload["private"]["items"][0]["patient"]["birth_date"] = "1981-01-02"
    elif mutation == "coverage":
        payload["public"]["coverage"] = "end_of_results"
    elif mutation == "transport":
        payload["private"]["transport"] = "vendor_sandbox"
    else:
        payload["private"]["items"][0]["appointment"]["status"] = None
    assert valid(payload) is False


def test_legacy_elation_wire_source_and_request_hash_stay_exact(ehr_case):
    from tests.integration.test_ehr_reads import observed as elation_observed
    from tests.integration.test_ehr_reads import review as elation_review
    from tests.integration.test_ehr_reads import review_body as elation_review_body
    from tests.integration.test_ehr_reads import verified as elation_verified
    f = ehr_case
    window = elation_observed(f)
    receipt = elation_verified(f, window)
    assert set(receipt) == {"contract_version", "observation_id", "observation_key", "transport", "connection_id", "binding_sha256", "source_sha256", "payload_sha256", "observation"}
    read = f.s.get(EhrReadRequest, receipt["observation_id"])
    assert "provider" not in read.request_json and read.request_hash == payload_hash(read.request_json)
    result = elation_review(f, receipt)
    assert result.status_code == 200, result.text
    saved = result.json()
    assert set(saved) == {"entry_id", "entry_revision", "workspace", "transport", "source", "request_sha256", "source_withheld"}
    assert saved["request_sha256"] == payload_hash({"workspace_id": f.workspace["id"], **elation_review_body(f, receipt)})
    item, observation = receipt["observation"]["item"], receipt["observation"]
    expected = ("Elation selected visit (synthetic frozen observation)\nPractice: Invented Elation Clinic\nPatient: Alex Example\nBirth date: 1980-01-02\n"
        f"Starts: {item['starts_at']}\nEnds: {item['ends_at']}\nAppointment status: Confirmed\nObserved: {observation['observed_at']}\n"
        "Coverage: Showing the returned page.\n\nThis reviewed snapshot does not book or update the EHR.")
    entry = next(e for e in saved["workspace"]["entries"] if e["id"] == saved["entry_id"])
    assert entry["content"] == expected and entry["source_label"] == "Elation: reviewed appointment"


def test_managed_elation_install_and_rotation_preserve_tebra_saved_source(sandbox, monkeypatch):
    f = sandbox
    scope = TebraWorkspaceScope(UUID(f.box), UUID(f.owner), uuid4(), uuid4(), 900, 901, "Invented Tebra Clinic", "UTC")
    binding = EhrReadBinding(box_id=f.box, owner_id=f.owner, account_id=f.account, vendor="tebra",
        connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation), customer_id="900",
        practice_id="901", practice_name=scope.practice_name, practice_timezone="UTC", environment="synthetic", binding_digest=scope.commitment())
    f.s.add(binding)
    f.s.commit()
    provider = InventedTebra(f.s)
    def dispatch(request):
        provider.session = f.provider.session
        return provider(request)
    tebra = SyntheticTebraReads((scope,), httpx.MockTransport(dispatch), enabled=lambda: True)
    ft = SimpleNamespace(**vars(f))
    ft.scope, ft.binding_id, ft.provider, ft.port = scope, binding.id, provider, tebra
    ft.patient_query = {"last_name": "Example", "birth_date": "1980-01-02"}
    registry = EhrReadRuntimes(elation=f.port, tebra=tebra)
    monkeypatch.setattr(api_module.app.state, "ehr_reads", registry)
    with ehr.install_runtime_reader(lambda: registry):
        receipt = verified(ft)
        saved = review(ft, receipt)
        assert saved.status_code == 200, saved.text
        first = installed(f)
        old = f.profile.elation_sandbox[0]
        updated = replace(old, id=uuid4(), scope=replace(old.scope, credential_generation=uuid4(), connection_id=uuid4()))
        async def never_credentials(_):
            pytest.fail("Installation does no provider IO")
        rotated = ManagedElationSandboxReads((updated,), credentials=never_credentials,
            credentials_current=lambda _: True, sessions=sessionmaker(bind=f.engine), enabled=lambda: True,
            transport_factory=lambda: pytest.fail("Installation does no provider IO"))
        registry = EhrReadRuntimes(elation=rotated, tebra=tebra)
        monkeypatch.setattr(api_module.app.state, "ehr_reads", registry)
        f.profile = replace(f.profile, elation_sandbox=(updated,))
        second = action(f, install_body(f, "install-rotated-2"))
        assert second.status_code == 200 and second.json()["status"] == "installed", second.text
        f.s.expire_all()
        assert f.s.get(EhrReadBinding, binding.id).state == "active"
        previous = f.s.scalar(select(EhrReadBinding).where(EhrReadBinding.connection_id == first["connection_id"]))
        assert previous.state == "revoked"
        recovered = review(ft, receipt)
        assert recovered.status_code == 200 and recovered.json()["source_withheld"] is False
        assert action(ft, {"action": "inspect", "provider": "tebra", "observation_id": receipt["observation_id"]}).status_code == 200
        rotated.close()
    assert provider.calls == ["GetPractices", "GetAppointments", "GetPatients", "GetAppointments"] and not f.provider.calls


def test_database_cannot_install_tebra_as_managed_elation(tebra_case):
    f = tebra_case
    body = dict(action="install", installation_id=str(uuid4()), installation_sha256="a"*64, idempotency_key="invalid-tebra-install")
    with pytest.raises(IntegrityError, match="Sandbox installation authority"), f.s.begin_nested():
        f.s.add(ElationSandboxInstallationReceipt(box_id=f.box, owner_id=f.owner, account_id=f.account,
            binding_id=f.binding_id, installation_id=body["installation_id"], installation_sha256=body["installation_sha256"],
            idempotency_key=body["idempotency_key"], request_sha256=payload_hash(body)))
        f.s.flush()
    f.s.rollback()
    assert not f.provider.calls
