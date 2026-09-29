import gzip
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from cosmas_os.adapters.scheduling import MAX_AVAILABILITY_BYTES, HttpSchedulingAvailability
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import (
    MAX_AVAILABILITY_SLOTS,
    AvailabilitySlot,
    AvailabilityWindow,
    SchedulingSelection,
    build_scheduling_availability,
)

NOW = datetime(2026, 9, 21, 9, tzinfo=UTC)
HEADERS = {"Content-Type": "application/json", "Cache-Control": "private, no-store"}
SLOT = {"starts_at": NOW.isoformat(), "ends_at": (NOW + timedelta(minutes=30)).isoformat()}


@pytest.fixture
def selection():
    return SchedulingSelection(**{name: uuid4() for name in SchedulingSelection.model_fields})


@pytest.fixture
def window():
    return AvailabilityWindow(starts_at=NOW, ends_at=NOW + timedelta(days=1))


def client(handler, **kwargs):
    return HttpSchedulingAvailability(
        kwargs.pop("origin", "https://scheduling.example.invalid"),
        kwargs.pop("staff_credential", lambda selected: SecretStr("PRIVATE_synthetic_staff")),
        transport=httpx.MockTransport(handler), now=kwargs.pop("now", lambda: NOW), **kwargs,
    )


@pytest.mark.parametrize("base_path", ["", "/api"])
def test_existing_staff_route_uses_fresh_scoped_identity_without_ambient_cookies(selection, window, base_path):
    identities, requests = [], []

    def identity(selected):
        identities.append(selected)
        return SecretStr("PRIVATE_synthetic_staff_" + str(selected.owner_id))

    def handle(request):
        requests.append(request)
        current = identities[-1]
        assert request.method == "GET"
        assert request.url.path == f"{base_path}/v1/practitioners/{current.practitioner_id}/availability"
        assert dict(request.url.params) == {
            "from": window.starts_at.isoformat(), "to": window.ends_at.isoformat(),
            "appointmentTypeId": str(current.appointment_type_id), "locationId": str(current.location_id),
        }
        assert request.headers["authorization"] == "Bearer PRIVATE_synthetic_staff_" + str(current.owner_id)
        assert request.headers["x-practice-id"] == str(current.practice_id)
        assert request.headers["cache-control"] == "no-store"
        assert request.headers["accept-encoding"] == "identity"
        assert not request.content
        assert all(name not in request.headers for name in ("x-tenant-id", "cookie", "x-actor-principal-id"))
        assert str(current.box_id) not in str(request.url)
        return httpx.Response(200, json=[SLOT], headers={**HEADERS, "Set-Cookie": "scope=PRIVATE; Path=/"})

    port = client(handle, staff_credential=identity, origin="https://scheduling.example.invalid" + base_path)
    try:
        first = port.availability(selection, window)
        other = selection.model_copy(update={"owner_id": uuid4(), "practice_id": uuid4()})
        second = port.availability(other, window)
        assert identities == [selection, other] and len(requests) == 2
        assert first.selection == selection and second.selection == other
        assert first.slots[0].starts_at == NOW
        assert first.observed_at == NOW
        assert first.google_calendar_coverage == "not_attested"
        assert first.appointment_reserved is False
        assert "PRIVATE" not in repr(first) and str(selection.practice_id) not in repr(first)
    finally:
        port.close()


def test_empty_success_is_not_a_calendar_attestation_or_booking(selection, window):
    port = client(lambda request: httpx.Response(200, json=[], headers=HEADERS))
    try:
        result = port.availability(selection, window)
        assert result.slots == () and result.google_calendar_coverage == "not_attested"
        assert result.appointment_reserved is False
    finally:
        port.close()


