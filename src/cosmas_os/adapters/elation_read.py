"""Bounded Elation REST reads; construction never connects to a provider.

Reference: https://help.elationhealth.com/articles/rest/overview/oauth
Resource contracts: https://help.elationhealth.com/articles/rest/overview/api-overview
Production is intentionally unavailable until qualified.
These private observations confer no chart-write or patient-link authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import SecretStr

ORIGIN = "https://sandbox.elationemr.com"
SCOPES = "system/practices.read system/appointments.read system/patients.read"
MAX_BODY = 1_048_576
PAGE_SIZE = 25
MAX_ID = 9_223_372_036_854_775_807
STATUSES = frozenset(("Scheduled", "Confirmed", "Checked Out", "Cancelled", "With Doctor",
    "In Room", "Checked In", "In Room - Vitals Taken", "Not Seen", "Billed"))


class ElationReadError(Exception):
    """Closed errors contain no patient content, credentials or provider text."""

    def __init__(self, code: str):
        if code not in {"disabled", "not_configured", "access_denied", "connection_changed",
                "invalid_request", "authentication_required", "permission_denied",
                "record_unavailable", "rate_limited", "timeout", "unavailable",
                "invalid_response", "response_too_large"}:
            code = "invalid_response"
        self.code = code
        super().__init__(code)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def _id(value, error="invalid_response") -> int:
    if type(value) is not int or not 0 < value <= MAX_ID:
        raise ElationReadError(error)
    return value


def _text(value, maximum, error="invalid_response") -> str:
    if (type(value) is not str or not 1 <= len(value) <= maximum
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ElationReadError(error)
    return value


def _stamp(value) -> datetime:
    if type(value) is not str or len(value) > 40:
        raise ElationReadError("invalid_response")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        raise ElationReadError("invalid_response") from None


def _optional_stamp(row, key):
    return None if row.get(key) is None else _stamp(row[key])


@dataclass(frozen=True, repr=False)
class ElationReadScope:
    box_id: UUID
    owner_id: UUID
    connection_id: UUID
    credential_generation: UUID
    practice_id: int
    practice_name: str
    environment: Literal["sandbox"] = "sandbox"

    def commitment(self) -> str:
        return _digest({"contract": "elation-read-scope.v1", **asdict(self)})


@dataclass(frozen=True, repr=False)
class ElationCredentials:
    scope_sha256: str
    client_id: SecretStr
    client_secret: SecretStr


@dataclass(frozen=True, repr=False)
class ElationPractice:
    practice_id: int
    name: str
    timezone: str
    active_physician_ids: tuple[int, ...]


@dataclass(frozen=True, repr=False)
class ElationPatient:
    patient_id: int
    first_name: str
    last_name: str
    birth_date: date
    primary_physician_id: int
    deleted_at: datetime | None


@dataclass(frozen=True, repr=False)
class ElationAppointment:
    appointment_id: int
    patient_id: int | None
    physician_id: int
    starts_at: datetime
    ends_at: datetime
    source_status: str | None
    scheduled_date_raw: str
    deleted_at: datetime | None


@dataclass(frozen=True, repr=False)
class ElationCursor:
    query_sha256: str
    value: str


@dataclass(frozen=True, repr=False)
class ElationReadResult:
    """One returned page or record; end_of_results describes pagination only."""

    scope: ElationReadScope
    operation: str
    request_sha256: str
    observed_at: datetime
    rows: tuple[ElationPractice | ElationPatient | ElationAppointment, ...]
    next_cursor: ElationCursor | None
    source_sha256: str
    coverage: Literal["end_of_results", "more_rows_available", "selected_record"]


class ElationReadAdapter:
    """The host must share one adapter per credential and recheck real authority.

    A permit callback can enforce a cross-process credential budget; the local
    limiter remains in force. A new cursor belongs only to its exact query and
    connection generation. Resolve/replay custody belongs to the application,
    not this adapter. There are no resource-write methods or automatic retries.
    """

    def __init__(self, scope: ElationReadScope,
            credentials: Callable[[ElationReadScope], Awaitable[ElationCredentials]], *,
            enabled: bool = False,
            authorize_read: Callable[[ElationReadScope], Awaitable[bool]] | None = None,
            permit_request: Callable[[ElationReadScope], Awaitable[bool]] | None = None,
            transport: httpx.AsyncBaseTransport | None = None,
            now: Callable[[], datetime] = lambda: datetime.now(UTC),
            monotonic: Callable[[], float] = time.monotonic,
            sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        if (type(scope) is not ElationReadScope or type(enabled) is not bool
                or scope.environment != "sandbox"
                or any(type(v) is not UUID for v in (scope.box_id, scope.owner_id,
                    scope.connection_id, scope.credential_generation))):
            raise ElationReadError("invalid_request")
        _id(scope.practice_id, "invalid_request")
        _text(scope.practice_name, 200, "invalid_request")
        self.scope, self.credentials, self.enabled = scope, credentials, enabled
        self.authorize_read, self.permit_request = authorize_read, permit_request
        self.transport, self.now, self.monotonic, self.sleep = transport, now, monotonic, sleep
        self._token: SecretStr | None = None
        self._token_until = 0.0
        self._credential_commitment: str | None = None
        self._token_lock, self._rate_lock = asyncio.Lock(), asyncio.Lock()
        self._calls: deque[float] = deque()

    def __repr__(self):
        return "ElationReadAdapter(<protected>)"

    async def _authorize(self):
        if not self.enabled:
            raise ElationReadError("disabled")
        try:
            allowed = self.authorize_read is not None and await self.authorize_read(self.scope) is True
        except Exception:
            allowed = False
        if not allowed:
            self._token = None
            raise ElationReadError("access_denied")

    async def _permit(self):
        if self.permit_request is not None and await self.permit_request(self.scope) is not True:
            raise ElationReadError("rate_limited")
        async with self._rate_lock:
            now = self.monotonic()
            while self._calls and now - self._calls[0] >= 86400:
                self._calls.popleft()
            if len(self._calls) >= 149_999:
                raise ElationReadError("rate_limited")
            if self._calls:
                await self.sleep(max(0.0, self._calls[-1] + 0.51 - now))
            self._calls.append(self.monotonic())

    async def _json(self, client, method, path, *, params=None, form=None, token=None):
        await self._authorize()
        await self._permit()
        await self._authorize()
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token.get_secret_value()
        async with client.stream(method, ORIGIN + path, params=params, data=form, headers=headers) as response:
            if response.status_code != 200:
                code = {401: "authentication_required", 403: "permission_denied",
                    404: "record_unavailable", 410: "record_unavailable", 429: "rate_limited"}.get(
                        response.status_code, "unavailable" if response.status_code >= 500 else "invalid_response")
                if response.status_code == 401:
                    self._token = None
                raise ElationReadError(code)
            if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ElationReadError("invalid_response")
            if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                raise ElationReadError("invalid_response")
            maximum = 16_384 if form is not None else MAX_BODY
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > maximum:
                    raise ElationReadError("response_too_large")
                raw.extend(chunk)
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result
        def invalid(_):
            raise ValueError
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid)
        if type(value) is not dict:
            raise ElationReadError("invalid_response")
        await self._authorize()
        return value

    async def _access_token(self, client):
        async with self._token_lock:
            await self._authorize()
            supplied = await self.credentials(self.scope)
            if (type(supplied) is not ElationCredentials
                    or supplied.scope_sha256 != self.scope.commitment()):
                raise ElationReadError("connection_changed")
            if type(supplied.client_id) is not SecretStr or type(supplied.client_secret) is not SecretStr:
                raise ElationReadError("not_configured")
            identity = _text(supplied.client_id.get_secret_value(), 1024, "not_configured")
            secret = _text(supplied.client_secret.get_secret_value(), 4096, "not_configured")
            commitment = _digest([self.scope.commitment(), identity, secret])
            if self._credential_commitment is not None and self._credential_commitment != commitment:
                self._token = None
                raise ElationReadError("connection_changed")
            self._credential_commitment = commitment
            if self._token is not None and self.monotonic() < self._token_until:
                return self._token
            began = self.monotonic()
            value = await self._json(client, "POST", "/api/2.0/oauth2/token/", form={
                "grant_type": "client_credentials", "client_id": identity,
                "client_secret": secret, "scope": SCOPES,
            })
            token = _text(value.get("access_token"), 8192)
            lifetime = value.get("expires_in")
            if (not token.isascii() or any(c.isspace() for c in token)
                    or value.get("token_type") != "Bearer" or type(lifetime) is not int
                    or not 1 <= lifetime <= 31_536_000
                    or type(value.get("scope")) is not str
                    or set(value["scope"].split()) != set(SCOPES.split())):
                raise ElationReadError("invalid_response")
            self._token = SecretStr(token)
            self._token_until = began + lifetime - min(30, lifetime / 10)
            return self._token

    def _query_hash(self, path, params):
        return _digest({"scope": self.scope.commitment(), "path": path, "params": params})

    def _continuation(self, value, path, params, query_hash, current):
        if value is None:
            return None
        if (type(value) is not str or len(value) > 8192
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ElationReadError("invalid_response")
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc != urlsplit(ORIGIN).netloc
                or parsed.path not in (path, path.removesuffix("/")) or parsed.fragment):
            raise ElationReadError("invalid_response")
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=12)
        fields = dict(pairs)
        cursor = fields.pop("cursor", None)
        # Some documented next links carry only a cursor. Reconstruct the
        # request from the original filters; never follow the provider URL.
        if (len(pairs) != len(dict(pairs)) or any(params.get(k) != v for k, v in fields.items())
                or type(cursor) is not str or not 1 <= len(cursor) <= 2048
                or not cursor.isascii() or any(c.isspace() or ord(c) < 32 for c in cursor)
                or current is not None and cursor == current.value):
            raise ElationReadError("invalid_response")
        return ElationCursor(query_hash, cursor)

    async def _read(self, path, params, parser, *, cursor=None, page=False):
        try:
            async with asyncio.timeout(30):
                await self._authorize()
                query_hash = self._query_hash(path, params)
                sent = dict(params)
                if cursor is not None:
                    if (not page or type(cursor) is not ElationCursor
                            or cursor.query_sha256 != query_hash or type(cursor.value) is not str
                            or not 1 <= len(cursor.value) <= 2048 or not cursor.value.isascii()
                            or any(c.isspace() or ord(c) < 32 for c in cursor.value)):
                        raise ElationReadError("invalid_request")
                    sent["cursor"] = cursor.value
                async with httpx.AsyncClient(transport=self.transport, trust_env=False,
                        follow_redirects=False, timeout=10) as client:
                    token = await self._access_token(client)
                    client.cookies.clear()  # OAuth bearer authority never gains a cookie session.
                    value = await self._json(client, "GET", path, params=sent, token=token)
                if page:
                    items = value.get("results")
                    if (type(items) is not list or len(items) > PAGE_SIZE
                            or "next" not in value or "previous" not in value):
                        raise ElationReadError("invalid_response")
                    following = self._continuation(value["next"], path, params, query_hash, cursor)
                    rows = tuple(parser(item) for item in items)
                    if any(type(item) is not dict for item in items):
                        raise ElationReadError("invalid_response")
                    ids = [item.get("id") for item in items]
                    if len(set(ids)) != len(ids) or not rows and following is not None:
                        raise ElationReadError("invalid_response")
                    coverage = "more_rows_available" if following else "end_of_results"
                else:
                    rows, following, coverage = (parser(value),), None, "selected_record"
                await self._authorize()
                observed = self.now()
                if type(observed) is not datetime or observed.utcoffset() is None:
                    raise ElationReadError("invalid_response")
                observed = observed.astimezone(UTC)
                request_hash = self._query_hash(path, sent)
                source_hash = _digest({"scope": self.scope.commitment(), "request": request_hash,
                    "observed_at": observed, "rows": [asdict(row) for row in rows],
                    "next": asdict(following) if following else None, "coverage": coverage})
                return ElationReadResult(self.scope, path, request_hash, observed,
                    rows, following, source_hash, coverage)
        except ElationReadError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise ElationReadError("timeout") from None
        except httpx.HTTPError:
            raise ElationReadError("unavailable") from None
        except Exception:
            raise ElationReadError("invalid_response") from None

    def _patient(self, row):
        if (type(row) is not dict or row.get("caregiver_practice") != self.scope.practice_id
                or "deleted_date" not in row):
            raise ElationReadError("invalid_response")
        _id(row.get("caregiver_practice"))
        dob = row.get("dob")
        if type(dob) is not str or len(dob) != 10:
            raise ElationReadError("invalid_response")
        return ElationPatient(_id(row.get("id")), _text(row.get("first_name"), 70),
            _text(row.get("last_name"), 70), date.fromisoformat(dob),
            _id(row.get("primary_physician")), _optional_stamp(row, "deleted_date"))

    def _appointment(self, row):
        if (type(row) is not dict or row.get("practice") != self.scope.practice_id
                or row.get("time_slot_type") != "appointment" or "status" not in row
                or "deleted_date" not in row):
            raise ElationReadError("invalid_response")
        _id(row.get("practice"))
        start = _stamp(row.get("scheduled_date"))
        duration, state = row.get("duration"), row.get("status")
        if type(duration) is not int or not 1 <= duration <= 1440:
            raise ElationReadError("invalid_response")
        status = None
        if state is not None:
            if type(state) is not dict or state.get("status") not in STATUSES:
                raise ElationReadError("invalid_response")
            status = state["status"]
        return ElationAppointment(_id(row.get("id")),
            None if row.get("patient") is None else _id(row["patient"]),
            _id(row.get("physician")), start, start + timedelta(minutes=duration), status,
            row["scheduled_date"], _optional_stamp(row, "deleted_date"))

    async def practice(self) -> ElationReadResult:
        def parse(row):
            if (type(row) is not dict or _id(row.get("id")) != self.scope.practice_id
                    or row.get("status") != "active"):
                raise ElationReadError("invalid_response")
            timezone = _text(row.get("timezone"), 100)
            try:
                ZoneInfo(timezone)
            except (ValueError, ZoneInfoNotFoundError):
                raise ElationReadError("invalid_response") from None
            ids = row.get("physicians")
            if type(ids) is not list or len(ids) > 100 or len(set(ids)) != len(ids):
                raise ElationReadError("invalid_response")
            return ElationPractice(self.scope.practice_id, _text(row.get("name"), 200),
                timezone, tuple(_id(value) for value in ids))
        return await self._read(f"/api/2.0/practices/{self.scope.practice_id}/", {}, parse)

    async def appointments(self, starts_at: datetime, ends_at: datetime, *,
            physician_id: int | None = None, cursor: ElationCursor | None = None) -> ElationReadResult:
        """Return a page within the inclusive UTC bounds; never availability.

        Both endpoints are retained because the vendor does not document their
        inclusivity. Application day views must deduplicate boundary records.
        """
        if (type(starts_at) is not datetime or type(ends_at) is not datetime
                or starts_at.utcoffset() is None or ends_at.utcoffset() is None):
            raise ElationReadError("invalid_request")
        starts_at, ends_at = starts_at.astimezone(UTC), ends_at.astimezone(UTC)
        if not timedelta(0) < ends_at - starts_at <= timedelta(days=7):
            raise ElationReadError("invalid_request")
        params = {"practice": str(self.scope.practice_id), "limit": str(PAGE_SIZE),
            "from_date": starts_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "to_date": ends_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "time_slot_type": "appointment"}
        if physician_id is not None:
            params["physician"] = str(_id(physician_id, "invalid_request"))
        def parse(row):
            item = self._appointment(row)
            if (not starts_at <= item.starts_at <= ends_at
                    or physician_id is not None and item.physician_id != physician_id):
                raise ElationReadError("invalid_response")
            return item
        return await self._read("/api/2.0/appointments/", params, parse, cursor=cursor, page=True)

    async def appointment(self, appointment_id: int) -> ElationReadResult:
        selected = _id(appointment_id, "invalid_request")
        def parse(row):
            item = self._appointment(row)
            if item.appointment_id != selected:
                raise ElationReadError("invalid_response")
            if item.deleted_at is not None:
                raise ElationReadError("record_unavailable")
            return item
        return await self._read(f"/api/2.0/appointments/{selected}/", {}, parse)

    async def patients(self, first_name: str, last_name: str, birth_date: date, *,
            cursor: ElationCursor | None = None) -> ElationReadResult:
        _text(first_name, 70, "invalid_request")
        _text(last_name, 70, "invalid_request")
        if (type(birth_date) is not date or first_name != first_name.strip()
                or last_name != last_name.strip()):
            raise ElationReadError("invalid_request")
        params = {"practice": str(self.scope.practice_id), "limit": str(PAGE_SIZE),
            "first_name": first_name, "last_name": last_name, "dob": birth_date.isoformat()}
        def parse(row):
            item = self._patient(row)
            if (item.first_name.casefold() != first_name.casefold()
                    or item.last_name.casefold() != last_name.casefold() or item.birth_date != birth_date):
                raise ElationReadError("invalid_response")
            return item
        return await self._read("/api/2.0/patients/", params, parse, cursor=cursor, page=True)

    async def patient(self, patient_id: int) -> ElationReadResult:
        selected = _id(patient_id, "invalid_request")
        def parse(row):
            item = self._patient(row)
            if item.patient_id != selected:
                raise ElationReadError("invalid_response")
            if item.deleted_at is not None:
                raise ElationReadError("record_unavailable")
            return item
        return await self._read(f"/api/2.0/patients/{selected}/", {}, parse)
