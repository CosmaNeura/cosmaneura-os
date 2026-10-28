"""Immutable Elation read intent, exact observation and selected visit custody."""

from pathlib import Path
from runpy import run_path

from alembic import op

revision = "m02e8a1c6543"
down_revision = "l91a7b0e5432"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)
    op.drop_constraint("ck_workspace_entry_kind", "workspace_entries", type_="check")
    op.create_check_constraint("ck_workspace_entry_kind", "workspace_entries",
        "kind IN ('synthetic_source','scratchpad','conversation','evidence','work_link','handoff_result','google_message','google_calendar','efax_inbound_source','fax_inbound_source','ehr_read_source')")
    op.execute(GUARDS)
    # Extend the exact previous selected-source guards, retaining saved-note
    # custody and owner directions without rewriting migration history.
    versions = Path(__file__).parent
    fax = run_path(str(versions / "h68e0c4f1239_fax_reviewed_source.py"))
    note = run_path(str(versions / "j79f1d5a2340_human_shared_note_custody.py"))
    directions = run_path(str(versions / "k80e6a9d4321_saved_note_drafting_directions.py"))
    for name, previous, extensions in (
        ("HANDOFF_GUARDS", note["REVIEW_EXTENSIONS"], REVIEW_EXTENSIONS),
        ("MODEL_GUARDS", (*note["MODEL_EXTENSIONS"], *directions["DIRECTIONS_EXTENSIONS"]), MODEL_EXTENSIONS),
    ):
        sql = fax[name]
        for before, after in previous:
            if sql.count(before) != 1:
                raise RuntimeError("Previous selected-source guard differs from the frozen extension")
            sql = sql.replace(before, after)
        for before, after, expected in extensions:
            if sql.count(before) != expected:
                raise RuntimeError("EHR selected-source guard extension does not match")
            sql = sql.replace(before, after)
        op.execute(sql)


def downgrade():
    raise RuntimeError("Retain EHR read intent, snapshots and exact human source reviews")


REVIEW_EXTENSIONS = (
    ("'fax_inbound_source','conversation') THEN 'evidence'",
     "'fax_inbound_source','ehr_read_source','conversation') THEN 'evidence'", 2),
    ("(kind='conversation' AND public.clinical_note_source_current(e.id)))",
     "(kind='conversation' AND public.clinical_note_source_current(e.id)) OR (kind='ehr_read_source' AND public.ehr_read_source_current(e.id)))", 1),
    ("OR (source_entry.kind='fax_inbound_source' AND NOT public.fax_inbound_source_current(source_entry.id))",
     "OR (source_entry.kind='fax_inbound_source' AND NOT public.fax_inbound_source_current(source_entry.id))\n"
     "   OR (source_entry.kind='ehr_read_source' AND NOT public.ehr_read_source_current(source_entry.id))", 1),
)
MODEL_EXTENSIONS = (
    ("'google_message','google_calendar','efax_inbound_source','fax_inbound_source')",
     "'google_message','google_calendar','efax_inbound_source','fax_inbound_source','ehr_read_source')", 1),
    ("OR (entry.kind='fax_inbound_source' AND NOT public.fax_inbound_source_current(entry.id))",
     "OR (entry.kind='fax_inbound_source' AND NOT public.fax_inbound_source_current(entry.id))\n"
     "    OR (entry.kind='ehr_read_source' AND NOT public.ehr_read_source_current(entry.id))", 1),
    ("entry.kind IN ('efax_inbound_source','fax_inbound_source')",
     "entry.kind IN ('efax_inbound_source','fax_inbound_source','ehr_read_source')", 1),
)


