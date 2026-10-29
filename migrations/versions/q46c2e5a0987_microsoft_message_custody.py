"""Immutable selected Outlook message custody using existing delegated Mail.Read."""
from pathlib import Path
from runpy import run_path

from alembic import op

revision = "q46c2e5a0987"
down_revision = "p35b1d4f9876"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)
    op.drop_constraint("ck_workspace_entry_kind", "workspace_entries", type_="check")
    op.create_check_constraint("ck_workspace_entry_kind", "workspace_entries", "kind IN ('synthetic_source','scratchpad','conversation','evidence','work_link','handoff_result','google_message','microsoft_message','google_calendar','efax_inbound_source','fax_inbound_source','ehr_read_source','calendar_import_source')")
    op.execute(GUARDS)
    versions = Path(__file__).parent
    fax = run_path(str(versions / "h68e0c4f1239_fax_reviewed_source.py"))
    note = run_path(str(versions / "j79f1d5a2340_human_shared_note_custody.py"))
    directions = run_path(str(versions / "k80e6a9d4321_saved_note_drafting_directions.py"))
    ehr = run_path(str(versions / "m02e8a1c6543_ehr_read_custody.py"))
    calendar = run_path(str(versions / "p35b1d4f9876_calendar_import_source.py"))
    for name, previous, ehr_extensions, calendar_extensions in (
        ("HANDOFF_GUARDS", note["REVIEW_EXTENSIONS"], ehr["REVIEW_EXTENSIONS"], calendar["REVIEW_EXTENSIONS"]),
        ("MODEL_GUARDS", (*note["MODEL_EXTENSIONS"], *directions["DIRECTIONS_EXTENSIONS"]), ehr["MODEL_EXTENSIONS"], calendar["MODEL_EXTENSIONS"]),
    ):
        sql = fax[name]
        for before, after in previous:
            if sql.count(before) != 1:
                raise RuntimeError("Previous selected-source guard changed")
            sql = sql.replace(before, after)
        for before, after, count in (*ehr_extensions, *calendar_extensions):
            if sql.count(before) != count:
                raise RuntimeError("Previous selected-source extension changed")
            sql = sql.replace(before, after)
        # Preserve each existing source rule; Outlook receives its own DB custody.
        sql = sql.replace("'google_message',", "'google_message','microsoft_message',")
        sql = sql.replace("(kind='google_message' AND public.google_message_source_current(e.id))", "(kind='google_message' AND public.google_message_source_current(e.id)) OR (kind='microsoft_message' AND public.microsoft_message_source_current(e.id))")
        sql = sql.replace("OR (source_entry.kind='google_message' AND NOT public.google_message_source_current(source_entry.id))", "OR (source_entry.kind='google_message' AND NOT public.google_message_source_current(source_entry.id)) OR (source_entry.kind='microsoft_message' AND NOT public.microsoft_message_source_current(source_entry.id))")
        sql = sql.replace("OR (entry.kind='google_message' AND NOT public.google_message_source_current(entry.id))", "OR (entry.kind='google_message' AND NOT public.google_message_source_current(entry.id)) OR (entry.kind='microsoft_message' AND NOT public.microsoft_message_source_current(entry.id))")
        if "microsoft_message_source_current" not in sql:
            raise RuntimeError("Outlook selected-source guard missing")
        op.execute(sql)


def downgrade():
    raise RuntimeError("Retain Outlook message custody and human source reviews")


