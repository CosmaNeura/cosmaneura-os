"""Immutable human feedback for an exact private teammate draft and saved inputs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "e14c7d9a2b60"
down_revision = "d91e7a3c5b20"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_handoff_reviews",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        *(
            sa.Column(name, UUID(as_uuid=False), nullable=False)
            for name in (
                "workspace_id",
                "box_id",
                "owner_id",
                "handoff_id",
                "attempt_id",
                "result_entry_id",
                "agent_id",
            )
        ),
        *(
            sa.Column(name, sa.String(64), nullable=False)
            for name in ("result_sha256", "source_sha256", "request_hash")
        ),
        sa.Column("source_versions", JSONB, nullable=False),
        sa.Column("expected_revision", sa.Integer, nullable=False),
        sa.Column("workspace_revision", sa.Integer, nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("feedback", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["handoff_id", "workspace_id", "box_id", "owner_id"],
            [
                "workspace_handoffs.id",
                "workspace_handoffs.workspace_id",
                "workspace_handoffs.box_id",
                "workspace_handoffs.owner_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "workspace_id", "box_id", "owner_id"],
            [
                "workspace_handoff_attempts.id",
                "workspace_handoff_attempts.workspace_id",
                "workspace_handoff_attempts.box_id",
                "workspace_handoff_attempts.owner_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["result_entry_id", "workspace_id", "box_id"],
            ["workspace_entries.id", "workspace_entries.workspace_id", "workspace_entries.box_id"],
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "box_id", "owner_id"],
            ["provider_bots.agent_id", "provider_bots.box_id", "provider_bots.owner_id"],
        ),
        sa.UniqueConstraint("attempt_id", name="uq_handoff_review_attempt"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_handoff_review_key"),
        sa.UniqueConstraint(
            "workspace_id", "workspace_revision", name="uq_handoff_review_revision"
        ),
        sa.CheckConstraint(
            "decision IN ('accepted','changes_requested')", name="ck_handoff_review_decision"
        ),
        sa.CheckConstraint(
            "char_length(feedback) <= 2000 AND (decision <> 'changes_requested' OR feedback !~ '^[[:space:]]*$')",
            name="ck_handoff_review_feedback",
        ),
        sa.CheckConstraint(
            "result_sha256 ~ '^[0-9a-f]{64}$' AND source_sha256 ~ '^[0-9a-f]{64}$' AND request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_handoff_review_hashes",
        ),
        sa.CheckConstraint(
            "expected_revision >= 1 AND workspace_revision = expected_revision + 1",
            name="ck_handoff_review_revision",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_versions)='array' AND jsonb_array_length(source_versions)<=12 AND octet_length(source_versions::text)<=32768",
            name="ck_handoff_review_sources",
        ),
    )
    op.execute(GUARD)


def downgrade():
    raise RuntimeError("Retain human handoff reviews; disable new review instead")


GUARD = r"""
CREATE FUNCTION public.handoff_review_sources_current(wid uuid, owner uuid, hid uuid, versions jsonb)
RETURNS boolean LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE h public.workspace_handoffs; t public.provider_team_revisions; bot jsonb; chief jsonb; selected jsonb;
BEGIN
 SELECT * INTO h FROM public.workspace_handoffs WHERE id=hid AND workspace_id=wid AND owner_id=owner;
 SELECT * INTO t FROM public.provider_team_revisions WHERE owner_id=owner AND box_id=h.box_id ORDER BY revision DESC LIMIT 1;
 IF h.id IS NULL OR t.id IS DISTINCT FROM h.team_revision_id THEN RETURN false; END IF;
 SELECT value INTO bot FROM jsonb_array_elements(t.configuration->'bots')
  WHERE coalesce(nullif(value->>'instance_id',''),value->>'role')=(SELECT coalesce(instance_id::text,role) FROM public.provider_bots WHERE agent_id=h.recipient_agent_id);
 SELECT value INTO chief FROM jsonb_array_elements(t.configuration->'bots') WHERE value->>'role'='chief';
 IF bot IS NULL OR chief IS NULL OR bot->>'enabled' IS DISTINCT FROM 'true' OR chief->>'enabled' IS DISTINCT FROM 'true'
  OR bot->>'retired'='true' OR chief->>'retired'='true'
  OR bot->>'role' IS DISTINCT FROM h.recipient_role
  OR coalesce(bot->'blocked_capabilities','[]'::jsonb) ?| ARRAY['private_draft_handoff','model_answer']
  OR coalesce(chief->'blocked_capabilities','[]'::jsonb) ?| ARRAY['private_draft_handoff','model_answer']
  OR NOT EXISTS(SELECT 1 FROM public.principals WHERE id=h.recipient_agent_id AND box_id=h.box_id AND principal_type='agent' AND state='active' AND tombstoned_at IS NULL)
  OR NOT EXISTS(SELECT 1 FROM public.principals WHERE id=h.issuer_agent_id AND box_id=h.box_id AND principal_type='agent' AND state='active' AND tombstoned_at IS NULL)
  OR NOT EXISTS(SELECT 1 FROM public.provider_bots WHERE agent_id=h.issuer_agent_id AND box_id=h.box_id AND owner_id=owner AND role='chief')
 THEN RETURN false; END IF;
 IF bot->>'role'='custom' AND NOT coalesce(bot->'skills','[]'::jsonb) ? 'saved_context' THEN selected:='[]'::jsonb;
 ELSE
  SELECT coalesce(jsonb_agg(jsonb_build_object('entry_id',id,'revision',revision,'label',coalesce(source_label,'Your jotted notes'),
      'kind',kind,'sha256',encode(sha256(convert_to(content,'UTF8')),'hex')) ORDER BY category,revision),'[]'::jsonb)
  INTO selected FROM (
   SELECT e.*,0 category FROM public.workspace_entries e WHERE workspace_id=wid AND actor_id=owner AND box_id=h.box_id
    AND kind='scratchpad' AND bot->>'include_notebook'='true' AND revision=(SELECT max(revision) FROM public.workspace_entries WHERE workspace_id=wid AND kind='scratchpad')
   UNION ALL
   SELECT e.*,1 category FROM public.workspace_entries e WHERE workspace_id=wid AND actor_id=owner AND box_id=h.box_id
    AND kind IN ('evidence','synthetic_source') AND bot->>'include_evidence'='true'
  ) current_sources;
 END IF;
 RETURN selected=versions;
