"""Signed, invented Tebra FHIR selection, exact review and custody boundaries."""

import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from tests.integration.test_handoff_review import isolate_http_request, request_sessions
from tests.integration.test_note_review import prepare
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.adapters.ehr_read_runtime import EhrReadRuntimes
from cosmas_os.adapters.tebra_fhir_read import FHIR_BASE
from cosmas_os.adapters.tebra_fhir_read_runtime import (
    SyntheticTebraFhirReads,
    TebraFhirAuthorizedPatient,
    TebraFhirConnectionScope,
)
from cosmas_os.api import app as api_module
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application import provider_team
from cosmas_os.application import services as svc
from cosmas_os.application import tebra_fhir_ehr as clinical
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import (
    EhrFhirPatientGrant,
    EhrReadBinding,
    EhrReadRequest,
    EhrReadSnapshot,
)
from cosmas_os.models import EncounterWorkspace, ExternalIdentity

signed_workspace = _signed_workspace
PATIENT = {"resourceType": "Patient", "id": "fhir-patient-A", "name": [{"given": ["Alex"], "family": "Éxample"}], "birthDate": "1980-01-02"}


class InventedFhir:
    def __init__(self, session):
        self.session, self.calls = session, []
        self.fail = False
        self.after = lambda: None
        self.patient = deepcopy(PATIENT)
        self.row = {"resourceType": "MedicationRequest", "id": "record-A", "subject": {"reference": "Patient/fhir-patient-A"},
            "status": "stopped", "intent": "plan", "authoredOn": "2025-01", "doNotPerform": True, "reportedBoolean": False,
            "medicationCodeableConcept": {"text": "Invented medication"},
            "dosageInstruction": [{"text": "Prendre la dose enregistrée.\r\n\tOriginal instruction remains unconfirmed.",
                "asNeededBoolean": False, "timing": {"repeat": {"period": 1.0, "periodUnit": "d"}},
                "doseAndRate": [{"doseQuantity": {"value": 0.5, "unit": "invented unit"}}]}],
            "note": [{"text": "Original qualifier; do not infer current use."}]}
        self.medication = {"resourceType": "Medication", "id": "med-A", "code": {"text": "Invented resolved medication"}}

    def __call__(self, request):
        assert not self.session.in_transaction(), "No SQL transaction may cross provider I/O"
        assert request.method == "GET" and request.url.host == "fhir.prd.cloud.tebra.com"
        self.calls.append(str(request.url))
        self.after()
        if self.fail:
            raise httpx.ReadTimeout("invented provider failure", request=request)
        if request.url.path == "/fhir-request/Patient/fhir-patient-A":
            body = self.patient
        elif request.url.path == "/fhir-request/MedicationRequest":
            body = {"resourceType": "Bundle", "type": "searchset", "total": 1,
                "link": [{"relation": "self", "url": str(request.url)}],
                "entry": [{"fullUrl": FHIR_BASE+"/MedicationRequest/record-A", "resource": self.row, "search": {"mode": "match"}}]}
        else:
            assert request.url.path == "/fhir-request/Medication/med-A"
            body = self.medication
        return httpx.Response(200, headers={"Content-Type": "application/fhir+json"},
            stream=httpx.ByteStream(json.dumps(body).encode()))


