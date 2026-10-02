"""Immutable private Google reads and explicit human selected-source review."""

from alembic import op

revision = "g39a7e1b6c82"
down_revision = "f28d6a9c3b71"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)
    op.drop_constraint("ck_workspace_entry_kind", "workspace_entries", type_="check")
    op.create_check_constraint(
        "ck_workspace_entry_kind",
        "workspace_entries",
        "kind IN ('synthetic_source','scratchpad','conversation','evidence','work_link','handoff_result','google_message')",
    )
    op.execute(GUARDS)
    op.execute(HANDOFF_GUARDS)


def downgrade():
    raise RuntimeError("Retain Google message custody and human source reviews")


GUARDS = r"""
CREATE FUNCTION public.google_message_aware_time(value jsonb) RETURNS boolean
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE stamp timestamptz;
BEGIN
 IF jsonb_typeof(value) IS DISTINCT FROM 'string'
  OR (value#>>'{}') !~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,9})?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$'
 THEN RETURN false; END IF;
 BEGIN
  stamp:=(value#>>'{}')::timestamptz;
 EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format OR invalid_parameter_value THEN
  RETURN false;
 END;
 RETURN isfinite(stamp);
END $$;
CREATE FUNCTION public.google_message_read_current(rid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.google_message_read_requests r
  JOIN public.external_identities a ON a.id=r.account_id AND a.box_id=r.box_id AND a.principal_id=r.owner_id
  JOIN public.principals p ON p.id=r.owner_id AND p.box_id=r.box_id
  JOIN public.google_connection_credentials c ON c.account_id=a.id
  WHERE r.id=rid AND a.active AND p.principal_type='human' AND p.state='active' AND p.tombstoned_at IS NULL
   AND c.status='ready' AND c.sealed IS NOT NULL AND c.expires_at>clock_timestamp()
   AND c.binding_digest=r.binding_digest AND c.connected_at=r.connected_at)
$$;
CREATE FUNCTION public.google_message_source_valid(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.google_message_source_reviews v
  JOIN public.workspace_entries e ON e.id=v.entry_id
  JOIN public.encounter_workspaces w ON w.id=v.workspace_id
  JOIN public.google_message_snapshots z ON z.id=v.snapshot_id
  JOIN public.google_message_read_requests r ON r.id=z.read_id
  WHERE e.id=eid AND e.kind='google_message' AND r.kind='message' AND z.payload->>'status'='complete'
   AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)
    =(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
   AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
   AND (r.box_id,r.owner_id)=(v.box_id,v.owner_id) AND (z.box_id,z.owner_id)=(v.box_id,v.owner_id)
   AND v.reviewed_patient AND v.reviewed_exact_message AND v.reviewed_untrusted_source
   AND v.source_sha256=z.source_sha256 AND v.content_sha256=z.payload->>'content_sha256'
   AND e.content=z.payload->>'content' AND char_length(e.content) BETWEEN 1 AND 5000
   AND e.source_label=left('Google message: '||(z.payload->>'subject'),160)
   AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex'))
$$;
CREATE FUNCTION public.google_message_source_current(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.google_message_source_valid(eid) AND EXISTS(SELECT 1
  FROM public.google_message_source_reviews v JOIN public.google_message_snapshots z ON z.id=v.snapshot_id
  JOIN public.google_message_read_requests r ON r.id=z.read_id
  WHERE v.entry_id=eid AND public.google_message_read_current(r.id)
   AND NOT EXISTS(SELECT 1 FROM public.google_message_read_requests n
    WHERE n.account_id=r.account_id AND n.kind='message' AND n.message_id=r.message_id AND n.ordinal>r.ordinal))
$$;
CREATE FUNCTION public.guard_google_message_read() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE parent public.google_message_read_requests; observation public.google_message_snapshots;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Google read requests are immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id
    AND principal_type='human' AND state='active' AND tombstoned_at IS NULL)
  OR NOT EXISTS(SELECT 1 FROM public.external_identities a JOIN public.google_connection_credentials c ON c.account_id=a.id
   WHERE a.id=NEW.account_id AND a.box_id=NEW.box_id AND a.principal_id=NEW.owner_id AND a.active
    AND c.status='ready' AND c.sealed IS NOT NULL AND c.expires_at>clock_timestamp()
    AND c.binding_digest=NEW.binding_digest AND c.connected_at=NEW.connected_at)
  OR NEW.ordinal IS DISTINCT FROM (SELECT coalesce(max(ordinal),0)+1 FROM public.google_message_read_requests WHERE account_id=NEW.account_id)
  OR NEW.request_hash IS DISTINCT FROM public.research_json_digest(jsonb_build_object('kind',NEW.kind,'account_id',NEW.account_id,
   'observation_id',NEW.observation_id,'observation_sha256',NEW.observation_sha256,'message_id',NEW.message_id,'thread_id',NEW.thread_id))
 THEN RAISE EXCEPTION 'Google read binding invalid' USING ERRCODE='23514'; END IF;
 IF NEW.kind='message' THEN
  SELECT * INTO parent FROM public.google_message_read_requests WHERE id=NEW.observation_id;
  SELECT * INTO observation FROM public.google_message_snapshots WHERE read_id=parent.id;
  IF parent.id IS NULL OR parent.kind<>'list' OR observation.id IS NULL
   OR (parent.box_id,parent.owner_id,parent.account_id,parent.binding_digest,parent.connected_at,parent.grant_sha256)
    IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.account_id,NEW.binding_digest,NEW.connected_at,NEW.grant_sha256)
   OR observation.source_sha256 IS DISTINCT FROM NEW.observation_sha256
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(observation.payload->'items') item
     WHERE item->>'id'=NEW.message_id AND (NEW.thread_id IS NULL OR item->>'thread_id'=NEW.thread_id))
  THEN RAISE EXCEPTION 'Google message not observed' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER google_message_read_guard BEFORE INSERT OR UPDATE OR DELETE ON public.google_message_read_requests
 FOR EACH ROW EXECUTE FUNCTION public.guard_google_message_read();
CREATE FUNCTION public.guard_google_message_snapshot() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r public.google_message_read_requests; payload jsonb; custody jsonb; item jsonb; ids text[]:=ARRAY[]::text[];
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Google snapshots are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM public.google_message_read_requests WHERE id=NEW.read_id;
 payload:=NEW.payload; custody:=payload->'custody';
 IF r.id IS NULL OR (r.box_id,r.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NOT public.google_message_read_current(r.id)
  OR NEW.payload_sha256 IS DISTINCT FROM public.research_json_digest(payload)
  OR NEW.source_sha256 IS DISTINCT FROM public.research_json_digest(jsonb_build_object('read_id',r.id,'account_id',r.account_id,
     'ordinal',r.ordinal,'request_hash',r.request_hash,'binding_digest',r.binding_digest,'grant_sha256',r.grant_sha256,'payload_sha256',NEW.payload_sha256))
 THEN RAISE EXCEPTION 'Google snapshot binding invalid' USING ERRCODE='23514'; END IF;
 IF r.kind='message' AND (
  NOT public.finance_settings_keys(payload,ARRAY['message_id','thread_id','history_id','subject','sender','received_at','is_read','observed_at','status','content','reason','raw_sha256','content_sha256','custody'])
  OR NOT public.finance_settings_keys(custody,ARRAY['account_id','binding_digest','connected_at','grant_sha256'])
  OR jsonb_typeof(payload->'subject') IS DISTINCT FROM 'string' OR char_length(payload->>'subject')>998
  OR jsonb_typeof(payload->'sender') IS DISTINCT FROM 'string' OR char_length(payload->>'sender')>320
  OR jsonb_typeof(payload->'is_read') IS DISTINCT FROM 'boolean'
  OR NOT public.research_hash(payload->'raw_sha256')
  OR NOT public.google_message_aware_time(payload->'received_at')
  OR NOT public.google_message_aware_time(payload->'observed_at')
  OR (payload->'history_id' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(payload->'history_id') IS DISTINCT FROM 'string' OR coalesce(payload->>'history_id' ~ '^[0-9]{1,32}$',false) IS NOT TRUE))
  OR
  payload->>'message_id' IS DISTINCT FROM r.message_id
  OR jsonb_typeof(payload->'thread_id') IS DISTINCT FROM 'string'
  OR coalesce(payload->>'thread_id' ~ '^[A-Za-z0-9_-]{1,128}$',false) IS NOT TRUE
  OR (r.thread_id IS NOT NULL AND payload->>'thread_id' IS DISTINCT FROM r.thread_id)
  OR custody->>'account_id' IS DISTINCT FROM r.account_id::text OR custody->>'binding_digest' IS DISTINCT FROM r.binding_digest
  OR custody->>'grant_sha256' IS DISTINCT FROM r.grant_sha256
  OR (CASE WHEN public.google_message_aware_time(custody->'connected_at')
     THEN (custody->>'connected_at')::timestamptz END) IS DISTINCT FROM r.connected_at
  OR jsonb_typeof(payload->'status') IS DISTINCT FROM 'string'
  OR coalesce(payload->>'status' IN ('complete','needs_human'),false) IS NOT TRUE
  OR (payload->>'status'='complete' AND (jsonb_typeof(payload->'content') IS DISTINCT FROM 'string'
    OR char_length(payload->>'content') NOT BETWEEN 1 AND 5000 OR payload->'reason' IS DISTINCT FROM 'null'::jsonb
    OR payload->>'content_sha256' IS DISTINCT FROM encode(sha256(convert_to(payload->>'content','UTF8')),'hex')))
  OR (payload->>'status'='needs_human' AND (payload->'content' IS DISTINCT FROM 'null'::jsonb
    OR payload->'content_sha256' IS DISTINCT FROM 'null'::jsonb OR jsonb_typeof(payload->'reason') IS DISTINCT FROM 'string'
    OR coalesce(payload->>'reason' IN ('attachment','html_only','unsupported_mime','oversize','ambiguous','invalid_encoding'),false) IS NOT TRUE))
 ) THEN RAISE EXCEPTION 'Google message snapshot invalid' USING ERRCODE='23514'; END IF;
 IF r.kind='list' THEN
  IF NOT public.finance_settings_keys(payload,ARRAY['kind','account','items','more','observed_at'])
   OR payload->>'kind' IS DISTINCT FROM 'mail' OR jsonb_typeof(payload->'items') IS DISTINCT FROM 'array'
   OR jsonb_array_length(payload->'items')>25 OR jsonb_typeof(payload->'more') IS DISTINCT FROM 'boolean'
   OR NOT public.finance_settings_keys(payload->'account',ARRAY['label','email'])
   OR NOT public.google_message_aware_time(payload->'observed_at')
  THEN RAISE EXCEPTION 'Google metadata observation invalid' USING ERRCODE='23514'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(payload->'items') LOOP
   IF (NOT public.finance_settings_keys(item,ARRAY['id','subject','sender','received_at','is_read'])
     AND NOT public.finance_settings_keys(item,ARRAY['id','thread_id','subject','sender','received_at','is_read']))
    OR item->>'id' !~ '^[A-Za-z0-9_-]{1,128}$' OR item->>'id'=ANY(ids)
    OR jsonb_typeof(item->'subject') IS DISTINCT FROM 'string' OR char_length(item->>'subject')>998
    OR jsonb_typeof(item->'sender') IS DISTINCT FROM 'string' OR char_length(item->>'sender')>320
    OR jsonb_typeof(item->'is_read') IS DISTINCT FROM 'boolean'
    OR NOT public.google_message_aware_time(item->'received_at')
   THEN RAISE EXCEPTION 'Google metadata item invalid' USING ERRCODE='23514'; END IF;
   ids:=array_append(ids,item->>'id');
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER google_message_snapshot_guard BEFORE INSERT OR UPDATE OR DELETE ON public.google_message_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.guard_google_message_snapshot();
CREATE FUNCTION public.guard_google_message_review() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE w public.encounter_workspaces; e public.workspace_entries; z public.google_message_snapshots; r public.google_message_read_requests;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Google source reviews are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 SELECT * INTO e FROM public.workspace_entries WHERE id=NEW.entry_id;
 SELECT * INTO z FROM public.google_message_snapshots WHERE id=NEW.snapshot_id;
 SELECT * INTO r FROM public.google_message_read_requests WHERE id=z.read_id;
 IF w.id IS NULL OR (w.box_id,w.owner_id,w.patient_link_id,w.revision) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.patient_link_id,NEW.workspace_revision)
  OR e.id IS NULL OR (e.workspace_id,e.box_id,e.actor_id,e.kind,e.revision,e.request_hash,e.idempotency_key)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,'google_message',NEW.workspace_revision,NEW.request_hash,NEW.idempotency_key)
  OR z.id IS NULL OR r.kind IS DISTINCT FROM 'message' OR z.payload->>'status' IS DISTINCT FROM 'complete'
  OR (z.box_id,z.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NOT public.google_message_read_current(r.id)
  OR EXISTS(SELECT 1 FROM public.google_message_read_requests n WHERE n.account_id=r.account_id AND n.kind='message' AND n.message_id=r.message_id AND n.ordinal>r.ordinal)
  OR e.content IS DISTINCT FROM z.payload->>'content' OR NEW.content_sha256 IS DISTINCT FROM z.payload->>'content_sha256'
  OR NEW.source_sha256 IS DISTINCT FROM z.source_sha256
  OR NEW.request_hash IS DISTINCT FROM public.research_json_digest(jsonb_build_object('expected',NEW.expected_revision,'read_id',r.id,
    'source_sha256',NEW.source_sha256,'patient_link_id',NEW.patient_link_id,'reviewed_patient',NEW.reviewed_patient,
    'reviewed_exact_message',NEW.reviewed_exact_message,'reviewed_untrusted_source',NEW.reviewed_untrusted_source))
 THEN RAISE EXCEPTION 'Google source review binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER google_message_review_guard BEFORE INSERT OR UPDATE OR DELETE ON public.google_message_source_reviews
 FOR EACH ROW EXECUTE FUNCTION public.guard_google_message_review();
CREATE FUNCTION public.guard_google_message_entry() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.kind='google_message' AND NOT public.google_message_source_valid(NEW.id)
 THEN RAISE EXCEPTION 'Google source review required' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER google_message_entry_guard AFTER INSERT ON public.workspace_entries
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_google_message_entry();
"""


