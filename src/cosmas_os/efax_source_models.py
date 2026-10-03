"""Immutable human-reviewed passages from exact, privately acquired eFax PDFs."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cosmas_os.db import Base
from cosmas_os.vendor_models import WorkspaceScope, digest_check


class EFaxInboundSourceReview(WorkspaceScope, Base):
    __tablename__ = "efax_inbound_source_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "box_id", "owner_id"],
                             ["encounter_workspaces.id", "encounter_workspaces.box_id", "encounter_workspaces.owner_id"]),
        ForeignKeyConstraint(["entry_id", "workspace_id", "box_id"],
                             ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"]),
        ForeignKeyConstraint(["operation_id", "box_id", "owner_id"],
                             ["efax_inbound_acquisitions.operation_id", "efax_inbound_acquisitions.box_id", "efax_inbound_acquisitions.owner_id"]),
        ForeignKeyConstraint(["grant_id", "box_id", "owner_id"],
                             ["efax_inbound_grants.id", "efax_inbound_grants.box_id", "efax_inbound_grants.owner_id"]),
        ForeignKeyConstraint(["patient_link_id", "box_id"], ["patient_links.id", "patient_links.box_id"]),
        UniqueConstraint("entry_id", name="uq_efax_source_entry"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_efax_source_key"),
        UniqueConstraint("workspace_id", "operation_id", "ordinal", name="uq_efax_source_ordinal"),
        CheckConstraint("expected_revision>=1 AND workspace_revision=expected_revision+1 AND ordinal BETWEEN 1 AND 500", name="ck_efax_source_revision"),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'", name="ck_efax_source_key"),
        CheckConstraint("reviewed_patient AND reviewed_exact_document AND reviewed_exact_text AND reviewed_untrusted_source", name="ck_efax_source_checks"),
        CheckConstraint("cardinality(page_numbers) BETWEEN 1 AND 50", name="ck_efax_source_pages"),
        digest_check("request_sha256", "source_sha256", "content_sha256", "document_sha256", "outcome_receipt_sha256", "selection_sha256"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    entry_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    grant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    patient_link_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    workspace_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    selection_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_numbers: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    reviewed_patient: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_exact_document: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_exact_text: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_untrusted_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
