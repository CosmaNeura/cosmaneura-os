"""Recovery evidence is scoped metadata, including when its lease has expired."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from tests.unit.test_core_capture_operations import NOW, exercise

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.capture_recovery import (
    CaptureRecoveryReceipt,
    CaptureRecoveryRequest,
    CaptureRecoveryState,
)


def test_contract_agrees_with_scribe_wire_fixture():
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/capture_recovery.json").read_text())
    for name, model in (
        ("request", CaptureRecoveryRequest),
        ("receipt", CaptureRecoveryReceipt),
        ("state", CaptureRecoveryState),
    ):
        assert model.model_validate(fixture[name]).model_dump(mode="json") == fixture[name]


@pytest.mark.parametrize("kind", ["recover_capture", "capture_recovery_state"])
@pytest.mark.parametrize("fault", ["session", "command", "future", "extra", "generation"])
def test_changed_recovery_evidence_is_not_released(kind, fault):
    def mutate(envelope):
        body = envelope["receipt"]
        receipt = body if kind == "recover_capture" else body["history"]["recoveries"][0]
        if fault == "session":
            receipt["session_id"] = str(uuid4())
        elif fault == "command":
            receipt["request"]["gap_id"] = str(uuid4())
        elif fault == "future":
            receipt["lease"]["issued_at"] = (NOW + timedelta(hours=1)).isoformat()
            receipt["lease"]["expires_at"] = (NOW + timedelta(hours=1, minutes=15)).isoformat()
        elif fault == "generation":
            receipt["lease"]["generation"] += 1
        else:
            body["capture_authorized"] = True

    with pytest.raises(ConnectorUnavailable):
        exercise(kind, mutate)
