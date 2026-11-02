"""Synthetic onboarding allocation intent/recovery; no hosting is invoked."""
from contextlib import contextmanager
from dataclasses import asdict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cosmas_os.enrollment.allocation import (
    ALLOCATION_OPERATION,
    ProductionWorkspaceAllocator,
    WorkspaceAllocationDestination,
    WorkspaceAllocationScheduler,
    WorkspaceAllocationWorker,
)
from cosmas_os.enrollment.domain import BAA_DOC_ID, BAA_SHA256, BAA_VERSION, EnrollmentError
from cosmas_os.enrollment.models import Acceptance, Command, Membership
from cosmas_os.enrollment.provisioning import EnrollmentProvisioner
from cosmas_os.enrollment.synthetic import create_synthetic_app


@pytest.fixture
def allocation_case():
    app = create_synthetic_app()
    service = app.state.enrollment_service
    service.settings.allowed_workspace_origins.append("https://workspace.example.invalid")
    with TestClient(app) as client:
        token = client.post("/lab/session", json={"user": "owner-a"}).json()["token"]
        identity = app.state.synthetic_identities.verify(token)
        headers = {"Authorization": "Bearer " + token}

        def write(path, body, method="POST"):
            state = client.get("/enrollment/v1/status", headers=headers).json()
            response = client.request(method, "/enrollment/v1" + path,
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"expected_revision": state["revision"], **body})
            assert response.status_code == 200, response.text
            return response.json()

        write("/profile", {"display_name": "Alex Example", "title": "Owner"}, "PUT")
        write("/practice", {"legal_name": "Example Practice LLC", "display_name": "Example Practice",
            "address_line1": "123 Example Street", "city": "Example City", "region": "NY", "postal_code": "10001",
            "administrative_email": "office@example.invalid", "human_seats": 2, "covered_entity": True}, "PUT")

        def accept():
            return write("/baa/accept", {"doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256,
                "signature_name": "Alex Example", "signature_title": "Owner", "authority_confirmed": True, "accepted": True})

        yield service, identity, accept, client, headers


class InventedClerk:
    def __init__(self):
        self.org = None
        self.creates = 0

    def organization(self, slug, binding, name, owner, seats):
        if self.org is None:
            self.creates += 1
            self.org = {"id": "org_invented", "slug": slug, "created_by": owner,
                        "private_metadata": {"cosmas_enrollment": binding}}
        return self.org

    def membership(self, *_):
        pass

    def request(self, method, path):
        assert method == "GET" and path == "/organizations/org_invented"
        return self.org


class InventedAllocation(ProductionWorkspaceAllocator):
    def __init__(self):
        self.calls = []
        self.destination_calls = 0
        self.lose_reply = False
        self.destination_value = WorkspaceAllocationDestination(
            "https://api.workspace.example.invalid", "https://workspace.example.invalid/", "1" * 40, "2" * 64)

    def destination(self, request):
        self.destination_calls += 1
        return self.destination_value

    def allocate(self, plan, *, operation_id):
        self.calls.append((operation_id, asdict(plan)))
        if self.lose_reply:
            self.lose_reply = False
            raise RuntimeError("Invented lost hosting reply; no hosting occurred")


class UncontendedSyntheticWorker(WorkspaceAllocationWorker):
    @contextmanager
    def _lease(self, _):
        # Only the uncontended intent/retry path is simulated here. Production
        # uses the retained Postgres session lock, separately checked on Postgres.
        yield True


def test_saved_acceptance_queues_once_and_keeps_trial_closed(allocation_case):
    service, identity, accept, client, headers = allocation_case
    scheduler = WorkspaceAllocationScheduler(service)
    with pytest.raises(EnrollmentError):
        scheduler.request(identity)
    accept()
    operation = scheduler.request(identity)
    assert operation == scheduler.request(identity)
    with service.sessions() as session:
        rows = list(session.scalars(select(Command).where(Command.operation == ALLOCATION_OPERATION)))
        assert len(rows) == 1 and rows[0].response["state"] == "queued"
    state = client.get("/enrollment/v1/status", headers=headers).json()
    assert state["workspace"]["box_id"] is None
    assert state["billing"]["status"] == "none" and state["billing"]["trial_ends_at"] is None


def test_allocation_lost_reply_reuses_exact_plan_operation_and_org(allocation_case):
    service, identity, accept, client, headers = allocation_case
    accept()
    operation = WorkspaceAllocationScheduler(service).request(identity)
    service.settings.provisioning_enabled = True
    clerk, allocation = InventedClerk(), InventedAllocation()
    worker = UncontendedSyntheticWorker(service, EnrollmentProvisioner(service, clerk), allocation)
    allocation.lose_reply = True
    assert worker.run_one() == operation
    with service.sessions() as session:
        command = session.get(Command, operation)
        assert command.response["state"] == "retry" and command.response["attempts"] == 1
    # A changed host default cannot silently retarget a saved in-flight release.
    allocation.destination_value = WorkspaceAllocationDestination(
        "https://api.workspace.example.invalid", "https://workspace.example.invalid/", "3" * 40, "4" * 64)
    assert worker.run_one() == operation
    assert allocation.calls[0] == allocation.calls[1]
    assert allocation.destination_calls == 1 and clerk.creates == 1
    assert worker.run_one() is None
    state = client.get("/enrollment/v1/status", headers=headers).json()
    assert state["workspace"]["box_id"] == allocation.calls[0][1]["box_id"]
    assert state["billing"]["status"] == "none" and state["billing"]["trial_ends_at"] is None
    assert state["stage"] == "activation_pending"


