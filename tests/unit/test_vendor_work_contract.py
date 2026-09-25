"""Public/private boundary and canonical browser-compatible command commitments."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from cosmas_os.api import vendor_work_schemas as v

FIXTURES = Path(__file__).parents[1] / "fixtures" / "vendor_work"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.mark.parametrize("vector", fixture("c1_public_hash_vectors"))
def test_actual_pydantic_normalization_and_domain_hash_match_reviewed_vectors(vector):
    model = v.read_json(json.dumps(vector["input"], ensure_ascii=False).encode(), v.VendorProposal)
    assert model.public() == vector["normalized"]
    scope = {"kind": "workspace", "id": vector["input"]["proposed_operation_id"]}
    assert v.request_digest("propose", scope, model) == vector["request_sha256"]
    assert (
        v.canonical(
            {
                "domain": "cosmas-vendor-public-request.v1",
                "value": {"command_kind": "propose", "scope": scope, "request": model.public()},
            }
        ).hex()
        == vector["canonical_utf8_hex"]
    )


@pytest.mark.parametrize(
    "name,model,bound",
    [
        ("proposal", v.VendorProposal, 32768),
        ("result", v.VendorResult, 16384),
        ("verify", v.VendorVerify, 2048),
        ("intent", v.VendorArtifactIntent, 2048),
        ("connection", v.ConnectionView, 2048),
        ("correspondence", v.CorrespondenceView, 2048),
        ("summary", v.Summary, 1536),
        ("detail", v.Detail, 65536),
        ("options", v.Options, 65536),
        ("catalog", v.Catalog, 65536),
        ("receipt", v.CommandResponse, 16384),
    ],
)
def test_actual_astral_maximum_shapes_fit_and_roundtrip(name, model, bound):
    value = fixture(name)
    assert model.model_validate(value).public() == value
    assert len(v.canonical(value)) <= bound


@pytest.mark.parametrize(
    "message",
    [
        "\u00a0\u2003",
        "a\x00b",
        "a\x7fb",
        "\ud800",
        "x" * 4001,
        *["a" + chr(n) + "b" for n in range(32) if n not in (9, 10, 13)],
    ],
)
def test_forbidden_text_is_rejected(message):
    value = fixture("proposal")
    value["message"] = message
    with pytest.raises((ValueError, UnicodeError)):
        v.VendorProposal.model_validate(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_workspace_revision", True),
        ("expected_workspace_revision", 1.0),
        ("expected_workspace_revision", "1"),
        ("expected_workspace_revision", 2147483648),
        ("share_to_practice", 1),
        ("share_to_practice", "true"),
        ("message", None),
        ("document", None),
        ("proposed_operation_id", "11111111-1111-4111-8111-11111111111A"),
        ("due_date", "2026-02-30"),
        ("due_date", "20260921"),
        ("credential_ref", "synthetic-private"),
    ],
)
def test_closed_strict_commands(field, value):
    payload = fixture("proposal")
    payload[field] = value
    with pytest.raises(ValueError):
        v.VendorProposal.model_validate(payload)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1.0}',
        b'{"x":9007199254740992}',
        b"[]",
        b'{"x":"\xff"}',
        b'{"x":{"a":1,"a":2}}',
    ],
)
def test_ambiguous_raw_json_rejected_before_model(raw):
    with pytest.raises((ValueError, UnicodeError)):
        v.read_json(raw, v.VendorProposal)


@pytest.mark.parametrize(
    "action,fields",
    [
        ("spruce_secure_message", {"correspondence", "message"}),
        ("spruce_fax", {"correspondence", "uploaded_media_operation_id"}),
        ("spruce_media_upload", {"document"}),
        ("srfax_fax", {"document", "correspondence"}),
        ("documo_fax", {"document", "correspondence"}),
    ],
)
def test_action_union_never_promotes_unknown_fields(action, fields):
    source = fixture("proposal")
    candidates = {
        k: source.get(k, fixture("intent"))
        for k in ("message", "correspondence", "uploaded_media_operation_id", "document")
    }
    candidates["document"] = fixture("detail")["review"]["uploaded_media"]["document"]
    for key in candidates:
        source.pop(key, None)
    source.update({key: candidates[key] for key in fields})
    source["action"] = action
    v.VendorProposal.model_validate(source)
    for key in fields:
        bad = deepcopy(source)
        bad.pop(key)
        with pytest.raises(ValueError):
            v.VendorProposal.model_validate(bad)
    for key in (
        set(candidates)
        - fields
        - ({"uploaded_media_operation_id"} if action == "spruce_secure_message" else set())
    ):
        with pytest.raises(ValueError):
            v.VendorProposal.model_validate({**source, key: candidates[key]})


def test_omission_and_explicit_null_response_are_distinct():
    value = fixture("detail")
    value["latest_result"] = None
    assert v.Detail.model_validate(value).public()["latest_result"] is None
    value["review"]["document"] = None
    with pytest.raises(ValueError):
        v.Detail.model_validate(value)


@pytest.mark.parametrize("version", [True, "1", 1.0, 2])
def test_response_version_strict(version):
    with pytest.raises(ValueError):
        v.Detail.model_validate({**fixture("detail"), "contract_version": version})


def test_recorded_receipt_cannot_be_missing_effect_or_accept_mutable_work_state():
    value = fixture("receipt")
    with pytest.raises(ValueError):
        v.CommandResponse.model_validate({**value, "effect": None})
    with pytest.raises(ValueError):
        v.CommandResponse.model_validate({**value, "summary": fixture("summary")})
    v.CommandResponse.model_validate(
        {**value, "outcome": "not_found", "effect": None, "summary": None}
    )


def test_byte_bound_is_not_scalar_count_and_scope_is_bound():
    proposal = v.VendorProposal.model_validate(fixture("proposal"))
    with pytest.raises(ValueError):
        v.read_json(v.canonical(proposal.public()), v.VendorProposal, 8192)
    a = v.request_digest(
        "propose", {"kind": "workspace", "id": proposal.proposed_operation_id}, proposal
    )
    b = v.request_digest(
        "propose", {"kind": "practice_work", "id": proposal.proposed_operation_id}, proposal
    )
    assert a != b
