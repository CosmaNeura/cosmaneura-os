"""Actual durable sign-in states never advertise an unfinished replacement grant."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from tests.unit.test_personal_connection_failure import connection as connection
from tests.unit.test_personal_connection_failure import start

from cosmas_os.adapters.google_connection import CALENDAR_SCOPE, SCOPES, GooglePersonalConnection


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
@pytest.mark.parametrize("state", ["pending", "exchanging"])
def test_unfinished_replacement_sign_in_hides_old_calendar_access_without_provider_io(connection, state):
    case = connection
    case.scopes = SCOPES + " " + CALENDAR_SCOPE
    assert case.service.callback(start(case), "synthetic_PRIVATE_code")
    original = case.service.calendar_status(case.identity)
    assert original["state"] == "connected" and original["calendar_read"] is True
    start(case)
    with case.factory() as session:
        attempt = session.scalar(select(case.service.Attempt).where(
            case.service.Attempt.account_id == case.account, case.service.Attempt.status == "pending"))
        assert attempt is not None
        attempt.status = state
        session.commit()
    before = len(case.requests)
    with case.factory() as session:
        assert case.service.calendar_status(case.identity, session=session) == {
            "contract_version": 1, "state": "sign_in_required", "calendar_read": False, "account": None}
        # The supplied session remains owned by its caller; the status did not commit it.
        assert session.in_transaction()
    assert len(case.requests) == before
    assert case.service.status(case.identity)["state"] == (
        "sign_in_pending" if state == "pending" else "completing_sign_in")


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
@pytest.mark.parametrize("change", ["expired", "failed", "old_binding"])
def test_finished_or_noncurrent_attempt_does_not_hide_existing_current_calendar_grant(connection, change):
    case = connection
    case.scopes = SCOPES + " " + CALENDAR_SCOPE
    assert case.service.callback(start(case), "synthetic_PRIVATE_code")
    original = case.service.calendar_status(case.identity)
    start(case)
    with case.factory() as session:
        attempt = session.scalar(select(case.service.Attempt).where(
            case.service.Attempt.account_id == case.account, case.service.Attempt.status == "pending"))
        assert attempt is not None
        if change == "expired":
            attempt.created_at = case.service.now() - timedelta(minutes=11)
            attempt.expires_at = case.service.now() - timedelta(minutes=1)
        elif change == "failed":
            attempt.status = "failed"
        else:
            attempt.binding_digest = "0" * 64
        session.commit()
    before = len(case.requests)
    assert case.service.calendar_status(case.identity) == original
    assert len(case.requests) == before


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
def test_completed_replacement_restores_status_from_new_calendar_grant(connection):
    case = connection
    case.scopes = SCOPES + " " + CALENDAR_SCOPE
    assert case.service.callback(start(case), "synthetic_PRIVATE_code")
    assert case.service.calendar_status(case.identity)["calendar_read"] is True
    replacement = start(case)
    assert case.service.calendar_status(case.identity)["state"] == "sign_in_required"
    # The provider did not grant calendar access to the replacement account.
    case.scopes = SCOPES
    assert case.service.callback(replacement, "synthetic_PRIVATE_replacement_code")
    before = len(case.requests)
    assert case.service.calendar_status(case.identity) == {
        "contract_version": 1, "state": "connected", "calendar_read": False,
        "account": {"label": "Gmail", "email": "member@example.invalid"}}
    assert len(case.requests) == before
