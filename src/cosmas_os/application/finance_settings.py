"""Reviewed owner settings; all changes and receipts share one local transaction."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.api import finance_setup_schemas as schema
from cosmas_os.api.vendor_work_schemas import bounded, public_digest, timestamp
from cosmas_os.application import finance_setup as admissions
from cosmas_os.application import vendor_work as common
from cosmas_os.application import workspace as ws
from cosmas_os.finance_models import FinanceConnectionVersion, FinanceCustomerVersion
from cosmas_os.finance_setup_models import FinanceSetup, FinanceSetupReceipt, FinanceSetupRevision
from cosmas_os.models import AuditEvent, PatientLink
from cosmas_os.ports.vendor_connectors import ConnectionSelection


def error(code, status=409) -> NoReturn:
    raise ws.WorkspaceError(code, status)


@dataclass(frozen=True)
class FinanceSetupPolicy:
    enabled: bool = False

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("Explicit settings flag required")


DEFAULT_POLICY = FinanceSetupPolicy()


@dataclass(frozen=True, repr=False)
class Installation:
    selection: ConnectionSelection
    label: str

    def public(self):
        value = {
            "installation_id": str(self.selection.connection_id),
            "label": self.label,
            "environment": self.selection.environment,
            "account_reference": self.selection.remote_account_id,
        }
        value["installation_sha256"] = public_digest(
            "cosmas-finance-installation.v1",
            {"public": value, "selection_sha256": self.selection.commitment()},
        )
        return schema.InstalledAccount.model_validate(value).public()


class Catalog:
    def __init__(self, installations=()):
        values = {}
        for item in installations:
            selection = ConnectionSelection.model_validate(item.selection.model_dump(mode="python"))
            if selection.vendor != "stripe" or selection.environment != "sandbox":
                raise ValueError(
                    "This local build accepts explicit Stripe sandbox installations only"
                )
            item = Installation(selection, item.label)
            public = item.public()
            if public["installation_id"] in values:
                raise ValueError("Distinct installed account identifiers required")
            values[public["installation_id"]] = item
        if len(values) > 50:
            raise ValueError("At most 50 explicit installed accounts")
        self.installations = MappingProxyType(values)

    def require(self, box, owner, installation_id, digest):
        item = self.installations.get(installation_id)
        if item is None or (str(item.selection.box_id), str(item.selection.owner_id)) != (
            box,
            owner,
        ):
            error("finance_installation_changed")
        if item.public()["installation_sha256"] != digest:
            error("finance_installation_changed")
        return item


EMPTY_CATALOG = Catalog()


def scope(box, owner):
    return {"box_id": box, "owner_id": owner}


def owner(s, box, actor, *, writing=False):
    p = ws._human(s, box, actor, creating=writing)
    if not p.is_owner:
        error("finance_setup_unavailable", 404)
    return p


def fence(s):
    check = s.info.get("finance_setup_authority")
    if check is not None:
        check()


def patient(s, box, patient_id):
    p = s.scalar(
        select(PatientLink)
        .where(
            PatientLink.id == patient_id,
            PatientLink.box_id == box,
            PatientLink.state == "confirmed",
            PatientLink.revoked_at.is_(None),
            PatientLink.source_owner_id.is_(None),
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if p is None:
        error("finance_patient_unavailable")
    return p


def entity(s, box, actor, setup_id):
    row = s.scalar(
        select(FinanceSetup)
        .where(
            FinanceSetup.id == setup_id,
            FinanceSetup.box_id == box,
            FinanceSetup.owner_id == actor,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        error("finance_setup_unavailable", 404)
    return row


def latest(s, setup_id):
    return s.scalar(
        select(FinanceSetupReceipt)
        .where(FinanceSetupReceipt.setup_id == setup_id)
        .order_by(FinanceSetupReceipt.version.desc())
        .limit(1)
    )


def current(s, row):
    h = latest(s, row.id)
    r = s.get(FinanceSetupRevision, h.revision_id) if h else None
    if h is None or r is None:
        error("finance_setup_integrity", 503)
    return h, r


def old_receipt(s, box, actor, kind, request):
    digest = schema.request_digest(scope(box, actor), kind, request)
    row = s.scalar(
        select(FinanceSetupReceipt).where(
            FinanceSetupReceipt.box_id == box,
            FinanceSetupReceipt.owner_id == actor,
            FinanceSetupReceipt.idempotency_key == request.idempotency_key,
        )
    )
    if row and (row.command_kind != kind or row.request_sha256 != digest):
        error("finance_setup_idempotency_conflict")
    return row, digest


def response(row):
    value = schema.Receipt.model_validate(row.response).public()
    if (
        value["receipt_sha256"] != row.receipt_sha256
        or public_digest(
            "cosmas-finance-setup-receipt.v1",
            {key: child for key, child in value.items() if key != "receipt_sha256"},
        )
        != row.receipt_sha256
    ):
        error("finance_setup_integrity", 503)
    return bounded(value, 8192)


def record(s, row, r, kind, request, digest, version, state):
    # Reauthentication expires ORM state; persist pending binding flags inside
    # this transaction before that fence can refresh them from the database.
    s.flush()
    fence(s)
    rid, now = str(uuid4()), common._clock(s)
    value = {
        "contract_version": 1,
        "outcome": "recorded",
        "scope": scope(row.box_id, row.owner_id),
        "command_kind": kind,
        "idempotency_key": request.idempotency_key,
        "request_sha256": digest,
        "receipt_id": rid,
        "recorded_at": timestamp(now),
        "effect": {
            "setup_id": row.id,
            "kind": row.kind,
            "version": version,
            "revision_id": r.id,
            "review_sha256": r.review_sha256,
            "state": state,
        },
    }
    sha = public_digest("cosmas-finance-setup-receipt.v1", value)
    value["receipt_sha256"] = sha
    saved = FinanceSetupReceipt(
        id=rid,
        box_id=row.box_id,
        owner_id=row.owner_id,
        setup_id=row.id,
        revision_id=r.id,
        version=version,
        command_kind=kind,
        state=state,
        idempotency_key=request.idempotency_key,
        request=request.public(),
        request_sha256=digest,
        response=value,
        receipt_sha256=sha,
        recorded_at=now,
    )
    s.add(saved)
    s.add(
        AuditEvent(
            box_id=row.box_id,
            aggregate_type="finance_setup",
            aggregate_id=row.id,
            actor_principal_id=row.owner_id,
            event_type="finance_setup." + kind,
            outcome=state,
            detail={"revision_id": r.id, "receipt_id": rid},
        )
    )
    s.flush()
    fence(s)
    s.commit()
    return response(saved)


def disable_binding(s, r, *, revoke=False):
    if r.kind == "account":
        c = s.get(FinanceConnectionVersion, r.connection_version_id)
        c.is_current, c.write_enabled, c.read_enabled = False, False, False
        # A later account activation must not revive the customer's older
        # reviewed account version or any payment approval bound to it.
        for mapping in s.scalars(
            select(FinanceCustomerVersion).where(
                FinanceCustomerVersion.connection_version_id == r.connection_version_id,
                FinanceCustomerVersion.box_id == r.box_id,
                FinanceCustomerVersion.owner_id == r.owner_id,
            )
        ):
            mapping.is_current = False
    else:
        c = s.get(FinanceCustomerVersion, r.customer_version_id)
        c.is_current = False
    if revoke and c.revoked_at is None:
        c.revoked_at = common._clock(s)


def account_current(s, box, actor, binding, installed):
    row = entity(s, box, actor, binding.setup_id)
    h, r = current(s, row)
    if row.kind != "account" or (h.version, r.id, r.review_sha256, h.state) != (
        binding.expected_version,
        binding.revision_id,
        binding.review_sha256,
        "active",
    ):
        error("finance_account_changed")
    item = installed.require(box, actor, r.installation_id, r.installation_sha256)
    c = s.get(FinanceConnectionVersion, r.connection_version_id)
    if c is None or c.revoked_at or not c.is_current:
        error("finance_account_changed")
    permissions = r.review["permissions"]
    if (c.read_enabled, c.write_enabled) != (
        permissions["read_status"],
        permissions["create_unconfirmed_intents"],
    ):
        error("finance_account_changed")
    return row, h, r, item


def proposal_entity(s, box, actor, request, kind):
    existing = s.get(FinanceSetup, request.setup_id)
    if existing is not None:
        row = entity(s, box, actor, request.setup_id)
        head, prior = current(s, row)
        if row.kind != kind or head.state == "revoked" or head.version != request.expected_version:
            error("finance_setup_changed")
        if (kind == "account" and row.installation_id != request.installation_id) or (
            kind == "customer"
            and (row.account_setup_id, row.patient_link_id)
            != (request.account.setup_id, request.patient_link_id)
        ):
            error("finance_setup_changed")
        if prior.revision >= 20 or head.version >= 98:
            error("finance_setup_limit")
        disable_binding(s, prior)
        return row, prior.revision + 1, head.version + 1
    if request.expected_version != 0:
        error("finance_setup_changed")
    if (
        s.scalar(
            select(func.count())
            .select_from(FinanceSetup)
            .where(
                FinanceSetup.box_id == box,
                FinanceSetup.owner_id == actor,
            )
        )
        >= 50
    ):
        error("finance_setup_limit")
    duplicate = select(FinanceSetup.id).where(
        FinanceSetup.box_id == box, FinanceSetup.owner_id == actor
    )
    duplicate = (
        duplicate.where(FinanceSetup.installation_id == request.installation_id)
        if kind == "account"
        else duplicate.where(
            FinanceSetup.account_setup_id == request.account.setup_id,
            FinanceSetup.patient_link_id == request.patient_link_id,
        )
    )
    if s.scalar(duplicate):
        error("finance_setup_already_exists")
    row = FinanceSetup(
        id=request.setup_id,
        box_id=box,
        owner_id=actor,
        kind=kind,
        installation_id=request.installation_id if kind == "account" else None,
        account_setup_id=request.account.setup_id if kind == "customer" else None,
        patient_link_id=request.patient_link_id if kind == "customer" else None,
        created_at=common._clock(s),
    )
    s.add(row)
    s.flush()
    return row, 1, 1


def propose(s, box, actor, kind, request, installed=EMPTY_CATALOG, *, policy=DEFAULT_POLICY):
    owner(s, box, actor, writing=True)
    old, digest = old_receipt(s, box, actor, kind, request)
    if old:
        fence(s)
        return response(old)
    if not policy.enabled:
        error("finance_setup_disabled", 403)
    if kind == "propose_account" and isinstance(request, schema.AccountProposal):
        item = installed.require(box, actor, request.installation_id, request.installation_sha256)
        row, number, version = proposal_entity(s, box, actor, request, "account")
        rid, cid = str(uuid4()), str(uuid4())
        derived = ConnectionSelection.model_validate(
            {**item.selection.model_dump(mode="python"), "connection_id": UUID(cid)}
        )
        # The reviewed legacy admissions commit only this SAVEPOINT. The outer
        # settings transaction retains the account, revision and receipt atomically.
        with Session(bind=s.connection(), join_transaction_mode="create_savepoint") as child:
            admissions.review_connection(child, box, actor, derived, label=request.label)
        review = schema.AccountReview(
            kind="account",
            setup_id=row.id,
            revision_id=rid,
            revision=number,
            installed=item.public(),
            label=request.label,
            permissions=request.permissions,
            connection_version_id=cid,
        ).public()
        mid = account_revision_id = patient_id = None
    elif kind == "propose_customer" and isinstance(request, schema.CustomerProposal):
        _, _, account, item = account_current(s, box, actor, request.account, installed)
        p = patient(s, box, request.patient_link_id)
        row, number, version = proposal_entity(s, box, actor, request, "customer")
        rid, cid, account_revision_id, patient_id = (
            str(uuid4()),
            account.connection_version_id,
            account.id,
            p.id,
        )
        with Session(bind=s.connection(), join_transaction_mode="create_savepoint") as child:
            view = admissions.review_customer(
                child, box, actor, cid, p.id, request.customer_id, label=request.label
            )
        mid = view["id"]
        native = s.get(FinanceCustomerVersion, mid)
        native.is_current = False
        review = schema.CustomerReview(
            kind="customer",
            setup_id=row.id,
            revision_id=rid,
            revision=number,
            installed=item.public(),
            label=request.label,
            account=request.account,
            account_label=account.review["label"],
            connection_version_id=cid,
            customer_version_id=mid,
            patient=schema.Patient(patient_link_id=p.id, label=p.label),
            customer_id=request.customer_id,
        ).public()
    else:
        error("invalid_finance_setup_request", 400)
    r = FinanceSetupRevision(
        id=rid,
        setup_id=row.id,
        box_id=box,
        owner_id=actor,
        kind=row.kind,
        revision=number,
        installation_id=str(item.selection.connection_id),
        installation_sha256=item.public()["installation_sha256"],
        connection_version_id=cid,
        customer_version_id=mid,
        account_revision_id=account_revision_id,
        patient_link_id=patient_id,
        review=review,
        review_sha256=public_digest("cosmas-finance-setup-review.v1", review),
        created_at=common._clock(s),
    )
    s.add(r)
    s.flush()
    return record(s, row, r, kind, request, digest, version, "pending_review")


def command(s, box, actor, kind, request, installed=EMPTY_CATALOG, *, policy=DEFAULT_POLICY):
    owner(s, box, actor, writing=True)
    old, digest = old_receipt(s, box, actor, kind, request)
    if old:
        fence(s)
        return response(old)
    row = entity(s, box, actor, request.setup_id)
    h, r = current(s, row)
    if (h.version, r.id, r.review_sha256) != (
        request.expected_version,
        request.revision_id,
        request.review_sha256,
    ) or h.state == "revoked":
        error("finance_setup_changed")
    if h.version >= 100:
        error("finance_setup_limit")
    if kind == "activate" and isinstance(request, schema.Activation):
        if h.version >= 98:
            error("finance_setup_limit")
        if not policy.enabled:
            error("finance_setup_disabled", 403)
        if h.state not in {"pending_review", "disabled"} or (
            (row.kind == "customer") != (request.reviewed_patient_customer is True)
        ):
            error("finance_setup_changed")
        installed.require(box, actor, r.installation_id, r.installation_sha256)
        if row.kind == "account":
            native = s.get(FinanceConnectionVersion, r.connection_version_id)
            if native.revoked_at:
                error("finance_binding_unavailable")
            native.is_current = True
            native.read_enabled = r.review["permissions"]["read_status"]
            native.write_enabled = r.review["permissions"]["create_unconfirmed_intents"]
        else:
            account_current(
                s, box, actor, schema.Binding.model_validate(r.review["account"]), installed
            )
            patient(s, box, r.patient_link_id)
            native = s.get(FinanceCustomerVersion, r.customer_version_id)
            if native.revoked_at:
                error("finance_binding_unavailable")
            native.is_current = True
        state = "active"
    elif kind == "disable" and isinstance(request, schema.Disable):
        if h.version >= 99:
            error("finance_setup_limit")
        if h.state == "disabled":
            error("finance_setup_changed")
        disable_binding(s, r)
        state = "disabled"
    elif kind == "revoke" and isinstance(request, schema.Revoke):
        for historical in s.scalars(
            select(FinanceSetupRevision).where(FinanceSetupRevision.setup_id == row.id)
        ):
            disable_binding(s, historical, revoke=True)
        state = "revoked"
    else:
        error("invalid_finance_setup_request", 400)
    return record(s, row, r, kind, request, digest, h.version + 1, state)


def summary(s, row, h, r, installed, policy):
    reason = "available"
    try:
        if not policy.enabled:
            error("finance_setup_disabled")
        installed.require(row.box_id, row.owner_id, r.installation_id, r.installation_sha256)
        if row.kind == "customer":
            account_current(
                s,
                row.box_id,
                row.owner_id,
                schema.Binding.model_validate(r.review["account"]),
                installed,
            )
            patient(s, row.box_id, r.patient_link_id)
        if h.state == "revoked":
            error("finance_setup_inactive")
        if h.state in {"pending_review", "disabled"} and h.version >= 98:
            error("finance_setup_limit")
        native = (
            s.get(FinanceConnectionVersion, r.connection_version_id)
            if row.kind == "account"
            else s.get(FinanceCustomerVersion, r.customer_version_id)
        )
        if native is None or native.revoked_at or (h.state == "active" and not native.is_current):
            error("finance_binding_unavailable")
    except ws.WorkspaceError as exc:
        reason = exc.code
    return schema.Summary.model_validate(
        {
            **h.response["effect"],
            "target": {"kind": "account", "installation_id": row.installation_id}
            if row.kind == "account"
            else {
                "kind": "customer",
                "account_setup_id": row.account_setup_id,
                "patient_link_id": row.patient_link_id,
            },
            "label": r.review["label"],
            "usable_locally": h.state == "active" and reason == "available",
            "availability": reason,
        }
    ).public()


def detail(s, box, actor, setup_id, installed=EMPTY_CATALOG, *, policy=DEFAULT_POLICY):
    owner(s, box, actor)
    row = entity(s, box, actor, setup_id)
    h, r = current(s, row)
    value = schema.Detail.model_validate(
        {
            "contract_version": 1,
            "scope": scope(box, actor),
            "summary": summary(s, row, h, r, installed, policy),
            "review": r.review,
            "last_receipt": response(h),
        }
    ).public()
    if public_digest("cosmas-finance-setup-review.v1", value["review"]) != r.review_sha256:
        error("finance_setup_integrity", 503)
    fence(s)
    return bounded(value, 32768)


def catalog(s, box, actor, installed=EMPTY_CATALOG, *, policy=DEFAULT_POLICY):
    owner(s, box, actor)
    rows = list(
        s.scalars(
            select(FinanceSetup)
            .where(FinanceSetup.box_id == box, FinanceSetup.owner_id == actor)
            .order_by(FinanceSetup.id)
            .limit(51)
        )
    )
    patients = list(
        s.scalars(
            select(PatientLink)
            .where(
                PatientLink.box_id == box,
                PatientLink.state == "confirmed",
                PatientLink.revoked_at.is_(None),
                PatientLink.source_owner_id.is_(None),
            )
            .order_by(PatientLink.id)
            .limit(101)
        )
    )
    if len(rows) > 50 or len(patients) > 100:
        error("finance_setup_limit")
    profiles = [
        item.public()
        for item in installed.installations.values()
        if policy.enabled
        and (str(item.selection.box_id), str(item.selection.owner_id)) == (box, actor)
    ]
    value = schema.Catalog.model_validate(
        {
            "contract_version": 1,
            "scope": scope(box, actor),
            "enabled": policy.enabled,
            "installed_accounts": profiles,
            "patients": [{"patient_link_id": p.id, "label": p.label} for p in patients],
            "setups": [summary(s, row, *current(s, row), installed, policy) for row in rows],
        }
    ).public()
    fence(s)
    return bounded(value, 131072)


def history(s, box, actor, setup_id):
    owner(s, box, actor)
    entity(s, box, actor, setup_id)
    rows = list(
        s.scalars(
            select(FinanceSetupReceipt)
            .where(FinanceSetupReceipt.setup_id == setup_id)
            .order_by(FinanceSetupReceipt.version)
            .limit(101)
        )
    )
    if len(rows) > 100:
        error("finance_setup_limit")
    fence(s)
    return bounded(
        schema.History.model_validate(
            {
                "contract_version": 1,
                "scope": scope(box, actor),
                "setup_id": setup_id,
                "receipts": [response(row) for row in rows],
            }
        ).public(),
        131072,
    )


def resolve(s, box, actor, request):
    owner(s, box, actor)
    row = s.scalar(
        select(FinanceSetupReceipt).where(
            FinanceSetupReceipt.box_id == box,
            FinanceSetupReceipt.owner_id == actor,
            FinanceSetupReceipt.idempotency_key == request.idempotency_key,
        )
    )
    fence(s)
    if row is None:
        return schema.NotFound(
            contract_version=1,
            outcome="not_found",
            scope=schema.Scope(box_id=box, owner_id=actor),
            command_kind=request.command_kind,
            idempotency_key=request.idempotency_key,
            request_sha256=request.request_sha256,
        ).public()
    if (row.command_kind, row.request_sha256) != (request.command_kind, request.request_sha256):
        error("finance_setup_idempotency_conflict")
    return response(row)
