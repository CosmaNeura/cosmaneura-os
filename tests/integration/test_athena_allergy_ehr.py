"""Signed, invented Athena allergy selection, exact review and custody boundaries."""

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
from tests.unit.test_athena_allergy_read import PATIENT, SECTION

from cosmas_os.adapters.athena_allergy_read_runtime import (
    AthenaAllergyConnectionScope,
    AthenaAuthorizedPatient,
    SyntheticAthenaAllergyReads,
)
from cosmas_os.adapters.ehr_read_runtime import EhrReadRuntimes
from cosmas_os.api import app as api_module
from cosmas_os.application import athena_allergy_ehr as clinical
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application import provider_team
from cosmas_os.application import services as svc
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import (
    EhrAthenaCorePatientGrant,
    EhrReadBinding,
    EhrReadRequest,
    EhrReadSnapshot,
)
from cosmas_os.models import EncounterWorkspace, ExternalIdentity

signed_workspace = _signed_workspace


class InventedAthena:
    def __init__(self, session=None):
        self.session, self.calls = session, []
        self.fail = False
        self.after = lambda: None
        self.patient, self.section = deepcopy(PATIENT), deepcopy(SECTION)

    def __call__(self, request):
        if self.session is not None:
            assert not self.session.in_transaction(), "No SQL transaction may cross provider I/O"
        assert request.method == "GET" and request.url.host == "api.preview.platform.athenahealth.com"
        self.calls.append(str(request.url))
        self.after()
        if self.fail:
            raise httpx.ReadTimeout("invented provider failure", request=request)
        if request.url.path == "/v1/901/patients/903":
            assert dict(request.url.params) == {"departmentid": "902"}
            body = [self.patient]
        else:
            assert request.url.path == "/v1/901/chart/903/allergies"
            assert dict(request.url.params) == {"departmentid": "902", "showinactive": "true"}
            body = self.section
        return httpx.Response(200, headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(json.dumps(body).encode()))


def install_grant(s, box, owner, account, workspace_id, patient_link_id):
    scope = AthenaAllergyConnectionScope(UUID(box), UUID(owner), UUID(account), uuid4(), uuid4(), "901", "Invented Athena Clinical")
    binding = EhrReadBinding(box_id=box, owner_id=owner, account_id=account, vendor="athena", protocol="core",
        connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
        practice_id=scope.practice_id, practice_name=scope.practice_label, environment=scope.environment, binding_digest=scope.commitment(), state="active")
    s.add(binding)
    s.flush()
    authorized = AthenaAuthorizedPatient(uuid4(), scope, UUID(workspace_id), UUID(patient_link_id), "902", "Invented chart department", PATIENT["patientid"],
        "a"*64, canonical_json(PATIENT), payload_hash(PATIENT))
    grant = EhrAthenaCorePatientGrant(id=str(authorized.grant_id), box_id=box, owner_id=owner, account_id=account,
        binding_id=binding.id, workspace_id=workspace_id, patient_link_id=patient_link_id, patient_id=authorized.patient_id, department_id=authorized.department_id, department_label=authorized.department_label,
        authorization_sha256=authorized.authorization_sha256, identity_json=authorized.identity_json,
        identity_sha256=authorized.identity_sha256, grant_digest=authorized.commitment(), state="active")
    s.add(grant)
    s.commit()
    return scope, binding, grant, authorized


@pytest.fixture
def athena_allergy_case(signed_workspace, session, monkeypatch):
    f = signed_workspace
    monkeypatch.setattr(f.configuration, "workspace_ehr_read_enabled", True)
    monkeypatch.setattr(f.configuration, "workspace_athena_allergies_enabled", True)
    monkeypatch.setattr(provider_team, "runtime_settings", f.configuration)
    workspace = session.get(EncounterWorkspace, f.workspace["id"])
    assert workspace is not None and workspace.patient_link_id is not None
    scope, binding, grant, authorized = install_grant(session, f.box, f.actor, f.binding.id, workspace.id, workspace.patient_link_id)
    provider = InventedAthena(session)
    # Host flag withdrawal is independently checked by the application boundary.
    port = SyntheticAthenaAllergyReads((scope,), (authorized,), httpx.MockTransport(provider), enabled=lambda: True)
    runtimes = EhrReadRuntimes(athena_core=port)
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
    response = action(f, {"action": "status", "provider": "athena", "protocol": "core"})
    assert response.status_code == 200, response.text
    return response.json()


