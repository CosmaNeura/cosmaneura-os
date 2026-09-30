"""One bounded primary-calendar read; no attendees, descriptions or mutations."""

import re
from datetime import UTC, date, datetime, timedelta

from cosmas_os.adapters.google_connection import CALENDAR_URL


def boundary(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid calendar boundary")
    if set(value) == {"date"} and isinstance(value["date"], str):
        parsed = date.fromisoformat(value["date"])
        if parsed.isoformat() != value["date"]:
            raise ValueError("Invalid calendar date")
        return parsed.isoformat(), True, datetime.combine(parsed, datetime.min.time(), UTC)
    if set(value) == {"dateTime"} and isinstance(value["dateTime"], str):
        raw = value["dateTime"]
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)", raw):
            raise ValueError("Invalid calendar time")
        parsed = datetime.fromisoformat(raw).astimezone(UTC)
        return parsed.isoformat(), False, parsed
    raise ValueError("Invalid calendar boundary")


def read_calendar(service, identity, private, binding, account_id):
    def current(*, audit=False):
        service._read_current(identity, private, binding, account_id, audit=audit)

    current()
    start = service.now()
    end = start + timedelta(days=7)
    data = service._request("GET", CALENDAR_URL, token=private["token"], params={
        "timeMin": start.isoformat(), "timeMax": end.isoformat(), "maxResults": "25",
        "singleEvents": "true", "orderBy": "startTime", "showDeleted": "false", "timeZone": "UTC",
        "fields": "items(id,summary,status,start(date,dateTime),end(date,dateTime)),nextPageToken",
    })
    current()
    if set(data) - {"items", "nextPageToken"}:
        raise ValueError("Unexpected calendar response")
    rows, page = data.get("items", []), data.get("nextPageToken")
    if (not isinstance(rows, list) or len(rows) > 25
        or page is not None and (not isinstance(page, str) or not 1 <= len(page) <= 4096)):
        raise ValueError("Invalid calendar list")
    items, identifiers = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"id", "summary", "status", "start", "end"}:
            raise ValueError("Invalid calendar event")
        identifier = row.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,1024}", identifier) or identifier in identifiers:
            raise ValueError("Invalid calendar reference")
        identifiers.add(identifier)
        starts_at, all_day, begins = boundary(row.get("start"))
        ends_at, end_all_day, finishes = boundary(row.get("end"))
        status = row.get("status")
        if (all_day != end_all_day or finishes <= begins or status not in {"confirmed", "tentative", "cancelled"}
            or not all_day and (finishes <= start or begins >= end)):
            raise ValueError("Invalid calendar interval")
        # Date-only events retain their original date; local display must not
        # turn a midnight UTC conversion into the preceding calendar day.
        if all_day and (finishes.date() <= start.date() or begins.date() > end.date()):
            raise ValueError("Invalid calendar interval")
        items.append({"id": identifier, "subject": service._text(row.get("summary", ""), 998),
                      "starts_at": starts_at, "ends_at": ends_at, "all_day": all_day,
                      "cancelled": status == "cancelled"})
    current(audit="calendar")
    return {"kind": "calendar", "account": {"label": private["label"], "email": private["email"]},
            "items": items, "more": page is not None, "observed_at": service.now().isoformat()}
