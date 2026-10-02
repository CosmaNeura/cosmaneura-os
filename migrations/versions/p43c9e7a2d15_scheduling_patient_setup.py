"""Personal patient correspondence custody; dormant receiver contract only."""

from alembic import op

revision = "p43c9e7a2d15"
down_revision = "g42b8d3f6a10"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)
    op.execute(GUARDS)


def downgrade():
    raise RuntimeError("Retain patient correspondence and human-review history")


TABLES = "\nCREATE TABLE scheduling_patient_setup_requests (\n\tid UUID NOT NULL, \n\texternal_identity_id UUID NOT NULL, \n\taccount_id UUID NOT NULL, \n\tpatient_link_id UUID NOT NULL, \n\tkind VARCHAR(8) NOT NULL, \n\tordinal INTEGER NOT NULL, \n\texpected_revision INTEGER NOT NULL, \n\tidempotency_key UUID NOT NULL, \n\trequest_nonce UUID NOT NULL, \n\tpreview_request_id UUID, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tcommand JSONB NOT NULL, \n\tselection JSONB NOT NULL, \n\tbinding_sha256 VARCHAR(64) NOT NULL, \n\tgrant_sha256 VARCHAR(64) NOT NULL, \n\tconnected_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tsource_context JSONB NOT NULL, \n\tsource_context_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), \n\tFOREIGN KEY(external_identity_id, box_id, owner_id) REFERENCES external_identities (id, box_id, principal_id), \n\tFOREIGN KEY(account_id) REFERENCES scheduling_accounts (id), \n\tFOREIGN KEY(patient_link_id, box_id) REFERENCES patient_links (id, box_id), \n\tFOREIGN KEY(preview_request_id, workspace_id, box_id, owner_id) REFERENCES scheduling_patient_setup_requests (id, workspace_id, box_id, owner_id), \n\tCONSTRAINT uq_patient_setup_request_scope UNIQUE (id, workspace_id, box_id, owner_id), \n\tCONSTRAINT uq_patient_setup_request_key UNIQUE (workspace_id, owner_id, kind, idempotency_key), \n\tCONSTRAINT uq_patient_setup_request_ordinal UNIQUE (account_id, workspace_id, ordinal), \n\tCONSTRAINT ck_patient_setup_request_bounds CHECK (kind IN ('preview','confirm') AND ordinal BETWEEN 1 AND 500 AND expected_revision>=1), \n\tCONSTRAINT ck_patient_setup_request_parent CHECK ((kind='preview' AND preview_request_id IS NULL) OR (kind='confirm' AND preview_request_id IS NOT NULL)), \n\tCONSTRAINT ck_patient_setup_request_time CHECK (isfinite(connected_at) AND isfinite(created_at)), \n\tCHECK (request_sha256 ~ '^[a-f0-9]{64}$' AND binding_sha256 ~ '^[a-f0-9]{64}$' AND grant_sha256 ~ '^[a-f0-9]{64}$' AND source_context_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(command) = 'object' AND octet_length(command::text) <= 4096), \n\tCHECK (jsonb_typeof(selection) = 'object' AND octet_length(selection::text) <= 2048), \n\tCHECK (jsonb_typeof(source_context) = 'object' AND octet_length(source_context::text) <= 4096)\n)\n\n;\n\nCREATE TABLE scheduling_patient_setup_snapshots (\n\tid UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\tpayload JSONB NOT NULL, \n\tpayload_sha256 VARCHAR(64) NOT NULL, \n\tsource_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(request_id, workspace_id, box_id, owner_id) REFERENCES scheduling_patient_setup_requests (id, workspace_id, box_id, owner_id), \n\tCONSTRAINT uq_patient_setup_snapshot_request UNIQUE (request_id), \n\tCONSTRAINT uq_patient_setup_snapshot_scope UNIQUE (id, workspace_id, box_id, owner_id), \n\tCHECK (payload_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 12288), \n\tCONSTRAINT ck_patient_setup_snapshot_time CHECK (isfinite(created_at))\n)\n\n;\n\nCREATE TABLE scheduling_patient_mapping_reviews (\n\tid UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\tsnapshot_id UUID NOT NULL, \n\tmapping_id UUID NOT NULL, \n\tpatient_link_id UUID NOT NULL, \n\treviewed_same_patient BOOLEAN NOT NULL, \n\treviewed_exact_identity BOOLEAN NOT NULL, \n\tmapping_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(request_id, workspace_id, box_id, owner_id) REFERENCES scheduling_patient_setup_requests (id, workspace_id, box_id, owner_id), \n\tFOREIGN KEY(snapshot_id, workspace_id, box_id, owner_id) REFERENCES scheduling_patient_setup_snapshots (id, workspace_id, box_id, owner_id), \n\tFOREIGN KEY(mapping_id, box_id, patient_link_id) REFERENCES scheduling_patient_accounts (id, box_id, patient_link_id), \n\tCONSTRAINT uq_patient_mapping_review_request UNIQUE (request_id), \n\tCONSTRAINT uq_patient_mapping_review_snapshot UNIQUE (snapshot_id), \n\tCONSTRAINT uq_patient_mapping_review_mapping UNIQUE (mapping_id), \n\tCONSTRAINT ck_patient_mapping_review_human CHECK (reviewed_same_patient AND reviewed_exact_identity), \n\tCHECK (mapping_sha256 ~ '^[a-f0-9]{64}$'), \n\tCONSTRAINT ck_patient_mapping_review_time CHECK (isfinite(created_at))\n)\n\n;"


