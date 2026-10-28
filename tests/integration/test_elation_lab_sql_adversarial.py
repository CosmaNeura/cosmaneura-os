"""Independent SQL parity for literal Lab records and exact source commitments."""
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from tests.integration.test_elation_lab_ehr import action, body, lab_report, lab_reports
from tests.integration.test_elation_lab_ehr import ehr_case as _ehr_case
from tests.integration.test_elation_lab_ehr import lab_case as _lab_case
from tests.integration.test_elation_lab_ehr import signed_workspace as _signed_workspace
from tests.unit.test_elation_lab_read import REPORT, SCOPE, Harness

from cosmas_os.adapters.elation_lab_read import ElationLabError, validate_report
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application.elation_lab_ehr import encoded
from cosmas_os.application.elation_lab_snapshot import prepare_lab_review
from cosmas_os.domain.hashing import canonical_json, payload_hash
from cosmas_os.ehr_read_models import EhrReadRequest, EhrReadSnapshot


def sql_report(session, raw):
    scoped = json.loads(encoded(Harness().read()))["scope"]
    return session.scalar(text("SELECT public.ehr_lab_report(:raw,CAST(:scope AS jsonb),:id)"),
        dict(raw=raw, scope=canonical_json(scoped), id=REPORT["id"]))


@pytest.mark.parametrize("change,accepted", [
    ("exact", True), ("empty_value", True), ("absent_units", True), ("null_units", True),
    ("max_physician", True), ("opaque_integer", True), ("empty_embedded_content", True),
    ("numeric_value", False), ("null_boolean", False), ("missing_note", False),
    ("unknown_result_field", False), ("null_grids", False), ("wrong_patient", False),
    ("wrong_practice", False), ("overflow_identifier", False), ("null_attachment_document", False),
    ("null_embedded_content", False), ("embedded_content", False), ("opaque_decimal", False),
])
def test_sql_preserves_or_refuses_exact_report_shape_like_reader(session, change, accepted):
    value = deepcopy(REPORT)
    result = value["grids"][0]["results"][0]
    if change == "empty_value":
        result["value"] = ""
    elif change == "absent_units":
        del result["units"]
    elif change == "null_units":
        result["units"] = None
    elif change == "max_physician":
        value["physician"] = 2**63-1
    elif change == "opaque_integer":
        value["files"][0]["external_content"] = {"opaque": 2**80, "uninterpreted": [None, ""]}
    elif change == "empty_embedded_content":
        value["files"][0]["base64_content"] = ""
    elif change == "numeric_value":
        result["value"] = 123
    elif change == "null_boolean":
        result["is_abnormal"] = None
    elif change == "missing_note":
        del result["note"]
    elif change == "unknown_result_field":
        result["interpretation"] = "Not a qualified field"
    elif change == "null_grids":
        value["grids"] = None
    elif change == "wrong_patient":
        value["patient"] = 904
    elif change == "wrong_practice":
        value["practice"] = 999
    elif change == "overflow_identifier":
        value["physician"] = 2**63
    elif change == "null_attachment_document":
        value["files"][0]["document"] = None
    elif change == "null_embedded_content":
        value["files"][0]["base64_content"] = None
    elif change == "embedded_content":
        value["files"][0]["base64_content"] = "AA=="
    elif change == "opaque_decimal":
        value["files"][0]["external_content"] = 1.2
    raw = canonical_json(value)
    if accepted:
        assert validate_report(value, SCOPE, REPORT["id"]) == raw
    else:
        # The full reader additionally runs its duplicate/number/tree parser.
        from cosmas_os.adapters.elation_lab_read import parse_json
        with pytest.raises(ElationLabError):
            validate_report(parse_json(raw), SCOPE, REPORT["id"])
    assert sql_report(session, raw) is accepted


