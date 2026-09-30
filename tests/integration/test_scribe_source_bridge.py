"""Signed HTTP, real disposable PostgreSQL, invented receiver/model transports."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration.test_workspace_capture import capture_case as _capture_case
from tests.unit.test_core_scribe_bridge import catalog_case, reviewed_fixture

from cosmas_os.application import (
    conversation,
    core_connection,
    core_workspace,
    handoffs,
    model_work,
)
from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.application.core_record_deadline import RecordDeadline
from cosmas_os.application.scribe_source import selection
from cosmas_os.models import (
    CoreCaptureAccount,
    EncounterWorkspace,
    ExternalIdentity,
    PatientLink,
    Principal,
    WorkspaceEntry,
)
from cosmas_os.ports.bot_capabilities import BotReply, ConnectorUnavailable, DraftBrief
from cosmas_os.ports.creator_review import ProviderEncounter

capture_case = _capture_case


def require_row[T](session: Session, model: type[T], identity) -> T:
    row = session.get(model, identity)
    assert row is not None
    return row


@pytest.fixture
def bridge(capture_case):
    f = capture_case
    f.view = reviewed_fixture("Invented walk-in discussion. " * 280)
    f.base = f"/workspaces/{f.workspace['id']}"
    f.headers = {"Authorization": "Bearer " + f.token(), "X-Cosmas-Model-Contract": "1"}

    def existing(binding, credential, key):
        f.port.step("provider_encounter")
        return ProviderEncounter(schema_version="1.0", status="available", review=f.view)

    f.port.provider_encounter = existing
    selected = selection(f.view)
    assert selected is not None
    f.body = {
        "expected_revision": 1,
        "idempotency_key": "invented-reviewed-source",
        "selection": selected.model_dump(mode="json"),
        "reviewed": True,
        "share_with_team": True,
    }
    return f


def post(f, body=None):
    return f.client.post(f.base + "/capture/source-packets", headers=f.headers, json=body or f.body)


def evidence(f):
    with Session(f.engine) as s:
        return list(
            s.scalars(
                select(WorkspaceEntry)
                .where(
                    WorkspaceEntry.workspace_id == f.workspace["id"],
                    WorkspaceEntry.kind == "evidence",
                )
                .order_by(WorkspaceEntry.revision)
            )
        )


def test_existing_recording_read_and_multipart_save_keep_original_session_and_replay_without_core(
    bridge,
):
    f = bridge
    for _ in range(2):
        result = f.client.post(
            f.base + "/capture/existing",
            headers=f.headers,
            json={"idempotency_key": "invented-read-existing"},
        )
        assert result.status_code == 200, result.text
        assert result.json()["selection"] == f.body["selection"]
        assert result.json()["review"]["session_id"] == str(f.view.session_id)
    saved = post(f)
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert len(result["entries"]) >= 2
    assert result["workspace"]["model_contract_version"] == 1
    assert result["workspace"]["model_observed_at"]
    rows = evidence(f)
    assert len(rows) == len(result["entries"]) and all(len(row.content) <= 5000 for row in rows)
    combined = "".join(row.content.split("\n", 1)[1] for row in rows)
    assert f.view.working.segments[0].content in combined
    assert (
        "continuity is unconfirmed" in combined
        and f.body["selection"]["snapshot_sha256"] in combined
    )
    assert f.port.calls == ["exchange", "resolve", "binding", "provider_encounter"] * 3
    with Session(f.engine) as s:
        ws.append(
            s,
            f.box,
            f.actor,
            f.workspace["id"],
            expected=result["entry_revision"],
            key="later-invented-note",
            kind="scratchpad",
            content="Invented later note",
            source_label=None,
        )

    def unavailable(*_):
        pytest.fail("Committed replay must not consult Core")

    f.port.exchange_context = unavailable
    replay = post(f)
    assert replay.status_code == 200, replay.text
    assert replay.json()["entries"] == result["entries"]
    assert replay.json()["workspace"]["revision"] == result["entry_revision"]
    assert len(evidence(f)) == len(rows)
    conflict = post(f, {**f.body, "expected_revision": result["entry_revision"]})
    assert conflict.status_code == 409 and conflict.json()["detail"] == "idempotency_conflict"


def test_new_intent_cannot_duplicate_an_already_saved_source_packet(bridge):
    f = bridge
    saved = post(f)
    assert saved.status_code == 200, saved.text
    result = post(
        f,
        {
            **f.body,
            "idempotency_key": "invented-new-intent",
            "expected_revision": saved.json()["entry_revision"],
        },
    )
    assert result.status_code == 409 and result.json()["detail"] == "scribe_source_already_saved"
    assert len(evidence(f)) == len(saved.json()["entries"])


@pytest.mark.parametrize(
    "target", ["expired_token", "foreign_owner", "identity", "principal", "patient"]
)
def test_saved_packet_replay_still_requires_current_human_and_local_authority(bridge, target):
    f = bridge
    assert post(f).status_code == 200
    calls = list(f.port.calls)
    if target == "expired_token":
        f.headers["Authorization"] = "Bearer " + f.token(exp=datetime(2020, 1, 1, tzinfo=UTC))
    elif target == "foreign_owner":
        f.headers["Authorization"] = "Bearer " + f.token(sub="invented-foreign-owner")
    else:
        with Session(f.engine) as s:
            if target == "identity":
                require_row(s, ExternalIdentity, f.identity_id).active = False
            elif target == "principal":
                require_row(s, Principal, f.actor).state = "suspended"
            else:
                require_row(s, PatientLink, f.patient_link_id).revoked_at = datetime.now(UTC)
            s.commit()
    result = post(f)
    assert result.status_code in {401, 403, 404}, result.text
    assert f.port.calls == calls
    assert "snapshot_sha256" not in result.text


@pytest.mark.parametrize("target", ["selection", "reviewed", "share_with_team", "version"])
def test_changed_same_key_payload_or_unchecked_review_cannot_recover_or_save(bridge, target):
    f = bridge
    assert post(f).status_code == 200
    calls = list(f.port.calls)
    if target == "selection":
        f.body["selection"]["session_id"] = str(uuid4())
    elif target == "version":
        f.body["selection"]["version"] = True
    else:
        f.body[target] = 1
    result = post(f)
    assert result.status_code == (409 if target == "selection" else 422), result.text
    assert f.port.calls == calls


@pytest.mark.parametrize(
    "target", ["source", "continuity", "consent", "identity", "account", "patient"]
)
def test_changed_source_or_current_authority_never_saves(bridge, target):
    f = bridge
    if target == "source":
        f.view = reviewed_fixture("Different invented transcript")
    elif target == "continuity":
        f.view = f.view.model_copy(update={"capture_continuity": None})
    elif target == "consent":

        def denied(*_):
            f.port.step("provider_encounter")
            raise ConnectorUnavailable("capture_consent_required")

        f.port.provider_encounter = denied
    else:

        def revoke(phase):
            if phase != "provider_encounter":
                return
            with Session(f.engine) as s:
                if target == "identity":
                    require_row(s, ExternalIdentity, f.identity_id).active = False
                elif target == "account":
                    require_row(s, CoreCaptureAccount, f.account_id).revoked_at = datetime.now(UTC)
                else:
                    require_row(s, PatientLink, f.patient_link_id).revoked_at = datetime.now(UTC)
                s.commit()

        f.port.after = revoke
    result = post(f)
    assert result.status_code in {403, 404, 409, 503}, result.text
    assert not evidence(f)
    assert "admit" not in f.port.calls


@pytest.mark.parametrize("field", ["workspace_id", "actor_ref", "tenant_ref", "appointment_ref"])
def test_binding_scope_mismatch_stops_before_original_session_read(bridge, field):
    f = bridge
    resolve = f.port.resolve_binding

    def wrong(selected, credential):
        binding = resolve(selected, credential)
        changed = uuid4() if field == "workspace_id" else getattr(binding, field)[:-1] + "2"
        return binding.model_copy(update={field: changed})

    f.port.resolve_binding = wrong
    result = post(f)
    assert result.status_code == 409 and result.json()["detail"] == "capture_context_changed", (
        result.text
    )
    assert f.port.calls == ["exchange", "resolve", "binding"] and not evidence(f)


def test_partway_database_failure_rolls_back_every_packet_part(bridge):
    f = bridge

    def fail_after_insert(_mapper, _connection, row):
        if row.workspace_id == f.workspace["id"] and row.kind == "evidence":
            raise ws.WorkspaceError("invented_database_failure", 409)

    event.listen(WorkspaceEntry, "after_insert", fail_after_insert)
    try:
        result = post(f)
        assert result.status_code == 409, result.text
    finally:
        event.remove(WorkspaceEntry, "after_insert", fail_after_insert)
    assert not evidence(f)
    with Session(f.engine) as s:
        assert require_row(s, EncounterWorkspace, f.workspace["id"]).revision == 1
    assert post(f).status_code == 200


def test_chief_and_research_receive_all_saved_parts_and_later_crowding_blocks_model(
    bridge, monkeypatch
):
    f = bridge
    f.configuration.workspace_llm_backend = "azure_gpt41"
    f.configuration.workspace_llm_api_key = SecretStr("invented-no-network")
    for module in (team, conversation, handoffs):
        monkeypatch.setattr(module, "runtime_settings", f.configuration)
    calls = []
    research_id = str(uuid4())

    def answer(claim):
        context = claim.envelope["context"]
        calls.append(context)
        return BotReply(
            "Invented private draft.",
            (),
            "azure_gpt41",
            20,
            7,
            handoffs=(
                DraftBrief(research_id, "Review the invented saved transcript for open questions.", REQUIREMENTS),
            )
            if context["role"] == "chief"
            else (),
        )

    monkeypatch.setattr(model_work, "dispatch_claim", answer)
    with Session(f.engine) as s:
        configuration = team.default_configuration()
        configuration["bots"].append(
            {"role": "research", "name": "Research", "enabled": True, "instance_id": research_id}
        )
        config = team.save(
            s, f.box, f.actor, expected=0, key="invented-team", configuration=configuration
        )
        ws.append(
            s,
            f.box,
            f.actor,
            f.workspace["id"],
            expected=1,
            key="prior-note",
            kind="scratchpad",
            content="Invented existing notebook context",
            source_label=None,
        )
        ws.append(
            s,
            f.box,
            f.actor,
            f.workspace["id"],
            expected=2,
            key="prior-evidence",
            kind="evidence",
            content="Invented prior source",
            source_label="Invented source",
        )
    f.body["expected_revision"] = 3
    saved = post(f)
    assert saved.status_code == 200, saved.text
    result = f.client.post(
        f.base + "/conversation",
        headers=f.headers,
        json={
            "expected_revision": saved.json()["entry_revision"],
            "team_revision": config["revision"],
            "idempotency_key": "invented-chief",
            "role": "chief",
            "content": "Ask Research to review the saved source.",
        },
    )
    assert result.status_code == 200 and result.json()["outcome"] == "saved", result.text

    @contextmanager
    def sessions():
        with Session(f.engine) as s:
            yield s

    assert handoffs.process_next(sessions)
    assert len(calls) == 2
    packet_ids = {item["entry_id"] for item in saved.json()["entries"]}
    for context in calls:
        assert packet_ids <= {source["entry_id"] for source in context["sources"]}
        assert "continuity is unconfirmed" in "".join(
            source["content"] for source in context["sources"]
        )
    with Session(f.engine) as s:
        snapshot = ws.read(s, f.box, f.actor, f.workspace["id"])
        for i in range(12):
            item = ws.append(
                s,
                f.box,
                f.actor,
                f.workspace["id"],
                expected=snapshot["revision"] + i,
                key=f"later-source-{i}",
                kind="evidence",
                content="Invented later evidence",
                source_label="Later",
            )
        revision = item["entry_revision"]
    blocked = f.client.post(
        f.base + "/conversation",
        headers=f.headers,
        json={
            "expected_revision": revision,
            "team_revision": config["revision"],
            "idempotency_key": "invented-crowded-chief",
            "role": "chief",
            "content": "Review all sources.",
        },
    )
    assert (
        blocked.status_code == 422 and blocked.json()["detail"] == "scribe_source_context_too_large"
    ), blocked.text
    assert len(calls) == 2


@pytest.mark.parametrize("existing", [False, True, "conflict"])
def test_new_notebook_uses_original_canonical_id_and_existing_notebook_is_never_rekeyed(
    bridge, existing
):
    f = bridge
    discovery, row = catalog_case()
    identity = SimpleNamespace(
        box_id=f.box, principal_id=f.actor, external_identity_id=f.identity_id
    )
    canonical = row["workspace_id"]
    with Session(f.engine) as s:
        account = require_row(s, CoreCaptureAccount, f.account_id)
        account.core_actor_ref = discovery.connection.actor_ref
        account.core_tenant_ref = discovery.connection.tenant_ref
        s.commit()
        original = None
        if existing is True:
            original = core_workspace.open_selected(
                s, identity=identity, account=account, discovery=discovery, budget=RecordDeadline()
            )
        if existing == "conflict":
            canonical = f.workspace["id"]
        calls = []

        class Core:
            def read(self, request, bearer):
                calls.append("read")
                return discovery

            def scribe_workspace(self, observed, bearer):
                calls.append("catalog")
                return canonical

        command = core_connection.ConnectionCommand(
            action="open",
            request_nonce=uuid4(),
            connection_sha256=discovery.connection.connection_sha256,
            appointment_ref=discovery.encounters[0].appointment.appointment_ref,
            source_sha256=discovery.encounters[0].source_sha256,
        )
        kwargs = dict(
            identity=identity,
            command=command,
            tenant_ref=account.core_tenant_ref,
            bearer=SecretStr("invented-human"),
            port=Core(),
            reauthenticate=lambda: None,
            budget=RecordDeadline(),
        )
        if existing == "conflict":
            with pytest.raises(ws.WorkspaceError, match="core_existing_recording_conflict"):
                core_connection.execute(s, **kwargs)
            s.rollback()
        else:
            result = core_connection.execute(s, **kwargs)
            assert result["workspace"]["workspace_id"] == (
                original["workspace_id"] if original else canonical
            )
            assert calls == (["read"] if original else ["read", "catalog"])
        assert require_row(s, EncounterWorkspace, f.workspace["id"]).revision == 1
