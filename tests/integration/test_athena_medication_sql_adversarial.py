"""Rehashed clinical payloads still obey independent scope and lossless SQL custody."""

import hashlib
import json
from copy import deepcopy

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from tests.integration.test_athena_allergy_sql_adversarial import insert_snapshot
from tests.integration.test_athena_medication_ehr import (
    action,
    medication_body,
    medications,
    patients,
    review,
    review_body,
)
from tests.integration.test_athena_medication_ehr import athena_medication_case as _medication_case
from tests.integration.test_athena_medication_ehr import signed_workspace as _signed_workspace

from cosmas_os.adapters.athena_medication_read import RecordedNumber, clinical_dumps, clinical_loads
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import EhrReadRequest, EhrReadSnapshot

signed_workspace = _signed_workspace
athena_medication_case = _medication_case


def reserved_payload(f):
    parent = patients(f)
    receipt = medications(f, parent)
    key = "medication-adversarial-reserved-intent"
    f.provider.fail = True
    assert action(f, medication_body(f, parent, key)).status_code == 503
    f.provider.fail = False
    read = f.s.scalar(select(EhrReadRequest).where(EhrReadRequest.account_id == f.account, EhrReadRequest.idempotency_key == key))
    original = f.s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == receipt["observation_id"]))
    assert read is not None and original is not None
    payload = deepcopy(original.payload)
    payload["private"]["request_sha256"] = read.request_hash
    assert valid(f, read, payload) is True
    with f.s.begin_nested() as baseline:
        insert_snapshot(f, read, payload)
        baseline.rollback()
    return read, payload


def valid(f, read, payload):
    return f.s.scalar(text("SELECT public.ehr_read_payload_valid(CAST(:payload AS jsonb),r) FROM ehr_read_requests r WHERE r.id=:id"),
        {"payload": canonical_json(payload), "id": read.id})


def reprojection(f, payload, raw):
    # Recompute every dependent digest. An invalid scalar must fail because of
    # its original recorded shape, not an unrelated stale outer hash.
    section = clinical_loads(raw["section_json"])
    raw["groups"] = [[dict(medication_entry_id=r.get("medicationentryid"), medication_name=r.get("medication"),
        original_json=clinical_dumps(r)) for r in group] for group in section["medications"]]
    raw["source_sha256"] = payload_hash(dict(contract="athena-medication-observation.v1", scope_sha256=f.authorized_patient.read_scope().commitment(),
        **{k: raw[k] for k in ("patient", "observed_at", "section_json", "provider_sources", "coverage", "medication_type", "includes_pending", "includes_ndc", "includes_rxnorm")}))
    source = f.s.scalar(text("SELECT public.ehr_athena_med_source_text(CAST(:raw AS jsonb))"), {"raw": canonical_json(raw)})
    item = payload["public"]["item"]
    item.update(section_json=raw["section_json"], source_content=source, content_sha256=hashlib.sha256(source.encode()).hexdigest(),
        **{k: raw[k] for k in ("coverage", "medication_type", "includes_pending", "includes_ndc", "includes_rxnorm")})
    item["sha256"] = ehr.item_hash("core_medications", item)
    payload["public"]["observed_at"] = raw["observed_at"].replace("+00:00", "Z")
    payload["private"]["reader_snapshot_json"] = canonical_json(raw)
    payload["private"]["review_sha256"] = payload_hash(dict(contract="athena-medication-review-snapshot.v1",
        scope_sha256=f.authorized_patient.read_scope().commitment(), observation_sha256=raw["source_sha256"],
        patient_identity_sha256=f.authorized_patient.identity_sha256, source_content_sha256=item["content_sha256"],
        completeness="bounded_recorded_medication_section"))


def refused(f, read, payload):
    assert valid(f, read, payload) is False
    with pytest.raises(IntegrityError) as rejected:
        with f.s.begin_nested():
            insert_snapshot(f, read, payload)
    assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    assert f.s.scalar(select(func.count()).select_from(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == read.id)) == 0


