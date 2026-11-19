import pytest
from pydantic import ValidationError

from cosmas_os.api.conversation_inbox_routes import MarkerCommand

# Exercises the full allowed alphabet under ^r1[0-9a-f]{16}[a-z][0-9a-f]{96}$
WATERMARK = "r1" + "0123456789abcdef" + "z" + "0123456789abcdef" * 6
assert len(WATERMARK) == 115

BASELINE = dict(watermark=WATERMARK, manual_unread=False, expected_version=3)


def test_positive_cases():
    # MarkerCommand() -> all three fields None
    cmd = MarkerCommand()
    dump = cmd.model_dump()
    assert dump["watermark"] is None
    assert dump["manual_unread"] is None
    assert dump["expected_version"] is None

    # only watermark=WATERMARK -> manual_unread None, expected_version None
    cmd = MarkerCommand(watermark=WATERMARK)
    dump = cmd.model_dump()
    assert dump["watermark"] == WATERMARK
    assert dump["manual_unread"] is None
    assert dump["expected_version"] is None

    # mark-read baseline: watermark + manual_unread=False + expected_version=3
    cmd = MarkerCommand(watermark=WATERMARK, manual_unread=False, expected_version=3)
    dump = cmd.model_dump()
    assert dump["watermark"] == WATERMARK
    assert dump["manual_unread"] is False
    assert dump["expected_version"] == 3

    # manual_unread=True, expected_version=0 (no watermark) is accepted
    cmd = MarkerCommand(manual_unread=True, expected_version=0)
    dump = cmd.model_dump()
    assert dump["watermark"] is None
    assert dump["manual_unread"] is True
    assert dump["expected_version"] == 0

    # manual_unread=True, expected_version=1, watermark=WATERMARK is accepted
    cmd = MarkerCommand(manual_unread=True, expected_version=1, watermark=WATERMARK)
    dump = cmd.model_dump()
    assert dump["watermark"] == WATERMARK
    assert dump["manual_unread"] is True
    assert dump["expected_version"] == 1

    # explicit watermark=None, manual_unread=None, expected_version=None is accepted
    cmd = MarkerCommand(watermark=None, manual_unread=None, expected_version=None)
    dump = cmd.model_dump()
    assert dump["watermark"] is None
    assert dump["manual_unread"] is None
    assert dump["expected_version"] is None


def test_negative_validator_logic():
    # baseline without watermark -> loc (), type "value_error"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(**{**BASELINE, "watermark": None})
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert errors[0]["type"] == "value_error"

    # only manual_unread=True -> loc (), "value_error"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(manual_unread=True)
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert errors[0]["type"] == "value_error"

    # only expected_version=1 -> loc (), "value_error"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(expected_version=1)
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert errors[0]["type"] == "value_error"

    # watermark=WATERMARK, expected_version=1 (no manual_unread) -> loc (), "value_error"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(watermark=WATERMARK, expected_version=1)
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert errors[0]["type"] == "value_error"


def test_negative_watermark_constraints():
    # baseline with watermark=WATERMARK[:-1] -> ("watermark",) "string_too_short"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(**{**BASELINE, "watermark": WATERMARK[:-1]})
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("watermark",)
    assert errors[0]["type"] == "string_too_short"

    # baseline with watermark=WATERMARK + "0" -> ("watermark",) "string_too_long"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(**{**BASELINE, "watermark": WATERMARK + "0"})
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("watermark",)
    assert errors[0]["type"] == "string_too_long"


@pytest.mark.parametrize(
    "bad_watermark",
    [
        "r2" + WATERMARK[2:],
        WATERMARK.upper(),
        "r1" + "0123456789abcdef" + "A" + "0123456789abcdef" * 6,
        "r1" + "0123456789abcdeg" + "z" + "0123456789abcdef" * 6,
        "r1" + "0123456789abcdef" + "z" + "g" + "0123456789abcdef" * 5 + "0123456789abcde",
        "r1" + "0123456789abcdeF" + "z" + "0123456789abcdef" * 6,
        "r1" + "0123456789abcdef" + "0" + "0123456789abcdef" * 6,
    ],
    ids=[
        "prefix_r2",
        "all_upper",
        "slot_upper_a",
        "hex16_g",
        "hex96_g",
        "hex16_upper_f",
        "slot_digit",
    ],
)
def test_negative_watermark_pattern(bad_watermark):
    # baseline with watermark pattern mismatch -> ("watermark",) "string_pattern_mismatch"
    assert len(bad_watermark) == 115
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(**{**BASELINE, "watermark": bad_watermark})
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("watermark",)
    assert errors[0]["type"] == "string_pattern_mismatch"


def test_negative_types():
    # baseline with manual_unread="true" -> ("manual_unread",) "bool_type"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(**{**BASELINE, "manual_unread": "true"})
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("manual_unread",)
    assert errors[0]["type"] == "bool_type"

    # baseline with manual_unread=1 -> ("manual_unread",) "bool_type"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(**{**BASELINE, "manual_unread": 1})
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("manual_unread",)
    assert errors[0]["type"] == "bool_type"

    # baseline with expected_version="1" -> ("expected_version",) "int_type"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(**{**BASELINE, "expected_version": "1"})
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("expected_version",)
    assert errors[0]["type"] == "int_type"

    # baseline with expected_version=True -> ("expected_version",) "int_type"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(**{**BASELINE, "expected_version": True})
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("expected_version",)
    assert errors[0]["type"] == "int_type"

    # baseline with expected_version=-1 -> ("expected_version",) "greater_than_equal"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(**{**BASELINE, "expected_version": -1})
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("expected_version",)
    assert errors[0]["type"] == "greater_than_equal"


def test_negative_extra_key():
    # baseline plus extra key x=1 -> ("x",) "extra_forbidden"
    with pytest.raises(ValidationError) as excinfo:
        MarkerCommand(**BASELINE, x=1)
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("x",)
    assert errors[0]["type"] == "extra_forbidden"
