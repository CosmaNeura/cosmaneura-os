"""Narrow receiver-only transport; no model, cached content or credential fallback."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from azure.identity import ManagedIdentityCredential
from pydantic import SecretStr

from cosmas_os.adapters.core_capture_connection import _CoreClient
from cosmas_os.adapters.core_record_connection import BoundedIdentityTransport
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_record_location import valid_core_web_origin
from cosmas_os.ports.core_visit_prep import (
    CoreVisitPrepList,
    CoreVisitPrepRead,
    CoreVisitPrepReceipt,
    CoreVisitPrepSelections,
)

PATH = "/service/v1/companion/visit-prep/package"
LIST_PATH = "/service/v1/companion/visit-prep/preparations"
MAX_BYTES = 262144


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate_visit_prep_field")
        result[key] = value
    return result


class HttpCoreVisitPrep:
    def __init__(
        self, origin, token, budget, *, transport_factory=None, now=lambda: datetime.now(UTC)
    ):
        if not valid_core_web_origin(origin) or origin.endswith(".localhost"):
            raise ValueError("invalid_visit_prep_origin")
        self.origin, self.token, self.budget, self.now = origin, token, budget, now
        self.http = _CoreClient(
            origin, budget, transport_factory, path_limits={PATH: MAX_BYTES, LIST_PATH: 32768}
        )

    def close(self):
        self.http.close()

    def read(self, request: CoreVisitPrepRead, bearer: SecretStr) -> CoreVisitPrepReceipt:
        return self._read(request, bearer, PATH, CoreVisitPrepReceipt, MAX_BYTES)

    def list(self, request: CoreVisitPrepList, bearer: SecretStr) -> CoreVisitPrepSelections:
        return self._read(request, bearer, LIST_PATH, CoreVisitPrepSelections, 32768)

    def _read(self, request, bearer, path, model, maximum):
        try:
            self.budget.check()
            request = type(request).model_validate(request.model_dump())
            raw = request.model_dump_json().encode()
            if len(raw) > 2048:
                raise ValueError
            tokens = (self.token(), bearer.get_secret_value())
            self.budget.check()
            if any(
                not isinstance(t, str)
                or not 1 <= len(t) <= 8185
                or not t.isascii()
                or any(c.isspace() for c in t)
                for t in tokens
            ):
                raise ValueError
            with self.http.stream(
                "POST",
                self.origin + path,
                json=request.model_dump(mode="json"),
                headers={
                    "Authorization": "Bearer " + tokens[0],
                    "X-Cosmaneura-Provider-Authorization": "Bearer " + tokens[1],
                    "X-Cosmaneura-Visit-Prep-Version": "1",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                if response.status_code in {401, 403}:
                    raise ConnectorUnavailable("visit_prep_access_denied")
                if (
                    response.status_code != 200
                    or response.headers.get_list("x-cosmaneura-visit-prep-version") != ["1"]
                    or response.headers.get("content-type") != "application/json"
                    or response.headers.get("referrer-policy") != "no-referrer"
                    or "no-store" not in response.headers.get("cache-control", "").split(",")
                    or len(response.content) > maximum
                ):
                    raise ValueError
                json.loads(
                    response.content.decode("utf-8"),
                    object_pairs_hook=_pairs,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                )
                result = model.model_validate_json(response.content, strict=True)
                if any(token in response.content.decode("utf-8") for token in tokens):
                    raise ValueError
            now = self.now()
            if (
                path == PATH
                and result.preparation_ref != request.preparation_ref
                or result.connection_sha256 != request.connection_sha256
                or result.workspace_id != request.workspace_id
                or result.request_nonce != request.request_nonce
                or not now - timedelta(seconds=30)
                <= result.checked_at
                <= now + timedelta(seconds=5)
            ):
                raise ValueError
            if path == LIST_PATH and (
                len(result.preparations) > request.limit
                or any(p.preparation_ref == request.before_ref for p in result.preparations)
            ):
                raise ValueError
            self.budget.check()
            return result
        except ConnectorUnavailable:
            raise
        except Exception:
            raise ConnectorUnavailable("visit_prep_unavailable") from None


@contextmanager
def visit_prep_connection(settings, budget):
    budget.check()
    if not settings.workspace_visit_prep_available:
        raise ConnectorUnavailable("visit_prep_unavailable")
    transport = BoundedIdentityTransport(budget)
    credential = ManagedIdentityCredential(
        client_id=settings.core_visit_prep_managed_identity_client_id,
        transport=transport,
        retry_total=0,
        retry_connect=0,
        retry_read=0,
        retry_status=0,
    )
    try:
        connection = HttpCoreVisitPrep(
            settings.core_capture_origin,
            lambda: credential.get_token(settings.core_visit_prep_scope).token,
            budget,
        )
        try:
            yield connection
        finally:
            connection.close()
    finally:
        credential.close()
        transport.close()
