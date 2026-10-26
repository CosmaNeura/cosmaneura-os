"""Immutable read-only EHR observations and exact human selected-source custody."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import OwnerScope, WorkspaceScope, digest_check, json_check


def _uuid():
    return str(uuid4())


class EhrReadBinding(OwnerScope, Base):
    __tablename__ = "ehr_read_bindings"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "box_id", "owner_id"],
            ["external_identities.id", "external_identities.box_id", "external_identities.principal_id"]),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_ehr_read_binding_scope"),
        UniqueConstraint("id", "box_id", "owner_id", "account_id", name="uq_ehr_read_binding_account"),
        UniqueConstraint("box_id", "owner_id", "connection_id", "credential_generation", "practice_id",
            name="uq_ehr_read_binding_version"),
        Index("uq_ehr_read_binding_active", "box_id", "owner_id", "account_id", "connection_id",
            unique=True, postgresql_where=text("state = 'active'")),
        CheckConstraint("coalesce((protocol IS NULL AND vendor='elation' AND environment='sandbox' AND customer_id IS NULL AND practice_timezone IS NULL) OR "
            "(protocol IS NULL AND vendor='tebra' AND environment='synthetic' AND customer_id IS NOT NULL AND customer_id ~ '^[1-9][0-9]{0,9}$' "
            "AND customer_id::numeric<=2147483647 AND practice_id::numeric<=2147483647 "
            "AND practice_timezone IS NOT NULL) OR (protocol='fhir' AND vendor='tebra' AND environment='synthetic' "
            "AND practice_id IS NULL AND customer_id IS NULL AND practice_timezone IS NULL) OR (protocol='core' AND vendor='athena' AND environment IN ('preview','production') AND customer_id IS NULL AND practice_timezone IS NULL),false)", name="ck_ehr_read_binding_vendor"),
        CheckConstraint("coalesce((protocol='fhir' AND practice_id IS NULL) OR (protocol IS NULL AND practice_id IS NOT NULL "
            "AND practice_id ~ '^[1-9][0-9]*$' AND char_length(practice_id)<=19 "
            "AND practice_id::numeric<=9223372036854775807) OR (protocol='core' AND practice_id IS NOT NULL AND practice_id ~ '^[1-9][0-9]{0,17}$'),false)", name="ck_ehr_read_binding_practice"),
        CheckConstraint("char_length(practice_name) BETWEEN 1 AND 200 AND practice_name !~ '[[:cntrl:]]'",
            name="ck_ehr_read_binding_name"),
        CheckConstraint("(state='active' AND revoked_at IS NULL) OR (state='revoked' AND revoked_at IS NOT NULL)",
            name="ck_ehr_read_binding_state"),
        digest_check("binding_digest"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    vendor: Mapped[str] = mapped_column(String(16), nullable=False, default="elation")
    protocol: Mapped[str | None] = mapped_column(String(4))
    connection_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    credential_generation: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    practice_id: Mapped[str | None] = mapped_column(String(20))
    customer_id: Mapped[str | None] = mapped_column(String(10))
    practice_timezone: Mapped[str | None] = mapped_column(String(100))
    practice_name: Mapped[str] = mapped_column(String(200), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="sandbox")
    binding_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
        server_default=func.clock_timestamp())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EhrFhirPatientGrant(OwnerScope, Base):
    """Server-owned FHIR authority for one exact workspace patient; no SOAP IDs."""

    __tablename__ = "ehr_fhir_patient_grants"
    __table_args__ = (
        ForeignKeyConstraint(["binding_id", "box_id", "owner_id", "account_id"],
            ["ehr_read_bindings.id", "ehr_read_bindings.box_id", "ehr_read_bindings.owner_id", "ehr_read_bindings.account_id"]),
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]),
        UniqueConstraint("id", "box_id", "owner_id", "workspace_id", "patient_link_id", name="uq_ehr_fhir_grant_scope"),
        Index("uq_ehr_fhir_grant_active", "binding_id", "workspace_id", "patient_link_id", "fhir_patient_id", unique=True,
            postgresql_where=text("state='active'")),
        CheckConstraint("fhir_patient_id ~ '^[A-Za-z0-9.-]{1,64}$' AND fhir_patient_id NOT IN ('.','..')", name="ck_ehr_fhir_grant_patient"),
        CheckConstraint("char_length(identity_json) BETWEEN 2 AND 20000", name="ck_ehr_fhir_grant_identity_size"),
        CheckConstraint("(state='active' AND revoked_at IS NULL) OR (state='revoked' AND revoked_at IS NOT NULL)", name="ck_ehr_fhir_grant_state"),
        digest_check("authorization_sha256", "identity_sha256", "grant_digest"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    binding_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    fhir_patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_json: Mapped[str] = mapped_column(Text, nullable=False)
    identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EhrAthenaCorePatientGrant(OwnerScope, Base):
    """Server-owned independent Athena clinical authority; no schedule or Core-account inference."""

    __tablename__ = "ehr_athena_core_patient_grants"
    __table_args__ = (
        ForeignKeyConstraint(["binding_id", "box_id", "owner_id", "account_id"],
            ["ehr_read_bindings.id", "ehr_read_bindings.box_id", "ehr_read_bindings.owner_id", "ehr_read_bindings.account_id"]),
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]),
        UniqueConstraint("id", "box_id", "owner_id", "workspace_id", "patient_link_id", name="uq_ehr_athena_core_grant_scope"),
        Index("uq_ehr_athena_core_grant_active", "binding_id", "workspace_id", "patient_link_id", "department_id", "patient_id", unique=True,
            postgresql_where=text("state='active'")),
        CheckConstraint("patient_id ~ '^[1-9][0-9]{0,17}$' AND department_id ~ '^[1-9][0-9]{0,17}$'", name="ck_ehr_athena_core_grant_patient"),
        CheckConstraint("char_length(identity_json) BETWEEN 2 AND 20000", name="ck_ehr_athena_core_grant_identity_size"),
        CheckConstraint("(state='active' AND revoked_at IS NULL) OR (state='revoked' AND revoked_at IS NOT NULL)", name="ck_ehr_athena_core_grant_state"),
        CheckConstraint("char_length(department_label) BETWEEN 1 AND 200 AND department_label !~ '[[:cntrl:]]'", name="ck_ehr_athena_core_department_label"),
        digest_check("authorization_sha256", "identity_sha256", "grant_digest"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    binding_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_id: Mapped[str] = mapped_column(String(18), nullable=False)
    department_id: Mapped[str] = mapped_column(String(18), nullable=False)
    department_label: Mapped[str] = mapped_column(String(200), nullable=False)
    authorization_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_json: Mapped[str] = mapped_column(Text, nullable=False)
    identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EhrReadRequest(OwnerScope, Base):
    __tablename__ = "ehr_read_requests"
    __table_args__ = (
        ForeignKeyConstraint(["binding_id", "box_id", "owner_id", "account_id"],
            ["ehr_read_bindings.id", "ehr_read_bindings.box_id", "ehr_read_bindings.owner_id", "ehr_read_bindings.account_id"]),
        ForeignKeyConstraint(["parent_snapshot_id", "box_id", "owner_id"],
            ["ehr_read_snapshots.id", "ehr_read_snapshots.box_id", "ehr_read_snapshots.owner_id"],
            name="fk_ehr_read_request_parent", use_alter=True),
        ForeignKeyConstraint(["fhir_grant_id", "box_id", "owner_id", "workspace_id", "patient_link_id"],
            ["ehr_fhir_patient_grants.id", "ehr_fhir_patient_grants.box_id", "ehr_fhir_patient_grants.owner_id", "ehr_fhir_patient_grants.workspace_id", "ehr_fhir_patient_grants.patient_link_id"]),
        ForeignKeyConstraint(["athena_grant_id", "box_id", "owner_id", "workspace_id", "patient_link_id"],
            ["ehr_athena_core_patient_grants.id", "ehr_athena_core_patient_grants.box_id", "ehr_athena_core_patient_grants.owner_id", "ehr_athena_core_patient_grants.workspace_id", "ehr_athena_core_patient_grants.patient_link_id"]),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_ehr_read_request_scope"),
        UniqueConstraint("binding_id", "ordinal", name="uq_ehr_read_request_ordinal"),
        UniqueConstraint("box_id", "owner_id", "idempotency_key", name="uq_ehr_read_request_key"),
        CheckConstraint("ordinal BETWEEN 1 AND 500 AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'",
            name="ck_ehr_read_request_key"),
        CheckConstraint("(((kind='window' AND parent_snapshot_id IS NULL AND item_handle IS NULL) OR "
            "(kind IN ('verify','problems','medications') AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL)) "
            "AND workspace_id IS NULL AND patient_link_id IS NULL AND fhir_grant_id IS NULL AND athena_grant_id IS NULL) OR "
            "(kind IN ('fhir_patients','core_patients') AND parent_snapshot_id IS NULL AND item_handle IS NULL AND fhir_grant_id IS NULL "
            "AND athena_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL) OR "
            "(kind='fhir_medications' AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL AND fhir_grant_id IS NOT NULL "
            "AND athena_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL) OR "
            "(kind='core_allergies' AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL AND athena_grant_id IS NOT NULL "
            "AND fhir_grant_id IS NULL AND workspace_id IS NOT NULL AND patient_link_id IS NOT NULL)", name="ck_ehr_read_request_kind"),
        CheckConstraint("(kind IN ('fhir_patients','fhir_medications') AND window_start IS NULL AND window_end IS NULL AND practice_id IS NULL) OR "
            "(kind IN ('core_patients','core_allergies') AND window_start IS NULL AND window_end IS NULL AND practice_id IS NOT NULL) OR "
            "(kind NOT IN ('fhir_patients','fhir_medications','core_patients','core_allergies') AND window_start IS NOT NULL AND window_end IS NOT NULL AND practice_id IS NOT NULL "
            "AND isfinite(window_start) AND isfinite(window_end) AND window_end>window_start "
            "AND window_end<=window_start+interval '168 hours')", name="ck_ehr_read_request_window"),
        CheckConstraint("isfinite(valid_until) AND valid_until>created_at "
            "AND valid_until<=created_at+interval '30 minutes'", name="ck_ehr_read_request_expiry"),
        digest_check("request_hash", "binding_digest"),
        json_check("request_json", 4096),
        CheckConstraint("transport IN ('mock','vendor_sandbox')", name="ck_ehr_read_transport"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    binding_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    connection_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    credential_generation: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    practice_id: Mapped[str | None] = mapped_column(String(20))
    binding_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    transport: Mapped[str] = mapped_column(String(20), nullable=False, default="mock", server_default="mock")
    parent_snapshot_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    item_handle: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    workspace_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    patient_link_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    fhir_grant_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    athena_grant_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
        server_default=func.clock_timestamp())


class EhrReadSnapshot(OwnerScope, Base):
    __tablename__ = "ehr_read_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(["observation_id", "box_id", "owner_id"],
            ["ehr_read_requests.id", "ehr_read_requests.box_id", "ehr_read_requests.owner_id"]),
        UniqueConstraint("observation_id", name="uq_ehr_read_snapshot_observation"),
        UniqueConstraint("id", "box_id", "owner_id", name="uq_ehr_read_snapshot_scope"),
        digest_check("payload_sha256", "source_sha256"),
        json_check("payload", 65536),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    observation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
        server_default=func.clock_timestamp())


class EhrReadSourceReview(WorkspaceScope, Base):
    __tablename__ = "ehr_read_source_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
            ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["entry_id", "workspace_id", "box_id"],
            ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        ForeignKeyConstraint(["snapshot_id", "box_id", "owner_id"],
            ["ehr_read_snapshots.id", "ehr_read_snapshots.box_id", "ehr_read_snapshots.owner_id"]),
        ForeignKeyConstraint(["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]),
        UniqueConstraint("entry_id", name="uq_ehr_read_review_entry"),
        UniqueConstraint("workspace_id", "snapshot_id", "item_handle", name="uq_ehr_read_review_item"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_ehr_read_review_key"),
        CheckConstraint("command_provider IS NULL OR command_provider IN ('elation','tebra','athena')", name="ck_ehr_review_provider"),
        CheckConstraint("coalesce(command_protocol IS NULL OR (command_protocol='fhir' AND command_provider='tebra') OR (command_protocol='core' AND command_provider='athena'),false)", name="ck_ehr_review_protocol"),
        CheckConstraint("expected_revision>=1 AND workspace_revision=expected_revision+1",
            name="ck_ehr_read_review_revision"),
        CheckConstraint("coalesce(((command_protocol IS NULL AND reviewed_visit IS TRUE) OR (command_protocol IN ('fhir','core') AND reviewed_visit IS NULL)) "
            "AND reviewed_patient_identity AND reviewed_exact_snapshot AND reviewed_untrusted_source,false)", name="ck_ehr_read_review_checks"),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'", name="ck_ehr_read_review_key"),
        digest_check("request_hash", "observation_sha256", "item_sha256", "source_sha256", "content_sha256"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    command_provider: Mapped[str | None] = mapped_column(String(16))
    command_protocol: Mapped[str | None] = mapped_column(String(4))
    entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    item_handle: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    item_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_visit: Mapped[bool | None] = mapped_column(Boolean)
    reviewed_patient_identity: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_exact_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_untrusted_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
        server_default=func.clock_timestamp())
