"""Immutable privately imported calendar summaries and exact source custody."""

from pathlib import Path
from runpy import run_path

from alembic import op

revision = "p35b1d4f9876"
down_revision = "o24a0c3e8765"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)
    op.drop_constraint("ck_workspace_entry_kind", "workspace_entries", type_="check")
    op.create_check_constraint("ck_workspace_entry_kind", "workspace_entries", "kind IN ('synthetic_source','scratchpad','conversation','evidence','work_link','handoff_result','google_message','google_calendar','efax_inbound_source','fax_inbound_source','ehr_read_source','calendar_import_source')")
    op.execute(CODEPOINT_GUARD.format(ranges=UNICODE_C_RANGES))
    op.execute(GUARDS)
    versions = Path(__file__).parent
    fax = run_path(str(versions / "h68e0c4f1239_fax_reviewed_source.py"))
    note = run_path(str(versions / "j79f1d5a2340_human_shared_note_custody.py"))
    directions = run_path(str(versions / "k80e6a9d4321_saved_note_drafting_directions.py"))
    ehr = run_path(str(versions / "m02e8a1c6543_ehr_read_custody.py"))
    for name, previous, ehr_extensions, extensions in (
        ("HANDOFF_GUARDS", note["REVIEW_EXTENSIONS"], ehr["REVIEW_EXTENSIONS"], REVIEW_EXTENSIONS),
        ("MODEL_GUARDS", (*note["MODEL_EXTENSIONS"], *directions["DIRECTIONS_EXTENSIONS"]), ehr["MODEL_EXTENSIONS"], MODEL_EXTENSIONS),
    ):
        sql = fax[name]
        for before, after in previous:
            if sql.count(before) != 1:
                raise RuntimeError("Previous selected-source guard changed")
            sql = sql.replace(before, after)
        for before, after, count in (*ehr_extensions, *extensions):
            if sql.count(before) != count:
                raise RuntimeError("Calendar import selected-source extension differs")
            sql = sql.replace(before, after)
        op.execute(sql)


def downgrade():
    raise RuntimeError("Retain imported calendar snapshot and revocation custody")


REVIEW_EXTENSIONS = (
    ("'fax_inbound_source','ehr_read_source','conversation') THEN 'evidence'",
     "'fax_inbound_source','ehr_read_source','calendar_import_source','conversation') THEN 'evidence'", 2),
    ("(kind='ehr_read_source' AND public.ehr_read_source_current(e.id)))",
     "(kind='ehr_read_source' AND public.ehr_read_source_current(e.id)) OR (kind='calendar_import_source' AND public.calendar_import_source_current(e.id)))", 1),
    ("OR (source_entry.kind='ehr_read_source' AND NOT public.ehr_read_source_current(source_entry.id))",
     "OR (source_entry.kind='ehr_read_source' AND NOT public.ehr_read_source_current(source_entry.id)) OR (source_entry.kind='calendar_import_source' AND NOT public.calendar_import_source_current(source_entry.id))", 1),
)
MODEL_EXTENSIONS = (
    ("'google_message','google_calendar','efax_inbound_source','fax_inbound_source','ehr_read_source')",
     "'google_message','google_calendar','efax_inbound_source','fax_inbound_source','ehr_read_source','calendar_import_source')", 1),
    ("OR (entry.kind='ehr_read_source' AND NOT public.ehr_read_source_current(entry.id))",
     "OR (entry.kind='ehr_read_source' AND NOT public.ehr_read_source_current(entry.id)) OR (entry.kind='calendar_import_source' AND NOT public.calendar_import_source_current(entry.id))", 1),
    ("entry.kind IN ('efax_inbound_source','fax_inbound_source','ehr_read_source')",
     "entry.kind IN ('efax_inbound_source','fax_inbound_source','ehr_read_source','calendar_import_source')", 1),
)

