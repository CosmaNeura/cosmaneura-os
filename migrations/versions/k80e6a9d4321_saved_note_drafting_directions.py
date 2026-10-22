"""Retain exact saved-note custody for additive human drafting directions."""

from pathlib import Path
from runpy import run_path

from alembic import op

revision = "k80e6a9d4321"
down_revision = "j79f1d5a2340"
branch_labels = None
depends_on = None


def upgrade():
    # Reconstruct the frozen j79 guard without editing it. Every pre-existing
    # connector, owner and selected-source check remains byte-for-byte intact.
    versions = Path(__file__).parent
    prior = run_path(str(versions / "h68e0c4f1239_fax_reviewed_source.py"))["MODEL_GUARDS"]
    frozen = run_path(str(versions / "j79f1d5a2340_human_shared_note_custody.py"))
    for before, after in (*frozen["MODEL_EXTENSIONS"], *DIRECTIONS_EXTENSIONS):
        if prior.count(before) != 1:
            raise RuntimeError("Prior immutable model source guard differs from the reviewed extension")
        prior = prior.replace(before, after)
    op.execute(prior)


def downgrade():
    raise RuntimeError("Retain exact saved-note custody and immutable drafting instructions")


DIRECTIONS_EXTENSIONS = (
    ("IF clinical_request->>'contract'='clinical-team-drafts.request.v1' THEN",
     "IF clinical_request->>'contract' IN ('clinical-team-drafts.request.v1','clinical-team-drafts.request.v2') THEN"),
    ("OR clinical_request-ARRAY['contract','source_entry_id','note_id','note_version','content_hash']<>'{}'::jsonb",
     """OR clinical_request-(CASE WHEN clinical_request->>'contract'='clinical-team-drafts.request.v2'
      THEN ARRAY['contract','source_entry_id','note_id','note_version','content_hash','owner_directions']
      ELSE ARRAY['contract','source_entry_id','note_id','note_version','content_hash'] END)<>'{}'::jsonb
   OR (clinical_request->>'contract'='clinical-team-drafts.request.v2' AND
     (jsonb_typeof(clinical_request->'owner_directions') IS DISTINCT FROM 'string'
      OR length(clinical_request->>'owner_directions') NOT BETWEEN 1 AND 2000
      OR length(m.request_body->>'content')>4000))"""),
)
