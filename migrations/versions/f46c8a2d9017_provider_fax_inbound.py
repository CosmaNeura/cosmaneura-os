"""Provider-neutral private received-fax custody; no external activation."""
from alembic import op

revision = "f46c8a2d9017"
down_revision = "e45a9d7c3b82"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(TABLES)
    op.execute(GUARDS)


def downgrade():
    raise RuntimeError("Retain private fax grants, approvals and one-attempt evidence")

TABLES = "\nCREATE TABLE fax_inbound_grants (\n\tid UUID NOT NULL, \n\tinstallation JSONB NOT NULL, \n\tinstallation_sha256 VARCHAR(64) NOT NULL, \n\taccount_sha256 VARCHAR(64) NOT NULL, \n\tlabel VARCHAR(80) NOT NULL, \n\timage_enabled BOOLEAN NOT NULL, \n\treviewed_by UUID NOT NULL, \n\treviewed_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), \n\tUNIQUE (id, box_id, owner_id), \n\tCHECK (expires_at>reviewed_at AND expires_at<=reviewed_at+interval '1 day'), \n\tCHECK (char_length(label) BETWEEN 1 AND 80 AND reviewed_by=owner_id), \n\tCHECK (installation_sha256 ~ '^[a-f0-9]{64}$' AND account_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(installation) = 'object' AND octet_length(installation::text) <= 8192)\n)\n\n;\n\nCREATE TABLE fax_inbound_commands (\n\tid UUID NOT NULL, \n\tidempotency_key VARCHAR(100) NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\trequest JSONB NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tpublic_request JSONB NOT NULL, \n\tresult JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), \n\tUNIQUE (id, box_id, owner_id), \n\tUNIQUE (box_id, owner_id, idempotency_key), \n\tCHECK (kind IN ('grant','revoke','observe','propose','decide','acquire')), \n\tCHECK (idempotency_key ~ '^[A-Za-z0-9:_-]{8,100}$'), \n\tCHECK (request_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(request) = 'object' AND octet_length(request::text) <= 8192), \n\tCHECK (jsonb_typeof(public_request) = 'object' AND octet_length(public_request::text) <= 8192), \n\tCHECK (jsonb_typeof(result) = 'object' AND octet_length(result::text) <= 8192)\n)\n\n;\n\nCREATE TABLE fax_inbound_observations (\n\tid UUID NOT NULL, \n\tgrant_id UUID NOT NULL, \n\tsnapshot JSONB NOT NULL, \n\tsource_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(grant_id, box_id, owner_id) REFERENCES fax_inbound_grants (id, box_id, owner_id), \n\tFOREIGN KEY(id, box_id, owner_id) REFERENCES fax_inbound_commands (id, box_id, owner_id), \n\tUNIQUE (id, box_id, owner_id), \n\tCHECK (source_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (jsonb_typeof(snapshot) = 'object' AND octet_length(snapshot::text) <= 131072)\n)\n\n;\n\nCREATE TABLE fax_inbound_images (\n\tid UUID NOT NULL, \n\tgrant_id UUID NOT NULL, \n\tobservation_id UUID NOT NULL, \n\tsource_sha256 VARCHAR(64) NOT NULL, \n\tticket_id UUID NOT NULL, \n\trevision_id UUID NOT NULL, \n\tpayload_sha256 VARCHAR(64) NOT NULL, \n\toperation_id UUID NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(grant_id, box_id, owner_id) REFERENCES fax_inbound_grants (id, box_id, owner_id), \n\tFOREIGN KEY(observation_id, box_id, owner_id) REFERENCES fax_inbound_observations (id, box_id, owner_id), \n\tFOREIGN KEY(revision_id, ticket_id, box_id, payload_sha256) REFERENCES action_revisions (id, ticket_id, box_id, payload_hash), \n\tUNIQUE (id, box_id, owner_id), \n\tUNIQUE (revision_id), \n\tUNIQUE (operation_id), \n\tCHECK (source_sha256 ~ '^[a-f0-9]{64}$' AND payload_sha256 ~ '^[a-f0-9]{64}$')\n)\n\n;\n\nCREATE TABLE fax_inbound_attempts (\n\toperation_id UUID NOT NULL, \n\tticket_id UUID NOT NULL, \n\timage_id UUID NOT NULL, \n\taccount_sha256 VARCHAR(64) NOT NULL, \n\tlocator_sha256 VARCHAR(64) NOT NULL, \n\ttoken_sha256 VARCHAR(64) NOT NULL, \n\tapproval_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdeadline TIMESTAMP WITH TIME ZONE NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (operation_id), \n\tFOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), \n\tFOREIGN KEY(image_id, box_id, owner_id) REFERENCES fax_inbound_images (id, box_id, owner_id), \n\tFOREIGN KEY(operation_id, ticket_id, box_id) REFERENCES operations (id, ticket_id, box_id), \n\tUNIQUE (operation_id, box_id, owner_id), \n\tUNIQUE (account_sha256, locator_sha256), \n\tCHECK (account_sha256 ~ '^[a-f0-9]{64}$' AND locator_sha256 ~ '^[a-f0-9]{64}$' AND token_sha256 ~ '^[a-f0-9]{64}$' AND approval_sha256 ~ '^[a-f0-9]{64}$'), \n\tCHECK (deadline>created_at AND deadline<=created_at+interval '45 seconds')\n)\n\n;\n\nCREATE TABLE fax_inbound_outcomes (\n\toperation_id UUID NOT NULL, \n\tstate VARCHAR(32) NOT NULL, \n\tdocument BYTEA, \n\tdocument_sha256 VARCHAR(64), \n\tpages INTEGER, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (operation_id), \n\tFOREIGN KEY(operation_id, box_id, owner_id) REFERENCES fax_inbound_attempts (operation_id, box_id, owner_id), \n\tCHECK (state IN ('acquired','outcome_unconfirmed')), \n\tCHECK (((state='acquired' AND document IS NOT NULL AND octet_length(document) BETWEEN 1 AND 1048576 AND pages BETWEEN 1 AND 50 AND document_sha256 ~ '^[a-f0-9]{64}$') OR (state='outcome_unconfirmed' AND document IS NULL AND document_sha256 IS NULL AND pages IS NULL))) IS TRUE)\n)\n\n;\n\nCREATE TABLE fax_inbound_dispatches (\n\toperation_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tPRIMARY KEY (operation_id), \n\tFOREIGN KEY(operation_id, box_id, owner_id) REFERENCES fax_inbound_attempts (operation_id, box_id, owner_id)\n)\n\n;"

