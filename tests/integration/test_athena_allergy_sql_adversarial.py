"""Independent SQL refusal gates for exact Athena identity and recorded section proof."""

import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from tests.integration.test_athena_allergy_ehr import action, allergies, allergy_body, patients
from tests.integration.test_athena_allergy_ehr import athena_allergy_case as _athena_allergy_case
from tests.integration.test_athena_allergy_ehr import signed_workspace as _signed_workspace

from cosmas_os.adapters.athena_allergy_read import AthenaAllergyError, patient_identity
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import EhrReadRequest, EhrReadSnapshot

signed_workspace = _signed_workspace
athena_allergy_case = _athena_allergy_case


def insert_snapshot(f, read, payload):
    digest = payload_hash(payload)
    f.s.execute(text("""
        INSERT INTO ehr_read_snapshots
            (id,box_id,owner_id,observation_id,payload,payload_sha256,source_sha256)
        VALUES (:id,:box,:owner,:read,CAST(:payload AS jsonb),:digest,:source)
    """), dict(id=str(uuid4()), box=f.box, owner=f.owner, read=read.id,
        payload=canonical_json(payload), digest=digest, source=ehr._commitment(read, digest)))


@pytest.mark.parametrize("change", ["reader_hash_null", "review_hash_null", "handle_null", "nkda_null", "string_nkda", "allergen_overflow", "reaction_negative", "unknown_section", "chart_department", "timestamp_z", "timestamp_fraction"])
def test_sql_rejects_rehashed_malformed_clinical_proof(athena_allergy_case, change):
    f = athena_allergy_case
    parent = patients(f)
    receipt = allergies(f, parent)
    key = "athena-adversarial-reserved-intent"
    f.provider.fail = True
    assert action(f, allergy_body(f, parent, key)).status_code == 503
    f.provider.fail = False
    read = f.s.scalar(select(EhrReadRequest).where(EhrReadRequest.account_id == f.account, EhrReadRequest.idempotency_key == key))
    original = f.s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == receipt["observation_id"]))
    assert read is not None and original is not None
    payload = deepcopy(original.payload)
    payload["private"]["request_sha256"] = read.request_hash

    def valid():
        return f.s.scalar(text("SELECT public.ehr_read_payload_valid(CAST(:payload AS jsonb),r) FROM ehr_read_requests r WHERE r.id=:id"),
            {"payload": canonical_json(payload), "id": read.id})

    assert valid() is True
    with f.s.begin_nested() as baseline:
        insert_snapshot(f, read, payload)
        baseline.rollback()

    raw = json.loads(payload["private"]["reader_snapshot_json"])
    if change in ("reader_hash_null", "review_hash_null", "handle_null"):
        if change == "reader_hash_null":
            raw["source_sha256"] = None
        elif change == "handle_null":
            payload["private"]["items"][0]["handle"] = None
    else:
        section = json.loads(raw["section_json"])
        if change == "nkda_null":
            section["nkda"] = None
        elif change == "string_nkda":
            section["nkda"] = "false"
        elif change == "allergen_overflow":
            section["allergies"][0]["allergenid"] = 2**63
        elif change == "reaction_negative":
            section["allergies"][0]["reactions"] = [{"snomedcode": -1}]
        elif change == "unknown_section":
            section["unsupported_clinical_state"] = "retain or refuse"
        elif change == "chart_department":
            raw["scope"]["department_id"] = "999"
        elif change == "timestamp_z":
            raw["observed_at"] = raw["observed_at"].replace("+00:00", "Z")
        else:
            raw["observed_at"] = raw["observed_at"][:19] + ".100+00:00"
        payload["public"]["observed_at"] = raw["observed_at"].replace("+00:00", "Z")
        raw["section_json"] = canonical_json(section)
        raw["records"] = [dict(record_id=r["id"], allergen_name=r["allergenname"], original_json=canonical_json(r)) for r in section["allergies"]]
        raw["source_sha256"] = payload_hash(dict(contract="athena-allergy-observation.v1", scope_sha256=f.authorized_patient.read_scope().commitment(),
            **{k: raw[k] for k in ("patient", "observed_at", "section_json", "provider_sources", "coverage", "includes_inactive")}))
        # Recompute all dependent public text/hashes so refusal must concern the
        # original clinical shape or exact authority, not a stale outer digest.
        source = f.s.scalar(text("SELECT public.ehr_athena_source_text(CAST(:raw AS jsonb))"), {"raw": canonical_json(raw)})
        item = payload["public"]["item"]
        item.update(section_json=raw["section_json"], source_content=source,
            content_sha256=f.s.scalar(text("SELECT encode(sha256(convert_to(:source,'UTF8')),'hex')"), {"source": source}))
        item["sha256"] = ehr.item_hash("core_allergies", item)
    payload["private"]["reader_snapshot_json"] = canonical_json(raw)
    payload["private"]["review_sha256"] = None if change == "review_hash_null" else payload_hash(dict(
        contract="athena-allergy-review-snapshot.v1", scope_sha256=f.authorized_patient.read_scope().commitment(),
        observation_sha256=raw["source_sha256"], patient_identity_sha256=f.authorized_patient.identity_sha256,
        source_content_sha256=payload["public"]["item"]["content_sha256"], completeness="bounded_recorded_allergy_section"))
    assert valid() is False
    with pytest.raises(IntegrityError) as rejected:
        with f.s.begin_nested():
            insert_snapshot(f, read, payload)
    assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    assert f.s.scalar(select(func.count()).select_from(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == read.id)) == 0


