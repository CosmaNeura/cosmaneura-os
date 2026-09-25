"""Both immutable envelope generations pass the same real PG admission ledger."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.orm import Session
from tests.integration.test_model_work_admission import case, command, enabled  # noqa: F401

from cosmas_os.adapters.gpt41 import GPT41Connector
from cosmas_os.application import model_work as work
from cosmas_os.models import ModelWorkAdmission


@pytest.mark.usefixtures("enabled")
@pytest.mark.parametrize("version", ["v1", "v2"])
def test_saved_admission_can_claim_once_without_changing_its_prepared_version(engine, monkeypatch, version):
    box, owner, workspace, _ = case(engine)
    original_prepare = GPT41Connector.prepare
    if version == "v1":
        monkeypatch.setattr(GPT41Connector, "prepare", lambda self, ctx: self._prepare_value(
            ctx, contract="cosmas-gpt41-prepared.v1"))
    with Session(engine) as session:
        admission, _ = work.reserve_conversation(session, box, owner, workspace, **command())
        row = session.get(ModelWorkAdmission, admission)
        assert row is not None
        assert row.envelope_contract == f"cosmas-gpt41-prepared.{version}"
        saved_digest, saved_body = row.envelope_sha256, row.prepared_envelope["body"]
    # Simulate a new application process using current preparation defaults.
    monkeypatch.setattr(GPT41Connector, "prepare", original_prepare)
    with Session(engine) as session:
        claimed = work.claim(session, box, owner, admission)
        assert claimed is not None
        assert claimed.envelope_sha256 == saved_digest
        assert claimed.envelope["body"] == saved_body
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "gpt-4.1", "usage": {"prompt_tokens": 31, "completion_tokens": 9},
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
                {"answer": "Invented source-limited answer.", "source_ids": []})}}]})

    reply = GPT41Connector(lambda: "invented", transport=httpx.MockTransport(respond)).review_prepared(claimed.envelope)
    with Session(engine) as session:
        work.settle(session, claimed, reply)
        assert work.claim(session, box, owner, admission) is None
        observed = work.resolve_conversation(session, box, owner, workspace, **command())
        row = session.get(ModelWorkAdmission, admission)
        assert row is not None
        assert observed["outcome"] == "saved"
        assert row.envelope_sha256 == saved_digest and row.prepared_envelope["body"] == saved_body
    assert calls == [saved_body]


@pytest.mark.usefixtures("enabled")
@pytest.mark.parametrize("version", ["v1", "v2"])
def test_unknown_admission_is_not_reclaimed_under_new_preparation(engine, monkeypatch, version):
    box, owner, workspace, _ = case(engine)
    if version == "v1":
        monkeypatch.setattr(GPT41Connector, "prepare", lambda self, ctx: self._prepare_value(
            ctx, contract="cosmas-gpt41-prepared.v1"))
    at = datetime.now(UTC)
    with Session(engine) as session:
        admission, _ = work.reserve_conversation(session, box, owner, workspace, clock=lambda: at, **command())
        claimed = work.claim(session, box, owner, admission, clock=lambda: at + timedelta(seconds=1))
        assert claimed is not None
    with Session(engine) as session:
        later = at + timedelta(seconds=92)
        assert work.claim(session, box, owner, admission, clock=lambda: later) is None
        observed = work.resolve_conversation(session, box, owner, workspace, clock=lambda: later, **command())
        row = session.get(ModelWorkAdmission, admission)
        assert row is not None
        assert observed["outcome"] == "unknown"
        assert row.dispatch_id == claimed.dispatch_id and row.envelope_sha256 == claimed.envelope_sha256
        assert row.result_entry_id is None
