"""Explicit Outlook calendar observations and reviewed linked-visit source custody.

Only additive tables and provider-specific guards. No external writes, grants or
private-notebook capability; current actor, account and source authority remain
mandatory at selection and model/handoff use.
"""

from pathlib import Path
from runpy import run_path

from alembic import op

revision = "cc68d2f1a903"
down_revision = "bb57e3d10c964"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)
    op.drop_constraint("ck_workspace_entry_kind", "workspace_entries", type_="check")
    op.create_check_constraint("ck_workspace_entry_kind", "workspace_entries",
        "kind IN ('synthetic_source','scratchpad','conversation','evidence','work_link','handoff_result','google_message','microsoft_message','google_calendar','microsoft_calendar','efax_inbound_source','fax_inbound_source','ehr_read_source','calendar_import_source')")
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
        # Add this provider without replacing any email, fax, EHR, note or import rule.
        for before, after, count in (
            ("'google_calendar'", "'google_calendar','microsoft_calendar'", 4 if name == "HANDOFF_GUARDS" else 2),
            ("(kind='google_calendar','microsoft_calendar' AND public.google_calendar_source_current(e.id))", "(kind='google_calendar' AND public.google_calendar_source_current(e.id)) OR (kind='microsoft_calendar' AND public.microsoft_calendar_source_current(e.id))", 1 if name == "HANDOFF_GUARDS" else 0),
            ("(source_entry.kind='google_calendar','microsoft_calendar' AND NOT public.google_calendar_source_current(source_entry.id))", "(source_entry.kind='google_calendar' AND NOT public.google_calendar_source_current(source_entry.id)) OR (source_entry.kind='microsoft_calendar' AND NOT public.microsoft_calendar_source_current(source_entry.id))", 1 if name == "HANDOFF_GUARDS" else 0),
            ("(entry.kind='google_calendar','microsoft_calendar' AND NOT public.google_calendar_source_current(entry.id))", "(entry.kind='google_calendar' AND NOT public.google_calendar_source_current(entry.id)) OR (entry.kind='microsoft_calendar' AND NOT public.microsoft_calendar_source_current(entry.id))", 1 if name == "MODEL_GUARDS" else 0),
        ):
            if sql.count(before) != count:
                raise RuntimeError("Selected calendar source guard changed")
            sql = sql.replace(before, after)
        op.execute(sql)


def downgrade():
    raise RuntimeError("Retain Outlook observations and explicit human reviews")