def test_sql_canonical_and_source_text_match_qualified_formatter_exactly(session):
    h = Harness()
    page = h.reader.list_reports()
    h.report["grids"][0]["results"][0]["value"] = "<0.1000"
    value = h.read(page)
    raw = encoded(value)
    assert session.scalar(text("SELECT public.ehr_lab_canonical(CAST(:raw AS jsonb))"), {"raw": raw}) == raw
    assert session.scalar(text("SELECT public.ehr_lab_digest(CAST(:raw AS jsonb))"), {"raw": value.report_json}) == value.report_sha256 == payload_hash(h.report)
    prepared = prepare_lab_review(value, expected_scope=SCOPE, expected_source_sha256=value.source_sha256,
        expected_candidates_sha256=page.source_sha256, expected_report_id=REPORT["id"], authorize_read=lambda _: True)
    source = session.scalar(text("SELECT public.ehr_lab_source_text(CAST(:raw AS jsonb))"), {"raw": raw})
    assert source == prepared.source_content
    assert session.scalar(text("SELECT public.ehr_lab_warnings(CAST(:raw AS jsonb))"), {"raw": raw}) == list(prepared.warnings)
    assert '123456789012345678' in source and '"<0.1000"' in source
    assert session.scalar(text("SELECT encode(sha256(convert_to(:source,'UTF8')),'hex')"), {"source": source}) == prepared.source_content_sha256


@pytest.mark.parametrize("raw", ['{"id":1,"id":2}', '{"fraction":1.0}', '{"fraction":1e2}'])
def test_noncanonical_duplicate_or_decimal_spelling_is_not_admitted(session, raw):
    assert sql_report(session, raw) is False

# These signed cases use a real retained intent, then recompute every dependent
# public/source hash. Refusal must concern custody/clinical shape, not a stale hash.

ehr_case = _ehr_case
lab_case = _lab_case
signed_workspace = _signed_workspace


def insert_lab_snapshot(f, read, payload):
    digest = payload_hash(payload)
    f.s.execute(text("""INSERT INTO ehr_read_snapshots
        (id,box_id,owner_id,observation_id,payload,payload_sha256,source_sha256)
        VALUES (:id,:box,:owner,:read,CAST(:payload AS jsonb),:digest,:source)"""),
        dict(id=str(uuid4()), box=f.box, owner=f.owner, read=read.id, payload=canonical_json(payload),
            digest=digest, source=ehr._commitment(read, digest)))


@pytest.mark.parametrize("change", ["reader_hash_null", "review_hash_null", "handle_null", "visit_proof_null",
    "patient", "practice", "value_number", "abnormal_null", "unknown_result", "scope_workspace",
    "patient_identity", "candidate_proof", "selected_proof", "timestamp_z", "timestamp_fraction", "whole_source_5001"])
