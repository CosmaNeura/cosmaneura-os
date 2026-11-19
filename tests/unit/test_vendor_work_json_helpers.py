"""Pin vendor-work JSON helper behavior (json_value, canonical, digests, labels)."""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from cosmas_os.api import vendor_work_schemas as v


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


def _nested_list(depth: int):
    x = 1
    for _ in range(depth):
        x = [x]
    return x


def test_json_value_accepts_valid_shapes():
    nested = {"a": [1, None, True, "x", {"b": "é"}]}
    assert v.json_value(nested) is nested
    falsey = {"a": False}
    assert v.json_value(falsey) is falsey
    assert v.json_value(2147483647) == 2147483647
    deep = _nested_list(30)
    assert v.json_value(deep) is deep


@pytest.mark.parametrize(
    "bad,message",
    [
        (1.5, "invalid JSON scalar"),
        ((1,), "invalid JSON scalar"),
        (b"x", "invalid JSON scalar"),
        ({1}, "invalid JSON scalar"),
        (type("S", (str,), {})("x"), "invalid JSON scalar"),
        (2147483648, "integer bound exceeded"),
        # -2147483648 is currently rejected (symmetric abs bound), not a bug.
        (-2147483648, "integer bound exceeded"),
        (-2147483649, "integer bound exceeded"),
        ({"é": 1}, "invalid JSON key"),
        ({1: 1}, "invalid JSON key"),
        (_nested_list(31), "JSON depth exceeded"),
    ],
)
def test_json_value_rejects_invalid_values(bad, message):
    with pytest.raises(ValueError, match=f"^{message}$"):
        v.json_value(bad)


def test_json_value_rejects_lone_surrogate():
    with pytest.raises(ValueError):
        v.json_value("\ud800")


def test_canonical_sorts_keys_and_encodes_utf8():
    assert v.canonical({"b": 1, "a": [True, None, "é"]}) == b'{"a":[true,null,"\xc3\xa9"],"b":1}'
    assert v.canonical({"a": 1, "b": 2}) == v.canonical({"b": 2, "a": 1})


def test_public_digest_is_stable_and_domain_bound():
    first = v.public_digest("d1", {"a": 1})
    assert first == "708bd6e12adc95c6444fe579c662714b06f60237c24feaa38980caee8c3390f0"
    assert v.public_digest("d1", {"a": 1}) == first
    assert v.public_digest("d2", {"a": 1}) != first


def test_timestamp_normalizes_aware_datetimes_to_utc_z():
    assert v.timestamp(datetime(2026, 11, 19, 15, 0, tzinfo=UTC)) == "2026-11-19T15:00:00.000000Z"
    assert (
        v.timestamp(datetime(2026, 11, 19, 10, 0, tzinfo=timezone(timedelta(hours=-5))))
        == "2026-11-19T15:00:00.000000Z"
    )


@pytest.mark.parametrize("bad", [datetime(2026, 11, 19, 15, 0), "2026-11-19"])
def test_timestamp_requires_aware_utc_datetime(bad):
    with pytest.raises(ValueError, match="^UTC timestamp required$"):
        v.timestamp(bad)


def test_bounded_enforces_canonical_byte_limit():
    assert len(v.canonical({"a": 1})) == 7
    assert v.bounded({"a": 1}, 7) == {"a": 1}
    assert v.bounded({"a": 1}, 8) == {"a": 1}
    with pytest.raises(ValueError, match="^response bound exceeded$"):
        v.bounded({"a": 1}, 6)


def test_safe_label_normalizes_and_truncates():
    assert v.safe_label("Synthetic Clinic") == "Synthetic Clinic"
    assert v.safe_label("a\r\nb") == "a\nb"
    assert v.safe_label("a\tb") == "a\tb"
    assert v.safe_label("x" * 100) == "x" * 80
    assert v.safe_label("abcdefghij", 5) == "abcde"


@pytest.mark.parametrize("bad", ["", "  \t", "a\x01b", "a\x7fb", "\xa0"])
def test_safe_label_rejects_invalid_text(bad):
    with pytest.raises(ValueError, match="^invalid text$"):
        v.safe_label(bad)


@pytest.mark.parametrize("bad", [5, b"x"])
def test_safe_label_requires_str(bad):
    with pytest.raises(ValueError, match="^label required$"):
        v.safe_label(bad)


def test_read_json_parses_valid_object_into_model():
    assert v.read_json(b'{"name":"x"}', Body) == Body(name="x")


@pytest.mark.parametrize(
    "raw,message",
    [
        (b'{"name":"x","name":"y"}', "duplicate key"),
        (b"[1]", "object required"),
        (b'"x"', "object required"),
        (b'{"name":"x","n":1.5}', "invalid JSON scalar"),
        (b'{"name":"x","n":2147483648}', "integer bound exceeded"),
        ('{"name":"x"}', "invalid request size"),
        ('{"é":1}'.encode(), "invalid JSON key"),
    ],
)
def test_read_json_rejects_invalid_payloads(raw, message):
    with pytest.raises(ValueError, match=f"^{message}$"):
        v.read_json(raw, Body)


def test_read_json_rejects_oversized_body():
    raw = b'{"name":"' + b"a" * 32758 + b'"}'
    assert len(raw) == 32769
    with pytest.raises(ValueError, match="^invalid request size$"):
        v.read_json(raw, Body)


def test_read_json_rejects_when_maximum_is_below_raw_size():
    with pytest.raises(ValueError, match="^invalid request size$"):
        v.read_json(b'{"name":"x"}', Body, maximum=5)


def test_read_json_rejects_truncated_json():
    with pytest.raises(ValueError) as excinfo:
        v.read_json(b"{", Body)
    assert isinstance(excinfo.value, json.JSONDecodeError)


def test_read_json_forbids_extra_fields():
    with pytest.raises(ValidationError) as excinfo:
        v.read_json(b'{"name":"x","o":1}', Body)
    errors = excinfo.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("o",)
    assert errors[0]["type"] == "extra_forbidden"