@pytest.mark.parametrize("change", [
    "reader_hash_null", "review_hash_null", "handle_null", "public_scope_missing", "private_scope_null",
    "nomedications_null", "nomedications_string", "quantity_string", "integer_decimal", "integer_overflow",
    "record_name_null", "event_type_null", "unknown_section", "unknown_record", "chart_department",
    "pending_false", "timestamp_z", "timestamp_fraction", "normalized_token_original_mismatch",
])
def test_sql_refuses_rehashed_invalid_medication_payload(athena_medication_case, change):
    f = athena_medication_case
    read, payload = reserved_payload(f)
    raw = json.loads(payload["private"]["reader_snapshot_json"])
    section = clinical_loads(raw["section_json"])
    row = section["medications"][0][0]
    if change == "nomedications_null":
        section["nomedicationsreported"] = None
    elif change == "nomedications_string":
        section["nomedicationsreported"] = "false"
    elif change == "quantity_string":
        row["quantity"] = "0.50"
    elif change == "integer_decimal":
        row["medicationid"] = RecordedNumber("1.0")
    elif change == "integer_overflow":
        row["medicationid"] = RecordedNumber("9223372036854775808")
    elif change == "record_name_null":
        row["medication"] = None
    elif change == "event_type_null":
        row["events"][0]["type"] = None
    elif change == "unknown_section":
        section["unknown_clinical_state"] = "cannot discard"
    elif change == "unknown_record":
        row["unknown_clinical_state"] = "cannot discard"
    elif change == "chart_department":
        raw["scope"]["department_id"] = "999"
    elif change == "pending_false":
        raw["includes_pending"] = False
    elif change == "timestamp_z":
        raw["observed_at"] = raw["observed_at"].replace("+00:00", "Z")
    elif change == "timestamp_fraction":
        raw["observed_at"] = raw["observed_at"][:19] + ".100+00:00"
    raw["section_json"] = clinical_dumps(section)
    reprojection(f, payload, raw)
    if change == "reader_hash_null":
        raw["source_sha256"] = None
        payload["private"]["reader_snapshot_json"] = canonical_json(raw)
        payload["private"]["review_sha256"] = payload_hash(dict(contract="athena-medication-review-snapshot.v1",
            scope_sha256=f.authorized_patient.read_scope().commitment(), observation_sha256=None,
            patient_identity_sha256=f.authorized_patient.identity_sha256,
            source_content_sha256=payload["public"]["item"]["content_sha256"], completeness="bounded_recorded_medication_section"))
    elif change == "review_hash_null":
        payload["private"]["review_sha256"] = None
    elif change == "handle_null":
        payload["private"]["items"][0]["handle"] = None
    elif change == "public_scope_missing":
        payload["public"].pop("clinical_scope")
    elif change == "private_scope_null":
        payload["private"]["clinical_scope"] = None
    elif change == "normalized_token_original_mismatch":
        raw["groups"][0][0]["original_json"] = raw["groups"][0][0]["original_json"].replace('"quantity":0.50', '"quantity":0.5')
        payload["private"]["reader_snapshot_json"] = canonical_json(raw)
    refused(f, read, payload)


def test_sql_keeps_exact_numeric_spelling_at_whole_source_5000_limit(athena_medication_case):
    f = athena_medication_case
    read, payload = reserved_payload(f)
    raw = json.loads(payload["private"]["reader_snapshot_json"])
    section = clinical_loads(raw["section_json"])
    section["sectionnote"] = ""
    raw["section_json"] = clinical_dumps(section)
    reprojection(f, payload, raw)
    padding = 5000 - len(payload["public"]["item"]["source_content"])
    assert 0 < padding < 4096
    section["sectionnote"] = "x" * padding
    raw["section_json"] = clinical_dumps(section)
    reprojection(f, payload, raw)
    source = payload["public"]["item"]["source_content"]
    assert len(source) == 5000 and '"quantity":0.50' in source and '"tiny":1e-7' in source and '"signedzero":-0' in source
    assert valid(f, read, payload) is True
    with f.s.begin_nested() as boundary:
        insert_snapshot(f, read, payload)
        boundary.rollback()
    section["sectionnote"] += "x"
    raw["section_json"] = clinical_dumps(section)
    reprojection(f, payload, raw)
    assert len(payload["public"]["item"]["source_content"]) == 5001
    refused(f, read, payload)


@pytest.mark.parametrize("scope", [None, "allergies", "medication", ""])
def test_medication_discriminator_cannot_be_omitted_or_swapped_on_any_existing_proof(athena_medication_case, scope):
    f = athena_medication_case
    root = patients(f)
    receipt = medications(f, root)
    commands = [medication_body(f, root, "wrong-scope-read"),
        dict(action="inspect", provider="athena", protocol="core", observation_id=receipt["observation_id"]),
        dict(action="resolve", provider="athena", protocol="core", idempotency_key=receipt["observation_key"])]
    body = review_body(f, receipt)
    for command in [*commands, body]:
        if scope is None:
            command.pop("clinical_scope", None)
        else:
            command["clinical_scope"] = scope
    for command in commands:
        response = action(f, command)
        assert response.status_code in (404, 409, 422), response.text
    response = f.client.post(f"/workspaces/{f.workspace['id']}/ehr-read/review", headers=f.headers(), json=body)
    assert response.status_code in (404, 409, 422), response.text
    assert len(f.provider.calls) == 2
    assert review(f, receipt).status_code == 200