TABLES = r"""
CREATE TABLE ehr_read_bindings (
	id UUID NOT NULL,
	account_id UUID NOT NULL,
	vendor VARCHAR(16) NOT NULL,
	connection_id UUID NOT NULL,
	credential_generation UUID NOT NULL,
	practice_id VARCHAR(20) NOT NULL,
	practice_name VARCHAR(200) NOT NULL,
	environment VARCHAR(16) NOT NULL,
	binding_digest VARCHAR(64) NOT NULL,
	state VARCHAR(16) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(account_id, box_id, owner_id) REFERENCES external_identities (id, box_id, principal_id),
	CONSTRAINT uq_ehr_read_binding_scope UNIQUE (id, box_id, owner_id),
	CONSTRAINT uq_ehr_read_binding_account UNIQUE (id, box_id, owner_id, account_id),
	CONSTRAINT uq_ehr_read_binding_version UNIQUE (box_id, owner_id, connection_id, credential_generation, practice_id),
	CONSTRAINT ck_ehr_read_binding_vendor CHECK (vendor='elation' AND environment='sandbox'),
	CONSTRAINT ck_ehr_read_binding_practice CHECK (practice_id ~ '^[1-9][0-9]*$' AND char_length(practice_id)<=19 AND practice_id::numeric<=9223372036854775807),
	CONSTRAINT ck_ehr_read_binding_name CHECK (char_length(practice_name) BETWEEN 1 AND 200 AND practice_name !~ '[[:cntrl:]]'),
	CONSTRAINT ck_ehr_read_binding_state CHECK ((state='active' AND revoked_at IS NULL) OR (state='revoked' AND revoked_at IS NOT NULL)),
	CHECK (binding_digest ~ '^[a-f0-9]{64}$')
);

CREATE TABLE ehr_read_requests (
	id UUID NOT NULL,
	binding_id UUID NOT NULL,
	account_id UUID NOT NULL,
	connection_id UUID NOT NULL,
	credential_generation UUID NOT NULL,
	practice_id VARCHAR(20) NOT NULL,
	binding_digest VARCHAR(64) NOT NULL,
	kind VARCHAR(16) NOT NULL,
	ordinal INTEGER NOT NULL,
	idempotency_key VARCHAR(100) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	request_json JSONB NOT NULL,
	parent_snapshot_id UUID,
	item_handle UUID,
	window_start TIMESTAMP WITH TIME ZONE NOT NULL,
	window_end TIMESTAMP WITH TIME ZONE NOT NULL,
	valid_until TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(binding_id, box_id, owner_id, account_id) REFERENCES ehr_read_bindings (id, box_id, owner_id, account_id),
	CONSTRAINT uq_ehr_read_request_scope UNIQUE (id, box_id, owner_id),
	CONSTRAINT uq_ehr_read_request_ordinal UNIQUE (binding_id, ordinal),
	CONSTRAINT uq_ehr_read_request_key UNIQUE (box_id, owner_id, idempotency_key),
	CONSTRAINT ck_ehr_read_request_key CHECK (ordinal BETWEEN 1 AND 500 AND idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'),
	CONSTRAINT ck_ehr_read_request_kind CHECK ((kind='window' AND parent_snapshot_id IS NULL AND item_handle IS NULL) OR (kind='verify' AND parent_snapshot_id IS NOT NULL AND item_handle IS NOT NULL)),
	CONSTRAINT ck_ehr_read_request_window CHECK (isfinite(window_start) AND isfinite(window_end) AND window_end>window_start AND window_end<=window_start+interval '168 hours'),
	CONSTRAINT ck_ehr_read_request_expiry CHECK (isfinite(valid_until) AND valid_until>created_at AND valid_until<=created_at+interval '30 minutes'),
	CHECK (request_hash ~ '^[a-f0-9]{64}$' AND binding_digest ~ '^[a-f0-9]{64}$'),
	CHECK (jsonb_typeof(request_json) = 'object' AND octet_length(request_json::text) <= 4096)
);

CREATE TABLE ehr_read_snapshots (
	id UUID NOT NULL,
	observation_id UUID NOT NULL,
	payload JSONB NOT NULL,
	payload_sha256 VARCHAR(64) NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(observation_id, box_id, owner_id) REFERENCES ehr_read_requests (id, box_id, owner_id),
	CONSTRAINT uq_ehr_read_snapshot_observation UNIQUE (observation_id),
	CONSTRAINT uq_ehr_read_snapshot_scope UNIQUE (id, box_id, owner_id),
	CHECK (payload_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$'),
	CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 65536)
);

CREATE TABLE ehr_read_source_reviews (
	id UUID NOT NULL,
	entry_id UUID NOT NULL,
	snapshot_id UUID NOT NULL,
	patient_link_id UUID NOT NULL,
	expected_revision INTEGER NOT NULL,
	workspace_revision INTEGER NOT NULL,
	idempotency_key VARCHAR(100) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	observation_sha256 VARCHAR(64) NOT NULL,
	item_handle UUID NOT NULL,
	item_sha256 VARCHAR(64) NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	valid_until TIMESTAMP WITH TIME ZONE NOT NULL,
	reviewed_visit BOOLEAN NOT NULL,
	reviewed_patient_identity BOOLEAN NOT NULL,
	reviewed_exact_snapshot BOOLEAN NOT NULL,
	reviewed_untrusted_source BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	workspace_id UUID NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id),
	FOREIGN KEY(entry_id, workspace_id, box_id) REFERENCES workspace_entries (id, workspace_id, box_id),
	FOREIGN KEY(snapshot_id, box_id, owner_id) REFERENCES ehr_read_snapshots (id, box_id, owner_id),
	FOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id),
	CONSTRAINT uq_ehr_read_review_entry UNIQUE (entry_id),
	CONSTRAINT uq_ehr_read_review_item UNIQUE (workspace_id, snapshot_id, item_handle),
	CONSTRAINT uq_ehr_read_review_key UNIQUE (workspace_id, idempotency_key),
	CONSTRAINT ck_ehr_read_review_revision CHECK (expected_revision>=1 AND workspace_revision=expected_revision+1),
	CONSTRAINT ck_ehr_read_review_checks CHECK (reviewed_visit AND reviewed_patient_identity AND reviewed_exact_snapshot AND reviewed_untrusted_source),
	CONSTRAINT ck_ehr_read_review_key CHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'),
	CHECK (request_hash ~ '^[a-f0-9]{64}$' AND observation_sha256 ~ '^[a-f0-9]{64}$' AND item_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$' AND content_sha256 ~ '^[a-f0-9]{64}$')
);

CREATE UNIQUE INDEX uq_ehr_read_binding_active ON ehr_read_bindings (box_id, owner_id, account_id, connection_id) WHERE state = 'active';

ALTER TABLE ehr_read_requests ADD CONSTRAINT fk_ehr_read_request_parent FOREIGN KEY(parent_snapshot_id, box_id, owner_id) REFERENCES ehr_read_snapshots (id, box_id, owner_id);
"""


