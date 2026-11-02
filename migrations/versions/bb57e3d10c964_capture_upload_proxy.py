"""CosmaBot-side capture ciphertext upload proxy (T-REL-6 follow-up).

Browser never PUTs to Core/Scribe blob (would need Cosmas CORS). CosmaBot
stores the Core-issued upload URL server-side and streams bytes S2S.
"""

from alembic import op

revision = "bb57e3d10c964"
down_revision = "aa46f2c09b853"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(UPGRADE)


def downgrade():
    op.execute(DOWNGRADE)


UPGRADE = r"""
CREATE TABLE capture_upload_proxies (
	id UUID PRIMARY KEY,
	box_id UUID NOT NULL REFERENCES box_contexts (id),
	workspace_id UUID NOT NULL,
	session_id UUID NOT NULL,
	object_id UUID NOT NULL,
	principal_id UUID NOT NULL,
	authorization_receipt_id UUID NOT NULL,
	target_upload_url TEXT NOT NULL,
	expires_at TIMESTAMPTZ NOT NULL,
	created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
	consumed_at TIMESTAMPTZ
);

CREATE INDEX ix_capture_upload_proxies_workspace_expires
	ON capture_upload_proxies (workspace_id, expires_at);
"""

DOWNGRADE = r"""
DROP TABLE IF EXISTS capture_upload_proxies;
"""
