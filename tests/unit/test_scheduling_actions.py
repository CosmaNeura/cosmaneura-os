import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from cosmas_os.adapters.scheduling_actions import MAX_APPOINTMENT_BYTES, HttpSchedulingAppointments
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling_actions import (
    AppointmentIntent,
    AppointmentOperation,
    AppointmentSelection,
    AppointmentSnapshot,
    build_scheduling_appointments,
)

NOW = datetime(2026, 9, 21, 14, tzinfo=UTC)
HEADERS = {"Content-Type": "application/json", "Cache-Control": "private, no-store"}


@pytest.fixture
def selected():
    return AppointmentSelection(**{name: uuid4() for name in AppointmentSelection.model_fields})


def snapshot(selected, **changes):
    return AppointmentSnapshot(**{
        "id": uuid4(), "version": 7, "status": "confirmed", "client_id": None,
        **{name: getattr(selected, name) for name in (
            "practitioner_id", "location_id", "appointment_type_id", "patient_id",
        )}, "starts_at": NOW + timedelta(days=1),
        "ends_at": NOW + timedelta(days=1, minutes=30), **changes,
    })


def operation(selected, action="book"):
    intent = AppointmentIntent(
        action=action, selection=selected,
        expected=snapshot(selected) if action != "book" else None,
        slot={"starts_at": NOW + timedelta(days=2), "ends_at": NOW + timedelta(days=2, minutes=30)} if action != "cancel" else None,
        google={"provider": "google", "calendar_id": "primary", "connection_id": uuid4(),
                "connected_at": NOW - timedelta(days=1), "checked_at": NOW} if action != "cancel" else None,
        expires_at=NOW + timedelta(minutes=3),
    )
    return AppointmentOperation(operation_id=uuid4(), intent=intent, approved_payload_hash=intent.approval_hash())


def client(handler, **kwargs):
    return HttpSchedulingAppointments(
        kwargs.pop("origin", "https://scheduling.example.invalid"), kwargs.pop("staff_credential", lambda s: SecretStr("PRIVATE_fixture")),
        transport=httpx.MockTransport(handler), now=kwargs.pop("now", lambda: NOW), **kwargs,
    )


def envelope(request, selected, appointment):
    return {
        "contract_version": "1", "request_nonce": request.url.params["requestNonce"],
        "practice_id": str(selected.practice_id), "actor_id": str(selected.expected_actor_id),
        "checked_at": NOW.isoformat(), "appointment": appointment.model_dump(mode="json"),
    }


def receipt(request, op):
    intent = op.intent
    if intent.action == "book":
        result = snapshot(intent.selection, version=1, status="booked",
                          starts_at=intent.slot.starts_at, ends_at=intent.slot.ends_at)
    elif intent.action == "cancel":
        result = intent.expected.model_copy(update={"version": 8, "status": "cancelled"})
    else:
        result = intent.expected.model_copy(update={"version": 8, "starts_at": intent.slot.starts_at,
                                                    "ends_at": intent.slot.ends_at})
    return {**envelope(request, intent.selection, result), "operation_id": str(op.operation_id),
            "request_hash": op.request_hash(), "calendar_state": "pending"}


@pytest.mark.parametrize("base_path", ["", "/api"])
def test_read_requires_verified_revision_and_exact_patient_staff_scope(selected, base_path):
    observed = snapshot(selected)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == f"{base_path}/v1/appointments/{observed.id}/verified"
        assert not request.content and "idempotency-key" not in request.headers
        return httpx.Response(200, json=envelope(request, selected, observed), headers=HEADERS)

    port = client(handler, origin="https://scheduling.example.invalid" + base_path)
    try:
        result = port.read_appointment(selected, observed.id)
        assert result.appointment == observed and result.selection == selected
        assert result.observed_at == NOW and len(calls) == 1
        assert str(selected.patient_id) not in repr(result)
    finally:
        port.close()


