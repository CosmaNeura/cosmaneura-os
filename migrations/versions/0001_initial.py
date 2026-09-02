"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "box_contexts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "principals",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("principal_type", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("is_owner", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("agent_key", sa.String(64), nullable=True),
        sa.Column("charter_version", sa.String(64), nullable=False),
        sa.Column("config_version", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "patient_links",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("source_pair_key", sa.String(200), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("confirmed_by_principal_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("principals.id")),
        sa.Column("attested_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("state", sa.String(32), nullable=False),
        sa.UniqueConstraint("box_id", "source_pair_key", name="uq_patient_link_source_pair"),
    )
    op.create_table(
        "appointment_observations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("external_id", sa.String(120), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_label", sa.String(200), nullable=False),
        sa.Column("patient_link_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("patient_links.id")),
        sa.Column("coverage_status", sa.String(32), nullable=False),
    )
    op.create_table(
        "tickets",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("lane", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_principal_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("principals.id")),
        sa.Column("appointment_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("appointment_observations.id")),
        sa.Column("patient_link_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("patient_links.id")),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=False)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "action_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("target_ref", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("automation_class", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("charter_version", sa.String(64), nullable=False),
        sa.Column("config_version", sa.String(64), nullable=False),
        sa.Column("created_by_principal_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("principals.id")),
        sa.Column("invalidated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("action_revision_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("action_revisions.id")),
        sa.Column("actor_principal_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("principals.id")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "operations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("action_revision_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("action_revisions.id")),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("adapter", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("external_reference", sa.String(200)),
        sa.Column("result_receipt_hash", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("action_revision_id", name="uq_operation_action_revision"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_principal_id", postgresql.UUID(as_uuid=False)),
        sa.Column("initiated_by_principal_id", postgresql.UUID(as_uuid=False)),
        sa.Column("approved_by_principal_id", postgresql.UUID(as_uuid=False)),
        sa.Column("action_revision_id", postgresql.UUID(as_uuid=False)),
        sa.Column("payload_hash", sa.String(64)),
        sa.Column("policy_version", sa.String(64)),
        sa.Column("charter_version", sa.String(64)),
        sa.Column("config_version", sa.String(64)),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("outcome", sa.String(64)),
        sa.Column("detail", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tickets.id")),
        sa.Column("classification", sa.String(64), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("blob_key", sa.String(300)),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True)),
        sa.Column("purge_receipt", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "capability_configs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("box_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("box_contexts.id"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("box_id", "key", name="uq_capability_box_key"),
    )


def downgrade() -> None:
    for t in (
        "capability_configs",
        "artifacts",
        "audit_events",
        "operations",
        "decisions",
        "action_revisions",
        "tickets",
        "appointment_observations",
        "patient_links",
        "principals",
        "box_contexts",
    ):
        op.drop_table(t)
