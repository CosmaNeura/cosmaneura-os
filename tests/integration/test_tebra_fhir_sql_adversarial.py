"""Independent SQL regressions for Tebra reference and nullable-proof boundaries."""

import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from tests.integration.test_tebra_fhir_ehr import (
    action,
    medication_body,
    medications,
    patients,
    review,
)
from tests.integration.test_tebra_fhir_ehr import signed_workspace as _signed_workspace
from tests.integration.test_tebra_fhir_ehr import tebra_fhir_case as _tebra_fhir_case

from cosmas_os.adapters.tebra_fhir_read import FHIR_BASE, TebraFhirReadError, _patient
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import EhrReadRequest, EhrReadSnapshot

signed_workspace = _signed_workspace
tebra_fhir_case = _tebra_fhir_case


def _insert_snapshot(f, read, payload):
    """Use SQL directly so application/Pydantic refusal cannot satisfy this gate."""
    digest = payload_hash(payload)
    f.s.execute(text("""
        INSERT INTO ehr_read_snapshots
            (id, box_id, owner_id, observation_id, payload, payload_sha256, source_sha256)
        VALUES (:id, :box, :owner, :observation, CAST(:payload AS jsonb), :payload_hash, :source_hash)
    """), dict(id=str(uuid4()), box=f.box, owner=f.owner, observation=read.id,
        payload=canonical_json(payload), payload_hash=digest, source_hash=ehr._commitment(read, digest)))


@pytest.mark.parametrize("field", ["reader_source", "review", "handle"])
def test_sql_rejects_null_proofs_even_after_recomputing_dependent_hashes(tebra_fhir_case, field):
    f = tebra_fhir_case
    parent = patients(f)
    receipt = medications(f, parent)

    # A second exact intent has no snapshot after a simulated transport failure.
    # Its still-current reservation lets us exercise the actual INSERT guard.
    key = "tebra-fhir-null-proof-target"
    f.provider.fail = True
    failed = action(f, medication_body(f, parent, key))
    assert failed.status_code == 503, failed.text
    f.provider.fail = False
    read = f.s.scalar(select(EhrReadRequest).where(
        EhrReadRequest.account_id == f.account, EhrReadRequest.idempotency_key == key))
    original = f.s.scalar(select(EhrReadSnapshot).where(
        EhrReadSnapshot.observation_id == receipt["observation_id"]))
    assert read is not None and original is not None
    payload = deepcopy(original.payload)
    payload["private"]["request_sha256"] = read.request_hash

    def valid(value):
        return f.s.scalar(text("""
            SELECT public.ehr_read_payload_valid(CAST(:payload AS jsonb), r)
            FROM ehr_read_requests r WHERE r.id=:id
        """), {"payload": canonical_json(value), "id": read.id})

    assert valid(payload) is True
    # First prove this reservation and unchanged clinical payload are admissible;
    # rollback only the test insert, retaining the original source and intent.
    with f.s.begin_nested() as baseline:
        _insert_snapshot(f, read, payload)
        assert f.s.scalar(select(func.count()).select_from(EhrReadSnapshot).where(
            EhrReadSnapshot.observation_id == read.id)) == 1
        baseline.rollback()

    if field == "review":
        payload["private"]["review_sha256"] = None
    elif field == "handle":
        payload["private"]["items"][0]["handle"] = None
    else:
        raw = json.loads(payload["private"]["reader_snapshot_json"])
        raw["source_sha256"] = None
        payload["private"]["reader_snapshot_json"] = canonical_json(raw)
        payload["private"]["review_sha256"] = payload_hash(dict(
            contract="tebra-fhir-review-snapshot.v1",
            scope_sha256=f.authorized_patient.read_scope().commitment(),
            observation_sha256=None,
            patient_identity_sha256=f.authorized_patient.identity_sha256,
            source_content_sha256=payload["public"]["item"]["content_sha256"],
            completeness="bounded_recorded_history"))

    # NULL must be a total False, never SQL's third truth value. Rehashing both
    # enclosing commitments cannot make the invalid proof safe to persist.
    assert valid(payload) is False
    with pytest.raises(IntegrityError) as rejected:
        with f.s.begin_nested():
            _insert_snapshot(f, read, payload)
    assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    assert f.s.scalar(select(func.count()).select_from(EhrReadSnapshot).where(
        EhrReadSnapshot.observation_id == read.id)) == 0


