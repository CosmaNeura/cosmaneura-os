"""Durable private model admission, truthful usage and no-dispatch failures."""

from alembic import op

revision = "9f26a481b7c0"
down_revision = "76ba9dcf120e"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE external_identities ADD CONSTRAINT uq_external_identity_scope UNIQUE (id,box_id,principal_id)')
    op.execute('ALTER TABLE workspace_handoff_attempts ADD CONSTRAINT uq_handoff_attempt_scope UNIQUE (id,workspace_id,box_id,owner_id)')
    op.execute('ALTER TABLE workspace_handoff_attempts DROP CONSTRAINT ck_handoff_attempt_times')
    op.execute("ALTER TABLE workspace_handoff_attempts ADD CONSTRAINT ck_handoff_attempt_times CHECK ((status <> 'queued' OR started_at IS NULL) AND (status NOT IN ('running','completed') OR started_at IS NOT NULL) AND (status IN ('queued','running')) = (completed_at IS NULL))")
    op.execute("CREATE TABLE model_work_admissions (\n\tid UUID NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tagent_id UUID NOT NULL, \n\tteam_revision_id UUID NOT NULL, \n\texternal_identity_id UUID, \n\tkind VARCHAR(32) NOT NULL, \n\trequest_key VARCHAR(100) NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\thandoff_attempt_id UUID, \n\texpected_revision INTEGER NOT NULL, \n\tcontext_revision INTEGER NOT NULL, \n\trequest_body JSONB NOT NULL, \n\tprepared_envelope JSONB NOT NULL, \n\tenvelope_contract VARCHAR(64) NOT NULL, \n\tenvelope_sha256 VARCHAR(64) NOT NULL, \n\tsource_sha256 VARCHAR(64) NOT NULL, \n\tadmitted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\treservation_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstate VARCHAR(16) NOT NULL, \n\tdispatch_id UUID, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tlease_ends_at TIMESTAMP WITH TIME ZONE, \n\tfinalized_at TIMESTAMP WITH TIME ZONE, \n\trequest_entry_id UUID NOT NULL, \n\tresult_entry_id UUID, \n\treason VARCHAR(64), \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(owner_id, box_id) REFERENCES principals (id, box_id), \n\tFOREIGN KEY(workspace_id, box_id, owner_id) REFERENCES encounter_workspaces (id, box_id, owner_id), \n\tFOREIGN KEY(agent_id, box_id, owner_id) REFERENCES provider_bots (agent_id, box_id, owner_id), \n\tFOREIGN KEY(team_revision_id, box_id, owner_id) REFERENCES provider_team_revisions (id, box_id, owner_id), \n\tFOREIGN KEY(external_identity_id, box_id, owner_id) REFERENCES external_identities (id, box_id, principal_id), \n\tFOREIGN KEY(handoff_attempt_id, workspace_id, box_id, owner_id) REFERENCES workspace_handoff_attempts (id, workspace_id, box_id, owner_id), \n\tFOREIGN KEY(request_entry_id, workspace_id, box_id) REFERENCES workspace_entries (id, workspace_id, box_id), \n\tFOREIGN KEY(result_entry_id, workspace_id, box_id) REFERENCES workspace_entries (id, workspace_id, box_id), \n\tCONSTRAINT uq_model_admission_scope UNIQUE (id, workspace_id, box_id, owner_id), \n\tCONSTRAINT uq_model_admission_request UNIQUE (workspace_id, request_key), \n\tCONSTRAINT uq_model_admission_entry UNIQUE (request_entry_id), \n\tCONSTRAINT uq_model_admission_handoff UNIQUE (handoff_attempt_id), \n\tCONSTRAINT ck_model_admission_kind CHECK (kind IN ('conversation','private_handoff') AND (kind='conversation') = (handoff_attempt_id IS NULL)), \n\tCONSTRAINT ck_model_admission_state CHECK (state IN ('reserved','running','completed','failed','unknown','abandoned')), \n\tCONSTRAINT ck_model_admission_hashes CHECK (request_hash ~ '^[0-9a-f]{64}$' AND envelope_sha256 ~ '^[0-9a-f]{64}$' AND source_sha256 ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT ck_model_admission_revisions CHECK (expected_revision >= 1 AND context_revision >= 1), \n\tCONSTRAINT ck_model_admission_json CHECK (jsonb_typeof(request_body)='object' AND octet_length(request_body::text) <= 131072 AND jsonb_typeof(prepared_envelope)='object' AND octet_length(prepared_envelope::text) <= 4194304), \n\tCONSTRAINT ck_model_admission_times CHECK (reservation_expires_at > admitted_at AND (state IN ('reserved','running')) = (finalized_at IS NULL)), \n\tCONSTRAINT ck_model_admission_dispatch CHECK ((dispatch_id IS NULL) = (started_at IS NULL) AND (dispatch_id IS NULL) = (lease_ends_at IS NULL) AND (state NOT IN ('running','completed','unknown') OR dispatch_id IS NOT NULL) AND (state NOT IN ('reserved','abandoned') OR dispatch_id IS NULL)), \n\tCONSTRAINT ck_model_admission_result_identity CHECK (result_entry_id IS NULL OR result_entry_id=request_entry_id), \n\tCONSTRAINT ck_model_admission_completed CHECK (state <> 'completed' OR result_entry_id IS NOT NULL)\n)")
    op.execute('CREATE INDEX ix_model_owner_admitted ON model_work_admissions (box_id, owner_id, admitted_at)')
    op.execute('CREATE INDEX ix_model_owner_state ON model_work_admissions (box_id, owner_id, state)')
    op.execute("CREATE UNIQUE INDEX uq_model_active_conversation ON model_work_admissions (workspace_id) WHERE kind='conversation' AND state IN ('reserved','running')")
    op.execute("CREATE TABLE model_usage_observations (\n\tid UUID NOT NULL, \n\tadmission_id UUID NOT NULL, \n\tworkspace_id UUID NOT NULL, \n\tbox_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\tobserved_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdispatch VARCHAR(32) NOT NULL, \n\toutcome VARCHAR(32) NOT NULL, \n\tusage VARCHAR(16) NOT NULL, \n\tinput_tokens INTEGER, \n\toutput_tokens INTEGER, \n\tmodel VARCHAR(64) NOT NULL, \n\tenvelope_sha256 VARCHAR(64) NOT NULL, \n\tresponse_sha256 VARCHAR(64), \n\treceipt_hash VARCHAR(64) NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(admission_id, workspace_id, box_id, owner_id) REFERENCES model_work_admissions (id, workspace_id, box_id, owner_id), \n\tCONSTRAINT uq_model_usage_kind UNIQUE (admission_id, kind), \n\tCONSTRAINT ck_model_usage_kind CHECK (kind IN ('terminal','late_usage')), \n\tCONSTRAINT ck_model_usage_dispatch CHECK (dispatch IN ('not_dispatched','started_unconfirmed','response_received')), \n\tCONSTRAINT ck_model_usage_outcome CHECK (outcome IN ('valid_output','invalid_output','connector_failure','authority_withheld','source_withheld','interrupted','reservation_expired')), \n\tCONSTRAINT ck_model_usage_tokens CHECK (usage IN ('unknown','verified') AND ((usage='unknown' AND input_tokens IS NULL AND output_tokens IS NULL) OR (usage='verified' AND input_tokens BETWEEN 0 AND 999999 AND output_tokens BETWEEN 0 AND 999999))), \n\tCONSTRAINT ck_model_usage_hashes CHECK (receipt_hash ~ '^[0-9a-f]{64}$' AND envelope_sha256 ~ '^[0-9a-f]{64}$' AND (response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$'))\n)")
    _guards()


