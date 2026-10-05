"""Documented SRFax inbound plans/parsers, no credentials or automatic I/O."""

import base64
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from cosmas_os.ports.fax_inbound import (
    MAX_PDF_BYTES,
    InboundFailure,
    ReceivedFax,
    WirePlan,
    bounded_json,
    checked_page,
    count,
    reported_label,
    reported_number,
    validate_pdf,
)

PATH = "/SRF_SecWebSvc.php"


class SRFaxInbound:
    @staticmethod
    def list_plan(scope):
        try:
            if scope.selection.vendor != "srfax" or scope.selection.environment != "production":
                raise ValueError
            zone = ZoneInfo(scope.account_timezone or "")
            if (
                scope.account_date_format != "%Y-%m-%d %H:%M:%S"
                or type(scope.received_status) is not str
                or not re.fullmatch(r"[A-Za-z ]{1,15}", scope.received_status)
            ):
                raise ValueError
        except (ValueError, KeyError):
            raise InboundFailure("account_timezone_required") from None
        return WirePlan(
            "POST",
            PATH,
            (
                ("action", "Get_Fax_Inbox"),
                ("sResponseFormat", "JSON"),
                ("sPeriod", "RANGE"),
                ("sStartDate", scope.starts_at.astimezone(zone).strftime("%Y%m%d")),
                ("sEndDate", scope.ends_at.astimezone(zone).strftime("%Y%m%d")),
                ("sViewedStatus", "ALL"),
            ),
        )

    @staticmethod
    def parse(scope, raw):
        SRFaxInbound.list_plan(scope)
        data = bounded_json(raw)
        if data.get("Status") != "Success" or type(data.get("Result")) is not list:
            raise InboundFailure("metadata_invalid")
        items = []
        for row in data["Result"]:
            if type(row) is not dict or row.get("ReceiveStatus") != scope.received_status:
                raise InboundFailure("receive_status_unknown")
            name = row.get("FileName")
            if type(name) is not str or not re.fullmatch(
                r"[A-Za-z0-9_.-]{1,75}\|[1-9][0-9]{0,19}", name
            ):
                raise InboundFailure("locator_invalid")
            # Date/EpochTime reflect account timezone. Use declared Date, never treat EpochTime as UTC.
            try:
                local = datetime.strptime(row["Date"], scope.account_date_format)
                zone = ZoneInfo(scope.account_timezone)
                first, second = (
                    local.replace(tzinfo=zone, fold=0),
                    local.replace(tzinfo=zone, fold=1),
                )
                if (
                    first.utcoffset() != second.utcoffset()
                    or first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != local
                ):
                    raise ValueError
                at = first.astimezone(UTC)
            except (ValueError, KeyError, TypeError):
                raise InboundFailure("account_date_unsupported") from None
            viewed = row.get("ViewedStatus")
            if viewed not in ("Y", "N"):
                raise InboundFailure("metadata_invalid")
            items.append(
                ReceivedFax(
                    scope.key(),
                    (name, name.rsplit("|", 1)[1]),
                    at,
                    count(row.get("Pages")),
                    count(row.get("Size"), 16777216),
                    viewed == "Y",
                    True,
                    sender_label=reported_label(row.get("RemoteID")),
                    sender_number=reported_number(row.get("CallerID")),
                )
            )
        return checked_page(scope, raw, items)

    @staticmethod
    def image_plan(scope, source, approval, now):
        SRFaxInbound.list_plan(scope)
        approval.check(scope, source, now)
        if (
            len(source.locator) != 2
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,75}\|[1-9][0-9]{0,19}", source.locator[0])
            or source.locator[1] != source.locator[0].rsplit("|", 1)[1]
        ):
            raise InboundFailure("locator_invalid")
        return WirePlan(
            "POST",
            PATH,
            (
                ("action", "Retrieve_Fax"),
                ("sFaxFileName", source.locator[0]),
                ("sDirection", "IN"),
                ("sFaxFormat", "PDF"),
                ("sResponseFormat", "JSON"),
                ("sMarkasViewed", "N"),
            ),
        )

    @staticmethod
    async def image(scope, source, approval, now, raw):
        SRFaxInbound.image_plan(scope, source, approval, now)
        # Retrieval has a larger bounded base64 payload than metadata.
        if type(raw) is not bytes or len(raw) > ((MAX_PDF_BYTES + 2) // 3) * 4 + 128:
            raise InboundFailure("document_needs_human")
        try:
            data = bounded_json(raw, ((MAX_PDF_BYTES + 2) // 3) * 4 + 128)
            if (
                set(data) != {"Status", "Result"}
                or data["Status"] != "Success"
                or type(data["Result"]) is not str
            ):
                raise ValueError
            document = base64.b64decode(data["Result"], validate=True)
        except (ValueError, TypeError):
            raise InboundFailure("document_needs_human") from None
        pages = await validate_pdf(document)
        if pages != source.pages:
            raise InboundFailure("document_changed")
        return document