TABLES = r"""

CREATE TABLE calendar_import_requests (
	id UUID NOT NULL, 
	account_id UUID NOT NULL, 
	patient_link_id UUID NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	byte_sha256 VARCHAR(64) NOT NULL, 
	reported_source VARCHAR(20) NOT NULL, 
	window_start DATE NOT NULL, 
	window_end DATE NOT NULL, 
	timezone VARCHAR(128) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	FOREIGN KEY(account_id, box_id, owner_id) REFERENCES external_identities (id, box_id, principal_id), 
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), 
	CONSTRAINT uq_calendar_import_scope UNIQUE (id, workspace_id, box_id, owner_id), 
	CONSTRAINT uq_calendar_import_key UNIQUE (workspace_id, idempotency_key), 
	CONSTRAINT ck_calendar_import_key CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), 
	CONSTRAINT ck_calendar_import_reported CHECK (reported_source IN ('atlas_md','other_calendar')), 
	CONSTRAINT ck_calendar_import_window CHECK (window_end=window_start+7 AND window_start>=date '1900-01-01' AND window_end<date '2101-01-01'), 
	CONSTRAINT ck_calendar_import_timezone CHECK (char_length(timezone) BETWEEN 1 AND 128), 
	CHECK (request_hash ~ '^[a-f0-9]{64}$' AND byte_sha256 ~ '^[a-f0-9]{64}$')
)

;

CREATE TABLE calendar_import_snapshots (
	id UUID NOT NULL, 
	import_id UUID NOT NULL, 
	payload JSONB NOT NULL, 
	payload_sha256 VARCHAR(64) NOT NULL, 
	source_sha256 VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	FOREIGN KEY(import_id, workspace_id, box_id, owner_id) REFERENCES calendar_import_requests (id, workspace_id, box_id, owner_id), 
	CONSTRAINT uq_calendar_snapshot_scope UNIQUE (id, workspace_id, box_id, owner_id), 
	CONSTRAINT uq_calendar_snapshot_import UNIQUE (import_id), 
	CHECK (payload_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$'), 
	CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 65536)
)

;

CREATE TABLE calendar_import_source_reviews (
	id UUID NOT NULL, 
	entry_id UUID NOT NULL, 
	snapshot_id UUID NOT NULL, 
	patient_link_id UUID NOT NULL, 
	expected_revision INTEGER NOT NULL, 
	workspace_revision INTEGER NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	import_sha256 VARCHAR(64) NOT NULL, 
	item_index INTEGER NOT NULL, 
	item_sha256 VARCHAR(64) NOT NULL, 
	source_sha256 VARCHAR(64) NOT NULL, 
	content_sha256 VARCHAR(64) NOT NULL, 
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
	FOREIGN KEY(snapshot_id, workspace_id, box_id, owner_id) REFERENCES calendar_import_snapshots (id, workspace_id, box_id, owner_id), 
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), 
	CONSTRAINT uq_calendar_source_entry UNIQUE (entry_id), 
	CONSTRAINT uq_calendar_source_key UNIQUE (workspace_id, idempotency_key), 
	CONSTRAINT uq_calendar_source_item UNIQUE (workspace_id, snapshot_id, item_index), 
	CONSTRAINT ck_calendar_source_revision CHECK (expected_revision>=1 AND workspace_revision=expected_revision+1), 
	CONSTRAINT ck_calendar_source_key CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$' AND item_index BETWEEN 0 AND 499), 
	CONSTRAINT ck_calendar_source_review CHECK (reviewed_visit AND reviewed_exact_summary AND reviewed_untrusted_source), 
	CHECK (request_hash ~ '^[a-f0-9]{64}$' AND import_sha256 ~ '^[a-f0-9]{64}$' AND item_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$' AND content_sha256 ~ '^[a-f0-9]{64}$')
)

;

CREATE TABLE calendar_import_revocations (
	id UUID NOT NULL, 
	import_id UUID NOT NULL, 
	expected_revision INTEGER NOT NULL, 
	idempotency_key VARCHAR(100) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	import_sha256 VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	workspace_id UUID NOT NULL, 
	box_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), 
	FOREIGN KEY(import_id, workspace_id, box_id, owner_id) REFERENCES calendar_import_requests (id, workspace_id, box_id, owner_id), 
	CONSTRAINT uq_calendar_revoke_import UNIQUE (import_id), 
	CONSTRAINT uq_calendar_revoke_key UNIQUE (workspace_id, idempotency_key), 
	CONSTRAINT ck_calendar_revoke_revision CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$' AND expected_revision>=1), 
	CHECK (request_hash ~ '^[a-f0-9]{64}$' AND import_sha256 ~ '^[a-f0-9]{64}$')
)

;
"""

