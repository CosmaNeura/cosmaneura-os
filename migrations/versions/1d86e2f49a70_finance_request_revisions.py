"""Unsent financial revision transition guards; retain prior approval history."""
from alembic import op

revision = "1d86e2f49a70"
down_revision = "f47c21b8a906"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(GUARD_DDL)


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.finance_work_revisions WHERE revision_number>1) THEN RAISE EXCEPTION 'revised finance history prevents downgrade' USING ERRCODE='23514'; END IF; END $$;")
    op.execute("DROP TRIGGER finance_revision_transition ON public.tickets; DROP FUNCTION public.finance_revision_transition_guard(); DROP TRIGGER finance_superseded_operation ON public.operations; DROP FUNCTION public.finance_superseded_operation_guard();")


GUARD_DDL = r"""
CREATE FUNCTION public.finance_revision_transition_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior public.finance_work_revisions; current_revision public.finance_work_revisions;
BEGIN
 IF OLD.lane<>'encounter_payment_request' AND NEW.lane<>'encounter_payment_request' THEN RETURN NEW; END IF;
 SELECT * INTO prior FROM public.finance_work_revisions WHERE action_revision_id=OLD.current_revision_id;
 SELECT * INTO current_revision FROM public.finance_work_revisions WHERE action_revision_id=NEW.current_revision_id;
 IF prior.action_revision_id IS NULL OR current_revision.action_revision_id IS NULL
  OR NEW.state<>'pending_approval' OR OLD.state NOT IN ('pending_approval','approved') OR NEW.version<>OLD.version+1
  OR (current_revision.ticket_id,current_revision.box_id,current_revision.owner_id,current_revision.workspace_id,current_revision.patient_link_id)
    IS DISTINCT FROM (prior.ticket_id,prior.box_id,prior.owner_id,prior.workspace_id,prior.patient_link_id)
  OR current_revision.revision_number<>prior.revision_number+1 OR current_revision.intended_operation_id=prior.intended_operation_id
  OR current_revision.public_proposal->'revises' IS DISTINCT FROM jsonb_build_object('ticket_id',OLD.id,'expected_version',OLD.version,'revision_id',OLD.current_revision_id,'payload_hash',prior.payload_hash)
  OR EXISTS(SELECT 1 FROM public.finance_submit_claims spent WHERE spent.operation_id=prior.intended_operation_id)
  OR EXISTS(SELECT 1 FROM public.operations previous_op WHERE previous_op.id=prior.intended_operation_id AND (previous_op.attempt_count<>0 OR previous_op.status<>'cancelled'))
 THEN RAISE EXCEPTION 'finance revision requires exact unclaimed prior request' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.finance_command_receipts proposed WHERE proposed.action_revision_id=current_revision.action_revision_id AND proposed.command_kind='propose' AND proposed.effect_version=NEW.version)
 THEN RAISE EXCEPTION 'finance revised proposal receipt required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER finance_revision_transition AFTER UPDATE ON public.tickets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
 WHEN (OLD.current_revision_id IS NOT NULL AND OLD.current_revision_id IS DISTINCT FROM NEW.current_revision_id)
 EXECUTE FUNCTION public.finance_revision_transition_guard();

CREATE FUNCTION public.finance_superseded_operation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r public.finance_work_revisions; current_id uuid; current_operation public.operations;
BEGIN
 SELECT * INTO current_operation FROM public.operations WHERE id=NEW.id;
 SELECT * INTO r FROM public.finance_work_revisions WHERE action_revision_id=current_operation.action_revision_id;
 IF r.action_revision_id IS NULL THEN RETURN NEW; END IF;
 SELECT current_revision_id INTO current_id FROM public.tickets WHERE id=r.ticket_id;
 IF current_id<>r.action_revision_id AND (current_operation.attempt_count<>0 OR current_operation.status<>'cancelled')
 THEN RAISE EXCEPTION 'superseded financial operation is permanently cancelled' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER finance_superseded_operation AFTER INSERT OR UPDATE ON public.operations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.finance_superseded_operation_guard();
"""
