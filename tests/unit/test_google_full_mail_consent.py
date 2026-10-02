"""Durable separate Gmail-body consent; provider HTTP and identities are invented."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select
from tests.unit.test_personal_connection_failure import connection as connection

from cosmas_os.adapters.google_connection import (
    CALENDAR_SCOPE,
    FULL_MAIL_SCOPE,
    SCOPES,
    GooglePersonalConnection,
)
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable

FULL_SCOPES = SCOPES + " " + CALENDAR_SCOPE + " " + FULL_MAIL_SCOPE


def full_start(case):
    case.service.settings.workspace_google_message_available = True
    return parse_qs(urlsplit(case.service.start_full_mail(case.identity)["authorization_url"]).query)


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
def test_separate_body_consent_is_sealed_and_exact_without_altering_legacy_status(connection, caplog):
    case = connection
    fields = full_start(case)
    assert fields["scope"] == [FULL_SCOPES] and case.requests == []
    with case.factory() as session:
        attempt = session.scalar(select(case.service.Attempt).where(case.service.Attempt.account_id == case.account))
        account, _, binding = case.service._account(session, identity=case.identity)
        private = case.service._open(attempt.sealed, "attempt", account.id, binding, attempt.id)
        assert private["full_mail"] is True and private["state"] == fields["state"][0]
    case.scopes = FULL_SCOPES
    assert case.service.callback(fields["state"][0], "synthetic_PRIVATE_code")
    assert case.calls == ["POST", "GET"]
    assert case.service.status(case.identity, include_capabilities=True)["capabilities"] == {"mail": True, "calendar": True}
    custody = case.service.message_binding(case.identity, require_full=True)
    assert custody.account_id == case.account and len(custody.grant_sha256) == 64
    assert "PRIVATE" not in caplog.text and fields["state"][0] not in caplog.text


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
@pytest.mark.parametrize("full_first", [False, True])
def test_pending_consent_cannot_switch_grant_type_without_new_human_action(connection, full_first):
    case = connection
    case.service.settings.workspace_google_message_available = True
    first = case.service.start_full_mail if full_first else case.service.start
    other = case.service.start if full_first else case.service.start_full_mail
    result = first(case.identity)
    assert first(case.identity) == result
    with pytest.raises(WorkspaceError, match="google_sign_in_in_progress"):
        other(case.identity)
    assert case.requests == []
    with case.factory() as session:
        assert len(session.scalars(select(case.service.Attempt).where(case.service.Attempt.account_id == case.account)).all()) == 1


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
@pytest.mark.parametrize("scopes", [SCOPES, SCOPES + " " + CALENDAR_SCOPE,
    FULL_SCOPES + " https://www.googleapis.com/auth/gmail.send"])
def test_declined_or_changed_full_grant_never_saves_partial_or_broader_credential(connection, scopes):
    case = connection
    fields = full_start(case)
    case.scopes = scopes
    assert not case.service.callback(fields["state"][0], "synthetic_PRIVATE_code")
    assert case.calls == ["POST"]
    assert not case.service.callback(fields["state"][0], "synthetic_PRIVATE_code")
    assert case.calls == ["POST"]
    with case.factory() as session:
        assert session.get(case.service.Credential, case.account) is None


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
def test_legacy_metadata_consent_cannot_implicitly_accept_full_body_permission(connection):
    case = connection
    fields = parse_qs(urlsplit(case.service.start(case.identity)["authorization_url"]).query)
    assert fields["scope"] == [SCOPES + " " + CALENDAR_SCOPE]
    case.scopes = FULL_SCOPES
    assert not case.service.callback(fields["state"][0], "synthetic_PRIVATE_code")
    assert case.calls == ["POST"]


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
def test_declining_full_consent_retains_existing_metadata_and_calendar_credential(connection):
    case = connection
    case.scopes = SCOPES + " " + CALENDAR_SCOPE
    fields = parse_qs(urlsplit(case.service.start(case.identity)["authorization_url"]).query)
    assert case.service.callback(fields["state"][0], "synthetic_PRIVATE_code")
    before = case.service.message_binding(case.identity)
    full = full_start(case)
    assert not case.service.callback(full["state"][0], denied=True)
    assert case.service.message_binding(case.identity) == before
    with pytest.raises(WorkspaceError, match="google_mail_consent_required"):
        case.service.message_binding(case.identity, require_full=True)
    assert case.calls == ["POST", "GET"]


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
@pytest.mark.parametrize("downgrade", [False, True])
def test_refresh_preserves_semantic_custody_and_rejects_permission_downgrade(connection, downgrade):
    case = connection
    fields = full_start(case)
    case.scopes = FULL_SCOPES
    assert case.service.callback(fields["state"][0], "synthetic_PRIVATE_code")
    before = case.service.message_binding(case.identity, require_full=True)
    with case.factory() as session:
        credential = session.get(case.service.Credential, case.account)
        sealed = credential.sealed
        credential.expires_at = case.service.now() + timedelta(seconds=30)
        session.commit()
    assert case.service.message_binding(case.identity, require_full=True) == before
    if downgrade:
        case.scopes = SCOPES + " " + CALENDAR_SCOPE
        with pytest.raises(ConnectorUnavailable):
            case.service.credential(case.identity)
        with pytest.raises(WorkspaceError, match="google_connection_changed"):
            case.service.message_binding(case.identity, require_full=True)
        assert case.calls == ["POST", "GET", "POST"]
        with case.factory() as session:
            credential = session.get(case.service.Credential, case.account)
            assert credential.status == "failed" and credential.sealed is None
    else:
        private, _, _ = case.service.credential(case.identity)
        assert private["mail_full_read"] is True
        assert case.service.message_binding(case.identity, require_full=True) == before
        assert case.calls == ["POST", "GET", "POST", "GET"]
        with case.factory() as session:
            assert session.get(case.service.Credential, case.account).sealed != sealed