GUARDS = r"""
CREATE FUNCTION public.fax_inbound_hash(v jsonb) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT encode(sha256(convert_to(public.vendor_public_canonical(v),'UTF8')),'hex')
$$;
CREATE FUNCTION public.guard_fax_inbound_grant() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v jsonb;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'fax grant retained' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR NEW.revoked_at<OLD.reviewed_at
   OR (to_jsonb(OLD)-'revoked_at') IS DISTINCT FROM (to_jsonb(NEW)-'revoked_at')
  THEN RAISE EXCEPTION 'fax revocation terminal' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 v:=NEW.installation->'selection';
 IF NOT public.efax_inbound_owner(NEW.box_id,NEW.owner_id)
  OR NEW.revoked_at IS NOT NULL OR NEW.reviewed_at>clock_timestamp()+interval '5 seconds'
  OR NEW.expires_at<=clock_timestamp() OR NEW.label IS DISTINCT FROM NEW.installation->>'label'
  OR NOT public.finance_settings_keys(v,ARRAY['vendor','connection_id','box_id','owner_id','environment','remote_account_id','credential_ref','configuration_sha256'])
  OR (v->>'box_id',v->>'owner_id') IS DISTINCT FROM (NEW.box_id::text,NEW.owner_id::text)
  OR coalesce(v->>'vendor' IN ('spruce','srfax','documo'),false) IS NOT TRUE
  OR coalesce(v->>'environment' IN ('production','sandbox'),false) IS NOT TRUE
  OR (v->>'vendor' IN ('srfax','spruce') AND v->>'environment'<>'production')
  OR (v->>'vendor'='spruce' AND NEW.image_enabled)
  OR NEW.image_enabled AND NEW.installation->'image_enabled' IS DISTINCT FROM 'true'::jsonb
  OR NEW.installation_sha256 IS DISTINCT FROM public.fax_inbound_hash(NEW.installation)
  OR NEW.account_sha256 IS DISTINCT FROM public.fax_inbound_hash(jsonb_build_object('box',NEW.box_id,'vendor',v->'vendor','environment',v->'environment','account',v->'remote_account_id'))
 THEN RAISE EXCEPTION 'fax installation scope invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER fax_inbound_grant_guard BEFORE INSERT OR UPDATE OR DELETE ON public.fax_inbound_grants FOR EACH ROW EXECUTE FUNCTION public.guard_fax_inbound_grant();

CREATE FUNCTION public.guard_fax_inbound_command() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NOT public.efax_inbound_owner(NEW.box_id,NEW.owner_id)
  OR NEW.request_sha256 IS DISTINCT FROM public.fax_inbound_hash(jsonb_build_object('kind',NEW.kind,'request',NEW.request))
  OR NEW.result->>'kind' IS DISTINCT FROM NEW.kind OR NEW.result->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key
 THEN RAISE EXCEPTION 'fax command invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER fax_inbound_command_guard BEFORE INSERT ON public.fax_inbound_commands FOR EACH ROW EXECUTE FUNCTION public.guard_fax_inbound_command();

CREATE FUNCTION public.guard_fax_inbound_observation() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE g public.fax_inbound_grants; c public.fax_inbound_commands;
BEGIN
 SELECT * INTO g FROM public.fax_inbound_grants WHERE id=NEW.grant_id;
 SELECT * INTO c FROM public.fax_inbound_commands WHERE id=NEW.id;
 IF g.revoked_at IS NOT NULL OR g.expires_at<=clock_timestamp() OR c.kind IS DISTINCT FROM 'observe'
  OR c.request->>'grant_id' IS DISTINCT FROM NEW.grant_id::text
  OR NEW.snapshot->'scope'->'selection' IS DISTINCT FROM g.installation->'selection'
  OR NEW.snapshot->'scope'->>'starts_at' IS DISTINCT FROM c.request->>'starts_at'
  OR NEW.snapshot->'scope'->>'ends_at' IS DISTINCT FROM c.request->>'ends_at'
  OR NEW.snapshot->'scope'->'limit' IS DISTINCT FROM c.request->'limit'
  OR NEW.snapshot->'inbox_complete' IS DISTINCT FROM 'false'::jsonb
  OR jsonb_typeof(NEW.snapshot->'items') IS DISTINCT FROM 'array'
  OR jsonb_array_length(NEW.snapshot->'items')>(c.request->>'limit')::integer
  OR NEW.source_sha256 IS DISTINCT FROM public.fax_inbound_hash(NEW.snapshot)
 THEN RAISE EXCEPTION 'fax observation invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER fax_inbound_observation_guard BEFORE INSERT ON public.fax_inbound_observations FOR EACH ROW EXECUTE FUNCTION public.guard_fax_inbound_observation();


CREATE FUNCTION public.guard_fax_inbound_image() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE g public.fax_inbound_grants; z public.fax_inbound_observations; t public.tickets; a public.action_revisions;
BEGIN
 SELECT * INTO g FROM public.fax_inbound_grants WHERE id=NEW.grant_id;
 SELECT * INTO z FROM public.fax_inbound_observations WHERE id=NEW.observation_id;
 SELECT * INTO t FROM public.tickets WHERE id=NEW.ticket_id;
 SELECT * INTO a FROM public.action_revisions WHERE id=NEW.revision_id;
 IF NOT public.efax_inbound_owner(NEW.box_id,NEW.owner_id)
  OR g.revoked_at IS NOT NULL OR g.expires_at<=clock_timestamp() OR NOT g.image_enabled
  OR z.grant_id IS DISTINCT FROM g.id OR z.created_at<clock_timestamp()-interval '5 minutes'
  OR NEW.expires_at<=clock_timestamp() OR NEW.expires_at>g.expires_at OR NEW.expires_at>clock_timestamp()+interval '5 minutes 5 seconds'
  OR t.lane IS DISTINCT FROM 'account_fax_inbound' OR t.created_by_principal_id IS DISTINCT FROM NEW.owner_id
  OR t.state IS DISTINCT FROM 'pending_approval' OR t.current_revision_id IS DISTINCT FROM NEW.revision_id
  OR a.invalidated OR a.action_type IS DISTINCT FROM 'fax_inbound_image' OR a.created_by_principal_id IS DISTINCT FROM NEW.owner_id
  OR a.payload IS DISTINCT FROM jsonb_build_object('contract_version',1,'fax_inbound_image_id',NEW.id,'source_sha256',NEW.source_sha256)
  OR a.payload_hash IS DISTINCT FROM NEW.payload_sha256 OR NEW.payload_sha256 IS DISTINCT FROM public.fax_inbound_hash(a.payload)
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(z.snapshot->'items') item WHERE item->'image_available'='true'::jsonb
    AND (item->>'pages')::integer BETWEEN 1 AND 50
    AND public.fax_inbound_hash(jsonb_build_object('scope',item->'scope_sha256','locator',item->'locator','at',item->'received_at',
      'pages',item->'pages','size',item->'size','viewed',item->'viewed','image_available',item->'image_available',
      'block',item->'image_block_reason','sender_label',item->'sender_label','sender_number',item->'sender_number',
      'url_commitment',CASE WHEN item->>'private_image_url' IS NULL THEN NULL ELSE encode(sha256(convert_to(item->>'private_image_url','UTF8')),'hex') END))=NEW.source_sha256)
 THEN RAISE EXCEPTION 'fax image proposal invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER fax_inbound_image_guard BEFORE INSERT ON public.fax_inbound_images FOR EACH ROW EXECUTE FUNCTION public.guard_fax_inbound_image();

CREATE FUNCTION public.guard_fax_inbound_core() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE i public.fax_inbound_images; t public.tickets; c public.fax_inbound_attempts;
BEGIN
 IF TG_TABLE_NAME='action_revisions' THEN
  SELECT * INTO i FROM public.fax_inbound_images WHERE revision_id=OLD.id;
  IF i.id IS NOT NULL THEN RAISE EXCEPTION 'fax approval revision immutable' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='tickets' THEN
  IF OLD.lane='account_fax_inbound' AND (TG_OP='DELETE' OR
    (to_jsonb(OLD)-ARRAY['state','version','closed_at']) IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['state','version','closed_at']))
  THEN RAISE EXCEPTION 'fax ticket binding immutable' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='decisions' THEN
  SELECT * INTO i FROM public.fax_inbound_images WHERE revision_id=OLD.action_revision_id;
  IF i.id IS NOT NULL THEN RAISE EXCEPTION 'fax decision immutable' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER fax_inbound_action_core BEFORE UPDATE OR DELETE ON public.action_revisions FOR EACH ROW EXECUTE FUNCTION public.guard_fax_inbound_core();
CREATE TRIGGER fax_inbound_ticket_core BEFORE UPDATE OR DELETE ON public.tickets FOR EACH ROW EXECUTE FUNCTION public.guard_fax_inbound_core();
CREATE TRIGGER fax_inbound_decision_core BEFORE UPDATE OR DELETE ON public.decisions FOR EACH ROW EXECUTE FUNCTION public.guard_fax_inbound_core();

CREATE FUNCTION public.guard_fax_inbound_attempt() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE i public.fax_inbound_images; g public.fax_inbound_grants; t public.tickets; a public.action_revisions; o public.operations;
BEGIN
 SELECT * INTO i FROM public.fax_inbound_images WHERE id=NEW.image_id;
 SELECT * INTO g FROM public.fax_inbound_grants WHERE id=i.grant_id;
 SELECT * INTO t FROM public.tickets WHERE id=i.ticket_id;
 SELECT * INTO a FROM public.action_revisions WHERE id=i.revision_id;
 SELECT * INTO o FROM public.operations WHERE id=NEW.operation_id;
 IF i.operation_id IS DISTINCT FROM NEW.operation_id OR i.ticket_id IS DISTINCT FROM NEW.ticket_id
  OR g.account_sha256 IS DISTINCT FROM NEW.account_sha256 OR g.revoked_at IS NOT NULL OR g.expires_at<=clock_timestamp()
  OR NOT g.image_enabled OR i.expires_at<=clock_timestamp() OR NEW.created_at>clock_timestamp()+interval '5 seconds'
  OR t.lane IS DISTINCT FROM 'account_fax_inbound' OR t.created_by_principal_id IS DISTINCT FROM NEW.owner_id
  OR t.current_revision_id IS DISTINCT FROM i.revision_id OR t.state IS DISTINCT FROM 'approved'
  OR a.invalidated OR a.payload_hash IS DISTINCT FROM i.payload_sha256
  OR a.action_type IS DISTINCT FROM 'fax_inbound_image'
  OR o.adapter IS DISTINCT FROM 'fax_inbound_once' OR o.attempt_count<>1 OR o.status NOT IN ('running','unknown','succeeded')
  OR NOT EXISTS(SELECT 1 FROM public.decisions d JOIN public.fax_inbound_commands c ON c.result->>'decision_id'=d.id::text
    WHERE c.box_id=NEW.box_id AND c.owner_id=NEW.owner_id AND c.kind='decide' AND c.request_sha256=NEW.approval_sha256
    AND c.request->'reviewed_exact_fax'='true'::jsonb AND c.request->>'choice'='approve'
    AND d.kind='approve' AND d.actor_principal_id=NEW.owner_id AND d.ticket_id=i.ticket_id AND d.action_revision_id=i.revision_id)
 THEN RAISE EXCEPTION 'fax attempt approval invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER fax_inbound_attempt_guard AFTER INSERT ON public.fax_inbound_attempts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.guard_fax_inbound_attempt();

CREATE FUNCTION public.guard_fax_inbound_outcome() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE c public.fax_inbound_attempts; i public.fax_inbound_images; g public.fax_inbound_grants;
BEGIN
 SELECT * INTO c FROM public.fax_inbound_attempts WHERE operation_id=NEW.operation_id;
 SELECT * INTO i FROM public.fax_inbound_images WHERE id=c.image_id;
 SELECT * INTO g FROM public.fax_inbound_grants WHERE id=i.grant_id;
 IF c.operation_id IS NULL OR (c.box_id,c.owner_id) IS DISTINCT FROM (NEW.box_id,NEW.owner_id)
  OR NEW.state='acquired' AND (NEW.document_sha256 IS DISTINCT FROM encode(sha256(NEW.document),'hex')
   OR substring(NEW.document FROM 1 FOR 5)<>decode('255044462d','hex'))
 THEN RAISE EXCEPTION 'fax outcome invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER fax_inbound_outcome_guard BEFORE INSERT ON public.fax_inbound_outcomes FOR EACH ROW EXECUTE FUNCTION public.guard_fax_inbound_outcome();
DO $$ DECLARE n text; BEGIN
 FOREACH n IN ARRAY ARRAY['fax_inbound_commands','fax_inbound_observations','fax_inbound_images','fax_inbound_attempts','fax_inbound_outcomes','fax_inbound_dispatches'] LOOP
  EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()',n||'_immutable',n);
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.fax_inbound_hash(jsonb), public.guard_fax_inbound_grant(), public.guard_fax_inbound_command(), public.guard_fax_inbound_observation(), public.guard_fax_inbound_attempt(), public.guard_fax_inbound_outcome(), public.guard_fax_inbound_image(), public.guard_fax_inbound_core() FROM PUBLIC;
"""
