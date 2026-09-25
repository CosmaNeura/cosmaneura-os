"""Reviewed invited Scheduling connection; preserve accepted correspondence history."""
from alembic import op
import sqlalchemy as sa
revision = "de316d1b22db"
down_revision = "c48b673e219a"
branch_labels = None
depends_on = None
UPGRADE_SQL = "\nCREATE TABLE scheduling_enrollments (\n\tid UUID NOT NULL, \n\texternal_identity_id UUID NOT NULL, \n\tstate_digest VARCHAR(64) NOT NULL, \n\tbinding_digest VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tsealed BYTEA, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\taccount_id UUID, \n\tcommand_key UUID, \n\tcommand_sha256 VARCHAR(64), \n\tPRIMARY KEY (id), \n\tCHECK (status IN ('pending','exchanging','review','confirmed','failed')), \n\tCHECK (sealed IS NULL OR octet_length(sealed) BETWEEN 28 AND 32768), \n\tCHECK (state_digest ~ '^[a-f0-9]{64}$' AND binding_digest ~ '^[a-f0-9]{64}$'), \n\tCHECK (expires_at > created_at), \n\tCHECK ((status = 'confirmed' AND sealed IS NULL AND account_id IS NOT NULL AND command_key IS NOT NULL AND command_sha256 IS NOT NULL) OR (status <> 'confirmed' AND account_id IS NULL AND command_key IS NULL AND command_sha256 IS NULL)), \n\tCHECK (command_sha256 IS NULL OR command_sha256 ~ '^[a-f0-9]{64}$'), \n\tFOREIGN KEY(external_identity_id) REFERENCES external_identities (id), \n\tUNIQUE (state_digest), \n\tFOREIGN KEY(account_id) REFERENCES scheduling_accounts (id)\n)\n\n;\nCREATE INDEX ix_scheduling_enrollments_external_identity_id ON scheduling_enrollments (external_identity_id);\nCREATE UNIQUE INDEX uq_scheduling_enrollment_active ON scheduling_enrollments (external_identity_id) WHERE status IN ('pending','exchanging','review');\nCREATE UNIQUE INDEX uq_scheduling_enrollment_command ON scheduling_enrollments (external_identity_id, command_key) WHERE command_key IS NOT NULL;\nCREATE FUNCTION guard_scheduling_enrollment_history() RETURNS trigger LANGUAGE plpgsql AS $$\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'scheduling enrollment history retained'; END IF;\n IF ROW(NEW.id,NEW.external_identity_id,NEW.state_digest,NEW.binding_digest,NEW.created_at,NEW.expires_at)\n IS DISTINCT FROM ROW(OLD.id,OLD.external_identity_id,OLD.state_digest,OLD.binding_digest,OLD.created_at,OLD.expires_at)\n THEN RAISE EXCEPTION 'scheduling enrollment scope immutable'; END IF;\n IF OLD.status IN ('confirmed','failed') AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'scheduling enrollment receipt immutable'; END IF;\n IF NEW.status<>OLD.status AND NOT ((OLD.status='pending' AND NEW.status IN ('exchanging','failed')) OR (OLD.status='exchanging' AND NEW.status IN ('review','failed')) OR (OLD.status='review' AND NEW.status IN ('confirmed','failed')))\n THEN RAISE EXCEPTION 'invalid scheduling enrollment transition'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER scheduling_enrollment_history BEFORE UPDATE OR DELETE ON scheduling_enrollments FOR EACH ROW EXECUTE FUNCTION guard_scheduling_enrollment_history();\n"

def upgrade():
    op.execute(UPGRADE_SQL)

def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM scheduling_enrollments)")):
        raise RuntimeError("Retain enrollment attempts and receipts before downgrade")
    op.drop_table("scheduling_enrollments")
    op.execute("DROP FUNCTION guard_scheduling_enrollment_history()")
