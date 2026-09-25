"""Signed Stripe callbacks are retained candidates, never payment authority."""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select

from cosmas_os.adapters.vendor_connectors import stripe
from cosmas_os.application import finance_work as work
from cosmas_os.application import vendor_work as common
from cosmas_os.finance_models import FinanceConnectionVersion, FinanceEventCandidate
from cosmas_os.models import Principal
from cosmas_os.ports import vendor_connectors as private


@dataclass(frozen=True, repr=False)
class FinanceEventRoute:
    route_id: str
    connection_id: str
    signing_secret: bytes
    expected_selection: private.ConnectionSelection | None = None


def ingest(s, route, raw, signature, *, policy=work.DEFAULT_POLICY):
    if (
        not policy.events_enabled
        or type(route) is not FinanceEventRoute
        or type(raw) is not bytes
        or len(raw) > 1048576
    ):
        work.error("finance_work_unavailable", 404)
    c = s.get(FinanceConnectionVersion, route.connection_id)
    if c is None:
        work.error("finance_work_unavailable", 404)
    selection = private.ConnectionSelection.model_validate(c.private_selection)
    if route.expected_selection is not None and (
        selection != route.expected_selection
        or c.box_id != str(selection.box_id)
        or c.owner_id != str(selection.owner_id)
        or c.environment != selection.environment
        or c.private_sha256 != selection.commitment()
    ):
        work.error("finance_work_unavailable", 404)
    try:
        candidate = stripe.verify_webhook(
            raw, signature, route.signing_secret, selection, common._clock(s)
        )
    except private.VendorError:
        work.error("invalid_finance_request", 400)
    # Retaining a signed late candidate is independent of a current human login.
    s.scalar(select(Principal).where(Principal.id == c.owner_id).with_for_update())
    previous = s.scalar(
        select(FinanceEventCandidate).where(
            FinanceEventCandidate.connection_version_id == c.id,
            FinanceEventCandidate.body_sha256 == candidate.body_sha256,
        )
    )
    if previous:
        work.final_authority(s)
        s.rollback()
        return {"received": True}
    values = candidate.model_dump(mode="json")
    s.add(
        FinanceEventCandidate(
            id=str(uuid4()),
            box_id=c.box_id,
            owner_id=c.owner_id,
            connection_version_id=c.id,
            route_id=route.route_id,
            body_sha256=candidate.body_sha256,
            correlation={k: values[k] for k in ("event_type", "event_id", "object_id")},
            received_at=common._clock(s),
        )
    )
    work.final_authority(s)
    s.commit()
    return {"received": True}
