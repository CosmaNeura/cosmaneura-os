"""Current selected calendar/email source lineage for private drafts and reviews."""

from alembic import op

revision = "g42b8d3f6a10"
down_revision = "g41c7a8e2d90"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(HANDOFF_GUARDS)
    op.execute(MODEL_GUARDS)


def downgrade():
    raise RuntimeError("Retain selected calendar source lineage and human reviews")


HANDOFF_GUARDS = r"""

CREATE OR REPLACE FUNCTION public.handoff_review_sources_current(wid uuid, owner uuid, hid uuid, versions jsonb)
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
      'kind',CASE WHEN kind IN ('google_message','google_calendar') THEN 'evidence' ELSE kind END,'sha256',encode(sha256(convert_to(content,'UTF8')),'hex')) ORDER BY category,revision),'[]'::jsonb)
  INTO selected FROM (
   SELECT e.*,0 category FROM public.workspace_entries e WHERE workspace_id=wid AND actor_id=owner AND box_id=h.box_id
    AND kind='scratchpad' AND bot->>'include_notebook'='true' AND revision=(SELECT max(revision) FROM public.workspace_entries WHERE workspace_id=wid AND kind='scratchpad')
   UNION ALL
   SELECT e.*,1 category FROM public.workspace_entries e WHERE workspace_id=wid AND actor_id=owner AND box_id=h.box_id
    AND (kind IN ('evidence','synthetic_source') OR (kind='google_message' AND public.google_message_source_current(e.id)) OR (kind='google_calendar' AND public.google_calendar_source_current(e.id))) AND bot->>'include_evidence'='true'
  ) current_sources;
 END IF;
 RETURN selected=versions;
END $$;
CREATE OR REPLACE FUNCTION public.guard_handoff_review() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
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
   OR source->>'kind' IS DISTINCT FROM (CASE WHEN source_entry.kind IN ('google_message','google_calendar') THEN 'evidence' ELSE source_entry.kind END)
   OR (source_entry.kind='google_message' AND NOT public.google_message_source_current(source_entry.id))
   OR (source_entry.kind='google_calendar' AND NOT public.google_calendar_source_current(source_entry.id))
   OR source->>'label' IS DISTINCT FROM coalesce(source_entry.source_label,'Your jotted notes')
   OR source->>'sha256' IS DISTINCT FROM encode(sha256(convert_to(source_entry.content,'UTF8')),'hex')
   OR (source_entry.kind='scratchpad' AND EXISTS(SELECT 1 FROM public.workspace_entries
       WHERE workspace_id=NEW.workspace_id AND kind='scratchpad' AND revision>source_entry.revision))
  THEN RAISE EXCEPTION 'handoff review source invalid' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
"""

MODEL_GUARDS = r"""
CREATE FUNCTION public.selected_google_model_sources_current(m public.model_work_admissions)
RETURNS boolean LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE source jsonb; entry public.workspace_entries;
BEGIN
 IF jsonb_typeof(m.prepared_envelope->'context'->'sources') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 FOR source IN SELECT value FROM jsonb_array_elements(m.prepared_envelope->'context'->'sources') LOOP
  SELECT * INTO entry FROM public.workspace_entries WHERE id::text=source->>'entry_id';
  IF entry.kind IN ('google_message','google_calendar') THEN
   IF (entry.workspace_id,entry.box_id,entry.actor_id) IS DISTINCT FROM (m.workspace_id,m.box_id,m.owner_id)
    OR source->'revision' IS DISTINCT FROM to_jsonb(entry.revision)
    OR source->>'kind' IS DISTINCT FROM 'evidence'
    OR source->>'label' IS DISTINCT FROM entry.source_label
    OR source->>'content' IS DISTINCT FROM entry.content
    OR (entry.kind='google_message' AND NOT public.google_message_source_current(entry.id))
    OR (entry.kind='google_calendar' AND NOT public.google_calendar_source_current(entry.id))
   THEN RETURN false; END IF;
  END IF;
 END LOOP;
 RETURN true;
END $$;
CREATE FUNCTION public.guard_selected_google_model_sources() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.state IN ('reserved','running','completed') AND NOT public.selected_google_model_sources_current(NEW)
 THEN RAISE EXCEPTION 'selected Google model source unavailable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER selected_google_model_sources_guard BEFORE INSERT OR UPDATE ON public.model_work_admissions
 FOR EACH ROW EXECUTE FUNCTION public.guard_selected_google_model_sources();
"""
