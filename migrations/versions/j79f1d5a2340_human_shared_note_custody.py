"""Exact human-shared saved-note custody for immutable private draft reviews."""

from importlib import import_module

from alembic import op

revision = "j79f1d5a2340"
down_revision = "e3a90d77b812"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(HELPERS)
    # Reuse the frozen prior guard, preserving every existing connector and
    # human/agent check. Each exact replacement fails migration on drift.
    frozen = import_module("migrations.versions.h68e0c4f1239_fax_reviewed_source")
    prior = frozen.HANDOFF_GUARDS
    for before, after in REVIEW_EXTENSIONS:
        if prior.count(before) != 1:
            raise RuntimeError("Prior immutable handoff guard differs from the reviewed extension")
        prior = prior.replace(before, after)
    op.execute(prior)
    prior = frozen.MODEL_GUARDS
    for before, after in MODEL_EXTENSIONS:
        if prior.count(before) != 1:
            raise RuntimeError("Prior model source guard differs from the reviewed extension")
        prior = prior.replace(before, after)
    op.execute(prior)
    op.execute(ENTRY_GUARD)


def downgrade():
    raise RuntimeError("Retain immutable human-shared note custody and review history")


HELPERS = r"""
CREATE FUNCTION public.clinical_note_ascii_canonical(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT coalesce(string_agg(CASE WHEN ascii(c)<127 THEN c
  WHEN ascii(c)<=65535 THEN chr(92)||'u'||lpad(to_hex(ascii(c)),4,'0')
  ELSE chr(92)||'u'||lpad(to_hex(55296+(ascii(c)-65536)/1024),4,'0')||
   chr(92)||'u'||lpad(to_hex(56320+(ascii(c)-65536)%1024),4,'0') END,'' ORDER BY ordinal),'')
 FROM regexp_split_to_table(public.vendor_public_canonical(value),'') WITH ORDINALITY parts(c,ordinal)
$$;
CREATE FUNCTION public.clinical_note_fingerprint(wid uuid, at_revision integer) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT encode(sha256(convert_to(public.clinical_note_ascii_canonical(coalesce(jsonb_agg(
  jsonb_build_object('id',e.id::text,'revision',e.revision,'content',e.content) ORDER BY e.revision),'[]'::jsonb)),'UTF8')),'hex')
 FROM public.workspace_entries e WHERE e.workspace_id=wid AND e.revision<=at_revision
  AND (e.kind IN ('evidence','synthetic_source') OR (e.kind='scratchpad' AND e.revision=(
   SELECT max(revision) FROM public.workspace_entries WHERE workspace_id=wid AND kind='scratchpad' AND revision<=at_revision)))
$$;
CREATE FUNCTION public.clinical_note_source_valid(eid uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE e public.workspace_entries; n public.workspace_notes; value jsonb; request jsonb; expected jsonb;
BEGIN
 SELECT * INTO e FROM public.workspace_entries WHERE id=eid;
 IF e.id IS NULL OR e.kind<>'conversation' OR e.source_label IS DISTINCT FROM 'Human-shared saved note'
  OR EXISTS(SELECT 1 FROM public.workspace_replies WHERE entry_id=eid) THEN RETURN false; END IF;
 value:=e.content::jsonb; request:=value->'request';
 IF jsonb_typeof(value) IS DISTINCT FROM 'object' OR jsonb_typeof(request) IS DISTINCT FROM 'object'
  OR request-ARRAY['expected_revision','idempotency_key','note_id','note_version','content_hash','source_fingerprint','share_with_team']<>'{}'::jsonb
  OR request->'share_with_team' IS DISTINCT FROM 'true'::jsonb
  OR request->'expected_revision' IS DISTINCT FROM to_jsonb(e.revision-1)
  OR request->>'idempotency_key' IS DISTINCT FROM e.idempotency_key THEN RETURN false; END IF;
 SELECT * INTO n FROM public.workspace_notes WHERE id::text=request->>'note_id';
 IF n.id IS NULL OR (n.workspace_id,n.box_id,n.owner_id) IS DISTINCT FROM (e.workspace_id,e.box_id,e.actor_id)
  OR n.workspace_revision>=e.revision OR request->'note_version' IS DISTINCT FROM to_jsonb(n.version)
  OR request->>'content_hash' IS DISTINCT FROM n.content_hash OR request->>'source_fingerprint' IS DISTINCT FROM n.source_fingerprint
  OR n.content_hash IS DISTINCT FROM encode(sha256(convert_to(public.clinical_note_ascii_canonical(jsonb_build_object('content',n.content)),'UTF8')),'hex')
  OR n.source_fingerprint IS DISTINCT FROM public.clinical_note_fingerprint(n.workspace_id,n.source_revision)
  OR e.request_hash IS DISTINCT FROM encode(sha256(convert_to(public.clinical_note_ascii_canonical(
   jsonb_build_object('contract','clinical-note-team-source.v1','request',request)),'UTF8')),'hex') THEN RETURN false; END IF;
 expected:=jsonb_build_object('contract','clinical-note-team-source.v1','request',request,'note',jsonb_build_object(
  'id',n.id::text,'version',n.version,'content_hash',n.content_hash,'source_fingerprint',n.source_fingerprint,'content',n.content));
 RETURN value=expected AND e.content=public.clinical_note_ascii_canonical(expected);
EXCEPTION WHEN invalid_text_representation OR data_exception THEN RETURN false;
END $$;
CREATE FUNCTION public.clinical_note_source_current(eid uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE e public.workspace_entries; w public.encounter_workspaces; n public.workspace_notes;
BEGIN
 IF NOT public.clinical_note_source_valid(eid) THEN RETURN false; END IF;
 SELECT * INTO e FROM public.workspace_entries WHERE id=eid;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=e.workspace_id;
 SELECT * INTO n FROM public.workspace_notes WHERE workspace_id=w.id ORDER BY version DESC LIMIT 1;
 RETURN w.appointment_id IS NOT NULL AND n.id::text=e.content::jsonb->'request'->>'note_id'
  AND n.source_fingerprint=public.clinical_note_fingerprint(w.id,w.revision)
  AND e.revision=(SELECT max(revision) FROM public.workspace_entries WHERE workspace_id=w.id
   AND kind='conversation' AND source_label='Human-shared saved note'
   AND CASE WHEN public.clinical_note_source_valid(id) THEN content::jsonb->'request'->>'note_id' END=n.id::text);
END $$;
CREATE FUNCTION public.clinical_note_source_content(eid uuid) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE value jsonb;
BEGIN
 IF NOT public.clinical_note_source_valid(eid) THEN RETURN NULL; END IF;
 SELECT content::jsonb->'note' INTO value FROM public.workspace_entries WHERE id=eid;
 RETURN 'Human-shared saved note · version '||(value->>'version')||chr(10)||
  'Saved private note snapshot; not clinical sign-off or a current chart read.'||chr(10)||chr(10)||(value->>'content');
END $$;
REVOKE ALL ON FUNCTION public.clinical_note_ascii_canonical(jsonb),public.clinical_note_fingerprint(uuid,integer),
 public.clinical_note_source_valid(uuid),public.clinical_note_source_current(uuid),public.clinical_note_source_content(uuid) FROM PUBLIC;
"""

