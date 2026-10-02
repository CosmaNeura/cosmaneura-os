"""One explicit human revision request per exact reviewed private draft."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "f28d6a9c3b71"
down_revision = "e14c7d9a2b60"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_handoff_revisions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        *(
            sa.Column(name, UUID(as_uuid=False), nullable=False)
            for name in (
                "workspace_id",
                "box_id",
                "owner_id",
                "parent_handoff_id",
                "review_id",
                "revision_handoff_id",
                "origin_entry_id",
            )
        ),
        sa.Column("expected_revision", sa.Integer, nullable=False),
        sa.Column("workspace_revision", sa.Integer, nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["parent_handoff_id", "workspace_id", "box_id", "owner_id"],
            [
                "workspace_handoffs.id",
                "workspace_handoffs.workspace_id",
                "workspace_handoffs.box_id",
                "workspace_handoffs.owner_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["revision_handoff_id", "workspace_id", "box_id", "owner_id"],
            [
                "workspace_handoffs.id",
                "workspace_handoffs.workspace_id",
                "workspace_handoffs.box_id",
                "workspace_handoffs.owner_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["origin_entry_id", "workspace_id", "box_id"],
            ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"],
        ),
        sa.ForeignKeyConstraint(["review_id"], ["workspace_handoff_reviews.id"]),
        sa.UniqueConstraint("review_id", name="uq_handoff_revision_review"),
        sa.UniqueConstraint("revision_handoff_id", name="uq_handoff_revision_assignment"),
        sa.UniqueConstraint("origin_entry_id", name="uq_handoff_revision_origin"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_handoff_revision_key"),
        sa.CheckConstraint(
            "parent_handoff_id <> revision_handoff_id", name="ck_handoff_revision_identity"
        ),
        sa.CheckConstraint(
            "expected_revision >= 1 AND workspace_revision = expected_revision + 1",
            name="ck_handoff_revision_revision",
        ),
        sa.CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="ck_handoff_revision_hash"),
    )
    op.execute(GUARD)


def downgrade():
    raise RuntimeError("Retain explicit human revision requests")


GUARD = r"""
CREATE FUNCTION public.guard_handoff_revision() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE w public.encounter_workspaces; p public.workspace_handoffs; h public.workspace_handoffs;
 r public.workspace_handoff_reviews; e public.workspace_entries; m public.model_work_admissions;
 a public.workspace_handoff_attempts; person public.principals; metadata jsonb;
 old_attempt public.workspace_handoff_attempts; old_reply public.workspace_replies; old_model public.model_work_admissions;
 ancestor uuid; previous uuid; depth integer:=0; seen uuid[]:=ARRAY[]::uuid[];
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'handoff revisions are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 SELECT * INTO person FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR SHARE;
 SELECT * INTO p FROM public.workspace_handoffs WHERE id=NEW.parent_handoff_id;
 SELECT * INTO h FROM public.workspace_handoffs WHERE id=NEW.revision_handoff_id;
 SELECT * INTO r FROM public.workspace_handoff_reviews WHERE id=NEW.review_id;
 SELECT * INTO e FROM public.workspace_entries WHERE id=NEW.origin_entry_id;
 SELECT * INTO a FROM public.workspace_handoff_attempts WHERE handoff_id=NEW.revision_handoff_id AND number=1;
 SELECT * INTO m FROM public.model_work_admissions WHERE handoff_attempt_id=a.id;
 SELECT * INTO old_attempt FROM public.workspace_handoff_attempts WHERE id=r.attempt_id;
 SELECT * INTO old_reply FROM public.workspace_replies WHERE entry_id=r.result_entry_id;
 SELECT * INTO old_model FROM public.model_work_admissions WHERE handoff_attempt_id=r.attempt_id;
 ancestor:=NEW.parent_handoff_id;
 LOOP
  IF ancestor=ANY(seen) THEN RAISE EXCEPTION 'handoff revision cycle' USING ERRCODE='23514'; END IF;
  seen:=array_append(seen,ancestor);
  SELECT parent_handoff_id INTO previous FROM public.workspace_handoff_revisions WHERE revision_handoff_id=ancestor;
  EXIT WHEN previous IS NULL;
  depth:=depth+1;
  IF depth>=3 THEN RAISE EXCEPTION 'handoff revision limit' USING ERRCODE='23514'; END IF;
  ancestor:=previous;
 END LOOP;
 metadata:=jsonb_build_object('parent_handoff_id',NEW.parent_handoff_id,'review_id',r.id,'attempt_id',r.attempt_id,
   'result_entry_id',r.result_entry_id,'result_sha256',r.result_sha256,'feedback',r.feedback);
 IF w.id IS NULL OR (w.box_id,w.owner_id,w.revision) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.workspace_revision+1)
  OR person.principal_type IS DISTINCT FROM 'human' OR person.state IS DISTINCT FROM 'active' OR person.tombstoned_at IS NOT NULL
  OR r.id IS NULL OR (r.handoff_id,r.workspace_id,r.box_id,r.owner_id,r.decision)
    IS DISTINCT FROM (NEW.parent_handoff_id,NEW.workspace_id,NEW.box_id,NEW.owner_id,'changes_requested')
  OR p.id IS NULL OR h.id IS NULL OR (h.workspace_id,h.box_id,h.owner_id,h.origin_entry_id,h.issuer_agent_id,h.recipient_agent_id,h.recipient_role,h.team_revision_id,h.brief)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.origin_entry_id,p.issuer_agent_id,p.recipient_agent_id,p.recipient_role,p.team_revision_id,p.brief)
  OR e.id IS NULL OR (e.workspace_id,e.box_id,e.actor_id,e.kind,e.revision,e.idempotency_key,e.request_hash)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,'conversation',NEW.workspace_revision,NEW.idempotency_key,NEW.request_hash)
  OR EXISTS(SELECT 1 FROM public.workspace_replies WHERE entry_id=e.id)
  OR m.id IS NULL OR (m.workspace_id,m.box_id,m.owner_id,m.agent_id,m.kind,m.state,m.team_revision_id)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,h.recipient_agent_id,'private_handoff','reserved',h.team_revision_id)
  OR m.request_body->'revision_request' IS DISTINCT FROM metadata
  OR m.request_body->'task_brief'->'depends_on' IS DISTINCT FROM jsonb_build_object('entry_id',e.id,'revision',e.revision)
  OR m.request_body->'task_brief'->'source_versions' IS DISTINCT FROM r.source_versions
  OR a.status IS DISTINCT FROM 'queued'
  OR old_attempt.id IS NULL OR old_attempt.handoff_id IS DISTINCT FROM NEW.parent_handoff_id
  OR old_attempt.status IS DISTINCT FROM 'completed' OR old_attempt.result_entry_id IS DISTINCT FROM r.result_entry_id
  OR EXISTS(SELECT 1 FROM public.workspace_handoff_attempts WHERE handoff_id=NEW.parent_handoff_id AND number>old_attempt.number)
  OR old_reply.entry_id IS NULL OR (old_reply.workspace_id,old_reply.box_id,old_reply.owner_id,old_reply.agent_id,old_reply.team_revision_id,old_reply.role)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,p.recipient_agent_id,p.team_revision_id,p.recipient_role)
  OR r.result_sha256 IS DISTINCT FROM encode(sha256(convert_to(old_reply.content,'UTF8')),'hex')
  OR old_model.id IS NULL OR (old_model.kind,old_model.state,old_model.result_entry_id,old_model.source_sha256)
    IS DISTINCT FROM ('private_handoff','completed',r.result_entry_id,r.source_sha256)
  OR old_model.request_body->'task_brief'->'source_versions' IS DISTINCT FROM r.source_versions
  OR NOT public.handoff_review_sources_current(NEW.workspace_id,NEW.owner_id,NEW.parent_handoff_id,r.source_versions)
 THEN RAISE EXCEPTION 'handoff revision binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER handoff_revision_binding BEFORE INSERT OR UPDATE OR DELETE ON public.workspace_handoff_revisions
 FOR EACH ROW EXECUTE FUNCTION public.guard_handoff_revision();
"""
