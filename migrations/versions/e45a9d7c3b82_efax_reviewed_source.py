"""Exact human-reviewed received-fax passages, separate from clinical notes."""

from alembic import op

revision = "e45a9d7c3b82"
down_revision = "i44e8f7a1c90"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)
    op.drop_constraint("ck_workspace_entry_kind", "workspace_entries", type_="check")
    op.create_check_constraint("ck_workspace_entry_kind", "workspace_entries",
        "kind IN ('synthetic_source','scratchpad','conversation','evidence','work_link','handoff_result','google_message','google_calendar','efax_inbound_source')")
    op.execute(GUARDS)
    op.execute(HANDOFF_GUARDS)
    op.execute(MODEL_GUARDS)


def downgrade():
    raise RuntimeError("Retain human source reviews and exact document commitments")


TABLES = r"""
CREATE TABLE public.efax_inbound_source_reviews (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, box_id uuid NOT NULL, owner_id uuid NOT NULL,
 entry_id uuid NOT NULL, operation_id uuid NOT NULL, grant_id uuid NOT NULL, patient_link_id uuid NOT NULL,
 ordinal integer NOT NULL, expected_revision integer NOT NULL, workspace_revision integer NOT NULL,
 idempotency_key varchar(100) NOT NULL, request_sha256 varchar(64) NOT NULL, source_sha256 varchar(64) NOT NULL,
 content_sha256 varchar(64) NOT NULL, document_sha256 varchar(64) NOT NULL,
 outcome_receipt_sha256 varchar(64) NOT NULL, selection_sha256 varchar(64) NOT NULL,
 page_numbers integer[] NOT NULL, reviewed_patient boolean NOT NULL, reviewed_exact_document boolean NOT NULL,
 reviewed_exact_text boolean NOT NULL, reviewed_untrusted_source boolean NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(workspace_id,box_id,owner_id) REFERENCES public.encounter_workspaces(id,box_id,owner_id),
 FOREIGN KEY(entry_id,workspace_id,box_id) REFERENCES public.workspace_entries(id,workspace_id,box_id),
 FOREIGN KEY(operation_id,box_id,owner_id) REFERENCES public.efax_inbound_acquisitions(operation_id,box_id,owner_id),
 FOREIGN KEY(grant_id,box_id,owner_id) REFERENCES public.efax_inbound_grants(id,box_id,owner_id),
 FOREIGN KEY(patient_link_id,box_id) REFERENCES public.patient_links(id,box_id),
 CONSTRAINT uq_efax_source_entry UNIQUE(entry_id),
 CONSTRAINT uq_efax_source_key UNIQUE(workspace_id,idempotency_key),
 CONSTRAINT uq_efax_source_ordinal UNIQUE(workspace_id,operation_id,ordinal),
 CONSTRAINT ck_efax_source_revision CHECK(expected_revision>=1 AND workspace_revision=expected_revision+1 AND ordinal BETWEEN 1 AND 500),
 CONSTRAINT ck_efax_source_key CHECK(idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'),
 CONSTRAINT ck_efax_source_checks CHECK(reviewed_patient AND reviewed_exact_document AND reviewed_exact_text AND reviewed_untrusted_source),
 CONSTRAINT ck_efax_source_pages CHECK(cardinality(page_numbers) BETWEEN 1 AND 50),
 CHECK(request_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$' AND content_sha256 ~ '^[a-f0-9]{64}$'
  AND document_sha256 ~ '^[a-f0-9]{64}$' AND outcome_receipt_sha256 ~ '^[a-f0-9]{64}$' AND selection_sha256 ~ '^[a-f0-9]{64}$')
);
"""