END $$;
CREATE FUNCTION public.guard_handoff_review() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE w public.encounter_workspaces; h public.workspace_handoffs; a public.workspace_handoff_attempts;
 r public.workspace_replies; m public.model_work_admissions; p public.principals; e public.workspace_entries;
 source jsonb; source_entry public.workspace_entries;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'handoff reviews are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 SELECT * INTO p FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR SHARE;
 SELECT * INTO h FROM public.workspace_handoffs WHERE id=NEW.handoff_id;
 SELECT * INTO a FROM public.workspace_handoff_attempts WHERE id=NEW.attempt_id;
 SELECT * INTO e FROM public.workspace_entries WHERE id=NEW.result_entry_id;
 SELECT * INTO r FROM public.workspace_replies WHERE entry_id=NEW.result_entry_id;
 SELECT * INTO m FROM public.model_work_admissions WHERE handoff_attempt_id=NEW.attempt_id;
 IF w.id IS NULL OR (w.box_id,w.owner_id,w.revision) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.workspace_revision)
  OR p.principal_type IS DISTINCT FROM 'human' OR p.state IS DISTINCT FROM 'active' OR p.tombstoned_at IS NOT NULL
  OR h.id IS NULL OR (h.workspace_id,h.box_id,h.owner_id,h.recipient_agent_id)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.agent_id)
  OR NEW.owner_id=NEW.agent_id
  OR a.id IS NULL OR (a.handoff_id,a.workspace_id,a.box_id,a.owner_id,a.status,a.result_entry_id)
    IS DISTINCT FROM (NEW.handoff_id,NEW.workspace_id,NEW.box_id,NEW.owner_id,'completed',NEW.result_entry_id)
  OR EXISTS(SELECT 1 FROM public.workspace_handoff_attempts WHERE handoff_id=NEW.handoff_id AND number>a.number)
  OR e.id IS NULL OR (e.workspace_id,e.box_id,e.actor_id,e.kind)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,'handoff_result')
  OR r.entry_id IS NULL OR (r.workspace_id,r.box_id,r.owner_id,r.agent_id,r.team_revision_id,r.role)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.agent_id,h.team_revision_id,h.recipient_role)
  OR NEW.result_sha256 IS DISTINCT FROM encode(sha256(convert_to(r.content,'UTF8')),'hex')
  OR m.id IS NULL OR (m.workspace_id,m.box_id,m.owner_id,m.agent_id,m.kind,m.state,m.request_entry_id,m.result_entry_id,m.source_sha256)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.agent_id,'private_handoff','completed',NEW.result_entry_id,NEW.result_entry_id,NEW.source_sha256)
  OR NEW.source_versions IS DISTINCT FROM m.request_body->'task_brief'->'source_versions'
  OR NOT public.handoff_review_sources_current(NEW.workspace_id,NEW.owner_id,NEW.handoff_id,NEW.source_versions)
 THEN RAISE EXCEPTION 'handoff review binding invalid' USING ERRCODE='23514'; END IF;
 FOR source IN SELECT value FROM jsonb_array_elements(NEW.source_versions) LOOP
  SELECT * INTO source_entry FROM public.workspace_entries WHERE id::text=source->>'entry_id';
  IF source_entry.id IS NULL OR (source_entry.workspace_id,source_entry.box_id,source_entry.actor_id)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id)
   OR source->'revision' IS DISTINCT FROM to_jsonb(source_entry.revision)
   OR source->>'kind' IS DISTINCT FROM source_entry.kind
   OR source->>'label' IS DISTINCT FROM coalesce(source_entry.source_label,'Your jotted notes')
   OR source->>'sha256' IS DISTINCT FROM encode(sha256(convert_to(source_entry.content,'UTF8')),'hex')
   OR (source_entry.kind='scratchpad' AND EXISTS(SELECT 1 FROM public.workspace_entries
       WHERE workspace_id=NEW.workspace_id AND kind='scratchpad' AND revision>source_entry.revision))
  THEN RAISE EXCEPTION 'handoff review source invalid' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER handoff_review_binding BEFORE INSERT OR UPDATE OR DELETE ON public.workspace_handoff_reviews
 FOR EACH ROW EXECUTE FUNCTION public.guard_handoff_review();
"""
