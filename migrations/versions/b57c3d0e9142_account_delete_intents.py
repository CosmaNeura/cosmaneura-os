"""Durable Clerk account-delete intent for retry after partial delete.

Additive and reversible. Records per-subject delete intent before the Clerk
Backend call so a later require_user 404 (already deleted in Clerk) can finish
the local wipe on retry without reporting success on a wrong-instance key.
"""

from alembic import op

revision = "b57c3d0e9142"
down_revision = "a46f2c09d853"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)


def downgrade():
    op.execute("DROP TABLE IF EXISTS account_delete_intents;")


TABLES = r"""
CREATE TABLE account_delete_intents (
	id UUID NOT NULL,
	box_id UUID NOT NULL,
	principal_id UUID NOT NULL,
	provider VARCHAR(32) NOT NULL,
	subject VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(box_id) REFERENCES box_contexts (id),
	FOREIGN KEY(principal_id, box_id) REFERENCES principals (id, box_id),
	CONSTRAINT uq_account_delete_intent_subject UNIQUE (box_id, principal_id, provider, subject),
	CONSTRAINT ck_account_delete_intent_provider CHECK (provider = 'clerk'),
	CONSTRAINT ck_account_delete_intent_subject CHECK (subject ~ '^user_' AND char_length(subject) BETWEEN 6 AND 255)
);
"""
