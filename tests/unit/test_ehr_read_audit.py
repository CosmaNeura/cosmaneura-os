"""C6: PHI-free EHR read audit and per-practice resource scope."""

from __future__ import annotations

import io
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cosmas_os import ehr_read_audit as audit
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.log_scrub import REDACTED, LogScrubFilter, scrub_text
from cosmas_os.models import AuditEvent

CANARY_NAME = "Zara Zedstone"
CANARY_DOB = "1980-04-02"
CANARY_MRN = "SYNTH-MRN-9911"


class _FakeSession:
    def __init__(self, row=None):
        self.row = row
        self.added: list[object] = []
        self.committed = 0
        self.flushed = 0

    def scalar(self, _query):
        return self.row

    def get(self, _cls, _identifier):
        return None

    def add(self, item):
        self.added.append(item)

    def flush(self):
        self.flushed += 1

    def commit(self):
        self.committed += 1


def test_default_allowed_resources_cover_todays_live_reads():
    assert audit.DEFAULT_ALLOWED_RESOURCES == frozenset(
        {
            "Patient",
            "Appointment",
            "Encounter",
            "AllergyIntolerance",
            "MedicationRequest",
            "Condition",
        }
    )
    # Today's observe/verify/problems/medications/allergies map into that default.
    for kind in ("window", "verify", "problems", "medications", "core_allergies", "core_medications",
                 "core_patients", "fhir_patients", "fhir_medications"):
        assert audit.resource_type_for_kind(kind) in audit.DEFAULT_ALLOWED_RESOURCES
    # Labs stay outside the default so enabling them needs an explicit practice allow.
    assert audit.resource_type_for_kind("lab_reports") == "Observation"
    assert "Observation" not in audit.DEFAULT_ALLOWED_RESOURCES


def test_missing_practice_scope_uses_default_allow_list():
    session = _FakeSession(row=None)
    assert audit.allowed_resources(session, str(uuid4()), str(uuid4())) == audit.DEFAULT_ALLOWED_RESOURCES


def test_disallowed_resource_is_refused_as_unsupported_and_audited():
    session = _FakeSession(row=None)
    box_id, connection_id, actor = str(uuid4()), str(uuid4()), str(uuid4())
    with pytest.raises(WorkspaceError, match="unsupported") as raised:
        audit.ensure_resource_allowed(
            session,
            box_id=box_id,
            connection_id=connection_id,
            resource_type="DocumentReference",
            actor_principal_id=actor,
            vendor="athena",
            practice_id="195900",
            request_hash="a" * 64,
            vendor_request_id="vendor-req-canary-9911",
        )
    assert raised.value.status == 404
    assert session.committed == 1
    assert len(session.added) == 1
    event = session.added[0]
    assert isinstance(event, AuditEvent)
    assert event.event_type == audit.EVENT_TYPE
    assert event.actor_principal_id == actor
    assert event.outcome == "unsupported"
    assert event.detail["resource_type"] == "DocumentReference"
    assert event.detail["vendor"] == "athena"
    assert event.detail["result_count"] == 0
    assert event.detail["connection_id"] == connection_id
    assert event.detail["practice_id"] == "195900"
    assert event.detail["request_hash"] == "a" * 64
    assert event.detail["vendor_request_id_hash"] == audit.hash_vendor_request_id("vendor-req-canary-9911")
    assert "vendor_request_id" not in event.detail
    blob = str(event.detail)
    assert "vendor-req-canary-9911" not in blob


