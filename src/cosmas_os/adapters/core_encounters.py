"""One trusted Core origin and a fresh human session; no redirects or credentials saved."""

import json
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr

from cosmas_os.adapters.core_record_connection import _BoundedHTTP
from cosmas_os.application.core_record_deadline import RecordDeadline
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_encounters import (
    MAX_RESPONSE_BYTES,
    ConnectedRequest,
    DiscoveryRequest,
    DiscoveryResponse,
    EncounterRequest,
    EncountersRequest,
    digest,
)
from cosmas_os.ports.core_record_location import valid_core_web_origin

PATH = "/embed/v1/companion/read"


class CoreDiscoveryDenied(ConnectorUnavailable):
    pass


class CoreEncounterConnection:
    def __init__(self, origin: str, budget: RecordDeadline, *, transport_factory=None,
                 now=lambda: datetime.now(UTC)):
        if not valid_core_web_origin(origin) or origin.endswith(".localhost"):
            raise ValueError("invalid_core_encounter_origin")
        self.origin, self.budget, self.now = origin, budget, now
        self.http = _BoundedHTTP(budget, transport_factory, max_bytes=MAX_RESPONSE_BYTES)

    def close(self):
        self.http.close()

    def setup_appointments(self, request, bearer):
        from cosmas_os.adapters.core_appointment_setup import setup_appointments
        return setup_appointments(self, request, bearer)

    def athena_visit_link(self, request, bearer):
        from cosmas_os.adapters.core_athena_visit_links import athena_visit_link
        return athena_visit_link(self, request, bearer)

    def read_athena(self, request, bearer):
        from cosmas_os.adapters.core_athena import read_athena
        return read_athena(self, request, bearer)

    def scribe_workspace(self, discovery, bearer):
        from cosmas_os.adapters.core_scribe_encounters import canonical_workspace
        return canonical_workspace(self, discovery, bearer)

    def read(self, request: DiscoveryRequest, bearer: SecretStr) -> DiscoveryResponse:
        self.budget.check()
        token = bearer.get_secret_value()
        if not 1 <= len(token) <= 8192 or not token.isascii() or any(c.isspace() for c in token):
            raise CoreDiscoveryDenied("core_connection_access_denied")
        raw = request.model_dump_json().encode("utf-8")
        if len(raw) > 2048:
            raise ValueError("invalid_core_encounter_request")
        try:
            response = self.http.request("POST", self.origin + PATH, headers={
                "Authorization": "Bearer " + token, "X-Cosmaneura-Record-Version": "1",
                "Content-Type": "application/json", "Accept": "application/json",
            }, content=raw)
            try:
                if response.status_code in (401, 403):
                    raise CoreDiscoveryDenied("core_connection_access_denied")
                if (response.status_code != 200
                    or response.headers.get_list("x-cosmaneura-record-version") != ["1"]
                    or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                    or "no-store" not in response.headers.get("cache-control", "").split(",")
                    or str(response.request.url) != self.origin + PATH):
                    raise ValueError("invalid_core_encounter_response")
                def pairs(values):
                    result = {}
                    for key, value in values:
                        if key in result:
                            raise ValueError("duplicate_field")
                        result[key] = value
                    return result
                value = json.loads(response.content.decode("utf-8"), object_pairs_hook=pairs,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_number")))
                result = DiscoveryResponse.model_validate(value)
                if (result.action != request.action or result.request_nonce != request.request_nonce
                    or result.connection.tenant_ref != request.expected_tenant_ref
                    or not self.now()-timedelta(seconds=30) <= result.checked_at <= self.now()+timedelta(seconds=5)):
                    raise ValueError("core_connection_changed")
                if isinstance(request, ConnectedRequest) and (
                    result.connection.actor_ref != request.expected_actor_ref
                    or result.connection.connection_sha256 != request.connection_sha256):
                    raise ValueError("core_connection_changed")
                if isinstance(request, EncounterRequest) and (
                    result.encounters[0].appointment.appointment_ref != request.appointment_ref
                    or result.encounters[0].source_sha256 != request.source_sha256):
                    raise ValueError("core_encounter_changed")
                if isinstance(request, EncountersRequest):
                    if (any(not request.window.start_date <= e.appointment.appointment_date.date() < request.window.end_date
                            for e in result.encounters)
                        or result.next_cursor is not None and result.next_cursor.window_sha256 != digest(request.window.model_dump(mode="json"))):
                        raise ValueError("core_encounter_window_changed")
                self.budget.check()
                return result
            finally:
                response.close()
        except CoreDiscoveryDenied:
            raise
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ConnectorUnavailable("core_connection_unavailable") from None