TABLES = """
CREATE TABLE microsoft_calendar_observation_requests (
	id UUID NOT NULL,
	account_id UUID NOT NULL,
	ordinal INTEGER NOT NULL,
	idempotency_key VARCHAR(100) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	binding_digest VARCHAR(64) NOT NULL,
	grant_sha256 VARCHAR(64) NOT NULL,
	connected_at TIMESTAMP WITH TIME ZONE NOT NULL,
	window_start TIMESTAMP WITH TIME ZONE NOT NULL,
	window_end TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(account_id, box_id, owner_id) REFERENCES external_identities (id, box_id, principal_id),
	CONSTRAINT uq_microsoft_calendar_observation_scope UNIQUE (id, box_id, owner_id),
	CONSTRAINT uq_microsoft_calendar_observation_ordinal UNIQUE (account_id, ordinal),
	CONSTRAINT uq_microsoft_calendar_observation_key UNIQUE (box_id, owner_id, idempotency_key),
	CONSTRAINT ck_microsoft_calendar_observation_key CHECK (ordinal>=1 AND char_length(idempotency_key) BETWEEN 8 AND 100),
	CONSTRAINT ck_microsoft_calendar_observation_window CHECK (window_end=window_start+interval '168 hours'),
	CHECK (request_hash ~ '^[a-f0-9]{64}$' AND binding_digest ~ '^[a-f0-9]{64}$' AND grant_sha256 ~ '^[a-f0-9]{64}$')
)

;

CREATE TABLE microsoft_calendar_snapshots (
	id UUID NOT NULL,
	observation_id UUID NOT NULL,
	payload JSONB NOT NULL,
	payload_sha256 VARCHAR(64) NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(observation_id, box_id, owner_id) REFERENCES microsoft_calendar_observation_requests (id, box_id, owner_id),
	CONSTRAINT uq_microsoft_calendar_snapshot_observation UNIQUE (observation_id),
	CONSTRAINT uq_microsoft_calendar_snapshot_scope UNIQUE (id, box_id, owner_id),
	CHECK (payload_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$'),
	CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 65536)
)

;

CREATE TABLE microsoft_calendar_source_reviews (
	id UUID NOT NULL,
	entry_id UUID NOT NULL,
	snapshot_id UUID NOT NULL,
	patient_link_id UUID NOT NULL,
	expected_revision INTEGER NOT NULL,
	workspace_revision INTEGER NOT NULL,
	idempotency_key VARCHAR(100) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	observation_sha256 VARCHAR(64) NOT NULL,
	event_id VARCHAR(2048) NOT NULL,
	event_sha256 VARCHAR(64) NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	valid_until TIMESTAMP WITH TIME ZONE NOT NULL,
	reviewed_visit BOOLEAN NOT NULL,
	reviewed_exact_summary BOOLEAN NOT NULL,
	reviewed_untrusted_source BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	workspace_id UUID NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id),
	FOREIGN KEY(entry_id, workspace_id, box_id) REFERENCES workspace_entries (id, workspace_id, box_id),
	FOREIGN KEY(snapshot_id, box_id, owner_id) REFERENCES microsoft_calendar_snapshots (id, box_id, owner_id),
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id),
	CONSTRAINT uq_microsoft_calendar_review_entry UNIQUE (entry_id),
	CONSTRAINT uq_microsoft_calendar_review_event UNIQUE (workspace_id, snapshot_id, event_id),
	CONSTRAINT uq_microsoft_calendar_review_key UNIQUE (workspace_id, idempotency_key),
	CONSTRAINT ck_microsoft_calendar_review_revision CHECK (expected_revision>=1 AND workspace_revision=expected_revision+1),
	CONSTRAINT ck_microsoft_calendar_review_checks CHECK (reviewed_visit AND reviewed_exact_summary AND reviewed_untrusted_source),
	CONSTRAINT ck_microsoft_calendar_review_event CHECK (event_id ~ '^[A-Za-z0-9_+=/-]+$' AND char_length(event_id) BETWEEN 1 AND 2048),
	CHECK (request_hash ~ '^[a-f0-9]{64}$' AND observation_sha256 ~ '^[a-f0-9]{64}$' AND event_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$' AND content_sha256 ~ '^[a-f0-9]{64}$')
)

;"""

