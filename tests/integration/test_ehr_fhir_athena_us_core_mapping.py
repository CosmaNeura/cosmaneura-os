"""athena Preview accepted on shared FHIR custody; mapped US Core sources carry provenance."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.adapters.ehr_fhir_vendor import ATHENA_FHIR_ENVIRONMENT, reviewed_medications_label
from cosmas_os.adapters.tebra_fhir_read_runtime import (
    TebraFhirAuthorizedPatient,
    TebraFhirConnectionScope,
)
from cosmas_os.application.ehr_fhir_us_core_mapping import (
    map_bundle_entries,
    map_patient_identity,
    resource_id_hash,
)
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ehr_read_models import EhrFhirPatientGrant, EhrReadBinding
from cosmas_os.models import EncounterWorkspace

signed_workspace = _signed_workspace
FIXTURES = Path(__file__).resolve().parents[1] / "unit" / "fixtures" / "ehr_fhir"
READ_TIME = datetime(2026, 11, 6, 17, 30, 0, tzinfo=UTC)


def test_athena_preview_fhir_binding_and_grant_accepted(signed_workspace, session):
    f = signed_workspace
    workspace = session.get(EncounterWorkspace, f.workspace["id"])
    assert workspace is not None and workspace.patient_link_id is not None
    patient = json.loads((FIXTURES / "patient.json").read_text())
    mapped = map_patient_identity(patient, vendor="athena", read_time=READ_TIME)
    scope = TebraFhirConnectionScope(
        UUID(f.box), UUID(f.actor), UUID(f.binding.id), uuid4(), uuid4(),
        "athena Preview 195900", vendor="athena",
    )
    binding = EhrReadBinding(
        box_id=f.box, owner_id=f.actor, account_id=f.binding.id, vendor="athena", protocol="fhir",
        connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
        practice_id=None, practice_name=scope.display_label, environment=ATHENA_FHIR_ENVIRONMENT,
        binding_digest=scope.commitment(), state="active",
    )
    session.add(binding)
    session.flush()
    authorized = TebraFhirAuthorizedPatient(
        uuid4(), scope, UUID(workspace.id), UUID(workspace.patient_link_id), mapped.fhir_patient_id,
        "b" * 64, mapped.identity_json, mapped.identity_sha256,
    )
    grant = EhrFhirPatientGrant(
        id=str(authorized.grant_id), box_id=f.box, owner_id=f.actor, account_id=f.binding.id,
        binding_id=binding.id, workspace_id=workspace.id, patient_link_id=workspace.patient_link_id,
        fhir_patient_id=authorized.fhir_patient_id, authorization_sha256=authorized.authorization_sha256,
        identity_json=authorized.identity_json, identity_sha256=authorized.identity_sha256,
        grant_digest=authorized.commitment(), state="active",
    )
    session.add(grant)
    session.commit()

    current = session.execute(text("SELECT public.ehr_fhir_grant_current(:gid)"), {"gid": grant.id}).scalar_one()
    assert current is True
    digest = session.execute(
        text("SELECT public.ehr_read_binding_digest(b) FROM public.ehr_read_bindings b WHERE b.id=:id"),
        {"id": binding.id},
    ).scalar_one()
    assert digest == scope.commitment()
    assert digest == binding.binding_digest

    # athena FHIR remains preview-only; synthetic environment must stay refused.
    bad = EhrReadBinding(
        box_id=f.box, owner_id=f.actor, account_id=f.binding.id, vendor="athena", protocol="fhir",
        connection_id=str(uuid4()), credential_generation=str(uuid4()), practice_id=None,
        practice_name="bad athena fhir", environment="synthetic", binding_digest="c" * 64, state="active",
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_mapped_us_core_sources_carry_review_provenance(signed_workspace):
    bundle = json.loads((FIXTURES / "us_core_synth_bundle.json").read_text())
    patient, sources = map_bundle_entries(bundle, vendor="athena", read_time=READ_TIME)
    assert patient is not None
    assert patient.provenance.as_dict() == {
        "vendor": "athena",
        "resource_type": "Patient",
        "resource_id_hash": resource_id_hash(patient.fhir_patient_id),
        "read_time": READ_TIME.isoformat(),
    }
    assert reviewed_medications_label("athena") == "Athena: reviewed medication records"
    med = next(source for source in sources if source.resource_type == "MedicationRequest")
    # Existing source-review flow admits exact source_content + content hash + provenance.
    assert med.content_sha256 == __import__("hashlib").sha256(med.source_content.encode()).hexdigest()
    assert med.provenance.vendor == "athena"
    assert med.display_label == "Athena: reviewed MedicationRequest"
    assert all(
        set(source.provenance.as_dict()) == {"vendor", "resource_type", "resource_id_hash", "read_time"}
        for source in sources
    )


def test_tebra_fhir_connection_digest_still_stable():
    scope = TebraFhirConnectionScope(
        UUID("11111111-1111-1111-1111-111111111111"),
        UUID("22222222-2222-2222-2222-222222222222"),
        UUID("33333333-3333-3333-3333-333333333333"),
        UUID("44444444-4444-4444-4444-444444444444"),
        UUID("55555555-5555-5555-5555-555555555555"),
        "Invented Tebra Clinical",
    )
    assert scope.vendor == "tebra"
    assert scope.commitment() == payload_hash({
        "contract": "tebra-fhir-connection-scope.v1",
        "fhir_base": "https://fhir.prd.cloud.tebra.com/fhir-request",
        "box_id": "11111111-1111-1111-1111-111111111111",
        "owner_id": "22222222-2222-2222-2222-222222222222",
        "account_id": "33333333-3333-3333-3333-333333333333",
        "connection_id": "44444444-4444-4444-4444-444444444444",
        "credential_generation": "55555555-5555-5555-5555-555555555555",
        "display_label": "Invented Tebra Clinical",
    })