GUARDS = r"""
CREATE FUNCTION public.efax_inbound_document_valid(oid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.efax_inbound_acquisitions c
 JOIN public.efax_inbound_outcomes o ON o.operation_id=c.operation_id
 JOIN public.efax_inbound_image_revisions r ON r.action_revision_id=c.action_revision_id
 JOIN public.efax_inbound_grants g ON g.id=r.grant_id
 JOIN public.action_revisions a ON a.id=r.action_revision_id
 JOIN public.efax_inbound_observation_requests q ON q.id=r.observation_id
 JOIN public.efax_inbound_observations z ON z.request_id=q.id
 WHERE c.operation_id=oid AND (o.box_id,o.owner_id)=(c.box_id,c.owner_id)
  AND (r.box_id,r.owner_id)=(c.box_id,c.owner_id) AND (g.box_id,g.owner_id)=(c.box_id,c.owner_id)
  AND o.state='acquired' AND o.receipt->>'state'='acquired' AND o.document IS NOT NULL
  AND o.document_sha256=encode(sha256(o.document),'hex') AND o.byte_length=octet_length(o.document)
  AND o.byte_length BETWEEN 1 AND 1048576 AND o.pages BETWEEN 1 AND 50
  AND o.receipt->>'document_sha256'=o.document_sha256 AND o.receipt->'byte_length'=to_jsonb(o.byte_length)
  AND o.receipt->'pages'=to_jsonb(o.pages) AND o.receipt->>'operation_id'=c.operation_id::text
  AND o.receipt_sha256=public.vendor_public_digest('cosmas-efax-inbound-receipt.v1',o.receipt)
  AND o.receipt->>'command_sha256'=r.command_sha256 AND o.receipt->>'selection_sha256'=g.selection_sha256
  AND c.approval->>'command_sha256'=r.command_sha256 AND c.approval->>'selection_sha256'=g.selection_sha256
  AND c.approval->>'operation_id'=c.operation_id::text AND r.command->>'operation_id'=c.operation_id::text
  AND r.command_sha256=public.vendor_public_digest('cosmas-efax-image-command.v1',r.command)
  AND r.command->'selection'=g.selection AND r.command->>'fax_id'=r.fax_id::text
  AND o.receipt->>'fax_id'=r.fax_id::text AND c.fax_id=r.fax_id AND c.account_sha256=g.account_sha256
  AND g.selection_sha256=public.vendor_public_digest('cosmas-vendor-selection.v1',g.selection)
  AND a.box_id=c.box_id AND a.ticket_id=r.ticket_id AND a.payload_hash=r.action_sha256
  AND a.payload=jsonb_build_object('contract_version',1,'inbound_revision_id',r.action_revision_id,'command_sha256',r.command_sha256)
  AND (q.box_id,q.owner_id)=(c.box_id,c.owner_id) AND q.grant_id=g.id AND z.payload->'request'=q.request
  AND z.payload_sha256=public.vendor_public_digest('cosmas-efax-inbound-snapshot-payload.v1',z.payload)
  AND z.source_sha256=public.vendor_public_digest('cosmas-efax-inbound-list.v1',z.payload-'source_sha256')
  AND r.command->>'source_sha256'=z.source_sha256
  AND EXISTS(SELECT 1 FROM jsonb_array_elements(z.payload->'items') item
   WHERE item->>'fax_id'=r.fax_id::text AND r.fax_sha256=public.vendor_public_digest('cosmas-efax-inbound-fax.v1',item)))
$$;
CREATE FUNCTION public.efax_inbound_source_valid(eid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.efax_inbound_source_reviews v
 JOIN public.workspace_entries e ON e.id=v.entry_id JOIN public.encounter_workspaces w ON w.id=v.workspace_id
 JOIN public.efax_inbound_acquisitions c ON c.operation_id=v.operation_id
 JOIN public.efax_inbound_outcomes o ON o.operation_id=c.operation_id
 JOIN public.efax_inbound_image_revisions r ON r.action_revision_id=c.action_revision_id
 JOIN public.efax_inbound_grants g ON g.id=r.grant_id
 WHERE e.id=eid AND e.kind='efax_inbound_source' AND public.efax_inbound_document_valid(c.operation_id)
  AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)
   =(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_sha256,v.idempotency_key)
  AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
  AND (c.box_id,c.owner_id)=(v.box_id,v.owner_id) AND v.grant_id=g.id
  AND v.document_sha256=o.document_sha256 AND v.outcome_receipt_sha256=o.receipt_sha256 AND v.selection_sha256=g.selection_sha256
  AND v.reviewed_patient AND v.reviewed_exact_document AND v.reviewed_exact_text AND v.reviewed_untrusted_source
  AND char_length(e.content) BETWEEN 1 AND 12000 AND e.content !~ '^[[:space:]]*$'
  AND e.content !~ '[\x01-\x08\x0b-\x1f\x7f]' AND e.source_label='Received eFax: human-reviewed passage'
  AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex')
  AND v.page_numbers=ARRAY(SELECT DISTINCT n FROM unnest(v.page_numbers) n ORDER BY n)
  AND NOT EXISTS(SELECT 1 FROM unnest(v.page_numbers) n WHERE n IS NULL OR n<1 OR n>o.pages)
  AND v.request_sha256=public.vendor_public_digest('cosmas-efax-inbound-source-command.v1',jsonb_build_object(
   'scope',jsonb_build_object('box_id',v.box_id,'owner_id',v.owner_id,'workspace_id',v.workspace_id),
   'request',jsonb_build_object('expected_revision',v.expected_revision,'idempotency_key',v.idempotency_key,
    'operation_id',v.operation_id,'document_sha256',v.document_sha256,'passage',e.content,'page_numbers',to_jsonb(v.page_numbers),
    'reviewed_patient',v.reviewed_patient,'reviewed_exact_document',v.reviewed_exact_document,
    'reviewed_exact_text',v.reviewed_exact_text,'reviewed_untrusted_source',v.reviewed_untrusted_source)))
  AND v.source_sha256=public.vendor_public_digest('cosmas-efax-inbound-reviewed-source.v1',jsonb_build_object(
    'operation_id',v.operation_id,'grant_id',v.grant_id,'document_sha256',v.document_sha256,
    'outcome_receipt_sha256',v.outcome_receipt_sha256,'selection_sha256',v.selection_sha256,
    'content_sha256',v.content_sha256,'page_numbers',to_jsonb(v.page_numbers),
    'coverage','human_selected_passage','extraction','human_entered_no_ocr')))
$$;
CREATE FUNCTION public.efax_inbound_source_current(eid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.efax_inbound_source_valid(eid) AND EXISTS(SELECT 1 FROM public.efax_inbound_source_reviews v
 JOIN public.efax_inbound_grants g ON g.id=v.grant_id
 JOIN public.encounter_workspaces w ON w.id=v.workspace_id
 JOIN public.appointment_observations a ON a.id=w.appointment_id AND a.box_id=w.box_id AND a.patient_link_id=v.patient_link_id
 JOIN public.patient_links p ON p.id=v.patient_link_id AND p.box_id=v.box_id
 WHERE v.entry_id=eid AND public.efax_inbound_grant_current(g.id) AND g.image_enabled
  AND p.state='confirmed' AND p.revoked_at IS NULL
  AND (p.source_owner_id IS NULL OR (p.source_owner_id=v.owner_id AND EXISTS(SELECT 1 FROM public.core_capture_accounts ca
   JOIN public.external_identities x ON x.id=ca.external_identity_id WHERE ca.id=p.source_account_id
    AND ca.revoked_at IS NULL AND x.active AND x.box_id=v.box_id AND x.principal_id=v.owner_id)))
  AND NOT EXISTS(SELECT 1 FROM public.efax_inbound_source_reviews n WHERE n.workspace_id=v.workspace_id
   AND n.operation_id=v.operation_id AND n.ordinal>v.ordinal))
$$;
CREATE FUNCTION public.guard_efax_inbound_source_review() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE w public.encounter_workspaces; c public.efax_inbound_acquisitions; r public.efax_inbound_image_revisions;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'eFax source reviews are immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR UPDATE;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 SELECT * INTO c FROM public.efax_inbound_acquisitions WHERE operation_id=NEW.operation_id;
 SELECT * INTO r FROM public.efax_inbound_image_revisions WHERE action_revision_id=c.action_revision_id;
 IF w.id IS NULL OR (w.box_id,w.owner_id,w.patient_link_id,w.revision) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.patient_link_id,NEW.workspace_revision)
  OR c.operation_id IS NULL OR (c.box_id,c.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR r.grant_id IS DISTINCT FROM NEW.grant_id OR NOT public.efax_inbound_owner(NEW.box_id,NEW.owner_id)
  OR NOT public.efax_inbound_grant_current(NEW.grant_id) OR NOT public.efax_inbound_document_valid(NEW.operation_id)
  OR NOT EXISTS(SELECT 1 FROM public.efax_inbound_grants WHERE id=NEW.grant_id AND image_enabled)
  OR NOT EXISTS(SELECT 1 FROM public.appointment_observations a JOIN public.patient_links p ON p.id=a.patient_link_id
   WHERE a.id=w.appointment_id AND a.box_id=NEW.box_id AND p.id=NEW.patient_link_id AND p.box_id=NEW.box_id
    AND p.state='confirmed' AND p.revoked_at IS NULL AND (p.source_owner_id IS NULL OR
     (p.source_owner_id=NEW.owner_id AND EXISTS(SELECT 1 FROM public.core_capture_accounts ca
      JOIN public.external_identities x ON x.id=ca.external_identity_id WHERE ca.id=p.source_account_id
       AND ca.revoked_at IS NULL AND x.active AND x.box_id=NEW.box_id AND x.principal_id=NEW.owner_id))))
  OR NEW.ordinal IS DISTINCT FROM (SELECT coalesce(max(ordinal),0)+1 FROM public.efax_inbound_source_reviews
   WHERE workspace_id=NEW.workspace_id AND operation_id=NEW.operation_id)
 THEN RAISE EXCEPTION 'eFax source review authority invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION public.guard_efax_inbound_source_entry() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF TG_TABLE_NAME='workspace_entries' THEN
  IF NEW.kind='efax_inbound_source' AND NOT public.efax_inbound_source_current(NEW.id)
  THEN RAISE EXCEPTION 'exact eFax human source review required' USING ERRCODE='23514'; END IF;
 ELSE
  IF NOT public.efax_inbound_source_current(NEW.entry_id)
  THEN RAISE EXCEPTION 'invalid eFax source commitment' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER efax_inbound_source_review_guard BEFORE INSERT OR UPDATE OR DELETE ON public.efax_inbound_source_reviews
 FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_source_review();
CREATE CONSTRAINT TRIGGER efax_inbound_source_entry_guard AFTER INSERT ON public.workspace_entries
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_source_entry();
CREATE CONSTRAINT TRIGGER efax_inbound_source_commitment_guard AFTER INSERT ON public.efax_inbound_source_reviews
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_source_entry();
REVOKE ALL ON FUNCTION public.efax_inbound_document_valid(uuid),public.efax_inbound_source_valid(uuid),
 public.efax_inbound_source_current(uuid),public.guard_efax_inbound_source_review(),public.guard_efax_inbound_source_entry() FROM PUBLIC;
"""

