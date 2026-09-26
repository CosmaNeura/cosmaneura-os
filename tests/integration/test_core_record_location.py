"""Actual signed OS/SQL boundary; Core is an injected port in these tests."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, get_ident
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from tests.integration.test_workspace_capture import LocalCore
from tests.integration.test_workspace_capture import capture_case as _capture_case

from cosmas_os.api import app as api
from cosmas_os.api import core_record_routes
from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, PatientLink

capture_case = _capture_case


@pytest.fixture
def record_case(capture_case, monkeypatch):
    f = capture_case
    f.configuration.workspace_core_record_enabled = True
    f.configuration.core_web_origin = "https://core.example.invalid"
    f.path = f"/workspaces/{f.workspace['id']}/cosmaneura-record/location"
    f.worker_sessions = []
    f.worker_closed = []
    f.worker_settled = Event()
    f.worker_ports = []
    f.worker_ports_closed = []
    f.binding_transform = lambda value: value
    f.record_engine = f.engine
    caller_thread = get_ident()
    assert f.client.portal is not None
    request_thread = f.client.portal.call(get_ident)
    # capture_case commits its seed, then reads expired IDs. End that read-only
    # setup transaction before the independent lock test takes its blocker lock.
    assert not (f.session.new or f.session.dirty or f.session.deleted)
    f.session.rollback()

    class WorkerSession(Session):
        def __init__(self):
            self.owner_thread = get_ident()
            assert self.owner_thread not in {caller_thread, request_thread}
            self.settled = Event()
            f.worker_settled.clear()
            super().__init__(f.record_engine, autoflush=False)
            f.worker_sessions.append(self)

        def close(self):
            assert get_ident() == self.owner_thread
            super().close()
            f.worker_closed.append(self)
            self.settled.set()
            f.worker_settled.set()

    class WorkerCore(LocalCore):
        def __init__(self):
            super().__init__()
            self.owner_thread = get_ident()
            assert self.owner_thread not in {caller_thread, request_thread}
            # Only invented observations and explicit test hooks are shared.
            self.calls, self.after = f.port.calls, f.port.after
            f.worker_ports.append(self)

        def step(self, name):
            assert get_ident() == self.owner_thread
            super().step(name)

        def resolve_binding(self, selection, credential):
            return f.binding_transform(super().resolve_binding(selection, credential))

        def admit_capture(self, *_args):
            raise AssertionError("Location must never admit a capture session")

        def close(self):
            assert get_ident() == self.owner_thread
            f.worker_ports_closed.append(self)

    @contextmanager
    def connection_factory(_settings, budget):
        assert get_ident() not in {caller_thread, request_thread}
        budget.check()
        # This is a pure Core test double, with no sockets or credentials.
        # Construct it here; no request-owned resource or bound method is reused.
        port = WorkerCore()
        try:
            yield port
        finally:
            port.close()

    monkeypatch.setattr(api, "SessionLocal", WorkerSession)
    monkeypatch.setattr(api, "core_record_connection", connection_factory)
    try:
        yield f
    finally:
        for worker in f.worker_sessions:
            assert worker.settled.wait(2), "The worker must settle after owned locks are released"
        assert f.worker_sessions == f.worker_closed
        assert f.worker_ports == f.worker_ports_closed


def read(f, **kwargs):
    headers = {
        "Authorization": "Bearer " + f.token(),
        "X-Cosmas-Record-Contract": "1",
        **kwargs.pop("headers", {}),
    }
    return f.client.get(f.path, headers=headers, **kwargs)


def test_same_record_opens_without_a_capture_session_note_model_or_workspace_write(record_case):
    f = record_case
    with Session(f.engine) as session:
        before = session.execute(
            text("SELECT row_to_json(w)::text FROM encounter_workspaces w WHERE id=:id"),
            {"id": f.workspace["id"]},
        ).scalar_one()
    response = read(f)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "contract_version",
        "workspace_id",
        "appointment_ref",
        "href",
        "checked_at",
    }
    assert (
        body["workspace_id"] == f.workspace["id"]
        and body["appointment_ref"] == f.appointment.external_id
    )
    assert body["href"] == f.configuration.core_web_origin + "/notes/" + f.appointment.external_id
    assert response.headers["cache-control"] == "no-store"
    assert f.port.calls == ["exchange", "resolve", "binding"] and f.port.saved is None
    with Session(f.engine) as session:
        after = session.execute(
            text("SELECT row_to_json(w)::text FROM encounter_workspaces w WHERE id=:id"),
            {"id": f.workspace["id"]},
        ).scalar_one()
    assert before == after


@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding"])
@pytest.mark.parametrize("target", ["identity", "account", "patient"])
def test_revocation_between_remote_phases_prevents_location_disclosure(record_case, phase, target):
    f = record_case

    def revoke(observed):
        if phase != observed:
            return
        with Session(f.engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '1s'"))
            if target == "identity":
                row = session.get(ExternalIdentity, f.identity_id)
                assert row is not None
                row.active = False
            elif target == "account":
                row = session.get(CoreCaptureAccount, f.account_id)
                assert row is not None
                row.revoked_at = datetime.now(UTC)
            else:
                row = session.get(PatientLink, f.patient_link_id)
                assert row is not None
                row.revoked_at = datetime.now(UTC)
            session.commit()

    f.port.after = revoke
    response = read(f)
    assert response.status_code in {403, 404, 409}, response.text
    assert "href" not in response.text and f.port.saved is None
    assert (
        f.port.calls
        == ["exchange", "resolve", "binding"][: ["exchange", "resolve", "binding"].index(phase) + 1]
    )


@pytest.mark.parametrize(
    "field", ["workspace_id", "appointment_ref", "actor_ref", "tenant_ref", "checked_at"]
)
def test_wrong_or_stale_core_binding_never_becomes_a_link(record_case, field):
    f = record_case
    def changed(result):
        value = (
            uuid4()
            if field == "workspace_id"
            else datetime.now(UTC) - timedelta(seconds=31)
            if field == "checked_at"
            else getattr(result, field)[:-1] + "2"
        )
        return result.model_copy(update={field: value})

    f.binding_transform = changed
    response = read(f)
    assert response.status_code in {409, 503} and "href" not in response.text


@pytest.mark.parametrize(
    "header,value",
    [
        ("X-Cosmas-Record-Contract", "2"),
        ("X-Cosmas-Record-Contract", "1, 1"),
        ("X-Box-Id", "invented"),
        ("Content-Encoding", "gzip"),
        ("Content-Length", "00"),
    ],
)
def test_unaccepted_request_never_contacts_core(record_case, header, value):
    response = read(record_case, headers={header: value})
    assert response.status_code in {401, 403, 422, 426}, response.text
    assert record_case.port.calls == []


def test_default_off_configuration_query_override_and_unknown_workspace(record_case):
    f = record_case
    f.configuration.workspace_core_record_enabled = False
    assert read(f).status_code == 404 and f.port.calls == []
    f.configuration.workspace_core_record_enabled = True
    assert read(f, params={"destination": "https://other.invalid"}).status_code == 422
    f.path = f"/workspaces/{uuid4()}/cosmaneura-record/location"
    assert read(f).status_code == 404 and f.port.calls == []


@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding"])
def test_feature_disable_and_destination_change_in_flight_are_rechecked(record_case, phase):
    f = record_case

    def change(observed):
        if phase == observed:
            f.configuration.core_web_origin = "https://changed.example.invalid"

    f.port.after = change
    assert read(f).status_code == 409
    assert (
        f.port.calls
        == ["exchange", "resolve", "binding"][: ["exchange", "resolve", "binding"].index(phase) + 1]
    )


def test_actual_postgres_lock_is_bounded_before_any_core_phase(record_case, monkeypatch):
    f = record_case
    monkeypatch.setattr(core_record_routes, "DEADLINE_SECONDS", 0.15)
    with f.engine.connect() as blocker:
        transaction = blocker.begin()
        try:
            blocker.execute(text("SET LOCAL lock_timeout = '2s'"))
            blocker.execute(text("LOCK TABLE external_identities IN ACCESS EXCLUSIVE MODE"))
            started = monotonic()
            result = read(f)
            assert monotonic() - started < 2
            assert result.status_code in {503, 504}
            assert "href" not in result.text and f.port.calls == []
        finally:
            transaction.rollback()
    assert f.worker_settled.wait(2)
    assert f.port.calls == []


def test_late_pool_acquisition_closes_in_worker_without_core_dispatch(record_case, monkeypatch):
    f = record_case
    monkeypatch.setattr(core_record_routes, "DEADLINE_SECONDS", 0.05)
    owned = create_engine(f.engine.url, pool_size=1, max_overflow=0, pool_timeout=1)
    held = owned.connect()
    f.record_engine = owned
    try:
        started = monotonic()
        result = read(f)
        assert monotonic() - started < 0.8
        assert result.status_code == 504 and "href" not in result.text
        assert f.port.calls == []
    finally:
        held.close()
        assert f.worker_settled.wait(2)
        owned.dispose()
    assert f.port.calls == []