REVIEW_EXTENSIONS = (
    ("'efax_inbound_source','fax_inbound_source') THEN 'evidence' ELSE kind END,'sha256',encode(sha256(convert_to(content,'UTF8')),'hex')",
     "'efax_inbound_source','fax_inbound_source','conversation') THEN 'evidence' ELSE kind END,'sha256',encode(sha256(convert_to(CASE WHEN kind='conversation' THEN public.clinical_note_source_content(id) ELSE content END,'UTF8')),'hex')"),
    ("(kind='fax_inbound_source' AND public.fax_inbound_source_current(e.id))) AND bot->>'include_evidence'='true'",
     "(kind='fax_inbound_source' AND public.fax_inbound_source_current(e.id)) OR (kind='conversation' AND public.clinical_note_source_current(e.id))) AND bot->>'include_evidence'='true'"),
    ("'efax_inbound_source','fax_inbound_source') THEN 'evidence' ELSE source_entry.kind END)",
     "'efax_inbound_source','fax_inbound_source','conversation') THEN 'evidence' ELSE source_entry.kind END)"),
    ("OR (source_entry.kind='fax_inbound_source' AND NOT public.fax_inbound_source_current(source_entry.id))",
     "OR (source_entry.kind='fax_inbound_source' AND NOT public.fax_inbound_source_current(source_entry.id))\n   OR (source_entry.kind='conversation' AND NOT public.clinical_note_source_current(source_entry.id))"),
    ("encode(sha256(convert_to(source_entry.content,'UTF8')),'hex')",
     "encode(sha256(convert_to(CASE WHEN source_entry.kind='conversation' THEN public.clinical_note_source_content(source_entry.id) ELSE source_entry.content END,'UTF8')),'hex')"),
)

