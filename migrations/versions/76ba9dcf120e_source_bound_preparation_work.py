"""Preserve private Core preparation proof on existing F-8 work."""
from alembic import op

revision = "76ba9dcf120e"
down_revision = "189ab72c0fd4"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""ALTER TABLE follow_up_sources
        ADD COLUMN source_kind varchar(32) NOT NULL DEFAULT 'reviewed_note',
        ADD COLUMN prep_snapshot_sha256 varchar(64), ADD COLUMN prep_receipt jsonb,
        ALTER COLUMN note_id DROP NOT NULL, ALTER COLUMN content_hash DROP NOT NULL,
        ALTER COLUMN source_fingerprint DROP NOT NULL,
        ADD CONSTRAINT fk_follow_up_workspace_owner FOREIGN KEY (workspace_id, box_id, owner_id)
            REFERENCES encounter_workspaces(id, box_id, owner_id),
        ADD CONSTRAINT ck_follow_up_source_kind CHECK (COALESCE(
            (source_kind = 'reviewed_note' AND note_id IS NOT NULL AND content_hash IS NOT NULL
             AND source_fingerprint IS NOT NULL AND prep_snapshot_sha256 IS NULL AND prep_receipt IS NULL)
            OR (source_kind = 'core_prep' AND note_id IS NULL AND content_hash IS NULL AND source_fingerprint IS NULL
                AND prep_snapshot_sha256 ~ '^[a-f0-9]{64}$' AND jsonb_typeof(prep_receipt) = 'object'
                AND prep_receipt->>'snapshot_sha256' = prep_snapshot_sha256
                AND jsonb_typeof(prep_receipt->'sources') = 'array'
                AND jsonb_array_length(prep_receipt->'sources') <= 6
                AND octet_length(prep_receipt::text) <= 262144), false))""")
    op.execute("""ALTER TABLE follow_up_receipts
        ADD COLUMN source_snapshot_sha256 varchar(64), ADD COLUMN source_proof jsonb,
        DROP CONSTRAINT ck_follow_up_receipt_kind,
        ADD CONSTRAINT ck_follow_up_receipt_kind CHECK (kind IN
            ('local_delivery', 'human_completion', 'internal_publication', 'ready_for_review', 'provider_verification')),
        ADD CONSTRAINT ck_follow_up_receipt_proof CHECK (COALESCE(
            (kind <> 'provider_verification' AND source_snapshot_sha256 IS NULL AND source_proof IS NULL)
            OR (kind = 'provider_verification' AND source_snapshot_sha256 ~ '^[a-f0-9]{64}$'
                AND jsonb_typeof(source_proof) = 'object'
                AND source_proof->>'snapshot_sha256' = source_snapshot_sha256
                AND jsonb_typeof(source_proof->'sources') = 'array'
                AND jsonb_array_length(source_proof->'sources') BETWEEN 1 AND 6
                AND octet_length(source_proof::text) <= 262144), false))""")


def downgrade():
    raise RuntimeError("Disable preparation work; private source and verification evidence cannot be downgraded destructively")