GUARDS = r"""
CREATE FUNCTION public.ehr_read_binding_digest(b public.ehr_read_bindings) RETURNS text
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT public.research_json_digest(jsonb_build_object('contract','elation-read-scope.v1',
  'box_id',b.box_id,'owner_id',b.owner_id,'connection_id',b.connection_id,
  'credential_generation',b.credential_generation,'practice_id',b.practice_id::bigint,
  'practice_name',b.practice_name,'environment',b.environment))
$$;
CREATE FUNCTION public.ehr_read_binding_current(bid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_read_bindings b
  JOIN public.external_identities a ON (a.id,a.box_id,a.principal_id)=(b.account_id,b.box_id,b.owner_id)
  JOIN public.principals p ON (p.id,p.box_id)=(b.owner_id,b.box_id)
  WHERE b.id=bid AND b.state='active' AND b.revoked_at IS NULL AND a.active
   AND p.principal_type='human' AND p.state='active' AND p.tombstoned_at IS NULL
   AND b.binding_digest=public.ehr_read_binding_digest(b))
$$;
CREATE FUNCTION public.guard_ehr_read_binding() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retain EHR binding identity' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-'state'-'revoked_at') IS DISTINCT FROM (to_jsonb(OLD)-'state'-'revoked_at')
   OR OLD.state<>'active' OR NEW.state<>'revoked' OR NEW.revoked_at IS NULL
   OR NOT isfinite(NEW.revoked_at) OR NEW.revoked_at<OLD.created_at
  THEN RAISE EXCEPTION 'EHR binding identity is immutable' USING ERRCODE='23514'; END IF;
 ELSE
  PERFORM 1 FROM public.principals WHERE (id,box_id)=(NEW.owner_id,NEW.box_id) FOR UPDATE;
  PERFORM 1 FROM public.external_identities WHERE id=NEW.account_id FOR SHARE;
  IF NEW.state<>'active' OR NEW.revoked_at IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM public.external_identities a JOIN public.principals p
    ON (p.id,p.box_id)=(a.principal_id,a.box_id)
    WHERE (a.id,a.box_id,a.principal_id)=(NEW.account_id,NEW.box_id,NEW.owner_id)
     AND a.active AND p.principal_type='human' AND p.state='active' AND p.tombstoned_at IS NULL)
   OR NEW.binding_digest IS DISTINCT FROM public.ehr_read_binding_digest(NEW)
  THEN RAISE EXCEPTION 'EHR binding authority invalid' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ehr_read_binding_guard BEFORE INSERT OR UPDATE OR DELETE ON public.ehr_read_bindings
 FOR EACH ROW EXECUTE FUNCTION public.guard_ehr_read_binding();

CREATE FUNCTION public.ehr_read_request_current(rid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_read_requests r
  JOIN public.ehr_read_bindings b ON (b.id,b.box_id,b.owner_id,b.account_id)=(r.binding_id,r.box_id,r.owner_id,r.account_id)
  LEFT JOIN public.ehr_read_snapshots parent ON parent.id=r.parent_snapshot_id
  LEFT JOIN public.ehr_read_requests root ON root.id=parent.observation_id
  WHERE r.id=rid AND public.ehr_read_binding_current(b.id) AND r.valid_until>clock_timestamp()
   AND (r.connection_id,r.credential_generation,r.practice_id,r.binding_digest)
    =(b.connection_id,b.credential_generation,b.practice_id,b.binding_digest)
   AND NOT EXISTS(SELECT 1 FROM public.ehr_read_requests newer WHERE newer.binding_id=r.binding_id
    AND newer.kind='window' AND newer.ordinal>CASE WHEN r.kind='window' THEN r.ordinal ELSE root.ordinal END)
   AND (r.kind='window' OR (root.kind='window' AND root.binding_id=r.binding_id AND root.valid_until>=r.valid_until)))
$$;
CREATE FUNCTION public.guard_ehr_read_request() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE b public.ehr_read_bindings; parent public.ehr_read_snapshots; root public.ehr_read_requests;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'EHR read requests are immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM public.principals WHERE (id,box_id)=(NEW.owner_id,NEW.box_id) FOR UPDATE;
 PERFORM 1 FROM public.external_identities WHERE id=NEW.account_id FOR SHARE;
 SELECT * INTO b FROM public.ehr_read_bindings WHERE id=NEW.binding_id FOR UPDATE;
 IF b.id IS NULL OR NOT public.ehr_read_binding_current(b.id)
  OR (NEW.box_id,NEW.owner_id,NEW.account_id,NEW.connection_id,NEW.credential_generation,NEW.practice_id,NEW.binding_digest)
   IS DISTINCT FROM (b.box_id,b.owner_id,b.account_id,b.connection_id,b.credential_generation,b.practice_id,b.binding_digest)
  OR NEW.ordinal IS DISTINCT FROM (SELECT coalesce(max(ordinal),0)+1 FROM public.ehr_read_requests WHERE binding_id=b.id)
  OR NEW.created_at>clock_timestamp() OR NEW.created_at<clock_timestamp()-interval '1 minute'
  OR NEW.valid_until<=clock_timestamp()
  OR NEW.request_hash IS DISTINCT FROM public.google_calendar_json_digest(NEW.request_json)
  OR NEW.request_json->>'connection_id' IS DISTINCT FROM NEW.connection_id::text
  OR NEW.request_json->>'binding_sha256' IS DISTINCT FROM NEW.binding_digest
  OR NEW.request_json->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
 THEN RAISE EXCEPTION 'EHR request authority or commitment invalid' USING ERRCODE='23514'; END IF;
 IF NEW.kind='window' THEN
  IF NOT public.finance_settings_keys(NEW.request_json,ARRAY['action','connection_id','binding_sha256','idempotency_key','starts_at','ends_at'])
   OR NEW.request_json->>'action' IS DISTINCT FROM 'observe'
   OR NOT public.google_message_aware_time(NEW.request_json->'starts_at')
   OR NOT public.google_message_aware_time(NEW.request_json->'ends_at')
   OR ((NEW.request_json->>'starts_at')::timestamptz,(NEW.request_json->>'ends_at')::timestamptz)
    IS DISTINCT FROM (NEW.window_start,NEW.window_end)
  THEN RAISE EXCEPTION 'EHR window request commitment invalid' USING ERRCODE='23514'; END IF;
 ELSIF NEW.kind='verify' THEN
  SELECT * INTO parent FROM public.ehr_read_snapshots WHERE id=NEW.parent_snapshot_id;
  SELECT * INTO root FROM public.ehr_read_requests WHERE id=parent.observation_id;
  IF parent.id IS NULL OR root.kind<>'window' OR root.binding_id<>NEW.binding_id
   OR (root.box_id,root.owner_id,root.window_start,root.window_end) IS DISTINCT FROM
    (NEW.box_id,NEW.owner_id,NEW.window_start,NEW.window_end)
   OR NOT public.ehr_read_request_current(root.id) OR NEW.valid_until>root.valid_until
   OR NOT public.ehr_read_snapshot_valid(parent.id)
   OR NOT public.finance_settings_keys(NEW.request_json,ARRAY['action','connection_id','binding_sha256','idempotency_key','observation_id','observation_sha256','item_handle','item_sha256'])
   OR NEW.request_json->>'action' IS DISTINCT FROM 'verify'
   OR NEW.request_json->>'observation_id' IS DISTINCT FROM root.id::text
   OR NEW.request_json->>'observation_sha256' IS DISTINCT FROM parent.source_sha256
   OR NEW.request_json->>'item_handle' IS DISTINCT FROM NEW.item_handle::text
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent.payload->'public'->'items') item
    WHERE item->>'handle'=NEW.item_handle::text AND item->>'selectable'='true'
     AND item->>'sha256'=NEW.request_json->>'item_sha256')
  THEN RAISE EXCEPTION 'EHR exact parent request invalid' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ehr_read_request_guard BEFORE INSERT OR UPDATE OR DELETE ON public.ehr_read_requests
 FOR EACH ROW EXECUTE FUNCTION public.guard_ehr_read_request();

CREATE FUNCTION public.ehr_read_text(value jsonb, maximum integer) RETURNS boolean
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT coalesce(jsonb_typeof(value)='string' AND char_length(value#>>'{}') BETWEEN 1 AND maximum
  AND (value#>>'{}') !~ '[[:cntrl:]]',false)
$$;
CREATE FUNCTION public.ehr_read_provider_id(value jsonb) RETURNS boolean
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
BEGIN
 RETURN coalesce(jsonb_typeof(value)='string' AND (value#>>'{}') ~ '^[1-9][0-9]{0,18}$'
  AND (value#>>'{}')::numeric<=9223372036854775807,false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_read_payload_valid(payload jsonb, r public.ehr_read_requests) RETURNS boolean
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE pub jsonb:=payload->'public'; priv jsonb:=payload->'private'; row jsonb; item jsonb; appt jsonb;
 patient jsonb; seen text[]:=ARRAY[]::text[]; seen_ids text[]:=ARRAY[]::text[];
 count_items integer; parent_item jsonb; b public.ehr_read_bindings;
BEGIN
 SELECT * INTO b FROM public.ehr_read_bindings WHERE id=r.binding_id;
 IF NOT public.finance_settings_keys(payload,ARRAY['public','private'])
  OR NOT public.finance_settings_keys(priv,ARRAY['binding_sha256','request_sha256','items','provider_sources'])
  OR priv->>'binding_sha256' IS DISTINCT FROM r.binding_digest OR priv->>'request_sha256' IS DISTINCT FROM r.request_hash
  OR jsonb_typeof(priv->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(priv->'items')>25
  OR jsonb_typeof(priv->'provider_sources') IS DISTINCT FROM 'array'
  OR jsonb_array_length(priv->'provider_sources') NOT BETWEEN 1 AND 2
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(priv->'provider_sources') digest
   WHERE jsonb_typeof(digest)<>'string' OR digest#>>'{}' !~ '^[a-f0-9]{64}$')
  OR pub->>'provider' IS DISTINCT FROM 'elation' OR pub->>'mode' IS DISTINCT FROM 'synthetic'
  OR NOT public.finance_settings_keys(pub->'practice',ARRAY['label','timezone'])
  OR pub->'practice'->>'label' IS DISTINCT FROM b.practice_name
  OR NOT public.ehr_read_text(pub->'practice'->'label',200)
  OR NOT public.ehr_read_text(pub->'practice'->'timezone',100)
  OR NOT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=pub->'practice'->>'timezone')
  OR NOT public.google_message_aware_time(pub->'observed_at')
  OR (pub->>'observed_at')::timestamptz<r.created_at OR (pub->>'observed_at')::timestamptz>clock_timestamp()
  OR NOT public.finance_settings_keys(pub->'window',ARRAY['starts_at','ends_at'])
  OR NOT public.google_message_aware_time(pub->'window'->'starts_at')
  OR NOT public.google_message_aware_time(pub->'window'->'ends_at')
  OR ((pub->'window'->>'starts_at')::timestamptz,(pub->'window'->>'ends_at')::timestamptz)
   IS DISTINCT FROM (r.window_start,r.window_end)
  OR coalesce(pub->>'coverage','') NOT IN ('end_of_results','more_rows_available')
 THEN RETURN false; END IF;
 IF r.kind='window' THEN
  IF NOT public.finance_settings_keys(pub,ARRAY['kind','provider','mode','practice','observed_at','window','coverage','items'])
   OR pub->>'kind' IS DISTINCT FROM 'window' OR jsonb_typeof(pub->'items') IS DISTINCT FROM 'array'
   OR jsonb_array_length(pub->'items')<>jsonb_array_length(priv->'items') THEN RETURN false; END IF;
 ELSE
  IF NOT public.finance_settings_keys(pub,ARRAY['kind','provider','mode','practice','observed_at','window','coverage','item'])
   OR pub->>'kind' IS DISTINCT FROM 'verified_visit' OR jsonb_array_length(priv->'items')<>1
   OR pub->'item'->>'handle' IS DISTINCT FROM r.item_handle::text THEN RETURN false; END IF;
 END IF;
 count_items:=0;
 FOR row IN SELECT * FROM jsonb_array_elements(priv->'items') LOOP
  appt:=row->'appointment'; patient:=row->'patient';
  IF NOT public.finance_settings_keys(row,ARRAY['handle','appointment','patient'])
   OR jsonb_typeof(row->'handle') IS DISTINCT FROM 'string'
   OR (row->>'handle')::uuid::text IS DISTINCT FROM row->>'handle' OR row->>'handle'=ANY(seen)
   OR NOT public.finance_settings_keys(appt,ARRAY['appointment_id','patient_id','physician_id','starts_at','ends_at','status','scheduled_date_raw','deleted_at'])
   OR NOT public.ehr_read_provider_id(appt->'appointment_id')
   OR appt->>'appointment_id'=ANY(seen_ids)
   OR NOT public.ehr_read_provider_id(appt->'physician_id')
   OR (appt->'patient_id'<>'null'::jsonb AND NOT public.ehr_read_provider_id(appt->'patient_id'))
   OR NOT public.ehr_read_text(appt->'scheduled_date_raw',40)
   OR NOT public.google_message_aware_time(appt->'starts_at') OR NOT public.google_message_aware_time(appt->'ends_at')
   OR (appt->>'starts_at')::timestamptz>=(appt->>'ends_at')::timestamptz
   OR (appt->>'ends_at')::timestamptz>(appt->>'starts_at')::timestamptz+interval '24 hours'
   OR (appt->>'starts_at')::timestamptz NOT BETWEEN r.window_start AND r.window_end
   OR (appt->>'scheduled_date_raw')::timestamptz IS DISTINCT FROM (appt->>'starts_at')::timestamptz
   OR (appt->'deleted_at'<>'null'::jsonb AND NOT public.google_message_aware_time(appt->'deleted_at'))
   OR (appt->'status'<>'null'::jsonb AND appt->>'status' NOT IN
    ('Scheduled','Confirmed','Checked Out','Cancelled','With Doctor','In Room','Checked In','In Room - Vitals Taken','Not Seen','Billed'))
  THEN RETURN false; END IF;
  seen:=array_append(seen,row->>'handle');
  seen_ids:=array_append(seen_ids,appt->>'appointment_id');
  IF r.kind='window' THEN
   item:=pub->'items'->count_items;
   IF NOT public.finance_settings_keys(item,ARRAY['handle','sha256','starts_at','ends_at','status','selectable'])
    OR patient<>'null'::jsonb OR jsonb_typeof(item->'selectable') IS DISTINCT FROM 'boolean'
    OR (item->>'selectable')::boolean IS DISTINCT FROM (appt->'patient_id'<>'null'::jsonb AND appt->'deleted_at'='null'::jsonb
     AND appt->'status'<>'null'::jsonb AND appt->>'status'<>'Cancelled')
    OR item->>'sha256' IS DISTINCT FROM public.google_calendar_json_digest(jsonb_build_object('kind','ehr_window_item.v1','item',item-'sha256'))
   THEN RETURN false; END IF;
  ELSE
   item:=pub->'item';
   SELECT value INTO parent_item FROM public.ehr_read_snapshots z,
    jsonb_array_elements(z.payload->'private'->'items') WHERE z.id=r.parent_snapshot_id AND value->>'handle'=row->>'handle';
   IF NOT public.finance_settings_keys(item,ARRAY['handle','sha256','starts_at','ends_at','status','patient'])
    OR NOT public.finance_settings_keys(patient,ARRAY['patient_id','first_name','last_name','birth_date','primary_physician_id','deleted_at'])
    OR NOT public.ehr_read_provider_id(patient->'patient_id') OR NOT public.ehr_read_provider_id(patient->'primary_physician_id')
    OR NOT public.ehr_read_text(patient->'first_name',70) OR NOT public.ehr_read_text(patient->'last_name',70)
    OR NOT public.google_calendar_date(patient->'birth_date') OR patient->'deleted_at'<>'null'::jsonb
    OR appt->'deleted_at'<>'null'::jsonb OR appt->'patient_id' IS DISTINCT FROM patient->'patient_id'
    OR appt->'status'='null'::jsonb OR appt->>'status'='Cancelled'
    OR parent_item IS NULL OR parent_item->'appointment' IS DISTINCT FROM appt
    OR item->'patient' IS DISTINCT FROM (patient-'patient_id'-'primary_physician_id'-'deleted_at')
    OR item->>'sha256' IS DISTINCT FROM public.google_calendar_json_digest(jsonb_build_object('kind','ehr_verified_item.v1','item',item-'sha256'))
   THEN RETURN false; END IF;
  END IF;
  IF item->>'handle' IS DISTINCT FROM row->>'handle' OR (item->'starts_at',item->'ends_at',item->'status')
   IS DISTINCT FROM (appt->'starts_at',appt->'ends_at',appt->'status') THEN RETURN false; END IF;
  count_items:=count_items+1;
 END LOOP;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.ehr_read_snapshot_valid(sid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_read_snapshots z JOIN public.ehr_read_requests r ON r.id=z.observation_id
  WHERE z.id=sid AND (z.box_id,z.owner_id)=(r.box_id,r.owner_id)
   AND r.request_hash=public.google_calendar_json_digest(r.request_json)
   AND public.ehr_read_payload_valid(z.payload,r) AND z.payload_sha256=public.google_calendar_json_digest(z.payload)
   AND z.source_sha256=public.google_calendar_json_digest(jsonb_build_object('observation_id',r.id,
    'request_sha256',r.request_hash,'binding_sha256',r.binding_digest,'payload_sha256',z.payload_sha256,
    'valid_until',public.google_calendar_stamp(r.valid_until))))
$$;
CREATE FUNCTION public.guard_ehr_read_snapshot() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r public.ehr_read_requests;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'EHR snapshots are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM public.ehr_read_requests WHERE id=NEW.observation_id;
 PERFORM 1 FROM public.principals WHERE (id,box_id)=(NEW.owner_id,NEW.box_id) FOR UPDATE;
 PERFORM 1 FROM public.external_identities WHERE id=r.account_id FOR SHARE;
 PERFORM 1 FROM public.ehr_read_bindings WHERE id=r.binding_id FOR UPDATE;
 IF r.id IS NULL OR (r.box_id,r.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NOT public.ehr_read_request_current(r.id)
 THEN RAISE EXCEPTION 'EHR snapshot authority invalid' USING ERRCODE='23514'; END IF;
 IF NOT public.ehr_read_payload_valid(NEW.payload,r)
 THEN RAISE EXCEPTION 'EHR snapshot payload invalid' USING ERRCODE='23514'; END IF;
 IF NEW.payload_sha256 IS DISTINCT FROM public.google_calendar_json_digest(NEW.payload)
 THEN RAISE EXCEPTION 'EHR snapshot payload commitment invalid' USING ERRCODE='23514'; END IF;
 IF NEW.source_sha256 IS DISTINCT FROM public.google_calendar_json_digest(jsonb_build_object('observation_id',r.id,
   'request_sha256',r.request_hash,'binding_sha256',r.binding_digest,'payload_sha256',NEW.payload_sha256,
   'valid_until',public.google_calendar_stamp(r.valid_until)))
 THEN RAISE EXCEPTION 'EHR snapshot source commitment invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ehr_read_snapshot_guard BEFORE INSERT OR UPDATE OR DELETE ON public.ehr_read_snapshots
 FOR EACH ROW EXECUTE FUNCTION public.guard_ehr_read_snapshot();

CREATE FUNCTION public.ehr_read_source_content(pub jsonb) RETURNS text
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT 'Elation selected visit (synthetic frozen observation)'||chr(10)
  ||'Practice: '||(pub->'practice'->>'label')||chr(10)
  ||'Patient: '||(pub->'item'->'patient'->>'first_name')||' '||(pub->'item'->'patient'->>'last_name')||chr(10)
  ||'Birth date: '||(pub->'item'->'patient'->>'birth_date')||chr(10)
  ||'Starts: '||(pub->'item'->>'starts_at')||chr(10)||'Ends: '||(pub->'item'->>'ends_at')||chr(10)
  ||'Appointment status: '||coalesce(pub->'item'->>'status','not provided')||chr(10)
  ||'Observed: '||(pub->>'observed_at')||chr(10)||'Coverage: '
  ||CASE WHEN pub->>'coverage'='more_rows_available' THEN 'Showing this page; more appointments may be available.'
   ELSE 'Showing the returned page.' END||chr(10)||chr(10)
  ||'This reviewed snapshot does not book or update the EHR.'
$$;
CREATE FUNCTION public.ehr_read_source_valid(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.ehr_read_source_reviews v
  JOIN public.workspace_entries e ON e.id=v.entry_id
  JOIN public.encounter_workspaces w ON w.id=v.workspace_id
  JOIN public.ehr_read_snapshots z ON z.id=v.snapshot_id
  JOIN public.ehr_read_requests r ON r.id=z.observation_id
  WHERE e.id=eid AND e.kind='ehr_read_source' AND r.kind='verify'
   AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)
    =(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
   AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
   AND (r.box_id,r.owner_id,z.box_id,z.owner_id)=(v.box_id,v.owner_id,v.box_id,v.owner_id)
   AND public.ehr_read_snapshot_valid(z.id) AND v.workspace_revision=v.expected_revision+1
   AND v.reviewed_visit AND v.reviewed_patient_identity AND v.reviewed_exact_snapshot AND v.reviewed_untrusted_source
   AND v.item_handle=r.item_handle AND z.payload->'public'->'item'->>'handle'=v.item_handle::text
   AND v.item_sha256=z.payload->'public'->'item'->>'sha256' AND v.observation_sha256=z.source_sha256
   AND v.source_sha256=public.google_calendar_json_digest(jsonb_build_object('observation_sha256',v.observation_sha256,
    'item_handle',v.item_handle,'item_sha256',v.item_sha256))
   AND v.request_hash=public.google_calendar_json_digest(jsonb_build_object('workspace_id',v.workspace_id,
    'expected_revision',v.expected_revision,'idempotency_key',v.idempotency_key,'observation_id',r.id,
    'observation_sha256',v.observation_sha256,'item_handle',v.item_handle,'item_sha256',v.item_sha256,
    'reviewed_visit',v.reviewed_visit,'reviewed_patient_identity',v.reviewed_patient_identity,
    'reviewed_exact_snapshot',v.reviewed_exact_snapshot,'reviewed_untrusted_source',v.reviewed_untrusted_source))
   AND e.content=public.ehr_read_source_content(z.payload->'public') AND e.source_label='Elation: reviewed appointment'
   AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex') AND v.valid_until=r.valid_until)
$$;
CREATE FUNCTION public.ehr_read_source_current(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.ehr_read_source_valid(eid) AND EXISTS(SELECT 1 FROM public.ehr_read_source_reviews v
  JOIN public.ehr_read_snapshots z ON z.id=v.snapshot_id
  WHERE v.entry_id=eid AND public.ehr_read_request_current(z.observation_id) AND v.valid_until>clock_timestamp())
$$;
CREATE FUNCTION public.guard_ehr_read_review() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE w public.encounter_workspaces; z public.ehr_read_snapshots; r public.ehr_read_requests;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'EHR source reviews are immutable' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM public.principals WHERE (id,box_id)=(NEW.owner_id,NEW.box_id) FOR UPDATE;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 SELECT * INTO z FROM public.ehr_read_snapshots WHERE id=NEW.snapshot_id;
 SELECT * INTO r FROM public.ehr_read_requests WHERE id=z.observation_id;
 PERFORM 1 FROM public.external_identities WHERE id=r.account_id FOR SHARE;
 PERFORM 1 FROM public.ehr_read_bindings WHERE id=r.binding_id FOR UPDATE;
 IF w.id IS NULL OR z.id IS NULL OR r.id IS NULL OR r.kind<>'verify'
  OR (w.box_id,w.owner_id,w.patient_link_id,w.revision) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.patient_link_id,NEW.workspace_revision)
  OR NOT public.ehr_read_request_current(r.id) OR NEW.valid_until IS DISTINCT FROM r.valid_until
  OR NEW.valid_until<=clock_timestamp() OR NOT public.ehr_read_snapshot_valid(z.id)
 THEN RAISE EXCEPTION 'EHR source review authority invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ehr_read_review_guard BEFORE INSERT OR UPDATE OR DELETE ON public.ehr_read_source_reviews
 FOR EACH ROW EXECUTE FUNCTION public.guard_ehr_read_review();
CREATE FUNCTION public.guard_ehr_read_entry() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_TABLE_NAME='workspace_entries' THEN
  IF NEW.kind='ehr_read_source' AND NOT public.ehr_read_source_valid(NEW.id)
   THEN RAISE EXCEPTION 'Exact EHR source review required' USING ERRCODE='23514'; END IF;
 ELSE
  IF NOT public.ehr_read_source_valid(NEW.entry_id)
   THEN RAISE EXCEPTION 'EHR source review commitment invalid' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER ehr_read_entry_guard AFTER INSERT ON public.workspace_entries
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_ehr_read_entry();
CREATE CONSTRAINT TRIGGER ehr_read_review_commitment_guard AFTER INSERT ON public.ehr_read_source_reviews
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_ehr_read_entry();
"""