def test_signed_sql_rejects_fully_rehashed_record_or_custody_change(lab_case, change):
    f = lab_case
    page = lab_reports(f)
    receipt = lab_report(f, page)
    f.lab_fail = True
    key = "lab-adversarial-retained-intent"
    assert action(f, body(f, page, key=key, action_name="lab_report")).status_code == 503
    f.lab_fail = False
    read = f.s.scalar(select(EhrReadRequest).where(EhrReadRequest.account_id == f.account, EhrReadRequest.idempotency_key == key))
    original = f.s.scalar(select(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == receipt["observation_id"]))
    assert read is not None and original is not None
    payload = deepcopy(original.payload)
    payload["private"]["request_sha256"] = read.request_hash

    def valid():
        return f.s.scalar(text("SELECT public.ehr_read_payload_valid(CAST(:payload AS jsonb),r) FROM ehr_read_requests r WHERE r.id=:id"),
            dict(payload=canonical_json(payload), id=read.id))

    assert valid() is True
    with f.s.begin_nested() as baseline:
        insert_lab_snapshot(f, read, payload)
        baseline.rollback()
    raw = json.loads(payload["private"]["reader_snapshot_json"])
    report = json.loads(raw["report_json"])
    if change == "handle_null":
        payload["private"]["items"][0]["handle"] = None
        payload["public"]["item"]["handle"] = None
    elif change == "visit_proof_null":
        payload["private"]["visit_provider_sources"][0] = None
    elif change == "patient":
        report["patient"] += 1
    elif change == "practice":
        report["practice"] += 1
    elif change == "value_number":
        report["grids"][0]["results"][0]["value"] = 123
    elif change == "abnormal_null":
        report["grids"][0]["results"][0]["is_abnormal"] = None
    elif change == "unknown_result":
        report["grids"][0]["results"][0]["new_meaning"] = "Unsupported"
    elif change == "scope_workspace":
        raw["scope"]["workspace_id"] = str(uuid4())
    elif change == "patient_identity":
        patient = json.loads(raw["patient"]["identity_json"])
        patient["first_name"] = "Other"
        raw["patient"] = dict(identity_json=canonical_json(patient), identity_sha256=payload_hash(patient))
        raw["scope"]["patient_identity_sha256"] = payload_hash(patient)
    elif change == "candidate_proof":
        raw["parent_candidates_sha256"] = "d"*64
    elif change == "selected_proof":
        raw["selected_report_sha256"] = "d"*64
    elif change == "timestamp_z":
        raw["observed_at"] = raw["observed_at"].replace("+00:00", "Z")
    elif change == "timestamp_fraction":
        raw["observed_at"] = raw["observed_at"][:19]+".100+00:00"
    elif change == "whole_source_5001":
        report["grids"][0]["note"] = "x"*3000
    raw["report_json"] = canonical_json(report)
    raw["report_sha256"] = payload_hash(report)
    raw["changed_since_selection"] = raw["report_sha256"] != raw["selected_report_sha256"]
    scoped = dict(raw["scope"])
    del scoped["connection_scope"]
    scope_sha = payload_hash(dict(scoped, contract="elation-lab-patient-scope.v1", connection_scope_sha256=read.binding_digest))
    observation = {k: v for k, v in raw.items() if k not in ("scope", "source_sha256")}
    raw["source_sha256"] = None if change == "reader_hash_null" else payload_hash(dict(observation, contract="elation-lab-report.v1", scope_sha256=scope_sha))

    def source():
        return f.s.scalar(text("SELECT public.ehr_lab_source_text(CAST(:raw AS jsonb))"), dict(raw=canonical_json(raw)))

    if change == "whole_source_5001":
        # Exact one-character boundary, with every original field still valid.
        target = 5001
        length = len(source())
        report["grids"][0]["note"] += "x"*max(0,target-length)
        if length > target:
            report["grids"][0]["note"] = report["grids"][0]["note"][:len(report["grids"][0]["note"])-(length-target)]
        raw["report_json"] = canonical_json(report)
        raw["report_sha256"] = payload_hash(report)
        observation = {k: v for k, v in raw.items() if k not in ("scope", "source_sha256")}
        raw["source_sha256"] = payload_hash(dict(observation, contract="elation-lab-report.v1", scope_sha256=scope_sha))
        assert len(source()) == target
    content = source()
    warnings = f.s.scalar(text("SELECT public.ehr_lab_warnings(CAST(:raw AS jsonb))"), dict(raw=canonical_json(raw)))
    item = payload["public"]["item"]
    contentsha = f.s.scalar(text("SELECT encode(sha256(convert_to(:source,'UTF8')),'hex')"), dict(source=content))
    item.update(report_json=raw["report_json"], changed_since_selection=raw["changed_since_selection"], warnings=warnings,
        source_content=content, content_sha256=contentsha)
    item["sha256"] = ehr.item_hash("verified_lab_report", item)
    payload["public"]["observed_at"] = raw["observed_at"].replace("+00:00", "Z")
    identity = json.loads(raw["patient"]["identity_json"])
    payload["public"]["patient_identity_json"] = canonical_json({k: identity[k] for k in ("first_name","last_name","dob")})
    payload["private"]["reader_snapshot_json"] = canonical_json(raw)
    payload["private"]["review_sha256"] = None if change == "review_hash_null" else payload_hash(dict(
        contract="elation-lab-review-snapshot.v1", scope_sha256=scope_sha, observation_sha256=raw["source_sha256"],
        parent_candidates_sha256=raw["parent_candidates_sha256"], report_id=raw["report_id"], patient_identity_sha256=raw["patient"]["identity_sha256"],
        source_content_sha256=contentsha, warnings=warnings, completeness="selected_report_api_fields_only"))
    assert valid() is False
    with pytest.raises(IntegrityError) as rejected:
        with f.s.begin_nested():
            insert_lab_snapshot(f, read, payload)
    assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    assert f.s.scalar(select(func.count()).select_from(EhrReadSnapshot).where(EhrReadSnapshot.observation_id == read.id)) == 0