@pytest.mark.parametrize("absolute", [False, True])
def test_same_server_medication_reference_preserves_request_and_resolved_labels(tebra_fhir_case, absolute):
    f = tebra_fhir_case
    f.provider.row.pop("medicationCodeableConcept")
    reference = (FHIR_BASE + "/" if absolute else "") + "Medication/med-A"
    f.provider.row["medicationReference"] = dict(
        reference=reference, type="Medication", display="Contradictory request label")
    receipt = medications(f)
    item = receipt["observation"]["item"]
    record = item["records"][0]
    assert json.loads(record["request_medication_json"]) == {
        "medicationReference": f.provider.row["medicationReference"]}
    assert json.loads(record["medication_json"]) == f.provider.medication
    assert record["medication_name"] == "Invented resolved medication"
    content = item["source_content"]
    assert "Original medication choice: " + record["request_medication_json"] in content
    assert "Resolved medication: " + record["medication_json"] in content
    assert len(f.provider.calls) == 3
    saved = review(f, receipt)
    assert saved.status_code == 200, saved.text
    entry = next(row for row in saved.json()["workspace"]["entries"]
        if row["id"] == saved.json()["entry_id"])
    assert entry["content"] == content
    assert entry["source_label"] == "Tebra: reviewed medication records"
    assert entry["ehr_source_state"] == "current"
    assert len(f.provider.calls) == 3


def _insert_grant(f, identity):
    identifier = str(uuid4())
    read_scope = replace(f.authorized_patient.read_scope(), patient_id=identity["id"])
    identity_hash = payload_hash(identity)
    digest = payload_hash(dict(contract="tebra-fhir-patient-grant.v1", grant_id=identifier,
        connection_sha256=f.scope.commitment(), workspace_id=f.workspace["id"],
        patient_link_id=str(f.authorized_patient.patient_link_id),
        read_scope_sha256=read_scope.commitment(), patient_identity_sha256=identity_hash))
    f.s.execute(text("""
        INSERT INTO ehr_fhir_patient_grants
            (id, binding_id, account_id, workspace_id, patient_link_id, fhir_patient_id,
             authorization_sha256, identity_json, identity_sha256, grant_digest, state, box_id, owner_id)
        VALUES (:id, :binding, :account, :workspace, :patient_link, :patient,
                :authorization_hash, :identity, :identity_hash, :grant_hash, 'active', :box, :owner)
    """), dict(id=identifier, binding=f.binding_id, account=f.account, workspace=f.workspace["id"],
        patient_link=str(f.authorized_patient.patient_link_id), patient=identity["id"],
        authorization_hash=read_scope.authorization_sha256, identity=canonical_json(identity),
        identity_hash=identity_hash, grant_hash=digest, box=f.box, owner=f.owner))
    return identifier


@pytest.mark.parametrize("change", [
    {"name": [{"family": 123}]},
    {"name": [{}]},
    {"active": "false"},
    {"deceasedBoolean": False, "deceasedDateTime": "2020"},
    {"identifier": [{"value": 123}]},
], ids=["numeric-family", "nameless-object", "string-active", "conflicting-death-fields", "numeric-identifier"])
def test_sql_grant_rejects_reader_invalid_identity_after_rehash(tebra_fhir_case, change):
    f = tebra_fhir_case
    identity = json.loads(f.authorized_patient.identity_json)
    identity["id"] = "fhir-patient-independent-probe"
    scoped = replace(f.authorized_patient.read_scope(), patient_id=identity["id"])
    assert _patient(identity, scoped).identity_sha256 == payload_hash(identity)
    # The same context accepts a valid new server-owned grant. Roll it back so
    # rejection below cannot be explained by the unique active-grant index.
    with f.s.begin_nested() as baseline:
        identifier = _insert_grant(f, identity)
        assert f.s.scalar(text("SELECT public.ehr_fhir_grant_current(:id)"), {"id": identifier}) is True
        baseline.rollback()

    identity.update(deepcopy(change))
    with pytest.raises(TebraFhirReadError):
        _patient(identity, scoped)
    with pytest.raises(IntegrityError) as rejected:
        with f.s.begin_nested():
            _insert_grant(f, identity)
    assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    assert f.s.scalar(text("""
        SELECT count(*) FROM ehr_fhir_patient_grants
        WHERE binding_id=:binding AND fhir_patient_id=:patient
    """), {"binding": f.binding_id, "patient": identity["id"]}) == 0
    assert not f.provider.calls
