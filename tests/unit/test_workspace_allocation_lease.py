"""Actual PostgreSQL session-lock custody; no provisioning or hosting runs."""
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import text

from cosmas_os.db import make_engine, make_session_factory
from cosmas_os.enrollment.allocation import (
    ProductionWorkspaceAllocator,
    WorkspaceAllocationWorker,
)
from cosmas_os.enrollment.provisioning import ClerkProvisioningPort, EnrollmentProvisioner
from cosmas_os.enrollment.service import EnrollmentService


class ForbiddenHosting(ProductionWorkspaceAllocator):
    def destination(self, request):
        raise AssertionError("A lease check must never choose a hosting destination")

    def allocate(self, plan, *, operation_id):
        raise AssertionError("A lease check must never allocate a workspace")


def worker(engine):
    # Only sessions are used by the actual worker's _lease. The ordinary worker
    # constructor and typed allocator guard are retained; no lease is replaced.
    service = cast(EnrollmentService, SimpleNamespace(sessions=make_session_factory(engine)))
    provisioner = EnrollmentProvisioner(service, cast(ClerkProvisioningPort, SimpleNamespace()))
    return WorkspaceAllocationWorker(service, provisioner, ForbiddenHosting())


@contextmanager
def competing_workers(engine):
    assert engine.dialect.name == "postgresql"
    # Separate pools are essential: a pooled session that leaked the advisory
    # lock could reacquire it reentrantly and falsely look like a release.
    contender = make_engine(engine.url)
    try:
        with engine.connect() as first, contender.connect() as second:
            assert first.scalar(text("SELECT pg_backend_pid()")) != second.scalar(
                text("SELECT pg_backend_pid()"))
        yield worker(engine), worker(contender)
    finally:
        contender.dispose()


def test_postgres_allocation_lease_serializes_same_operation_only(engine):
    operation, independent = str(uuid4()), str(uuid4())
    with competing_workers(engine) as (first, second):
        with first._lease(operation) as acquired:
            assert acquired is True
            with second._lease(operation) as competing:
                assert competing is False
            with second._lease(independent) as other_operation:
                assert other_operation is True
            # A failed contender must not release the original holder's lock.
            with second._lease(operation) as still_owned:
                assert still_owned is False
        with second._lease(operation) as released:
            assert released is True


def test_postgres_allocation_lease_releases_after_worker_exception(engine):
    operation = str(uuid4())
    with competing_workers(engine) as (first, second):
        with pytest.raises(RuntimeError, match="invented worker interruption"):
            with first._lease(operation) as acquired:
                assert acquired is True
                with second._lease(operation) as competing:
                    assert competing is False
                raise RuntimeError("invented worker interruption")
        # This is a different PostgreSQL backend, not the holder's reused pooled
        # connection. The real session-level lock must have been released.
        with second._lease(operation) as released:
            assert released is True
            with first._lease(operation) as competing:
                assert competing is False
