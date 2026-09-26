from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosmas_os.compact.web import install_compact_web
from cosmas_os.config import Settings


def config(**overrides):
    values = dict(
        _env_file=None,
        cosmas_env="synth_os",
        data_mode="synthetic",
        auth_mode="synth_headers",
        blob_backend="local",
        sync_worker=False,
        execution_backend="postgres_local",
        database_url="postgresql+psycopg://compact_synth:invented@127.0.0.1:55439/compact_test",
        cors_allowed_origins="http://127.0.0.1:8008",
    )
    return Settings(**(values | overrides))


def test_local_profile_does_not_need_redis():
    config(redis_url="").validate_runtime_configuration()


@pytest.mark.parametrize(
    "overrides",
    [
        {"cosmas_env": "early_adopter_beta"},
        {"auth_mode": "clerk_jwt"},
        {"data_mode": "authorized_beta"},
        {"blob_backend": "azure"},
        {"sync_worker": True},
        {
            "database_url": "postgresql+psycopg://compact_synth:invented@example.invalid/compact_test"
        },
        {"database_url": "postgresql+psycopg://compact_synth:invented@127.0.0.1/cosmas_os"},
        {"cors_allowed_origins": "http://0.0.0.0:8008"},
        {"cors_allowed_origins": "https://public.example.invalid"},
    ],
)
def test_compact_profile_fails_closed(overrides):
    with pytest.raises(RuntimeError, match="unsafe runtime"):
        config(**overrides).validate_runtime_configuration()


def test_static_assets_are_isolated_from_api_and_private_files(tmp_path):
    bundle = tmp_path / "dist"
    bundle.mkdir()
    (bundle / "assets").mkdir()
    (bundle / "index.html").write_text("<html>invented compact fixture</html>")
    (bundle / "assets" / "app.js").write_text("console.log('synthetic');")
    (tmp_path / "private.txt").write_text("not a public asset")
    (bundle / "assets" / "private.txt").symlink_to(tmp_path / "private.txt")
    app = FastAPI()
    install_compact_web(app, config(compact_web_root=str(bundle)))
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["cache-control"] == "no-store"
    assert client.get("/assets/app.js").status_code == 200
    for path in (
        "/api/not-real",
        "/private.txt",
        "/assets/private.txt",
        "/assets/%2e%2e/private.txt",
    ):
        assert client.get(path).status_code == 404


def test_static_experiment_cannot_be_installed_in_beta(tmp_path):
    with pytest.raises(RuntimeError):
        install_compact_web(
            FastAPI(), config(cosmas_env="early_adopter_beta", compact_web_root=str(tmp_path))
        )
