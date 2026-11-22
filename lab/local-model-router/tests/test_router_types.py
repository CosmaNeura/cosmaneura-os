from local_model_router.router_types import batch_kind_for_lane


def test_local_lane_returns_local():
    assert batch_kind_for_lane("local_model") == "local"


def test_azure_codex_mini_returns_azure():
    assert batch_kind_for_lane("azure_codex_mini") == "azure"


def test_gpt_5_3_codex_returns_azure():
    assert batch_kind_for_lane("gpt_5_3_codex") == "azure"


def test_cursor_cloud_agent_returns_cloud():
    assert batch_kind_for_lane("cursor_cloud_agent") == "cloud"


def test_unrouted_returns_none():
    assert batch_kind_for_lane("unrouted") == "none"


def test_aborted_returns_none():
    assert batch_kind_for_lane("aborted") == "none"


def test_none_returns_none():
    assert batch_kind_for_lane("none") == "none"