def install_grant(s, box, owner, account, workspace_id, patient_link_id):
    scope = TebraFhirConnectionScope(UUID(box), UUID(owner), UUID(account), uuid4(), uuid4(), "Invented Tebra Clinical")
    binding = EhrReadBinding(box_id=box, owner_id=owner, account_id=account, vendor="tebra", protocol="fhir",
        connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
        practice_id=None, practice_name=scope.display_label, environment="synthetic", binding_digest=scope.commitment(), state="active")
    s.add(binding)
    s.flush()
    authorized = TebraFhirAuthorizedPatient(uuid4(), scope, UUID(workspace_id), UUID(patient_link_id), PATIENT["id"],
        "a"*64, canonical_json(PATIENT), payload_hash(PATIENT))
    grant = EhrFhirPatientGrant(id=str(authorized.grant_id), box_id=box, owner_id=owner, account_id=account,
        binding_id=binding.id, workspace_id=workspace_id, patient_link_id=patient_link_id, fhir_patient_id=authorized.fhir_patient_id,
        authorization_sha256=authorized.authorization_sha256, identity_json=authorized.identity_json,
        identity_sha256=authorized.identity_sha256, grant_digest=authorized.commitment(), state="active")
    s.add(grant)
    s.commit()
    return scope, binding, grant, authorized


@pytest.fixture
def tebra_fhir_case(signed_workspace, session, monkeypatch):
    f = signed_workspace
    monkeypatch.setattr(f.configuration, "workspace_ehr_read_enabled", True)
    monkeypatch.setattr(f.configuration, "workspace_tebra_fhir_enabled", True)
    monkeypatch.setattr(provider_team, "runtime_settings", f.configuration)
    workspace = session.get(EncounterWorkspace, f.workspace["id"])
    assert workspace is not None and workspace.patient_link_id is not None
    scope, binding, grant, authorized = install_grant(session, f.box, f.actor, f.binding.id, workspace.id, workspace.patient_link_id)
    provider = InventedFhir(session)
    # Host flag withdrawal is independently checked by the application boundary.
    port = SyntheticTebraFhirReads((scope,), (authorized,), httpx.MockTransport(provider), enabled=lambda: True)
    runtimes = EhrReadRuntimes(tebra_fhir=port)
    monkeypatch.setattr(api_module.app.state, "ehr_reads", runtimes, raising=False)
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
    result = SimpleNamespace(client=f.client, token=f.token, workspace=f.workspace, box=f.box, owner=f.actor,
        account=f.binding.id, configuration=f.configuration, binding=binding, binding_id=binding.id, scope=scope,
        port=port, runtimes=runtimes, provider=provider, s=session, grant=grant, grant_id=grant.id,
        authorized_patient=authorized, patient_name="Alex Éxample")
    result.headers = lambda: {"Authorization": "Bearer " + f.token(), "X-Cosmas-Ehr-Read": "1"}
    try:
        with ehr.install_runtime_reader(lambda: runtimes):
            yield result
    finally:
        overrides[api_module.get_session] = previous_session


def action(f, body):
    return f.client.post("/connections/ehr/reads", headers=f.headers(), json=body)


def status(f):
    response = action(f, {"action": "status", "provider": "tebra", "protocol": "fhir"})
    assert response.status_code == 200, response.text
    return response.json()


def patients(f, key="tebra-fhir-patients-1"):
    response = action(f, dict(action="fhir_patients", provider="tebra", protocol="fhir", connection_id=str(f.scope.connection_id),
        binding_sha256=f.scope.commitment(), workspace_id=f.workspace["id"], idempotency_key=key))
    assert response.status_code == 200, response.text
    return response.json()


def medication_body(f, root, key="tebra-fhir-medications-1"):
    item = root["observation"]["items"][0]
    return dict(action="fhir_medications", provider="tebra", protocol="fhir", connection_id=str(f.scope.connection_id),
        binding_sha256=f.scope.commitment(), workspace_id=f.workspace["id"], idempotency_key=key,
        observation_id=root["observation_id"], observation_sha256=root["source_sha256"], item_handle=item["handle"], item_sha256=item["sha256"])


def medications(f, root=None, key="tebra-fhir-medications-1"):
    response = action(f, medication_body(f, root or patients(f), key))
    assert response.status_code == 200, response.text
    return response.json()