@pytest.mark.parametrize("action", ["book", "reschedule", "cancel"])
@pytest.mark.parametrize("base_path", ["", "/api"])
def test_exact_operation_and_explicit_retry_keep_one_identity_and_payload(selected, action, base_path):
    op = operation(selected, action)
    calls, credentials = [], []

    def staff(scope):
        credentials.append(scope)
        return SecretStr("PRIVATE_" + str(len(credentials)))

    def handler(request):
        calls.append(request)
        assert request.url.path == base_path + "/v1/appointment-operations"
        assert request.method == "POST"
        assert json.loads(request.content) == op.request_payload()
        assert request.headers["idempotency-key"] == "os-appointment:" + str(op.operation_id)
        assert request.headers["authorization"] == "Bearer PRIVATE_" + str(len(credentials))
        assert request.headers["x-practice-id"] == str(selected.practice_id)
        assert request.headers["cache-control"] == "no-store" and request.headers["accept-encoding"] == "identity"
        assert not any(name in request.headers for name in ("cookie", "x-tenant-id", "x-actor-principal-id"))
        for local_id in (selected.box_id, selected.owner_id, selected.patient_link_id):
            assert str(local_id).encode() not in request.content
        return httpx.Response(200, json=receipt(request, op), headers={**HEADERS, "Set-Cookie": "private=PRIVATE; Path=/"})

    port = client(handler, staff_credential=staff, origin="https://scheduling.example.invalid" + base_path)
    try:
        first = port.submit(op)
        second = port.submit(op)
        assert first.operation_id == second.operation_id == op.operation_id
        assert first.calendar_state == second.calendar_state == "pending"
        assert len(calls) == 2 and credentials == [selected, selected]
        assert calls[0].content == calls[1].content
        assert calls[0].url.params["requestNonce"] != calls[1].url.params["requestNonce"]
    finally:
        port.close()


@pytest.mark.parametrize("base_path", ["", "/api"])
def test_lost_reply_is_unknown_and_reconciles_same_operation_after_expiry(selected, base_path):
    op = operation(selected)
    calls = []
    now = [NOW]

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            raise httpx.ReadTimeout("PRIVATE reply lost after commit", request=request)
        assert request.url.path == f"{base_path}/v1/appointment-operations/{op.operation_id}"
        assert not request.content
        result = receipt(request, op)
        result["checked_at"] = now[0].isoformat()
        return httpx.Response(200, json=result, headers=HEADERS)

    port = client(handler, now=lambda: now[0], origin="https://scheduling.example.invalid" + base_path)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_action_unconfirmed$"):
            port.submit(op)
        assert len(calls) == 1
        now[0] += timedelta(days=3)
        with pytest.raises(ConnectorUnavailable, match="^scheduling_approval_expired$"):
            port.submit(op)
        assert len(calls) == 1
        result = port.reconcile(op)
        assert result.operation_id == op.operation_id and len(calls) == 2
        assert [r.method for r in calls] == ["POST", "GET"]
    finally:
        port.close()


@pytest.mark.parametrize("status", [200, 201, 301, 302, 307, 401, 403, 404, 409, 410, 412, 429, 500, 503])
def test_legacy_response_failure_redirect_or_missing_result_never_retries_or_closes(selected, status):
    op = operation(selected)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=snapshot(selected).model_dump(mode="json"),
                              headers={**HEADERS, "Location": "https://other.invalid/PRIVATE"})

    port = client(handler)
    try:
        with pytest.raises(ConnectorUnavailable) as caught:
            port.reconcile(op)
        assert len(calls) == 1 and "PRIVATE" not in str(caught.value)
        assert calls[0].method == "GET" and "/appointment-operations/" in calls[0].url.path
    finally:
        port.close()


@pytest.mark.parametrize("fault", [
    "practice_id", "actor_id", "request_nonce", "operation_id", "request_hash", "contract_version",
    "patient_id", "practitioner_id", "location_id", "appointment_type_id", "version", "status",
    "ends_at", "starts_at", "extra", "stale", "future", "calendar", "client_id",
])
def test_changed_or_stale_effect_receipts_do_not_confirm_booking(selected, fault):
    op = operation(selected)

    def handler(request):
        result = receipt(request, op)
        if fault in {"practice_id", "actor_id", "request_nonce", "operation_id"}:
            result[fault] = str(uuid4())
        elif fault in {"patient_id", "practitioner_id", "location_id", "appointment_type_id", "client_id"}:
            result["appointment"][fault] = str(uuid4())
        elif fault == "request_hash":
            result[fault] = "0" * 64
        elif fault == "contract_version":
            result[fault] = "2"
        elif fault == "version":
            result["appointment"][fault] = 2
        elif fault == "status":
            result["appointment"][fault] = "confirmed"
        elif fault in {"starts_at", "ends_at"}:
            result["appointment"][fault] = (getattr(op.intent.slot, fault) + timedelta(minutes=5)).isoformat()
        elif fault == "extra":
            result["private_text"] = "PRIVATE"
        elif fault == "calendar":
            result["calendar_state"] = "complete"
        else:
            result["checked_at"] = (NOW + timedelta(seconds=-31 if fault == "stale" else 6)).isoformat()
        return httpx.Response(200, json=result, headers=HEADERS)

    port = client(handler)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_receipt_invalid$"):
            port.submit(op)
    finally:
        port.close()


