"""Boundary checks only: no database, listener, or external network is opened."""

import pytest
from tests.helpers.owned_process import database_socket, matches_endpoint, owned_root


@pytest.fixture(autouse=True)
def isolate_database_routing(monkeypatch):
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("PGSERVICE", raising=False)


def approve_root(monkeypatch, tmp_path):
    monkeypatch.setenv("COSMAS_TEST_TMP_ROOT", str(tmp_path))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/integration/test_process.py::test_owned (call)")
    root = tmp_path / "test_owned0"
    root.mkdir()
    return root


def test_accepts_only_the_explicit_pytest_child_root(monkeypatch, tmp_path):
    root = approve_root(monkeypatch, tmp_path)
    assert owned_root(root) == root
    for path in (tmp_path, tmp_path.parent, tmp_path / "missing", "relative"):
        with pytest.raises(PermissionError):
            owned_root(path)


@pytest.mark.parametrize("missing", ["COSMAS_TEST_TMP_ROOT", "PYTEST_CURRENT_TEST"])
def test_requires_both_parent_authorization_and_active_pytest(monkeypatch, tmp_path, missing):
    root = approve_root(monkeypatch, tmp_path)
    monkeypatch.delenv(missing)
    with pytest.raises(PermissionError):
        owned_root(root)


def test_rejects_symlink_roots_and_parent_traversal(monkeypatch, tmp_path):
    root = approve_root(monkeypatch, tmp_path)
    link = tmp_path / "linked"
    link.symlink_to(root, target_is_directory=True)
    for path in (link, root / ".." / root.name):
        with pytest.raises(PermissionError):
            owned_root(path)
    monkeypatch.setenv("COSMAS_TEST_TMP_ROOT", str(link))
    with pytest.raises(PermissionError):
        owned_root(root)


@pytest.mark.parametrize("host,port", [("127.0.0.1", 55800), ("127.0.0.1", 55479), ("::1", 55801)])
def test_accepts_the_exact_runner_database_socket(monkeypatch, host, port):
    authority = f"[{host}]" if ":" in host else host
    monkeypatch.setenv("DATABASE_URL", f"postgresql+psycopg://fixture@{authority}:{port}/w1a_owned")
    endpoint = database_socket()
    assert endpoint == (host, port)
    assert matches_endpoint(host, port, endpoint)
    assert matches_endpoint(host.encode("ascii"), str(port), endpoint)
    assert not matches_endpoint(host, port + 1, endpoint)
    assert not matches_endpoint("external.example.invalid", port, endpoint)


@pytest.mark.parametrize("url", [
    "",
    "postgresql+psycopg://fixture@external.example.invalid:55800/w1a_owned",
    "postgresql+psycopg://fixture@192.0.2.1:55800/w1a_owned",
    "postgresql+psycopg://fixture@localhost:55800/w1a_owned",
    "postgresql+psycopg://fixture@127.0.0.1/w1a_owned",
    "postgresql+psycopg://fixture@127.0.0.1:0/w1a_owned",
    "postgresql+psycopg://fixture@127.0.0.1:65536/w1a_owned",
    "postgresql+psycopg://fixture@127.0.0.1:55800/production",
    "postgresql+psycopg://fixture@127.0.0.1:55800/w1a_",
    "postgresql+psycopg://fixture@127.0.0.1:55800/w1a_owned?host=external.example.invalid",
    "postgresql+psycopg://fixture@127.0.0.1:55800/w1a_owned?hostaddr=192.0.2.1",
    "postgresql+psycopg://fixture@127.0.0.1:55800/w1a_owned?service=external",
    "postgresql+psycopg://fixture@127.0.0.1:55800/w1a_owned#fragment",
    "sqlite:///w1a_owned",
])
def test_rejects_external_ambiguous_or_non_test_databases(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(PermissionError):
        database_socket()


@pytest.mark.parametrize("name,value", [("PGHOSTADDR", "192.0.2.1"), ("PGSERVICE", "external")])
def test_rejects_libpq_environment_routing_overrides(monkeypatch, name, value):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://fixture@127.0.0.1:55800/w1a_owned")
    monkeypatch.setenv(name, value)
    with pytest.raises(PermissionError):
        database_socket()
