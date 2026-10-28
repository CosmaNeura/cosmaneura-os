"""Reviewed Google Calendar summaries for private notebooks, never implicit visits.

The original clinical review table and its NOT NULL patient/acknowledgment guards
remain unchanged. Private commitments require an unlinked notebook at both
write-time and every later model/source-use validation.
"""
from alembic import op

revision = "y24f0a87c631"
down_revision = "x13d9ec7654"
branch_labels = None
depends_on = None

TABLES = r"""
CREATE TABLE google_calendar_private_source_reviews (
	id UUID NOT NULL,
	entry_id UUID NOT NULL,
	snapshot_id UUID NOT NULL,
	expected_revision INTEGER NOT NULL,
	workspace_revision INTEGER NOT NULL,
	idempotency_key VARCHAR(100) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	observation_sha256 VARCHAR(64) NOT NULL,
	event_id VARCHAR(1024) NOT NULL,
	event_sha256 VARCHAR(64) NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	valid_until TIMESTAMP WITH TIME ZONE NOT NULL,
	reviewed_private_notebook BOOLEAN NOT NULL,
	reviewed_exact_summary BOOLEAN NOT NULL,
	reviewed_untrusted_source BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	workspace_id UUID NOT NULL,
	box_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id),
	FOREIGN KEY(entry_id, workspace_id, box_id) REFERENCES workspace_entries (id, workspace_id, box_id),
	FOREIGN KEY(snapshot_id, box_id, owner_id) REFERENCES google_calendar_snapshots (id, box_id, owner_id),
	CONSTRAINT uq_google_calendar_private_review_entry UNIQUE (entry_id),
	CONSTRAINT uq_google_calendar_private_review_event UNIQUE (workspace_id, snapshot_id, event_id),
	CONSTRAINT uq_google_calendar_private_review_key UNIQUE (workspace_id, idempotency_key),
	CONSTRAINT ck_google_calendar_private_review_revision CHECK (expected_revision>=1 AND workspace_revision=expected_revision+1),
	CONSTRAINT ck_google_calendar_private_review_checks CHECK (reviewed_private_notebook AND reviewed_exact_summary AND reviewed_untrusted_source),
	CONSTRAINT ck_google_calendar_private_review_event CHECK (event_id ~ '^[A-Za-z0-9_-]+$' AND char_length(event_id) BETWEEN 1 AND 1024),
	CHECK (request_hash ~ '^[a-f0-9]{64}$' AND observation_sha256 ~ '^[a-f0-9]{64}$' AND event_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$' AND content_sha256 ~ '^[a-f0-9]{64}$')
)

;
"""

