from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from cosmas_os.adapters.local import FakeNotifyAdapter, InjectableClock, LocalBlobAdapter
from cosmas_os.application import services as svc
from cosmas_os.db import make_engine, make_session_factory
from cosmas_os.model_registry import metadata


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://cosmas:cosmas@localhost:54329/cosmas_os"
    )
    eng = make_engine(url)
    metadata.create_all(eng)
    yield eng


@pytest.fixture(autouse=True)
def owned_database_isolation(request):
    """Committed worker tests must not consume another test's pending work."""
    token = os.environ.get("COSMAS_TEST_DATABASE_TOKEN")
    if not token or "engine" not in request.fixturenames:
        return
    eng = request.getfixturevalue("engine")
    if eng.url.host != "127.0.0.1" or eng.url.database != "w1a_local_checks":
        raise RuntimeError("Test isolation requires the owned local database")
    with eng.begin() as connection:
        marker = connection.scalar(text(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()"
        ))
        if marker != "cosmas-local-workspace:" + token:
            raise RuntimeError("Test database ownership marker does not match")
        tables = ", ".join(eng.dialect.identifier_preparer.format_table(table)
                           for table in metadata.sorted_tables)
        connection.exec_driver_sql("TRUNCATE TABLE " + tables + " RESTART IDENTITY CASCADE")


@pytest.fixture
def session(engine) -> Iterator[Session]:
    connection = engine.connect()
    trans = connection.begin()
    SessionLocal = make_session_factory(engine)
    # Application services deliberately commit/rollback their own unit of work.
    # Keep each test isolated behind a savepoint without de-associating the
    # fixture's outer transaction when an expected failure rolls back.
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture
def clock() -> InjectableClock:
    return InjectableClock(datetime(2026, 9, 2, 12, 0, tzinfo=UTC))


@pytest.fixture
def blob(tmp_path: Path) -> LocalBlobAdapter:
    return LocalBlobAdapter(tmp_path / "blobs")


@pytest.fixture
def notify() -> FakeNotifyAdapter:
    return FakeNotifyAdapter()


@pytest.fixture
def container(session, clock, blob, notify) -> svc.Container:
    return svc.Container(session, clock=clock, blob=blob, notify=notify)


@pytest.fixture
def seeded(container: svc.Container) -> dict:
    return svc.provision_box(container, "Test Clinic")