def test_disabled_worker_leaves_saved_request_queued(allocation_case):
    service, identity, accept, _, _ = allocation_case
    accept()
    operation = WorkspaceAllocationScheduler(service).request(identity)
    service.settings.provisioning_enabled = False
    allocation = InventedAllocation()
    worker = UncontendedSyntheticWorker(service, EnrollmentProvisioner(service, InventedClerk()), allocation)
    assert worker.run_one() is None and allocation.calls == []
    with service.sessions() as session:
        assert session.get(Command, operation).response["state"] == "queued"


def test_revoked_owner_cannot_allocate_or_repair_binding(allocation_case):
    service, identity, accept, _, _ = allocation_case
    accept()
    operation = WorkspaceAllocationScheduler(service).request(identity)
    service.settings.provisioning_enabled = True
    with service.sessions.begin() as session:
        session.scalar(select(Membership)).active = False
    allocation = InventedAllocation()
    worker = UncontendedSyntheticWorker(service, EnrollmentProvisioner(service, InventedClerk()), allocation)
    assert worker.run_one() is None
    assert allocation.calls == []
    with service.sessions() as session:
        assert session.get(Command, operation).response["state"] == "held"
        assert session.scalar(select(Membership)).active is False
    # Repeated worker ticks cannot silently restore membership or start setup.
    assert worker.run_one() is None and allocation.calls == []


def test_revoked_practice_does_not_block_another_owners_allocation(allocation_case):
    service, identity, accept, client, _ = allocation_case
    accept()
    scheduler = WorkspaceAllocationScheduler(service)
    revoked_operation = scheduler.request(identity)
    with service.sessions.begin() as session:
        session.scalar(select(Membership)).active = False
    token = client.post("/lab/session", json={"user": "owner-b"}).json()["token"]
    second_identity = client.app.state.synthetic_identities.verify(token)
    headers = {"Authorization": "Bearer " + token}
    steps = [("PUT", "/profile", {"display_name": "Blake Example", "title": "Owner"}),
        ("PUT", "/practice", {"legal_name": "Second Example LLC", "display_name": "Second Example",
            "address_line1": "456 Example Street", "city": "Example City", "region": "NY", "postal_code": "10001",
            "administrative_email": "second@example.invalid", "human_seats": 2, "covered_entity": True}),
        ("POST", "/baa/accept", {"doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256,
            "signature_name": "Blake Example", "signature_title": "Owner", "authority_confirmed": True,
            "accepted": True})]
    for method, path, body in steps:
        state = client.get("/enrollment/v1/status", headers=headers).json()
        response = client.request(method, "/enrollment/v1" + path,
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"expected_revision": state["revision"], **body})
        assert response.status_code == 200, response.text
    valid_operation = scheduler.request(second_identity)
    service.settings.provisioning_enabled = True
    allocation = InventedAllocation()
    worker = UncontendedSyntheticWorker(service, EnrollmentProvisioner(service, InventedClerk()), allocation)
    assert worker.run_one() == valid_operation
    assert len(allocation.calls) == 1 and allocation.calls[0][0] == valid_operation
    with service.sessions() as session:
        assert session.get(Command, revoked_operation).response["state"] == "held"
        assert session.get(Command, valid_operation).response["state"] == "allocated"
    # Owner recovery requires restored registry authority and preserves intent.
    with pytest.raises(EnrollmentError):
        scheduler.request(identity)


@pytest.mark.parametrize(("field", "value"), [
    ("request", None), ("request", {"practice_id": []}), ("attempts", "invalid"),
])
def test_invalid_saved_request_is_held_without_repeated_worker_failure(allocation_case, field, value):
    service, identity, accept, _, _ = allocation_case
    accept()
    operation = WorkspaceAllocationScheduler(service).request(identity)
    with service.sessions.begin() as session:
        command = session.get(Command, operation)
        command.response = {**command.response, field: value}
    service.settings.provisioning_enabled = True
    allocation = InventedAllocation()
    worker = UncontendedSyntheticWorker(service, EnrollmentProvisioner(service, InventedClerk()), allocation)
    assert worker.run_one() is None and worker.run_one() is None
    assert allocation.calls == []
    with service.sessions() as session:
        assert session.get(Command, operation).response["state"] == "held"