GUARDS = r"""
CREATE FUNCTION public.patient_setup_canonical(value jsonb, depth integer DEFAULT 0) RETURNS text
 LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog AS $$
DECLARE encoded text; kind text:=jsonb_typeof(value);
BEGIN
 IF depth>30 THEN RAISE EXCEPTION 'patient JSON depth exceeded' USING ERRCODE='23514'; END IF;
 IF kind='object' THEN
  IF EXISTS(SELECT 1 FROM jsonb_object_keys(value) k WHERE octet_length(k)<>char_length(k)) THEN
   RAISE EXCEPTION 'patient JSON key invalid' USING ERRCODE='23514'; END IF;
  SELECT '{'||coalesce(string_agg(to_jsonb(key)::text||':'||public.patient_setup_canonical(child,depth+1),',' ORDER BY key COLLATE "C"),'')||'}'
   INTO encoded FROM jsonb_each(value) AS fields(key,child);
 ELSIF kind='array' THEN
  SELECT '['||coalesce(string_agg(public.patient_setup_canonical(child,depth+1),',' ORDER BY ordinal),'')||']'
   INTO encoded FROM jsonb_array_elements(value) WITH ORDINALITY AS elements(child,ordinal);
 ELSIF kind='number' THEN
  encoded:=value::text;
  IF encoded !~ '^-?(0|[1-9][0-9]*)$' OR abs(encoded::numeric)>9007199254740991 THEN
   RAISE EXCEPTION 'patient JSON integer invalid' USING ERRCODE='23514'; END IF;
 ELSE encoded:=value::text;
 END IF;
 RETURN encoded;
END $$;
CREATE FUNCTION public.patient_setup_digest(domain text, value jsonb) RETURNS text
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT encode(sha256(convert_to(public.patient_setup_canonical(jsonb_build_array(domain,value)),'UTF8')),'hex')
$$;
CREATE FUNCTION public.patient_setup_identity_valid(v jsonb) RETURNS boolean
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
BEGIN
 IF NOT public.finance_settings_keys(v,ARRAY['choice_ref','display_name','birth_date','subject_revision','identity_sha256'])
  OR jsonb_typeof(v->'choice_ref') IS DISTINCT FROM 'string' OR v->>'choice_ref' !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  OR jsonb_typeof(v->'display_name') IS DISTINCT FROM 'string' OR char_length(v->>'display_name') NOT BETWEEN 1 AND 120
  OR v->>'display_name'<>btrim(v->>'display_name') OR (v->>'display_name') ~ '[[:cntrl:]]'
  OR jsonb_typeof(v->'subject_revision') IS DISTINCT FROM 'number' OR (v->>'subject_revision') !~ '^[1-9][0-9]*$'
  OR (v->>'subject_revision')::numeric>9007199254740991
  OR (jsonb_typeof(v->'birth_date') IS DISTINCT FROM 'null' AND NOT public.google_calendar_date(v->'birth_date'))
  OR jsonb_typeof(v->'identity_sha256') IS DISTINCT FROM 'string'
  OR v->>'identity_sha256' IS DISTINCT FROM public.patient_setup_digest('cosmas-scheduling-patient-identity.v1',v-'identity_sha256')
 THEN RETURN false; END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.patient_setup_payload_valid(kind text, v jsonb) RETURNS boolean
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE item jsonb; ids text[]:=ARRAY[]::text[]; checked timestamptz; expiry timestamptz;
BEGIN
 IF kind='preview' THEN
  IF NOT public.finance_settings_keys(v,ARRAY['contract_version','request_nonce','practice_id','actor_id','checked_at','lookup_ref','expires_at','choices','more','preview_sha256'])
   OR jsonb_typeof(v->'choices') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'choices')>5
   OR jsonb_typeof(v->'more') IS DISTINCT FROM 'boolean' OR (v->>'more'='true' AND jsonb_array_length(v->'choices')<>5)
   OR NOT public.google_message_aware_time(v->'checked_at')
   OR v->>'preview_sha256' IS DISTINCT FROM public.patient_setup_digest('cosmas-scheduling-patient-preview.v1',v-'preview_sha256')
  THEN RETURN false; END IF;
  checked:=(v->>'checked_at')::timestamptz;
  FOR item IN SELECT value FROM jsonb_array_elements(v->'choices') LOOP
   IF NOT public.patient_setup_identity_valid(item) OR item->>'choice_ref'=ANY(ids) THEN RETURN false; END IF;
   ids:=array_append(ids,item->>'choice_ref');
  END LOOP;
 ELSE
  IF kind<>'confirm' OR NOT public.finance_settings_keys(v,ARRAY['contract_version','request_nonce','practice_id','actor_id','lookup_ref','patient_id','identity','verified_at','expires_at','verification_sha256'])
   OR NOT public.patient_setup_identity_valid(v->'identity') OR NOT public.google_message_aware_time(v->'verified_at')
   OR v->>'verification_sha256' IS DISTINCT FROM public.patient_setup_digest('cosmas-scheduling-patient-verification.v1',v-'verification_sha256')
   OR jsonb_typeof(v->'patient_id') IS DISTINCT FROM 'string' OR v->>'patient_id' !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  THEN RETURN false; END IF;
  checked:=(v->>'verified_at')::timestamptz;
 END IF;
 IF v->>'contract_version' IS DISTINCT FROM '1' OR jsonb_typeof(v->'contract_version') IS DISTINCT FROM 'string'
  OR NOT public.google_message_aware_time(v->'expires_at') THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(jsonb_build_array(v->'request_nonce',v->'practice_id',v->'actor_id',v->'lookup_ref')) LOOP
  IF jsonb_typeof(item) IS DISTINCT FROM 'string' OR (item#>>'{}') !~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$' THEN RETURN false; END IF;
 END LOOP;
 expiry:=(v->>'expires_at')::timestamptz;
 RETURN expiry>checked AND expiry<=checked+interval '5 minutes';
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.patient_setup_source_context(wid uuid) RETURNS jsonb
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('workspace_id',w.id,'patient_link_id',w.patient_link_id,'appointment_id',a.id,
  'appointment_source',a.source,'appointment_ref',a.external_id,'source_owner_id',a.source_owner_id,
  'source_sha256',a.source_sha256,'patient_source_owner_id',p.source_owner_id,
  'patient_source_account_id',p.source_account_id,'patient_state',p.state)
 FROM public.encounter_workspaces w JOIN public.appointment_observations a ON a.id=w.appointment_id
 JOIN public.patient_links p ON p.id=w.patient_link_id WHERE w.id=wid
$$;
CREATE FUNCTION public.patient_setup_request_current(rid uuid, same_revision boolean DEFAULT false) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.scheduling_patient_setup_requests r
  JOIN public.encounter_workspaces w ON (w.id,w.box_id,w.owner_id,w.patient_link_id)=(r.workspace_id,r.box_id,r.owner_id,r.patient_link_id)
  JOIN public.principals h ON h.id=r.owner_id AND h.box_id=r.box_id
  JOIN public.external_identities e ON (e.id,e.box_id,e.principal_id)=(r.external_identity_id,r.box_id,r.owner_id)
  JOIN public.scheduling_accounts a ON a.id=r.account_id AND a.external_identity_id=e.id
  JOIN public.scheduling_login_credentials c ON c.account_id=a.id
  JOIN public.patient_links p ON p.id=w.patient_link_id AND p.box_id=w.box_id
  WHERE r.id=rid AND e.active AND h.principal_type='human' AND h.state='active' AND h.tombstoned_at IS NULL
   AND a.revoked_at IS NULL AND p.revoked_at IS NULL AND p.state='confirmed'
   AND (p.source_owner_id IS NULL OR (p.source_owner_id=r.owner_id AND EXISTS(
    SELECT 1 FROM public.core_capture_accounts ca JOIN public.external_identities ce ON ce.id=ca.external_identity_id
    WHERE ca.id=p.source_account_id AND ca.revoked_at IS NULL AND ce.active AND ce.box_id=p.box_id AND ce.principal_id=r.owner_id)))
   AND c.status='ready' AND c.sealed IS NOT NULL AND c.expires_at>clock_timestamp()
   AND c.binding_digest=r.binding_sha256 AND c.connected_at=r.connected_at
   AND r.selection=jsonb_build_object('box_id',r.box_id,'owner_id',r.owner_id,'practice_id',a.practice_id,
     'expected_actor_id',a.actor_id,'practitioner_id',a.practitioner_id,'location_id',a.location_id,'appointment_type_id',a.appointment_type_id)
   AND r.source_context=public.patient_setup_source_context(w.id) AND (NOT same_revision OR w.revision=r.expected_revision)
   AND NOT EXISTS(SELECT 1 FROM public.scheduling_patient_setup_requests newer WHERE newer.account_id=r.account_id
    AND newer.workspace_id=r.workspace_id AND newer.kind='preview' AND newer.ordinal>
      CASE WHEN r.kind='preview' THEN r.ordinal ELSE (SELECT parent.ordinal FROM public.scheduling_patient_setup_requests parent WHERE parent.id=r.preview_request_id) END))
$$;
CREATE FUNCTION public.patient_setup_snapshot_valid(sid uuid) RETURNS boolean
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE z public.scheduling_patient_setup_snapshots; r public.scheduling_patient_setup_requests; prior public.scheduling_patient_setup_snapshots;
 choice jsonb;
BEGIN
 SELECT * INTO z FROM public.scheduling_patient_setup_snapshots WHERE id=sid;
 SELECT * INTO r FROM public.scheduling_patient_setup_requests WHERE id=z.request_id;
 IF r.id IS NULL OR NOT public.patient_setup_payload_valid(r.kind,z.payload)
  OR (z.workspace_id,z.box_id,z.owner_id) IS DISTINCT FROM (r.workspace_id,r.box_id,r.owner_id)
  OR r.request_sha256 IS DISTINCT FROM public.patient_setup_digest('cosmas-scheduling-patient-command.v1',jsonb_build_object('workspace_id',r.workspace_id,'request',r.command))
  OR r.source_context_sha256 IS DISTINCT FROM public.patient_setup_digest('cosmas-scheduling-patient-context.v1',r.source_context)
  OR (z.payload->>'request_nonce',z.payload->>'practice_id',z.payload->>'actor_id') IS DISTINCT FROM (r.request_nonce::text,r.selection->>'practice_id',r.selection->>'expected_actor_id')
  OR z.payload_sha256 IS DISTINCT FROM public.patient_setup_digest('cosmas-scheduling-patient-payload.v1',z.payload)
  OR z.source_sha256 IS DISTINCT FROM public.patient_setup_digest('cosmas-scheduling-patient-source.v1',jsonb_build_object(
   'request_id',r.id,'request_sha256',r.request_sha256,'account_id',r.account_id,'binding_sha256',r.binding_sha256,
   'connected_at',public.google_calendar_stamp(r.connected_at),'grant_sha256',r.grant_sha256,
   'source_context_sha256',r.source_context_sha256,'payload_sha256',z.payload_sha256))
 THEN RETURN false; END IF;
 IF r.kind='confirm' THEN
  SELECT * INTO prior FROM public.scheduling_patient_setup_snapshots WHERE request_id=r.preview_request_id;
  IF prior.id IS NULL OR NOT public.patient_setup_snapshot_valid(prior.id) OR prior.source_sha256 IS DISTINCT FROM r.command->>'preview_sha256'
   OR r.command->>'preview_id' IS DISTINCT FROM r.preview_request_id::text OR prior.payload->>'lookup_ref' IS DISTINCT FROM z.payload->>'lookup_ref' THEN RETURN false; END IF;
  SELECT value INTO choice FROM jsonb_array_elements(prior.payload->'choices') WHERE value->>'choice_ref'=r.command->>'choice_ref';
  IF choice IS NULL OR choice IS DISTINCT FROM z.payload->'identity' OR choice->>'identity_sha256' IS DISTINCT FROM r.command->>'identity_sha256' THEN RETURN false; END IF;
 END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.guard_patient_setup_request() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE w public.encounter_workspaces; a public.scheduling_accounts; e public.external_identities; c public.scheduling_login_credentials;
 parent public.scheduling_patient_setup_requests; prior public.scheduling_patient_setup_snapshots;
 h public.principals; p public.patient_links; newest integer; choice jsonb;
BEGIN
 SELECT * INTO h FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR SHARE;
 SELECT * INTO w FROM public.encounter_workspaces WHERE id=NEW.workspace_id FOR SHARE;
 SELECT * INTO e FROM public.external_identities WHERE id=NEW.external_identity_id FOR SHARE;
 SELECT * INTO a FROM public.scheduling_accounts WHERE id=NEW.account_id FOR SHARE;
 SELECT * INTO c FROM public.scheduling_login_credentials WHERE account_id=a.id FOR SHARE;
 SELECT * INTO p FROM public.patient_links WHERE id=NEW.patient_link_id FOR SHARE;
 SELECT coalesce(max(ordinal),0)+1 INTO newest FROM public.scheduling_patient_setup_requests WHERE account_id=NEW.account_id AND workspace_id=NEW.workspace_id;
 IF h.id IS NULL OR h.principal_type<>'human' OR h.state<>'active' OR h.tombstoned_at IS NOT NULL
  OR (w.box_id,w.owner_id,w.patient_link_id,w.revision) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.patient_link_id,NEW.expected_revision)
  OR e.id IS NULL OR NOT e.active OR (e.box_id,e.principal_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR a.id IS NULL OR a.revoked_at IS NOT NULL OR a.external_identity_id IS DISTINCT FROM NEW.external_identity_id
  OR p.id IS NULL OR p.state<>'confirmed' OR p.revoked_at IS NOT NULL OR (p.source_owner_id IS NOT NULL AND p.source_owner_id<>NEW.owner_id)
  OR (p.source_owner_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.core_capture_accounts ca
   JOIN public.external_identities ce ON ce.id=ca.external_identity_id WHERE ca.id=p.source_account_id
   AND ca.revoked_at IS NULL AND ce.active AND ce.box_id=p.box_id AND ce.principal_id=NEW.owner_id))
  OR c.status IS DISTINCT FROM 'ready' OR c.sealed IS NULL OR c.expires_at<=clock_timestamp()
  OR c.binding_digest IS DISTINCT FROM NEW.binding_sha256 OR c.connected_at IS DISTINCT FROM NEW.connected_at
  OR NEW.ordinal<>newest OR NEW.source_context IS DISTINCT FROM public.patient_setup_source_context(w.id)
  OR NEW.source_context_sha256 IS DISTINCT FROM public.patient_setup_digest('cosmas-scheduling-patient-context.v1',NEW.source_context)
  OR NEW.selection IS DISTINCT FROM jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id,'practice_id',a.practice_id,
   'expected_actor_id',a.actor_id,'practitioner_id',a.practitioner_id,'location_id',a.location_id,'appointment_type_id',a.appointment_type_id)
  OR NEW.request_sha256 IS DISTINCT FROM public.patient_setup_digest('cosmas-scheduling-patient-command.v1',jsonb_build_object('workspace_id',NEW.workspace_id,'request',NEW.command))
  OR NEW.command->>'action' IS DISTINCT FROM NEW.kind OR NEW.command->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key::text
  OR NEW.command->>'expected_revision' IS DISTINCT FROM NEW.expected_revision::text
  OR jsonb_typeof(NEW.command->'action') IS DISTINCT FROM 'string'
  OR jsonb_typeof(NEW.command->'idempotency_key') IS DISTINCT FROM 'string'
  OR jsonb_typeof(NEW.command->'expected_revision') IS DISTINCT FROM 'number'
  OR (NEW.command->>'expected_revision') !~ '^[1-9][0-9]*$'
 THEN RAISE EXCEPTION 'invalid patient setup request' USING ERRCODE='23514'; END IF;
 IF NEW.kind='preview' THEN
  IF NOT public.finance_settings_keys(NEW.command,ARRAY['action','expected_revision','idempotency_key','search'])
   OR NOT public.finance_settings_keys(NEW.command->'search',ARRAY['kind','query','birth_date'])
   OR NEW.command->'search'->>'kind' IS DISTINCT FROM 'search'
   OR jsonb_typeof(NEW.command->'search'->'query') IS DISTINCT FROM 'string'
   OR char_length(NEW.command->'search'->>'query') NOT BETWEEN 1 AND 120
   OR NEW.command->'search'->>'query'<>btrim(NEW.command->'search'->>'query') OR (NEW.command->'search'->>'query') ~ '[[:cntrl:]]'
  THEN RAISE EXCEPTION 'invalid patient search' USING ERRCODE='23514'; END IF;
  IF jsonb_typeof(NEW.command->'search'->'birth_date') IS DISTINCT FROM 'null' THEN
   IF NOT public.google_calendar_date(NEW.command->'search'->'birth_date') THEN
    RAISE EXCEPTION 'invalid patient search date' USING ERRCODE='23514'; END IF;
   IF (NEW.command->'search'->>'birth_date')::date>(clock_timestamp() AT TIME ZONE 'UTC')::date THEN
    RAISE EXCEPTION 'invalid patient search date' USING ERRCODE='23514'; END IF;
  END IF;
 ELSE
  SELECT * INTO parent FROM public.scheduling_patient_setup_requests WHERE id=NEW.preview_request_id;
  IF parent.kind IS DISTINCT FROM 'preview' OR (parent.workspace_id,parent.box_id,parent.owner_id,parent.account_id,parent.external_identity_id,parent.patient_link_id)
   IS DISTINCT FROM (NEW.workspace_id,NEW.box_id,NEW.owner_id,NEW.account_id,NEW.external_identity_id,NEW.patient_link_id)
   OR NOT public.patient_setup_request_current(parent.id) OR NOT public.finance_settings_keys(NEW.command,
    ARRAY['action','expected_revision','idempotency_key','preview_id','preview_sha256','choice_ref','identity_sha256','reviewed_same_patient','reviewed_exact_identity'])
   OR NEW.command->'reviewed_same_patient' IS DISTINCT FROM 'true'::jsonb OR NEW.command->'reviewed_exact_identity' IS DISTINCT FROM 'true'::jsonb
  THEN RAISE EXCEPTION 'invalid patient confirmation' USING ERRCODE='23514'; END IF;
  SELECT * INTO prior FROM public.scheduling_patient_setup_snapshots WHERE request_id=parent.id;
  IF prior.id IS NULL OR NOT public.patient_setup_snapshot_valid(prior.id)
   OR NEW.command->>'preview_id' IS DISTINCT FROM parent.id::text
   OR NEW.command->>'preview_sha256' IS DISTINCT FROM prior.source_sha256
   OR (prior.payload->>'expires_at')::timestamptz<=clock_timestamp() THEN
   RAISE EXCEPTION 'invalid selected patient preview' USING ERRCODE='23514'; END IF;
  SELECT value INTO choice FROM jsonb_array_elements(prior.payload->'choices') WHERE value->>'choice_ref'=NEW.command->>'choice_ref';
  IF choice IS NULL OR NEW.command->>'identity_sha256' IS DISTINCT FROM choice->>'identity_sha256'
   OR jsonb_typeof(NEW.command->'preview_id') IS DISTINCT FROM 'string'
   OR jsonb_typeof(NEW.command->'preview_sha256') IS DISTINCT FROM 'string'
   OR jsonb_typeof(NEW.command->'choice_ref') IS DISTINCT FROM 'string'
   OR jsonb_typeof(NEW.command->'identity_sha256') IS DISTINCT FROM 'string' THEN
   RAISE EXCEPTION 'invalid selected patient choice' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION public.guard_patient_setup_snapshot() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r public.scheduling_patient_setup_requests; checked timestamptz;
BEGIN
 SELECT * INTO r FROM public.scheduling_patient_setup_requests WHERE id=NEW.request_id;
 IF NOT public.patient_setup_request_current(r.id,true) OR NOT public.patient_setup_payload_valid(r.kind,NEW.payload) THEN
  RAISE EXCEPTION 'invalid patient setup snapshot' USING ERRCODE='23514'; END IF;
 checked:=CASE WHEN r.kind='preview' THEN (NEW.payload->>'checked_at')::timestamptz ELSE (NEW.payload->>'verified_at')::timestamptz END;
 IF checked<clock_timestamp()-interval '30 seconds' OR checked>clock_timestamp()+interval '5 seconds' OR (NEW.payload->>'expires_at')::timestamptz<=clock_timestamp() THEN
  RAISE EXCEPTION 'expired patient setup snapshot' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION public.patient_setup_mapping_hash(v public.scheduling_patient_mapping_reviews) RETURNS text
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT public.patient_setup_digest('cosmas-scheduling-patient-mapping.v1',jsonb_build_object('review_id',v.id,'mapping_id',v.mapping_id,
  'request_id',r.id,'request_sha256',r.request_sha256,'box_id',r.box_id,'owner_id',r.owner_id,'patient_link_id',r.patient_link_id,
  'account_id',r.account_id,'practice_id',z.payload->>'practice_id','patient_id',z.payload->>'patient_id',
  'identity_sha256',z.payload->'identity'->>'identity_sha256','subject_revision',z.payload->'identity'->'subject_revision'))
 FROM public.scheduling_patient_setup_requests r JOIN public.scheduling_patient_setup_snapshots z ON z.id=v.snapshot_id WHERE r.id=v.request_id
$$;
CREATE FUNCTION public.guard_patient_setup_settlement() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r public.scheduling_patient_setup_requests; z public.scheduling_patient_setup_snapshots;
 v public.scheduling_patient_mapping_reviews; m public.scheduling_patient_accounts; sid uuid;
BEGIN
 IF TG_TABLE_NAME='scheduling_patient_setup_snapshots' THEN sid:=NEW.id;
 ELSE sid:=NEW.snapshot_id; END IF;
 SELECT * INTO z FROM public.scheduling_patient_setup_snapshots WHERE id=sid;
 SELECT * INTO r FROM public.scheduling_patient_setup_requests WHERE id=z.request_id;
 IF NOT public.patient_setup_snapshot_valid(z.id) OR NOT public.patient_setup_request_current(r.id,true) THEN
  RAISE EXCEPTION 'invalid patient setup settlement' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='scheduling_patient_mapping_reviews' AND r.kind<>'confirm' THEN
  RAISE EXCEPTION 'verified patient confirmation required' USING ERRCODE='23514'; END IF;
 IF r.kind='confirm' THEN
  SELECT * INTO v FROM public.scheduling_patient_mapping_reviews WHERE request_id=r.id;
  SELECT * INTO m FROM public.scheduling_patient_accounts WHERE id=v.mapping_id;
  IF v.id IS NULL OR m.id IS NULL OR (v.workspace_id,v.box_id,v.owner_id,v.patient_link_id,v.snapshot_id) IS DISTINCT FROM
   (r.workspace_id,r.box_id,r.owner_id,r.patient_link_id,z.id)
   OR (m.box_id,m.patient_link_id,m.practice_id::text,m.patient_id::text,m.reviewed_by,m.evidence_ref,m.reviewed_at) IS DISTINCT FROM
    (r.box_id,r.patient_link_id,z.payload->>'practice_id',z.payload->>'patient_id',r.owner_id::text,'scheduling-patient:v1:'||v.id::text,v.created_at)
   OR m.revoked_at IS NOT NULL OR NOT v.reviewed_same_patient OR NOT v.reviewed_exact_identity
   OR v.mapping_sha256 IS DISTINCT FROM public.patient_setup_mapping_hash(v)
  THEN RAISE EXCEPTION 'invalid personal patient mapping review' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION public.guard_personal_patient_mapping() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.evidence_ref LIKE 'scheduling-patient:v1:%' AND NOT EXISTS(SELECT 1 FROM public.scheduling_patient_mapping_reviews v
  WHERE v.mapping_id=NEW.id AND NEW.evidence_ref='scheduling-patient:v1:'||v.id::text) THEN
  RAISE EXCEPTION 'personal patient mapping review required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION public.immutable_patient_setup() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'patient setup history is immutable' USING ERRCODE='23514'; END $$;
CREATE TRIGGER patient_setup_request_guard BEFORE INSERT ON public.scheduling_patient_setup_requests FOR EACH ROW EXECUTE FUNCTION public.guard_patient_setup_request();
CREATE TRIGGER patient_setup_snapshot_guard BEFORE INSERT ON public.scheduling_patient_setup_snapshots FOR EACH ROW EXECUTE FUNCTION public.guard_patient_setup_snapshot();
CREATE CONSTRAINT TRIGGER patient_setup_snapshot_settlement AFTER INSERT ON public.scheduling_patient_setup_snapshots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_patient_setup_settlement();
CREATE CONSTRAINT TRIGGER patient_setup_review_settlement AFTER INSERT ON public.scheduling_patient_mapping_reviews DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_patient_setup_settlement();
CREATE CONSTRAINT TRIGGER personal_patient_mapping_review AFTER INSERT ON public.scheduling_patient_accounts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_personal_patient_mapping();
CREATE TRIGGER immutable_patient_setup_request BEFORE UPDATE OR DELETE ON public.scheduling_patient_setup_requests FOR EACH ROW EXECUTE FUNCTION public.immutable_patient_setup();
CREATE TRIGGER immutable_patient_setup_snapshot BEFORE UPDATE OR DELETE ON public.scheduling_patient_setup_snapshots FOR EACH ROW EXECUTE FUNCTION public.immutable_patient_setup();
CREATE TRIGGER immutable_patient_setup_review BEFORE UPDATE OR DELETE ON public.scheduling_patient_mapping_reviews FOR EACH ROW EXECUTE FUNCTION public.immutable_patient_setup();
REVOKE ALL ON FUNCTION public.guard_patient_setup_request() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.guard_patient_setup_snapshot() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.guard_patient_setup_settlement() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.guard_personal_patient_mapping() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.patient_setup_canonical(jsonb,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.patient_setup_digest(text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.patient_setup_identity_valid(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.patient_setup_payload_valid(text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.patient_setup_source_context(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.patient_setup_request_current(uuid,boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.patient_setup_snapshot_valid(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.patient_setup_mapping_hash(public.scheduling_patient_mapping_reviews) FROM PUBLIC;
"""
