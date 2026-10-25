"""Outlook custody remains distinct from Gmail and from clinical notes."""
from types import SimpleNamespace

import pytest

from cosmas_os.application import microsoft_message, google_message, model_work, note_review
from cosmas_os.application import selected_connector_sources as sources
from cosmas_os.application import workspace as ws
from cosmas_os.ports.bot_capabilities import SourcePassage


class SelectedSession:
    def __init__(self, row, admission=None):
        self.row = row
        self.admission = admission

    def get(self, model, identifier):
        return self.row if identifier == self.row.id else None

    def scalar(self, query):
        return self.admission


def row():
    return SimpleNamespace(id='invented-outlook-source', kind='microsoft_message', revision=3,
                           source_label='Invented Outlook email', content='Invented reviewed passage')


def test_outlook_dispatches_to_its_own_custody_and_masks_uncited_lineage(monkeypatch):
    selected = row()
    session, workspace = SelectedSession(selected), object()
    calls = []
    monkeypatch.setattr(microsoft_message, 'validate_selected_source',
                        lambda s, w, i: calls.append(i) or selected)
    monkeypatch.setattr(google_message, 'validate_selected_source',
                        lambda *args: pytest.fail('Outlook source used Gmail custody'))
    assert sources.validate_selected_source(session, workspace, selected.id) is selected
    assert calls == [selected.id]

    def withdrawn(*args):
        raise ws.WorkspaceError('microsoft_message_grant_unavailable')

    monkeypatch.setattr(microsoft_message, 'validate_selected_source', withdrawn)
    context = SimpleNamespace(sources=(SourcePassage(selected.id, 3, selected.source_label,
                                                   'evidence', selected.content),))
    assert sources.unavailable_states(session, workspace, context) == {'microsoft_source_state'}
    assert sources.projection_unavailable({'google_source_state': 'current', 'microsoft_source_state': 'unavailable'})


def test_outlook_passages_require_feature_gate_and_join_in_revision_order(monkeypatch):
    selected = row()
    flags = SimpleNamespace(workspace_microsoft_message_available=False,
                            workspace_calendar_import_available=False,
                            workspace_ehr_read_available=False,
                            efax_inbound_source_available=False, fax_inbound_source_available=False)
    monkeypatch.setattr(model_work.team, 'runtime_settings', flags)
    google = SourcePassage('invented-google-source', 2, 'Invented Gmail email', 'evidence', 'Earlier email')
    monkeypatch.setattr(model_work, '_selected_google_passages', lambda *args: (google,))
    from cosmas_os.application import clinical_note_share
    monkeypatch.setattr(clinical_note_share, 'selected', lambda *args: ())
    calls = []
    monkeypatch.setattr(microsoft_message, 'selected_entries', lambda *args: calls.append(args) or [selected])
    workspace = SimpleNamespace(appointment_id='invented-visit', revision=3)
    assert model_work._selected_connector_passages(None, workspace, {}) == (google,)
    assert calls == []
    flags.workspace_microsoft_message_available = True
    passages = model_work._selected_connector_passages(None, workspace, {})
    assert [source.entry_id for source in passages] == ['invented-google-source', selected.id]
    assert passages[1].content == selected.content


def test_outlook_derived_output_cannot_be_imported_as_clinical_note(monkeypatch):
    selected = row()
    context = SimpleNamespace(sources=(SourcePassage(selected.id, 3, selected.source_label,
                                                   'evidence', selected.content),))
    from cosmas_os.adapters import gpt41
    monkeypatch.setattr(gpt41, '_context', lambda value: context)
    session = SelectedSession(selected, SimpleNamespace(prepared_envelope={'context': {}}))
    workspace = SimpleNamespace(id='invented-workspace', box_id='invented-box', owner_id='invented-owner')
    with pytest.raises(ws.WorkspaceError, match='microsoft_message_note_import_unavailable'):
        note_review._require_note_lineage(session, workspace, 'invented-derived-reply')