def review_body(f, receipt, key="tebra-fhir-review-1"):
    item = receipt["observation"]["item"]
    return dict(provider="tebra", protocol="fhir", expected_revision=f.workspace["revision"], idempotency_key=key,
        observation_id=receipt["observation_id"], observation_sha256=receipt["source_sha256"], item_handle=item["handle"], item_sha256=item["sha256"],
        reviewed_patient_identity=True, reviewed_exact_snapshot=True, reviewed_untrusted_source=True)


def review(f, receipt, key="tebra-fhir-review-1"):
    return f.client.post(f"/workspaces/{f.workspace['id']}/ehr-read/review", headers=f.headers(), json=review_body(f, receipt, key))


def revoke(f):
    f.s.execute(text("UPDATE ehr_fhir_patient_grants SET state='revoked', revoked_at=clock_timestamp() WHERE id=:id"), {"id": f.grant_id})
    f.s.commit()


def test_signed_selection_read_review_and_recovery_use_exact_proof(tebra_fhir_case):
    f = tebra_fhir_case
    assert status(f) == dict(contract_version=1, provider="tebra", protocol="fhir", mode="synthetic", transport="mock", status="ready",
        connection_id=str(f.scope.connection_id), binding_sha256=f.scope.commitment(), display_label=f.scope.display_label)
    root = patients(f)
    assert root["observation"]["coverage"] == "authorized_candidates_only" and not f.provider.calls
    receipt = medications(f, root)
    item = receipt["observation"]["item"]
    assert item["handle"] == root["observation"]["items"][0]["handle"]
    assert '"period":1.0' in item["records"][0]["dosage_instructions_json"]
    assert '"value":0.5' in item["records"][0]["dosage_instructions_json"]
    assert 'enregistrée' in json.loads(item["records"][0]["dosage_instructions_json"])[0]["text"]
    assert len(f.provider.calls) == 2
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    entry = next(e for e in saved.json()["workspace"]["entries"] if e["id"] == saved.json()["entry_id"])
    assert entry["content"] == item["source_content"] and entry["source_label"] == "Tebra: reviewed medication records"
    for command in ({"action": "inspect", "observation_id": receipt["observation_id"]}, {"action": "resolve", "idempotency_key": "tebra-fhir-medications-1"}):
        recovered = action(f, {**command, "provider": "tebra", "protocol": "fhir"})
        assert recovered.status_code == 200 and recovered.json() == receipt
    assert medications(f, root) == receipt
    assert review(f, receipt).json()["entry_id"] == saved.json()["entry_id"]
    assert len(f.provider.calls) == 2
    assert f.s.scalar(select(func.count()).select_from(EhrReadRequest).where(EhrReadRequest.account_id == f.account)) == 2


def test_unknown_and_failed_reads_recover_with_explicit_protocol(tebra_fhir_case):
    f = tebra_fhir_case
    missing = action(f, dict(action="resolve", provider="tebra", protocol="fhir", idempotency_key="unknown-fhir-key"))
    assert missing.status_code == 200 and missing.json() == dict(status="not_found", provider="tebra", protocol="fhir", observation_id=None, observation_key="unknown-fhir-key")
    root = patients(f)
    f.provider.fail = True
    failed = action(f, medication_body(f, root))
    assert failed.status_code == 503
    recovered = action(f, dict(action="resolve", provider="tebra", protocol="fhir", idempotency_key="tebra-fhir-medications-1"))
    assert recovered.status_code == 200 and recovered.json()["status"] == "unconfirmed"
    assert recovered.json()["provider"] == "tebra" and recovered.json()["protocol"] == "fhir"
    assert action(f, medication_body(f, root)).status_code == 503
    assert len(f.provider.calls) == 1


@pytest.mark.parametrize("change", ["omit", "null", "soap", "elation"])
def test_protocol_never_falls_back_or_crosses_provider(tebra_fhir_case, change):
    f = tebra_fhir_case
    root = patients(f)
    body = medication_body(f, root)
    if change == "omit":
        body.pop("protocol")
    elif change == "elation":
        body["provider"] = "elation"
    else:
        body = {**body, "protocol": None if change == "null" else "soap"}
    assert action(f, body).status_code == 422
    assert not f.provider.calls
    assert action(f, dict(action="inspect", provider="tebra", observation_id=root["observation_id"])).status_code == 404


