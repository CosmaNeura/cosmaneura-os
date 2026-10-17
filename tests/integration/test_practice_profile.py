"""Structured preferences retain the team contract and enter the actual helper context."""
from copy import deepcopy

import pytest
from pydantic import ValidationError
from tests.integration import test_private_workspace_drafts as private

from cosmas_os.api.team_schemas import TeamConfiguration
from cosmas_os.application import conversation, provider_team

create, headers = private.create, private.headers
signed_workspace = private.signed_workspace

PROFILE = {"version": 1, "practice_name": "Invented clinic", "specialty": "Family medicine", "provider_name": "Invented Provider",
    "credentials": "MD", "state": "NY", "note_format": "SOAP", "language": "English"}


def test_save_reopen_exact_profile_and_helper_context(signed_workspace, session):
    f = signed_workspace
    _, notebook = create(f)
    value = provider_team.read(session, f.box, f.actor)
    configuration = deepcopy(value['configuration'])
    configuration['practice_profile'] = PROFILE
    signed = {**headers(f), 'X-Cosmas-Team-Contract': '5'}
    command = {'expected_revision': value['revision'], 'idempotency_key': 'practice-profile-001', 'configuration': configuration}
    result = f.client.post('/provider-team', headers=signed, json=command)
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved['configuration']['practice_profile'] == PROFILE
    assert f.client.post('/provider-team', headers=signed, json=command).json()['revision'] == saved['revision']
    assert f.client.get('/provider-team', headers=signed).json()['configuration']['practice_profile'] == PROFILE
    # Older clients cannot omit and overwrite a profile they cannot represent.
    assert f.client.get('/provider-team', headers={**signed, 'X-Cosmas-Team-Contract': '4'}).status_code == 426
    assert f.client.post('/provider-team', headers={**signed, 'X-Cosmas-Team-Contract': '4'}, json={
        **command, 'expected_revision': saved['revision'], 'idempotency_key': 'old-profile-client', 'configuration': value['configuration']}).status_code == 426
    version = provider_team.current(session, f.box, f.actor)
    settings = next(bot for bot in version.configuration['bots'] if bot['role'] == 'scribe')
    context = conversation.build_context(notebook, version, settings, 'scribe', 'Draft my saved notes')
    assert 'Practice name: Invented clinic' in context.practice_context
    assert 'Provider name: Invented Provider' in context.practice_context and 'Default note format: SOAP' in context.practice_context
    assert context.role == 'scribe' and context.workspace_id == notebook['id']
    assert saved['configuration']['bots'] == provider_team.configuration_value(value['configuration'])['bots']


@pytest.mark.parametrize('profile', [{**PROFILE, 'version': True}, {**PROFILE, 'capabilities': ['send_email']}, {**PROFILE, 'provider_name': '\ud800'}, None])
def test_profile_rejects_unknown_authority_and_invalid_text(profile):
    configuration = {'practice_context': '', 'bots': [{'role': role, 'name': role, 'enabled': True} for role in ('scribe','visit_prep','follow_up','chief')], 'practice_profile': profile}
    with pytest.raises(ValidationError):
        TeamConfiguration.model_validate(configuration)


def test_profile_cannot_exceed_existing_helper_context_budget():
    with pytest.raises(ValidationError):
        TeamConfiguration.model_validate({'practice_context': 'x'*1000, 'bots': [{'role': role, 'name': role, 'enabled': True} for role in ('scribe','visit_prep','follow_up','chief')], 'practice_profile': PROFILE})