def patients(f, key="athena-core-patients-1"):
    response = action(f, dict(action="core_patients", provider="athena", protocol="core", connection_id=str(f.scope.connection_id),
        binding_sha256=f.scope.commitment(), workspace_id=f.workspace["id"], idempotency_key=key))
    assert response.status_code == 200, response.text
    return response.json()


def allergy_body(f, root, key="athena-core-allergies-1"):
    item = root["observation"]["items"][0]
    return dict(action="core_allergies", provider="athena", protocol="core", connection_id=str(f.scope.connection_id),
        binding_sha256=f.scope.commitment(), workspace_id=f.workspace["id"], idempotency_key=key,
        observation_id=root["observation_id"], observation_sha256=root["source_sha256"], item_handle=item["handle"], item_sha256=item["sha256"])


def allergies(f, root=None, key="athena-core-allergies-1"):
    response = action(f, allergy_body(f, root or patients(f), key))
    assert response.status_code == 200, response.text
    return response.json()


def review_body(f, receipt, key="athena-core-review-1"):
    item = receipt["observation"]["item"]
    return dict(provider="athena", protocol="core", expected_revision=f.workspace["revision"], idempotency_key=key,
        observation_id=receipt["observation_id"], observation_sha256=receipt["source_sha256"], item_handle=item["handle"], item_sha256=item["sha256"],
        reviewed_patient_identity=True, reviewed_exact_snapshot=True, reviewed_untrusted_source=True)


def review(f, receipt, key="athena-core-review-1"):
    return f.client.post(f"/workspaces/{f.workspace['id']}/ehr-read/review", headers=f.headers(), json=review_body(f, receipt, key))


def revoke(f):
    f.s.execute(text("UPDATE ehr_athena_core_patient_grants SET state='revoked', revoked_at=clock_timestamp() WHERE id=:id"), {"id": f.grant_id})
    f.s.commit()


def test_signed_selection_read_review_and_recovery_use_exact_proof(athena_allergy_case):
    f = athena_allergy_case
    assert status(f) == dict(contract_version=1, provider="athena", protocol="core", mode="synthetic", transport="mock", status="ready",
        connection_id=str(f.scope.connection_id), binding_sha256=f.scope.commitment(), practice_label=f.scope.practice_label)
    root = patients(f)
    assert root["observation"]["coverage"] == "authorized_candidates_only" and not f.provider.calls
    candidate = root["observation"]["items"][0]
    assert candidate["department_label"] == "Invented chart department"
    identity = json.loads(candidate["patient_identity_json"])
    assert identity["lastname"] == "Éxample" and "patientid" not in identity and "departmentid" not in identity
    receipt = allergies(f, root)
    item = receipt["observation"]["item"]
    assert item["handle"] == candidate["handle"]
    assert json.loads(item["section_json"]) == f.provider.section
    assert '123456789012345678' in item["section_json"]
    assert item["includes_inactive"] is True and item["coverage"] == "returned_section_only"
    assert len(f.provider.calls) == 2
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    entry = next(e for e in saved.json()["workspace"]["entries"] if e["id"] == saved.json()["entry_id"])
    assert entry["content"] == item["source_content"] and entry["source_label"] == "Athena: reviewed allergy records"
    for command in ({"action": "inspect", "observation_id": receipt["observation_id"]}, {"action": "resolve", "idempotency_key": "athena-core-allergies-1"}):
        recovered = action(f, {**command, "provider": "athena", "protocol": "core"})
        assert recovered.status_code == 200 and recovered.json() == receipt
    assert allergies(f, root) == receipt
    assert review(f, receipt).json()["entry_id"] == saved.json()["entry_id"]
    assert len(f.provider.calls) == 2
    assert f.s.scalar(select(func.count()).select_from(EhrReadRequest).where(EhrReadRequest.account_id == f.account)) == 2


def test_unknown_and_failed_reads_recover_with_explicit_protocol(athena_allergy_case):
    f = athena_allergy_case
    missing = action(f, dict(action="resolve", provider="athena", protocol="core", idempotency_key="unknown-core-key"))
    assert missing.status_code == 200 and missing.json() == dict(status="not_found", provider="athena", protocol="core", observation_id=None, observation_key="unknown-core-key")
    root = patients(f)
    f.provider.fail = True
    failed = action(f, allergy_body(f, root))
    assert failed.status_code == 503
    recovered = action(f, dict(action="resolve", provider="athena", protocol="core", idempotency_key="athena-core-allergies-1"))
    assert recovered.status_code == 200 and recovered.json()["status"] == "unconfirmed"
    assert recovered.json()["provider"] == "athena" and recovered.json()["protocol"] == "core"
    assert action(f, allergy_body(f, root)).status_code == 503
    assert len(f.provider.calls) == 1


