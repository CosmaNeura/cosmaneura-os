"""Copy to EHR phone-remote contract: flag gate, highlight-only payloads, expiry."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cosmas_os.api.copy_to_ehr_remote_routes import router
from cosmas_os.api.copy_to_ehr_remote_schemas import (
    CreateRemoteSession,
    HighlightRemoteSection,
)
from cosmas_os.application import copy_to_ehr_remote as remote
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.config import Settings

HEADERS = {
    "Authorization": "Bearer synthetic",
    "X-Cosmas-Copy-To-Ehr": "1",
    "Content-Type": "application/json",
}


def create_body(**changes):
    body = {
        "draft_id": str(uuid4()),
        "draft_revision": 1,
        "section_keys": ["subjective", "objective", "assessment", "plan"],
        "visit_key": "visit-taylor-morgan-sore-throat",
    }
    body.update(changes)
    return body


@pytest.mark.parametrize(
    "change",
    [
        {"text": "Taylor Morgan reports an invented sore throat."},
        {"note_text": "Invented note"},
        {"section_keys": ["Subjective"]},
        {"draft_revision": 0},
        {"visit_key": "bad key"},
        {"section_keys": ["subjective", "subjective"]},
    ],
)
def test_create_body_rejects_note_text_and_invalid_keys(change):
    with pytest.raises(ValidationError):
        CreateRemoteSession.model_validate({**create_body(), **change})


@pytest.mark.parametrize(
    "body",
    [
        {"draft_revision": 1, "section_key": "subjective", "text": "nope"},
        {"draft_revision": 1, "section_key": "S"},
        {"draft_revision": 0, "section_key": "subjective"},
    ],
)
def test_highlight_body_is_keys_only(body):
    with pytest.raises(ValidationError):
        HighlightRemoteSection.model_validate(body)


def isolated(enabled=True, identity=None, store=None):
    app = FastAPI()
    calls = []
    member = identity or SimpleNamespace(
        auth_mode="clerk_jwt",
        external_identity_id=str(uuid4()),
        box_id=str(uuid4()),
        principal_id=str(uuid4()),
    )
    sessions = store or remote.RemoteSessionStore()

    def fence(*_):
        calls.append("fence")

    @app.exception_handler(WorkspaceError)
    async def closed_error(_request, exc: WorkspaceError):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    app.include_router(
        router(
            configuration=lambda: SimpleNamespace(copy_to_ehr_remote_enabled=enabled),
            identity_dependency=lambda: member,
            session_dependency=lambda: object(),
            workspace_gate=lambda: None,
            fence=fence,
            store=sessions,
        )
    )
    return TestClient(app), calls, member, sessions


def test_flag_defaults_off_on_settings_and_route_stays_dark():
    assert Settings().copy_to_ehr_remote_enabled is False
    client, calls, _, store = isolated(enabled=False)
    with client:
        result = client.post("/api/copy-to-ehr/sessions", headers=HEADERS, json=create_body())
    assert result.status_code == 404
    assert result.json() == {"detail": "copy_to_ehr_remote_unavailable"}
    assert calls == []
    assert store.current(box_id="x", principal_id="y") is None


def test_desktop_native_identity_stays_dark():
    identity = SimpleNamespace(
        auth_mode="desktop_native",
        external_identity_id=None,
        box_id=str(uuid4()),
        principal_id=str(uuid4()),
    )
    client, calls, _, _ = isolated(identity=identity)
    with client:
        result = client.post("/api/copy-to-ehr/sessions", headers=HEADERS, json=create_body())
    assert result.status_code == 404
    assert result.json() == {"detail": "copy_to_ehr_remote_unavailable"}
    assert calls == []


def test_computer_creates_session_and_phone_highlight_contains_no_note_text():
    client, calls, member, store = isolated()
    body = create_body()
    with client:
        created = client.post("/api/copy-to-ehr/sessions", headers=HEADERS, json=body)
        assert created.status_code == 201
        session = created.json()
        remote.assert_no_note_text(session)
        assert session["status"] == "open"
        assert session["section_keys"] == body["section_keys"]
        assert "text" not in session

        highlighted = client.post(
            f"/api/copy-to-ehr/sessions/{session['session_id']}/highlight",
            headers=HEADERS,
            json={"draft_revision": 1, "section_key": "subjective"},
        )
        assert highlighted.status_code == 200
        event = highlighted.json()
        remote.assert_no_note_text(event)
        assert set(event) == {"seq", "section_key", "draft_revision", "at"}
        assert event["section_key"] == "subjective"

        polled = client.get(
            f"/api/copy-to-ehr/sessions/{session['session_id']}/events?after=0",
            headers={"Authorization": "Bearer synthetic", "X-Cosmas-Copy-To-Ehr": "1"},
        )
        assert polled.status_code == 200
        page = polled.json()
        remote.assert_no_note_text(page)
        assert page["events"] == [event]
        assert page["next_after"] == event["seq"]

        current = client.get(
            "/api/copy-to-ehr/sessions/current",
            headers={"Authorization": "Bearer synthetic", "X-Cosmas-Copy-To-Ehr": "1"},
        )
        assert current.status_code == 200
        assert current.json()["session_id"] == session["session_id"]

    assert calls
    owned = store.get_for_owner(
        session_id=session["session_id"],
        box_id=member.box_id,
        principal_id=member.principal_id,
    )
    assert owned.draft_revision == 1


def test_other_clinician_cannot_read_or_highlight_another_session():
    store = remote.RemoteSessionStore()
    first = SimpleNamespace(
        auth_mode="clerk_jwt",
        external_identity_id=str(uuid4()),
        box_id=str(uuid4()),
        principal_id=str(uuid4()),
    )
    second = SimpleNamespace(
        auth_mode="clerk_jwt",
        external_identity_id=str(uuid4()),
        box_id=first.box_id,
        principal_id=str(uuid4()),
    )
    client_a, _, _, _ = isolated(identity=first, store=store)
    with client_a:
        created = client_a.post("/api/copy-to-ehr/sessions", headers=HEADERS, json=create_body())
        session_id = created.json()["session_id"]

    client_b, _, _, _ = isolated(identity=second, store=store)
    with client_b:
        denied = client_b.post(
            f"/api/copy-to-ehr/sessions/{session_id}/highlight",
            headers=HEADERS,
            json={"draft_revision": 1, "section_key": "subjective"},
        )
        missing = client_b.get(
            f"/api/copy-to-ehr/sessions/{session_id}/events?after=0",
            headers={"Authorization": "Bearer synthetic", "X-Cosmas-Copy-To-Ehr": "1"},
        )
    assert denied.status_code == 404
    assert missing.status_code == 404


def test_idle_and_absolute_session_expiry():
    store = remote.RemoteSessionStore()
    start = datetime(2026, 11, 9, 18, 0, tzinfo=UTC)
    session = store.create(
        box_id="box",
        principal_id="clinician",
        draft_id=str(uuid4()),
        draft_revision=1,
        section_keys=["subjective", "plan"],
        visit_key="visit-1",
        now=start,
    )

    idle_expired = store.events_after(
        session_id=session.id,
        box_id="box",
        principal_id="clinician",
        after=0,
        now=start + timedelta(minutes=15),
    )[0]
    assert remote.session_status(idle_expired) == "expired"
    assert idle_expired.end_reason == "idle"

    fresh = store.create(
        box_id="box",
        principal_id="clinician",
        draft_id=str(uuid4()),
        draft_revision=2,
        section_keys=["subjective"],
        visit_key="visit-2",
        now=start,
    )
    # Keep the session active with a highlight just before the absolute limit,
    # then expire only on the 60-minute absolute clock.
    store.highlight(
        session_id=fresh.id,
        box_id="box",
        principal_id="clinician",
        draft_revision=2,
        section_key="subjective",
        now=start + timedelta(minutes=14),
    )
    absolute = store.events_after(
        session_id=fresh.id,
        box_id="box",
        principal_id="clinician",
        after=0,
        now=start + timedelta(minutes=60),
    )[0]
    assert remote.session_status(absolute) == "expired"
    assert absolute.end_reason == "absolute"


def test_revision_mismatch_and_end_reasons():
    store = remote.RemoteSessionStore()
    session = store.create(
        box_id="box",
        principal_id="clinician",
        draft_id=str(uuid4()),
        draft_revision=3,
        section_keys=["assessment"],
        visit_key="visit-3",
    )
    with pytest.raises(WorkspaceError) as mismatch:
        store.highlight(
            session_id=session.id,
            box_id="box",
            principal_id="clinician",
            draft_revision=2,
            section_key="assessment",
        )
    assert mismatch.value.code == "copy_to_ehr_remote_revision_mismatch"

    ended = store.end(
        session_id=session.id,
        box_id="box",
        principal_id="clinician",
        reason="visit_change",
    )
    assert remote.session_status(ended) == "ended"
    assert ended.end_reason == "visit_change"
    assert store.current(box_id="box", principal_id="clinician") is None


def test_missing_contract_header_fails_closed():
    client, calls, _, _ = isolated()
    with client:
        result = client.post(
            "/api/copy-to-ehr/sessions",
            headers={"Authorization": "Bearer synthetic", "Content-Type": "application/json"},
            json=create_body(),
        )
    assert result.status_code == 422
    assert result.json() == {"detail": "invalid_copy_to_ehr_remote_request"}
    assert calls == []
