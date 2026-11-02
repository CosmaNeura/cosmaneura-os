"""Private, retryable dedicated-workspace allocation after saved BAA acceptance.

Customers never supply a destination, image, owner, Box or deployment command.
The registry queues intent in Postgres; a separately configured host worker
performs allocation. Allocation alone never grants admission or starts a trial.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .domain import EnrollmentError, canonical_hash, now_utc
from .models import Account, Command, Membership, Practice

if TYPE_CHECKING:
    from .auth import HumanIdentity
    from .provisioning import EnrollmentProvisioner, WorkspacePlan
    from .service import EnrollmentService

ALLOCATION_CONTRACT = "cosmas-workspace-allocation.v1"
ALLOCATION_OPERATION = "workspace_allocate"


@dataclass(frozen=True)
class WorkspaceAllocationRequest:
    practice_id: str
    box_id: str
    owner_id: str
    owner_subject: str
    issuer: str


@dataclass(frozen=True)
class WorkspaceAllocationDestination:
    api_origin: str
    workspace_url: str
    source_commit: str
    image_sha256: str


class ProductionWorkspaceAllocator(ABC):
    """Root-installed hosting adapter; absent adapters leave requests queued.

    destination selects only a host-reviewed release. allocate must use the
    stable operation ID and same saved plan on retries, including lost replies.
    It prepares the dedicated database, exact runtime and first-owner reservation.
    Actual native/member qualification remains a separate signed runtime read.
    """

    @abstractmethod
    def destination(self, request: WorkspaceAllocationRequest) -> WorkspaceAllocationDestination:
        raise NotImplementedError

    @abstractmethod
    def allocate(self, plan: WorkspacePlan, *, operation_id: str) -> None:
        raise NotImplementedError


class WorkspaceAllocationScheduler:
    def __init__(self, service: EnrollmentService):
        self.service = service

    def request(self, identity: HumanIdentity, *, session: Session | None = None) -> str | None:
        """Called after saved acceptance, never as an existing-user entry gate."""
        # Enrollment can enqueue in the same transaction as the signed BAA.
        # Direct recovery calls own their transaction; borrowed sessions are
        # never committed or closed by this port.
        context = nullcontext(session) if session is not None else self.service.sessions.begin()
        with context as session:
            assert session is not None
            account = self.service._account(session, identity)
            practice, member = self.service._practice(session, account)
            if practice.workspace_status == "ready":
                return None
            request = self._registered_request(session, practice.id)
            if (member.role != "owner" or account.id != request.owner_id
                    or not self.service._acceptance(session, practice)):
                raise EnrollmentError("workspace_allocation_denied", "The practice owner must finish setup first.", 403)
            key = "host-workspace:" + request.practice_id
            digest = canonical_hash(asdict(request))
            command = session.scalar(select(Command).where(Command.account_id == account.id,
                Command.key == key).with_for_update())
            if command is not None:
                if command.operation != ALLOCATION_OPERATION or command.payload_sha256 != digest:
                    raise EnrollmentError("workspace_allocation_conflict", "The saved practice setup needs review.")
                if command.response.get("state") == "held":
                    # Only a freshly authorized owner recovery may release a
                    # held intent. Background polling cannot restore authority.
                    command.response = {**command.response, "state": "queued", "error_code": None}
                return command.id
            command = Command(id=str(uuid4()), account_id=account.id, key=key,
                operation=ALLOCATION_OPERATION, payload_sha256=digest, created_at=now_utc(),
                response={"contract_version": ALLOCATION_CONTRACT, "request": asdict(request),
                          "state": "queued", "attempts": 0})
            session.add(command)
            return command.id

    def _registered_request(self, session, practice_id: str) -> WorkspaceAllocationRequest:
        from .provisioning import BOX_NAMESPACE

        practice = session.scalar(select(Practice).where(Practice.id == practice_id).with_for_update())
        owner = session.get(Account, practice.owner_id) if practice else None
        member = session.scalar(select(Membership).where(Membership.practice_id == practice_id,
            Membership.account_id == owner.id, Membership.active.is_(True))) if owner else None
        if (not practice or not owner or not member or member.role != "owner"
                or owner.issuer != self.service.settings.clerk_issuer
                or practice.human_seats > 10 or not self.service._acceptance(session, practice)):
            raise EnrollmentError("workspace_allocation_denied", "This practice is not ready for workspace setup.", 403)
        return WorkspaceAllocationRequest(practice.id, str(uuid5(BOX_NAMESPACE, str(UUID(practice.id)))),
                                          owner.id, owner.subject, owner.issuer)


class WorkspaceAllocationWorker:
    def __init__(self, service: EnrollmentService, provisioner: EnrollmentProvisioner,
                 allocator: ProductionWorkspaceAllocator):
        if not isinstance(allocator, ProductionWorkspaceAllocator):
            raise ValueError("Workspace allocation requires a root-owned hosting adapter")
        self.service, self.provisioner, self.allocator = service, provisioner, allocator
        self.scheduler = WorkspaceAllocationScheduler(service)

    @contextmanager
    def _lease(self, operation_id: str):
        # A process loss releases this session lock. Ordinary registry writes and
        # provisioner transactions do not borrow or block on this private lock.
        lock = int.from_bytes(hashlib.sha256(operation_id.encode()).digest()[:8], "big", signed=True)
        with self.service.sessions() as session:
            connection = session.connection()
            if connection.dialect.name != "postgresql":
                raise EnrollmentError("workspace_allocation_unavailable", "Workspace setup is unavailable.", 503)
            acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock})
            try:
                yield acquired is True
            finally:
                if acquired:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock})

    def run_one(self) -> str | None:
        if not self.service.settings.provisioning_enabled:
            return None
        with self.service.sessions() as session:
            ids = list(session.scalars(select(Command.id).where(Command.operation == ALLOCATION_OPERATION)
                                      .where(Command.response["state"].as_string().in_(("queued", "retry", "running")))
                                      .order_by(Command.created_at, Command.id).limit(100)))
        for operation_id in ids:
            with self._lease(operation_id) as acquired:
                if acquired and self._run(operation_id):
                    return operation_id
        return None

    def _run(self, operation_id: str) -> bool:
        with self.service.sessions.begin() as session:
            command = session.scalar(select(Command).where(Command.id == operation_id).with_for_update())
            if command is None or command.response.get("state") not in {"queued", "retry", "running"}:
                return False
            saved = command.response
            if command.operation != ALLOCATION_OPERATION:
                return False
            try:
                attempts = saved.get("attempts")
                saved_request = saved.get("request")
                if (saved.get("contract_version") != ALLOCATION_CONTRACT
                        or not isinstance(saved_request, dict)
                        or set(saved_request) != {"practice_id", "box_id", "owner_id", "owner_subject", "issuer"}
                        or not all(isinstance(value, str) and 0 < len(value) <= 1024
                                   for value in saved_request.values())
                        or type(attempts) is not int or attempts < 0):
                    raise EnrollmentError("workspace_allocation_conflict", "Saved workspace setup is invalid.")
                request = self.scheduler._registered_request(session, saved_request.get("practice_id", ""))
                if saved.get("request") != asdict(request) or command.payload_sha256 != canonical_hash(asdict(request)):
                    raise EnrollmentError("workspace_allocation_conflict", "Saved workspace ownership changed.")
            except EnrollmentError:
                # This host-owned bookkeeping grants no authority and changes
                # no registry binding. A revoked/invalid request must not stop
                # every other practice or consume the pending queue forever.
                command.response = {**saved, "state": "held", "error_code": "workspace_allocation_denied"}
                return False
            command.response = {**saved, "state": "running", "attempts": attempts + 1}
        try:
            if "plan" in saved:
                # Hydrate only the current registered plan. Corrupt command
                # JSON is never used to construct a hosting destination.
                plan = self.provisioner.saved_plan(request.practice_id)
                if plan is None or saved["plan"] != asdict(plan):
                    raise EnrollmentError("workspace_allocation_conflict", "The selected workspace release changed.")
            else:
                destination = self.allocator.destination(request)
                plan = self.provisioner.prepare(request.practice_id, **asdict(destination))
                if (plan.box_id, plan.owner_subject, plan.issuer) != (request.box_id, request.owner_subject, request.issuer):
                    raise EnrollmentError("workspace_allocation_conflict", "Workspace identity differs from its registry.")
            # Both initial attempts and saved-plan retries recheck current
            # owner authority after potentially slow Clerk/registry reads.
            self._record(operation_id, state="running", plan=asdict(plan))
            self.allocator.allocate(plan, operation_id=operation_id)
            if self.provisioner.saved_plan(request.practice_id) != plan:
                raise EnrollmentError("workspace_allocation_conflict", "Workspace binding changed during setup.")
            self._record(operation_id, state="allocated", plan=asdict(plan))
        except Exception as error:
            # No exception text, command stream, credential or patient data is
            # retained. Reuse this operation and saved release after lost replies.
            if isinstance(error, EnrollmentError) and error.code in {
                    "workspace_allocation_conflict", "workspace_allocation_denied"}:
                self._hold(operation_id)
            else:
                try:
                    self._record(operation_id, state="retry", error_code="workspace_allocation_pending")
                except EnrollmentError:
                    self._hold(operation_id)
        return True

    def _hold(self, operation_id: str) -> None:
        with self.service.sessions.begin() as session:
            command = session.scalar(select(Command).where(Command.id == operation_id).with_for_update())
            if command is None or command.operation != ALLOCATION_OPERATION:
                raise EnrollmentError("workspace_allocation_conflict", "Workspace setup operation is missing.")
            command.response = {**command.response, "state": "held", "error_code": "workspace_allocation_denied"}

    def _record(self, operation_id: str, **updates):
        with self.service.sessions.begin() as session:
            command = session.scalar(select(Command).where(Command.id == operation_id).with_for_update())
            if command is None or command.operation != ALLOCATION_OPERATION:
                raise EnrollmentError("workspace_allocation_conflict", "Workspace setup operation is missing.")
            request = self.scheduler._registered_request(session, command.response["request"]["practice_id"])
            if command.response["request"] != asdict(request) or command.payload_sha256 != canonical_hash(asdict(request)):
                raise EnrollmentError("workspace_allocation_conflict", "Workspace ownership changed during setup.")
            command.response = {**command.response, **updates}
