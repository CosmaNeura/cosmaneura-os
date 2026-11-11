"""T-REL-6 real-patient recording gate: synthetic fixtures only, no PHI."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cosmas_os.application import real_patient_recording as gate
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.models import AppointmentObservation, BoxContext, PatientLink

REPO = Path(__file__).resolve().parents[2]


def runtime(**refs):
    return SimpleNamespace(
        clinic_approval_ref=refs.get("clinic"),
        baa_evidence_ref=refs.get("baa"),
        phi_authorization_ref=refs.get("phi"),
    )


def box(*, enabled=False, killed=True):
    return BoxContext(
        id=str(uuid4()),
        display_name="Invented Clinic",
        real_patient_recording_enabled=enabled,
        real_patient_recording_kill_engaged=killed,
    )


def appointment(*, recording_class="synthetic"):
    return AppointmentObservation(
        id=str(uuid4()),
        box_id=str(uuid4()),
        external_id="invented-appointment-ref",
        source="cosmaneura_core",
        patient_label="Invented Patient",
        recording_class=recording_class,
    )


class MemorySession:
    def __init__(self, box_row: BoxContext):
        self.box = box_row
        self.refreshed = 0

    def get(self, model, key):
        assert model is BoxContext
        assert key == self.box.id
        return self.box

    def refresh(self, row):
        assert row is self.box
        self.refreshed += 1


def test_defaults_keep_real_patient_recording_off():
    settings = Settings()
    assert settings.real_patient_recording_enabled is False
    row = box()
    assert row.real_patient_recording_enabled is False
    assert row.real_patient_recording_kill_engaged is True
    assert gate.real_patient_recording_effective(box=row, runtime=runtime()) is False


def test_process_env_cannot_enable_real_patient_recording():
    settings = Settings.model_validate({"real_patient_recording_enabled": True})
    errors = settings.runtime_configuration_errors()
    assert any("REAL_PATIENT_RECORDING_ENABLED must remain false" in item for item in errors)


def test_shipped_profiles_never_set_real_patient_recording_enabled():
    needles = (
        "REAL_PATIENT_RECORDING_ENABLED=true",
        "REAL_PATIENT_RECORDING_ENABLED': 'true'",
        'REAL_PATIENT_RECORDING_ENABLED": "true"',
        "real_patient_recording_enabled: true",
        '"real_patient_recording_enabled": true',
        "real_patient_recording_enabled=True",
    )
    paths = [
        REPO / "infra/standalone/render.mjs",
        REPO / "clients/shared/beta-feature-profile.mjs",
        REPO / "clients/shared/independent-beta-feature-profile.test.mjs",
        REPO / "infra/beta/environment/modules/workspace-runtime/main.tf",
        REPO / "infra/beta/environment/container_apps.tf",
        REPO / ".env.example",
        REPO / ".env.hosted.example",
        REPO / "web/.env.hosted.example",
        REPO / "Dockerfile",
        REPO / "Dockerfile.web",
    ]
    for path in paths:
        text = path.read_text()
        for needle in needles:
            assert needle not in text, f"{path} must not enable real-patient recording ({needle})"
    assert "real_patient_recording_enabled: bool = False" in (
        REPO / "src/cosmas_os/config.py"
    ).read_text()


@pytest.mark.parametrize("missing", ["clinic", "baa", "phi"])
def test_switch_on_without_all_refs_is_treated_as_off(missing):
    refs = {"clinic": "clinic-ref", "baa": "baa-ref", "phi": "phi-ref"}
    refs[missing] = None
    row = box(enabled=True, killed=False)
    assert gate.evidence_refs_present(runtime(**refs)) is False
    assert gate.real_patient_recording_effective(box=row, runtime=runtime(**refs)) is False
    session = MemorySession(row)
    with pytest.raises(ws.WorkspaceError, match=gate.REFUSED) as caught:
        gate.require_recording_start_allowed(
            session,  # type: ignore[arg-type]
            box_id=row.id,
            appointment=appointment(recording_class="real"),
            runtime=runtime(**refs),
        )
    assert caught.value.status == 403


def test_switch_on_with_refs_admits_real_patient_only_when_kill_clear():
    refs = runtime(clinic="clinic-ref", baa="baa-ref", phi="phi-ref")
    row = box(enabled=True, killed=True)
    session = MemorySession(row)
    with pytest.raises(ws.WorkspaceError, match=gate.REFUSED):
        gate.require_recording_start_allowed(
            session,  # type: ignore[arg-type]
            box_id=row.id,
            appointment=appointment(recording_class="real"),
            runtime=refs,
        )
    row.real_patient_recording_kill_engaged = False
    gate.require_recording_start_allowed(
        session,  # type: ignore[arg-type]
        box_id=row.id,
        appointment=appointment(recording_class="real"),
        runtime=refs,
    )
    assert session.refreshed >= 1


def test_flipping_kill_switch_stops_next_start_without_restart():
    refs = runtime(clinic="clinic-ref", baa="baa-ref", phi="phi-ref")
    row = box(enabled=True, killed=False)
    session = MemorySession(row)
    visit = appointment(recording_class="real")
    gate.require_recording_start_allowed(
        session,  # type: ignore[arg-type]
        box_id=row.id,
        appointment=visit,
        runtime=refs,
    )
    row.real_patient_recording_kill_engaged = True
    with pytest.raises(ws.WorkspaceError, match=gate.REFUSED) as caught:
        gate.require_recording_start_allowed(
            session,  # type: ignore[arg-type]
            box_id=row.id,
            appointment=visit,
            runtime=refs,
        )
    assert caught.value.code == gate.REFUSED


@pytest.mark.parametrize("recording_class", ["synthetic", "demo"])
def test_synthetic_or_demo_records_with_switch_off(recording_class):
    row = box(enabled=False, killed=True)
    session = MemorySession(row)
    gate.require_recording_start_allowed(
        session,  # type: ignore[arg-type]
        box_id=row.id,
        appointment=appointment(recording_class=recording_class),
        runtime=runtime(),
    )
    assert session.refreshed == 0


def test_existing_default_class_is_synthetic_and_blocks_only_real():
    assert appointment().recording_class == "synthetic"
    assert AppointmentObservation.__table__.c.recording_class.default.arg == "synthetic"
    assert PatientLink.__table__.c.recording_class.default.arg == "synthetic"
    assert BoxContext.__table__.c.real_patient_recording_enabled.default.arg is False
    assert BoxContext.__table__.c.real_patient_recording_kill_engaged.default.arg is True
    assert gate.visit_recording_class(appointment()) == "synthetic"
    assert gate.visit_recording_class(
        SimpleNamespace(recording_class=None)
    ) == "synthetic"


def test_data_mode_and_ehr_real_data_defaults_unchanged():
    settings = Settings()
    assert settings.data_mode == "synthetic"
    assert settings.cosmas_ehr_real_data_enabled is False


def test_sign_in_and_notes_modules_do_not_import_recording_gate():
    # Existing users' sign-in and notes must not depend on this gate.
    note_paths = [
        REPO / "src/cosmas_os/application/note_review.py",
        REPO / "src/cosmas_os/application/core_note_review.py",
        REPO / "src/cosmas_os/application/clinical_note_share.py",
        REPO / "src/cosmas_os/api/auth.py",
    ]
    for path in note_paths:
        if not path.exists():
            continue
        text = path.read_text()
        assert "real_patient_recording" not in text, path.name
