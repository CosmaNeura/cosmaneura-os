"""Startup wiring for copy-to-EHR flags. Synthetic notes only; logs stay metadata."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from cosmas_os.api import copy_to_ehr_routes
from cosmas_os.api.copy_to_ehr_routes import (
    CopyToEhrFlagHeaderMiddleware,
    copy_to_ehr_flags_header,
    install_copy_to_ehr_draft_loader,
)

NOTE = "Taylor Morgan has a sore throat for two days."
STRUCTURED = "Subjective\nSore throat for two days.\n\nPlan\nFluids and rest."
DRAFT_ID = "visit_note_taylor"


def _flags(*, enabled: bool, remote: bool = False, fallback: bool = False):
    return SimpleNamespace(
        copy_to_ehr_enabled=enabled,
        copy_to_ehr_remote_enabled=remote,
        copy_to_ehr_fallback_enabled=fallback,
    )


def _client(enabled: bool, *, remote: bool = False, fallback: bool = False) -> TestClient:
    app = FastAPI()
    app.include_router(
        copy_to_ehr_routes.router(
            configuration=lambda: _flags(enabled=enabled, remote=remote, fallback=fallback)
        )
    )
    return TestClient(app)


@contextmanager
def _session():
    yield object()


def _note(content: str, version: int = 2):
    return SimpleNamespace(version=version, content=content)


@pytest.fixture(autouse=True)
def _reset_loader():
    copy_to_ehr_routes.configure_draft_loader(None)
    yield
    copy_to_ehr_routes.configure_draft_loader(None)


def test_flags_off_startup_does_not_register_a_loader_and_drafts_404():
    def open_session():
        raise AssertionError("session opened while copy to ehr is off")

    install_copy_to_ehr_draft_loader(enabled=False, open_session=open_session)
    off = _client(False)
    assert off.get(f"/api/copy-to-ehr/drafts/{DRAFT_ID}").status_code == 404
    assert off.get("/api/copy-to-ehr/flags").json() == {
        "copy_to_ehr_enabled": False,
        "copy_to_ehr_remote_enabled": False,
        "copy_to_ehr_fallback_enabled": False,
    }
    # The route flag can be on later, but startup never installed a loader.
    assert _client(True).get(f"/api/copy-to-ehr/drafts/{DRAFT_ID}").status_code == 404


def test_flags_on_startup_registers_loader_and_serves_synthetic_draft(caplog):
    def find_note(_session, draft_id: str):
        assert draft_id == DRAFT_ID
        return _note(STRUCTURED, version=3), True

    install_copy_to_ehr_draft_loader(enabled=True, open_session=_session, find_note=find_note)
    client = _client(True, remote=True, fallback=True)
    assert client.get("/api/copy-to-ehr/flags").json() == {
        "copy_to_ehr_enabled": True,
        "copy_to_ehr_remote_enabled": True,
        "copy_to_ehr_fallback_enabled": True,
    }
    with caplog.at_level(logging.DEBUG):
        response = client.get(f"/api/copy-to-ehr/drafts/{DRAFT_ID}", params={"profile": "atlas_md"})
    assert response.status_code == 200
    body = response.json()
    assert body["draft_id"] == DRAFT_ID
    assert body["draft_revision"] == "3"
    assert body["review_state"] == "reviewed"
    assert "Sore throat for two days." in body["full_note"]
    assert "Fluids and rest." in body["full_note"]
    assert "Sore throat for two days." not in caplog.text
    assert NOTE not in caplog.text


def test_loader_failure_log_has_no_note_text(caplog):
    def find_note(_session, _draft_id: str):
        raise RuntimeError(NOTE)

    install_copy_to_ehr_draft_loader(enabled=True, open_session=_session, find_note=find_note)
    hook_logger = logging.getLogger("cosmas_os.ehr_export.draft_source")
    was_disabled = hook_logger.disabled
    hook_logger.disabled = False
    try:
        with caplog.at_level(logging.INFO, logger="cosmas_os.ehr_export.draft_source"):
            response = _client(True).get(f"/api/copy-to-ehr/drafts/{DRAFT_ID}")
        assert response.status_code == 404
        assert "copy_to_ehr.draft_load_failed" in caplog.text
        assert NOTE not in caplog.text
        for record in caplog.records:
            blob = record.getMessage()
            for value in record.__dict__.values():
                if isinstance(value, str):
                    blob += " " + value
            assert NOTE not in blob
            assert "Sore throat" not in blob
    finally:
        hook_logger.disabled = was_disabled


def test_unstructured_note_loads_as_one_section_without_logging_text(caplog):
    def find_note(_session, _draft_id: str):
        return _note(NOTE, version=1), False

    install_copy_to_ehr_draft_loader(enabled=True, open_session=_session, find_note=find_note)
    with caplog.at_level(logging.DEBUG):
        response = _client(True).get(f"/api/copy-to-ehr/drafts/{DRAFT_ID}")
    assert response.status_code == 200
    body = response.json()
    assert [section["key"] for section in body["sections"]] == ["note"]
    assert body["review_state"] == "unreviewed"
    assert NOTE in body["full_note"]
    assert NOTE not in caplog.text


def test_api_startup_registers_loader_from_the_enabled_flag():
    source = (Path(__file__).parents[2] / "src/cosmas_os/api/app.py").read_text(encoding="utf-8")
    assert "install_copy_to_ehr_draft_loader(" in source
    assert "enabled=settings.copy_to_ehr_enabled" in source
    assert "open_session=session_scope" in source
    assert "CopyToEhrFlagHeaderMiddleware" in source


def test_flag_header_is_metadata_only_and_follows_the_three_flags():
    assert copy_to_ehr_flags_header(_flags(enabled=False)) == b"0,0,0"
    assert copy_to_ehr_flags_header(_flags(enabled=True, remote=True, fallback=True)) == b"1,1,1"
    assert NOTE.encode() not in copy_to_ehr_flags_header(_flags(enabled=True))

    async def ok(_request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/ok", ok)])
    app.add_middleware(CopyToEhrFlagHeaderMiddleware, configuration=lambda: _flags(enabled=False))
    response = TestClient(app).get("/ok")
    assert response.status_code == 200
    assert response.headers["x-cosmas-copy-to-ehr-flags"] == "0,0,0"
    assert NOTE not in response.text
