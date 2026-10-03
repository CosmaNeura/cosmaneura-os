"""Current custody for explicitly shared email, calendar and fax evidence.

Source kinds keep separate ledgers. Historical provenance never grants current
model or human-review access, including for uncited derived drafts.
"""

from cosmas_os.application import workspace as ws
from cosmas_os.models import WorkspaceEntry

SOURCE_STATE_FIELDS = {
    "google_message": "google_source_state",
    "google_calendar": "calendar_source_state",
    "efax_inbound_source": "fax_source_state",
}


def is_selected_connector(entry):
    return entry is not None and entry.kind in SOURCE_STATE_FIELDS


def _service(kind):
    if kind == "google_message":
        from cosmas_os.application import google_message

        return google_message
    if kind == "google_calendar":
        from cosmas_os.application import google_calendar

        return google_calendar
    if kind == "efax_inbound_source":
        from cosmas_os.application import efax_inbound_source

        return efax_inbound_source
    raise ws.WorkspaceError("selected_connector_source_invalid")


def source_state_field(kind):
    if kind not in SOURCE_STATE_FIELDS:
        raise ws.WorkspaceError("selected_connector_source_invalid")
    return SOURCE_STATE_FIELDS[kind]


def validate_selected_source(s, w, entry_id):
    entry = s.get(WorkspaceEntry, entry_id)
    if not is_selected_connector(entry):
        raise ws.WorkspaceError("selected_connector_source_invalid")
    return _service(entry.kind).validate_selected_source(s, w, entry_id)


def historical_source(s, w, entry_id):
    entry = s.get(WorkspaceEntry, entry_id)
    if not is_selected_connector(entry):
        raise ws.WorkspaceError("selected_connector_source_invalid")
    return _service(entry.kind).historical_source(s, w, entry_id)


def unavailable_states(s, w, context):
    unavailable = set()
    for passage in context.sources:
        entry = s.get(WorkspaceEntry, passage.entry_id)
        if is_selected_connector(entry):
            try:
                validate_selected_source(s, w, entry.id)
            except ws.WorkspaceError:
                unavailable.add(SOURCE_STATE_FIELDS[entry.kind])
    return unavailable


def projection_unavailable(entry):
    return any(entry.get(field) == "unavailable" for field in SOURCE_STATE_FIELDS.values())
