from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from cosmas_os.config import Settings
from cosmas_os.ports.core_capture import CoreCaptureBindingSnapshot
from cosmas_os.ports.core_record_location import record_location, valid_core_web_origin


def binding():
    return CoreCaptureBindingSnapshot(
        contract_version="1",
        binding_ref="scribe_capture_binding_" + "0" * 25 + "1",
        workspace_id=uuid4(),
        appointment_ref="appointment_" + "0" * 25 + "1",
        actor_ref="authority_actor_" + "0" * 25 + "1",
        tenant_ref="authority_tenant_" + "0" * 25 + "1",
        request_nonce=uuid4(),
        checked_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "http://core.example.invalid",
        "https://core.example.invalid/",
        "https://CORE.example.invalid",
        "https://user@core.example.invalid",
        "https://core.example.invalid:443",
        "https://core.example.invalid?next=outside",
        "https://core.example.invalid#record",
        "https://core.example.invalid/%2e%2e",
        "https://core.example.invalid\\outside",
        "https://core..invalid",
        "https://-core.invalid",
        "https://core.invalid\n",
        "https://cöre.invalid",
        "https://localhost",
        "https://127.0.0.1",
        "https://core.example.invalid:8443",
        "https://core.123",
        "https://core.0xabc",
        "https://0x7f000001",
        "https://127.1",
    ],
)
def test_only_exact_configured_origin_can_create_a_navigation_destination(origin):
    assert not valid_core_web_origin(origin)
    b = binding()
    with pytest.raises(ValueError):
        record_location(origin, b.workspace_id, b)


def test_destination_contains_only_the_existing_appointment_and_no_authority_or_clinical_state():
    b = binding()
    value = record_location("https://core.example.invalid", b.workspace_id, b).model_dump(
        mode="json"
    )
    assert value == {
        "contract_version": 1,
        "workspace_id": str(b.workspace_id),
        "appointment_ref": b.appointment_ref,
        "href": "https://core.example.invalid/notes/" + b.appointment_ref,
        "checked_at": b.checked_at.isoformat().replace("+00:00", "Z"),
    }


@pytest.mark.parametrize("age", [-6, 31])
def test_expired_or_future_observation_cannot_be_offered_as_a_fresh_lookup(age):
    b = binding().model_copy(update={"checked_at": datetime.now(UTC) - timedelta(seconds=age)})
    with pytest.raises(ValueError):
        record_location("https://core.example.invalid", b.workspace_id, b)


def test_wrong_workspace_rejected_and_configuration_starts_disabled():
    b = binding()
    with pytest.raises(ValueError):
        record_location("https://core.example.invalid", uuid4(), b)
    configuration = Settings(_env_file=None)  # pyright: ignore[reportCallIssue] -- BaseSettings runtime-only option.
    assert not configuration.workspace_core_record_available
