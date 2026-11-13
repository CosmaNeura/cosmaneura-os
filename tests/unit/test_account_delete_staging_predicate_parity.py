"""Parity: shared classify_review_profile and render classifyAccountDeleteProfile."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from cosmas_os.production_review_profile import (
    REVIEW_CLERK_ISSUER,
    REVIEW_SESSION_POLICY,
    REVIEW_WEB_ORIGIN,
    STAGING_SESSION_POLICY,
    STAGING_WEB_ORIGIN,
    classify_review_profile,
)

REPO = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO / "infra/standalone/package/entrypoint.py"
RENDER = REPO / "infra/standalone/render.mjs"
MATRIX = REPO / "infra/standalone/account-delete-profile-matrix.json"
SHARED = REPO / "src/cosmas_os/production_review_profile.py"


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location(
        "standalone_package_entrypoint_parity", ENTRYPOINT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _matrix_rows() -> list[dict]:
    rows = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert isinstance(rows, list) and rows
    return rows


def test_account_delete_shared_matrix_file_exists_and_covers_refused_rows():
    rows = _matrix_rows()
    ids = {row["id"] for row in rows}
    assert "refused_shared_staging_with_beta_cors" in ids
    assert "refused_audience_mixed_cors" in ids
    assert "review_audience_beta_clerk_beta" in ids
    assert "refused_review_wrong_issuer" in ids
    assert "refused_audience_beta_second_in_cors" in ids
    assert "refused_audience_uppercase_beta" in ids
    assert "refused_audience_beta_trailing_slash" in ids
    assert "refused_audience_beta_port_443" in ids
    assert "refused_audience_missing_issuer" in ids
    assert "refused_audience_empty_issuer" in ids
    assert "refused_missing_policy_with_beta" in ids


@pytest.mark.parametrize("row", _matrix_rows(), ids=lambda row: row["id"])
def test_shared_classify_review_profile_matches_matrix(row):
    """Python side of the shared matrix drives cosmas_os.production_review_profile."""
    kind = classify_review_profile(
        policy=row["policy"],
        web_origin=row["web_origin"],
        cors=row["cors"],
        issuer=row["issuer"],
    )
    expected = None if row["expect"] == "none" else row["expect"]
    assert kind == expected
    cors_only = classify_review_profile(
        policy=row["policy"],
        web_origin=None,
        cors=row["cors"],
        issuer=row["issuer"],
    )
    cors_parts = [p.strip() for p in row["cors"].split(",") if p.strip()]
    if row["web_origin"] and cors_parts and cors_parts[0] == row["web_origin"]:
        assert cors_only == expected


@pytest.mark.parametrize("row", _matrix_rows(), ids=lambda row: row["id"])
def test_entrypoint_thin_alias_matches_shared_classify(row):
    entrypoint = _load_entrypoint()
    entrypoint._bind_shared_predicate()
    assert entrypoint.classify_account_delete_profile is entrypoint.classify_review_profile
    expected = classify_review_profile(
        policy=row["policy"],
        web_origin=row["web_origin"],
        cors=row["cors"],
        issuer=row["issuer"],
    )
    assert (
        entrypoint.classify_account_delete_profile(
            policy=row["policy"],
            web_origin=row["web_origin"],
            cors=row["cors"],
            issuer=row["issuer"],
        )
        == expected
    )


def test_entrypoint_reexports_shared_constants_behaviour():
    entrypoint = _load_entrypoint()
    entrypoint._bind_shared_predicate()
    assert entrypoint.STAGING_WEB_ORIGIN == STAGING_WEB_ORIGIN == "https://staging.cosmas.ai"
    assert entrypoint.REVIEW_WEB_ORIGIN == REVIEW_WEB_ORIGIN == "https://beta.cosmas.ai"
    assert entrypoint.REVIEW_CLERK_ISSUER == REVIEW_CLERK_ISSUER == "https://clerk.beta.cosmas.ai"
    assert entrypoint.STAGING_SESSION_POLICY == STAGING_SESSION_POLICY == "shared_staging"
    assert entrypoint.REVIEW_SESSION_POLICY == REVIEW_SESSION_POLICY == "audience"
    assert entrypoint.ACCOUNT_DELETE_ENV_NAME == "ACCOUNT_DELETE_CLERK_SECRET_KEY"
    assert entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY == "CLERK_ACCOUNT_DELETION_SECRET"
    assert entrypoint.REVIEW_ACCOUNT_DELETE_VAULT_OBJECT == "CLERK-ACCOUNT-DELETION-SECRET"
    assert SHARED.is_file()
    # Behaviour: JS twin classify + render mapping (not source-string pins).
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            """
import {
  classifyAccountDeleteProfile, render, Refused,
  REVIEW_WEB_ORIGIN, REVIEW_CLERK_ISSUER, ACCOUNT_DELETE_ENV_NAME,
  REVIEW_ACCOUNT_DELETE_HOST_KEY, STAGING_ACCOUNT_DELETE_VAULT_SECRET,
} from './infra/standalone/render.mjs';
import {readFile} from 'node:fs/promises';
const sample=JSON.parse(await readFile('./infra/standalone/invented-host-input.json','utf8'));
const review=classifyAccountDeleteProfile({
  web_origin:REVIEW_WEB_ORIGIN, identity_policy:'audience',
  cors_origins:[REVIEW_WEB_ORIGIN,'app://cosmas','capacitor://localhost'],
  issuer:REVIEW_CLERK_ISSUER,
});
if(review!=='review') throw new Error('js twin review failed');
const omitted=classifyAccountDeleteProfile({
  identity_policy:'audience',
  cors_origins:[REVIEW_WEB_ORIGIN,'app://cosmas','capacitor://localhost'],
  issuer:REVIEW_CLERK_ISSUER,
});
if(omitted!=='review') throw new Error('js twin omitted web_origin failed');
const value=structuredClone(sample);
value.resource_scope='owned-cosmabot-vm-instance';
value.web_origin='https://staging.cosmas.ai';
value.api_origin='https://api.staging.cosmas.ai';
value.identity.apiOrigin=value.api_origin;
value.tls.hostnames=['staging.cosmas.ai','api.staging.cosmas.ai'];
value.identity_policy='audience';
value.identity.profile='operational-beta-v1';
value.identity.frontendOrigin='https://clerk.staging.cosmas.ai';
value.identity.publishableKey='pk_live_'+Buffer.from('clerk.staging.cosmas.ai$').toString('base64');
value.identity.audience='cosmas-os-beta-api';
value.beta_features={model:{origin:'https://invented-owned-chief.openai.azure.com',
  endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'},
  google:{client_id:'invented-client.apps.googleusercontent.com',
    callback_uri:value.api_origin+'/connections/google/callback',return_origin:value.web_origin}};
const files=render(value);
const names=files['host-preparation.json'].private_environment.key_vault_secret_names;
if(names[ACCOUNT_DELETE_ENV_NAME]!==STAGING_ACCOUNT_DELETE_VAULT_SECRET)
  throw new Error('staging vault mapping drifted');
if(names[ACCOUNT_DELETE_ENV_NAME]===REVIEW_ACCOUNT_DELETE_HOST_KEY)
  throw new Error('review host key leaked into staging mapping');
console.log('behaviour_ok');
""",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "behaviour_ok" in result.stdout