@pytest.mark.parametrize("change", ["omit", "null", "fhir", "elation"])
def test_protocol_never_falls_back_or_crosses_provider(athena_allergy_case, change):
    f = athena_allergy_case
    root = patients(f)
    body = allergy_body(f, root)
    if change == "omit":
        body.pop("protocol")
    elif change == "elation":
        body["provider"] = "elation"
    else:
        body = {**body, "protocol": None if change == "null" else "fhir"}
    assert action(f, body).status_code == 422
    assert not f.provider.calls
    assert action(f, dict(action="inspect", provider="athena", observation_id=root["observation_id"])).status_code == 422


@pytest.mark.parametrize("change", ["identity", "patient", "source_size"])
def test_identity_cross_patient_and_oversized_packet_withhold_entire_read(athena_allergy_case, change):
    f = athena_allergy_case
    root = patients(f)
    if change == "identity":
        f.provider.patient["dob"] = "01/02/1981"
    elif change == "patient":
        f.provider.patient["patientid"] = "904"
    else:
        f.provider.section["sectionnote"] = "x" * 4000
    assert action(f, allergy_body(f, root)).status_code == 503
    assert len(f.provider.calls) == (2 if change == "source_size" else 1)
    assert f.s.scalar(select(func.count()).select_from(EhrReadSnapshot).join(EhrReadRequest, EhrReadRequest.id == EhrReadSnapshot.observation_id)
        .where(EhrReadRequest.account_id == f.account, EhrReadRequest.kind == "core_allergies")) == 0


@pytest.mark.parametrize("change", ["grant", "host"])
def test_revocation_or_host_disable_withholds_saved_source(athena_allergy_case, change, monkeypatch):
    f = athena_allergy_case
    receipt = allergies(f)
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    if change == "grant":
        revoke(f)
    else:
        monkeypatch.setattr(f.configuration, "workspace_athena_allergies_enabled", False)
    response = f.client.get(f"/workspaces/{f.workspace['id']}", headers={"Authorization": "Bearer " + f.token()})
    assert response.status_code == 200, response.text
    entry = next(e for e in response.json()["entries"] if e["id"] == saved.json()["entry_id"])
    assert entry["content"] == "" and entry["ehr_source_state"] == "unavailable"
    assert len(f.provider.calls) == 2


def test_grant_is_immutable_and_current_lookup_fences_concurrent_revocation(engine):
    # Separate committed connections are required; signed fixtures have an outer rollback transaction.
    with Session(engine) as setup:
        seeded = svc.provision_box(svc.Container(setup), "Invented Athena lock clinic")
    with Session(engine) as setup:
        box, owner, workspace, link = prepare(setup, seeded)
        account = ExternalIdentity(box_id=box, principal_id=owner, issuer="https://clerk-"+str(uuid4())+".example.invalid",
            subject="invented", organization_id="org_invented", reviewed_by="Invented", evidence_ref="invented:athena-lock")
        setup.add(account)
        setup.flush()
        _, _, grant, _ = install_grant(setup, box, owner, account.id, workspace["id"], link)
        grant_id = grant.id
        setup.commit()
    with Session(engine) as reader, Session(engine) as writer:
        clinical.grant(reader, grant_id, current=True)
        writer.execute(text("SET LOCAL lock_timeout='150ms'"))
        with pytest.raises(DBAPIError) as caught:
            writer.execute(text("UPDATE ehr_athena_core_patient_grants SET state='revoked', revoked_at=clock_timestamp() WHERE id=:id"), {"id": grant_id})
        assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
        writer.rollback()
        reader.commit()
        with pytest.raises(IntegrityError):
            writer.execute(text("UPDATE ehr_athena_core_patient_grants SET department_id='999' WHERE id=:id"), {"id": grant_id})
        writer.rollback()
        writer.execute(text("UPDATE ehr_athena_core_patient_grants SET state='revoked', revoked_at=clock_timestamp() WHERE id=:id"), {"id": grant_id})
        writer.commit()
        assert reader.scalar(text("SELECT public.ehr_athena_grant_current(:id)"), {"id": grant_id}) is False
        with pytest.raises(Exception, match="ehr_read_core_grant_changed"):
            clinical.grant(reader, grant_id, current=True)
