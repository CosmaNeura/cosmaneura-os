"""Existing encrypted OAuth grant authorizes the selected Outlook read path."""
import json

import httpx
import pytest
from sqlalchemy import select
from tests.unit.test_microsoft_message import ID, message
from tests.unit.test_personal_connection_failure import connection as connection
from tests.unit.test_personal_connection_failure import start

from cosmas_os.adapters.microsoft_connection import MicrosoftPersonalConnection
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.models import ExternalIdentity
from cosmas_os.ports.microsoft_message import MicrosoftMessageSelection


@pytest.mark.parametrize("connection", [MicrosoftPersonalConnection], indirect=True)
def test_existing_sealed_mail_read_grant_reads_one_message_with_no_new_scope(connection):
    f = connection
    f.service.settings.workspace_microsoft_message_available = True
    assert f.service.callback(start(f), "synthetic_PRIVATE_code")
    before = len(f.requests)
    proof = f.service.message_binding(f.identity, require_full=True)
    assert f.service.message_status(f.identity)["full_mail_read"] is True
    assert len(f.requests) == before
    with f.factory() as session:
        credential = session.get(f.service.Credential, f.account)
        private = f.service._open(credential.sealed, "credential", f.account, credential.binding_digest)
        private["token"] = "synthetic_PRIVATE_refreshed_token"
        credential.sealed = f.service._seal(private, "credential", f.account, credential.binding_digest)
        session.commit()
    assert f.service.message_binding(f.identity, require_full=True) == proof
    f.service._client.close()
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"},
                              stream=httpx.ByteStream(json.dumps(message()).encode()))

    f.service._client = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False)
    result = f.service.read_message(f.identity, MicrosoftMessageSelection(message_id=ID))
    assert result.status == "complete" and result.custody == proof
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].headers["Authorization"] == "Bearer synthetic_PRIVATE_refreshed_token"


@pytest.mark.parametrize("connection", [MicrosoftPersonalConnection], indirect=True)
@pytest.mark.parametrize("state", ["pending", "exchanging"])
def test_unfinished_replacement_never_discloses_previous_account_or_message_grant(connection, state):
    f = connection
    f.service.settings.workspace_microsoft_message_available = True
    assert f.service.callback(start(f), "synthetic_PRIVATE_code")
    start(f)
    with f.factory() as session:
        attempt = session.scalar(select(f.service.Attempt).where(
            f.service.Attempt.account_id == f.account, f.service.Attempt.status == "pending"))
        assert attempt is not None
        attempt.status = state
        session.commit()
    before = len(f.requests)
    assert f.service.message_status(f.identity) == {"contract_version": 1, "state": "sign_in_required",
                                                   "full_mail_read": False, "account": None}
    with pytest.raises(WorkspaceError, match="microsoft_message_grant_unavailable"):
        f.service.message_binding(f.identity, require_full=True)
    assert len(f.requests) == before


@pytest.mark.parametrize("connection", [MicrosoftPersonalConnection], indirect=True)
@pytest.mark.parametrize("change", ["disconnect", "owner", "installed_config"])
def test_changed_authority_withholds_grant_without_refresh_or_provider_access(connection, change):
    f = connection
    f.service.settings.workspace_microsoft_message_available = True
    assert f.service.callback(start(f), "synthetic_PRIVATE_code")
    if change == "disconnect":
        f.service.disconnect(f.identity)
    elif change == "owner":
        with f.factory() as session:
            account = session.get(ExternalIdentity, f.account)
            assert account is not None
            account.active = False
            session.commit()
    else:
        f.service.config_digest = "e" * 64
    before = len(f.requests)
    with pytest.raises(WorkspaceError):
        f.service.message_binding(f.identity, require_full=True)
    assert len(f.requests) == before


@pytest.mark.parametrize("connection", [MicrosoftPersonalConnection], indirect=True)
@pytest.mark.parametrize("race", ["none", "refresh", "replacement", "refreshing"])
def test_graph_401_invalidates_only_the_exact_failed_token_and_connection(connection, race):
    from datetime import timedelta

    f = connection
    f.service.settings.workspace_microsoft_message_available = True
    assert f.service.callback(start(f), "synthetic_PRIVATE_code")
    f.service._client.close()
    requests = []
    original = f.service.message_binding(f.identity)

    def handle(request):
        requests.append(request)
        if race != "none":
            with f.factory() as session:
                credential = session.get(f.service.Credential, f.account)
                assert credential is not None
                if race == "refreshing":
                    credential.status = "refreshing"
                else:
                    private = f.service._open(credential.sealed, "credential", f.account, credential.binding_digest)
                    private["token"] = "synthetic_PRIVATE_new_token"
                    credential.sealed = f.service._seal(private, "credential", f.account, credential.binding_digest)
                    if race == "replacement":
                        credential.connected_at += timedelta(seconds=1)
                session.commit()
        return httpx.Response(401, headers={"content-type": "application/json"},
                              stream=httpx.ByteStream(b'{"private":"never disclose"}'))

    f.service._client = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False)
    with pytest.raises(WorkspaceError, match="microsoft_message_authentication_required"):
        f.service.read_message(f.identity, MicrosoftMessageSelection(message_id=ID))
    assert len(requests) == 1
    with f.factory() as session:
        credential = session.get(f.service.Credential, f.account)
        assert credential is not None
        if race == "none":
            assert credential.status == "failed" and credential.sealed is None
            assert f.service.message_status(f.identity)["state"] == "sign_in_required"
        else:
            assert credential.status == ("refreshing" if race == "refreshing" else "ready")
            assert credential.sealed is not None
            if race == "refresh":
                assert f.service.message_binding(f.identity) == original
            if race == "replacement":
                assert f.service.message_binding(f.identity).connected_at != original.connected_at
