"""Closed CosmasNativePracticeConnection schema for owned Infos packaging."""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "native_practice_connection_info", ROOT / "scripts/native_practice_connection_info.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def staging_practice():
    host = "invented-practice.clerk.accounts.dev"
    return {
        "enabled": True,
        "accountOrigin": "https://enrollment.example.invalid",
        "realm": {
            "publishableKey": "pk_test_" + base64.b64encode((host + "$").encode()).decode(),
            "frontendOrigin": "https://" + host,
            "audience": "",
            "profile": "operational-staging-v1",
            "keychainNamespace": "a" * 64,
        },
        "apiOrigins": [],
        "registeredPracticeOrigins": "synthetic-practice-uuid-staging-v1",
    }


def production_practice():
    host = "clerk.cosmas.ai"
    return {
        "enabled": True,
        "accountOrigin": "https://enrollment-api.cosmas.ai",
        "realm": {
            "publishableKey": "pk_live_" + base64.b64encode((host + "$").encode()).decode(),
            "frontendOrigin": "https://" + host,
            "audience": "cosmabot-practice-api",
            "profile": "operational-beta-v1",
            "keychainNamespace": "c" * 64,
        },
        "apiOrigins": [],
        "registeredPracticeOrigins": "practice-uuid-production-v1",
    }


def test_staging_and_production_practice_configs_are_accepted():
    assert MODULE.native_practice_configuration(staging_practice()) == staging_practice()
    assert MODULE.native_practice_configuration(production_practice()) == production_practice()


@pytest.mark.parametrize("change", [
    lambda value: value["realm"].update(profile="operational-beta-v1"),
    lambda value: value["realm"].update(audience="cosmas-os-beta"),
    lambda value: value.update(registeredPracticeOrigins="practice-uuid-production-v1"),
    lambda value: value.update(registeredPracticeOrigins="*"),
    lambda value: value.update(accountOrigin="https://enrollment.example.invalid/path"),
])
def test_staging_rejects_production_mix_and_unreviewed_inputs(change):
    value = staging_practice()
    change(value)
    with pytest.raises(ValueError):
        MODULE.native_practice_configuration(value)


@pytest.mark.parametrize("change", [
    lambda value: value.update(accountOrigin="https://enrollment.example.invalid"),
    lambda value: value.update(registeredPracticeOrigins="synthetic-practice-uuid-staging-v1"),
    lambda value: value["realm"].update(audience=""),
    lambda value: value["realm"].update(profile="operational-staging-v1"),
    lambda value: value["realm"].update(frontendOrigin="https://other.clerk.accounts.dev"),
])
def test_production_rejects_staging_mix_and_empty_audience(change):
    value = production_practice()
    change(value)
    with pytest.raises(ValueError):
        MODULE.native_practice_configuration(value)


def test_load_practice_config_reads_reviewed_json(tmp_path: Path):
    path = tmp_path / "native-practice.json"
    path.write_text(json.dumps(production_practice()))
    assert MODULE.load_practice_config(path) == production_practice()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(staging_practice() | {"extra": True}))
    with pytest.raises(ValueError):
        MODULE.load_practice_config(bad)
