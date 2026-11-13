"""Parity: entrypoint and render classifyAccountDeleteProfile share one matrix."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO / "infra/standalone/package/entrypoint.py"
RENDER = REPO / "infra/standalone/render.mjs"
MATRIX = REPO / "infra/standalone/account-delete-profile-matrix.json"


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
def test_entrypoint_classify_matches_shared_matrix(row):
    entrypoint = _load_entrypoint()
    kind = entrypoint.classify_account_delete_profile(
        policy=row["policy"],
        web_origin=row["web_origin"],
        cors=row["cors"],
        issuer=row["issuer"],
    )
    expected = None if row["expect"] == "none" else row["expect"]
    assert kind == expected
    # CORS-only path (entrypoint runtime) must agree when web_origin is omitted.
    cors_only = entrypoint.classify_account_delete_profile(
        policy=row["policy"],
        web_origin=None,
        cors=row["cors"],
        issuer=row["issuer"],
    )
    if row["web_origin"] in (entrypoint.REVIEW_WEB_ORIGIN, entrypoint.STAGING_WEB_ORIGIN) or (
        entrypoint.REVIEW_WEB_ORIGIN in row["cors"] or entrypoint.STAGING_WEB_ORIGIN in row["cors"]
    ):
        # When CORS already encodes the web origin (or mixed), cors-only matches.
        if row["web_origin"] in {p.strip() for p in row["cors"].split(",") if p.strip()}:
            assert cors_only == expected


def test_entrypoint_constants_match_render_exports():
    entrypoint = _load_entrypoint()
    render = RENDER.read_text(encoding="utf-8")
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
