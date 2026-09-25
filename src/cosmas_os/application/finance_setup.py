"""Explicit private Stripe setup; credential references are never secrets."""

from uuid import uuid4

from sqlalchemy import select

from cosmas_os.api import finance_work_schemas as public
from cosmas_os.api.vendor_work_schemas import public_digest
from cosmas_os.application import vendor_work as common
from cosmas_os.application import workspace as ws
from cosmas_os.finance_models import FinanceConnectionVersion, FinanceCustomerVersion
from cosmas_os.models import PatientLink
from cosmas_os.ports import vendor_connectors as private


def connection_view(row):
    value = {k: v for k, v in row.public_view.items() if k != "public_sha256"}
    value["availability"] = (
        "unavailable"
        if row.revoked_at
        else "enabled"
        if row.is_current and row.write_enabled
        else "read_only"
        if row.read_enabled
        else "unavailable"
    )
    value["public_sha256"] = public_digest("cosmas-finance-public-selection.v1", value)
    return public.FinanceConnectionView.model_validate(value).public()


def customer_view(row):
    value = {k: v for k, v in row.public_view.items() if k != "public_sha256"}
    value["availability"] = "reviewed" if row.is_current and not row.revoked_at else "unavailable"
    value["public_sha256"] = public_digest("cosmas-finance-public-selection.v1", value)
    return public.FinanceCustomerView.model_validate(value).public()


def review_connection(s, box, actor, selection, *, label, write_enabled=False, read_enabled=False):
    ws._human(s, box, actor, creating=True)
    selection = private.ConnectionSelection.model_validate(selection.model_dump(mode="python"))
    if (
        selection.vendor != "stripe"
        or str(selection.box_id) != box
        or str(selection.owner_id) != actor
        or type(write_enabled) is not bool
        or type(read_enabled) is not bool
    ):
        raise ws.WorkspaceError("finance_selection_changed", 409)
    if s.get(FinanceConnectionVersion, str(selection.connection_id)):
        raise ws.WorkspaceError("finance_selection_changed", 409)
    view = {
        "id": str(selection.connection_id),
        "revision": 1,
        "environment": selection.environment,
        "label": label,
        "availability": "enabled"
        if write_enabled
        else "read_only"
        if read_enabled
        else "unavailable",
    }
    view["public_sha256"] = public_digest("cosmas-finance-public-selection.v1", view)
    view = public.FinanceConnectionView.model_validate(view).public()
    row = FinanceConnectionVersion(
        id=str(selection.connection_id),
        family_id=str(uuid4()),
        revision=1,
        box_id=box,
        owner_id=actor,
        environment=selection.environment,
        private_selection=selection.model_dump(mode="json"),
        private_sha256=selection.commitment(),
        public_view=view,
        public_sha256=view["public_sha256"],
        reviewed_by=actor,
        reviewed_at=common._clock(s),
        write_enabled=write_enabled,
        read_enabled=read_enabled,
    )
    s.add(row)
    s.commit()
    return connection_view(row)


def review_customer(s, box, actor, connection_id, patient_id, customer_id, *, label):
    ws._human(s, box, actor, creating=True)
    connection = s.scalar(
        select(FinanceConnectionVersion)
        .where(
            FinanceConnectionVersion.id == connection_id,
            FinanceConnectionVersion.box_id == box,
            FinanceConnectionVersion.owner_id == actor,
        )
        .with_for_update(read=True)
    )
    patient = s.scalar(
        select(PatientLink)
        .where(
            PatientLink.id == patient_id,
            PatientLink.box_id == box,
            PatientLink.state == "confirmed",
            PatientLink.revoked_at.is_(None),
            PatientLink.source_owner_id.is_(None),
        )
        .with_for_update(read=True)
    )
    if connection is None or connection.revoked_at or not connection.is_current or patient is None:
        raise ws.WorkspaceError("finance_selection_changed", 409)
    # Reuse the qualified intent's exact customer-id validator without creating
    # or confirming any processor object.
    private.StripePaymentIntentIntent(customer_id=customer_id, amount=50, currency="usd")
    mid = str(uuid4())
    mapping = {
        "connection_id": connection_id,
        "patient_link_id": patient_id,
        "customer_id": customer_id,
    }
    view = {
        "id": mid,
        "revision": 1,
        "connection_id": connection_id,
        "label": label,
        "availability": "reviewed",
    }
    view["public_sha256"] = public_digest("cosmas-finance-public-selection.v1", view)
    view = public.FinanceCustomerView.model_validate(view).public()
    row = FinanceCustomerVersion(
        id=mid,
        family_id=str(uuid4()),
        revision=1,
        box_id=box,
        owner_id=actor,
        patient_link_id=patient_id,
        connection_version_id=connection_id,
        customer_id=customer_id,
        mapping_sha256=private.digest("cosmas-finance-customer.v1", mapping),
        public_view=view,
        public_sha256=view["public_sha256"],
        reviewed_by=actor,
        reviewed_at=common._clock(s),
    )
    s.add(row)
    s.commit()
    return customer_view(row)
