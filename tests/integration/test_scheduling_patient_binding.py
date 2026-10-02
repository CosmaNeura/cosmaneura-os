"""Actual sealed Google staff grants remain stable across refresh, not reconnect."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.orm import Session
from tests.integration.test_scheduling_patient_setup import case as patient_case
from tests.unit.test_scheduling_runtime import configuration as runtime_configuration

from cosmas_os.adapters.scheduling_enrollment import SchedulingEnrollmentService
from cosmas_os.adapters.scheduling_google_login import SchedulingGoogleLogin
from cosmas_os.application import model_work
from cosmas_os.models import ExternalIdentity, SchedulingAccount
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.scheduling_login_models import SchedulingLoginCredential

case = patient_case
configuration = runtime_configuration


@pytest.fixture
def sealed(case, configuration):
    f = case
    now = datetime.now(UTC)
    configuration.workspace_scheduling_login_enabled = True
    configuration.scheduling_origin = "https://scheduling.example.invalid"
    configuration.scheduling_login_return_origin = "https://workspace.example.invalid"
    configuration.scheduling_google_callback_uri = "https://workspace.example.invalid/connections/scheduling/google/callback"
    configuration.scheduling_google_client_id = "invented.apps.googleusercontent.com"
    configuration.scheduling_google_client_secret = SecretStr("invented-client-secret")
    configuration.scheduling_login_encryption_key = SecretStr(base64.urlsafe_b64encode(bytes(range(32))).decode())

    def forbidden(*_args, **_kwargs):
        pytest.fail("Reading the existing staff grant must not refresh, use network, or create another Session")

    login = SchedulingGoogleLogin(configuration, forbidden, now=lambda: now,
        google_transport=httpx.MockTransport(forbidden), scheduling_transport=httpx.MockTransport(forbidden))
    account, selected, binding = login._account(f.s, account_id=f.account)
    account_id = account.id
    credential = f.s.get(SchedulingLoginCredential, account_id)
    assert credential is not None
    private = {"token": "invented-access-token", "refresh": "invented-refresh-token", "subject": "invented-google-subject"}
    credential.binding_digest = binding
    credential.sealed = login._seal(private, "credential", account_id, binding)
    credential.connected_at = now - timedelta(minutes=5)
    credential.expires_at = now + timedelta(hours=1)
    f.s.commit()
    try:
        yield f, configuration, login, account_id, selected, binding, private, now
    finally:
        login.close()


def read(sealed):
    f, _configuration, login, account_id, _selected, _binding, _private, _now = sealed
    account = f.s.get(SchedulingAccount, account_id)
    assert account is not None
    return login.patient_setup_binding(f.s, f.identity, account)


def test_actual_cipher_refresh_keeps_semantic_grant_and_shared_read_locks(sealed):
    f, _configuration, login, account_id, selected, binding, private, _now = sealed
    first = read(sealed)
    f.s.commit()
    credential = f.s.get(SchedulingLoginCredential, account_id)
    assert credential is not None
    original_ciphertext = bytes(credential.sealed)
    credential.sealed = login._seal({**private, "token": "invented-refreshed-access", "refresh": "invented-rotated-refresh"},
        "credential", account_id, binding)
    assert credential.sealed != original_ciphertext
    f.s.commit()
    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    connection = f.s.connection()
    event.listen(connection, "before_cursor_execute", observe)
    try:
        second = read(sealed)
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    assert second == first
    assert second.selection == selected and second.binding_sha256 == binding
    assert sum("FOR SHARE" in statement for statement in statements) == 3
    assert not any("FOR UPDATE" in statement or statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements)
    assert private["token"] not in repr(second) and private["refresh"] not in repr(second)


@pytest.mark.parametrize("selector", ["identity", "account_id", "selection"])
def test_login_and_patient_grant_use_human_first_lock_order_without_deadlock(sealed, selector):
    f, _configuration, login, account_id, selected, _binding, _private, _now = sealed
    f.s.commit()
    engine = f.s.get_bind()
    owner_locked, login_waiting_for_owner = Event(), Event()
    statements = []

    def signing_in():
        assert owner_locked.wait(5)
        with Session(engine) as s:
            connection = s.connection()

            def before(_connection, _cursor, statement, _parameters, _context, _executemany):
                statements.append(statement)
                if "FROM principals" in statement and "FOR UPDATE" in statement:
                    login_waiting_for_owner.set()

            event.listen(connection, "before_cursor_execute", before)
            try:
                args = {"identity": SimpleNamespace(auth_mode="clerk_jwt", external_identity_id=f.identity,
                    box_id=f.box, principal_id=f.owner)} if selector == "identity" else {
                    "account_id": account_id} if selector == "account_id" else {"selection": selected}
                account, observed, _ = login._account(s, **args)
                assert account.id == account_id and observed == selected
                s.commit()
            finally:
                event.remove(connection, "before_cursor_execute", before)

    with ThreadPoolExecutor(max_workers=1) as pool, Session(engine) as s:
        model_work.lock_owner(s, f.box, f.owner)
        owner_locked.set()
        pending = pool.submit(signing_in)
        try:
            assert login_waiting_for_owner.wait(5)
            # Login is waiting for this human, so it must not hold a conflicting
            # account lock while patient setup reads the same sealed grant.
            account = s.get(SchedulingAccount, account_id)
            assert account is not None
            observed = login.patient_setup_binding(s, f.identity, account)
            assert observed.selection == selected
        finally:
            s.commit()
        pending.result(timeout=10)
    locked = [statement for statement in statements if "FOR UPDATE" in statement]
    assert len(locked) == 2 and "FROM principals" in locked[0] and "scheduling_accounts" in locked[1]


@pytest.mark.parametrize("entry", ["owner", "status"])
def test_enrollment_waits_for_human_before_locking_patient_identity(sealed, entry):
    f, configuration, login, account_id, selected, _binding, _private, _now = sealed
    configuration.workspace_scheduling_enrollment_enabled = True
    configuration.scheduling_enrollment_practice_id = str(selected.practice_id)
    enrollment = SchedulingEnrollmentService(login)
    identity = SimpleNamespace(auth_mode="clerk_jwt", external_identity_id=f.identity,
        box_id=f.box, principal_id=f.owner)
    f.s.commit()
    engine = f.s.get_bind()
    owner_locked, enrollment_waiting = Event(), Event()
    statements = []

    def observing():
        assert owner_locked.wait(5)
        with Session(engine) as s:
            connection = s.connection()
            def before(_connection, _cursor, statement, _parameters, _context, _executemany):
                statements.append(statement)
                if "FROM principals" in statement and "FOR UPDATE" in statement:
                    enrollment_waiting.set()
            event.listen(connection, "before_cursor_execute", before)
            try:
                if entry == "owner":
                    external, _ = enrollment.owner(s, identity)
                    assert external.id == f.identity
                else:
                    # Use the actual installed entry point with this owned
                    # session, avoiding a second session/connection in the test.
                    from contextlib import contextmanager
                    @contextmanager
                    def session_scope():
                        yield s
                    original = login._session
                    login._session = session_scope
                    try:
                        assert enrollment.status(identity, None)["state"] == "connected"
                    finally:
                        login._session = original
                s.commit()
            finally:
                event.remove(connection, "before_cursor_execute", before)

    with ThreadPoolExecutor(max_workers=1) as pool, Session(engine) as s:
        model_work.lock_owner(s, f.box, f.owner)
        owner_locked.set()
        pending = pool.submit(observing)
        try:
            assert enrollment_waiting.wait(5)
            account = s.get(SchedulingAccount, account_id)
            assert account is not None
            assert login.patient_setup_binding(s, f.identity, account).selection == selected
        finally:
            s.commit()
        pending.result(timeout=10)
    locked = [statement for statement in statements if "FOR UPDATE" in statement]
    assert "FROM principals" in locked[1] and "FROM external_identities" in locked[2]


@pytest.mark.parametrize("change", ["reconnect", "google_subject", "external_subject", "organization"])
def test_reconnection_and_identity_changes_invalidate_previous_grant(sealed, change):
    f, _configuration, login, account_id, _selected, binding, private, now = sealed
    first = read(sealed)
    f.s.commit()
    if change == "reconnect":
        credential = f.s.get(SchedulingLoginCredential, account_id)
        assert credential is not None
        credential.connected_at = now
    elif change == "google_subject":
        credential = f.s.get(SchedulingLoginCredential, account_id)
        assert credential is not None
        credential.sealed = login._seal({**private, "subject": "invented-other-google-subject"}, "credential", account_id, binding)
    else:
        identity = f.s.get(ExternalIdentity, f.identity)
        assert identity is not None
        setattr(identity, "subject" if change == "external_subject" else "organization_id", "invented-other-identity")
    f.s.commit()
    second = read(sealed)
    assert second != first
    if change == "reconnect":
        assert second.grant_sha256 == first.grant_sha256 and second.connected_at != first.connected_at
    else:
        assert second.grant_sha256 != first.grant_sha256


@pytest.mark.parametrize("fault", ["tamper", "binding", "expired", "missing_subject", "control_subject", "extra_private_field", "revoked_account", "inactive_identity"])
def test_invalid_current_sealed_grant_refuses_without_network_or_secret_leak(sealed, fault):
    f, _configuration, login, account_id, _selected, binding, private, now = sealed
    credential = f.s.get(SchedulingLoginCredential, account_id)
    assert credential is not None
    if fault == "tamper":
        value = bytearray(credential.sealed)
        value[-1] ^= 1
        credential.sealed = bytes(value)
    elif fault == "binding":
        credential.binding_digest = "f" * 64
    elif fault == "expired":
        credential.expires_at = now
    elif fault in {"missing_subject", "control_subject", "extra_private_field"}:
        value = {**private}
        if fault == "missing_subject":
            value.pop("subject")
        elif fault == "control_subject":
            value["subject"] = "private\nsubject"
        else:
            value["extra"] = "PRIVATE must never appear"
        credential.sealed = login._seal(value, "credential", account_id, binding)
    elif fault == "revoked_account":
        account = f.s.get(SchedulingAccount, account_id)
        assert account is not None
        account.revoked_at = now
    else:
        identity = f.s.get(ExternalIdentity, f.identity)
        assert identity is not None
        identity.active = False
    f.s.commit()
    with pytest.raises(ConnectorUnavailable, match="^scheduling_patient_grant_unavailable$") as error:
        read(sealed)
    assert "PRIVATE" not in str(error.value) and private["token"] not in str(error.value)