TABLES = "\nCREATE TABLE google_message_read_requests (\n\tid UUID NOT NULL, \n\taccount_id UUID NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\tidempotency_key VARCHAR(100) NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tbinding_digest VARCHAR(64) NOT NULL, \n\tgrant_sha256 VARCHAR(64) NOT NULL, \n\tconnected_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tobservation_id UUID, \n\tobservation_sha256 VARCHAR(64), \n\tmessage_id VARCHAR(128), \n\tthread_id VARCHAR(128), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(account_id, box_id, owner_id) REFERENCES external_identities (id, box_id, principal_id), \n\tFOREIGN KEY(observation_id, box_id, owner_id) REFERENCES google_message_read_requests (id, box_id, owner_id), \n\tCONSTRAINT uq_google_message_read_scope UNIQUE (id, box_id, owner_id), \n\tCONSTRAINT uq_google_message_read_ordinal UNIQUE (account_id, ordinal), \n\tCONSTRAINT uq_google_message_read_key UNIQUE (box_id, owner_id, idempotency_key), \n\tCONSTRAINT ck_google_message_read_kind CHECK (kind IN ('list','message') AND ordinal >= 1), \n\tCONSTRAINT ck_google_message_read_key CHECK (char_length(idempotency_key) BETWEEN 1 AND 100), \n\tCONSTRAINT ck_google_message_read_selection CHECK ((kind='list' AND observation_id IS NULL AND observation_sha256 IS NULL AND message_id IS NULL AND thread_id IS NULL) OR (kind='message' AND observation_id IS NOT NULL AND observation_sha256 ~ '^[0-9a-f]{64}$' AND message_id ~ '^[A-Za-z0-9_-]{1,128}$' AND (thread_id IS NULL OR thread_id ~ '^[A-Za-z0-9_-]{1,128}$'))), \n\tCHECK (request_hash ~ '^[a-f0-9]{64}$' AND binding_digest ~ '^[a-f0-9]{64}$' AND grant_sha256 ~ '^[a-f0-9]{64}$')\n)\n\n;\n\nCREATE TABLE google_message_snapshots (\n\tid UUID NOT NULL, \n\tread_id UUID NOT NULL, \n\tpayload JSONB NOT NULL, \n\tpayload_sha256 VARCHAR(64) NOT NULL, \n\tsource_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(read_id, box_id, owner_id) REFERENCES google_message_read_requests (id, box_id, owner_id), \n\tCONSTRAINT uq_google_message_snapshot_read UNIQUE (read_id), \n\tCONSTRAINT uq_google_message_snapshot_scope UNIQUE (id, box_id, owner_id), \n\tCHECK (payload_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 65536)\n)\n\n;\n\nCREATE TABLE google_message_source_reviews (\n\tid UUID NOT NULL, \n\tentry_id UUID NOT NULL, \n\tsnapshot_id UUID NOT NULL, \n\tpatient_link_id UUID NOT NULL, \n\texpected_revision INTEGER NOT NULL, \n\tworkspace_revision INTEGER NOT NULL, \n\tidempotency_key VARCHAR(100) NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tsource_sha256 VARCHAR(64) NOT NULL, \n\tcontent_sha256 VARCHAR(64) NOT NULL, \n\treviewed_patient BOOLEAN NOT NULL, \n\treviewed_exact_message BOOLEAN NOT NULL, \n\treviewed_untrusted_source BOOLEAN NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), \n\tFOREIGN KEY(entry_id, workspace_id, box_id) REFERENCES workspace_entries (id, workspace_id, box_id), \n\tFOREIGN KEY(snapshot_id, box_id, owner_id) REFERENCES google_message_snapshots (id, box_id, owner_id), \n\tFOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), \n\tCONSTRAINT uq_google_message_review_entry UNIQUE (entry_id), \n\tCONSTRAINT uq_google_message_review_snapshot UNIQUE (workspace_id, snapshot_id), \n\tCONSTRAINT uq_google_message_review_key UNIQUE (workspace_id, idempotency_key), \n\tCONSTRAINT ck_google_message_review_revision CHECK (expected_revision >= 1 AND workspace_revision=expected_revision+1), \n\tCONSTRAINT ck_google_message_review_checks CHECK (reviewed_patient AND reviewed_exact_message AND reviewed_untrusted_source), \n\tCHECK (request_hash ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$' AND content_sha256 ~ '^[a-f0-9]{64}$')\n)\n\n;"

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
      'kind',CASE WHEN kind='google_message' THEN 'evidence' ELSE kind END,'sha256',encode(sha256(convert_to(content,'UTF8')),'hex')) ORDER BY category,revision),'[]'::jsonb)
  INTO selected FROM (
   SELECT e.*,0 category FROM public.workspace_entries e WHERE workspace_id=wid AND actor_id=owner AND box_id=h.box_id
    AND kind='scratchpad' AND bot->>'include_notebook'='true' AND revision=(SELECT max(revision) FROM public.workspace_entries WHERE workspace_id=wid AND kind='scratchpad')
   UNION ALL
   SELECT e.*,1 category FROM public.workspace_entries e WHERE workspace_id=wid AND actor_id=owner AND box_id=h.box_id
    AND (kind IN ('evidence','synthetic_source') OR (kind='google_message' AND public.google_message_source_current(e.id))) AND bot->>'include_evidence'='true'
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
   OR source->>'kind' IS DISTINCT FROM (CASE WHEN source_entry.kind='google_message' THEN 'evidence' ELSE source_entry.kind END)
   OR (source_entry.kind='google_message' AND NOT public.google_message_source_current(source_entry.id))
   OR source->>'label' IS DISTINCT FROM coalesce(source_entry.source_label,'Your jotted notes')
   OR source->>'sha256' IS DISTINCT FROM encode(sha256(convert_to(source_entry.content,'UTF8')),'hex')
   OR (source_entry.kind='scratchpad' AND EXISTS(SELECT 1 FROM public.workspace_entries
       WHERE workspace_id=NEW.workspace_id AND kind='scratchpad' AND revision>source_entry.revision))
  THEN RAISE EXCEPTION 'handoff review source invalid' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
"""