GUARDS = r"""
CREATE FUNCTION public.microsoft_message_aware_time(value jsonb) RETURNS boolean
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
CREATE FUNCTION public.microsoft_message_read_current(rid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.microsoft_message_read_requests r
  JOIN public.external_identities a ON a.id=r.account_id AND a.box_id=r.box_id AND a.principal_id=r.owner_id
  JOIN public.principals p ON p.id=r.owner_id AND p.box_id=r.box_id
  JOIN public.microsoft_connection_credentials c ON c.account_id=a.id
  WHERE r.id=rid AND a.active AND p.principal_type='human' AND p.state='active' AND p.tombstoned_at IS NULL
   AND c.status='ready' AND c.sealed IS NOT NULL AND c.expires_at>clock_timestamp()
   AND c.binding_digest=r.binding_digest AND c.connected_at=r.connected_at
   AND NOT EXISTS (SELECT 1 FROM public.microsoft_connection_attempts t WHERE t.account_id=a.id
       AND t.status IN ('pending','exchanging') AND t.expires_at>clock_timestamp()))
$$;
CREATE FUNCTION public.microsoft_message_source_valid(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.microsoft_message_source_reviews v
  JOIN public.workspace_entries e ON e.id=v.entry_id
  JOIN public.encounter_workspaces w ON w.id=v.workspace_id
  JOIN public.microsoft_message_snapshots z ON z.id=v.snapshot_id
  JOIN public.microsoft_message_read_requests r ON r.id=z.read_id
  WHERE e.id=eid AND e.kind='microsoft_message' AND r.kind='message' AND z.payload->>'status'='complete'
   AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)
    =(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
   AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
   AND (r.box_id,r.owner_id)=(v.box_id,v.owner_id) AND (z.box_id,z.owner_id)=(v.box_id,v.owner_id)
   AND v.reviewed_patient AND v.reviewed_exact_message AND v.reviewed_untrusted_source
   AND v.source_sha256=z.source_sha256 AND v.content_sha256=z.payload->>'content_sha256'
   AND e.content=z.payload->>'content' AND char_length(e.content) BETWEEN 1 AND 5000
   AND e.source_label=left('Outlook message: '||(z.payload->>'subject'),160)
   AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex'))
$$;
CREATE FUNCTION public.microsoft_message_source_current(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.microsoft_message_source_valid(eid) AND EXISTS(SELECT 1
  FROM public.microsoft_message_source_reviews v JOIN public.microsoft_message_snapshots z ON z.id=v.snapshot_id
  JOIN public.microsoft_message_read_requests r ON r.id=z.read_id
  WHERE v.entry_id=eid AND public.microsoft_message_read_current(r.id)
   AND NOT EXISTS(SELECT 1 FROM public.microsoft_message_read_requests n
    WHERE n.account_id=r.account_id AND n.kind='message' AND n.message_id=r.message_id AND n.ordinal>r.ordinal))
$$;
CREATE FUNCTION public.guard_microsoft_message_read() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE parent public.microsoft_message_read_requests; observation public.microsoft_message_snapshots;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Microsoft read requests are immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id
    AND principal_type='human' AND state='active' AND tombstoned_at IS NULL)
  OR NOT EXISTS(SELECT 1 FROM public.external_identities a JOIN public.microsoft_connection_credentials c ON c.account_id=a.id
   WHERE a.id=NEW.account_id AND a.box_id=NEW.box_id AND a.principal_id=NEW.owner_id AND a.active
    AND c.status='ready' AND c.sealed IS NOT NULL AND c.expires_at>clock_timestamp()
    AND c.binding_digest=NEW.binding_digest AND c.connected_at=NEW.connected_at)
  OR NEW.ordinal IS DISTINCT FROM (SELECT coalesce(max(ordinal),0)+1 FROM public.microsoft_message_read_requests WHERE account_id=NEW.account_id)
  OR NEW.request_hash IS DISTINCT FROM public.research_json_digest(jsonb_build_object('kind',NEW.kind,'account_id',NEW.account_id,
   'observation_id',NEW.observation_id,'observation_sha256',NEW.observation_sha256,'message_id',NEW.message_id,'thread_id',NEW.thread_id))
 THEN RAISE EXCEPTION 'Microsoft read binding invalid' USING ERRCODE='23514'; END IF;
 IF NEW.kind='message' THEN
  SELECT * INTO parent FROM public.microsoft_message_read_requests WHERE id=NEW.observation_id;
  SELECT * INTO observation FROM public.microsoft_message_snapshots WHERE read_id=parent.id;
  IF parent.id IS NULL OR parent.kind<>'list' OR observation.id IS NULL
   OR (parent.box_id,parent.owner_id,parent.account_id,parent.binding_digest,parent.connected_at,parent.grant_sha256)
    IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.account_id,NEW.binding_digest,NEW.connected_at,NEW.grant_sha256)
   OR observation.source_sha256 IS DISTINCT FROM NEW.observation_sha256
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(observation.payload->'items') item
     WHERE item->>'id'=NEW.message_id AND (NEW.thread_id IS NULL OR item->>'thread_id'=NEW.thread_id))
  THEN RAISE EXCEPTION 'Microsoft message not observed' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER microsoft_message_read_guard BEFORE INSERT OR UPDATE OR DELETE ON public.microsoft_message_read_requests
 FOR EACH ROW EXECUTE FUNCTION public.guard_microsoft_message_read();
CREATE FUNCTION public.guard_microsoft_message_snapshot() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r public.microsoft_message_read_requests; payload jsonb; custody jsonb; item jsonb; ids text[]:=ARRAY[]::text[];
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Microsoft snapshots are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM public.microsoft_message_read_requests WHERE id=NEW.read_id;
 payload:=NEW.payload; custody:=payload->'custody';
 IF r.id IS NULL OR (r.box_id,r.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NOT public.microsoft_message_read_current(r.id)
  OR NEW.payload_sha256 IS DISTINCT FROM public.research_json_digest(payload)
  OR NEW.source_sha256 IS DISTINCT FROM public.research_json_digest(jsonb_build_object('read_id',r.id,'account_id',r.account_id,
     'ordinal',r.ordinal,'request_hash',r.request_hash,'binding_digest',r.binding_digest,'grant_sha256',r.grant_sha256,'payload_sha256',NEW.payload_sha256))
 THEN RAISE EXCEPTION 'Microsoft snapshot binding invalid' USING ERRCODE='23514'; END IF;
 IF r.kind='message' AND (
  NOT public.finance_settings_keys(payload,ARRAY['message_id','thread_id','change_key','subject','sender','received_at','is_read','observed_at','status','content','reason','raw_sha256','content_sha256','custody'])
  OR NOT public.finance_settings_keys(custody,ARRAY['account_id','binding_digest','connected_at','grant_sha256'])
  OR jsonb_typeof(payload->'subject') IS DISTINCT FROM 'string' OR char_length(payload->>'subject')>998
  OR jsonb_typeof(payload->'sender') IS DISTINCT FROM 'string' OR char_length(payload->>'sender')>320
  OR jsonb_typeof(payload->'is_read') IS DISTINCT FROM 'boolean'
  OR NOT public.research_hash(payload->'raw_sha256')
  OR NOT public.microsoft_message_aware_time(payload->'received_at')
  OR NOT public.microsoft_message_aware_time(payload->'observed_at')
  OR char_length(payload->>'change_key')>2048
  OR (payload->'change_key' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(payload->'change_key') IS DISTINCT FROM 'string' OR coalesce(payload->>'change_key' ~ '^[A-Za-z0-9_+/=-]+$',false) IS NOT TRUE))
  OR
  payload->>'message_id' IS DISTINCT FROM r.message_id
  OR jsonb_typeof(payload->'thread_id') IS DISTINCT FROM 'string' OR char_length(payload->>'thread_id')>2048
  OR coalesce(payload->>'thread_id' ~ '^[A-Za-z0-9_+/=-]+$',false) IS NOT TRUE
  OR (r.thread_id IS NOT NULL AND payload->>'thread_id' IS DISTINCT FROM r.thread_id)
  OR custody->>'account_id' IS DISTINCT FROM r.account_id::text OR custody->>'binding_digest' IS DISTINCT FROM r.binding_digest
  OR custody->>'grant_sha256' IS DISTINCT FROM r.grant_sha256
  OR (CASE WHEN public.microsoft_message_aware_time(custody->'connected_at')
     THEN (custody->>'connected_at')::timestamptz END) IS DISTINCT FROM r.connected_at
  OR jsonb_typeof(payload->'status') IS DISTINCT FROM 'string'
  OR coalesce(payload->>'status' IN ('complete','needs_human'),false) IS NOT TRUE
  OR (payload->>'status'='complete' AND (jsonb_typeof(payload->'content') IS DISTINCT FROM 'string'
    OR char_length(payload->>'content') NOT BETWEEN 1 AND 5000 OR payload->'reason' IS DISTINCT FROM 'null'::jsonb
    OR payload->>'content_sha256' IS DISTINCT FROM encode(sha256(convert_to(payload->>'content','UTF8')),'hex')))
  OR (payload->>'status'='needs_human' AND (payload->'content' IS DISTINCT FROM 'null'::jsonb
    OR payload->'content_sha256' IS DISTINCT FROM 'null'::jsonb OR jsonb_typeof(payload->'reason') IS DISTINCT FROM 'string'
    OR coalesce(payload->>'reason' IN ('attachment','html_only','unsupported_mime','oversize','ambiguous','invalid_encoding'),false) IS NOT TRUE))
 ) THEN RAISE EXCEPTION 'Microsoft message snapshot invalid' USING ERRCODE='23514'; END IF;
 IF r.kind='list' THEN
  IF NOT public.finance_settings_keys(payload,ARRAY['kind','account','items','more','observed_at'])
   OR payload->>'kind' IS DISTINCT FROM 'mail' OR jsonb_typeof(payload->'items') IS DISTINCT FROM 'array'
   OR jsonb_array_length(payload->'items')>25 OR jsonb_typeof(payload->'more') IS DISTINCT FROM 'boolean'
   OR NOT public.finance_settings_keys(payload->'account',ARRAY['label','email'])
   OR NOT public.microsoft_message_aware_time(payload->'observed_at')
  THEN RAISE EXCEPTION 'Microsoft metadata observation invalid' USING ERRCODE='23514'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(payload->'items') LOOP
   IF (NOT public.finance_settings_keys(item,ARRAY['id','subject','sender','received_at','is_read'])
     AND NOT public.finance_settings_keys(item,ARRAY['id','thread_id','subject','sender','received_at','is_read']))
    OR char_length(item->>'id')>2048
    OR item->>'id' !~ '^[A-Za-z0-9_+/=-]+$' OR item->>'id'=ANY(ids)
    OR jsonb_typeof(item->'subject') IS DISTINCT FROM 'string' OR char_length(item->>'subject')>998
    OR jsonb_typeof(item->'sender') IS DISTINCT FROM 'string' OR char_length(item->>'sender')>320
    OR jsonb_typeof(item->'is_read') IS DISTINCT FROM 'boolean'
    OR NOT public.microsoft_message_aware_time(item->'received_at')
   THEN RAISE EXCEPTION 'Microsoft metadata item invalid' USING ERRCODE='23514'; END IF;
   ids:=array_append(ids,item->>'id');
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER microsoft_message_snapshot_guard BEFORE INSERT OR UPDATE OR DELETE ON public.microsoft_message_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.guard_microsoft_message_snapshot();
CREATE FUNCTION public.guard_microsoft_message_review() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE w public.encounter_workspaces; e public.workspace_entries; z public.microsoft_message_snapshots; r public.microsoft_message_read_requests;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Microsoft source reviews are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 SELECT * INTO e FROM public.workspace_entries WHERE id=NEW.entry_id;
 SELECT * INTO z FROM public.microsoft_message_snapshots WHERE id=NEW.snapshot_id;
 SELECT * INTO r FROM public.microsoft_message_read_requests WHERE id=z.read_id;
 IF w.id IS NULL OR (w.box_id,w.owner_id,w.patient_link_id,w.revision) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.patient_link_id,NEW.workspace_revision)
  OR e.id IS NULL OR (e.workspace_id,e.box_id,e.actor_id,e.kind,e.revision,e.request_hash,e.idempotency_key)
    IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,'microsoft_message',NEW.workspace_revision,NEW.request_hash,NEW.idempotency_key)
  OR z.id IS NULL OR r.kind IS DISTINCT FROM 'message' OR z.payload->>'status' IS DISTINCT FROM 'complete'
  OR (z.box_id,z.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NOT public.microsoft_message_read_current(r.id)
  OR EXISTS(SELECT 1 FROM public.microsoft_message_read_requests n WHERE n.account_id=r.account_id AND n.kind='message' AND n.message_id=r.message_id AND n.ordinal>r.ordinal)
  OR e.content IS DISTINCT FROM z.payload->>'content' OR NEW.content_sha256 IS DISTINCT FROM z.payload->>'content_sha256'
  OR NEW.source_sha256 IS DISTINCT FROM z.source_sha256
  OR NEW.request_hash IS DISTINCT FROM public.research_json_digest(jsonb_build_object('expected',NEW.expected_revision,'read_id',r.id,
    'source_sha256',NEW.source_sha256,'patient_link_id',NEW.patient_link_id,'reviewed_patient',NEW.reviewed_patient,
    'reviewed_exact_message',NEW.reviewed_exact_message,'reviewed_untrusted_source',NEW.reviewed_untrusted_source))
 THEN RAISE EXCEPTION 'Microsoft source review binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER microsoft_message_review_guard BEFORE INSERT OR UPDATE OR DELETE ON public.microsoft_message_source_reviews
 FOR EACH ROW EXECUTE FUNCTION public.guard_microsoft_message_review();
CREATE FUNCTION public.guard_microsoft_message_entry() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.kind='microsoft_message' AND NOT public.microsoft_message_source_valid(NEW.id)
 THEN RAISE EXCEPTION 'Microsoft source review required' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER microsoft_message_entry_guard AFTER INSERT ON public.workspace_entries
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_microsoft_message_entry();
"""

