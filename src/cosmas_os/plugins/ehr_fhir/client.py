"""Vendor-neutral FHIR R4 / US Core read client.

Read-only: only GET is issued. Write HTTP verbs are refused before transport.
Sandbox base URLs are required by default; production hosts stay refused until a
later qualification path sets ``allow_production=True``. Real patient systems are
never the default target. This package does not register CosmaBot tools.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from cosmas_os.plugins.ehr_fhir.errors import (
    READY,
    FhirReadError,
    error_result,
    map_http_status,
    map_operation_outcome,
    messages_for,
)
from cosmas_os.plugins.ehr_fhir.resources import (
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    READABLE_RESOURCES,
    WRITE_HTTP_METHODS,
)
from cosmas_os.plugins.ehr_fhir.urls import assert_allowed_base_url, same_origin


@dataclass(frozen=True, slots=True)
class FhirReadResult:
    """One successful page set or a closed error state. Never includes secrets."""

    state: str
    message: str
    resource_type: str | None = None
    resources: tuple[dict[str, Any], ...] = ()
    pages_read: int = 0
    bytes_read: int = 0
    more_available: bool = False

    @property
    def ok(self) -> bool:
        return self.state == READY

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"state": self.state, "message": self.message}
        if self.state == READY:
            body.update(
                {
                    "resource_type": self.resource_type,
                    "resources": list(self.resources),
                    "pages_read": self.pages_read,
                    "bytes_read": self.bytes_read,
                    "more_available": self.more_available,
                }
            )
        return body


class FhirR4ReadClient:
    """Shared FHIR R4 search/read helper with hard paging and size limits."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        access_token: str | None = None,
        display_label: str = "EHR",
        allow_production: bool = False,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._label = display_label
        self._messages = messages_for(display_label)
        try:
            self._base_url = assert_allowed_base_url(base_url, allow_production=allow_production)
        except ValueError as exc:
            code = str(exc)
            if code == "fhir_base_url_production_refused":
                raise PermissionError("fhir_base_url_production_refused") from exc
            if code == "fhir_base_url_not_sandbox":
                raise PermissionError("fhir_base_url_not_sandbox") from exc
            raise ValueError("fhir_base_url_invalid") from exc
        if type(max_pages) is not int or not 1 <= max_pages <= 20:
            raise ValueError("max_pages_invalid")
        if type(max_response_bytes) is not int or not 1024 <= max_response_bytes <= 2_097_152:
            raise ValueError("max_response_bytes_invalid")
        if type(timeout_seconds) is not float and type(timeout_seconds) is not int:
            raise ValueError("timeout_invalid")
        if not 0.1 <= float(timeout_seconds) <= 120:
            raise ValueError("timeout_invalid")
        if access_token is not None:
            if type(access_token) is not str or not 1 <= len(access_token) <= 16384:
                raise ValueError("access_token_invalid")
            if any(ord(c) < 33 or ord(c) > 126 for c in access_token):
                raise ValueError("access_token_invalid")
        self._token = access_token
        self._transport = transport
        self._max_pages = max_pages
        self._max_bytes = max_response_bytes
        self._timeout = float(timeout_seconds)

    @property
    def base_url(self) -> str:
        return self._base_url

    def read(self, resource_type: str, resource_id: str) -> FhirReadResult:
        refused = self._refuse_resource(resource_type)
        if refused is not None:
            return refused
        if type(resource_id) is not str or not 1 <= len(resource_id) <= 64:
            return self._error("malformed")
        if any(c in resource_id for c in "/?#\\") or resource_id in {".", ".."}:
            return self._error("malformed")
        path = f"{self._base_url}/{resource_type}/{resource_id}"
        return self._get_resource(resource_type, path)

    def search(
        self,
        resource_type: str,
        params: Mapping[str, str] | None = None,
        *,
        follow_paging: bool = True,
    ) -> FhirReadResult:
        refused = self._refuse_resource(resource_type)
        if refused is not None:
            return refused
        query = self._validate_params(params)
        if isinstance(query, FhirReadResult):
            return query
        path = f"{self._base_url}/{resource_type}"
        if query:
            path = f"{path}?{urlencode(sorted(query.items()))}"
        return self._get_search(resource_type, path, follow_paging=follow_paging)

    def create(self, *args: Any, **kwargs: Any) -> FhirReadResult:
        return self._write_refused()

    def update(self, *args: Any, **kwargs: Any) -> FhirReadResult:
        return self._write_refused()

    def patch(self, *args: Any, **kwargs: Any) -> FhirReadResult:
        return self._write_refused()

    def delete(self, *args: Any, **kwargs: Any) -> FhirReadResult:
        return self._write_refused()

    def post(self, *args: Any, **kwargs: Any) -> FhirReadResult:
        return self._write_refused()

    def put(self, *args: Any, **kwargs: Any) -> FhirReadResult:
        return self._write_refused()

    def request(self, method: str, *args: Any, **kwargs: Any) -> FhirReadResult:
        if type(method) is str and method.upper() in WRITE_HTTP_METHODS:
            return self._write_refused()
        if type(method) is str and method.upper() == "GET":
            return self._error("malformed")
        return self._write_refused()

    def _write_refused(self) -> FhirReadResult:
        return FhirReadResult(state="refused", message=self._messages["write_refused"])

    def _error(self, state: str) -> FhirReadResult:
        err = error_result(state, self._label)  # type: ignore[arg-type]
        return FhirReadResult(state=err.state, message=err.message)

    def _from_error(self, err: FhirReadError) -> FhirReadResult:
        return FhirReadResult(state=err.state, message=err.message)

    def _refuse_resource(self, resource_type: str) -> FhirReadResult | None:
        if type(resource_type) is not str or resource_type not in READABLE_RESOURCES:
            return self._error("malformed")
        return None

    def _validate_params(
        self, params: Mapping[str, str] | None
    ) -> dict[str, str] | FhirReadResult:
        if params is None:
            return {}
        if not isinstance(params, Mapping):
            return self._error("malformed")
        cleaned: dict[str, str] = {}
        for key, value in params.items():
            if type(key) is not str or type(value) is not str:
                return self._error("malformed")
            if not 1 <= len(key) <= 64 or not 0 <= len(value) <= 512:
                return self._error("malformed")
            if any(ord(c) < 32 for c in key) or any(ord(c) < 32 for c in value):
                return self._error("malformed")
            cleaned[key] = value
        return cleaned

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/fhir+json",
            "Accept-Encoding": "identity",
        }
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _client(self) -> httpx.Client:
        return httpx.Client(
            transport=self._transport,
            timeout=self._timeout,
            follow_redirects=False,
            trust_env=False,
        )

    def _get_bytes(self, url: str, *, used: int) -> tuple[bytes, int, FhirReadResult | None]:
        if not same_origin(self._base_url, url):
            return b"", used, self._error("stale")
        try:
            with self._client() as client:
                client.cookies.clear()
                with client.stream("GET", url, headers=self._headers()) as response:
                    status = response.status_code
                    if status != 200:
                        body_preview = b""
                        for chunk in response.iter_bytes():
                            body_preview += chunk
                            if len(body_preview) > 8192:
                                break
                        outcome_code = self._outcome_code(body_preview)
                        # Explicit HTTP status mappings win over body issue codes.
                        return b"", used, self._from_error(
                            map_http_status(status, self._label, outcome_code=outcome_code)
                        )
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type not in {"application/fhir+json", "application/json"}:
                        return b"", used, self._error("malformed")
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        used += len(chunk)
                        if used > self._max_bytes:
                            return b"", used, self._error("malformed")
                        raw.extend(chunk)
                    return bytes(raw), used, None
        except httpx.TimeoutException:
            return b"", used, self._error("timeout")
        except httpx.TransportError:
            return b"", used, self._error("not_connected")
        except (httpx.HTTPError, ValueError, TypeError, OSError):
            return b"", used, self._error("malformed")

    def _try_outcome(self, raw: bytes) -> FhirReadError | None:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return None
        if type(payload) is not dict:
            return None
        return map_operation_outcome(payload, self._label)

    def _outcome_code(self, raw: bytes) -> str | None:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return None
        if type(payload) is not dict or payload.get("resourceType") != "OperationOutcome":
            return None
        issues = payload.get("issue")
        if type(issues) is not list:
            return None
        for issue in issues:
            if type(issue) is not dict:
                continue
            severity = issue.get("severity")
            if severity in {"warning", "information"}:
                continue
            code = issue.get("code")
            return code if type(code) is str else None
        return None

    def _parse_json(self, raw: bytes) -> dict[str, Any] | FhirReadResult:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return self._error("malformed")
        if type(payload) is not dict:
            return self._error("malformed")
        outcome = map_operation_outcome(payload, self._label)
        if outcome is not None:
            return self._from_error(outcome)
        return payload

    def _get_resource(self, resource_type: str, url: str) -> FhirReadResult:
        raw, used, failed = self._get_bytes(url, used=0)
        if failed is not None:
            return failed
        parsed = self._parse_json(raw)
        if isinstance(parsed, FhirReadResult):
            return parsed
        if parsed.get("resourceType") != resource_type:
            return self._error("malformed")
        return FhirReadResult(
            state=READY,
            message=self._messages["ready_page"],
            resource_type=resource_type,
            resources=(parsed,),
            pages_read=1,
            bytes_read=used,
            more_available=False,
        )

    def _get_search(
        self, resource_type: str, url: str, *, follow_paging: bool
    ) -> FhirReadResult:
        collected: list[dict[str, Any]] = []
        pages = 0
        used = 0
        more = False
        next_url: str | None = url
        seen: set[str] = set()

        while next_url is not None:
            if next_url in seen:
                return self._error("stale")
            seen.add(next_url)
            if pages >= self._max_pages:
                more = True
                break
            raw, used, failed = self._get_bytes(next_url, used=used)
            if failed is not None:
                return failed
            parsed = self._parse_json(raw)
            if isinstance(parsed, FhirReadResult):
                return parsed
            if parsed.get("resourceType") == resource_type:
                # Instance-shaped search miss is treated as one resource page.
                collected.append(parsed)
                pages += 1
                next_url = None
                continue
            if parsed.get("resourceType") != "Bundle" or parsed.get("type") not in {
                "searchset",
                "collection",
            }:
                return self._error("malformed")
            entries = parsed.get("entry", [])
            if "entry" in parsed and type(entries) is not list:
                return self._error("malformed")
            for entry in entries or []:
                if type(entry) is not dict:
                    return self._error("malformed")
                resource = entry.get("resource")
                if type(resource) is not dict:
                    return self._error("malformed")
                kind = resource.get("resourceType")
                if kind == "OperationOutcome":
                    outcome = map_operation_outcome(resource, self._label)
                    if outcome is not None:
                        return self._from_error(outcome)
                    continue
                if kind != resource_type:
                    # Included companions are ignored; only requested matches are kept.
                    search = entry.get("search")
                    if type(search) is dict and search.get("mode") == "include":
                        continue
                    return self._error("malformed")
                collected.append(resource)
            pages += 1
            next_url = None
            more = False
            if follow_paging:
                for link in parsed.get("link", []) or []:
                    if type(link) is not dict:
                        return self._error("malformed")
                    if link.get("relation") == "next":
                        candidate = link.get("url")
                        if type(candidate) is not str or not candidate:
                            return self._error("malformed")
                        if not same_origin(self._base_url, candidate):
                            return self._error("stale")
                        next_url = candidate
                        more = True
                        break
            if next_url is not None and pages >= self._max_pages:
                more = True
                next_url = None

        if not collected:
            message = self._messages["ready_empty"]
        elif more:
            message = self._messages["ready_more"]
        else:
            message = self._messages["ready_page"]
        return FhirReadResult(
            state=READY,
            message=message,
            resource_type=resource_type,
            resources=tuple(collected),
            pages_read=pages,
            bytes_read=used,
            more_available=more,
        )


def production_base_refused(base_url: str, *, allow_production: bool = False) -> bool:
    """True when constructing a client for ``base_url`` would refuse the host."""
    try:
        assert_allowed_base_url(base_url, allow_production=allow_production)
    except ValueError as exc:
        return str(exc) in {
            "fhir_base_url_production_refused",
            "fhir_base_url_not_sandbox",
            "fhir_base_url_invalid",
        }
    return False