# Preserve the existing human/team/source fences while admitting the new exact
# reviewed fax kind. Trigger entrypoints retain their migration-owned authority;
# the existing helper names remain compatible with prior trigger/runtime grants.
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
      'kind',CASE WHEN kind IN ('google_message','google_calendar','efax_inbound_source') THEN 'evidence' ELSE kind END,'sha256',encode(sha256(convert_to(content,'UTF8')),'hex')) ORDER BY category,revision),'[]'::jsonb)
  INTO selected FROM (
   SELECT e.*,0 category FROM public.workspace_entries e WHERE workspace_id=wid AND actor_id=owner AND box_id=h.box_id
    AND kind='scratchpad' AND bot->>'include_notebook'='true' AND revision=(SELECT max(revision) FROM public.workspace_entries WHERE workspace_id=wid AND kind='scratchpad')
   UNION ALL
   SELECT e.*,1 category FROM public.workspace_entries e WHERE workspace_id=wid AND actor_id=owner AND box_id=h.box_id
    AND (kind IN ('evidence','synthetic_source') OR (kind='google_message' AND public.google_message_source_current(e.id)) OR (kind='google_calendar' AND public.google_calendar_source_current(e.id)) OR (kind='efax_inbound_source' AND public.efax_inbound_source_current(e.id))) AND bot->>'include_evidence'='true'
  ) current_sources;
 END IF;
 RETURN selected=versions;