def test_allergy_and_medication_bindings_grants_and_roots_remain_independent(athena_medication_case, monkeypatch):
    from types import SimpleNamespace

    import httpx
    from tests.integration.test_athena_allergy_ehr import install_grant as allergy_grant
    from tests.integration.test_athena_allergy_ehr import patients as allergy_patients
    from tests.integration.test_athena_allergy_ehr import revoke as revoke_allergy

    from cosmas_os.adapters.athena_allergy_read_runtime import SyntheticAthenaAllergyReads
    from cosmas_os.adapters.ehr_read_runtime import EhrReadRuntimes
    from cosmas_os.api import app as api_module

    f = athena_medication_case
    monkeypatch.setattr(f.configuration, "workspace_athena_allergies_enabled", True)
    missing = action(f, dict(action="status", provider="athena", protocol="core"))
    assert missing.status_code == 200 and missing.json()["status"] == "not_configured"
    # Same exact patient/department IDs do not make the grants interchangeable.
    scope, binding, grant, authorized = allergy_grant(f.s, f.box, f.owner, f.account, f.workspace["id"], str(f.authorized_patient.patient_link_id))
    unused_transport = httpx.MockTransport(lambda _: pytest.fail("No allergy HTTP read was requested"))
    allergy = SyntheticAthenaAllergyReads((scope,), (authorized,), unused_transport, enabled=lambda: True)
    combined = EhrReadRuntimes(athena_core=allergy, athena_medications=f.port)
    other = SimpleNamespace(**{**vars(f), "scope": scope, "grant_id": grant.id, "binding_id": binding.id})
    monkeypatch.setattr(api_module.app.state, "ehr_reads", combined)
    with ehr.install_runtime_reader(lambda: combined):
        root = patients(f)
        old_root = allergy_patients(other)
        assert "clinical_scope" not in old_root and old_root["observation"]["kind"] == "core_patients"
        assert root["clinical_scope"] == "medications" and root["source_sha256"] != old_root["source_sha256"]
        assert action(f, medication_body(f, old_root)).status_code == 409
        assert not f.provider.calls
        receipt = medications(f, root)
        saved = review(f, receipt)
        assert saved.status_code == 200, saved.text
        revoke_allergy(other)
        current = f.client.get(f"/workspaces/{f.workspace['id']}", headers={"Authorization": "Bearer " + f.token()})
        assert current.status_code == 200
        entry = next(e for e in current.json()["entries"] if e["id"] == saved.json()["entry_id"])
        assert entry["ehr_source_state"] == "current" and entry["content"] == receipt["observation"]["item"]["source_content"]
        assert len(f.provider.calls) == 2


@pytest.mark.parametrize("label", [" ", "\u2003", "\u0085\u00a0"])
def test_sql_medication_grant_refuses_rehashed_blank_department_label(athena_medication_case, label):
    from dataclasses import asdict
    from uuid import UUID, uuid4

    f = athena_medication_case
    identity = json.loads(f.authorized_patient.identity_json)
    identity["patientid"] = "904"
    scoped = {k: str(v) if type(v) is UUID else v for k, v in asdict(f.authorized_patient.read_scope()).items()}
    scoped.update(patient_id="904", department_label=label)
    identifier = str(uuid4())
    scope_hash = payload_hash(dict(contract="athena-medication-patient-scope.v1", origin="https://api.preview.platform.athenahealth.com", **scoped))
    grant_hash = payload_hash(dict(contract="athena-medication-patient-grant.v1", grant_id=identifier,
        scope_sha256=scope_hash, patient_identity_sha256=payload_hash(identity)))
    with pytest.raises(IntegrityError) as rejected:
        with f.s.begin_nested():
            f.s.execute(text("""INSERT INTO ehr_athena_medication_patient_grants
              (id,binding_id,account_id,workspace_id,patient_link_id,patient_id,department_id,department_label,
               authorization_sha256,identity_json,identity_sha256,grant_digest,state,box_id,owner_id)
              VALUES (:id,:binding,:account,:workspace,:link,'904','902',:label,:auth,:identity,:identity_hash,:grant_hash,'active',:box,:owner)"""),
              dict(id=identifier,binding=f.binding_id,account=f.account,workspace=f.workspace["id"],link=str(f.authorized_patient.patient_link_id),
                  label=label,auth=f.authorized_patient.authorization_sha256,identity=canonical_json(identity),identity_hash=payload_hash(identity),
                  grant_hash=grant_hash,box=f.box,owner=f.owner))
    assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    assert not f.provider.calls