def test_conflicting_saved_plan_is_held_and_never_retargets_hosting(allocation_case):
    service, identity, accept, _, _ = allocation_case
    accept()
    operation = WorkspaceAllocationScheduler(service).request(identity)
    service.settings.provisioning_enabled = True
    allocation = InventedAllocation()
    provisioner = EnrollmentProvisioner(service, InventedClerk())
    worker = UncontendedSyntheticWorker(service, provisioner, allocation)
    allocation.lose_reply = True
    assert worker.run_one() == operation and len(allocation.calls) == 1
    with service.sessions.begin() as session:
        command = session.get(Command, operation)
        command.response = {**command.response, "plan": {**command.response["plan"], "source_commit": "3" * 40}}
    assert worker.run_one() == operation
    assert worker.run_one() is None and len(allocation.calls) == 1
    registered_plan = provisioner.saved_plan(allocation.calls[0][1]["practice_id"])
    assert registered_plan is not None and registered_plan.source_commit == "1" * 40
    with service.sessions() as session:
        assert session.get(Command, operation).response["state"] == "held"


def test_saved_plan_retry_rechecks_owner_after_registry_read(allocation_case, monkeypatch):
    service, identity, accept, _, _ = allocation_case
    accept()
    operation = WorkspaceAllocationScheduler(service).request(identity)
    service.settings.provisioning_enabled = True
    allocation = InventedAllocation()
    provisioner = EnrollmentProvisioner(service, InventedClerk())
    worker = UncontendedSyntheticWorker(service, provisioner, allocation)
    allocation.lose_reply = True
    assert worker.run_one() == operation and len(allocation.calls) == 1
    saved_plan = provisioner.saved_plan

    def revoked_after_read(practice_id):
        plan = saved_plan(practice_id)
        with service.sessions.begin() as session:
            session.scalar(select(Membership)).active = False
        return plan

    monkeypatch.setattr(provisioner, "saved_plan", revoked_after_read)
    assert worker.run_one() == operation
    assert len(allocation.calls) == 1 and worker.run_one() is None
    with service.sessions() as session:
        assert session.get(Command, operation).response["state"] == "held"
        assert session.scalar(select(Membership)).active is False


def test_workspace_ready_does_not_enqueue_another_setup(allocation_case):
    service, identity, accept, client, _ = allocation_case
    state = accept()
    assert client.post("/lab/qualify", json={"practice_id": state["practice"]["id"]}).status_code == 200
    assert WorkspaceAllocationScheduler(service).request(identity) is None


def test_worker_rejects_an_untyped_hosting_shortcut(allocation_case):
    service, _, _, _, _ = allocation_case
    with pytest.raises(ValueError):
        WorkspaceAllocationWorker(service, EnrollmentProvisioner(service, InventedClerk()), object())


def test_borrowed_allocation_session_never_commits_callers_transaction(allocation_case):
    service, identity, accept, _, _ = allocation_case
    accept()
    scheduler = WorkspaceAllocationScheduler(service)
    with pytest.raises(RuntimeError, match="invented rollback"):
        with service.sessions.begin() as session:
            operation = scheduler.request(identity, session=session)
            session.flush()
            assert session.get(Command, operation) is not None
            raise RuntimeError("invented rollback")
    with service.sessions() as session:
        assert list(session.scalars(select(Command).where(Command.operation == ALLOCATION_OPERATION))) == []


def test_acceptance_and_allocation_intent_commit_together_and_retry_once(allocation_case):
    service, identity, _, client, headers = allocation_case

    class FailingOnce(WorkspaceAllocationScheduler):
        failed = False

        def request(self, identity, *, session=None):
            if session is not None and not self.failed:
                self.failed = True
                raise EnrollmentError("workspace_allocation_unavailable", "Invented queue retry", 503)
            return super().request(identity, session=session)

    service.workspace_allocation_scheduler = FailingOnce(service)
    state = client.get("/enrollment/v1/status", headers=headers).json()
    request = {"expected_revision": state["revision"], "doc_id": BAA_DOC_ID,
        "version": BAA_VERSION, "sha256": BAA_SHA256, "signature_name": "Alex Example",
        "signature_title": "Owner", "authority_confirmed": True, "accepted": True}
    retry_headers = {**headers, "Idempotency-Key": str(uuid4())}
    failed = client.post("/enrollment/v1/baa/accept", headers=retry_headers, json=request)
    assert failed.status_code == 503
    with service.sessions() as session:
        assert list(session.scalars(select(Acceptance))) == []
        assert list(session.scalars(select(Command).where(Command.operation == ALLOCATION_OPERATION))) == []
    completed = client.post("/enrollment/v1/baa/accept", headers=retry_headers, json=request)
    replayed = client.post("/enrollment/v1/baa/accept", headers=retry_headers, json=request)
    assert completed.status_code == replayed.status_code == 200
    assert completed.json() == replayed.json()
    with service.sessions() as session:
        assert len(list(session.scalars(select(Acceptance)))) == 1
        assert len(list(session.scalars(select(Command).where(Command.operation == ALLOCATION_OPERATION)))) == 1
    assert WorkspaceAllocationScheduler(service).request(identity) is not None
