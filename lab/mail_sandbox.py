"""Actual personal-account adapters with bounded, offline provider responses.

No network transport exists here. OAuth, credential custody, refresh, account
fences and summary parsing execute in the product against the owned lab database.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy.orm import sessionmaker

from cosmas_os.adapters.google_connection import GooglePersonalConnection
from cosmas_os.adapters.microsoft_connection import MicrosoftPersonalConnection
from cosmas_os.api.auth import RequestIdentity
from cosmas_os.models import ExternalIdentity
from lab.store import LabError


class MailSandbox:
    def __init__(self, app, provider="microsoft"):
        if provider not in {"microsoft", "google"}:
            raise LabError("unsupported_synthetic_provider")
        self.app, self.provider = app, provider
        self.factory = sessionmaker(app.engine, expire_on_commit=False)
        self.account, self.remote = str(uuid4()), str(uuid4())
        self.now = datetime.now(UTC)
        self.fault: str | None = None
        self.calls = []
        with self.factory() as session:
            session.add(ExternalIdentity(id=self.account, box_id=app.box, principal_id=app.owner,
                issuer="https://identity.example.invalid", subject="lab_" + self.account,
                organization_id="synthetic_clinic", active=True, reviewed_by="synthetic_provider",
                evidence_ref="lab:virtual-clinic"))
            session.commit()
        self.identity = RequestIdentity(app.box, app.owner, "clerk_jwt", "synthetic_clinic", self.account)
        settings = SimpleNamespace(workspace_available=True, workspace_authenticated_enabled=True,
            auth_mode="clerk_jwt", workspace_microsoft_connection_enabled=True,
            workspace_google_connection_enabled=True, microsoft_connection_tenant_id=str(uuid4()),
            microsoft_connection_client_id=str(uuid4()), google_connection_client_id="lab.apps.googleusercontent.com")
        for name in ("google", "microsoft"):
            setattr(settings, name + "_connection_return_origin", "https://lab.example.invalid")
            setattr(settings, name + "_connection_callback_uri", "https://api.example.invalid/connections/" + name + "/callback")
            setattr(settings, name + "_connection_client_secret", SecretStr("invented-lab-secret"))
            setattr(settings, name + "_connection_encryption_key", SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode()))
        cls = MicrosoftPersonalConnection if provider == "microsoft" else GooglePersonalConnection
        self.service = cls(settings, self.factory, transport=httpx.MockTransport(self.respond), now=lambda: self.now)

    def connect(self):
        started = self.service.start(self.identity)
        state = parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]
        if not self.service.callback(state, "invented-code") or self.service.status(self.identity)["state"] != "connected":
            raise LabError("synthetic_sign_in_failed")

    def close(self):
        self.service.close()

    def respond(self, request):
        path, host = request.url.path, request.url.host
        token = request.method == "POST" and str(request.url) == self.service.token_url
        microsoft = host == "graph.microsoft.com" and path in {
            "/v1.0/me", "/v1.0/me/mailFolders/inbox/messages", "/v1.0/me/calendarView"}
        google = (host == "openidconnect.googleapis.com" and path == "/v1/userinfo" or
                  host == "gmail.googleapis.com" and path in {"/gmail/v1/users/me/messages", "/gmail/v1/users/me/messages/lab1"})
        if not token and not (request.method == "GET" and (microsoft or google)):
            raise LabError("unexpected_provider_route")
        self.calls.append({"method": request.method, "path": path})
        is_data = "messages" in path or "calendarView" in path
        if is_data and self.fault == "read_timeout":
            self.fault = None
            raise httpx.ReadTimeout("injected synthetic timeout")
        if is_data and self.fault == "throttled":
            self.fault = None
            return httpx.Response(429, json={"error": "synthetic_throttle"})
        if is_data and self.fault == "revoked_during_read":
            self.fault = None
            with self.factory() as session:
                row = session.get(ExternalIdentity, self.account)
                if row is None:
                    raise LabError("synthetic_account_missing")
                row.active = False
                session.commit()
        if token:
            scopes = "User.Read Mail.Read Calendars.Read" if self.provider == "microsoft" else "openid email https://www.googleapis.com/auth/gmail.metadata"
            payload = dict(access_token="invented-access", refresh_token="invented-refresh", expires_in=3600,
                token_type="Bearer", scope=scopes)
        elif path == "/v1.0/me":
            payload = dict(id=self.remote, displayName="Synthetic clinician", mail="clinician@example.invalid")
        elif path == "/v1/userinfo":
            payload = dict(sub=self.remote, email="clinician@example.invalid", email_verified=True)
        elif path == "/v1.0/me/calendarView":
            if request.url.params.get("$top") != "25":
                raise LabError("unbounded_calendar_query")
            start = datetime.fromisoformat(request.url.params["startDateTime"])
            end = datetime.fromisoformat(request.url.params["endDateTime"])
            if end - start != timedelta(days=7):
                raise LabError("unbounded_calendar_range")
            payload = {"value": [{"id": "lab-appointment", "subject": "Synthetic Jordan Cypress follow-up",
                "start": {"dateTime": "2026-10-01T15:30:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-10-01T16:00:00", "timeZone": "UTC"},
                "isCancelled": False, "isAllDay": False}]}
            if self.fault == "invalid_timezone":
                payload["value"][0]["start"]["timeZone"] = "unrecognized-zone"
        elif path == "/v1.0/me/mailFolders/inbox/messages":
            if request.url.params.get("$top") != "25" or "body" in request.url.params.get("$select", ""):
                raise LabError("unbounded_mail_query")
            row = {"id": "lab-mail", "subject": "Synthetic appointment confirmation requested",
                "from": {"emailAddress": {"address": "jordan@example.invalid"}},
                "receivedDateTime": self.now.isoformat(), "isRead": False}
            payload = {"value": [row] * (26 if self.fault == "oversized" else 1)}
        elif path.endswith("/messages"):
            if request.url.params.get("maxResults") != "10":
                raise LabError("unbounded_gmail_query")
            payload = {"messages": [{"id": "lab1"}] * (11 if self.fault == "oversized" else 1)}
        else:
            if request.url.params.get("format") != "metadata":
                raise LabError("gmail_body_access_denied")
            payload = {"id": "lab1", "internalDate": str(int(self.now.timestamp() * 1000)),
                "labelIds": ["INBOX", "UNREAD"], "payload": {"headers": [
                    {"name": "Subject", "value": "Synthetic appointment confirmation requested"},
                    {"name": "From", "value": "Jordan Cypress <jordan@example.invalid>"}]}}
        return httpx.Response(200, headers={"content-type": "application/json"},
            stream=httpx.ByteStream(json.dumps(payload).encode()))

    def read(self, kind="mail"):
        if kind not in {"mail", "calendar"} or kind == "calendar" and self.provider != "microsoft":
            raise LabError("calendar_not_supported_by_this_adapter")
        return getattr(self.service, kind)(self.identity)


def exercise_mail(app, provider, scenario):
    """Independent episodes keep revoked accounts and faults out of later cases."""
    box = MailSandbox(app, provider)
    checks = {}
    try:
        box.connect()
        checks["oauth_connection_saved"] = True
        kind = "calendar" if scenario == "invalid_timezone" else "mail"
        if scenario == "token_expiry":
            box.now += timedelta(hours=2)
        elif scenario != "normal":
            box.fault = scenario
        before = len(box.calls)
        value, failed = None, False
        try:
            value = box.read(kind)
        except Exception:
            failed = True
        if scenario in {"read_timeout", "throttled", "oversized", "revoked_during_read", "invalid_timezone"}:
            checks["failure_does_not_disclose_or_claim_success"] = failed and value is None
            checks["no_automatic_request_retry"] = len(box.calls) == before + 1
            if scenario in {"read_timeout", "throttled"}:
                checks["account_connection_retained"] = box.service.status(box.identity)["state"] == "connected"
                checks["explicit_retry_recovers"] = len(box.read(kind)["items"]) == 1
        else:
            checks["bounded_mail_read"] = not failed and value is not None and len(value["items"]) == 1
            if provider == "microsoft":
                checks["seven_day_calendar_read"] = len(box.read("calendar")["items"]) == 1
            if scenario == "token_expiry":
                checks["one_refresh_exchange"] = sum(r["method"] == "POST" for r in box.calls[before:]) == 1
        checks["no_mail_or_calendar_writes"] = all(r["method"] == "GET" or "token" in r["path"] for r in box.calls)
        return {"provider": provider, "scenario": scenario, "checks": checks, "passed": all(checks.values()),
                "requests": box.calls, "evidence_level": "real adapter and PostgreSQL; synthetic HTTP responses"}
    finally:
        box.close()