SQL = r"""
CREATE FUNCTION public.google_calendar_private_source_valid(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.google_calendar_private_source_reviews v
  JOIN public.workspace_entries e ON e.id=v.entry_id JOIN public.encounter_workspaces w ON w.id=v.workspace_id
  JOIN public.google_calendar_snapshots z ON z.id=v.snapshot_id JOIN public.google_calendar_observation_requests r ON r.id=z.observation_id
  CROSS JOIN LATERAL jsonb_array_elements(z.payload->'items') item
  WHERE e.id=eid AND e.kind='google_calendar' AND item->>'id'=v.event_id
   AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)
    =(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
   AND (w.box_id,w.owner_id)=(v.box_id,v.owner_id)
   AND w.appointment_id IS NULL AND w.patient_link_id IS NULL AND w.draft_title IS NOT NULL
   AND (r.box_id,r.owner_id)=(v.box_id,v.owner_id) AND (z.box_id,z.owner_id)=(v.box_id,v.owner_id)
   AND public.google_calendar_snapshot_valid(z.id) AND v.workspace_revision=v.expected_revision+1
   AND v.reviewed_private_notebook AND v.reviewed_exact_summary AND v.reviewed_untrusted_source
   AND v.observation_sha256=z.source_sha256 AND v.event_sha256=public.google_calendar_json_digest(item)
   AND v.source_sha256=public.google_calendar_json_digest(jsonb_build_object('observation_sha256',v.observation_sha256,'event_id',v.event_id,'event_sha256',v.event_sha256))
   AND v.request_hash=public.google_calendar_json_digest(jsonb_build_object('workspace_id',v.workspace_id,'expected_revision',v.expected_revision,
     'idempotency_key',v.idempotency_key,'observation_id',r.id,'observation_sha256',v.observation_sha256,'event_id',v.event_id,
     'event_sha256',v.event_sha256,'reviewed_private_notebook',v.reviewed_private_notebook,'reviewed_exact_summary',v.reviewed_exact_summary,'reviewed_untrusted_source',v.reviewed_untrusted_source))
   AND e.content=public.google_calendar_source_content(z.payload,item)
   AND e.source_label=left('Google calendar: '||(item->>'subject'),160)
   AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex')
   AND v.valid_until=public.google_calendar_valid_until(z.payload,item))
$$;

CREATE OR REPLACE FUNCTION public.google_calendar_source_valid(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.google_calendar_source_reviews v
  JOIN public.workspace_entries e ON e.id=v.entry_id JOIN public.encounter_workspaces w ON w.id=v.workspace_id
  JOIN public.google_calendar_snapshots z ON z.id=v.snapshot_id JOIN public.google_calendar_observation_requests r ON r.id=z.observation_id
  CROSS JOIN LATERAL jsonb_array_elements(z.payload->'items') item
  WHERE e.id=eid AND e.kind='google_calendar' AND item->>'id'=v.event_id
   AND (e.workspace_id,e.box_id,e.actor_id,e.revision,e.request_hash,e.idempotency_key)
    =(v.workspace_id,v.box_id,v.owner_id,v.workspace_revision,v.request_hash,v.idempotency_key)
   AND (w.box_id,w.owner_id,w.patient_link_id)=(v.box_id,v.owner_id,v.patient_link_id)
   AND (r.box_id,r.owner_id)=(v.box_id,v.owner_id) AND (z.box_id,z.owner_id)=(v.box_id,v.owner_id)
   AND public.google_calendar_snapshot_valid(z.id) AND v.workspace_revision=v.expected_revision+1
   AND v.reviewed_visit AND v.reviewed_exact_summary AND v.reviewed_untrusted_source
   AND v.observation_sha256=z.source_sha256 AND v.event_sha256=public.google_calendar_json_digest(item)
   AND v.source_sha256=public.google_calendar_json_digest(jsonb_build_object('observation_sha256',v.observation_sha256,'event_id',v.event_id,'event_sha256',v.event_sha256))
   AND v.request_hash=public.google_calendar_json_digest(jsonb_build_object('workspace_id',v.workspace_id,'expected_revision',v.expected_revision,
     'idempotency_key',v.idempotency_key,'observation_id',r.id,'observation_sha256',v.observation_sha256,'event_id',v.event_id,
     'event_sha256',v.event_sha256,'reviewed_visit',v.reviewed_visit,'reviewed_exact_summary',v.reviewed_exact_summary,'reviewed_untrusted_source',v.reviewed_untrusted_source))
   AND e.content=public.google_calendar_source_content(z.payload,item)
   AND e.source_label=left('Google calendar: '||(item->>'subject'),160)
   AND v.content_sha256=encode(sha256(convert_to(e.content,'UTF8')),'hex')
   AND v.valid_until=public.google_calendar_valid_until(z.payload,item))
 OR public.google_calendar_private_source_valid(eid)
$$;

CREATE OR REPLACE FUNCTION public.google_calendar_source_current(eid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.google_calendar_source_valid(eid) AND (EXISTS(SELECT 1 FROM public.google_calendar_source_reviews v
  JOIN public.google_calendar_snapshots z ON z.id=v.snapshot_id JOIN public.google_calendar_observation_requests r ON r.id=z.observation_id
  WHERE v.entry_id=eid AND public.google_calendar_observation_current(r.id) AND v.valid_until>clock_timestamp()
   AND r.window_end>clock_timestamp() AND NOT EXISTS(SELECT 1 FROM public.google_calendar_observation_requests n
    WHERE n.account_id=r.account_id AND n.ordinal>r.ordinal))
 OR EXISTS(SELECT 1 FROM public.google_calendar_private_source_reviews v
  JOIN public.google_calendar_snapshots z ON z.id=v.snapshot_id JOIN public.google_calendar_observation_requests r ON r.id=z.observation_id
  WHERE v.entry_id=eid AND public.google_calendar_observation_current(r.id) AND v.valid_until>clock_timestamp()
   AND r.window_end>clock_timestamp() AND NOT EXISTS(SELECT 1 FROM public.google_calendar_observation_requests n
    WHERE n.account_id=r.account_id AND n.ordinal>r.ordinal))
)
$$;

CREATE FUNCTION public.guard_google_calendar_private_review() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE w public.encounter_workspaces; z public.google_calendar_snapshots; r public.google_calendar_observation_requests;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Private calendar reviews are immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 SELECT * INTO z FROM public.google_calendar_snapshots WHERE id=NEW.snapshot_id;
 SELECT * INTO r FROM public.google_calendar_observation_requests WHERE id=z.observation_id;
 IF w.id IS NULL OR (w.box_id,w.owner_id,w.revision) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.workspace_revision)
  OR w.appointment_id IS NOT NULL OR w.patient_link_id IS NOT NULL OR w.draft_title IS NULL
  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.id=NEW.owner_id AND p.box_id=NEW.box_id
    AND p.principal_type='human' AND p.state='active' AND p.tombstoned_at IS NULL)
  OR z.id IS NULL OR r.id IS NULL OR NOT public.google_calendar_observation_current(r.id) OR NEW.valid_until<=clock_timestamp()
  OR EXISTS(SELECT 1 FROM public.google_calendar_observation_requests n WHERE n.account_id=r.account_id AND n.ordinal>r.ordinal)
  OR EXISTS(SELECT 1 FROM public.google_calendar_source_reviews v WHERE v.entry_id=NEW.entry_id)
 THEN RAISE EXCEPTION 'Private calendar review authority invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER google_calendar_private_review_guard BEFORE INSERT OR UPDATE OR DELETE
 ON public.google_calendar_private_source_reviews FOR EACH ROW EXECUTE FUNCTION public.guard_google_calendar_private_review();
CREATE FUNCTION public.guard_google_calendar_private_commitment() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NOT public.google_calendar_private_source_valid(NEW.entry_id)
 THEN RAISE EXCEPTION 'Private calendar commitment invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER google_calendar_private_commitment_guard AFTER INSERT ON public.google_calendar_private_source_reviews
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_google_calendar_private_commitment();
REVOKE ALL ON FUNCTION public.google_calendar_private_source_valid(uuid), public.guard_google_calendar_private_review(),
 public.guard_google_calendar_private_commitment() FROM PUBLIC;
"""


def upgrade():
    op.execute(TABLES)
    op.execute(SQL)


def downgrade():
    raise RuntimeError("Private calendar review history must be retained")
