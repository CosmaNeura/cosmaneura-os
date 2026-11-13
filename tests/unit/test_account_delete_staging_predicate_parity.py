"""Parity: entrypoint account-delete predicate must match render.mjs exactly."""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO / "infra/standalone/package/entrypoint.py"
RENDER = REPO / "infra/standalone/render.mjs"

EXPECTED_STAGING_ORIGIN = "https://staging.cosmas.ai"
EXPECTED_REVIEW_ORIGIN = "https://beta.cosmas.ai"
EXPECTED_POLICY = "shared_staging"


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location(
        "standalone_package_entrypoint_parity", ENTRYPOINT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_account_delete_staging_constants_match_render_mjs():
    """Python and JS must share the same origin and policy constants."""
    entry = ENTRYPOINT.read_text(encoding="utf-8")
    render = RENDER.read_text(encoding="utf-8")
    entrypoint = _load_entrypoint()

    assert f'STAGING_WEB_ORIGIN = "{EXPECTED_STAGING_ORIGIN}"' in entry
    assert f'REVIEW_WEB_ORIGIN = "{EXPECTED_REVIEW_ORIGIN}"' in entry
    assert f'STAGING_SESSION_POLICY = "{EXPECTED_POLICY}"' in entry
    assert f"const STAGING_WEB_ORIGIN='{EXPECTED_STAGING_ORIGIN}'" in render
    assert f"const REVIEW_WEB_ORIGIN='{EXPECTED_REVIEW_ORIGIN}'" in render
    assert f"const STAGING_SESSION_POLICY='{EXPECTED_POLICY}'" in render
    assert entrypoint.ACCOUNT_DELETE_ENV_NAME == "ACCOUNT_DELETE_CLERK_SECRET_KEY"
    assert entrypoint.REVIEW_ACCOUNT_DELETE_KV_NAME == "CLERK_ACCOUNT_DELETION_SECRET"
    assert "ACCOUNT_DELETE_CLERK_SECRET_KEY:'CLERK_ACCOUNT_DELETION_SECRET'" in render
    assert "ACCOUNT_DELETE_CLERK_SECRET_KEY:'account-delete-clerk-secret-key'" in render

    # Issuer-only admission is forbidden in both copies.
    assert "STAGING_CLERK_ISSUER" not in entry
    assert "STAGING_CLERK_ISSUER" not in render
    assert re.search(
        r"const stagingHost=value\.web_origin===STAGING_WEB_ORIGIN",
        render,
    )
    assert re.search(
        r"const reviewHost=value\.web_origin===REVIEW_WEB_ORIGIN",
        render,
    )
    assert re.search(
        r"const stagingProfile=value\.identity_policy===STAGING_SESSION_POLICY\|\|stagingHost;",
        render,
    )
    assert re.search(
        r"const accountDeleteProfile=stagingProfile\|\|reviewHost;",
        render,
    )
    # Env name allowed on both profiles; staging and review KV secret names differ.
    assert "if(accountDeleteProfile){" in render
    assert "optional_exact_names=['ACCOUNT_DELETE_CLERK_SECRET_KEY']" in render
    after_admit = render.split("const accountDeleteProfile=stagingProfile||reviewHost;")[1]
    first_staging = after_admit.split("if(stagingProfile){")[1].split("}else if(reviewHost){")[0]
    assert "ACCOUNT_DELETE_CLERK_SECRET_KEY:'account-delete-clerk-secret-key'" in first_staging
    assert "key_vault_name" in first_staging
    assert "optional_exact_names" not in first_staging
    review_map = after_admit.split("}else if(reviewHost){")[1].split("if(ownedVm)")[0]
    assert "ACCOUNT_DELETE_CLERK_SECRET_KEY:'CLERK_ACCOUNT_DELETION_SECRET'" in review_map
    assert "account-delete-clerk-secret-key" not in review_map
    assert "key_vault_name" not in review_map
    assert "key_vault_uri" not in review_map
    # Join pin: env name and #356 KV name meet in render key_vault_secret_names.
    assert "ACCOUNT_DELETE_CLERK_SECRET_KEY:'CLERK_ACCOUNT_DELETION_SECRET'" in render


def test_account_delete_staging_predicate_ast_has_no_issuer_branch():
    """AST of account_delete_profile: policy OR staging origin OR review origin."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    tree = ast.parse(text)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "account_delete_profile"
    )
    # Body only (skip docstring): no issuer attribute and a single BoolOp Or.
    body = list(fn.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    body_source = "\n".join(
        ast.get_source_segment(text, node) or "" for node in body
    )
    assert "clerk_issuer" not in body_source
    assert "STAGING_CLERK_ISSUER" not in body_source
    assert "STAGING_SESSION_POLICY" in body_source
    assert "STAGING_WEB_ORIGIN" in body_source
    assert "REVIEW_WEB_ORIGIN" in body_source
    returns = [node for node in body if isinstance(node, ast.Return)]
    assert len(returns) == 1
    assert isinstance(returns[0].value, ast.BoolOp)
    assert isinstance(returns[0].value.op, ast.Or)
    assert len(returns[0].value.values) == 3


@pytest.mark.parametrize(
    "policy,origins,expected",
    [
        ("shared_staging", "https://workspace.invented-practice.test", True),
        ("audience", "https://staging.cosmas.ai", True),
        ("audience", "https://staging.cosmas.ai,app://cosmas", True),
        ("audience", "https://beta.cosmas.ai", True),
        ("audience", "https://beta.cosmas.ai,app://cosmas,capacitor://localhost", True),
        ("audience", "https://workspace.invented-practice.test", False),
        ("shared_staging", "https://beta.cosmas.ai", True),
        ("audience", "https://cosmas.ai", False),
    ],
)
def test_staging_account_delete_profile_behavior_matrix(policy, origins, expected):
    """Behavioral pin of admitted branches (staging, review) and refusals."""
    entrypoint = _load_entrypoint()

    class Checked:
        clerk_session_policy = policy
        cors_allowed_origins = origins
        clerk_issuer = "https://clerk.staging.cosmas.ai"  # issuer must not matter

    assert entrypoint.account_delete_profile(Checked()) is expected
    assert entrypoint.STAGING_WEB_ORIGIN == EXPECTED_STAGING_ORIGIN
    assert entrypoint.REVIEW_WEB_ORIGIN == EXPECTED_REVIEW_ORIGIN
    assert entrypoint.STAGING_SESSION_POLICY == EXPECTED_POLICY
