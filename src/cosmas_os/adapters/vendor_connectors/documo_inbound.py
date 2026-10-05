"""Documented Documo inbound history/PDF plans; no live runtime wiring."""

from urllib.parse import urlencode
from uuid import UUID

from cosmas_os.ports.fax_inbound import (
    InboundFailure,
    ReceivedFax,
    WirePlan,
    bounded_json,
    checked_page,
    count,
    reported_label,
    reported_number,
    timestamp,
    validate_pdf,
)


class DocumoInbound:
    @staticmethod
    def list_plan(scope):
        if scope.selection.vendor != "documo" or scope.selection.environment not in {
            "production",
            "sandbox",
        }:
            raise InboundFailure("scope_invalid")
        return WirePlan(
            "GET",
            "/v1/fax/history?"
            + urlencode(
                {
                    "accountId": scope.selection.remote_account_id,
                    "offset": 0,
                    "limit": scope.limit,
                    "direction": "inbound",
                    "status": "success",
                    "fromDate": scope.starts_at.date().isoformat(),
                    "toDate": scope.ends_at.date().isoformat(),
                }
            ),
        )

    @staticmethod
    def parse(scope, raw):
        DocumoInbound.list_plan(scope)
        data = bounded_json(raw)
        if type(data.get("rows")) is not list:
            raise InboundFailure("metadata_invalid")
        items = []
        for row in data["rows"]:
            if (
                type(row) is not dict
                or row.get("accountId") != scope.selection.remote_account_id
                or row.get("direction") != "inbound"
                or row.get("status") != "success"
            ):
                raise InboundFailure("source_changed")
            try:
                locator = str(UUID(row["messageId"]))
                if locator != row["messageId"]:
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise InboundFailure("locator_invalid") from None
            pages = count(row.get("pagesCount"))
            if (
                pages < 1
                or count(row.get("pagesComplete")) != pages
                or row.get("resultCode") != "0"
            ):
                raise InboundFailure("receive_status_unknown")
            viewed = row.get("isRead")
            if type(viewed) is not bool or type(row.get("isFilePurged")) is not bool:
                raise InboundFailure("metadata_invalid")
            items.append(
                ReceivedFax(
                    scope.key(),
                    (locator,),
                    timestamp(row.get("createdAt")),
                    pages,
                    None,
                    viewed,
                    not row["isFilePurged"],
                    "document_unavailable" if row["isFilePurged"] else None,
                    sender_label=reported_label(row.get("faxCsid")),
                    sender_number=reported_number(row.get("faxCallerId")),
                )
            )
        return checked_page(scope, raw, items)

    @staticmethod
    def image_plan(scope, source, approval, now):
        DocumoInbound.list_plan(scope)
        approval.check(scope, source, now)
        try:
            if len(source.locator) != 1 or str(UUID(source.locator[0])) != source.locator[0]:
                raise ValueError
        except (ValueError, TypeError):
            raise InboundFailure("locator_invalid") from None
        return WirePlan("GET", "/v1/fax/" + source.locator[0] + "/download?format=pdf")

    @staticmethod
    async def image(scope, source, approval, now, raw):
        DocumoInbound.image_plan(scope, source, approval, now)
        if await validate_pdf(raw) != source.pages:
            raise InboundFailure("document_changed")
        return raw
