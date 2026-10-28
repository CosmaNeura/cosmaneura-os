"""CI partitions retain every test file and its required database profile."""

import importlib.util
from pathlib import Path

import pytest


def runner():
    path = Path(__file__).resolve().parents[2] / "scripts/check-backend-local.py"
    spec = importlib.util.spec_from_file_location("backend_suites", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ci_file_partitions_are_complete_disjoint_and_keep_database_profiles():
    module = runner()
    expected = {
        path.relative_to(module.REPO).as_posix()
        for pattern in ("test_*.py", "*_test.py")
        for path in (module.REPO / "tests").rglob(pattern)
    }
    observed = set()
    for suite in (*module.BACKEND_SUITES, *module.SIGNED_UI_SUITES):
        groups, ignored = module.suite_selections(suite)
        assert not ignored
        assert groups
        for profile, paths in groups.items():
            for path in paths:
                assert path not in observed
                observed.add(path)
                required = (
                    "compact" if path == module.COMPACT_TEST
                    else "deployment" if path in module.DEPLOYMENT_TESTS
                    else "workspace"
                )
                assert profile == required
                assert (path in module.SIGNED_UI_TESTS) == (suite in module.SIGNED_UI_SUITES)
    assert observed == expected
    assert set(module.DEPLOYMENT_TESTS) | {module.COMPACT_TEST} <= observed


def test_backend_discovery_includes_new_files_from_both_pytest_patterns(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "SIGNED_UI_TESTS", ("tests/integration/test_invented_ui_server_lab.py",))
    names = (
        "tests/unit/test_alpha.py", "tests/unit/beta_test.py",
        "tests/integration/test_gamma.py", "tests/integration/delta_test.py",
        "tests/unit/helper.py", "tests/integration/test_invented_ui_server_lab.py",
    )
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    assert set(module.backend_tests()) == set(names[:4])
    added = tmp_path / "tests/unit/new_test.py"
    added.touch()
    assigned = [
        path
        for suite in module.BACKEND_SUITES
        for paths in module.suite_selections(suite)[0].values()
        for path in paths
    ]
    assert set(assigned) == set(names[:4]) | {"tests/unit/new_test.py"}
    assert len(assigned) == len(set(assigned))


def test_existing_full_backend_selection_is_preserved():
    module = runner()
    groups, ignored = module.suite_selections("backend")
    assert groups == module.selections([], "all")
    assert ignored == module.SIGNED_UI_TESTS


def test_empty_backend_partition_refuses_to_run_unbounded_fallback(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, "REPO", tmp_path)
    with pytest.raises(ValueError, match="No backend tests belong"):
        module.suite_selections("backend-1")
