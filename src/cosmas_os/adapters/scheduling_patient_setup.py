"""Default-closed client for the proposed read-only patient identity receiver.

No runtime installs this adapter. It has no legacy lookup fallback, automatic
retry, mapping write or booking action. Receiver deployment and identity/version
semantics require separate qualification before an explicit host can enable it.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic

import httpx
from pydantic import SecretStr

from cosmas_os.adapters.scheduling_google_login import exact_origin
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import SchedulingSelection
from cosmas_os.ports.scheduling_patient_setup import (
    MAX_PREVIEW_BYTES,
    MAX_VERIFY_BYTES,
    PatientPreview,
    PatientPreviewRequest,
    PatientVerification,
    PatientVerifyRequest,
    validate_preview,
    validate_verification,
)

PATH = "/v1/companion/patient-correspondence/"
VERSION_HEADER = "X-Cosmaneura-Patient-Correspondence"


class HttpSchedulingPatientSetup:
    def __init__(self, origin: str, staff_credential: Callable, *, enabled: Callable[[], bool] | None = None,
                 transport: httpx.BaseTransport | None = None, now=lambda: datetime.now(UTC)):
        self._origin = exact_origin(origin, allow_api_path=True)
        self._credential, self._enabled, self._now = staff_credential, enabled, now
        self._closed = False
        self._client = httpx.Client(timeout=10, follow_redirects=False, trust_env=False, transport=transport,
                                   limits=httpx.Limits(max_connections=4, max_keepalive_connections=2))

    def close(self):
        self._closed = True
        self._client.close()

    def _gate(self):
        if self._closed or self._enabled is None or self._enabled() is not True:
            raise ConnectorUnavailable("scheduling_patient_setup_unavailable")

    def _clock(self):
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError
        return value.astimezone(UTC)

    def _exchange(self, selection, action, request, response_type, limit):
        self._gate()
        if not isinstance(selection, SchedulingSelection):
            raise ValueError
        selected = SchedulingSelection.model_validate(selection.model_dump(warnings=False))
        if selected.expected_actor_id is None or request.expected_actor_id != selected.expected_actor_id:
            raise ValueError
        self._clock()
        credential = self._credential(selected)
        if not isinstance(credential, SecretStr):
            raise ValueError
        token = credential.get_secret_value()
        if not 1 <= len(token) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError
        self._gate()
        raw = request.model_dump_json().encode()
        if len(raw) > 1024:
            raise ValueError
        wire = self._client.build_request("POST", self._origin + PATH + action, content=raw, headers={
            "Authorization": "Bearer " + token, "X-Practice-ID": str(selected.practice_id),
            VERSION_HEADER: "1", "Accept": "application/json", "Content-Type": "application/json",
            "Accept-Encoding": "identity", "Cache-Control": "no-store",
        })
        wire.headers.pop("Cookie", None)
        deadline = monotonic() + 10
        response = self._client.send(wire, stream=True, follow_redirects=False)
        try:
            if (response.status_code != 200 or str(response.request.url) != str(wire.url)
                or response.headers.get_list(VERSION_HEADER) != ["1"]
                or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                or response.headers.get("content-encoding", "identity").lower() != "identity"
                or "no-store" not in {v.strip().lower() for v in response.headers.get("cache-control", "").split(",")}):
                raise ValueError
            data = bytearray()
            for part in response.iter_bytes():
                if monotonic() >= deadline or len(data) + len(part) > limit:
                    raise ValueError
                data.extend(part)
        finally:
            response.close()
        if monotonic() >= deadline:
            raise ValueError

        def pairs(values):
            result = {}
            for key, value in values:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        result = response_type.model_validate(value)
        self._gate()
        return result

    def preview(self, selection, request):
        try:
            if not isinstance(request, PatientPreviewRequest):
                raise ValueError
            request = PatientPreviewRequest.model_validate(request.model_dump(warnings=False))
            if request.selector.kind == "search" and request.selector.birth_date is not None and request.selector.birth_date > self._clock().date():
                raise ValueError
            result = self._exchange(selection, "preview", request, PatientPreview, MAX_PREVIEW_BYTES)
            validate_preview(selection, request, result, self._clock())
            self._gate()
            return result
        except Exception:
            raise ConnectorUnavailable("scheduling_patient_setup_unavailable") from None

    def verify(self, selection, request, preview):
        try:
            if not isinstance(request, PatientVerifyRequest) or not isinstance(preview, PatientPreview):
                raise ValueError
            request = PatientVerifyRequest.model_validate(request.model_dump(warnings=False))
            preview = PatientPreview.model_validate(preview.model_dump(warnings=False))
            choice = next((v for v in preview.choices if v.choice_ref == request.choice_ref), None)
            if (choice is None or choice.identity_sha256 != request.identity_sha256 or request.lookup_ref != preview.lookup_ref
                or preview.expires_at <= self._clock() or preview.practice_id != selection.practice_id
                or preview.actor_id != selection.expected_actor_id
                or preview.checked_at > self._clock() + timedelta(seconds=5)):
                raise ValueError
            result = self._exchange(selection, "verify", request, PatientVerification, MAX_VERIFY_BYTES)
            validate_verification(selection, request, preview, result, self._clock())
            self._gate()
            return result
        except Exception:
            raise ConnectorUnavailable("scheduling_patient_setup_unavailable") from None
