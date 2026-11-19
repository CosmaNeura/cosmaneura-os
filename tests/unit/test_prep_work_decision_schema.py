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


def test_positive():
    # Standard approve
    d = valid()
    m = PrepWorkDecision(**d)
    assert m.choice == "approve"
    assert m.bot.address == "scribe"
    assert m.bot.team_revision == 1
    assert m.expected_snapshot_sha256 == "b" * 64

    # Reject with None values
    d = valid(choice="reject", bot=None, expected_snapshot_sha256=None)
    m = PrepWorkDecision(**d)
    assert m.choice == "reject"
    assert m.bot is None
    assert m.expected_snapshot_sha256 is None

    # Custom bot identity
    d = valid(bot={"address": "00000000-0000-4000-8000-0000000000aa", "team_revision": 2})
    m = PrepWorkDecision(**d)
    assert m.bot.address == "00000000-0000-4000-8000-0000000000aa"
    assert m.bot.team_revision == 2


def test_negatives():
    # bot=None (approve)
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(bot=None))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert errors[0]["type"] == "value_error"

    # expected_snapshot_sha256=None (approve)
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(expected_snapshot_sha256=None))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert errors[0]["type"] == "value_error"

    # choice="reject" alone (bot and snapshot still set)
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(choice="reject"))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert errors[0]["type"] == "value_error"

    # choice="reject", bot=None (snapshot still set)
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(choice="reject", bot=None))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert errors[0]["type"] == "value_error"

    # choice="reject", expected_snapshot_sha256=None (bot still set)
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(choice="reject", expected_snapshot_sha256=None))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert errors[0]["type"] == "value_error"

    # choice="maybe"
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(choice="maybe"))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("choice",)
    assert errors[0]["type"] == "literal_error"

    # expected_version=0
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(expected_version=0))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("expected_version",)
    assert errors[0]["type"] == "greater_than_equal"

    # expected_version="1"
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(expected_version="1"))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("expected_version",)
    assert errors[0]["type"] == "int_type"

    # payload_hash="a" * 63
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(payload_hash="a" * 63))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("payload_hash",)
    assert errors[0]["type"] == "string_pattern_mismatch"

    # revision_id="nope"
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(revision_id="nope"))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("revision_id",)
    assert errors[0]["type"] == "uuid_parsing"

    # extra key x=1
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(x=1))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("x",)
    assert errors[0]["type"] == "extra_forbidden"

    # bot={"address": "nobody", "team_revision": 1}
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(bot={"address": "nobody", "team_revision": 1}))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("bot", "address")
    assert errors[0]["type"] == "string_pattern_mismatch"

    # bot={"address": "scribe", "team_revision": 0}
    with pytest.raises(ValidationError) as exc:
        PrepWorkDecision(**valid(bot={"address": "scribe", "team_revision": 0}))
    errors = exc.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("bot", "team_revision")
    assert errors[0]["type"] == "greater_than_equal"