ENTRY_GUARD = r"""
CREATE FUNCTION public.guard_clinical_note_source() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.source_label='Human-shared saved note' AND (NOT public.clinical_note_source_current(NEW.id)
  OR NEW.revision IS DISTINCT FROM (SELECT revision FROM public.encounter_workspaces WHERE id=NEW.workspace_id))
 THEN RAISE EXCEPTION 'exact current human saved-note sharing required' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER clinical_note_source_guard AFTER INSERT ON public.workspace_entries
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_clinical_note_source();
REVOKE ALL ON FUNCTION public.guard_clinical_note_source() FROM PUBLIC;
"""

MODEL_EXTENSIONS = (
    (" ordinary boolean;", " ordinary boolean; clinical_request jsonb; clinical_entry public.workspace_entries;"),
    ("IF entry.kind IN ('google_message','google_calendar','efax_inbound_source','fax_inbound_source') THEN",
     "IF entry.kind IN ('google_message','google_calendar','efax_inbound_source','fax_inbound_source')\n"
     "   OR entry.source_label='Human-shared saved note' OR source->>'label'='Human-shared saved note' THEN"),
    ("OR source->>'content' IS DISTINCT FROM entry.content",
     "OR source->>'content' IS DISTINCT FROM (CASE WHEN entry.kind='conversation' THEN public.clinical_note_source_content(entry.id) ELSE entry.content END)\n"
     "    OR ((entry.source_label='Human-shared saved note' OR source->>'label'='Human-shared saved note') AND\n"
     "      (entry.kind IS DISTINCT FROM 'conversation' OR NOT public.clinical_note_source_current(entry.id)\n"
     "       OR source-ARRAY['entry_id','revision','kind','label','content']<>'{}'::jsonb))"),
    ("IF entry.kind IN ('efax_inbound_source','fax_inbound_source') AND NOT EXISTS (",
     "IF (entry.kind IN ('efax_inbound_source','fax_inbound_source') OR entry.source_label='Human-shared saved note'\n"
     "     OR descriptor->>'label'='Human-shared saved note') AND NOT EXISTS ("),
    ("AND descriptor->>'sha256'=encode(sha256(convert_to(entry.content,'UTF8')),'hex')",
     "AND descriptor->>'sha256'=encode(sha256(convert_to(CASE WHEN entry.kind='conversation' THEN public.clinical_note_source_content(entry.id) ELSE entry.content END,'UTF8')),'hex')\n"
     "       AND ((entry.source_label IS DISTINCT FROM 'Human-shared saved note' AND descriptor->>'label' IS DISTINCT FROM 'Human-shared saved note') OR\n"
     "         (entry.source_label='Human-shared saved note' AND entry.kind='conversation' AND public.clinical_note_source_current(entry.id)\n"
     "          AND selected->>'kind'='evidence' AND selected->>'label'=entry.source_label\n"
     "          AND (NOT descriptor ? 'kind' OR descriptor->>'kind'='evidence')\n"
     "          AND (NOT descriptor ? 'label' OR descriptor->>'label'=entry.source_label)))"),
    (" RETURN true;", r"""
 -- A Chief request binds its source even if every optional descriptor is omitted.
 -- Ordinary conversation text remains valid when it is not JSON.
 BEGIN
  clinical_request:=(m.request_body->>'content')::jsonb;
 EXCEPTION WHEN data_exception THEN clinical_request:=NULL;
 END;
 IF clinical_request->>'contract'='clinical-team-drafts.request.v1' THEN
  SELECT * INTO clinical_entry FROM public.workspace_entries WHERE id::text=clinical_request->>'source_entry_id';
  IF NOT ordinary OR m.prepared_envelope->'context'->>'role' IS DISTINCT FROM 'chief'
   OR clinical_request-ARRAY['contract','source_entry_id','note_id','note_version','content_hash']<>'{}'::jsonb
   OR clinical_entry.id IS NULL OR NOT public.clinical_note_source_current(clinical_entry.id)
   OR (clinical_entry.workspace_id,clinical_entry.box_id,clinical_entry.actor_id) IS DISTINCT FROM (m.workspace_id,m.box_id,m.owner_id)
  THEN RETURN false; END IF;
  -- Only an already verified canonical snapshot may be parsed below.
  IF clinical_request->'note_id' IS DISTINCT FROM clinical_entry.content::jsonb->'note'->'id'
   OR clinical_request->'note_version' IS DISTINCT FROM clinical_entry.content::jsonb->'note'->'version'
   OR clinical_request->'content_hash' IS DISTINCT FROM clinical_entry.content::jsonb->'note'->'content_hash'
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(m.prepared_envelope->'context'->'sources') bound_source(value)
      WHERE bound_source.value->>'entry_id'=clinical_entry.id::text)
  THEN RETURN false; END IF;
 END IF;
 RETURN true;"""),
)