@pytest.mark.parametrize("payload", [
    {"slots": [SLOT]}, [None], [{**SLOT, "patient_name": "PRIVATE"}],
    [{**SLOT, "starts_at": NOW.replace(tzinfo=None).isoformat()}],
    [{**SLOT, "starts_at": 1789981200}],
    [{**SLOT, "ends_at": NOW.isoformat()}],
    [{**SLOT, "starts_at": (NOW - timedelta(seconds=1)).isoformat()}],
    [{**SLOT, "ends_at": (NOW + timedelta(days=1, seconds=1)).isoformat()}],
    [SLOT, SLOT], [SLOT] * (MAX_AVAILABILITY_SLOTS + 1),
])
def test_malformed_or_mis_scoped_slots_are_unavailable_not_silently_trimmed(selection, window, payload):
    port = client(lambda request: httpx.Response(200, json=payload, headers=HEADERS))
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_receipt_invalid$") as caught:
            port.availability(selection, window)
        assert "PRIVATE" not in str(caught.value)
    finally:
        port.close()


@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 410, 429, 500, 503])
def test_failure_or_redirect_cannot_become_free_time_or_retry(selection, window, status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, text="PRIVATE remote detail", headers={"Location": "https://other.invalid/PRIVATE"})

    port = client(handle)
    try:
        expected = "scheduling_access_unavailable" if status in {401, 403, 404, 410} else "scheduling_availability_unavailable"
        with pytest.raises(ConnectorUnavailable, match="^" + expected + "$"):
            port.availability(selection, window)
        assert len(calls) == 1
    finally:
        port.close()


@pytest.mark.parametrize("headers", [
    {"Content-Type": "application/json"}, {**HEADERS, "Cache-Control": "private"},
    {**HEADERS, "Content-Type": "text/html"}, {**HEADERS, "Content-Type": "application/problem+json"},
])
def test_confidential_json_is_required(selection, window, headers):
    port = client(lambda request: httpx.Response(200, json=[SLOT], headers=headers))
    try:
        with pytest.raises(ConnectorUnavailable, match="scheduling_receipt_invalid"):
            port.availability(selection, window)
    finally:
        port.close()


@pytest.mark.parametrize("content", [b"PRIVATE malformed", b"[" * 1500, b" " * (MAX_AVAILABILITY_BYTES + 1)])
def test_invalid_deep_or_oversized_json_has_safe_failure(selection, window, content):
    port = client(lambda request: httpx.Response(200, content=content, headers=HEADERS))
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_receipt_invalid$"):
            port.availability(selection, window)
    finally:
        port.close()


def test_compression_rejected_before_expansion_and_stream_closed(selection, window):
    consumed = []

    class Compressed(httpx.SyncByteStream):
        def __iter__(self):
            consumed.append("read")
            yield gzip.compress(b" " * (MAX_AVAILABILITY_BYTES * 2))

        def close(self):
            consumed.append("closed")

    port = client(lambda request: httpx.Response(200, stream=Compressed(), headers={**HEADERS, "Content-Encoding": "gzip"}))
    try:
        with pytest.raises(ConnectorUnavailable, match="scheduling_receipt_invalid"):
            port.availability(selection, window)
        assert consumed == ["closed"]
    finally:
        port.close()


