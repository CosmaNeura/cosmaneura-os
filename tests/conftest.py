from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
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
