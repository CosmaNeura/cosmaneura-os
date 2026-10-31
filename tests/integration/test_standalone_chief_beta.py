"""Signed standalone account -> own notes -> bounded Chief HTTP -> durable recovery.

Uses only the explicitly marked qualification PostgreSQL database and invented
identities/content. Mock HTTP passes through the actual pinned model adapter.
"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration import test_standalone_practice as owned
from tests.unit.test_standalone_beta_features import MODEL_ORIGIN, google_values, model_values

from cosmas_os.adapters.gpt41 import GPT41Connector
from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import conversation, handoffs, model_work, provider_team
from cosmas_os.application.capture_deadline import own_capture_session
from cosmas_os.application.standalone_practice import (
    StandalonePracticeManifest,
    reserve_standalone_practice,
    seed_standalone_practice,
)
from cosmas_os.models import (
    CoreCaptureAccount,
    ModelWorkAdmission,
    Operation,
    Ticket,
    WorkspaceHandoff,
)

case = owned.case


@pytest.fixture
def chief(case, monkeypatch):
    c = case
    issuer, origin = "https://identity.invented-cosmabot.test", "https://workspace.invented-cosmabot.test"
    c.config = c.config.model_copy(update={
        "cosmas_env": "standalone_clerk_synthetic", "standalone_jwks_path": "",
        "standalone_clerk_issuer_allowlist": issuer, "workspace_hosted_enabled": True,
        "clerk_issuer": issuer, "clerk_jwks_url": issuer + "/.well-known/jwks.json",
        "clerk_session_policy": "audience", "clerk_audience": "invented-practice-app-api",
        "clerk_organization_id": "org_invented_chief_practice",
        "clerk_authorized_parties": origin, "cors_allowed_origins": origin,
        **model_values(),
    })
    c.config.validate_runtime_configuration()
    manifest = c.manifest.model_dump(mode="json")
    manifest["identity"].update(clerk_issuer=issuer, clerk_organization_id=c.config.clerk_organization_id)
    c.manifest = StandalonePracticeManifest.model_validate(manifest)
    reserve_standalone_practice(c.session, c.config, c.manifest)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_keys(self, **_):
            return [SimpleNamespace(key_id="invented-chief-key", key=private.public_key())]

    def fresh_session(*_):
        return own_capture_session(Session(bind=c.session.get_bind(), join_transaction_mode="create_savepoint", autoflush=False))

    def dependency():
        with fresh_session() as current:
            yield current

    def token(subject):
        now = datetime.now(UTC)
        return jwt.encode({"iss": issuer, "sub": subject, "org_id": c.config.clerk_organization_id,
            "sid": "sess_invented_chief", "aud": c.config.clerk_audience, "azp": origin,
            "iat": now, "nbf": now, "exp": now + timedelta(minutes=5)}, private,
            algorithm="RS256", headers={"kid": "invented-chief-key"})

    monkeypatch.setattr(api, "settings", c.config)
    monkeypatch.setattr(api, "new_capture_session", fresh_session)
    monkeypatch.setattr(api, "_clerk_verifier", lambda native_origin=None: ClerkTokenVerifier(
        c.config, jwks_client=Keys(), start_background_refresh=False, native_origin=native_origin))
    for module in (provider_team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", c.config)
    previous = api.app.dependency_overrides.copy()
    api.app.dependency_overrides[api.get_session] = dependency
    c.headers = {"Authorization": "Bearer " + token(c.manifest.identity.clerk_subject), "Origin": origin,
        "X-Cosmas-Workspace-Protocol": "1", "X-Cosmas-Draft-Recovery": "2",
        "X-Cosmas-Practice-Access-Contract": "1", "X-Cosmas-Team-Contract": "2", "X-Cosmas-Model-Contract": "1"}
    c.wrong_headers = {**c.headers, "Authorization": "Bearer " + token("user_invented_other")}
    c.client = TestClient(api.app)
    original_request = c.client.request

    def request(*args, **kwargs):
        # Each request owns a fresh Session while sharing only the fixture's
        # outer rollback transaction, never another request's capture budget.
        c.session.commit()
        try:
            return original_request(*args, **kwargs)
        finally:
            c.session.expire_all()

    c.client.request = request
    try:
        setup = c.client.post("/practice-access/setup/complete", headers=c.headers, json={
            "idempotency_key": str(uuid4()), "practice_name": c.manifest.identity.clinic_display_name,
            "display_name": c.manifest.identity.owner_display_name, "confirm": True})
        assert setup.status_code == 200, setup.text
        seed_standalone_practice(c.session, c.config, c.manifest)
        team = c.client.post("/provider-team", headers=c.headers, json={"expected_revision": 0,
            "idempotency_key": "invented-chief-team", "configuration": provider_team.default_configuration()})
        assert team.status_code == 200, team.text
        assert team.json()["llm"]["enabled"]
        opened = c.client.post("/workspaces", headers=c.headers, json={
            "appointment_id": str(c.manifest.appointments[0].id), "idempotency_key": "invented-chief-visit"})
        assert opened.status_code == 200, opened.text
        c.path = "/workspaces/" + opened.json()["id"]
        note = c.client.post(c.path + "/entries", headers=c.headers, json={"expected_revision": 1,
            "idempotency_key": "invented-chief-notebook", "kind": "scratchpad",
            "content": "Invented plan: ask about preferred appointment times. Completion is not documented."})
        assert note.status_code == 200, note.text
        c.notebook = note.json()["workspace"]
        c.command = {"expected_revision": c.notebook["revision"], "team_revision": 1,
            "idempotency_key": "invented-chief-question", "role": "chief",
            "content": "Help me organize this note and draft a short plan for my review."}
        c.requests = []

        def install_http(handler):
            class SelectedConnector(GPT41Connector):
                def __init__(self, key, **kwargs):
                    kwargs["transport"] = httpx.MockTransport(handler)
                    super().__init__(key, **kwargs)
            monkeypatch.setattr(model_work, "GPT41Connector", SelectedConnector)
        c.install_http = install_http
        yield c
    finally:
        c.client.close()
        api.app.dependency_overrides = previous


def reply(c, request, *, extra=None):
    assert str(request.url) == MODEL_ORIGIN + "/openai/v1/chat/completions"
    body = json.loads(request.content)
    assert body["model"] == "gpt-4.1-dzus" and body["store"] is False and "tools" not in body
    schema = body["response_format"]["json_schema"]["schema"]
    assert "handoffs" not in schema["properties"]
    c.requests.append(body)
    value = {"answer": "Draft plan: ask about preferred times; no completion is documented.", "source_ids": []}
    value.update(extra or {})
    return httpx.Response(200, json={"model": "gpt-4.1", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(value)}}]})


def assert_no_external_work(c):
    for model in (WorkspaceHandoff, Operation, Ticket, CoreCaptureAccount):
        assert c.session.scalar(select(func.count()).select_from(model)) == 0
    assert c.calls == []


def disable_model(c):
    c.config.workspace_llm_backend = "disabled"
    c.config.workspace_llm_endpoint = ""
    c.config.standalone_model_origin_allowlist = ""
    c.config.workspace_llm_api_key = None
    c.config.validate_runtime_configuration()


def assert_prompt_retained_without_reply(c):
    entries = c.client.get(c.path, headers=c.headers).json()["entries"]
    assert entries[:-1] == c.notebook["entries"]
    assert entries[-1]["content"] == c.command["content"]
    assert entries[-1]["reply"] is None


def test_signed_owner_notes_chief_reply_and_exact_recovery_after_disable(chief):
    c = chief
    c.install_http(lambda request: reply(c, request))
    denied = c.client.post(c.path + "/conversation", headers=c.wrong_headers, json=c.command)
    assert denied.status_code == 403 and c.requests == []
    saved = c.client.post(c.path + "/conversation", headers=c.headers, json=c.command)
    assert saved.status_code == 200, saved.text
    assert saved.json()["outcome"] == "saved" and len(c.requests) == 1
    reopened = c.client.get(c.path, headers=c.headers)
    assert reopened.status_code == 200
    assert reopened.json()["entries"][-1]["reply"]["content"].startswith("Draft plan:")
    assert reopened.json()["entries"][0] == c.notebook["entries"][0]
    repeated = c.client.post(c.path + "/conversation", headers=c.headers, json=c.command)
    assert repeated.status_code == 200 and repeated.json() == saved.json()
    assert len(c.requests) == 1
    row = c.session.scalar(select(ModelWorkAdmission))
    assert row.prepared_envelope["flags"]["can_handoff"] is False
    assert row.prepared_envelope["context"]["handoff_roles"] == []
    disable_model(c)
    resolved = c.client.post(c.path + "/conversation/resolve", headers=c.headers, json=c.command)
    assert resolved.status_code == 200 and resolved.json() == saved.json()
    blocked = c.client.post(c.path + "/conversation", headers=c.headers, json=c.command)
    assert blocked.status_code == 403 and len(c.requests) == 1
    assert_no_external_work(c)


def test_uncertain_model_send_stays_recoverable_and_never_redispatches(chief):
    c = chief

    def timeout(request):
        c.requests.append(str(request.url))
        raise httpx.ReadTimeout("invented uncertain response", request=request)

    c.install_http(timeout)
    uncertain = c.client.post(c.path + "/conversation", headers=c.headers, json=c.command)
    assert uncertain.status_code == 409 and uncertain.json()["outcome"] == "unknown", uncertain.text
    for suffix in ("/conversation", "/conversation/resolve"):
        observed = c.client.post(c.path + suffix, headers=c.headers, json=c.command)
        assert observed.json() == uncertain.json()
    disable_model(c)
    resolved = c.client.post(c.path + "/conversation/resolve", headers=c.headers, json=c.command)
    assert resolved.status_code == 200 and resolved.json() == uncertain.json()
    assert len(c.requests) == 1
    assert_prompt_retained_without_reply(c)
    assert_no_external_work(c)


def test_model_cannot_request_handoffs_or_external_actions(chief):
    c = chief
    c.install_http(lambda request: reply(c, request, extra={"handoffs": [{"role": "follow_up", "brief": "Send it"}]}))
    rejected = c.client.post(c.path + "/conversation", headers=c.headers, json=c.command)
    assert rejected.status_code == 409 and rejected.json()["outcome"] == "failed", rejected.text
    assert len(c.requests) == 1
    assert_prompt_retained_without_reply(c)
    assert_no_external_work(c)


def test_explicit_google_service_status_and_callback_use_existing_actual_stack(chief, monkeypatch):
    c = chief
    calls = []

    class Google:
        return_origin = google_values()["google_connection_return_origin"]

        def status(self, identity, *, include_capabilities=False):
            assert identity.box_id == c.config.beta_box_id and include_capabilities
            calls.append("status")
            return {"state": "not_connected"}

        def callback(self, state, code, error):
            assert (state, code, error) == ("invented-state", "invented-code", False)
            calls.append("callback")
            return True

    monkeypatch.setattr(api.app.state, "google_connection", Google(), raising=False)
    path = "/connections/google/session"
    headers = {**c.headers, "X-Cosmas-Google-Connection": "1"}
    command = {"action": "status", "include_capabilities": True}
    assert c.client.post(path, headers=headers, json=command).status_code == 403
    assert calls == []
    for name, value in google_values().items():
        setattr(c.config, name, value)
    c.config.validate_runtime_configuration()
    status = c.client.post(path, headers=headers, json=command)
    assert status.status_code == 200 and status.json() == {"state": "not_connected"}
    callback = c.client.get("/connections/google/callback?state=invented-state&code=invented-code",
                            follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == Google.return_origin + "/#google-connected"
    assert callback.headers["referrer-policy"] == "no-referrer"
    assert calls == ["status", "callback"]
    assert_no_external_work(c)