def downgrade():
    raise RuntimeError("Retain model admissions and usage; disable new work instead")


def _guards():
    op.execute("""CREATE FUNCTION public.guard_model_admission() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'model admissions are retained'; END IF;
            IF NEW.reason IS NOT NULL AND NEW.reason NOT IN
              ('model_unavailable','authority_changed','source_changed','dispatch_interrupted','reservation_expired','team_work_limit')
              THEN RAISE EXCEPTION 'invalid model reason'; END IF;
            IF TG_OP='INSERT' THEN
                IF NEW.state <> 'reserved' OR NEW.dispatch_id IS NOT NULL OR NEW.result_entry_id IS NOT NULL
                   OR NEW.reason IS NOT NULL THEN RAISE EXCEPTION 'model admission must begin reserved'; END IF;
                RETURN NEW;
            END IF;
            IF OLD.state='reserved' AND NEW.state='running' AND NEW.dispatch_id IS NOT NULL
              AND NEW.started_at IS NOT NULL AND NEW.lease_ends_at > NEW.started_at
              AND NEW.lease_ends_at <= NEW.started_at + interval '90 seconds'
              AND NEW.started_at < NEW.reservation_expires_at
              AND (to_jsonb(OLD)-ARRAY['state','dispatch_id','started_at','lease_ends_at']) =
                  (to_jsonb(NEW)-ARRAY['state','dispatch_id','started_at','lease_ends_at']) THEN RETURN NEW; END IF;
            IF ((OLD.state='reserved' AND NEW.state IN ('failed','abandoned'))
                 OR (OLD.state='running' AND NEW.state IN ('completed','failed','unknown')))
              AND (to_jsonb(OLD)-ARRAY['state','finalized_at','result_entry_id','reason']) =
                  (to_jsonb(NEW)-ARRAY['state','finalized_at','result_entry_id','reason']) THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'invalid model admission transition';
        END; $$""")
    op.execute("""CREATE TRIGGER model_admission_lifecycle BEFORE INSERT OR UPDATE OR DELETE
        ON public.model_work_admissions FOR EACH ROW EXECUTE FUNCTION public.guard_model_admission()""")
    op.execute("""CREATE TRIGGER model_usage_immutable BEFORE UPDATE OR DELETE
        ON public.model_usage_observations FOR EACH ROW EXECUTE FUNCTION public.reject_workspace_history_change()""")
    op.execute("""CREATE OR REPLACE FUNCTION public.guard_workspace_handoff_attempt() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'handoff attempts are retained'; END IF;
            IF OLD.status='queued' AND NEW.status='running' AND
                (to_jsonb(OLD)-ARRAY['status','started_at']) = (to_jsonb(NEW)-ARRAY['status','started_at']) THEN RETURN NEW; END IF;
            IF OLD.status='queued' AND NEW.status IN ('failed','interrupted')
              AND NEW.started_at IS NULL AND NEW.error_code IN
                ('team_work_limit','legacy_queued_unadmitted','reservation_expired','authority_changed','source_changed','model_unavailable')
              AND (to_jsonb(OLD)-ARRAY['status','completed_at','error_code']) =
                  (to_jsonb(NEW)-ARRAY['status','completed_at','error_code']) THEN RETURN NEW; END IF;
            IF OLD.status='running' AND NEW.status IN ('completed','failed','interrupted') AND
                (to_jsonb(OLD)-ARRAY['status','completed_at','error_code','result_entry_id']) =
                (to_jsonb(NEW)-ARRAY['status','completed_at','error_code','result_entry_id']) THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'invalid handoff attempt transition';
        END; $$""")
