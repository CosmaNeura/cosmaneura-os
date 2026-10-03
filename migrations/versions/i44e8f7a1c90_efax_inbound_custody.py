"""Private eFax inbound grants and one-shot account acquisition around F8."""

from alembic import op

revision = "i44e8f7a1c90"
down_revision = "p43c9e7a2d15"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)
    op.execute(GUARDS)
    op.execute(PRIVATE_TRIGGERS)


def downgrade():
    raise RuntimeError("Retain eFax inbound approval, dispatch uncertainty and document custody")


TABLES = "\nCREATE TABLE efax_inbound_grants (\n\tid UUID NOT NULL, \n\tconnection_id UUID NOT NULL, \n\taccount_sha256 VARCHAR(64) NOT NULL, \n\tselection JSONB NOT NULL, \n\tselection_sha256 VARCHAR(64) NOT NULL, \n\tlabel VARCHAR(80) NOT NULL, \n\tmetadata_enabled BOOLEAN NOT NULL, \n\timage_enabled BOOLEAN NOT NULL, \n\treviewed_by UUID NOT NULL, \n\treviewed_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), \n\tCONSTRAINT uq_efax_inbound_grant_scope UNIQUE (id, box_id, owner_id), \n\tCHECK (metadata_enabled AND expires_at>reviewed_at AND expires_at<=reviewed_at+interval '30 days'), \n\tCHECK (char_length(label) BETWEEN 1 AND 80 AND reviewed_by=owner_id), \n\tCHECK (account_sha256 ~ '^[a-f0-9]{64}$' AND selection_sha256 ~ '^[a-f0-9]{64}$' AND request_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(selection) = 'object' AND octet_length(selection::text) <= 4096)\n)\n\n;\n\nCREATE TABLE efax_inbound_receipts (\n\tid UUID NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\tidempotency_key VARCHAR(100) NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\trequest JSONB NOT NULL, \n\tresult JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), \n\tCONSTRAINT uq_efax_inbound_receipt_key UNIQUE (box_id, owner_id, idempotency_key), \n\tCHECK (kind IN ('grant','revoke','observe','propose','decide','acquire')), \n\tCHECK (char_length(idempotency_key) BETWEEN 8 AND 100), \n\tCHECK (request_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(request) = 'object' AND octet_length(request::text) <= 8192), \n\tCHECK (jsonb_typeof(result) = 'object' AND octet_length(result::text) <= 8192)\n)\n\n;\n\nCREATE TABLE efax_inbound_observation_requests (\n\tid UUID NOT NULL, \n\tgrant_id UUID NOT NULL, \n\trequest JSONB NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(grant_id, box_id, owner_id) REFERENCES efax_inbound_grants (id, box_id, owner_id), \n\tCONSTRAINT uq_efax_inbound_observe_scope UNIQUE (id, box_id, owner_id), \n\tCHECK (request_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(request) = 'object' AND octet_length(request::text) <= 8192)\n)\n\n;\n\nCREATE TABLE efax_inbound_observations (\n\tid UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\tpayload JSONB NOT NULL, \n\tpayload_sha256 VARCHAR(64) NOT NULL, \n\tsource_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(request_id, box_id, owner_id) REFERENCES efax_inbound_observation_requests (id, box_id, owner_id), \n\tCONSTRAINT uq_efax_inbound_observation_request UNIQUE (request_id), \n\tCONSTRAINT uq_efax_inbound_observation_scope UNIQUE (id, box_id, owner_id), \n\tCHECK (payload_sha256 ~ '^[a-f0-9]{64}$' AND source_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 65536)\n)\n\n;\n\nCREATE TABLE efax_inbound_image_revisions (\n\taction_revision_id UUID NOT NULL, \n\tticket_id UUID NOT NULL, \n\tgrant_id UUID NOT NULL, \n\tobservation_id UUID NOT NULL, \n\toperation_id UUID NOT NULL, \n\tfax_id UUID NOT NULL, \n\tfax_sha256 VARCHAR(64) NOT NULL, \n\taction_sha256 VARCHAR(64) NOT NULL, \n\tcommand JSONB NOT NULL, \n\tcommand_sha256 VARCHAR(64) NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (action_revision_id), \n\tFOREIGN KEY(action_revision_id, ticket_id, box_id, action_sha256) REFERENCES action_revisions (id, ticket_id, box_id, payload_hash), \n\tFOREIGN KEY(grant_id, box_id, owner_id) REFERENCES efax_inbound_grants (id, box_id, owner_id), \n\tFOREIGN KEY(observation_id, box_id, owner_id) REFERENCES efax_inbound_observation_requests (id, box_id, owner_id), \n\tCONSTRAINT uq_efax_inbound_revision_scope UNIQUE (action_revision_id, box_id, owner_id), \n\tCONSTRAINT uq_efax_inbound_revision_ticket UNIQUE (ticket_id), \n\tCONSTRAINT uq_efax_inbound_revision_operation UNIQUE (operation_id), \n\tCHECK (action_sha256 ~ '^[a-f0-9]{64}$' AND command_sha256 ~ '^[a-f0-9]{64}$' AND fax_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(command) = 'object' AND octet_length(command::text) <= 8192)\n)\n\n;\n\nCREATE TABLE efax_inbound_acquisitions (\n\toperation_id UUID NOT NULL, \n\tticket_id UUID NOT NULL, \n\taction_revision_id UUID NOT NULL, \n\taccount_sha256 VARCHAR(64) NOT NULL, \n\tfax_id UUID NOT NULL, \n\ttoken_sha256 VARCHAR(64) NOT NULL, \n\tapproval JSONB NOT NULL, \n\tapproval_sha256 VARCHAR(64) NOT NULL, \n\tclaimed_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdeadline TIMESTAMP WITH TIME ZONE NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (operation_id), \n\tFOREIGN KEY(operation_id, ticket_id, box_id) REFERENCES operations (id, ticket_id, box_id), \n\tFOREIGN KEY(action_revision_id, box_id, owner_id) REFERENCES efax_inbound_image_revisions (action_revision_id, box_id, owner_id), \n\tCONSTRAINT uq_efax_inbound_acquisition_scope UNIQUE (operation_id, box_id, owner_id), \n\tCONSTRAINT uq_efax_inbound_acquisition_resource UNIQUE (box_id, account_sha256, fax_id), \n\tCHECK (deadline>claimed_at AND deadline<=claimed_at+interval '45 seconds'), \n\tCHECK (account_sha256 ~ '^[a-f0-9]{64}$' AND token_sha256 ~ '^[a-f0-9]{64}$' AND approval_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(approval) = 'object' AND octet_length(approval::text) <= 8192)\n)\n\n;\n\nCREATE TABLE efax_inbound_invocations (\n\toperation_id UUID NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (operation_id), \n\tFOREIGN KEY(operation_id, box_id, owner_id) REFERENCES efax_inbound_acquisitions (operation_id, box_id, owner_id)\n)\n\n;\n\nCREATE TABLE efax_inbound_outcomes (\n\toperation_id UUID NOT NULL, \n\tstate VARCHAR(32) NOT NULL, \n\treceipt JSONB NOT NULL, \n\treceipt_sha256 VARCHAR(64) NOT NULL, \n\tdocument BYTEA, \n\tdocument_sha256 VARCHAR(64), \n\tbyte_length INTEGER, \n\tpages INTEGER, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (operation_id), \n\tFOREIGN KEY(operation_id, box_id, owner_id) REFERENCES efax_inbound_acquisitions (operation_id, box_id, owner_id), \n\tCHECK (state IN ('not_attempted','outcome_unconfirmed','acquired','needs_human')), \n\tCHECK ((state='acquired' AND document IS NOT NULL AND document_sha256 IS NOT NULL AND byte_length IS NOT NULL AND pages IS NOT NULL AND octet_length(document) BETWEEN 1 AND 1048576 AND byte_length=octet_length(document) AND pages BETWEEN 1 AND 50 AND document_sha256=encode(sha256(document),'hex')) OR (state<>'acquired' AND document IS NULL AND document_sha256 IS NULL AND byte_length IS NULL AND pages IS NULL)), \n\tCHECK (receipt_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(receipt) = 'object' AND octet_length(receipt::text) <= 8192)\n)\n\n;"
GUARDS = r"""
CREATE FUNCTION public.efax_inbound_owner(b uuid,h uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.principals WHERE id=h AND box_id=b AND is_owner
  AND principal_type='human' AND state='active' AND tombstoned_at IS NULL)
$$;
CREATE FUNCTION public.efax_inbound_grant_current(gid uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM public.efax_inbound_grants g
 WHERE g.id=gid AND public.efax_inbound_owner(g.box_id,g.owner_id)
  AND g.revoked_at IS NULL AND g.expires_at>clock_timestamp() AND g.metadata_enabled)
$$;
CREATE FUNCTION public.guard_efax_inbound_grant() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'inbound grants are retained' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR NEW.revoked_at<OLD.reviewed_at
   OR (to_jsonb(OLD)-'revoked_at') IS DISTINCT FROM (to_jsonb(NEW)-'revoked_at')
  THEN RAISE EXCEPTION 'inbound grant revocation is terminal' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 PERFORM 1 FROM public.principals WHERE id=NEW.owner_id AND box_id=NEW.box_id FOR UPDATE;
 IF NOT public.efax_inbound_owner(NEW.box_id,NEW.owner_id) OR NEW.revoked_at IS NOT NULL
  OR NOT public.finance_settings_keys(NEW.selection,ARRAY['vendor','connection_id','box_id','owner_id','environment','remote_account_id','credential_ref','configuration_sha256'])
  OR NEW.selection->>'vendor'<>'efax' OR NEW.selection->>'environment'<>'production'
  OR (NEW.selection->>'connection_id',NEW.selection->>'box_id',NEW.selection->>'owner_id')
   IS DISTINCT FROM (NEW.connection_id::text,NEW.box_id::text,NEW.owner_id::text)
  OR coalesce(NEW.selection->>'remote_account_id' ~ '^[A-Za-z0-9_-]{1,255}$',false) IS NOT TRUE
  OR coalesce(NEW.selection->>'credential_ref' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$',false) IS NOT TRUE
  OR NOT public.research_hash(NEW.selection->'configuration_sha256')
  OR NEW.selection_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-vendor-selection.v1',NEW.selection)
  OR NEW.account_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-efax-inbound-account.v1',
    jsonb_build_object('box_id',NEW.box_id,'vendor','efax','environment','production','remote_account_id',NEW.selection->'remote_account_id'))
  OR NEW.reviewed_at>clock_timestamp()+interval '5 seconds' OR NEW.expires_at<=clock_timestamp()
 THEN RAISE EXCEPTION 'invalid inbound grant scope' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER efax_inbound_grant_guard BEFORE INSERT OR UPDATE OR DELETE ON public.efax_inbound_grants
 FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_grant();

CREATE FUNCTION public.guard_efax_inbound_receipt() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT public.efax_inbound_owner(NEW.box_id,NEW.owner_id)
  OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-efax-inbound-public-command.v1',
   jsonb_build_object('box_id',NEW.box_id,'owner_id',NEW.owner_id,'kind',NEW.kind,'request',NEW.request))
 THEN RAISE EXCEPTION 'invalid inbound command receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER efax_inbound_receipt_guard BEFORE INSERT ON public.efax_inbound_receipts
 FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_receipt();

CREATE FUNCTION public.guard_efax_inbound_observation_request() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE g public.efax_inbound_grants; starts timestamptz; ends timestamptz;
BEGIN
 SELECT * INTO g FROM public.efax_inbound_grants WHERE id=NEW.grant_id FOR SHARE;
 IF NOT public.efax_inbound_grant_current(g.id)
  OR (g.box_id,g.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NOT public.finance_settings_keys(NEW.request,ARRAY['selection','request_id','starts_at','ends_at','limit','offset'])
  OR NEW.request->'selection' IS DISTINCT FROM g.selection OR NEW.request->>'request_id' IS DISTINCT FROM NEW.id::text
  OR NEW.request_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-efax-inbound-observation-request.v1',NEW.request)
  OR NOT public.google_message_aware_time(NEW.request->'starts_at') OR NOT public.google_message_aware_time(NEW.request->'ends_at')
  OR jsonb_typeof(NEW.request->'limit') IS DISTINCT FROM 'number' OR (NEW.request->>'limit') !~ '^[1-9][0-9]*$'
  OR (NEW.request->>'limit')::numeric>25
  OR jsonb_typeof(NEW.request->'offset') IS DISTINCT FROM 'number' OR (NEW.request->>'offset') !~ '^(0|[1-9][0-9]*)$'
  OR (NEW.request->>'offset')::numeric>5000
 THEN RAISE EXCEPTION 'invalid inbound metadata request' USING ERRCODE='23514'; END IF;
 starts:=(NEW.request->>'starts_at')::timestamptz; ends:=(NEW.request->>'ends_at')::timestamptz;
 IF ends<=starts OR ends>starts+interval '7 days' OR ends>clock_timestamp()+interval '5 seconds'
 THEN RAISE EXCEPTION 'invalid inbound metadata window' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER efax_inbound_observation_request_guard BEFORE INSERT ON public.efax_inbound_observation_requests
 FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_observation_request();

CREATE FUNCTION public.guard_efax_inbound_observation() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r public.efax_inbound_observation_requests; item jsonb; ids text[]:=ARRAY[]::text[]; stamp timestamptz; prior timestamptz; k text;
BEGIN
 SELECT * INTO r FROM public.efax_inbound_observation_requests WHERE id=NEW.request_id;
 IF r.id IS NULL OR (r.box_id,r.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NOT public.efax_inbound_grant_current(r.grant_id)
  OR NOT public.finance_settings_keys(NEW.payload,ARRAY['request','first_record','last_record','items','observed_at','raw_sha256','source_sha256','scope','inbox_complete','continuation'])
  OR NEW.payload->'request' IS DISTINCT FROM r.request
  OR NEW.payload->>'scope' IS DISTINCT FROM 'one_received_metadata_page'
  OR NEW.payload->'inbox_complete' IS DISTINCT FROM 'false'::jsonb OR NEW.payload->>'continuation' IS DISTINCT FROM 'unknown'
  OR NOT public.research_hash(NEW.payload->'raw_sha256')
  OR NEW.payload_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-efax-inbound-snapshot-payload.v1',NEW.payload)
  OR NEW.source_sha256 IS DISTINCT FROM NEW.payload->>'source_sha256'
  OR NEW.source_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-efax-inbound-list.v1',NEW.payload-'source_sha256')
  OR NOT public.google_message_aware_time(NEW.payload->'observed_at')
  OR (NEW.payload->>'observed_at')::timestamptz NOT BETWEEN clock_timestamp()-interval '5 minutes' AND clock_timestamp()+interval '5 seconds'
  OR jsonb_typeof(NEW.payload->'items') IS DISTINCT FROM 'array'
  OR jsonb_array_length(NEW.payload->'items')>(r.request->>'limit')::integer
 THEN RAISE EXCEPTION 'invalid inbound snapshot' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['first_record','last_record'] LOOP
  IF jsonb_typeof(NEW.payload->k) IS DISTINCT FROM 'number'
   OR (NEW.payload->>k) !~ '^(0|[1-9][0-9]*)$' OR (NEW.payload->>k)::numeric>2147483647
  THEN RAISE EXCEPTION 'invalid inbound pagination metadata' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.payload->'items') LOOP
  IF NOT public.finance_settings_keys(item,ARRAY['fax_id','size','duration','pages','image_downloaded','completed_timestamp','destination_fax_number','originating_fax_number','originating_fax_tsid','fax_status'])
   OR coalesce(item->>'fax_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$',false) IS NOT TRUE
   OR item->>'fax_id'=ANY(ids) OR jsonb_typeof(item->'image_downloaded') IS DISTINCT FROM 'boolean'
   OR NOT public.google_message_aware_time(item->'completed_timestamp')
   OR (item->'fax_status' IS DISTINCT FROM 'null'::jsonb AND item->>'fax_status' NOT IN ('STORED','NOT_STORED'))
   OR jsonb_typeof(item->'originating_fax_tsid') IS DISTINCT FROM 'string'
   OR char_length(item->>'originating_fax_tsid')>128 OR (item->>'originating_fax_tsid') ~ '[[:cntrl:]]'
   OR coalesce(item->>'destination_fax_number' ~ '^[+]?[0-9]{7,15}$',false) IS NOT TRUE
   OR coalesce(item->>'originating_fax_number' ~ '^[+]?[0-9]{7,15}$',false) IS NOT TRUE
  THEN RAISE EXCEPTION 'invalid inbound fax metadata' USING ERRCODE='23514'; END IF;
  FOREACH k IN ARRAY ARRAY['size','duration','pages'] LOOP
   IF jsonb_typeof(item->k) IS DISTINCT FROM 'number' OR (item->>k) !~ '^(0|[1-9][0-9]*)$'
    OR (item->>k)::numeric>(CASE k WHEN 'size' THEN 16777216 WHEN 'duration' THEN 86400 ELSE 10000 END)
   THEN RAISE EXCEPTION 'invalid inbound metadata bounds' USING ERRCODE='23514'; END IF;
  END LOOP;
  stamp:=(item->>'completed_timestamp')::timestamptz;
  IF stamp NOT BETWEEN (r.request->>'starts_at')::timestamptz AND (r.request->>'ends_at')::timestamptz
   OR (prior IS NOT NULL AND stamp>prior)
  THEN RAISE EXCEPTION 'invalid inbound metadata ordering' USING ERRCODE='23514'; END IF;
  prior:=stamp; ids:=array_append(ids,item->>'fax_id');
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER efax_inbound_observation_guard BEFORE INSERT ON public.efax_inbound_observations
 FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_observation();

CREATE FUNCTION public.efax_inbound_revision_valid(rid uuid) RETURNS boolean
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE r public.efax_inbound_image_revisions; a public.action_revisions; g public.efax_inbound_grants;
 z public.efax_inbound_observations; q public.efax_inbound_observation_requests; item jsonb;
BEGIN
 SELECT * INTO r FROM public.efax_inbound_image_revisions WHERE action_revision_id=rid;
 SELECT * INTO a FROM public.action_revisions WHERE id=rid;
 SELECT * INTO g FROM public.efax_inbound_grants WHERE id=r.grant_id;
 SELECT * INTO q FROM public.efax_inbound_observation_requests WHERE id=r.observation_id;
 SELECT * INTO z FROM public.efax_inbound_observations WHERE request_id=q.id;
 SELECT value INTO item FROM jsonb_array_elements(z.payload->'items') WHERE value->>'fax_id'=r.fax_id::text;
 RETURN coalesce(r.action_revision_id IS NOT NULL AND a.id IS NOT NULL AND g.id IS NOT NULL
  AND q.id IS NOT NULL AND z.id IS NOT NULL AND item IS NOT NULL
  AND (r.box_id,r.owner_id)=(g.box_id,g.owner_id) AND (q.box_id,q.owner_id,q.grant_id)=(r.box_id,r.owner_id,g.id)
  AND a.ticket_id=r.ticket_id AND a.box_id=r.box_id AND a.created_by_principal_id=r.owner_id
  AND a.action_type='efax_inbound_image' AND NOT a.invalidated
  AND a.payload=jsonb_build_object('contract_version',1,'inbound_revision_id',r.action_revision_id,'command_sha256',r.command_sha256)
  AND a.payload_hash=r.action_sha256 AND a.payload_hash=public.research_json_digest(a.payload)
  AND r.command_sha256=public.vendor_public_digest('cosmas-efax-image-command.v1',r.command)
  AND public.finance_settings_keys(r.command,ARRAY['selection','operation_id','source_sha256','fax_id','format','expires_at','side_effect'])
  AND r.command->'selection'=g.selection AND r.command->'selection'=q.request->'selection'
  AND r.command->>'source_sha256'=z.source_sha256 AND r.command->>'operation_id'=r.operation_id::text
  AND r.command->>'fax_id'=r.fax_id::text AND r.command->>'format'='PDF'
  AND r.command->>'side_effect'='marks_fax_downloaded_or_read'
  AND public.google_message_aware_time(r.command->'expires_at')
  AND r.fax_sha256=public.vendor_public_digest('cosmas-efax-inbound-fax.v1',item)
  AND item->>'fax_status' IS DISTINCT FROM 'NOT_STORED'
  AND (item->>'pages')::integer BETWEEN 1 AND 50,false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION public.guard_efax_inbound_revision() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT public.efax_inbound_revision_valid(NEW.action_revision_id)
  OR NOT public.efax_inbound_grant_current(NEW.grant_id)
  OR NOT (SELECT image_enabled FROM public.efax_inbound_grants WHERE id=NEW.grant_id)
 THEN RAISE EXCEPTION 'invalid inbound image revision' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER efax_inbound_revision_guard AFTER INSERT ON public.efax_inbound_image_revisions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_revision();

CREATE FUNCTION public.guard_efax_inbound_claim() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r public.efax_inbound_image_revisions; g public.efax_inbound_grants; d public.efax_inbound_receipts;
BEGIN
 SELECT * INTO r FROM public.efax_inbound_image_revisions WHERE action_revision_id=NEW.action_revision_id;
 SELECT * INTO g FROM public.efax_inbound_grants WHERE id=r.grant_id FOR SHARE;
 SELECT * INTO d FROM public.efax_inbound_receipts WHERE box_id=NEW.box_id AND owner_id=NEW.owner_id
  AND kind='decide' AND request_sha256=NEW.approval_sha256;
 IF NOT public.efax_inbound_owner(NEW.box_id,NEW.owner_id)
  OR NOT public.efax_inbound_grant_current(g.id) OR NOT g.image_enabled
  OR NOT public.efax_inbound_revision_valid(r.action_revision_id)
  OR (r.box_id,r.owner_id,r.ticket_id,r.operation_id,r.fax_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id,NEW.ticket_id,NEW.operation_id,NEW.fax_id)
  OR NEW.account_sha256 IS DISTINCT FROM g.account_sha256
  OR d.id IS NULL OR d.request->>'choice' IS DISTINCT FROM 'approve'
  OR d.request->>'revision_id' IS DISTINCT FROM r.action_revision_id::text
  OR NOT EXISTS(SELECT 1 FROM public.decisions x WHERE x.id=(d.result->>'decision_id')::uuid
   AND x.action_revision_id=r.action_revision_id AND x.actor_principal_id=NEW.owner_id AND x.kind='approve')
  OR NOT public.finance_settings_keys(NEW.approval,ARRAY['operation_id','command_sha256','selection_sha256','operator_id','approved_at','expires_at','reviewed_exact_fax','approved_mark_downloaded_or_read'])
  OR (NEW.approval->>'operation_id',NEW.approval->>'command_sha256',NEW.approval->>'selection_sha256',NEW.approval->>'operator_id')
   IS DISTINCT FROM (NEW.operation_id::text,r.command_sha256,g.selection_sha256,NEW.owner_id::text)
  OR NEW.approval->'reviewed_exact_fax' IS DISTINCT FROM 'true'::jsonb
  OR NEW.approval->'approved_mark_downloaded_or_read' IS DISTINCT FROM 'true'::jsonb
  OR (r.command->>'expires_at')::timestamptz<=clock_timestamp()
 THEN RAISE EXCEPTION 'invalid inbound acquisition approval' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER efax_inbound_claim_guard BEFORE INSERT ON public.efax_inbound_acquisitions
 FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_claim();

CREATE FUNCTION public.guard_efax_inbound_invocation() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c public.efax_inbound_acquisitions; r public.efax_inbound_image_revisions;
BEGIN
 SELECT * INTO c FROM public.efax_inbound_acquisitions WHERE operation_id=NEW.operation_id FOR SHARE;
 SELECT * INTO r FROM public.efax_inbound_image_revisions WHERE action_revision_id=c.action_revision_id;
 IF c.operation_id IS NULL OR (c.box_id,c.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NOT public.efax_inbound_grant_current(r.grant_id) OR NOT public.efax_inbound_owner(NEW.box_id,NEW.owner_id)
  OR NEW.started_at>=c.deadline OR NEW.started_at<c.claimed_at
  OR EXISTS(SELECT 1 FROM public.efax_inbound_outcomes WHERE operation_id=c.operation_id)
 THEN RAISE EXCEPTION 'inbound invocation is fenced' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER efax_inbound_invocation_guard BEFORE INSERT ON public.efax_inbound_invocations
 FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_invocation();

CREATE FUNCTION public.guard_efax_inbound_outcome() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c public.efax_inbound_acquisitions; r public.efax_inbound_image_revisions; item jsonb;
BEGIN
 SELECT * INTO c FROM public.efax_inbound_acquisitions WHERE operation_id=NEW.operation_id;
 SELECT * INTO r FROM public.efax_inbound_image_revisions WHERE action_revision_id=c.action_revision_id;
 IF c.operation_id IS NULL OR (c.box_id,c.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NEW.receipt_sha256 IS DISTINCT FROM public.vendor_public_digest('cosmas-efax-inbound-receipt.v1',NEW.receipt)
  OR NEW.state IS DISTINCT FROM NEW.receipt->>'state'
  OR NOT public.finance_settings_keys(NEW.receipt,ARRAY['operation_id','command_sha256','selection_sha256','fax_id','state','attempted','provider_read_state','content_available','observed_at','response_sha256','document_sha256','source_sha256','byte_length','pages','retry_allowed','trust'])
  OR (NEW.receipt->>'operation_id',NEW.receipt->>'command_sha256',NEW.receipt->>'selection_sha256',NEW.receipt->>'fax_id')
   IS DISTINCT FROM (c.operation_id::text,r.command_sha256,public.vendor_public_digest('cosmas-vendor-selection.v1',r.command->'selection'),r.fax_id::text)
 THEN RAISE EXCEPTION 'invalid inbound outcome custody' USING ERRCODE='23514'; END IF;
 IF NEW.receipt->'attempted' IS DISTINCT FROM to_jsonb(EXISTS(SELECT 1 FROM public.efax_inbound_invocations WHERE operation_id=c.operation_id))
  OR NEW.receipt->'retry_allowed' IS DISTINCT FROM 'false'::jsonb
  OR NEW.receipt->>'trust' IS DISTINCT FROM 'untrusted_external_document'
  OR NOT public.google_message_aware_time(NEW.receipt->'observed_at')
 THEN RAISE EXCEPTION 'invalid inbound outcome effect' USING ERRCODE='23514'; END IF;
 IF NEW.receipt->'response_sha256' IS DISTINCT FROM 'null'::jsonb
  AND NOT public.research_hash(NEW.receipt->'response_sha256')
 THEN RAISE EXCEPTION 'invalid inbound response hash' USING ERRCODE='23514'; END IF;
 IF NEW.state='acquired' THEN
  SELECT value INTO item FROM public.efax_inbound_observations z,
   LATERAL jsonb_array_elements(z.payload->'items') WHERE z.request_id=r.observation_id AND value->>'fax_id'=r.fax_id::text;
  IF NEW.receipt->'content_available' IS DISTINCT FROM 'true'::jsonb
   OR NEW.receipt->>'provider_read_state' IS DISTINCT FROM 'endpoint_reported_download'
   OR NEW.document_sha256 IS DISTINCT FROM NEW.receipt->>'document_sha256'
   OR NEW.byte_length IS DISTINCT FROM (NEW.receipt->>'byte_length')::integer OR NEW.pages IS DISTINCT FROM (NEW.receipt->>'pages')::integer
   OR NEW.pages IS DISTINCT FROM (item->>'pages')::integer
   OR NOT public.research_hash(NEW.receipt->'response_sha256')
   OR NEW.receipt->>'source_sha256' IS DISTINCT FROM public.vendor_public_digest('cosmas-efax-inbound-image.v1',
    jsonb_build_object('command_sha256',r.command_sha256,'list_source_sha256',r.command->'source_sha256','fax_id',r.fax_id,
    'response_sha256',NEW.receipt->'response_sha256','document_sha256',NEW.document_sha256,'byte_length',NEW.byte_length,'pages',NEW.pages))
  THEN RAISE EXCEPTION 'invalid inbound PDF receipt' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.receipt->'content_available' IS DISTINCT FROM 'false'::jsonb
   OR NEW.receipt->'document_sha256' IS DISTINCT FROM 'null'::jsonb
   OR NEW.receipt->'source_sha256' IS DISTINCT FROM 'null'::jsonb
   OR NEW.receipt->'byte_length' IS DISTINCT FROM 'null'::jsonb
   OR NEW.receipt->'pages' IS DISTINCT FROM 'null'::jsonb
   OR (NEW.state='not_attempted' AND (NEW.receipt->'attempted' IS DISTINCT FROM 'false'::jsonb OR NEW.receipt->>'provider_read_state'<>'unchanged_by_this_attempt'))
   OR (NEW.state<>'not_attempted' AND (NEW.receipt->'attempted' IS DISTINCT FROM 'true'::jsonb OR NEW.receipt->>'provider_read_state' NOT IN ('may_have_changed','endpoint_reported_download')))
  THEN RAISE EXCEPTION 'invalid inbound uncertain receipt' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER efax_inbound_outcome_guard BEFORE INSERT ON public.efax_inbound_outcomes
 FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_outcome();

CREATE FUNCTION public.guard_efax_inbound_f8() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE t public.tickets; r public.efax_inbound_image_revisions; o public.operations;
 c public.efax_inbound_acquisitions; result public.efax_inbound_outcomes; started boolean;
BEGIN
 IF TG_TABLE_NAME='tickets' THEN SELECT * INTO t FROM public.tickets WHERE id=NEW.id;
 ELSIF TG_TABLE_NAME IN ('efax_inbound_invocations','efax_inbound_outcomes') THEN
  SELECT ticket_id INTO o.ticket_id FROM public.operations WHERE id=NEW.operation_id;
  SELECT * INTO t FROM public.tickets WHERE id=o.ticket_id;
 ELSE SELECT * INTO t FROM public.tickets WHERE id=NEW.ticket_id; END IF;
 IF t.lane IS DISTINCT FROM 'account_efax_inbound' THEN
  IF TG_TABLE_NAME='operations' THEN
   IF NEW.adapter='efax_inbound_once' THEN RAISE EXCEPTION 'inbound operation requires private ticket' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NULL;
 END IF;
 SELECT * INTO r FROM public.efax_inbound_image_revisions WHERE ticket_id=t.id;
 SELECT * INTO o FROM public.operations WHERE action_revision_id=r.action_revision_id;
 SELECT * INTO c FROM public.efax_inbound_acquisitions WHERE operation_id=o.id;
 SELECT * INTO result FROM public.efax_inbound_outcomes WHERE operation_id=o.id;
 SELECT EXISTS(SELECT 1 FROM public.efax_inbound_invocations WHERE operation_id=o.id) INTO started;
 IF NOT public.efax_inbound_revision_valid(r.action_revision_id)
  OR t.current_revision_id IS DISTINCT FROM r.action_revision_id OR t.box_id IS DISTINCT FROM r.box_id
  OR t.created_by_principal_id IS DISTINCT FROM r.owner_id OR t.patient_link_id IS NOT NULL OR t.appointment_id IS NOT NULL
  OR t.state NOT IN ('pending_approval','approved','rejected')
 THEN RAISE EXCEPTION 'inbound F8 identity invalid' USING ERRCODE='23514'; END IF;
 IF t.state='approved' THEN
  IF o.id IS NULL OR o.id IS DISTINCT FROM r.operation_id OR o.adapter<>'efax_inbound_once'
   OR (o.ticket_id,o.box_id) IS DISTINCT FROM (t.id,t.box_id) OR o.external_reference IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM public.decisions d WHERE d.ticket_id=t.id AND d.action_revision_id=r.action_revision_id
     AND d.kind='approve' AND d.actor_principal_id=r.owner_id)
   OR o.attempt_count IS DISTINCT FROM (CASE WHEN c.operation_id IS NULL THEN 0 ELSE 1 END)
   OR (result.operation_id IS NULL AND o.status IS DISTINCT FROM (CASE WHEN started THEN 'unknown' WHEN c.operation_id IS NOT NULL THEN 'running' ELSE 'pending' END))
   OR (result.operation_id IS NOT NULL AND (o.result_receipt_hash IS DISTINCT FROM result.receipt_sha256
      OR o.status IS DISTINCT FROM (CASE result.state WHEN 'acquired' THEN 'succeeded' WHEN 'outcome_unconfirmed' THEN 'unknown' ELSE 'failed' END)))
  THEN RAISE EXCEPTION 'inbound F8 outcome invalid' USING ERRCODE='23514'; END IF;
 ELSIF o.id IS NOT NULL THEN RAISE EXCEPTION 'unapproved inbound operation' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER efax_inbound_ticket_guard AFTER INSERT OR UPDATE ON public.tickets
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_f8();
CREATE CONSTRAINT TRIGGER efax_inbound_operation_guard AFTER INSERT OR UPDATE ON public.operations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_f8();
CREATE CONSTRAINT TRIGGER efax_inbound_acquisition_f8_guard AFTER INSERT ON public.efax_inbound_acquisitions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_f8();
CREATE CONSTRAINT TRIGGER efax_inbound_invocation_f8_guard AFTER INSERT ON public.efax_inbound_invocations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_f8();
CREATE CONSTRAINT TRIGGER efax_inbound_outcome_f8_guard AFTER INSERT ON public.efax_inbound_outcomes
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_f8();

CREATE FUNCTION public.guard_efax_inbound_core_mutation() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_TABLE_NAME='operations' THEN
  IF OLD.adapter='efax_inbound_once' THEN
   IF TG_OP='DELETE' OR (to_jsonb(OLD)-ARRAY['status','attempt_count','started_at','completed_at','result_receipt_hash'])
     IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['status','attempt_count','started_at','completed_at','result_receipt_hash'])
    OR NEW.attempt_count<OLD.attempt_count OR NEW.attempt_count>1
   THEN RAISE EXCEPTION 'inbound operation cannot reset' USING ERRCODE='23514'; END IF;
  END IF;
 ELSE
  IF OLD.lane='account_efax_inbound' THEN
   IF TG_OP='DELETE' OR (to_jsonb(OLD)-ARRAY['state','version']) IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['state','version'])
    OR NEW.version<OLD.version OR NEW.state NOT IN ('pending_approval','approved','rejected')
   THEN RAISE EXCEPTION 'inbound ticket identity retained' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER efax_inbound_operation_mutation BEFORE UPDATE OR DELETE ON public.operations
 FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_core_mutation();
CREATE TRIGGER efax_inbound_ticket_mutation BEFORE UPDATE OR DELETE ON public.tickets
 FOR EACH ROW EXECUTE FUNCTION public.guard_efax_inbound_core_mutation();

DO $$
DECLARE table_name text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['efax_inbound_receipts','efax_inbound_observation_requests','efax_inbound_observations',
  'efax_inbound_image_revisions','efax_inbound_acquisitions','efax_inbound_invocations','efax_inbound_outcomes'] LOOP
  EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()',table_name||'_immutable',table_name);
 END LOOP;
END $$;
"""


# The application role cannot execute custody readers directly. These pinned
# trigger entrypoints enforce their exact row bindings under migration-owned
# authority, matching the existing Google and human-review trigger pattern.
PRIVATE_TRIGGERS = r"""
DO $$
DECLARE signature text;
BEGIN
 FOREACH signature IN ARRAY ARRAY[
  'public.guard_efax_inbound_grant()','public.guard_efax_inbound_receipt()',
  'public.guard_efax_inbound_observation_request()','public.guard_efax_inbound_observation()',
  'public.guard_efax_inbound_revision()','public.guard_efax_inbound_claim()',
  'public.guard_efax_inbound_invocation()','public.guard_efax_inbound_outcome()',
  'public.guard_efax_inbound_f8()','public.guard_efax_inbound_core_mutation()'
 ] LOOP
  EXECUTE 'ALTER FUNCTION ' || signature || ' SECURITY DEFINER SET search_path=pg_catalog';
  EXECUTE 'REVOKE ALL ON FUNCTION ' || signature || ' FROM PUBLIC';
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.efax_inbound_owner(uuid,uuid),
 public.efax_inbound_grant_current(uuid),public.efax_inbound_revision_valid(uuid) FROM PUBLIC;
"""
