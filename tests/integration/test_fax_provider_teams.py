"""Qualification uses the existing lab, real SQL guards and saved evidence."""

import json

import pytest
from lab.fax_teams import run_provider
from tests.integration.test_virtual_clinic_lab import clinic as clinic


@pytest.mark.parametrize("provider", ["spruce", "srfax", "documo"])
def test_provider_matrix_and_shared_lessons(clinic, provider):
    app, store = clinic
    result = run_provider(app, store, provider, provider)
    assert result["passed"], result
    assert result["connector_scenarios"]
    assert result["shared_lessons"]
    assert all(row["checks"] for row in result["connector_scenarios"])
    assert result["application"]["external_effects"] == 0
    assert "invented-lab-secret" not in json.dumps(result)
    assert "invented-spruce-lab-secret" not in json.dumps(result)
    assert "invented-lab-webhook-secret" not in json.dumps(result)
    if provider == "spruce":
        assert all(row["ticket"]["transport"] != "delivered" for row in result["connector_scenarios"])
    else:
        assert all(sum(call["action"] == "submit" for call in row["requests"]) == 1
                   for row in result["connector_scenarios"])
