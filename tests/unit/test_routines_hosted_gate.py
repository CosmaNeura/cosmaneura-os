"""Hosted startup exercises the real routine pass without a database or provider."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url
from tests.unit.test_hosted_workspace_config import hosted

from cosmas_os.application import follow_up, routines, shared_work
from cosmas_os.application import workspace as ws
from cosmas_os.application.worker_progress import WorkerProgress, workspace_workers_ready
from cosmas_os.config import Settings

HOSTED_DATABASE = (
    "postgresql+psycopg://invented:invented@postgres:5432/cosmas_os"
    "?sslmode=verify-full&sslrootcert=system"
)


class EmptySession:
    def __init__(self, url):
        self.url = make_url(url)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_bind(self):
        return SimpleNamespace(engine=SimpleNamespace(url=self.url))

    def execute(self, statement):
        assert statement.is_select
        self.statements.append(statement)
        return []


@pytest.fixture
def configuration(monkeypatch):
    value = hosted(database_url=HOSTED_DATABASE, workspace_routines_enabled=True)
    value.validate_runtime_configuration()
    monkeypatch.setattr(routines, "settings", value)
    monkeypatch.setattr(follow_up, "settings", value)
    return value


def test_real_hosted_empty_pass_establishes_then_clears_worker_readiness(configuration):
    session = EmptySession(configuration.database_url)
    progress = WorkerProgress(300)
    application = SimpleNamespace(
        state=SimpleNamespace(workspace_worker_progress={"routines": progress})
    )
    observed = []

    class Stop:
        done = False

        def is_set(self):
            return self.done

        async def wait(self):
            observed.append(workspace_workers_ready(application, configuration))
            self.done = True

    assert not workspace_workers_ready(application, configuration)
    asyncio.run(routines.run_worker(lambda: session, Stop(), progress=progress))
    assert observed == [True]
    assert not workspace_workers_ready(application, configuration)
    assert len(session.statements) == 1
    assert "routine_revisions" in str(session.statements[0])


@pytest.mark.parametrize(
    "changes",
    [
        {"host": "another-db.example.invalid"},
        {"database": "another_database"},
        {"username": "postgres"},
        {"query": {"sslmode": "require", "sslrootcert": "system"}},
    ],
)
def test_hosted_pass_rejects_another_connection_before_query(configuration, changes):
    session = EmptySession(make_url(configuration.database_url).set(**changes))
    with pytest.raises(ws.WorkspaceError, match="routines_connection_required"):
        routines.process_batch(lambda: session)
    assert not session.statements


@pytest.mark.parametrize(
    "changes, error",
    [
        ({"workspace_routines_enabled": False}, "routines_unavailable"),
        ({"workspace_enabled": False}, "routines_connection_required"),
        ({"workspace_authenticated_enabled": False}, "routines_connection_required"),
        ({"human_deploy_evidence_ref": None}, "routines_connection_required"),
        ({"workspace_hosted_enabled": False}, "follow_up_connection_required"),
        (
            {
                "data_mode": "authorized_beta",
                "clinic_approval_ref": "invented:clinic",
                "baa_evidence_ref": "invented:baa",
                "phi_authorization_ref": "invented:phi",
            },
            "routines_connection_required",
        ),
    ],
)
def test_hosted_gate_requires_current_synthetic_profile(configuration, changes, error):
    session = EmptySession(configuration.database_url)
    for name, value in changes.items():
        setattr(configuration, name, value)
    with pytest.raises(ws.WorkspaceError, match=error):
        routines.process_batch(lambda: session)
    assert not session.statements


def test_hosted_gate_does_not_fall_back_to_a_local_session(configuration):
    session = EmptySession("postgresql+psycopg://invented@127.0.0.1/w1a_rehearsal")
    with pytest.raises(ws.WorkspaceError, match="routines_connection_required"):
        routines.process_batch(lambda: session)
    assert not session.statements


def test_local_rehearsal_pass_and_revocation_remain_supported(monkeypatch):
    value = Settings(
        _env_file=None,
        workspace_enabled=True,
        workspace_routines_enabled=True,
        database_url="postgresql+psycopg://invented@127.0.0.1/w1a_rehearsal",
    )
    monkeypatch.setattr(routines, "settings", value)
    monkeypatch.setattr(follow_up, "settings", value)
    session = EmptySession(value.database_url)
    assert routines.process_batch(lambda: session) is None
    value.workspace_routines_enabled = False
    with pytest.raises(ws.WorkspaceError, match="routines_unavailable"):
        routines.process_batch(lambda: session)
    assert len(session.statements) == 1


def test_hosted_read_gate_does_not_open_responsibility_changes_or_delivery(configuration):
    session = EmptySession(configuration.database_url)
    routines._local(session)
    shared_work._read_connection(session, False)
    with pytest.raises(ws.WorkspaceError, match="follow_up_connection_required"):
        shared_work._target(session, "invented-box", "invented-owner", "invented-ticket", writing=True)
    with pytest.raises(ws.WorkspaceError, match="follow_up_connection_required"):
        follow_up.deliver(
            session,
            "invented-box",
            "invented-owner",
            "invented-workspace",
            "invented-ticket",
            revision_id="invented-revision",
            digest="invented-digest",
        )
    assert not session.statements


@pytest.mark.parametrize("changes", [{"writing": True}, {"recipient": "invented-recipient"}])
def test_routine_read_option_cannot_be_used_for_a_mutating_target(configuration, changes):
    session = EmptySession(configuration.database_url)
    with pytest.raises(ws.WorkspaceError, match="routine_read_only"):
        shared_work._target(
            session,
            "invented-box",
            "invented-owner",
            "invented-ticket",
            _routine_read=True,
            **changes,
        )
    assert not session.statements