@pytest.mark.parametrize("change", ["identity", "subject", "source_size"])
def test_identity_cross_patient_and_oversized_packet_withhold_entire_read(tebra_fhir_case, change):
    f = tebra_fhir_case
    root = patients(f)
    if change == "identity":
        f.provider.patient["birthDate"] = "1981"
    elif change == "subject":
        f.provider.row["subject"] = {"reference": "Patient/unrelated-patient"}
    else:
        f.provider.row["note"] = [{"text": "Invented full qualifier " * 250}]
    assert action(f, medication_body(f, root)).status_code == 503
    assert len(f.provider.calls) == (1 if change == "identity" else 2)
    assert f.s.scalar(select(func.count()).select_from(EhrReadSnapshot).join(EhrReadRequest, EhrReadRequest.id == EhrReadSnapshot.observation_id)
        .where(EhrReadRequest.account_id == f.account, EhrReadRequest.kind == "fhir_medications")) == 0


@pytest.mark.parametrize("change", ["grant", "host"])
def test_revocation_or_host_disable_withholds_saved_source(tebra_fhir_case, change, monkeypatch):
    f = tebra_fhir_case
    receipt = medications(f)
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    if change == "grant":
        revoke(f)
    else:
        monkeypatch.setattr(f.configuration, "workspace_tebra_fhir_enabled", False)
    response = f.client.get(f"/workspaces/{f.workspace['id']}", headers={"Authorization": "Bearer " + f.token()})
    assert response.status_code == 200, response.text
    entry = next(e for e in response.json()["entries"] if e["id"] == saved.json()["entry_id"])
    assert entry["content"] == "" and entry["ehr_source_state"] == "unavailable"
    assert len(f.provider.calls) == 2


def test_grant_is_immutable_and_current_lookup_fences_concurrent_revocation(engine):
    # Separate committed connections are required; the signed fixture has an outer rollback transaction.
    with Session(engine) as setup:
        seeded = svc.provision_box(svc.Container(setup), "Invented FHIR lock clinic")
    with Session(engine) as setup:
        box, owner, workspace, link = prepare(setup, seeded)
        account = ExternalIdentity(box_id=box, principal_id=owner, issuer="https://clerk-"+str(uuid4())+".example.invalid",
            subject="invented", organization_id="org_invented", reviewed_by="Invented", evidence_ref="invented:fhir-lock")
        setup.add(account)
        setup.flush()
        _, _, grant, _ = install_grant(setup, box, owner, account.id, workspace["id"], link)
        grant_id = grant.id
        setup.commit()
    with Session(engine) as reader, Session(engine) as writer:
        clinical.grant(reader, grant_id, current=True)
        writer.execute(text("SET LOCAL lock_timeout='150ms'"))
        with pytest.raises(DBAPIError) as caught:
            writer.execute(text("UPDATE ehr_fhir_patient_grants SET state='revoked', revoked_at=clock_timestamp() WHERE id=:id"), {"id": grant_id})
        assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
        writer.rollback()
        reader.commit()
        with pytest.raises(IntegrityError):
            writer.execute(text("UPDATE ehr_fhir_patient_grants SET fhir_patient_id='substituted' WHERE id=:id"), {"id": grant_id})
        writer.rollback()
        writer.execute(text("UPDATE ehr_fhir_patient_grants SET state='revoked', revoked_at=clock_timestamp() WHERE id=:id"), {"id": grant_id})
        writer.commit()
        assert reader.scalar(text("SELECT public.ehr_fhir_grant_current(:id)"), {"id": grant_id}) is False
        with pytest.raises(Exception, match="ehr_read_fhir_grant_changed"):
            clinical.grant(reader, grant_id, current=True)