def test_synthetic_read_audits_without_phi_fields():
    session = _FakeSession()
    connection_id = str(uuid4())
    request_hash = "b" * 64
    event = audit.record_ehr_read_audit(
        session,
        box_id=str(uuid4()),
        actor_principal_id=str(uuid4()),
        connection_id=connection_id,
        practice_id="910",
        vendor="elation",
        resource_type="Appointment",
        result_count=2,
        outcome="ok",
        request_hash=request_hash,
        vendor_request_id="elation-trace-canary",
        # Callers must never pass PHI; this asserts the helper strips forbidden keys.
        request_body={"action": "observe", "name": CANARY_NAME, "dob": CANARY_DOB},
    )
    assert event.outcome == "ok"
    assert event.detail["connection_id"] == connection_id
    assert event.detail["practice_id"] == "910"
    assert event.detail["vendor"] == "elation"
    assert event.detail["resource_type"] == "Appointment"
    assert event.detail["result_count"] == 2
    assert event.detail["request_hash"] == request_hash
    assert event.detail["vendor_request_id_hash"] == audit.hash_vendor_request_id(
        "elation-trace-canary"
    )
    assert "name" not in event.detail and "dob" not in event.detail
    serialized = repr(event.detail) + repr(event.__dict__)
    for canary in (CANARY_NAME, CANARY_DOB, CANARY_MRN, "elation-trace-canary"):
        assert canary not in serialized


