"""Real-patient recording gate for capture admission (T-REL-6).

Process configuration cannot enable real-patient recording. Box flags take
effect only when clinic approval, BAA evidence, and PHI authorization refs are
all present, and only while the kill switch is not engaged. Synthetic and demo
visits remain admissible through this gate regardless of those flags.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from cosmas_os.application import workspace as ws
from cosmas_os.models import AppointmentObservation, BoxContext, PatientLink

RecordingClass = Literal["synthetic", "demo", "real"]
REFUSED = "real_patient_recording_refused"
RECORDING_CLASSES = frozenset({"synthetic", "demo", "real"})


def evidence_refs_present(runtime) -> bool:
    """True only when all three compliance evidence refs are nonempty."""
    return bool(
        getattr(runtime, "clinic_approval_ref", None)
        and getattr(runtime, "baa_evidence_ref", None)
        and getattr(runtime, "phi_authorization_ref", None)
    )


def real_patient_recording_effective(*, box: BoxContext, runtime) -> bool:
    """Box switch is on, kill is clear, and evidence refs are all present."""
    if not box.real_patient_recording_enabled:
        return False
    if box.real_patient_recording_kill_engaged:
        return False
    return evidence_refs_present(runtime)


def visit_recording_class(
    appointment: AppointmentObservation, patient: PatientLink | None = None
) -> RecordingClass:
    """Prefer the visit class; fall back to the patient link; else synthetic."""
    value = getattr(appointment, "recording_class", None) or "synthetic"
    if value not in RECORDING_CLASSES and patient is not None:
        value = getattr(patient, "recording_class", None) or "synthetic"
    if value not in RECORDING_CLASSES:
        value = "synthetic"
    return value  # type: ignore[return-value]


def require_recording_start_allowed(
    session: Session,
    *,
    box_id: str,
    appointment: AppointmentObservation,
    runtime,
) -> None:
    """Refuse real-patient capture starts when the gate is not effective.

    Synthetic and demo classes always pass this gate. Sign-in and notes are
    unrelated and never call this helper.
    """
    kind = visit_recording_class(appointment)
    if kind in {"synthetic", "demo"}:
        return
    box = session.get(BoxContext, box_id)
    if box is None:
        raise ws.WorkspaceError(REFUSED, 403)
    # Re-read kill/enable on every start so ops flips apply without restart.
    session.refresh(box)
    if real_patient_recording_effective(box=box, runtime=runtime):
        return
    raise ws.WorkspaceError(REFUSED, 403)
