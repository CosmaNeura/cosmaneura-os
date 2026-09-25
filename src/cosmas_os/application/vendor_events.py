"""Authenticated candidates and untrusted hints; never a sender or automatic read."""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select

from cosmas_os.adapters.vendor_connectors import documo, spruce, srfax
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_work as work
from cosmas_os.config import settings
from cosmas_os.models import EncounterWorkspace, Principal, Ticket
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.vendor_models import (
    VendorConnectionVersion,
    VendorEventCandidate,
    VendorProviderObservation,
    VendorWorkRevision,
)


@dataclass(frozen=True, repr=False)
class EventRoute:
    route_id: str
    connection_version_id: str
    vendor: str
    signing_secret: bytes | None = None
    expected_selection: private.ConnectionSelection | None = None


def ingest(s, route: EventRoute, raw: bytes, *, signature=None):
    if (
        not settings.vendor_events_enabled
        or type(route) is not EventRoute
        or type(raw) is not bytes
        or len(raw) > 1048576
    ):
        work.error("vendor_work_unavailable", 404)
    connection = s.get(VendorConnectionVersion, route.connection_version_id)
    if (
        connection is None
        or connection.vendor != route.vendor
        or connection.routing.get("event_route_id") != route.route_id
    ):
        work.error("vendor_work_unavailable", 404)
    selection = private.ConnectionSelection.model_validate(connection.private_selection)
    if route.expected_selection is not None and (
        selection != route.expected_selection
        or connection.box_id != str(selection.box_id)
        or connection.owner_id != str(selection.owner_id)
        or connection.environment != selection.environment
        or connection.private_sha256 != selection.commitment()
    ):
        work.error("vendor_work_unavailable", 404)
    now = work._clock(s)
    try:
        if route.vendor == "spruce":
            if type(signature) is not str or type(route.signing_secret) is not bytes:
                raise private.VendorError("signature_invalid")
            candidate = spruce.verify_webhook(raw, signature, route.signing_secret, selection, now)
        elif route.vendor == "srfax":
            candidate = srfax.notification_hint(raw, selection, now)
        elif route.vendor == "documo":
            candidate = documo.notification_hint(raw, selection, now)
        else:
            raise private.VendorError("event_untrusted")
    except private.VendorError:
        work.error("invalid_vendor_request", 400)
    # Serialize account candidates and correlation with commands under the owner
    # lock. No human active gate applies to privately retained late evidence.
    s.scalar(select(Principal).where(Principal.id == connection.owner_id).with_for_update())
    authenticity = "signed" if candidate.authenticity == "signature_verified" else "untrusted_hint"
    previous = s.scalar(
        select(VendorEventCandidate).where(
            VendorEventCandidate.connection_version_id == connection.id,
            VendorEventCandidate.vendor == connection.vendor,
            VendorEventCandidate.authenticity == authenticity,
            VendorEventCandidate.body_sha256 == candidate.body_sha256,
        )
    )
    if previous:
        work._final_authority(s)
        s.rollback()
        return {"received": True}
    correlation = {
        key: value
        for key, value in candidate.model_dump(mode="json").items()
        if key in {"event_type", "event_id", "object_id", "request_id"} and value is not None
    }
    row = VendorEventCandidate(
        id=str(uuid4()),
        route_id=route.route_id,
        connection_version_id=connection.id,
        box_id=connection.box_id,
        owner_id=connection.owner_id,
        vendor=connection.vendor,
        authenticity=authenticity,
        body_sha256=candidate.body_sha256,
        correlation=correlation,
        received_at=now,
    )
    s.add(row)
    s.flush()
    # Unsigned callbacks never create a reference or a transport observation.
    if authenticity == "signed" and candidate.request_id and candidate.object_id:
        matches = list(
            s.scalars(
                select(VendorWorkRevision)
                .join(
                    VendorProviderObservation,
                    VendorProviderObservation.operation_id
                    == VendorWorkRevision.intended_operation_id,
                )
                .where(
                    VendorWorkRevision.connection_version_id == connection.id,
                    VendorProviderObservation.kind == "submission",
                    VendorProviderObservation.public_observation["acceptance"].as_string()
                    == "accepted",
                    VendorProviderObservation.private_reference["kind"].as_string()
                    == "async_request",
                    VendorProviderObservation.private_reference["value"].as_string()
                    == candidate.request_id,
                )
                .distinct()
                .limit(2)
            )
        )
        if len(matches) == 1:
            r = matches[0]
            s.scalar(
                select(EncounterWorkspace)
                .where(EncounterWorkspace.id == r.workspace_id)
                .with_for_update()
            )
            t = s.scalar(
                select(Ticket)
                .where(Ticket.id == r.ticket_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            command = private.VendorCommand.model_validate(r.private_command)
            ref = private.ProviderReference(
                vendor="spruce",
                connection_id=selection.connection_id,
                environment=selection.environment,
                selection_sha256=selection.commitment(),
                operation_id=command.operation_id,
                request_sha256=command.commitment(),
                kind="conversation_item",
                value=candidate.object_id,
                request_id=candidate.request_id,
                observed_at=now,
            )
            head = work._head(s, r)
            oid = str(uuid4())
            value = {
                "id": oid,
                "sequence": head["sequence"] + 1,
                "operation_id": r.intended_operation_id,
                "kind": "transport",
                "observed_at": public.timestamp(now),
                "recorded_at": public.timestamp(now),
                "transport": "pending",
            }
            sha = public.public_digest("cosmas-vendor-public-observation.v1", value)
            value["sha256"] = sha
            value = public.Observation.model_validate(value).public()
            next_head = public.public_digest(
                "cosmas-vendor-observation-head.v1",
                {
                    "operation_id": r.intended_operation_id,
                    "sequence": head["sequence"] + 1,
                    "previous_sha256": head["sha256"],
                    "observation_sha256": sha,
                },
            )
            s.add(
                VendorProviderObservation(
                    id=oid,
                    operation_id=r.intended_operation_id,
                    ticket_id=r.ticket_id,
                    action_revision_id=r.action_revision_id,
                    workspace_id=r.workspace_id,
                    box_id=r.box_id,
                    owner_id=r.owner_id,
                    connection_version_id=connection.id,
                    sequence=head["sequence"] + 1,
                    source="event",
                    source_id=row.id,
                    event_candidate_id=row.id,
                    kind="transport",
                    observed_at=now,
                    recorded_at=now,
                    body_sha256=candidate.body_sha256,
                    canonical_sha256=private.digest(
                        "cosmas-vendor-correlated-candidate.v1", correlation
                    ),
                    private_reference=ref.model_dump(mode="json"),
                    public_observation=value,
                    public_sha256=sha,
                    head_sha256=next_head,
                )
            )
            t.version += 1
    work._final_authority(s)
    s.commit()
    return {"received": True}