END $$;
CREATE OR REPLACE FUNCTION public.guard_handoff_review() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
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
   OR source->>'kind' IS DISTINCT FROM (CASE WHEN source_entry.kind IN ('google_message','google_calendar','efax_inbound_source') THEN 'evidence' ELSE source_entry.kind END)
   OR (source_entry.kind='google_message' AND NOT public.google_message_source_current(source_entry.id))
   OR (source_entry.kind='google_calendar' AND NOT public.google_calendar_source_current(source_entry.id))
   OR (source_entry.kind='efax_inbound_source' AND NOT public.efax_inbound_source_current(source_entry.id))
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
CREATE OR REPLACE FUNCTION public.selected_google_model_sources_current(m public.model_work_admissions)
RETURNS boolean LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE source jsonb; carrier jsonb; entry public.workspace_entries; descriptor jsonb;
 ordinary boolean;
BEGIN
 ordinary := NOT (m.request_body ?| ARRAY['session_prep_analysis','inbox_analysis','membership_analysis','research_analysis']);
 IF jsonb_typeof(m.prepared_envelope->'context'->'sources') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 FOR source IN SELECT value FROM jsonb_array_elements(m.prepared_envelope->'context'->'sources') LOOP
  IF jsonb_typeof(source) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
  SELECT * INTO entry FROM public.workspace_entries WHERE id::text=source->>'entry_id';
  IF entry.id IS NULL AND ordinary THEN RETURN false; END IF;
  IF entry.kind IN ('google_message','google_calendar','efax_inbound_source') THEN
   IF (entry.workspace_id,entry.box_id,entry.actor_id) IS DISTINCT FROM (m.workspace_id,m.box_id,m.owner_id)
    OR source->'revision' IS DISTINCT FROM to_jsonb(entry.revision)
    OR source->>'kind' IS DISTINCT FROM 'evidence'
    OR source->>'label' IS DISTINCT FROM entry.source_label
    OR source->>'content' IS DISTINCT FROM entry.content
    OR (entry.kind='google_message' AND NOT public.google_message_source_current(entry.id))
    OR (entry.kind='google_calendar' AND NOT public.google_calendar_source_current(entry.id))
    OR (entry.kind='efax_inbound_source' AND NOT public.efax_inbound_source_current(entry.id))
   THEN RETURN false; END IF;
  END IF;
 END LOOP;
 -- Exact fax handles declared elsewhere in the admission cannot disappear
 -- from the saved full-source context. Feature-disabled contexts may omit
 -- fax entirely; no current-document inventory is inferred here.
 FOR carrier IN SELECT value FROM jsonb_array_elements(jsonb_build_array(
   m.prepared_envelope->'tool_selection'->'sources',
   m.prepared_envelope->'source_delivery',
   m.request_body->'task_brief'->'source_versions')) LOOP
  IF carrier = 'null'::jsonb THEN CONTINUE; END IF;
  IF jsonb_typeof(carrier) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
  FOR descriptor IN SELECT value FROM jsonb_array_elements(carrier) LOOP
   IF jsonb_typeof(descriptor) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
   SELECT * INTO entry FROM public.workspace_entries WHERE id::text=descriptor->>'entry_id';
   IF entry.kind = 'efax_inbound_source' AND NOT EXISTS (
     SELECT 1 FROM jsonb_array_elements(m.prepared_envelope->'context'->'sources') selected
     WHERE selected->>'entry_id'=entry.id::text
       AND selected->'revision'=descriptor->'revision'
       AND descriptor->>'sha256'=encode(sha256(convert_to(entry.content,'UTF8')),'hex')
   ) THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 RETURN true;
END $$;
"""
