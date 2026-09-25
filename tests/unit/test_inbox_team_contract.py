from copy import deepcopy

import pytest

from cosmas_os.application import provider_team as team
from cosmas_os.application import team_setup


def test_front_desk_upgrade_requires_current_contract_and_cannot_downgrade():
    from uuid import uuid4

    from cosmas_os.application.workspace import WorkspaceError

    value = team.default_configuration()
    slots = {slot: str(uuid4()) for slot in ("inbox", "scheduling", "intake")}
    for slot, address in slots.items():
        value["bots"].append(
            {
                "role": "custom",
                "instance_id": address,
                "name": slot,
                "job_focus": "Invented work",
                "enabled": False,
                "include_notebook": False,
                "include_evidence": False,
            }
        )
    value["presets"] = [
        {
            "preset_id": "provider",
            "version": 1,
            "slots": {role: role for role in ("scribe", "visit_prep", "follow_up", "chief")},
        },
        {"preset_id": "front_desk", "version": 1, "slots": slots},
    ]
    before = team.configuration_value(value)
    after = deepcopy(before)
    after["presets"][1]["version"] = 2
    after["bots"][4]["skills"] = ["inbox_review"]
    after["bots"][4]["enabled"] = True
    after = team.configuration_value(after)
    assert team_setup.review_required(before, after)
    team_setup.validate_transition(before, after)
    team_setup.require_compatible(3, before, after)
    with pytest.raises(WorkspaceError, match="team_contract_required"):
        team_setup.require_compatible(2, after)
    with pytest.raises(WorkspaceError, match="team_catalog_changed"):
        team_setup.validate_transition(after, before)
    assert team_setup.catalog(2)["presets"][1]["slots"][0]["skills"] == []
    assert team_setup.catalog(3)["presets"][1]["slots"][0]["skills"] == ["inbox_review"]
