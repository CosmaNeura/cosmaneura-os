import pytest
from pydantic import ValidationError

from cosmas_os.api.prep_work_schemas import PrepWorkDecision

U = "00000000-0000-4000-8000-000000000001"
H = "a" * 64


def valid(**changes):
    return {
        "expected_version": 1,
        "revision_id": U,
        "payload_hash": H,
        "choice": "approve",
        "bot": {"address": "scribe", "team_revision": 1},
        "expected_snapshot_sha256": "b" * 64,
        **changes,
    }


@pytest.mark.parametrize(
    "changes,expected",
    [
        (
            {},
            {
                "choice": "approve",
                "bot_address": "scribe",
                "bot_team_revision": 1,
                "expected_snapshot_sha256": "b" * 64,
            },
        ),
        (
            {"choice": "reject", "bot": None, "expected_snapshot_sha256": None},
            {
                "choice": "reject",
                "bot_address": None,
                "bot_team_revision": None,
                "expected_snapshot_sha256": None,
            },
        ),
        (
            {
                "bot": {
                    "address": "00000000-0000-4000-8000-0000000000aa",
                    "team_revision": 2,
                }
            },
            {
                "choice": "approve",
                "bot_address": "00000000-0000-4000-8000-0000000000aa",
                "bot_team_revision": 2,
                "expected_snapshot_sha256": "b" * 64,
            },
        ),
    ],
    ids=["approve_baseline", "reject_neither", "bot_uuid_address"],
)
def test_positive(changes, expected):
    model = PrepWorkDecision(**valid(**changes))
    assert model.choice == expected["choice"]
    if expected["bot_address"] is None:
        assert model.bot is None
    else:
        assert model.bot.address == expected["bot_address"]
        assert model.bot.team_revision == expected["bot_team_revision"]
    assert model.expected_snapshot_sha256 == expected["expected_snapshot_sha256"]


@pytest.mark.parametrize(
    "changes,loc,err_type",
    [
        ({"bot": None}, (), "value_error"),
        ({"expected_snapshot_sha256": None}, (), "value_error"),
        ({"choice": "reject"}, (), "value_error"),
        ({"choice": "reject", "bot": None}, (), "value_error"),
        ({"choice": "reject", "expected_snapshot_sha256": None}, (), "value_error"),
        ({"choice": "maybe"}, ("choice",), "literal_error"),
        ({"expected_version": 0}, ("expected_version",), "greater_than_equal"),
        ({"expected_version": "1"}, ("expected_version",), "int_type"),
        ({"payload_hash": "a" * 63}, ("payload_hash",), "string_pattern_mismatch"),
        ({"revision_id": "nope"}, ("revision_id",), "uuid_parsing"),
        ({"x": 1}, ("x",), "extra_forbidden"),
        (
            {"bot": {"address": "nobody", "team_revision": 1}},
            ("bot", "address"),
            "string_pattern_mismatch",
        ),
        (
            {"bot": {"address": "scribe", "team_revision": 0}},
            ("bot", "team_revision"),
            "greater_than_equal",
        ),
    ],
    ids=[
        "approve_bot_none",
        "approve_snapshot_none",
        "reject_both_still_set",
        "reject_bot_none_snapshot_set",
        "reject_snapshot_none_bot_set",
        "choice_maybe",
        "expected_version_zero",
        "expected_version_str",
        "payload_hash_short",
        "revision_id_invalid",
        "extra_forbidden",
        "bot_address_unknown",
        "bot_team_revision_zero",
    ],
)
def test_negative(changes, loc, err_type):
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(**changes))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == loc
    assert errors[0]["type"] == err_type
