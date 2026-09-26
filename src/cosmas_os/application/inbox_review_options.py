"""A private read of current matching workspaces; no new source or authority."""

from sqlalchemy import select

from cosmas_os.api import inbox_review_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import inbox_work as inbox
from cosmas_os.application import workspace as ws
from cosmas_os.models import EncounterWorkspace


def read(s, box, actor, iid, *, registry=inbox.no_registry, policy=inbox.DEFAULT_POLICY):
    row = inbox.item(s, box, actor, iid)
    if not policy.enabled:
        inbox.error("inbox_feature_disabled", 403)
    if row.version >= 96:
        inbox.error("inbox_history_limit")
    grant = inbox.InboxReadGrant.model_validate(row.grant)
    inbox.grant_current(s, box, actor, grant, registry)
    source = inbox.head(s, row)
    if source is None or row.read_issue or row.source_conflict:
        inbox.error("inbox_source_changed")
    inbox.source_snapshot(source)
    rows = list(
        s.scalars(
            select(EncounterWorkspace)
            .where(
                EncounterWorkspace.box_id == box,
                EncounterWorkspace.owner_id == actor,
                EncounterWorkspace.patient_link_id == row.patient_link_id,
            )
            .order_by(EncounterWorkspace.id)
            .limit(101)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    if len(rows) > 100:
        inbox.error("inbox_history_limit")
    choices = []
    for candidate in rows:
        try:
            appointment = ws._encounter(s, box, candidate.appointment_id, row.patient_link_id, owner=actor)
        except ws.WorkspaceError:
            continue
        if appointment.start_at is None:
            continue
        choices.append(
            {
                "workspace_id": candidate.id,
                "expected_workspace_revision": candidate.revision,
                "appointment_id": appointment.id,
                "label": appointment.patient_label,
                "start_at": public.timestamp(appointment.start_at),
            }
        )
    value = {
        "contract_version": 1,
        "scope": inbox.scope(box, actor),
        "item_id": row.id,
        "item_version": row.version,
        "source_id": source.id,
        "source_sha256": source.source_sha256,
        "patient_link_id": row.patient_link_id,
        "choices": choices,
    }
    value["options_sha256"] = public.public_digest("cosmas-inbox-review-options.v1", value)
    result = public.bounded(schema.ReviewOptions.model_validate(value).public(), 131072)
    inbox.final_authority(s)
    inbox.grant_current(s, box, actor, grant, registry)
    return result