GUARDS = r"""
CREATE FUNCTION public.calendar_import_scope_current(wid uuid, bid uuid, oid uuid, aid uuid, pid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.encounter_workspaces w
 JOIN public.principals h ON (h.id,h.box_id)=(w.owner_id,w.box_id)
 JOIN public.external_identities x ON (x.id,x.box_id,x.principal_id)=(aid,w.box_id,w.owner_id)
 JOIN public.appointment_observations a ON (a.id,a.box_id,a.patient_link_id)=(w.appointment_id,w.box_id,w.patient_link_id)
 JOIN public.patient_links p ON (p.id,p.box_id)=(w.patient_link_id,w.box_id)
 WHERE (w.id,w.box_id,w.owner_id,w.patient_link_id)=(wid,bid,oid,pid)
 AND h.principal_type='human' AND h.state='active' AND h.tombstoned_at IS NULL AND x.active
 AND p.state='confirmed' AND p.revoked_at IS NULL
 AND (p.source_owner_id IS NULL OR (p.source_owner_id=oid AND EXISTS(SELECT 1 FROM public.core_capture_accounts ca
 JOIN public.external_identities e ON e.id=ca.external_identity_id WHERE ca.id=p.source_account_id
 AND ca.revoked_at IS NULL AND e.active AND e.box_id=bid AND e.principal_id=oid))))
$$;
CREATE FUNCTION public.calendar_import_lock_scope(wid uuid, bid uuid, oid uuid, aid uuid, pid uuid) RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 PERFORM 1 FROM public.principals WHERE (id,box_id)=(oid,bid) FOR UPDATE;
 PERFORM 1 FROM public.external_identities WHERE id=aid FOR SHARE;
 PERFORM 1 FROM public.encounter_workspaces WHERE id=wid FOR UPDATE;
 PERFORM 1 FROM public.patient_links WHERE id=pid FOR SHARE;
 PERFORM 1 FROM public.core_capture_accounts WHERE id=(SELECT source_account_id FROM public.patient_links WHERE id=pid) FOR SHARE;
 PERFORM 1 FROM public.external_identities WHERE id=(SELECT ca.external_identity_id FROM public.core_capture_accounts ca
  JOIN public.patient_links p ON p.source_account_id=ca.id WHERE p.id=pid) FOR SHARE;
END $$;
CREATE FUNCTION public.calendar_import_request_hash(r public.calendar_import_requests) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT public.google_calendar_json_digest(jsonb_build_object('kind','calendar-import-v1','action','upload',
 'workspace_id',r.workspace_id,'idempotency_key',r.idempotency_key,'byte_sha256',r.byte_sha256,'reported_source',r.reported_source,
 'window',jsonb_build_object('starts_on',r.window_start,'ends_on',r.window_end,'timezone',r.timezone)))
$$;
CREATE FUNCTION public.calendar_import_request_current(rid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.calendar_import_requests r WHERE r.id=rid
 AND r.request_hash=public.calendar_import_request_hash(r)
 AND public.calendar_import_scope_current(r.workspace_id,r.box_id,r.owner_id,r.account_id,r.patient_link_id)
 AND NOT EXISTS(SELECT 1 FROM public.calendar_import_revocations v WHERE v.import_id=r.id))
$$;
CREATE FUNCTION public.calendar_import_key_free(wid uuid, key text, kind text) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT NOT EXISTS(SELECT 1 FROM public.calendar_import_requests WHERE workspace_id=wid AND idempotency_key=key AND kind<>'upload')
 AND NOT EXISTS(SELECT 1 FROM public.calendar_import_source_reviews WHERE workspace_id=wid AND idempotency_key=key AND kind<>'review')
 AND NOT EXISTS(SELECT 1 FROM public.calendar_import_revocations WHERE workspace_id=wid AND idempotency_key=key AND kind<>'revoke')
 AND (kind='review' OR NOT EXISTS(SELECT 1 FROM public.workspace_entries WHERE workspace_id=wid AND idempotency_key=key))
$$;
CREATE FUNCTION public.guard_calendar_import_request() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 PERFORM public.calendar_import_lock_scope(NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.account_id,NEW.patient_link_id);
 IF NOT public.calendar_import_scope_current(NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.account_id,NEW.patient_link_id)
 OR NEW.request_hash IS DISTINCT FROM public.calendar_import_request_hash(NEW)
 OR NOT public.calendar_import_key_free(NEW.workspace_id,NEW.idempotency_key,'upload')
 OR NOT isfinite(NEW.created_at) OR date_trunc('second',NEW.created_at) IS DISTINCT FROM NEW.created_at
 OR NEW.created_at>clock_timestamp() OR NEW.created_at<clock_timestamp()-interval '1 minute'
 OR NEW.timezone !~ '^[A-Za-z0-9_+.-]+(/[A-Za-z0-9_+.-]+)*$'
 OR NOT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=NEW.timezone)
 OR ((NEW.window_start::timestamp AT TIME ZONE NEW.timezone) AT TIME ZONE NEW.timezone) IS DISTINCT FROM NEW.window_start::timestamp
 OR ((NEW.window_end::timestamp AT TIME ZONE NEW.timezone) AT TIME ZONE NEW.timezone) IS DISTINCT FROM NEW.window_end::timestamp
 OR (SELECT count(*) FROM public.calendar_import_requests WHERE workspace_id=NEW.workspace_id)>=100
 OR (SELECT count(*) FROM public.calendar_import_requests WHERE box_id=NEW.box_id AND owner_id=NEW.owner_id)>=500
 THEN RAISE EXCEPTION 'Calendar import authority or request invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER calendar_import_request_guard BEFORE INSERT ON public.calendar_import_requests
 FOR EACH ROW EXECUTE FUNCTION public.guard_calendar_import_request();
CREATE FUNCTION public.calendar_import_integer(value jsonb, maximum integer) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
BEGIN
 RETURN coalesce(jsonb_typeof(value)='number' AND value::text ~ '^(0|[1-9][0-9]*)$' AND value::text::numeric<=maximum,false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.calendar_import_title_valid(value jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE title text; normalized text;
BEGIN
 IF jsonb_typeof(value) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
 title:=value#>>'{}'; normalized:=normalize(title,NFKC);
 RETURN char_length(title)<=300 AND public.calendar_import_codepoints_valid(title) AND public.calendar_import_codepoints_valid(normalized)
 AND normalized !~* '%[0-9a-f]{2}|&[^[:space:];]+;'
 AND normalized !~* '([a-z][a-z0-9+.-]*:[^[:space:]]|[a-z][a-z0-9+.-]*[[:space:]]*:[[:space:]]*//|//|\\\\|(^|[^a-z0-9_])www\.)';
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.calendar_import_utc_seconds(value jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE v text;
BEGIN
 IF jsonb_typeof(value) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
 v:=value#>>'{}';
 RETURN v ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
 AND to_char(v::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"')=v
 AND extract(year FROM v::timestamptz AT TIME ZONE 'UTC') BETWEEN 1900 AND 2100;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.calendar_import_payload_valid(payload jsonb,r public.calendar_import_requests) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE item jsonb; seen integer[]:=ARRAY[]::integer[]; idx integer; total integer; matching integer;
 begins timestamptz; ends timestamptz; last_begins timestamptz; last_index integer;
BEGIN
 IF NOT public.finance_settings_keys(payload,ARRAY['imported_at','reported_source','window','items','total_events','matching_events','more','coverage'])
 OR payload->>'imported_at' IS DISTINCT FROM to_char(r.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"')
 OR payload->>'reported_source' IS DISTINCT FROM r.reported_source
 OR payload->'window' IS DISTINCT FROM jsonb_build_object('starts_on',r.window_start,'ends_on',r.window_end,'timezone',r.timezone)
 OR payload->>'coverage' IS DISTINCT FROM 'file_window_only'
 OR jsonb_typeof(payload->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(payload->'items')>25
 OR NOT public.calendar_import_integer(payload->'total_events',500) OR NOT public.calendar_import_integer(payload->'matching_events',500)
 OR jsonb_typeof(payload->'more') IS DISTINCT FROM 'boolean'
 THEN RETURN false; END IF;
 total:=(payload->>'total_events')::integer; matching:=(payload->>'matching_events')::integer;
 IF matching>total OR jsonb_array_length(payload->'items')<>least(matching,25)
 OR (payload->>'more')::boolean IS DISTINCT FROM (matching>25) THEN RETURN false; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(payload->'items') LOOP
  IF NOT public.finance_settings_keys(item,ARRAY['item_index','title','title_truncated','starts_at','ends_at','all_day','cancelled'])
  OR NOT public.calendar_import_integer(item->'item_index',499) OR NOT public.calendar_import_title_valid(item->'title')
  OR jsonb_typeof(item->'title_truncated') IS DISTINCT FROM 'boolean' OR jsonb_typeof(item->'all_day') IS DISTINCT FROM 'boolean'
  OR jsonb_typeof(item->'cancelled') IS DISTINCT FROM 'boolean'
  OR (item->>'title_truncated')::boolean AND char_length(item->>'title')<>300 THEN RETURN false; END IF;
  idx:=(item->>'item_index')::integer;
  IF idx>=total OR idx=ANY(seen) THEN RETURN false; END IF;
  seen:=array_append(seen,idx);
  IF (item->>'all_day')::boolean THEN
   IF NOT public.google_calendar_date(item->'starts_at') OR NOT public.google_calendar_date(item->'ends_at')
    OR (item->>'starts_at')::date>=r.window_end OR (item->>'ends_at')::date<=r.window_start
    OR (item->>'starts_at')::date<(date '1900-01-01') OR (item->>'ends_at')::date>=date '2101-01-01'
    OR (item->>'ends_at')::date<=(item->>'starts_at')::date THEN RETURN false; END IF;
   begins:=(item->>'starts_at')::date::timestamp AT TIME ZONE r.timezone;
   ends:=(item->>'ends_at')::date::timestamp AT TIME ZONE r.timezone;
  ELSE
   IF NOT public.calendar_import_utc_seconds(item->'starts_at') OR NOT public.calendar_import_utc_seconds(item->'ends_at') THEN RETURN false; END IF;
   begins:=(item->>'starts_at')::timestamptz; ends:=(item->>'ends_at')::timestamptz;
   IF begins>=r.window_end::timestamp AT TIME ZONE r.timezone OR ends<=r.window_start::timestamp AT TIME ZONE r.timezone THEN RETURN false; END IF;
  END IF;
  IF ends<=begins OR (last_begins IS NOT NULL AND (begins<last_begins OR (begins=last_begins AND idx<=last_index))) THEN RETURN false; END IF;
  last_begins:=begins; last_index:=idx;
 END LOOP;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.calendar_import_snapshot_hash(r public.calendar_import_requests, digest text) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT public.google_calendar_json_digest(jsonb_build_object('kind','calendar-import-snapshot-v1','import_id',r.id,
 'box_id',r.box_id,'owner_id',r.owner_id,'account_id',r.account_id,'workspace_id',r.workspace_id,'patient_link_id',r.patient_link_id,
 'request_sha256',r.request_hash,'payload_sha256',digest))
$$;
CREATE FUNCTION public.calendar_import_snapshot_valid(sid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.calendar_import_snapshots s JOIN public.calendar_import_requests r ON r.id=s.import_id
 WHERE s.id=sid AND (s.workspace_id,s.box_id,s.owner_id)=(r.workspace_id,r.box_id,r.owner_id)
 AND r.request_hash=public.calendar_import_request_hash(r) AND public.calendar_import_payload_valid(s.payload,r)
 AND s.payload_sha256=public.google_calendar_json_digest(s.payload)
 AND s.source_sha256=public.calendar_import_snapshot_hash(r,s.payload_sha256))
$$;
CREATE FUNCTION public.guard_calendar_import_snapshot() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r public.calendar_import_requests;
BEGIN
 SELECT * INTO r FROM public.calendar_import_requests WHERE id=NEW.import_id;
 PERFORM public.calendar_import_lock_scope(r.workspace_id,r.box_id,r.owner_id,r.account_id,r.patient_link_id);
 IF r.id IS NULL OR (NEW.workspace_id,NEW.box_id,NEW.owner_id) IS DISTINCT FROM (r.workspace_id,r.box_id,r.owner_id)
 OR NOT public.calendar_import_request_current(r.id) OR NOT public.calendar_import_payload_valid(NEW.payload,r)
 OR NEW.payload_sha256 IS DISTINCT FROM public.google_calendar_json_digest(NEW.payload)
 OR NEW.source_sha256 IS DISTINCT FROM public.calendar_import_snapshot_hash(r,NEW.payload_sha256)
 THEN RAISE EXCEPTION 'Calendar import snapshot custody or payload invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER calendar_import_snapshot_guard BEFORE INSERT ON public.calendar_import_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.guard_calendar_import_snapshot();
CREATE FUNCTION public.calendar_import_source_content(payload jsonb, selected_index integer) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT 'Imported calendar snapshot'||chr(10)||'Source reported by user: '||CASE WHEN payload->>'reported_source'='atlas_md' THEN 'Atlas.md' ELSE 'Other calendar' END||chr(10)
 ||'Imported at: '||(payload->>'imported_at')||chr(10)||'Title: '||CASE WHEN item->>'title'='' THEN '(Untitled event)' ELSE item->>'title' END||chr(10)
 ||'Title truncated: '||CASE WHEN (item->>'title_truncated')::boolean THEN 'yes' ELSE 'no' END||chr(10)
 ||'Starts: '||(item->>'starts_at')||chr(10)||'Ends (exclusive): '||(item->>'ends_at')||chr(10)
 ||'All day: '||CASE WHEN (item->>'all_day')::boolean THEN 'yes' ELSE 'no' END||chr(10)
 ||'Status: '||CASE WHEN (item->>'cancelled')::boolean THEN 'Cancelled' ELSE 'Not marked cancelled' END||chr(10)
 ||'Window: '||(payload->'window'->>'starts_on')||' through '||(payload->'window'->>'ends_on')||' (end date excluded); timezone '||(payload->'window'->>'timezone')||chr(10)
 ||'Coverage: Showing '||jsonb_array_length(payload->'items')::text||' of '||(payload->>'matching_events')||' matching events in the supplied file. Other appointments may be missing.'||chr(10)
 ||'This staff-supplied calendar summary does not verify patient or chart identity, current availability, or a booking.'
 FROM jsonb_array_elements(payload->'items') item WHERE (item->>'item_index')::integer=selected_index
$$;
CREATE FUNCTION public.calendar_import_source_valid(eid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.calendar_import_source_reviews v JOIN public.workspace_entries e ON e.id=v.entry_id
 JOIN public.calendar_import_snapshots s ON s.id=v.snapshot_id JOIN public.calendar_import_requests r ON r.id=s.import_id
 JOIN public.encounter_workspaces w ON w.id=v.workspace_id,
 jsonb_array_elements(s.payload->'items') item
 WHERE e.id=eid AND e.kind='calendar_import_source'
 AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)=(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
 AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
 AND (r.workspace_id,r.box_id,r.owner_id,r.patient_link_id)=(v.workspace_id,v.box_id,v.owner_id,v.patient_link_id)
 AND public.calendar_import_snapshot_valid(s.id) AND v.import_sha256=s.source_sha256
 AND v.expected_revision+1=v.workspace_revision AND v.reviewed_visit AND v.reviewed_exact_summary AND v.reviewed_untrusted_source
 AND (item->>'item_index')::integer=v.item_index AND item->'cancelled'='false'::jsonb
 AND v.item_sha256=public.google_calendar_json_digest(jsonb_build_object('kind','calendar-import-item-v1','item',item))
 AND v.source_sha256=public.google_calendar_json_digest(jsonb_build_object('kind','calendar-import-selected-v1','import_sha256',v.import_sha256,'item_index',v.item_index,'item_sha256',v.item_sha256))
 AND v.request_hash=public.google_calendar_json_digest(jsonb_build_object('action','review','workspace_id',v.workspace_id,'expected_revision',v.expected_revision,
 'idempotency_key',v.idempotency_key,'import_id',r.id,'source_sha256',v.import_sha256,'item_index',v.item_index,'item_sha256',v.item_sha256,
 'reviewed_visit',v.reviewed_visit,'reviewed_exact_summary',v.reviewed_exact_summary,'reviewed_untrusted_source',v.reviewed_untrusted_source))
 AND e.content=public.calendar_import_source_content(s.payload,v.item_index) AND e.source_label='Imported calendar snapshot'
 AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex'))
$$;
CREATE FUNCTION public.calendar_import_source_current(eid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.calendar_import_source_valid(eid) AND EXISTS(SELECT 1 FROM public.calendar_import_source_reviews v
 JOIN public.calendar_import_snapshots s ON s.id=v.snapshot_id WHERE v.entry_id=eid AND public.calendar_import_request_current(s.import_id))
$$;
CREATE FUNCTION public.guard_calendar_import_review() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r public.calendar_import_requests; s public.calendar_import_snapshots; w public.encounter_workspaces;
BEGIN
 SELECT * INTO s FROM public.calendar_import_snapshots WHERE id=NEW.snapshot_id;
 SELECT * INTO r FROM public.calendar_import_requests WHERE id=s.import_id;
 PERFORM public.calendar_import_lock_scope(r.workspace_id,r.box_id,r.owner_id,r.account_id,r.patient_link_id);
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=r.workspace_id;
 IF r.id IS NULL OR s.id IS NULL OR w.id IS NULL
 OR (NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.patient_link_id,NEW.workspace_revision) IS DISTINCT FROM (r.workspace_id,r.box_id,r.owner_id,r.patient_link_id,w.revision)
 OR NOT public.calendar_import_key_free(NEW.workspace_id,NEW.idempotency_key,'review')
 OR NOT public.calendar_import_request_current(r.id) OR NOT public.calendar_import_snapshot_valid(s.id)
 THEN RAISE EXCEPTION 'Calendar import review custody invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER calendar_import_review_guard BEFORE INSERT ON public.calendar_import_source_reviews
 FOR EACH ROW EXECUTE FUNCTION public.guard_calendar_import_review();
CREATE FUNCTION public.guard_calendar_import_entry() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_TABLE_NAME='workspace_entries' THEN
  -- Share the import/revoke workspace lock without upgrading the owner's lock.
  -- This also serializes ordinary direct-SQL entry inserts with reservations.
  PERFORM 1 FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR NO KEY UPDATE;
  IF EXISTS(SELECT 1 FROM public.calendar_import_requests WHERE workspace_id=NEW.workspace_id AND idempotency_key=NEW.idempotency_key)
   OR EXISTS(SELECT 1 FROM public.calendar_import_revocations WHERE workspace_id=NEW.workspace_id AND idempotency_key=NEW.idempotency_key)
   THEN RAISE EXCEPTION 'Calendar import key already reserved' USING ERRCODE='23514'; END IF;
  IF NEW.kind='calendar_import_source' AND NOT public.calendar_import_source_valid(NEW.id)
   THEN RAISE EXCEPTION 'Exact calendar import source review required' USING ERRCODE='23514'; END IF;
 ELSIF NOT public.calendar_import_source_valid(NEW.entry_id)
  THEN RAISE EXCEPTION 'Calendar import source commitment invalid' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER calendar_import_entry_guard AFTER INSERT ON public.workspace_entries
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_calendar_import_entry();
CREATE CONSTRAINT TRIGGER calendar_import_review_commitment_guard AFTER INSERT ON public.calendar_import_source_reviews
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_calendar_import_entry();
CREATE FUNCTION public.guard_calendar_import_revocation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r public.calendar_import_requests; s public.calendar_import_snapshots; w public.encounter_workspaces;
BEGIN
 SELECT * INTO r FROM public.calendar_import_requests WHERE id=NEW.import_id;
 PERFORM public.calendar_import_lock_scope(r.workspace_id,r.box_id,r.owner_id,r.account_id,r.patient_link_id);
 SELECT * INTO s FROM public.calendar_import_snapshots WHERE import_id=r.id;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=r.workspace_id;
 IF r.id IS NULL OR s.id IS NULL OR w.id IS NULL
 OR (NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.expected_revision) IS DISTINCT FROM (r.workspace_id,r.box_id,r.owner_id,w.revision)
 OR NOT public.calendar_import_key_free(NEW.workspace_id,NEW.idempotency_key,'revoke')
 OR NOT public.calendar_import_request_current(r.id) OR NOT public.calendar_import_snapshot_valid(s.id)
 OR NEW.import_sha256 IS DISTINCT FROM s.source_sha256
 OR NEW.request_hash IS DISTINCT FROM public.google_calendar_json_digest(jsonb_build_object('action','revoke','workspace_id',NEW.workspace_id,
 'expected_revision',NEW.expected_revision,'idempotency_key',NEW.idempotency_key,'import_id',NEW.import_id,'source_sha256',NEW.import_sha256))
 THEN RAISE EXCEPTION 'Calendar import revocation custody or commitment invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER calendar_import_revocation_guard BEFORE INSERT ON public.calendar_import_revocations
 FOR EACH ROW EXECUTE FUNCTION public.guard_calendar_import_revocation();
CREATE TRIGGER calendar_import_request_immutable BEFORE UPDATE OR DELETE ON public.calendar_import_requests
 FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER calendar_import_snapshot_immutable BEFORE UPDATE OR DELETE ON public.calendar_import_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER calendar_import_review_immutable BEFORE UPDATE OR DELETE ON public.calendar_import_source_reviews
 FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
CREATE TRIGGER calendar_import_revocation_immutable BEFORE UPDATE OR DELETE ON public.calendar_import_revocations
 FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change();
"""