@pytest.mark.parametrize("action", ["reschedule", "cancel"])
@pytest.mark.parametrize("fault", ["id", "version", "client_id", "status", "starts_at"])
def test_changed_existing_appointment_result_is_not_accepted(selected, action, fault):
    op = operation(selected, action)

    def handler(request):
        result = receipt(request, op)
        changes = {"id": str(uuid4()), "version": 7, "client_id": str(uuid4()),
                   "status": "fulfilled", "starts_at": (NOW + timedelta(hours=3)).isoformat()}
        result["appointment"][fault] = changes[fault]
        return httpx.Response(200, json=result, headers=HEADERS)

    port = client(handler)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_receipt_invalid$"):
            port.submit(op)
    finally:
        port.close()


@pytest.mark.parametrize("fault", ["owner_id", "box_id", "patient_link_id", "patient_id", "practice_id", "expected_actor_id", "slot", "expires_at", "expected"])
def test_proposal_edits_invalidate_original_approval_before_credentials(selected, fault):
    op = operation(selected, "reschedule")
    raw = op.model_dump(mode="json")
    if fault in raw["intent"]["selection"]:
        raw["intent"]["selection"][fault] = str(uuid4())
    elif fault == "slot":
        raw["intent"]["slot"]["starts_at"] = (NOW + timedelta(days=2, minutes=1)).isoformat()
    elif fault == "expires_at":
        raw["intent"][fault] = (NOW + timedelta(minutes=4)).isoformat()
    else:
        # Same time/status, newer receiver revision: changed-then-restored is stale.
        raw["intent"][fault]["version"] += 2
    with pytest.raises(ValidationError):
        AppointmentOperation.model_validate(raw)
    forged = op.model_copy(update={"intent": raw["intent"]})
    port = client(lambda r: pytest.fail("no request"), staff_credential=lambda s: pytest.fail("no credential"))
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_approval_changed$"):
            port.submit(forged)
    finally:
        port.close()


@pytest.mark.parametrize("fault", ["cancel_slot", "book_existing", "no_expected", "fulfilled", "foreign_patient", "no_google", "no_slot", "old_google", "bad_connection", "same_slot"])
def test_invalid_actions_cannot_become_approvable(selected, fault):
    raw = operation(selected, "reschedule").intent.model_dump(mode="json")
    if fault == "cancel_slot":
        raw["action"] = "cancel"
    elif fault == "book_existing":
        raw["action"] = "book"
    elif fault == "no_expected":
        raw["expected"] = None
    elif fault == "fulfilled":
        raw["expected"]["status"] = "fulfilled"
    elif fault == "foreign_patient":
        raw["expected"]["patient_id"] = str(uuid4())
    elif fault == "no_google":
        raw["google"] = None
    elif fault == "no_slot":
        raw["slot"] = None
    elif fault == "old_google":
        raw["google"]["checked_at"] = (NOW - timedelta(minutes=6)).isoformat()
    elif fault == "bad_connection":
        raw["google"]["connected_at"] = (NOW + timedelta(minutes=1)).isoformat()
    else:
        raw["slot"] = {name: raw["expected"][name] for name in ("starts_at", "ends_at")}
    with pytest.raises(ValidationError):
        AppointmentIntent.model_validate(raw)


