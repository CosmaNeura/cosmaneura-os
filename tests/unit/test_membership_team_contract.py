from copy import deepcopy
from uuid import uuid4

import pytest

from cosmas_os.application import provider_team as team
from cosmas_os.application import team_setup
from cosmas_os.application.workspace import WorkspaceError


def test_practice_manager_upgrade_is_reviewed_and_requires_contract_four():
    before = team.default_configuration()
    slots = {"operations": str(uuid4()), "membership_billing": str(uuid4()), "chief": "chief"}
    for slot in ("operations", "membership_billing"):
        before["bots"].append(
            {
                "role": "custom",
                "instance_id": slots[slot],
                "name": slot,
                "enabled": False,
                "job_focus": "Private review",
                "working_preferences": "Preserved preference",
                "blocked_capabilities": ["model_answer"],
            }
        )
    before["presets"] = [
        {
            "preset_id": "provider",
            "version": 1,
            "slots": {r: r for r in ("scribe", "visit_prep", "follow_up", "chief")},
        },
        {"preset_id": "practice_manager", "version": 1, "slots": slots},
    ]
    before = team.configuration_value(before)
    after = deepcopy(before)
    after["presets"][1]["version"] = 2
    after["bots"][-1]["skills"] = ["membership_review"]
    after["bots"][-1]["enabled"] = True
    after = team.configuration_value(after)
    assert team_setup.review_required(before, after)
    team_setup.validate_transition(before, after)
    team_setup.require_compatible(4, before, after)
    with pytest.raises(WorkspaceError, match="team_contract_required"):
        team_setup.require_compatible(3, after)
    with pytest.raises(WorkspaceError, match="team_catalog_changed"):
        team_setup.validate_transition(after, before)
    assert team_setup.catalog(3)["presets"][2]["slots"][1]["skills"] == []
    assert team_setup.catalog(4)["presets"][2]["slots"][1]["skills"] == ["membership_review"]
    assert after["bots"][-1]["instance_id"] == before["bots"][-1]["instance_id"]
    assert after["bots"][-1]["blocked_capabilities"] == ["model_answer"]
