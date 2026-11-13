"""Parity: entrypoint staging predicate must match render.mjs exactly."""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO / "infra/standalone/package/entrypoint.py"
RENDER = REPO / "infra/standalone/render.mjs"

EXPECTED_ORIGIN = "https://staging.cosmas.ai"
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

    assert f'STAGING_WEB_ORIGIN = "{EXPECTED_ORIGIN}"' in entry
    assert f'STAGING_SESSION_POLICY = "{EXPECTED_POLICY}"' in entry
    assert f"const STAGING_WEB_ORIGIN='{EXPECTED_ORIGIN}'" in render
    assert f"const STAGING_SESSION_POLICY='{EXPECTED_POLICY}'" in render

    # Issuer-only admission is forbidden in both copies.
    assert "STAGING_CLERK_ISSUER" not in entry
    assert "STAGING_CLERK_ISSUER" not in render
    assert re.search(
        r"const stagingHost=value\.web_origin===STAGING_WEB_ORIGIN",
        render,
    )
    assert re.search(
        r"const stagingProfile=value\.identity_policy===STAGING_SESSION_POLICY\|\|stagingHost",
        render,
    )


def test_account_delete_staging_predicate_ast_has_no_issuer_branch():
    """AST of staging_account_delete_profile: policy OR origin only."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    tree = ast.parse(text)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "staging_account_delete_profile"
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
    returns = [node for node in body if isinstance(node, ast.Return)]
    assert len(returns) == 1
    assert isinstance(returns[0].value, ast.BoolOp)
    assert isinstance(returns[0].value.op, ast.Or)
    assert len(returns[0].value.values) == 2


@pytest.mark.parametrize(
    "policy,origins,expected",
    [
        ("shared_staging", "https://workspace.invented-practice.test", True),
        ("audience", "https://staging.cosmas.ai", True),
        ("audience", "https://staging.cosmas.ai,app://cosmas", True),
        ("audience", "https://beta.cosmas.ai", False),
        ("audience", "https://workspace.invented-practice.test", False),
        ("shared_staging", "https://beta.cosmas.ai", True),
    ],
)
def test_staging_account_delete_profile_behavior_matrix(policy, origins, expected):
    """Behavioral pin of the two admitted branches (and their refusals)."""
    entrypoint = _load_entrypoint()

    class Checked:
        clerk_session_policy = policy
        cors_allowed_origins = origins
        clerk_issuer = "https://clerk.staging.cosmas.ai"  # issuer must not matter

    assert entrypoint.staging_account_delete_profile(Checked()) is expected
    assert entrypoint.STAGING_WEB_ORIGIN == EXPECTED_ORIGIN
    assert entrypoint.STAGING_SESSION_POLICY == EXPECTED_POLICY