GUARDS = r"""
CREATE FUNCTION public.microsoft_calendar_json_digest(value jsonb) RETURNS text
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE raw text:=public.vendor_public_canonical(value); rendered text:=''; point integer; character text;
BEGIN
 FOR n IN 1..char_length(raw) LOOP
  character:=substr(raw,n,1); point:=ascii(character);
  IF point<128 THEN rendered:=rendered||character;
  ELSIF point<=65535 THEN rendered:=rendered||chr(92)||'u'||lpad(to_hex(point),4,'0');
  ELSE
   point:=point-65536;
   rendered:=rendered||chr(92)||'u'||lpad(to_hex(55296+(point/1024)),4,'0')
    ||chr(92)||'u'||lpad(to_hex(56320+(point%1024)),4,'0');
  END IF;
 END LOOP;
 RETURN encode(sha256(convert_to(rendered,'UTF8')),'hex');
END $$;
CREATE FUNCTION public.microsoft_calendar_stamp(value timestamptz) RETURNS text
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT to_char(value AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'
$$;
CREATE FUNCTION public.microsoft_calendar_payload_valid(payload jsonb, begins timestamptz, finishes timestamptz) RETURNS boolean
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE item jsonb; ids text[]:=ARRAY[]::text[]; first_time timestamptz; last_time timestamptz;
BEGIN
 IF NOT public.finance_settings_keys(payload,ARRAY['kind','account','items','more','observed_at','window'])
  OR payload->>'kind' IS DISTINCT FROM 'calendar' OR jsonb_typeof(payload->'more') IS DISTINCT FROM 'boolean'
  OR NOT public.finance_settings_keys(payload->'account',ARRAY['label','email'])
  OR jsonb_typeof(payload->'account'->'label') IS DISTINCT FROM 'string'
  OR char_length(payload->'account'->>'label') NOT BETWEEN 1 AND 256
  OR (payload->'account'->>'label') ~ '[[:cntrl:]]'
  OR jsonb_typeof(payload->'account'->'email') IS DISTINCT FROM 'string'
  OR char_length(payload->'account'->>'email') NOT BETWEEN 1 AND 320
  OR (payload->'account'->>'email') ~ '[[:cntrl:]]'
  OR NOT public.microsoft_message_aware_time(payload->'observed_at')
  OR NOT public.finance_settings_keys(payload->'window',ARRAY['starts_at','ends_at'])
  OR NOT public.microsoft_message_aware_time(payload->'window'->'starts_at')
  OR NOT public.microsoft_message_aware_time(payload->'window'->'ends_at')
 THEN RETURN false; END IF;
 IF (payload->'window'->>'starts_at') !~ '(Z|[+-]00:00)$' OR (payload->'window'->>'ends_at') !~ '(Z|[+-]00:00)$'
  OR (payload->'window'->>'starts_at')::timestamptz<>begins OR (payload->'window'->>'ends_at')::timestamptz<>finishes
  OR finishes<>begins+interval '168 hours'
  OR NOT begins<=(payload->>'observed_at')::timestamptz OR NOT (payload->>'observed_at')::timestamptz<finishes
  OR jsonb_typeof(payload->'items') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(payload->'items')>25 THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(payload->'items') LOOP
  IF NOT public.finance_settings_keys(item,ARRAY['id','subject','starts_at','ends_at','all_day','cancelled'])
   OR jsonb_typeof(item->'id') IS DISTINCT FROM 'string' OR coalesce(item->>'id' ~ '^[A-Za-z0-9_+=/-]+$',false) IS NOT TRUE OR char_length(item->>'id') NOT BETWEEN 1 AND 2048
   OR item->>'id'=ANY(ids) OR jsonb_typeof(item->'subject') IS DISTINCT FROM 'string'
   OR char_length(item->>'subject')>998 OR (item->>'subject') ~ '[[:cntrl:]]'
   OR jsonb_typeof(item->'all_day') IS DISTINCT FROM 'boolean' OR jsonb_typeof(item->'cancelled') IS DISTINCT FROM 'boolean'
  THEN RETURN false; END IF;
  ids:=array_append(ids,item->>'id');
  -- Graph supplies exact instants even when its all-day marker is true.
  IF NOT public.microsoft_message_aware_time(item->'starts_at') OR NOT public.microsoft_message_aware_time(item->'ends_at') THEN RETURN false; END IF;
  first_time:=(item->>'starts_at')::timestamptz; last_time:=(item->>'ends_at')::timestamptz;
  IF last_time<=first_time OR last_time<=begins OR first_time>=finishes THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.microsoft_calendar_observation_current(rid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.microsoft_calendar_observation_requests r
  JOIN public.external_identities a ON a.id=r.account_id AND a.box_id=r.box_id AND a.principal_id=r.owner_id
  JOIN public.principals p ON p.id=r.owner_id AND p.box_id=r.box_id
  JOIN public.microsoft_connection_credentials c ON c.account_id=a.id
  WHERE r.id=rid AND a.active AND p.principal_type='human' AND p.state='active' AND p.tombstoned_at IS NULL
   AND c.status='ready' AND c.sealed IS NOT NULL AND c.expires_at>clock_timestamp()
   AND c.binding_digest=r.binding_digest AND c.connected_at=r.connected_at
   AND NOT EXISTS(SELECT 1 FROM public.microsoft_connection_attempts t WHERE t.account_id=a.id
       AND t.status IN ('pending','exchanging') AND t.expires_at>clock_timestamp()))
$$;
CREATE FUNCTION public.microsoft_calendar_snapshot_valid(sid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.microsoft_calendar_snapshots z JOIN public.microsoft_calendar_observation_requests r ON r.id=z.observation_id
  WHERE z.id=sid AND (z.box_id,z.owner_id)=(r.box_id,r.owner_id)
   AND public.microsoft_calendar_payload_valid(z.payload,r.window_start,r.window_end)
   AND r.request_hash=public.microsoft_calendar_json_digest(jsonb_build_object('action','observe','account_id',r.account_id,'idempotency_key',r.idempotency_key))
   AND z.payload_sha256=public.research_json_digest(z.payload)
   AND z.source_sha256=public.research_json_digest(jsonb_build_object('observation_id',r.id,'account_id',r.account_id,'ordinal',r.ordinal,
    'request_hash',r.request_hash,'binding_digest',r.binding_digest,'connected_at',public.microsoft_calendar_stamp(r.connected_at),
    'grant_sha256',r.grant_sha256,'window_start',public.microsoft_calendar_stamp(r.window_start),'window_end',public.microsoft_calendar_stamp(r.window_end),
    'payload_sha256',z.payload_sha256)))
$$;
CREATE FUNCTION public.microsoft_calendar_source_content(payload jsonb, item jsonb) RETURNS text
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT 'Outlook calendar summary (frozen observation)'||chr(10)
  ||'Account: '||(payload->'account'->>'label')||' <'||(payload->'account'->>'email')||'>'||chr(10)
  ||'Event: '||(item->>'subject')||chr(10)||'Starts: '||(item->>'starts_at')||chr(10)||'Ends (exclusive): '||(item->>'ends_at')||chr(10)
  ||'All day: '||(CASE WHEN item->>'all_day'='true' THEN 'yes' ELSE 'no' END)||chr(10)
  ||'Status: '||(CASE WHEN item->>'cancelled'='true' THEN 'cancelled' ELSE 'not marked cancelled' END)||chr(10)
  ||'Observed: '||(payload->>'observed_at')||chr(10)||'Window: '||(payload->'window'->>'starts_at')||' to '||(payload->'window'->>'ends_at')||chr(10)
  ||'Coverage: '||(CASE WHEN payload->>'more'='true' THEN 'partial (more events available)' ELSE 'up to 25 events in the primary calendar' END)
  ||chr(10)||chr(10)||'This observed summary does not establish current availability or a booking.'
$$;
CREATE FUNCTION public.microsoft_calendar_valid_until(payload jsonb, item jsonb) RETURNS timestamptz
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE ending timestamptz;
BEGIN
 ending:=(item->>'ends_at')::timestamptz;
 RETURN least(ending,(payload->'window'->>'ends_at')::timestamptz);
EXCEPTION WHEN OTHERS THEN RETURN NULL;
END $$;
CREATE FUNCTION public.microsoft_calendar_source_valid(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.microsoft_calendar_source_reviews v
  JOIN public.workspace_entries e ON e.id=v.entry_id JOIN public.encounter_workspaces w ON w.id=v.workspace_id
  JOIN public.microsoft_calendar_snapshots z ON z.id=v.snapshot_id JOIN public.microsoft_calendar_observation_requests r ON r.id=z.observation_id
  CROSS JOIN LATERAL jsonb_array_elements(z.payload->'items') item
  WHERE e.id=eid AND e.kind='microsoft_calendar' AND item->>'id'=v.event_id
   AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)
    =(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
   AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
   AND (r.box_id,r.owner_id)=(v.box_id,v.owner_id) AND (z.box_id,z.owner_id)=(v.box_id,v.owner_id)
   AND public.microsoft_calendar_snapshot_valid(z.id) AND v.workspace_revision=v.expected_revision+1
   AND v.reviewed_visit AND v.reviewed_exact_summary AND v.reviewed_untrusted_source
   AND v.observation_sha256=z.source_sha256 AND v.event_sha256=public.microsoft_calendar_json_digest(item)
   AND v.source_sha256=public.microsoft_calendar_json_digest(jsonb_build_object('observation_sha256',v.observation_sha256,'event_id',v.event_id,'event_sha256',v.event_sha256))
   AND v.request_hash=public.microsoft_calendar_json_digest(jsonb_build_object('workspace_id',v.workspace_id,'expected_revision',v.expected_revision,
     'idempotency_key',v.idempotency_key,'observation_id',r.id,'observation_sha256',v.observation_sha256,'event_id',v.event_id,
     'event_sha256',v.event_sha256,'reviewed_visit',v.reviewed_visit,'reviewed_exact_summary',v.reviewed_exact_summary,'reviewed_untrusted_source',v.reviewed_untrusted_source))
   AND e.content=public.microsoft_calendar_source_content(z.payload,item)
   AND e.source_label=left('Outlook calendar: '||(item->>'subject'),160)
   AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex')
   AND v.valid_until=public.microsoft_calendar_valid_until(z.payload,item))
$$;
CREATE FUNCTION public.microsoft_calendar_source_current(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.microsoft_calendar_source_valid(eid) AND EXISTS(SELECT 1 FROM public.microsoft_calendar_source_reviews v
  JOIN public.microsoft_calendar_snapshots z ON z.id=v.snapshot_id JOIN public.microsoft_calendar_observation_requests r ON r.id=z.observation_id
  WHERE v.entry_id=eid AND public.microsoft_calendar_observation_current(r.id) AND v.valid_until>clock_timestamp()
   AND r.window_end>clock_timestamp() AND NOT EXISTS(SELECT 1 FROM public.microsoft_calendar_observation_requests n
    WHERE n.account_id=r.account_id AND n.ordinal>r.ordinal))
$$;
CREATE FUNCTION public.guard_microsoft_calendar_observation() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Calendar observation requests are immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id AND principal_type='human' AND state='active' AND tombstoned_at IS NULL)
  OR NOT EXISTS(SELECT 1 FROM public.external_identities a JOIN public.microsoft_connection_credentials c ON c.account_id=a.id
   WHERE a.id=NEW.account_id AND a.box_id=NEW.box_id AND a.principal_id=NEW.owner_id AND a.active
    AND c.status='ready' AND c.sealed IS NOT NULL AND c.expires_at>clock_timestamp() AND c.binding_digest=NEW.binding_digest AND c.connected_at=NEW.connected_at)
  OR NEW.ordinal IS DISTINCT FROM (SELECT coalesce(max(ordinal),0)+1 FROM public.microsoft_calendar_observation_requests WHERE account_id=NEW.account_id)
  OR NEW.ordinal>500 OR NEW.idempotency_key !~ '^[A-Za-z0-9:_-]{8,100}$'
  OR NOT isfinite(NEW.window_start) OR NOT isfinite(NEW.window_end) OR NEW.window_end<>NEW.window_start+interval '168 hours'
  OR NEW.window_start>clock_timestamp() OR NEW.window_start<clock_timestamp()-interval '1 minute'
  OR NEW.request_hash IS DISTINCT FROM public.microsoft_calendar_json_digest(jsonb_build_object('action','observe','account_id',NEW.account_id,'idempotency_key',NEW.idempotency_key))
 THEN RAISE EXCEPTION 'Calendar observation binding invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER microsoft_calendar_observation_guard BEFORE INSERT OR UPDATE OR DELETE ON public.microsoft_calendar_observation_requests
 FOR EACH ROW EXECUTE FUNCTION public.guard_microsoft_calendar_observation();
CREATE FUNCTION public.guard_microsoft_calendar_snapshot() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r public.microsoft_calendar_observation_requests;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Calendar snapshots are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM public.microsoft_calendar_observation_requests WHERE id=NEW.observation_id;
 IF r.id IS NULL OR (r.box_id,r.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
 THEN RAISE EXCEPTION 'Calendar snapshot scope invalid' USING ERRCODE='23514'; END IF;
 IF NOT public.microsoft_calendar_observation_current(r.id)
 THEN RAISE EXCEPTION 'Calendar snapshot authority invalid' USING ERRCODE='23514'; END IF;
 IF NOT public.microsoft_calendar_payload_valid(NEW.payload,r.window_start,r.window_end)
 THEN RAISE EXCEPTION 'Calendar snapshot payload invalid' USING ERRCODE='23514'; END IF;
 IF NEW.payload_sha256 IS DISTINCT FROM public.research_json_digest(NEW.payload)
 THEN RAISE EXCEPTION 'Calendar snapshot payload commitment invalid' USING ERRCODE='23514'; END IF;
 IF NEW.source_sha256 IS DISTINCT FROM public.research_json_digest(jsonb_build_object('observation_id',r.id,'account_id',r.account_id,'ordinal',r.ordinal,
    'request_hash',r.request_hash,'binding_digest',r.binding_digest,'connected_at',public.microsoft_calendar_stamp(r.connected_at),
    'grant_sha256',r.grant_sha256,'window_start',public.microsoft_calendar_stamp(r.window_start),'window_end',public.microsoft_calendar_stamp(r.window_end),'payload_sha256',NEW.payload_sha256))
 THEN RAISE EXCEPTION 'Calendar snapshot custody commitment invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER microsoft_calendar_snapshot_guard BEFORE INSERT OR UPDATE OR DELETE ON public.microsoft_calendar_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.guard_microsoft_calendar_snapshot();
CREATE FUNCTION public.guard_microsoft_calendar_review() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE w public.encounter_workspaces; z public.microsoft_calendar_snapshots; r public.microsoft_calendar_observation_requests;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Calendar reviews are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 SELECT * INTO z FROM public.microsoft_calendar_snapshots WHERE id=NEW.snapshot_id;
 SELECT * INTO r FROM public.microsoft_calendar_observation_requests WHERE id=z.observation_id;
 IF w.id IS NULL OR (w.box_id,w.owner_id,w.patient_link_id,w.revision) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.patient_link_id,NEW.workspace_revision)
  OR w.appointment_id IS NULL
  OR z.id IS NULL OR r.id IS NULL OR NOT public.microsoft_calendar_observation_current(r.id) OR NEW.valid_until<=clock_timestamp()
  OR EXISTS(SELECT 1 FROM public.microsoft_calendar_observation_requests n WHERE n.account_id=r.account_id AND n.ordinal>r.ordinal)
 THEN RAISE EXCEPTION 'Calendar review authority invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER microsoft_calendar_review_guard BEFORE INSERT OR UPDATE OR DELETE ON public.microsoft_calendar_source_reviews
 FOR EACH ROW EXECUTE FUNCTION public.guard_microsoft_calendar_review();
CREATE FUNCTION public.guard_microsoft_calendar_entry() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_TABLE_NAME='workspace_entries' THEN
  IF NEW.kind='microsoft_calendar' AND NOT public.microsoft_calendar_source_valid(NEW.id)
   THEN RAISE EXCEPTION 'Calendar exact source review required' USING ERRCODE='23514'; END IF;
 ELSE
  IF NOT public.microsoft_calendar_source_valid(NEW.entry_id)
   THEN RAISE EXCEPTION 'Calendar review commitment invalid' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER microsoft_calendar_entry_guard AFTER INSERT ON public.workspace_entries
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_microsoft_calendar_entry();
CREATE CONSTRAINT TRIGGER microsoft_calendar_review_commitment_guard AFTER INSERT ON public.microsoft_calendar_source_reviews
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_microsoft_calendar_entry();

ALTER FUNCTION public.guard_microsoft_calendar_observation() SECURITY DEFINER SET search_path=pg_catalog;
REVOKE ALL ON FUNCTION public.guard_microsoft_calendar_observation() FROM PUBLIC;
ALTER FUNCTION public.guard_microsoft_calendar_snapshot() SECURITY DEFINER SET search_path=pg_catalog;
REVOKE ALL ON FUNCTION public.guard_microsoft_calendar_snapshot() FROM PUBLIC;
ALTER FUNCTION public.guard_microsoft_calendar_review() SECURITY DEFINER SET search_path=pg_catalog;
REVOKE ALL ON FUNCTION public.guard_microsoft_calendar_review() FROM PUBLIC;
ALTER FUNCTION public.guard_microsoft_calendar_entry() SECURITY DEFINER SET search_path=pg_catalog;
REVOKE ALL ON FUNCTION public.guard_microsoft_calendar_entry() FROM PUBLIC;"""