@pytest.mark.parametrize("headers", [
    {"Content-Type": "application/json"}, {**HEADERS, "Content-Encoding": "gzip"},
    {**HEADERS, "Content-Type": "text/html"},
])
def test_unsafe_response_rejected_before_stream_consumption(selected, headers):
    events = []

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            events.append("read")
            yield b"PRIVATE"

        def close(self):
            events.append("closed")

    port = client(lambda r: httpx.Response(200, stream=Body(), headers=headers))
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_receipt_invalid$"):
            port.submit(operation(selected))
        assert events == ["closed"]
    finally:
        port.close()


@pytest.mark.parametrize("body", [b"PRIVATE", b"[" * 1500, b" " * (MAX_APPOINTMENT_BYTES + 1)])
def test_malformed_or_unbounded_receipt_has_safe_error(selected, body):
    port = client(lambda r: httpx.Response(200, content=body, headers=HEADERS))
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_receipt_invalid$") as caught:
            port.submit(operation(selected))
        assert "PRIVATE" not in str(caught.value)
    finally:
        port.close()


@pytest.mark.parametrize("credential", [None, "PRIVATE", SecretStr(""), SecretStr("PRIVATE\nvalue")])
def test_missing_or_invalid_staff_identity_makes_no_request(selected, credential):
    port = client(lambda r: pytest.fail("no request"), staff_credential=lambda s: credential)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_identity_unavailable$"):
            port.submit(operation(selected))
    finally:
        port.close()


def test_default_runtime_stays_disconnected(selected):
    port = build_scheduling_appointments()
    op = operation(selected)
    for call in (lambda: port.read_appointment(selected, uuid4()), lambda: port.submit(op), lambda: port.reconcile(op)):
        with pytest.raises(ConnectorUnavailable, match="^scheduling_connection_unavailable$"):
            call()


@pytest.mark.parametrize("value", [True, 0, -1, "7", 7.0, 9_223_372_036_854_775_808])
def test_receiver_revision_requires_a_database_integer(selected, value):
    with pytest.raises(ValidationError):
        snapshot(selected, version=value)


@pytest.mark.parametrize("field", ["starts_at", "ends_at", "checked_at"])
@pytest.mark.parametrize("value", [1789999200, "1789999200", "2026-09-21T14:00:00"])
def test_receipt_timestamps_cannot_coerce_an_epoch_or_omit_offset(selected, field, value):
    expected = snapshot(selected)

    def handler(request):
        result = envelope(request, selected, expected)
        if field == "checked_at":
            result[field] = value
        else:
            result["appointment"][field] = value
        return httpx.Response(200, json=result, headers=HEADERS)

    port = client(handler)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_receipt_invalid$"):
            port.read_appointment(selected, expected.id)
    finally:
        port.close()


@pytest.mark.parametrize("fault", ["id", "patient_id", "practice_id", "actor_id", "version"])
def test_read_cannot_substitute_the_appointment_or_scope(selected, fault):
    expected = snapshot(selected)

    def handler(request):
        result = envelope(request, selected, expected)
        target = result if fault in {"practice_id", "actor_id"} else result["appointment"]
        if fault == "version":
            del target[fault]
        else:
            target[fault] = str(uuid4())
        return httpx.Response(200, json=result, headers=HEADERS)

    port = client(handler)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_receipt_invalid$"):
            port.read_appointment(selected, expected.id)
    finally:
        port.close()


@pytest.mark.parametrize("now", [None, NOW.replace(tzinfo=None), "PRIVATE"])
def test_bad_clock_fails_before_identity_or_request(selected, now):
    port = client(lambda r: pytest.fail("no request"), staff_credential=lambda s: pytest.fail("no credentials"), now=lambda: now)
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_clock_unavailable$"):
            port.submit(operation(selected))
    finally:
        port.close()


@pytest.mark.parametrize("fault", ["missing_actor", "string_id", "wrong_selection"])
def test_invalid_scope_fails_before_identity_or_request(selected, fault):
    scope, aid = selected, uuid4()
    if fault == "missing_actor":
        scope = selected.model_copy(update={"expected_actor_id": None})
    elif fault == "string_id":
        aid = str(aid)
    else:
        scope = selected.model_dump()
    port = client(lambda r: pytest.fail("no request"), staff_credential=lambda s: pytest.fail("no credentials"))
    try:
        with pytest.raises(ConnectorUnavailable, match="^scheduling_scope_invalid$"):
            port.read_appointment(scope, aid)
    finally:
        port.close()