def insert_grant(f, identity):
    identifier = str(uuid4())
    scoped = replace(f.authorized_patient.read_scope(), patient_id=identity["patientid"])
    digest = payload_hash(dict(contract="athena-allergy-patient-grant.v1", grant_id=identifier,
        scope_sha256=scoped.commitment(), patient_identity_sha256=payload_hash(identity)))
    f.s.execute(text("""
        INSERT INTO ehr_athena_core_patient_grants
            (id,binding_id,account_id,workspace_id,patient_link_id,patient_id,department_id,department_label,
             authorization_sha256,identity_json,identity_sha256,grant_digest,state,box_id,owner_id)
        VALUES (:id,:binding,:account,:workspace,:link,:patient,:department,:label,
                :auth,:identity,:identity_hash,:grant_hash,'active',:box,:owner)
    """), dict(id=identifier, binding=f.binding_id, account=f.account, workspace=f.workspace["id"],
        link=str(scoped.patient_link_id), patient=scoped.patient_id, department=scoped.department_id,
        label=scoped.department_label, auth=scoped.authorization_sha256, identity=canonical_json(identity),
        identity_hash=payload_hash(identity), grant_hash=digest, box=f.box, owner=f.owner))
    return identifier


@pytest.mark.parametrize("change", [{"firstname": None}, {"lastname": "\u2003"}, {"dob": "02/29/2023"}])
def test_sql_grant_rejects_rehashed_reader_invalid_identity(athena_allergy_case, change):
    f = athena_allergy_case
    identity = json.loads(f.authorized_patient.identity_json)
    identity["patientid"] = "904"
    scoped = replace(f.authorized_patient.read_scope(), patient_id="904")
    assert patient_identity([identity], scoped).identity_sha256 == payload_hash(identity)
    with f.s.begin_nested() as baseline:
        identifier = insert_grant(f, identity)
        assert f.s.scalar(text("SELECT public.ehr_athena_grant_current(:id)"), {"id": identifier}) is True
        baseline.rollback()
    identity.update(change)
    with pytest.raises(AthenaAllergyError):
        patient_identity([identity], scoped)
    with pytest.raises(IntegrityError) as rejected:
        with f.s.begin_nested():
            insert_grant(f, identity)
    assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    assert not f.provider.calls
