"""Opaque process-scoped pagination; restart simply requires a fresh listing."""

import base64
import hashlib
import hmac
import json
import secrets

from cosmas_os.application import workspace as ws

_KEY = secrets.token_bytes(32)


def encode(scope, after):
    raw = json.dumps(
        {"scope": scope, "after": after}, sort_keys=True, separators=(",", ":")
    ).encode()
    return (
        base64.urlsafe_b64encode(raw).decode().rstrip("=")
        + "."
        + hmac.digest(_KEY, raw, "sha256").hex()
    )


def decode(scope, cursor):
    if cursor is None:
        return None
    try:
        if type(cursor) is not str or len(cursor) > 512 or not cursor.isascii():
            raise ValueError
        encoded, signature = cursor.split(".")
        raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        if not hmac.compare_digest(hmac.digest(_KEY, raw, hashlib.sha256).hex(), signature):
            raise ValueError
        value = json.loads(raw)
        if set(value) != {"scope", "after"} or value["scope"] != scope:
            raise ValueError
        return value["after"]
    except (ValueError, TypeError, UnicodeError):
        raise ws.WorkspaceError("invalid_finance_request", 400) from None
