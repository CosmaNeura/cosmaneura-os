"""Allocator-host activation holds stay dark until separate founder authorization."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("allocator_hold_flags", ROOT / "hold_flags.py")
assert spec and spec.loader
hold_flags = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hold_flags)


def test_default_receipt_keeps_every_activation_hold_false():
    receipt = hold_flags.validate_hold_flags(hold_flags.default_held_receipt())
    assert receipt["practice_uuid_limit"] == 1
    assert receipt["worker_enable_command_emitted"] is False
    assert receipt["azure_apply_performed"] is False
    assert receipt["allocation_qualified"] is False
    assert all(value is False for value in receipt["activation_holds"].values())
    assert all(value is False for value in receipt["review_flags"].values())


@pytest.mark.parametrize(
    "flag",
    [
        "hosting_configuration_enabled",
        "worker_started",
        "p2_extra_box_authorized",
        "stripe_live_mode",
        "production_registration_qualified",
    ],
)
def test_activation_holds_cannot_flip_true(flag):
    value = hold_flags.default_held_receipt(environment="staging")
    value[flag] = True
    with pytest.raises(ValueError, match=flag):
        hold_flags.validate_hold_flags(value)


def test_practice_limit_refuses_second_box_authorization():
    value = hold_flags.default_held_receipt()
    value["practice_uuid_limit"] = 2
    with pytest.raises(ValueError, match="exactly one practice UUID"):
        hold_flags.validate_hold_flags(value)


def test_review_flags_may_become_true_without_enabling_worker(tmp_path):
    value = hold_flags.default_held_receipt(environment="production")
    for name in hold_flags.REVIEW_FLAGS:
        value[name] = True
    path = tmp_path / "holds.json"
    path.write_text(json.dumps(value) + "\n")
    receipt = hold_flags.load_hold_flags(path)
    assert all(receipt["review_flags"].values())
    assert receipt["activation_holds"]["worker_started"] is False
    assert receipt["worker_enable_command_emitted"] is False


def test_load_refuses_relative_or_symlink_paths(tmp_path):
    value = hold_flags.default_held_receipt()
    path = tmp_path / "holds.json"
    path.write_text(json.dumps(value) + "\n")
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="regular absolute"):
        hold_flags.load_hold_flags(Path("holds.json"))
    with pytest.raises(ValueError, match="regular absolute"):
        hold_flags.load_hold_flags(link)
