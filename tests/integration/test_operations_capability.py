"""Operational status capabilities exercise the existing persistent agent lab."""

import json

import pytest
from lab.operations_capability import SCENARIOS, exercise
from tests.integration.test_virtual_clinic_lab import clinic as clinic


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_operational_role_transition_keeps_next_steps_honest(clinic, scenario):
    app, store = clinic
    result = exercise(app, store, scenario, scenario)
    assert result["passed"], result
    assert result["stages"] and result["checks"]
    assert all(row["evidence"]["commitment"] for row in result["stages"])
    content = json.dumps(result)
    for private in ("sk_test_synthetic_only", "acct_Synthetic", "cus_Synthetic", "SYNTHETIC appointment question"):
        assert private not in content