def test_response_stream_is_bounded_and_closed_on_overflow(selection, window):
    consumed = []

    class Large(httpx.SyncByteStream):
        def __iter__(self):
            for number in range(4):
                consumed.append(number)
                yield b" " * (MAX_AVAILABILITY_BYTES // 2)

        def close(self):
            consumed.append("closed")

    port = client(lambda request: httpx.Response(200, stream=Large(), headers=HEADERS))
    try:
        with pytest.raises(ConnectorUnavailable, match="scheduling_receipt_invalid"):
            port.availability(selection, window)
        assert consumed == [0, 1, 2, "closed"]
    finally:
        port.close()


def test_transport_timeout_does_not_leak_or_repeat_request(selection, window):
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("PRIVATE token/provider body", request=request)

    port = client(timeout)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_request_unconfirmed$"):
            port.availability(selection, window)
        assert len(calls) == 1
    finally:
        port.close()


@pytest.mark.parametrize("credential", [None, "PRIVATE_raw", SecretStr(""), SecretStr("a b"), SecretStr("a\nPRIVATE"), SecretStr("é"), SecretStr("a" * 16385)])
def test_unqualified_credential_shape_never_reaches_transport(selection, window, credential):
    calls = []
    port = client(lambda request: calls.append(request), staff_credential=lambda selected: credential)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_identity_unavailable$"):
            port.availability(selection, window)
        assert not calls
    finally:
        port.close()


def test_credential_provider_error_is_sanitized(selection, window):
    def bad_credential(selected):
        raise RuntimeError("PRIVATE credential failure")

    port = client(lambda request: pytest.fail("no request expected"), staff_credential=bad_credential)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_identity_unavailable$"):
            port.availability(selection, window)
    finally:
        port.close()


@pytest.mark.parametrize("changes", [
    {"ends_at": NOW}, {"ends_at": NOW + timedelta(days=31, seconds=1)},
    {"starts_at": NOW.replace(tzinfo=None)},
])
def test_invalid_window_cannot_be_constructed(changes):
    with pytest.raises(ValidationError):
        AvailabilityWindow(**{"starts_at": NOW, "ends_at": NOW + timedelta(days=1), **changes})


def test_window_limit_uses_elapsed_time_across_daylight_saving():
    eastern = ZoneInfo("America/New_York")
    start = datetime(2026, 10, 15, 9, tzinfo=eastern)
    with pytest.raises(ValidationError):
        AvailabilityWindow(starts_at=start, ends_at=start + timedelta(days=31))
    exact = AvailabilityWindow(starts_at=start, ends_at=start.astimezone(UTC) + timedelta(days=31))
    assert exact.ends_at - exact.starts_at == timedelta(days=31)
    assert exact.starts_at.tzinfo == UTC


def test_repeated_clock_hour_does_not_reverse_a_slot():
    eastern = ZoneInfo("America/New_York")
    before = datetime(2026, 11, 1, 1, 45, tzinfo=eastern, fold=0)
    after = datetime(2026, 11, 1, 1, 15, tzinfo=eastern, fold=1)
    slot = AvailabilitySlot(starts_at=before, ends_at=after)
    assert slot.ends_at - slot.starts_at == timedelta(minutes=30)
    with pytest.raises(ValidationError):
        AvailabilitySlot(starts_at=after, ends_at=before)


def test_forged_model_copy_is_revalidated_before_identity(selection, window, recwarn):
    identities = []
    port = client(lambda request: pytest.fail("no request expected"), staff_credential=lambda selected: identities.append(selected))
    try:
        for altered, period in [
            (selection.model_copy(update={"practice_id": "../PRIVATE"}), window),
            (selection, window.model_copy(update={"ends_at": NOW})),
            (None, window), (selection, None),
        ]:
            with pytest.raises(ConnectorUnavailable, match="^scheduling_scope_invalid$"):
                port.availability(altered, period)
        assert not identities
        assert not recwarn
    finally:
        port.close()


@pytest.mark.parametrize("origin", [
    "http://scheduling.invalid", "https://", "https://u:p@scheduling.invalid",
    "https://scheduling.invalid:8046", "https://scheduling.invalid/path",
    "https://scheduling.invalid/?token=PRIVATE", "https://scheduling.invalid/#PRIVATE",
    "https://scheduling.invalid\n", "https://scheduling.invalid/\t", None,
])
def test_origin_cannot_select_credentials_paths_redirects_or_non_https(origin):
    with pytest.raises(ValueError, match="^Scheduling requires a configured HTTPS origin$"):
        HttpSchedulingAvailability(origin, lambda selected: SecretStr("PRIVATE"))


def test_invalid_clock_never_publishes_snapshot(selection, window):
    port = client(lambda request: httpx.Response(200, json=[], headers=HEADERS), now=lambda: NOW.replace(tzinfo=None))
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_clock_unavailable$"):
            port.availability(selection, window)
    finally:
        port.close()


def test_runtime_remains_disconnected_even_with_incidental_environment(selection, window, monkeypatch):
    monkeypatch.setenv("SCHEDULING_ENABLED", "true")
    monkeypatch.setenv("SCHEDULING_API_TOKEN", "PRIVATE")
    with pytest.raises(ConnectorUnavailable, match="^scheduling_connection_unavailable$"):
        build_scheduling_availability().availability(selection, window)
