"""Per-practice EHR allowed-resource scope. Additive only; no PHI columns.

Defaults live in application code (Patient, Appointment, Encounter,
AllergyIntolerance, MedicationRequest, Condition). A missing row means the
default allow-list, so today's live reads stay permitted without a backfill.
"""

from alembic import op

revision = "z35e1b98a742"
down_revision = "y24f0a87c631"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)


def downgrade():
    raise RuntimeError("Retain EHR practice resource scope configuration")


TABLES = r"""
CREATE TABLE ehr_practice_resource_scopes (
	id UUID NOT NULL,
	box_id UUID NOT NULL,
	connection_id UUID NOT NULL,
	allowed_resources JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(box_id) REFERENCES box_contexts (id),
	CONSTRAINT uq_ehr_practice_resource_scope UNIQUE (box_id, connection_id),
	CONSTRAINT ck_ehr_practice_resource_scope_list CHECK (
		jsonb_typeof(allowed_resources) = 'array'
		AND jsonb_array_length(allowed_resources) BETWEEN 1 AND 32
	)
);

CREATE INDEX ix_ehr_practice_resource_scopes_box
	ON ehr_practice_resource_scopes (box_id);
"""
