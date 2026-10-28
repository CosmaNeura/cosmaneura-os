"""Host-only fresh synthetic practice bootstrap; no platform or connector adapter.

Reservation requires an empty, explicitly marked dedicated PostgreSQL database.
Seeding then requires the existing verified first-owner setup to have completed.
Neither phase can bind a login by email, copy records, or modify another practice.
"""

from datetime import UTC, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from alembic.script import ScriptDirectory
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select, text

from cosmas_os.application import practice_access
from cosmas_os.application.beta_bootstrap import BetaBootstrapManifest, _matches_runtime
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.model_registry import metadata
from cosmas_os.models import (
    AppointmentObservation,
    AuditEvent,
    BoxContext,
    ExternalIdentity,
    PatientLink,
)
from cosmas_os.practice_setup_models import PracticeOwnerReservation, PracticeSetupProfile

CONTRACT = "cosmas-os/standalone-synthetic-practice/v1"
SOURCE = "cosmabot_synthetic"
_LOCK = 187463921  # Same lock as the existing first-owner reservation.


class StandalonePracticeError(Exception):
    """Bounded public failure; never include manifest, identity or database inputs."""


def _uuid4(value):
    if not isinstance(value, str):
        raise ValueError("explicit canonical UUIDv4 required")
    parsed = UUID(value)
    if str(parsed) != value or parsed.version != 4:
        raise ValueError("explicit canonical UUIDv4 required")
    return parsed


