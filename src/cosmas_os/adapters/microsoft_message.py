"""One selected Graph message using the existing delegated Mail.Read grant.

Only the server supplies the origin and path. Graph renders the requested text
representation; attachments (including inline attachments) require human review.
No URL, attachment body, remote image, or mailbox write is followed.
"""

import hashlib
import json
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import quote

from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import check_capture_deadline
from cosmas_os.ports.microsoft_message import MicrosoftMessageRead, MicrosoftMessageSelection

SELECT = "id,conversationId,changeKey,subject,from,receivedDateTime,isRead,hasAttachments,body"
MAX_BYTES = 131072


def read_message(service, identity, selection: MicrosoftMessageSelection) -> MicrosoftMessageRead:
    selection = MicrosoftMessageSelection.model_validate(selection)
    service._full_message_enabled()
    private, binding, account_id = service.credential(identity)
    custody = service.message_binding(identity, require_full=True)
    if (custody.account_id, custody.binding_digest) != (account_id, binding):
        raise ws.WorkspaceError("microsoft_message_grant_changed")

    def current():
        check_capture_deadline()
        service._full_message_enabled()
        if service.message_binding(identity, require_full=True) != custody:
            raise ws.WorkspaceError("microsoft_message_grant_changed")

    current()
    url = "https://graph.microsoft.com/v1.0/me/messages/" + quote(selection.message_id, safe="")
    headers = {"Accept": "application/json", "Accept-Encoding": "identity",
               "Authorization": "Bearer " + private["token"],
               "Prefer": 'outlook.body-content-type="text"'}
    deadline = monotonic() + 10
    raw = bytearray()
    with service._client.stream("GET", url, headers=headers,
                               params={"$select": SELECT, "$expand": "attachments($select=id,isInline)"}) as response:
        if response.status_code != 200:
            if response.status_code == 401:
                service._message_authentication_failed(identity, private, custody)
            code = {401: "authentication_required", 403: "permission_denied", 404: "record_unavailable",
                    429: "rate_limited"}.get(response.status_code, "read_unconfirmed")
            raise ws.WorkspaceError("microsoft_message_" + code, 503)
        if (response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json"
                or response.headers.get("content-encoding") not in {None, "identity"}):
            raise ws.WorkspaceError("microsoft_message_response_invalid", 502)
        for chunk in response.iter_raw():
            current()
            if monotonic() >= deadline or len(raw) + len(chunk) > MAX_BYTES:
                raise ws.WorkspaceError("microsoft_message_response_too_large", 502)
            raw.extend(chunk)
    current()
    if monotonic() >= deadline:
        raise ws.WorkspaceError("microsoft_message_read_unconfirmed", 503)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique)
        result = parse_message(value, selection, custody, service.now())
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ws.WorkspaceError("microsoft_message_response_invalid", 502) from None
    current()
    return result


def parse_message(value, selection, custody, now):
    if not isinstance(value, dict) or value.get("id") != selection.message_id:
        raise ValueError("different message")
    thread, change = value.get("conversationId"), value.get("changeKey")
    MicrosoftMessageSelection(message_id=value["id"], thread_id=thread)
    if thread is None or selection.thread_id is not None and thread != selection.thread_id:
        raise ValueError("different conversation")
    if type(value.get("isRead")) is not bool or type(value.get("hasAttachments")) is not bool:
        raise ValueError("missing message flags")
    subject, sender = value.get("subject"), value.get("from", {}).get("emailAddress", {}).get("address")
    if not isinstance(subject, str) or not isinstance(sender, str):
        raise ValueError("invalid header")
    for text, limit in ((subject, 998), (sender, 320)):
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 or ord(c) == 127 for c in text):
            raise ValueError("invalid header")
    stamp = value.get("receivedDateTime")
    if not isinstance(stamp, str) or len(stamp) > 64:
        raise ValueError("invalid time")
    received = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if received.utcoffset() is None:
        raise ValueError("invalid time")
    attachments, body = value.get("attachments"), value.get("body")
    reason = None
    content = None
    if not isinstance(attachments, list) or len(attachments) > 25 or "attachments@odata.nextLink" in value:
        reason = "ambiguous"
    elif value["hasAttachments"] or attachments:
        reason = "attachment"
    elif not isinstance(body, dict) or set(body) != {"contentType", "content"}:
        reason = "ambiguous"
    elif body["contentType"] == "html":
        reason = "html_only"
    elif body["contentType"] != "text":
        reason = "unsupported_mime"
    elif not isinstance(body["content"], str) or any(ord(c) < 32 and c not in "\r\n\t" or ord(c) == 127 for c in body["content"]):
        reason = "invalid_encoding"
    else:
        text = body["content"].replace("\r\n", "\n")
        content = f"Subject: {subject}\nFrom: {sender}\nReceived: {received.astimezone(UTC).isoformat()}\n\n{text}"
        if not text.strip():
            reason, content = "ambiguous", None
        elif len(content) > 5000:
            reason, content = "oversize", None
    return MicrosoftMessageRead(message_id=value["id"], thread_id=thread, change_key=change,
        subject=subject, sender=sender, received_at=received, is_read=value["isRead"], observed_at=now,
        status="needs_human" if reason else "complete", reason=reason, content=content,
        raw_sha256=hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        content_sha256=hashlib.sha256(content.encode()).hexdigest() if content is not None else None,
        custody=custody)