TABLES = r"""
CREATE TABLE microsoft_message_read_requests (
	id UUID NOT NULL,
	account_id UUID NOT NULL,
	ordinal INTEGER NOT NULL,
	kind VARCHAR(16) NOT NULL,
	idempotency_key VARCHAR(100) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	binding_digest VARCHAR(64) NOT NULL,
	grant_sha256 VARCHAR(64) NOT NULL,
	connected_at TIMESTAMP WITH TIME ZONE NOT NULL,
	observation_id UUID,
	observation_sha256 VARCHAR(64),
	message_id VARCHAR(2048),
	thread_id VARCHAR(2048),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(account_id, box_id, owner_id) REFERENCES external_identities (id, box_id, principal_id),
	FOREIGN KEY(observation_id, box_id, owner_id) REFERENCES microsoft_message_read_requests (id, box_id, owner_id),
	CONSTRAINT uq_microsoft_message_read_scope UNIQUE (id, box_id, owner_id),
	CONSTRAINT uq_microsoft_message_read_ordinal UNIQUE (account_id, ordinal),
	CONSTRAINT uq_microsoft_message_read_key UNIQUE (box_id, owner_id, idempotency_key),
	CONSTRAINT ck_microsoft_message_read_kind CHECK (kind IN ('list','message') AND ordinal >= 1),
	CONSTRAINT ck_microsoft_message_read_key CHECK (char_length(idempotency_key) BETWEEN 1 AND 100),
	CONSTRAINT ck_microsoft_message_read_selection CHECK ((kind='list' AND observation_id IS NULL AND observation_sha256 IS NULL AND message_id IS NULL AND thread_id IS NULL) OR (kind='message' AND observation_id IS NOT NULL AND observation_sha256 ~ '^[0-9a-f]{64}$' AND message_id ~ '^[A-Za-z0-9_+/=-]+$' AND (thread_id IS NULL OR thread_id ~ '^[A-Za-z0-9_+/=-]+$'))),
	CHECK (request_hash ~ '^[a-f0-9]{64}$' AND binding_digest ~ '^[a-f0-9]{64}$' AND grant_sha256 ~ '^[a-f0-9]{64}$')
)

;

CREATE TABLE microsoft_message_snapshots (
	id UUID NOT NULL,
	read_id UUID NOT NULL,
	payload JSONB NOT NULL,
	payload_sha256 VARCHAR(64) NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(read_id, box_id, owner_id) REFERENCES microsoft_message_read_requests (id, box_id, owner_id),
	CONSTRAINT uq_microsoft_message_snapshot_read UNIQUE (read_id),
	CONSTRAINT uq_microsoft_message_snapshot_scope UNIQUE (id, box_id, owner_id),
	CHECK (payload_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$'),
	CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 65536)
)

;

CREATE TABLE microsoft_message_source_reviews (
	id UUID NOT NULL,
	entry_id UUID NOT NULL,
	snapshot_id UUID NOT NULL,
	patient_link_id UUID NOT NULL,
	expected_revision INTEGER NOT NULL,
	workspace_revision INTEGER NOT NULL,
	idempotency_key VARCHAR(100) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	reviewed_patient BOOLEAN NOT NULL,
	reviewed_exact_message BOOLEAN NOT NULL,
	reviewed_untrusted_source BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id),
	FOREIGN KEY(entry_id, workspace_id, box_id) REFERENCES workspace_entries (id, workspace_id, box_id),
	FOREIGN KEY(snapshot_id, box_id, owner_id) REFERENCES microsoft_message_snapshots (id, box_id, owner_id),
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id),
	CONSTRAINT uq_microsoft_message_review_entry UNIQUE (entry_id),
	CONSTRAINT uq_microsoft_message_review_snapshot UNIQUE (workspace_id, snapshot_id),
	CONSTRAINT uq_microsoft_message_review_key UNIQUE (workspace_id, idempotency_key),
	CONSTRAINT ck_microsoft_message_review_revision CHECK (expected_revision >= 1 AND workspace_revision=expected_revision+1),
	CONSTRAINT ck_microsoft_message_review_checks CHECK (reviewed_patient AND reviewed_exact_message AND reviewed_untrusted_source),
	CHECK (request_hash ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$' AND content_sha256 ~ '^[a-f0-9]{64}$')
)

;"""