class SyntheticPatient(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    label: str = Field(min_length=10, max_length=120, strict=True)

    _id = field_validator("id", mode="before")(_uuid4)

    @field_validator("label")
    @classmethod
    def invented_label(cls, value):
        if not value.startswith("Invented ") or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("explicit invented patient label required")
        return value


class SyntheticAppointment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    patient_id: UUID
    start_at: AwareDatetime

    _ids = field_validator("id", "patient_id", mode="before")(_uuid4)

    @field_validator("start_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)


class StandalonePracticeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["cosmas-os/standalone-synthetic-practice/v1"]
    provenance: Literal["fresh_invented_cosmabot_practice"]
    confirm_synthetic_only: Literal[True]
    instance_id: UUID
    dataset_id: UUID
    database_name: str = Field(pattern=r"^cosmabot_standalone_[a-z0-9_]{1,40}$", strict=True)
    identity: BetaBootstrapManifest
    patients: list[SyntheticPatient] = Field(min_length=1, max_length=12)
    appointments: list[SyntheticAppointment] = Field(min_length=1, max_length=24)

    _ids = field_validator("instance_id", "dataset_id", mode="before")(_uuid4)

    @field_validator("confirm_synthetic_only", mode="before")
    @classmethod
    def exact_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit synthetic confirmation required")
        return value

    @model_validator(mode="after")
    def distinct_local_namespace(self):
        identity = self.identity
        if (identity.box_id.version != 4 or "synthetic" not in identity.clinic_display_name.casefold()
                or len(identity.clinic_display_name) > 120 or len(identity.owner_display_name) > 120):
            raise ValueError("fresh Box UUIDv4 and visibly synthetic practice name required")
        patient_ids = {p.id for p in self.patients}
        identifiers = [self.instance_id, self.dataset_id, identity.box_id,
                       *(p.id for p in self.patients), *(a.id for a in self.appointments)]
        if len(set(identifiers)) != len(identifiers) or any(a.patient_id not in patient_ids for a in self.appointments):
            raise ValueError("distinct local IDs and exact patient references required")
        return self


def _guard(s, runtime, manifest):
    try:
        runtime.validate_runtime_configuration()
    except (ValueError, RuntimeError):
        raise StandalonePracticeError("standalone_runtime_required") from None
    if (runtime.cosmas_env not in {"standalone_synthetic", "standalone_clerk_synthetic"} or runtime.data_mode != "synthetic"
            or not runtime.workspace_available
            or runtime.standalone_instance_id != str(manifest.instance_id)
            or not _matches_runtime(manifest.identity, runtime)
            or runtime.workspace_capture_backend != "disabled"):
        raise StandalonePracticeError("standalone_runtime_required")
    # These fields are inert only when absent/disabled, including inherited inputs.
    for name, value in runtime.model_dump().items():
        if (name.startswith("core_") or name.startswith("workspace_core_")
                or name.startswith("workspace_capture_") or name.startswith("workspace_athena_")
                or name in {"workspace_session_prep_enabled", "workspace_prep_enabled", "workspace_prep_work_enabled"}):
            if name != "workspace_capture_backend" and value:
                raise StandalonePracticeError("standalone_core_configuration_forbidden")
    if s.bind.dialect.name != "postgresql":
        raise StandalonePracticeError("owned_postgresql_required")
    s.execute(select(func.pg_advisory_xact_lock(_LOCK)))
    actual = s.scalar(text("SELECT current_database()"))
    marker = s.scalar(text("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()"))
    if actual != manifest.database_name or marker != "cosmabot-standalone:" + str(manifest.instance_id):
        raise StandalonePracticeError("standalone_database_ownership_required")
    schemas = set(s.scalars(text("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema'")))
    tables = set(s.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")))
    if (s.scalar(text("SELECT current_schema()")) != "public" or schemas != {"public"}
            or tables != set(metadata.tables) | {"alembic_version"}):
        raise StandalonePracticeError("standalone_migrated_database_required")
    expected_head = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "migrations")).get_current_head()
    if list(s.scalars(text("SELECT version_num FROM alembic_version"))) != [expected_head]:
        raise StandalonePracticeError("standalone_migrated_database_required")


def _digest(manifest):
    return payload_hash(manifest.model_dump(mode="json"))


def _detail(manifest):
    return {"contract": CONTRACT, "manifest_sha256": _digest(manifest),
            "provenance": manifest.provenance, "source": SOURCE,
            "patient_count": len(manifest.patients), "appointment_count": len(manifest.appointments)}


def _receipt(s, manifest, phase):
    rows = list(s.scalars(select(AuditEvent).where(
        AuditEvent.aggregate_type == "standalone_practice", AuditEvent.aggregate_id == str(manifest.dataset_id),
        AuditEvent.event_type == "standalone_practice." + phase)))
    if not rows:
        return None
    if (len(rows) != 1 or rows[0].box_id != str(manifest.identity.box_id)
            or rows[0].payload_hash != _digest(manifest) or rows[0].detail != _detail(manifest)):
        raise StandalonePracticeError("standalone_manifest_conflict")
    return rows[0]


def _audit(s, manifest, phase, owner=None):
    s.add(AuditEvent(box_id=str(manifest.identity.box_id), aggregate_type="standalone_practice",
        aggregate_id=str(manifest.dataset_id), event_type="standalone_practice." + phase,
        actor_principal_id=owner, outcome=phase, payload_hash=_digest(manifest), detail=_detail(manifest)))


def _reservation(s, manifest):
    identity = manifest.identity
    boxes = list(s.scalars(select(BoxContext)))
    row = s.get(PracticeOwnerReservation, str(identity.box_id))
    if (len(boxes) != 1 or boxes[0].id != str(identity.box_id) or boxes[0].display_name != identity.clinic_display_name
            or row is None or row.manifest_sha256 != payload_hash(identity.model_dump(mode="json"))
            or (row.issuer, row.subject, row.organization_id, row.reviewed_by, row.evidence_ref) != (
                identity.clerk_issuer, identity.clerk_subject, identity.clerk_organization_id,
                identity.reviewed_by, identity.evidence_ref)):
        raise StandalonePracticeError("standalone_reservation_conflict")
    return row


def _result(manifest, phase):
    return {"contract": CONTRACT, "phase": phase, "manifest_sha256": _digest(manifest),
            "patient_count": len(manifest.patients) if phase == "seeded" else 0,
            "appointment_count": len(manifest.appointments) if phase == "seeded" else 0,
            "identity_provider_changed": False, "owner_binding_checked": phase == "seeded",
            "platform_data_copied": False}


def reserve_standalone_practice(s, runtime, manifest):
    """Reserve an exact future owner; no principal or login access is granted."""
    try:
        _guard(s, runtime, manifest)
        if _receipt(s, manifest, "reserved"):
            _reservation(s, manifest)
        else:
            # Freeze all application tables while proving the dedicated DB is empty.
            names = ", ".join(s.bind.dialect.identifier_preparer.format_table(t) for t in metadata.sorted_tables)
            s.execute(text("LOCK TABLE " + names + " IN SHARE ROW EXCLUSIVE MODE"))
            if any(s.scalar(select(func.count()).select_from(t)) for t in metadata.sorted_tables):
                raise StandalonePracticeError("standalone_empty_database_required")
            identity = manifest.identity
            s.add(BoxContext(id=str(identity.box_id), display_name=identity.clinic_display_name))
            s.flush()
            s.add(PracticeOwnerReservation(box_id=str(identity.box_id), issuer=identity.clerk_issuer,
                organization_id=identity.clerk_organization_id, subject=identity.clerk_subject,
                reviewed_by=identity.reviewed_by, evidence_ref=identity.evidence_ref,
                manifest_sha256=payload_hash(identity.model_dump(mode="json")),
                expires_at=practice_access._now(s) + timedelta(days=7)))
            _audit(s, manifest, "reserved")
        s.commit()
        return _result(manifest, "reserved")
    except Exception:
        s.rollback()
        raise


def _owner(s, manifest):
    identity = manifest.identity
    reservation = _reservation(s, manifest)
    member = practice_access.VerifiedMember(str(identity.box_id), identity.clerk_issuer,
                                          identity.clerk_organization_id, identity.clerk_subject)
    principal = practice_access._binding(s, member)
    binding = s.scalar(select(ExternalIdentity).where(ExternalIdentity.issuer == member.issuer,
                                                     ExternalIdentity.subject == member.subject))
    profile = s.get(PracticeSetupProfile, str(identity.box_id))
    if (reservation.consumed_at is None or principal is None or not principal.is_owner
            or principal.tombstoned_at is not None or principal.display_name != identity.owner_display_name
            or binding is None or binding.reviewed_by != identity.reviewed_by or binding.evidence_ref != identity.evidence_ref
            or profile is None or profile.owner_id != principal.id
            or profile.display_name != identity.clinic_display_name
            or profile.owner_display_name != identity.owner_display_name):
        raise StandalonePracticeError("standalone_verified_owner_setup_required")
    return principal


def _patient_key(manifest, patient):
    return "cosmabot-synthetic:" + ":".join(map(str, (manifest.instance_id, manifest.dataset_id, patient.id)))


def _appointment_key(manifest, appointment):
    return "cosmabot-synthetic:" + str(manifest.dataset_id) + ":" + str(appointment.id)


def _verify_seed(s, manifest, owner):
    labels = {p.id: p.label for p in manifest.patients}
    for patient in manifest.patients:
        row = s.get(PatientLink, str(patient.id))
        if (row is None or row.box_id != str(manifest.identity.box_id) or row.label != patient.label
                or row.source_pair_key != _patient_key(manifest, patient) or row.state != "confirmed"
                or row.confirmed_by_principal_id != owner.id or row.attested_at is None
                or row.revoked_at is not None or row.source_owner_id is not None or row.source_account_id is not None):
            raise StandalonePracticeError("standalone_seed_conflict")
    for appointment in manifest.appointments:
        row = s.get(AppointmentObservation, str(appointment.id))
        if (row is None or row.box_id != str(manifest.identity.box_id) or row.source != SOURCE
                or row.external_id != _appointment_key(manifest, appointment)
                or row.patient_link_id != str(appointment.patient_id) or row.patient_label != labels[appointment.patient_id]
                or row.start_at != appointment.start_at or row.source_owner_id is not None
                or row.source_local_start is not None or row.source_sha256 is not None):
            raise StandalonePracticeError("standalone_seed_conflict")


def seed_standalone_practice(s, runtime, manifest):
    """Load the exact invented fixture only after authenticated owner setup."""
    try:
        _guard(s, runtime, manifest)
        if not _receipt(s, manifest, "reserved"):
            raise StandalonePracticeError("standalone_reservation_required")
        owner = _owner(s, manifest)
        if not _receipt(s, manifest, "seeded"):
            if (s.scalar(select(func.count()).select_from(PatientLink))
                    or s.scalar(select(func.count()).select_from(AppointmentObservation))):
                raise StandalonePracticeError("standalone_empty_records_required")
            now = practice_access._now(s)
            labels = {p.id: p.label for p in manifest.patients}
            for patient in manifest.patients:
                s.add(PatientLink(id=str(patient.id), box_id=str(manifest.identity.box_id),
                    source_pair_key=_patient_key(manifest, patient), label=patient.label, state="confirmed",
                    confirmed_by_principal_id=owner.id, attested_at=now))
            s.flush()
            for appointment in manifest.appointments:
                s.add(AppointmentObservation(id=str(appointment.id), box_id=str(manifest.identity.box_id),
                    external_id=_appointment_key(manifest, appointment), source=SOURCE,
                    patient_link_id=str(appointment.patient_id), patient_label=labels[appointment.patient_id],
                    start_at=appointment.start_at))
            _audit(s, manifest, "seeded", owner.id)
            s.flush()
        _verify_seed(s, manifest, owner)
        s.commit()
        return _result(manifest, "seeded")
    except Exception:
        s.rollback()
        raise
