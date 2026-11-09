"""C8: athena Preview FHIR wired into /connections/ehr/reads — mocks and flags only."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from tests.integration.test_handoff_review import isolate_http_request, request_sessions
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.adapters.athena_fhir_r4 import (
    ATHENA_FHIR_R4_BASE_URL,
    ATHENA_FHIR_SYSTEM_READ_SCOPES,
    ATHENA_FHIR_TOKEN_URL,
    ATHENA_PRACTICE_PARAM,
    ATHENA_PRACTICE_VALUE,
)
from cosmas_os.adapters.ehr_auth import (
    ATHENA_FHIR_CLIENT_ID_REF,
    ATHENA_FHIR_CLIENT_SECRET_REF,
    ClientCredentialsConfig,
    ClientCredentialsTokenClient,
    ManagedSecretEnvResolver,
)
from cosmas_os.adapters.ehr_fhir_vendor import ATHENA_FHIR_ENVIRONMENT
from cosmas_os.adapters.ehr_read_runtime import EhrReadRuntimes
from cosmas_os.adapters.tebra_fhir_read_runtime import (
    SyntheticTebraFhirReads,
    TebraFhirAuthorizedPatient,
    TebraFhirConnectionScope,
)
from cosmas_os.api import app as api_module
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application import provider_team
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import EhrFhirPatientGrant, EhrReadBinding, EhrReadRequest

signed_workspace = _signed_workspace
PATIENT = {
    "resourceType": "Patient",
    "id": "synth-athena-patient-A",
    "name": [{"given": ["Avery"], "family": "Northwind"}],
    "birthDate": "1988-04-12",
}
MED_REQUEST = {
    "resourceType": "MedicationRequest",
    "id": "synth-athena-medreq-A",
    "status": "active",
    "intent": "order",
    "authoredOn": "2026-09-01",
    "subject": {"reference": "Patient/synth-athena-patient-A"},
    "medicationCodeableConcept": {"text": "Invented lisinopril tablet"},
    "dosageInstruction": [{"text": "Take 1 tablet by mouth daily"}],
}
FAKE_CLIENT_ID = "fake-athena-fhir-c8-client-id-PLACEHOLDER"
FAKE_CLIENT_SECRET = "fake-athena-fhir-c8-client-secret-PLACEHOLDER"
CANARY_TOKEN = "CANARY_ATHENA_FHIR_C8_TOKEN_aa11bb22_NEVER_LOG"
CANARY_SECRET = "CANARY_ATHENA_FHIR_C8_SECRET_cc33dd44_NEVER_LOG"


class InventedAthenaFhir:
    """Mock token + Preview FHIR; counts auth/network before any refusal check fails."""

    def __init__(self, session):
        self.session = session
        self.token_calls = 0
        self.fhir_calls: list[str] = []
        self.fail = False
        self.patient = deepcopy(PATIENT)
        self.row = deepcopy(MED_REQUEST)
        self.access_token = CANARY_TOKEN
        self.granted_scope = " ".join(sorted(ATHENA_FHIR_SYSTEM_READ_SCOPES))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert not self.session.in_transaction(), "No SQL transaction may cross provider I/O"
        url = str(request.url)
        if request.method == "POST" and url.rstrip("/") == ATHENA_FHIR_TOKEN_URL:
            self.token_calls += 1
            return httpx.Response(
                200,
                json={
                    "access_token": self.access_token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": self.granted_scope,
                },
            )
        assert request.method == "GET"
        assert request.url.host == "api.preview.platform.athenahealth.com"
        self.fhir_calls.append(url)
        if self.fail:
            raise httpx.ReadTimeout("invented athena fhir failure", request=request)
        path = request.url.path
        if path.endswith(f"/Patient/{PATIENT['id']}"):
            body = self.patient
        elif path.endswith("/MedicationRequest"):
            raw = request.url.query
            if isinstance(raw, bytes):
                raw = raw.decode()
            assert f"{ATHENA_PRACTICE_PARAM}={ATHENA_PRACTICE_VALUE}" in raw.replace("%2F", "/")
            body = {
                "resourceType": "Bundle",
                "type": "searchset",
                "total": 1,
                "link": [{"relation": "self", "url": url}],
                "entry": [{
                    "fullUrl": f"{ATHENA_FHIR_R4_BASE_URL}/MedicationRequest/{self.row['id']}",
                    "resource": self.row,
                    "search": {"mode": "match"},
                }],
            }
        else:
            raise AssertionError(path)
        return httpx.Response(
            200,
            headers={"Content-Type": "application/fhir+json"},
            content=json.dumps(body).encode(),
        )


def install_grant(s, box, owner, account, workspace_id, patient_link_id):
    scope = TebraFhirConnectionScope(
        UUID(box), UUID(owner), UUID(account), uuid4(), uuid4(),
        "athena Preview 195900", vendor="athena",
    )
    binding = EhrReadBinding(
        box_id=box, owner_id=owner, account_id=account, vendor="athena", protocol="fhir",
        connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
        practice_id=None, practice_name=scope.display_label, environment=ATHENA_FHIR_ENVIRONMENT,
        binding_digest=scope.commitment(), state="active",
    )
    s.add(binding)
    s.flush()
    authorized = TebraFhirAuthorizedPatient(
        uuid4(), scope, UUID(workspace_id), UUID(patient_link_id), PATIENT["id"],
        "b" * 64, canonical_json(PATIENT), payload_hash(PATIENT),
    )
    grant = EhrFhirPatientGrant(
        id=str(authorized.grant_id), box_id=box, owner_id=owner, account_id=account,
        binding_id=binding.id, workspace_id=workspace_id, patient_link_id=patient_link_id,
        fhir_patient_id=authorized.fhir_patient_id, authorization_sha256=authorized.authorization_sha256,
        identity_json=authorized.identity_json, identity_sha256=authorized.identity_sha256,
        grant_digest=authorized.commitment(), state="active",
    )
    s.add(grant)
    s.commit()
    return scope, binding, grant, authorized


@pytest.fixture
def athena_fhir_case(signed_workspace, session, monkeypatch):
    f = signed_workspace
    monkeypatch.setattr(f.configuration, "workspace_ehr_read_enabled", True)
    monkeypatch.setattr(f.configuration, "workspace_athena_fhir_sandbox_enabled", True)
    monkeypatch.setattr(provider_team, "runtime_settings", f.configuration)
    monkeypatch.setenv(ATHENA_FHIR_CLIENT_ID_REF, FAKE_CLIENT_ID)
    monkeypatch.setenv(ATHENA_FHIR_CLIENT_SECRET_REF, FAKE_CLIENT_SECRET)
    from cosmas_os.models import EncounterWorkspace
    workspace = session.get(EncounterWorkspace, f.workspace["id"])
    assert workspace is not None and workspace.patient_link_id is not None
    scope, binding, grant, authorized = install_grant(
        session, f.box, f.actor, f.binding.id, workspace.id, workspace.patient_link_id,
    )
    provider = InventedAthenaFhir(session)
    transport = httpx.MockTransport(provider)
    token_client = ClientCredentialsTokenClient(
        config=ClientCredentialsConfig(
            client_id_ref=ATHENA_FHIR_CLIENT_ID_REF,
            client_secret_ref=ATHENA_FHIR_CLIENT_SECRET_REF,
            token_url=ATHENA_FHIR_TOKEN_URL,
            scopes=ATHENA_FHIR_SYSTEM_READ_SCOPES,
        ),
        secrets=ManagedSecretEnvResolver(),
        transport=transport,
    )
    port = SyntheticTebraFhirReads(
        (scope,), (authorized,), transport, enabled=lambda: True,
        athena_token_client=token_client,
        athena_sandbox_enabled=True,
    )
    runtimes = EhrReadRuntimes(athena_fhir=port)
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
    result = SimpleNamespace(
        client=f.client, token=f.token, workspace=f.workspace, box=f.box, owner=f.actor,
        account=f.binding.id, configuration=f.configuration, binding=binding, scope=scope,
        port=port, provider=provider, s=session, grant=grant, grant_id=grant.id,
    )
    result.headers = lambda: {"Authorization": "Bearer " + f.token(), "X-Cosmas-Ehr-Read": "1"}
    try:
        with ehr.install_runtime_reader(lambda: runtimes):
            yield result
    finally:
        overrides[api_module.get_session] = previous_session


def action(f, body):
    return f.client.post("/connections/ehr/reads", headers=f.headers(), json=body)


def status(f):
    response = action(f, {"action": "status", "provider": "athena", "protocol": "fhir"})
    assert response.status_code == 200, response.text
    return response.json()


def patients(f, key="athena-fhir-patients-1"):
    response = action(f, dict(
        action="fhir_patients", provider="athena", protocol="fhir",
        connection_id=str(f.scope.connection_id), binding_sha256=f.scope.commitment(),
        workspace_id=f.workspace["id"], idempotency_key=key,
    ))
    assert response.status_code == 200, response.text
    return response.json()


def medication_body(f, root, key="athena-fhir-medications-1"):
    item = root["observation"]["items"][0]
    return dict(
        action="fhir_medications", provider="athena", protocol="fhir",
        connection_id=str(f.scope.connection_id), binding_sha256=f.scope.commitment(),
        workspace_id=f.workspace["id"], idempotency_key=key,
        observation_id=root["observation_id"], observation_sha256=root["source_sha256"],
        item_handle=item["handle"], item_sha256=item["sha256"],
    )


def medications(f, root=None, key="athena-fhir-medications-1"):
    response = action(f, medication_body(f, root or patients(f), key))
    assert response.status_code == 200, response.text
    return response.json()


def review(f, receipt, key="athena-fhir-review-1"):
    item = receipt["observation"]["item"]
    body = dict(
        provider="athena", protocol="fhir", expected_revision=f.workspace["revision"],
        idempotency_key=key, observation_id=receipt["observation_id"],
        observation_sha256=receipt["source_sha256"], item_handle=item["handle"],
        item_sha256=item["sha256"], reviewed_patient_identity=True,
        reviewed_exact_snapshot=True, reviewed_untrusted_source=True,
    )
    return f.client.post(
        f"/workspaces/{f.workspace['id']}/ehr-read/review", headers=f.headers(), json=body,
    )


def test_signed_athena_fhir_patients_medications_and_review(athena_fhir_case):
    f = athena_fhir_case
    assert status(f) == dict(
        contract_version=1, provider="athena", protocol="fhir", mode="synthetic",
        transport="mock", status="ready", connection_id=str(f.scope.connection_id),
        binding_sha256=f.scope.commitment(), display_label=f.scope.display_label,
    )
    root = patients(f)
    assert root["observation"]["coverage"] == "authorized_candidates_only"
    assert f.provider.token_calls == 0 and not f.provider.fhir_calls
    receipt = medications(f, root)
    item = receipt["observation"]["item"]
    assert item["handle"] == root["observation"]["items"][0]["handle"]
    assert item["records"][0]["medication_name"] == "Invented lisinopril tablet"
    assert f.provider.token_calls == 1
    assert len(f.provider.fhir_calls) == 2
    shown = json.dumps(receipt) + json.dumps(status(f))
    assert CANARY_TOKEN not in shown and CANARY_SECRET not in shown
    assert FAKE_CLIENT_SECRET not in shown
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    entry = next(e for e in saved.json()["workspace"]["entries"] if e["id"] == saved.json()["entry_id"])
    assert entry["content"] == item["source_content"]
    assert entry["source_label"] == "Athena: reviewed medication records"
    assert f.s.scalar(select(func.count()).select_from(EhrReadRequest).where(
        EhrReadRequest.account_id == f.account)) == 2


@pytest.mark.parametrize("change", ["ehr_off", "athena_off", "both_off"])
def test_flags_off_refuse_before_auth_or_network(athena_fhir_case, change, monkeypatch):
    f = athena_fhir_case
    if change in {"ehr_off", "both_off"}:
        monkeypatch.setattr(f.configuration, "workspace_ehr_read_enabled", False)
    if change in {"athena_off", "both_off"}:
        monkeypatch.setattr(f.configuration, "workspace_athena_fhir_sandbox_enabled", False)
    unavailable = action(f, {"action": "status", "provider": "athena", "protocol": "fhir"})
    assert unavailable.status_code == 200
    body = unavailable.json()
    assert body["status"] == "not_enabled"
    assert body["provider"] == "athena"
    blocked = action(f, dict(
        action="fhir_patients", provider="athena", protocol="fhir",
        connection_id=str(f.scope.connection_id), binding_sha256=f.scope.commitment(),
        workspace_id=f.workspace["id"], idempotency_key="athena-fhir-blocked-1",
    ))
    assert blocked.status_code == 404
    assert f.provider.token_calls == 0 and not f.provider.fhir_calls


def test_tebra_flag_does_not_enable_athena_fhir(athena_fhir_case, monkeypatch):
    f = athena_fhir_case
    monkeypatch.setattr(f.configuration, "workspace_athena_fhir_sandbox_enabled", False)
    monkeypatch.setattr(f.configuration, "workspace_tebra_fhir_enabled", True)
    blocked = action(f, dict(
        action="fhir_patients", provider="athena", protocol="fhir",
        connection_id=str(f.scope.connection_id), binding_sha256=f.scope.commitment(),
        workspace_id=f.workspace["id"], idempotency_key="athena-fhir-tebra-flag-1",
    ))
    assert blocked.status_code == 404
    assert f.provider.token_calls == 0 and not f.provider.fhir_calls


def test_provider_isolation_refuses_tebra_and_elation_bodies(athena_fhir_case):
    f = athena_fhir_case
    root = patients(f)
    body = medication_body(f, root)
    # tebra+fhir is schema-valid but this fixture has no tebra port / flag → 404.
    assert action(f, {**body, "provider": "tebra"}).status_code == 404
    # elation cannot use protocol=fhir → 422 before any I/O.
    assert action(f, {**body, "provider": "elation"}).status_code == 422
    assert action(f, {**body, "protocol": "core"}).status_code == 422
    assert f.provider.token_calls == 0
    # patients() does not hit the network; medications would.
    assert not f.provider.fhir_calls


def test_sandbox_disabled_on_runtime_refuses_before_token(athena_fhir_case, monkeypatch):
    f = athena_fhir_case
    # Host flag still on so the route selects the port; adapter sandbox flag is off.
    monkeypatch.setattr(f.port, "_athena_sandbox_enabled", False)
    root = patients(f)
    failed = action(f, medication_body(f, root, key="athena-fhir-sandbox-off-1"))
    assert failed.status_code == 503
    assert f.provider.token_calls == 0 and not f.provider.fhir_calls


def test_canaries_never_appear_in_errors(athena_fhir_case, monkeypatch):
    f = athena_fhir_case
    monkeypatch.setenv(ATHENA_FHIR_CLIENT_SECRET_REF, CANARY_SECRET)
    f.provider.access_token = CANARY_TOKEN
    root = patients(f)
    f.provider.fail = True
    failed = action(f, medication_body(f, root, key="athena-fhir-canary-1"))
    assert failed.status_code == 503
    text = failed.text
    assert CANARY_TOKEN not in text and CANARY_SECRET not in text
    assert FAKE_CLIENT_ID not in text