# Generated from Python unicodedata15.1.0: each interval contains exactly category C
# (control, format, surrogate, private-use or unassigned) codepoints. The unit check
# recomputes this fixed contract to refuse silent Unicode-version drift.
UNICODE_VERSION = "15.1.0"
UNICODE_C_RANGES = (
    '{[0,32),[127,160),[173,174),[888,890),[896,900),[907,908),[909,910),[930,931),[1328,1329),[1367,1369),[1419,1421),[1424,1425),[1480,1488),[1515,1519),[1525,1542),[1564,1565),[1757,'
    '1758),[1806,1808),[1867,1869),[1970,1984),[2043,2045),[2094,2096),[2111,2112),[2140,2142),[2143,2144),[2155,2160),[2191,2200),[2274,2275),[2436,2437),[2445,2447),[2449,2451),[2473,'
    '2474),[2481,2482),[2483,2486),[2490,2492),[2501,2503),[2505,2507),[2511,2519),[2520,2524),[2526,2527),[2532,2534),[2559,2561),[2564,2565),[2571,2575),[2577,2579),[2601,2602),[2609,'
    '2610),[2612,2613),[2615,2616),[2618,2620),[2621,2622),[2627,2631),[2633,2635),[2638,2641),[2642,2649),[2653,2654),[2655,2662),[2679,2689),[2692,2693),[2702,2703),[2706,2707),[2729,'
    '2730),[2737,2738),[2740,2741),[2746,2748),[2758,2759),[2762,2763),[2766,2768),[2769,2784),[2788,2790),[2802,2809),[2816,2817),[2820,2821),[2829,2831),[2833,2835),[2857,2858),[2865,'
    '2866),[2868,2869),[2874,2876),[2885,2887),[2889,2891),[2894,2901),[2904,2908),[2910,2911),[2916,2918),[2936,2946),[2948,2949),[2955,2958),[2961,2962),[2966,2969),[2971,2972),[2973,'
    '2974),[2976,2979),[2981,2984),[2987,2990),[3002,3006),[3011,3014),[3017,3018),[3022,3024),[3025,3031),[3032,3046),[3067,3072),[3085,3086),[3089,3090),[3113,3114),[3130,3132),[3141,'
    '3142),[3145,3146),[3150,3157),[3159,3160),[3163,3165),[3166,3168),[3172,3174),[3184,3191),[3213,3214),[3217,3218),[3241,3242),[3252,3253),[3258,3260),[3269,3270),[3273,3274),[3278,'
    '3285),[3287,3293),[3295,3296),[3300,3302),[3312,3313),[3316,3328),[3341,3342),[3345,3346),[3397,3398),[3401,3402),[3408,3412),[3428,3430),[3456,3457),[3460,3461),[3479,3482),[3506,'
    '3507),[3516,3517),[3518,3520),[3527,3530),[3531,3535),[3541,3542),[3543,3544),[3552,3558),[3568,3570),[3573,3585),[3643,3647),[3676,3713),[3715,3716),[3717,3718),[3723,3724),[3748,'
    '3749),[3750,3751),[3774,3776),[3781,3782),[3783,3784),[3791,3792),[3802,3804),[3808,3840),[3912,3913),[3949,3953),[3992,3993),[4029,4030),[4045,4046),[4059,4096),[4294,4295),[4296,'
    '4301),[4302,4304),[4681,4682),[4686,4688),[4695,4696),[4697,4698),[4702,4704),[4745,4746),[4750,4752),[4785,4786),[4790,4792),[4799,4800),[4801,4802),[4806,4808),[4823,4824),[4881,'
    '4882),[4886,4888),[4955,4957),[4989,4992),[5018,5024),[5110,5112),[5118,5120),[5789,5792),[5881,5888),[5910,5919),[5943,5952),[5972,5984),[5997,5998),[6001,6002),[6004,6016),[6110,'
    '6112),[6122,6128),[6138,6144),[6158,6159),[6170,6176),[6265,6272),[6315,6320),[6390,6400),[6431,6432),[6444,6448),[6460,6464),[6465,6468),[6510,6512),[6517,6528),[6572,6576),[6602,'
    '6608),[6619,6622),[6684,6686),[6751,6752),[6781,6783),[6794,6800),[6810,6816),[6830,6832),[6863,6912),[6989,6992),[7039,7040),[7156,7164),[7224,7227),[7242,7245),[7305,7312),[7355,'
    '7357),[7368,7376),[7419,7424),[7958,7960),[7966,7968),[8006,8008),[8014,8016),[8024,8025),[8026,8027),[8028,8029),[8030,8031),[8062,8064),[8117,8118),[8133,8134),[8148,8150),[8156,'
    '8157),[8176,8178),[8181,8182),[8191,8192),[8203,8208),[8234,8239),[8288,8304),[8306,8308),[8335,8336),[8349,8352),[8385,8400),[8433,8448),[8588,8592),[9255,9280),[9291,9312),[11124'
    ',11126),[11158,11159),[11508,11513),[11558,11559),[11560,11565),[11566,11568),[11624,11631),[11633,11647),[11671,11680),[11687,11688),[11695,11696),[11703,11704),[11711,11712),[117'
    '19,11720),[11727,11728),[11735,11736),[11743,11744),[11870,11904),[11930,11931),[12020,12032),[12246,12272),[12352,12353),[12439,12441),[12544,12549),[12592,12593),[12687,12688),[1'
    '2772,12783),[12831,12832),[42125,42128),[42183,42192),[42540,42560),[42744,42752),[42955,42960),[42962,42963),[42964,42965),[42970,42994),[43053,43056),[43066,43072),[43128,43136),'
    '[43206,43214),[43226,43232),[43348,43359),[43389,43392),[43470,43471),[43482,43486),[43519,43520),[43575,43584),[43598,43600),[43610,43612),[43715,43739),[43767,43777),[43783,43785'
    '),[43791,43793),[43799,43808),[43815,43816),[43823,43824),[43884,43888),[44014,44016),[44026,44032),[55204,55216),[55239,55243),[55292,63744),[64110,64112),[64218,64256),[64263,642'
    '75),[64280,64285),[64311,64312),[64317,64318),[64319,64320),[64322,64323),[64325,64326),[64451,64467),[64912,64914),[64968,64975),[64976,65008),[65050,65056),[65107,65108),[65127,6'
    '5128),[65132,65136),[65141,65142),[65277,65281),[65471,65474),[65480,65482),[65488,65490),[65496,65498),[65501,65504),[65511,65512),[65519,65532),[65534,65536),[65548,65549),[65575'
    ',65576),[65595,65596),[65598,65599),[65614,65616),[65630,65664),[65787,65792),[65795,65799),[65844,65847),[65935,65936),[65949,65952),[65953,66000),[66046,66176),[66205,66208),[662'
    '57,66272),[66300,66304),[66340,66349),[66379,66384),[66427,66432),[66462,66463),[66500,66504),[66518,66560),[66718,66720),[66730,66736),[66772,66776),[66812,66816),[66856,66864),[6'
    '6916,66927),[66939,66940),[66955,66956),[66963,66964),[66966,66967),[66978,66979),[66994,66995),[67002,67003),[67005,67072),[67383,67392),[67414,67424),[67432,67456),[67462,67463),'
    '[67505,67506),[67515,67584),[67590,67592),[67593,67594),[67638,67639),[67641,67644),[67645,67647),[67670,67671),[67743,67751),[67760,67808),[67827,67828),[67830,67835),[67868,67871'
    '),[67898,67903),[67904,67968),[68024,68028),[68048,68050),[68100,68101),[68103,68108),[68116,68117),[68120,68121),[68150,68152),[68155,68159),[68169,68176),[68185,68192),[68256,682'
    '88),[68327,68331),[68343,68352),[68406,68409),[68438,68440),[68467,68472),[68498,68505),[68509,68521),[68528,68608),[68681,68736),[68787,68800),[68851,68858),[68904,68912),[68922,6'
    '9216),[69247,69248),[69290,69291),[69294,69296),[69298,69373),[69416,69424),[69466,69488),[69514,69552),[69580,69600),[69623,69632),[69710,69714),[69750,69759),[69821,69822),[69827'
    ',69840),[69865,69872),[69882,69888),[69941,69942),[69960,69968),[70007,70016),[70112,70113),[70133,70144),[70162,70163),[70210,70272),[70279,70280),[70281,70282),[70286,70287),[703'
    '02,70303),[70314,70320),[70379,70384),[70394,70400),[70404,70405),[70413,70415),[70417,70419),[70441,70442),[70449,70450),[70452,70453),[70458,70459),[70469,70471),[70473,70475),[7'
    '0478,70480),[70481,70487),[70488,70493),[70500,70502),[70509,70512),[70517,70656),[70748,70749),[70754,70784),[70856,70864),[70874,71040),[71094,71096),[71134,71168),[71237,71248),'
    '[71258,71264),[71277,71296),[71354,71360),[71370,71424),[71451,71453),[71468,71472),[71495,71680),[71740,71840),[71923,71935),[71943,71945),[71946,71948),[71956,71957),[71959,71960'
    '),[71990,71991),[71993,71995),[72007,72016),[72026,72096),[72104,72106),[72152,72154),[72165,72192),[72264,72272),[72355,72368),[72441,72448),[72458,72704),[72713,72714),[72759,727'
    '60),[72774,72784),[72813,72816),[72848,72850),[72872,72873),[72887,72960),[72967,72968),[72970,72971),[73015,73018),[73019,73020),[73022,73023),[73032,73040),[73050,73056),[73062,7'
    '3063),[73065,73066),[73103,73104),[73106,73107),[73113,73120),[73130,73440),[73465,73472),[73489,73490),[73531,73534),[73562,73648),[73649,73664),[73714,73727),[74650,74752),[74863'
    ',74864),[74869,74880),[75076,77712),[77811,77824),[78896,78912),[78934,82944),[83527,92160),[92729,92736),[92767,92768),[92778,92782),[92863,92864),[92874,92880),[92910,92912),[929'
    '18,92928),[92998,93008),[93018,93019),[93026,93027),[93048,93053),[93072,93760),[93851,93952),[94027,94031),[94088,94095),[94112,94176),[94181,94192),[94194,94208),[100344,100352),'
    '[101590,101632),[101641,110576),[110580,110581),[110588,110589),[110591,110592),[110883,110898),[110899,110928),[110931,110933),[110934,110948),[110952,110960),[111356,113664),[113'
    '771,113776),[113789,113792),[113801,113808),[113818,113820),[113824,118528),[118574,118576),[118599,118608),[118724,118784),[119030,119040),[119079,119081),[119155,119163),[119275,'
    '119296),[119366,119488),[119508,119520),[119540,119552),[119639,119648),[119673,119808),[119893,119894),[119965,119966),[119968,119970),[119971,119973),[119975,119977),[119981,1199'
    '82),[119994,119995),[119996,119997),[120004,120005),[120070,120071),[120075,120077),[120085,120086),[120093,120094),[120122,120123),[120127,120128),[120133,120134),[120135,120138),'
    '[120145,120146),[120486,120488),[120780,120782),[121484,121499),[121504,121505),[121520,122624),[122655,122661),[122667,122880),[122887,122888),[122905,122907),[122914,122915),[122'
    '917,122918),[122923,122928),[122990,123023),[123024,123136),[123181,123184),[123198,123200),[123210,123214),[123216,123536),[123567,123584),[123642,123647),[123648,124112),[124154,'
    '124896),[124903,124904),[124908,124909),[124911,124912),[124927,124928),[125125,125127),[125143,125184),[125260,125264),[125274,125278),[125280,126065),[126133,126209),[126270,1264'
    '64),[126468,126469),[126496,126497),[126499,126500),[126501,126503),[126504,126505),[126515,126516),[126520,126521),[126522,126523),[126524,126530),[126531,126535),[126536,126537),'
    '[126538,126539),[126540,126541),[126544,126545),[126547,126548),[126549,126551),[126552,126553),[126554,126555),[126556,126557),[126558,126559),[126560,126561),[126563,126564),[126'
    '565,126567),[126571,126572),[126579,126580),[126584,126585),[126589,126590),[126591,126592),[126602,126603),[126620,126625),[126628,126629),[126634,126635),[126652,126704),[126706,'
    '126976),[127020,127024),[127124,127136),[127151,127153),[127168,127169),[127184,127185),[127222,127232),[127406,127462),[127491,127504),[127548,127552),[127561,127568),[127570,1275'
    '84),[127590,127744),[128728,128732),[128749,128752),[128765,128768),[128887,128891),[128986,128992),[129004,129008),[129009,129024),[129036,129040),[129096,129104),[129114,129120),'
    '[129160,129168),[129198,129200),[129202,129280),[129620,129632),[129646,129648),[129661,129664),[129673,129680),[129726,129727),[129734,129742),[129756,129760),[129769,129776),[129'
    '785,129792),[129939,129940),[129995,130032),[130042,131072),[173792,173824),[177978,177984),[178206,178208),[183970,183984),[191457,191472),[192094,194560),[195102,196608),[201547,'
    '201552),[205744,917760),[918000,1114112)}'
)
CODEPOINT_GUARD = """
CREATE FUNCTION public.calendar_import_codepoints_valid(value text) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT NOT EXISTS(SELECT 1 FROM generate_series(1,char_length(value)) n
 WHERE ascii(substr(value,n,1)) <@ '{ranges}'::int4multirange)
$$;
"""
