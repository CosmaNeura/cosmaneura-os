from types import SimpleNamespace

import pytest
from src.cosmas_os.api.workspace_protocol import HEADER, PROTOCOL, protected, required


def get_scope(method="GET", path="/workspaces/1", type="http"):
    return {"method": method, "path": path, "type": type}


def get_rt(workspace_hosted_enabled=True, cosmas_env="x", workspace_draft_recovery_required=True):
    return SimpleNamespace(
        workspace_hosted_enabled=workspace_hosted_enabled,
        cosmas_env=cosmas_env,
        workspace_draft_recovery_required=workspace_draft_recovery_required,
    )


def test_constants():
    assert PROTOCOL == "1"
    assert HEADER == b"x-cosmas-workspace-protocol"


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/workspaces/1"),
        ("GET", "/provider-team/x"),
        ("POST", "/inbox/a/b"),
        ("GET", "/workspaces"),
        ("GET", "/research/x"),
        ("GET", "/inbox-handoffs/1"),
        ("GET", "/connections/other"),
        ("POST", "/connections/google/callback"),
    ],
)
def test_protected_positive(method, path):
    scope = get_scope(method=method, path=path)
    assert protected(scope) is True


@pytest.mark.parametrize(
    "method, path, type",
    [
        ("OPTIONS", "/workspaces/1", "http"),  # Change method to OPTIONS
        ("GET", "/health", "http"),  # Change path to non-root
        ("GET", "/", "http"),  # Change path to root
        ("GET", "/Workspaces/1", "http"),  # Change path case
        ("GET", "/inbox-handoff/1", "http"),  # Change path typo (singular)
        ("GET", "/workspaces/1", "websocket"),  # Change type to websocket
    ],
)
def test_protected_negative_variants(method, path, type):
    scope = get_scope(method=method, path=path, type=type)
    assert protected(scope) is False


@pytest.mark.parametrize(
    "path",
    [
        "/connections/google/callback",
        "/connections/microsoft/callback",
        "/connections/scheduling/google/callback",
    ],
)
def test_protected_negative_callbacks(path):
    # Change method to GET on a callback path
    scope = get_scope(method="GET", path=path)
    assert protected(scope) is False


@pytest.mark.parametrize(
    "hosted, env, recovery, expected",
    [
        (True, "x", True, True),
        (True, "x", False, False),
        (False, "standalone_synthetic", True, True),
        (False, "standalone_synthetic", False, False),
        (False, "other", True, False),
    ],
)
def test_required(hosted, env, recovery, expected):
    rt = get_rt(
        workspace_hosted_enabled=hosted, cosmas_env=env, workspace_draft_recovery_required=recovery
    )
    assert required(rt) is expected