def test_audit_and_logs_never_keep_canary_name_or_dob(caplog):
    session = _FakeSession()
    logger = logging.getLogger("cosmas_os.ehr_read_audit")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(LogScrubFilter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with caplog.at_level(logging.INFO, logger="cosmas_os.ehr_read_audit"):
            audit.record_ehr_read_audit(
                session,
                box_id=str(uuid4()),
                actor_principal_id=str(uuid4()),
                connection_id=str(uuid4()),
                practice_id="910",
                vendor="elation",
                resource_type="Patient",
                result_count=1,
                outcome="ok",
                request_hash="c" * 64,
            )
            # Accidental PHI in a nearby log line must still be scrubbed.
            logger.info(
                "follow-up patient_name=%s dob=%s mrn=%s",
                CANARY_NAME,
                CANARY_DOB,
                CANARY_MRN,
            )
    finally:
        logger.removeHandler(handler)

    event = session.added[0]
    assert isinstance(event, AuditEvent)
    joined = "\n".join(
        [
            repr(event.detail),
            stream.getvalue(),
            "\n".join(record.getMessage() for record in caplog.records),
        ]
    )
    assert CANARY_NAME not in joined
    assert CANARY_DOB not in joined
    assert CANARY_MRN not in joined
    assert "patient_name=" + REDACTED in scrub_text(
        f"patient_name={CANARY_NAME} dob={CANARY_DOB} mrn={CANARY_MRN}"
    ) or REDACTED in scrub_text(f"patient_name={CANARY_NAME}")


def test_result_count_from_payload_counts_items_only():
    payload = {
        "public": {
            "kind": "window",
            "items": [{"handle": "1"}, {"handle": "2"}],
            "practice": {"label": CANARY_NAME},
        },
        "private": {
            "items": [
                {"appointment": {"patient_id": "930"}, "patient": {"first_name": CANARY_NAME, "dob": CANARY_DOB}},
            ]
        },
    }
    assert audit.result_count_from_payload(payload) == 2


def test_audit_stored_read_uses_binding_vendor_and_kind_mapping():
    connection_id = str(uuid4())
    binding = SimpleNamespace(vendor="tebra", connection_id=connection_id, practice_id=None)
    read = SimpleNamespace(
        box_id=str(uuid4()),
        owner_id=str(uuid4()),
        connection_id=connection_id,
        practice_id=None,
        binding_id=str(uuid4()),
        kind="fhir_medications",
        request_hash="d" * 64,
        request_json={"provider": "tebra", "protocol": "fhir", "action": "fhir_medications"},
    )

    class Session(_FakeSession):
        def get(self, _cls, _identifier):
            return binding

    session = Session()
    event = audit.audit_stored_read(
        session,
        read,
        {"public": {"kind": "fhir_medications", "items": [{"handle": "m1"}]}},
    )
    assert event.detail["vendor"] == "tebra"
    assert event.detail["resource_type"] == "MedicationRequest"
    assert event.detail["result_count"] == 1
    assert event.outcome == "ok"


def test_migration_is_additive_only():
    from pathlib import Path

    text = Path("migrations/versions/z35e1b98a742_ehr_practice_resource_scopes.py").read_text()
    assert "CREATE TABLE ehr_practice_resource_scopes" in text
    assert "down_revision = \"y24f0a87c631\"" in text
    for banned in ("DROP TABLE", "DROP COLUMN", "ALTER TABLE", "DELETE FROM"):
        assert banned not in text.upper().replace("DOWNGRADE", "")
    # Downgrade refuses destructive history rewrites.
    assert "Raise RuntimeError" in text or "raise RuntimeError" in text


def test_c1_connector_resource_names_map_to_fhir_allow_list():
    assert audit.connector_resource_to_fhir("appointments") == "Appointment"
    assert audit.connector_resource_to_fhir("patients") == "Patient"
    assert audit.connector_resource_to_fhir("medications") == "MedicationRequest"
    assert audit.connector_resource_to_fhir("allergies") == "AllergyIntolerance"
    assert audit.connector_resource_to_fhir("problems") == "Condition"
    assert audit.connector_resource_to_fhir("labs") == "Observation"
    assert audit.connector_resource_to_fhir("visit") == "Encounter"
    assert audit.connector_resource_to_fhir("visit_link_status") is None
    assert audit.connector_resource_to_fhir("Appointment") == "Appointment"


def test_session_practice_scope_matches_c1_allow_practice_hook():
    """Shape matches plugins.ehr.hooks.PracticeScopeConfig once #258 merges."""
    connection_id = str(uuid4())
    session = _FakeSession(
        row=SimpleNamespace(allowed_resources=["Patient", "Appointment", "Condition"])
    )
    scope = audit.SessionPracticeScopeConfig(session=session, box_id=str(uuid4()))
    assert scope.allow_practice(
        vendor_id="elation", practice_ref=connection_id, resource="appointments"
    )
    assert scope.allow_practice(
        vendor_id="elation", practice_ref=connection_id, resource="Appointment"
    )
    assert not scope.allow_practice(
        vendor_id="elation", practice_ref=connection_id, resource="labs"
    )
    assert not scope.allow_practice(
        vendor_id="elation", practice_ref="", resource="appointments"
    )
    assert not scope.allow_practice(
        vendor_id="elation", practice_ref=connection_id, resource="visit_link_status"
    )


def test_session_phi_free_read_audit_matches_c1_record_read_hook():
    """Shape matches plugins.ehr.hooks.PhiFreeReadAudit once #258 merges."""
    session = _FakeSession()
    box_id, actor, practice_ref = str(uuid4()), str(uuid4()), str(uuid4())
    hook = audit.SessionPhiFreeReadAudit(
        session=session, box_id=box_id, actor_principal_id=actor, commit=True
    )
    hook.record_read(
        vendor_id="athena",
        resource="allergies",
        target="sandbox",
        practice_ref=practice_ref,
        outcome="allowed",
    )
    hook.record_read(
        vendor_id="athena",
        resource="labs",
        target="sandbox",
        practice_ref=practice_ref,
        outcome="refused",
    )
    assert session.committed == 2
    assert len(session.added) == 2
    allowed, refused = session.added
    assert allowed.outcome == "allowed"
    assert allowed.detail["resource_type"] == "AllergyIntolerance"
    assert allowed.detail["connector_resource"] == "allergies"
    assert allowed.detail["target"] == "sandbox"
    assert allowed.detail["connection_id"] == practice_ref
    assert allowed.actor_principal_id == actor
    assert refused.outcome == "refused"
    assert refused.detail["resource_type"] == "Observation"
    blob = repr(allowed.detail) + repr(refused.detail)
    assert CANARY_NAME not in blob and CANARY_DOB not in blob
