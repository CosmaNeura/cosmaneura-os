"""Documentation source/review loops use the existing persistent virtual lab."""

import pytest
from lab.documentation_capability import SCENARIOS, exercise
from tests.integration.test_virtual_clinic_lab import clinic as clinic


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_documentation_retains_exact_sources_and_review_boundaries(clinic, scenario):
    app, store = clinic
    result = exercise(app, store, scenario, scenario)
    assert result["passed"], result
    assert result["material"] and result["persistent_artifacts"] and result["review_steps"]
    assert all(artifact["record_id"] and artifact["sha256"] for artifact in result["persistent_artifacts"])
    assert result["checks"]["all_reported_reviews_exist"]
    assert result["checks"]["note_source_review_state_survives_reopen"]
