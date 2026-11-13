"""Parity: shared classify_review_profile and render classifyAccountDeleteProfile."""

from __future__ import annotations

import importlib.util
import json
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
    if row["web_origin"] in (REVIEW_WEB_ORIGIN, STAGING_WEB_ORIGIN) or (
        REVIEW_WEB_ORIGIN in row["cors"] or STAGING_WEB_ORIGIN in row["cors"]
    ):
        if row["web_origin"] in {p.strip() for p in row["cors"].split(",") if p.strip()}:
            assert cors_only == expected


@pytest.mark.parametrize("row", _matrix_rows(), ids=lambda row: row["id"])
def test_entrypoint_thin_alias_matches_shared_classify(row):
    entrypoint = _load_entrypoint()
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


def test_entrypoint_reexports_shared_constants_and_render_keeps_js_twin():
    entrypoint = _load_entrypoint()
    render = RENDER.read_text(encoding="utf-8")
    assert entrypoint.STAGING_WEB_ORIGIN is STAGING_WEB_ORIGIN
    assert entrypoint.REVIEW_WEB_ORIGIN is REVIEW_WEB_ORIGIN
    assert entrypoint.REVIEW_CLERK_ISSUER is REVIEW_CLERK_ISSUER
    assert entrypoint.STAGING_SESSION_POLICY is STAGING_SESSION_POLICY
    assert entrypoint.REVIEW_SESSION_POLICY is REVIEW_SESSION_POLICY
    assert entrypoint.STAGING_WEB_ORIGIN == "https://staging.cosmas.ai"
    assert entrypoint.REVIEW_WEB_ORIGIN == "https://beta.cosmas.ai"
    assert entrypoint.REVIEW_CLERK_ISSUER == "https://clerk.beta.cosmas.ai"
    assert entrypoint.STAGING_SESSION_POLICY == "shared_staging"
    assert entrypoint.REVIEW_SESSION_POLICY == "audience"
    assert entrypoint.ACCOUNT_DELETE_ENV_NAME == "ACCOUNT_DELETE_CLERK_SECRET_KEY"
    assert entrypoint.REVIEW_ACCOUNT_DELETE_HOST_KEY == "CLERK_ACCOUNT_DELETION_SECRET"
    assert entrypoint.REVIEW_ACCOUNT_DELETE_VAULT_OBJECT == "CLERK-ACCOUNT-DELETION-SECRET"
    assert "export const REVIEW_ACCOUNT_DELETE_HOST_KEY='CLERK_ACCOUNT_DELETION_SECRET'" in render
    assert "export const REVIEW_ACCOUNT_DELETE_VAULT_OBJECT='CLERK-ACCOUNT-DELETION-SECRET'" in render
    assert "export const STAGING_ACCOUNT_DELETE_VAULT_SECRET='account-delete-clerk-secret-key'" in render
    assert "export function classifyAccountDeleteProfile" in render
    assert SHARED.is_file()
