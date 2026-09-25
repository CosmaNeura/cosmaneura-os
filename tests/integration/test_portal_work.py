"""Actual PostgreSQL and private PDF custody for explicitly installed portal work."""

from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Table, text
from sqlalchemy.exc import DBAPIError
from starlette.concurrency import run_in_threadpool
from tests.integration.test_vendor_artifact_ledger import PDF, _case
from tests.integration.test_vendor_artifact_ledger import request as artifact_request
from tests.unit.test_vendor_portal_contract import SyntheticInMemoryPortal, selection

from cosmas_os.adapters.vendor_artifacts import LocalVendorArtifactStore
from cosmas_os.adapters.vendor_connectors.portals import (
    PRODUCTION_PORTALS,
    PortalBinding,
    PortalRegistry,
)
from cosmas_os.api import app as api
from cosmas_os.api import portal_setup_schemas as setup_schema
from cosmas_os.api import portal_work_routes
from cosmas_os.api import portal_work_schemas as p
from cosmas_os.api.vendor_work_schemas import public_digest
from cosmas_os.application import note_review as notes
from cosmas_os.application import portal_setup as setup
from cosmas_os.application import portal_work as flow
from cosmas_os.application import portal_work_execution as execution
from cosmas_os.application import services
from cosmas_os.application import vendor_artifacts as custody
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.domain.rules import AuthorizationError
from cosmas_os.models import EncounterWorkspace, Operation, Principal
from cosmas_os.portal_work_models import PortalWorkObservation, PortalWorkReceipt
from cosmas_os.ports import vendor_connectors as private
from cosmas_os.vendor_models import VendorArtifact

POLICY = flow.PortalWorkPolicy(True, True)


class SyntheticPortal(SyntheticInMemoryPortal):
    def __init__(self):
        super().__init__()
        self.enabled = True
        self.current_authority = True
        self.state = "pending"

    async def observe(self, command, reference):
        prior = await super().observe(command, reference)
        return prior.model_copy(update={"state": self.state, "observed_at": datetime.now(UTC)})


@pytest.fixture(autouse=True)
def gates(monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    monkeypatch.setattr(settings, "portal_setup_enabled", True)


@pytest.fixture
def portal_case(session, seeded, tmp_path):
    c = _case(session, seeded)
    s = session
    request = artifact_request(c)
    first = custody.intent(s, c["box"], c["owner"], c["wid"], request)
    admission = custody.begin_content(
        s, c["box"], c["owner"], c["wid"], request.artifact_id, "portal-pdf-content"
    )
    store = LocalVendorArtifactStore(tmp_path / "documents")
    assert admission.token
    assert custody.write_content(store, admission.token, PDF) == "ready"
    assert custody.settle_in_session(s, admission.token, "ready") == "settled"
    s.commit()
    adapter = SyntheticPortal()
    chosen = selection().model_copy(
        update={"connection_id": uuid4(), "box_id": UUID(c["box"]), "owner_id": UUID(c["owner"])}
    )
    registry = PortalRegistry((PortalBinding(adapter.profile, adapter),))
    catalog = setup.Catalog(
        registry, (setup.Installation(chosen, adapter.profile, "Invented operational portal"),)
    )
    proposal = setup_schema.Proposal(
        connection_id=str(uuid4()),
        expected_version=0,
        idempotency_key="portal-setup-" + str(uuid4()),
        installation_id=str(chosen.connection_id),
        profile_sha256=adapter.profile.commitment(),
        configuration_sha256=chosen.configuration_sha256,
        capabilities=["document.upload", "referral.submit", "referral.read"],
        mappings=setup_schema.Mappings(
            patient_link_id=c["link"],
            practice_reference="synthetic_practice",
            patient_reference="invented_patient",
            recipient_reference="invented_specialist",
            practice_label="Invented practice",
            recipient_label="Invented specialist",
        ),
    )
    setup.propose(s, c["box"], c["owner"], proposal, catalog)
    d = setup.detail(s, c["box"], c["owner"], proposal.connection_id, catalog)
    setup.command(
        s,
        c["box"],
        c["owner"],
        "activate",
        setup_schema.Activation(
            connection_id=d["connection_id"],
            revision_id=d["revision_id"],
            expected_version=d["version"],
            review_sha256=d["review_sha256"],
            idempotency_key="portal-activate-" + str(uuid4()),
            reviewed_profile=True,
            reviewed_practice=True,
            reviewed_patient=True,
            reviewed_recipient=True,
            confirm_local_activation=True,
        ),
        catalog,
    )
    d = setup.detail(s, c["box"], c["owner"], proposal.connection_id, catalog)
    return {
        **c,
        "catalog": catalog,
        "adapter": adapter,
        "store": store,
        "setup": d,
        "document": first["artifact"]["document"],
    }


def proposal(s, c, **changes):
    return p.Proposal.model_validate(
        {
            "expected_workspace_revision": s.get(EncounterWorkspace, c["wid"]).revision,
            "proposed_operation_id": str(uuid4()),
            "idempotency_key": "portal-propose-" + str(uuid4()),
            "action": "document.upload",
            "setup": {
                k: c["setup"][k]
                for k in ["connection_id", "revision_id", "version", "review_sha256"]
            },
            "source": c["source"],
            "document": c["document"],
            "due_date": "2026-09-30",
            "expected_outcome": "Exact reviewed document accepted by selected portal.",
            **changes,
        }
    )


def call(s, c, f, *args, **kwargs):
    return f(s, c["box"], c["owner"], c["wid"], *args, **kwargs)


def detail(s, c, tid):
    return call(s, c, flow.detail, tid)


def bound(d) -> dict[str, Any]:
    return {
        **{k: d[k] for k in ["revision_id", "operation_id", "payload_hash"]},
        "expected_version": d["version"],
        "idempotency_key": "portal-command-" + str(uuid4()),
    }


def approve(s, c, tid):
    d = detail(s, c, tid)
    return call(
        s,
        c,
        flow.local_command,
        tid,
        "decide",
        p.Decision(
            **bound(d),
            review_sha256=d["review_sha256"],
            choice="approve",
            reviewed_document=True,
            reviewed_mapping=True,
            reviewed_action=True,
        ),
        catalog=c["catalog"],
        policy=POLICY,
    )


def create(s, c, **changes):
    req = proposal(s, c, **changes)
    r = call(s, c, flow.propose, req, catalog=c["catalog"], policy=POLICY)
    return r["effect"]["ticket_id"], req, r


async def submit(s, c, tid):
    d = detail(s, c, tid)
    req = p.Bound(**bound(d))
    receipt, inv = call(
        s, c, execution.claim, tid, "submit", req, catalog=c["catalog"], policy=POLICY
    )
    assert inv
    assert execution.mark(s, inv, catalog=c["catalog"], policy=POLICY)
    command = inv.command
    data = None
    if isinstance(command.intent, private.PortalDocumentIntent):
        data = PDF
    prepared = c["catalog"].registry.prepare(command, data)
    observation = await c["adapter"].submit(prepared, inv.approval)
    execution.settle(s, inv, observation=observation)
    return req, receipt, inv


async def read_status(s, c, tid, state):
    c["adapter"].state = state
    d = detail(s, c, tid)
    receipt, inv = call(
        s,
        c,
        execution.claim,
        tid,
        "status",
        p.Bound(**bound(d)),
        catalog=c["catalog"],
        policy=POLICY,
    )
    assert inv
    assert execution.mark(s, inv, catalog=c["catalog"], policy=POLICY)
    observation = await c["adapter"].observe(inv.command, inv.reference)
    execution.settle(s, inv, observation=observation)
    return receipt, inv


def result(
    s,
    c,
    tid,
    disposition: Literal[
        "verified_in_portal", "reported_exception", "unable_to_establish"
    ] = "verified_in_portal",
):
    d = detail(s, c, tid)
    return call(
        s,
        c,
        flow.local_command,
        tid,
        "result",
        p.Result(
            **bound(d),
            observation_head=d["observation_head"],
            evidence_sha256=d["evidence_sha256"],
            disposition=disposition,
            evidence="Invented owner checked the exact portal outcome.",
        ),
    )


def verify(s, c, tid):
    d = detail(s, c, tid)
    r = d["latest_result"]
    return call(
        s,
        c,
        flow.local_command,
        tid,
        "verify",
        p.Verify(
            **bound(d),
            observation_head=d["observation_head"],
            evidence_sha256=d["evidence_sha256"],
            result_receipt_id=r["effect"]["receipt_id"],
            result_receipt_sha256=r["receipt_sha256"],
            reviewed_result=True,
            reviewed_observations=True,
            outcome_confirmed=True,
        ),
    )


@pytest.mark.asyncio
async def test_exact_document_upload_then_separately_approved_referral_completion(
    session, portal_case
):
    s, c = session, portal_case
    tid, req, first = create(s, c)
    assert call(s, c, flow.propose, req, catalog=c["catalog"], policy=POLICY) == first
    assert c["adapter"].effects == []
    approve(s, c, tid)
    assert c["adapter"].effects == []
    sent, receipt, inv = await submit(s, c, tid)
    assert (
        detail(s, c, tid)["acceptance"] == "accepted"
        and detail(s, c, tid)["verification"] == "pending"
    )
    replay, again = call(
        s, c, execution.claim, tid, "submit", sent, catalog=c["catalog"], policy=POLICY
    )
    assert replay == receipt and again is None
    with pytest.raises(ws.WorkspaceError):
        call(
            s,
            c,
            execution.claim,
            tid,
            "submit",
            p.Bound(**bound(detail(s, c, tid))),
            catalog=c["catalog"],
            policy=POLICY,
        )
    result(s, c, tid)
    verify(s, c, tid)
    assert detail(s, c, tid)["state"] == "closed"
    referral, _, _ = create(
        s,
        c,
        action="referral.submit",
        summary="Invented referral summary reviewed by owner.",
        uploaded_operation_id=str(inv.command.operation_id),
        expected_outcome="The selected specialist receives the exact referral.",
    )
    assert len(c["adapter"].effects) == 1
    approve(s, c, referral)
    await submit(s, c, referral)
    result(s, c, referral)
    with pytest.raises(ws.WorkspaceError, match="exception_unresolved"):
        verify(s, c, referral)
    await read_status(s, c, referral, "received")
    result(s, c, referral)
    verify(s, c, referral)
    d = detail(s, c, referral)
    assert (
        d["state"] == "closed"
        and d["verification"] == "verified"
        and len(c["adapter"].effects) == 2
    )
    assert PRODUCTION_PORTALS._bindings == {}


@pytest.mark.asyncio
async def test_later_unknown_or_contradictory_status_reopens_retained_completion(
    session, portal_case
):
    s, c = session, portal_case
    upload, _, _ = create(s, c)
    approve(s, c, upload)
    _, _, inv = await submit(s, c, upload)
    tid, _, _ = create(
        s,
        c,
        action="referral.submit",
        summary="Invented referral",
        uploaded_operation_id=str(inv.command.operation_id),
    )
    approve(s, c, tid)
    await submit(s, c, tid)
    await read_status(s, c, tid, "received")
    result(s, c, tid)
    verified = verify(s, c, tid)
    await read_status(s, c, tid, "unknown")
    assert detail(s, c, tid)["state"] == "approved"
    result(s, c, tid)
    with pytest.raises(ws.WorkspaceError, match="exception_unresolved"):
        verify(s, c, tid)
    await read_status(s, c, tid, "received")
    result(s, c, tid)
    verify(s, c, tid)
    await read_status(s, c, tid, "declined")
    assert detail(s, c, tid)["conflicting_evidence"] and detail(s, c, tid)["state"] == "approved"
    assert (
        call(
            s,
            c,
            flow.resolve,
            p.Resolve(
                command_kind="verify",
                idempotency_key=verified["idempotency_key"],
                request_sha256=verified["request_sha256"],
            ),
        )
        == verified
    )


@pytest.mark.parametrize("change", ["note", "artifact", "mapping", "policy"])
def test_current_source_mapping_custody_and_gate_fence_before_approval(
    session, portal_case, change
):
    s, c = session, portal_case
    tid, _, _ = create(s, c)
    if change == "note":
        notes.save(
            s,
            c["box"],
            c["owner"],
            c["wid"],
            expected=s.get(EncounterWorkspace, c["wid"]).revision,
            key="changed-portal-source",
            base_note_id=c["source"]["note_id"],
            source_reply_id=None,
            content="Changed invented source.",
        )
    elif change == "artifact":
        artifact = s.get(VendorArtifact, c["document"]["artifact_id"])
        artifact.state = "quarantined"
        artifact.version += 1
        s.commit()
    elif change == "mapping":
        d = c["setup"]
        setup.command(
            s,
            c["box"],
            c["owner"],
            "disable",
            setup_schema.Disable(
                connection_id=d["connection_id"],
                revision_id=d["revision_id"],
                expected_version=d["version"],
                review_sha256=d["review_sha256"],
                idempotency_key="disable-current-mapping",
                confirm_disable=True,
            ),
            c["catalog"],
        )
    if change == "policy":
        d = detail(s, c, tid)
        with pytest.raises(ws.WorkspaceError):
            call(
                s,
                c,
                flow.local_command,
                tid,
                "decide",
                p.Decision(
                    **bound(d),
                    review_sha256=d["review_sha256"],
                    choice="approve",
                    reviewed_document=True,
                    reviewed_mapping=True,
                    reviewed_action=True,
                ),
                catalog=c["catalog"],
            )
    else:
        with pytest.raises(ws.WorkspaceError):
            approve(s, c, tid)
    assert (
        s.get(Operation, detail(s, c, tid)["operation_id"]) is None and c["adapter"].effects == []
    )


def test_referral_cannot_reference_missing_or_unaccepted_upload(session, portal_case):
    s, c = session, portal_case
    tid, _, _ = create(s, c)
    approve(s, c, tid)
    with pytest.raises(ws.WorkspaceError):
        create(
            s,
            c,
            action="referral.submit",
            summary="Invented referral",
            uploaded_operation_id=detail(s, c, tid)["operation_id"],
        )
    assert c["adapter"].effects == []


def test_spent_unconfirmed_claim_never_automatically_retries_or_closes(session, portal_case):
    s, c = session, portal_case
    tid, _, _ = create(s, c)
    approve(s, c, tid)
    request = p.Bound(**bound(detail(s, c, tid)))
    receipt, inv = call(
        s, c, execution.claim, tid, "submit", request, catalog=c["catalog"], policy=POLICY
    )
    assert inv
    replay, again = call(
        s, c, execution.claim, tid, "submit", request, catalog=c["catalog"], policy=POLICY
    )
    assert replay == receipt and again is None
    execution.settle(s, inv, failure=private.VendorError("transport_unconfirmed", attempted=True))
    assert detail(s, c, tid)["state"] == "approved" and detail(s, c, tid)["acceptance"] == "unknown"
    result(s, c, tid)
    with pytest.raises(ws.WorkspaceError):
        verify(s, c, tid)
    with pytest.raises(ws.WorkspaceError):
        call(
            s,
            c,
            execution.claim,
            tid,
            "submit",
            p.Bound(**bound(detail(s, c, tid))),
            catalog=c["catalog"],
            policy=POLICY,
        )
    assert c["adapter"].effects == []


def test_other_provider_and_legacy_paths_cannot_view_or_mutate_portal_work(session, portal_case):
    s, c = session, portal_case
    tid, _, _ = create(s, c)
    peer = Principal(box_id=c["box"], principal_type="human", display_name="Invented peer")
    s.add(peer)
    s.commit()
    with pytest.raises(ws.WorkspaceError):
        flow.detail(s, c["box"], peer.id, c["wid"], tid)
    container = services.Container(s)
    assert tid not in [row["id"] for row in services.list_queue(container, c["box"])]
    with pytest.raises(AuthorizationError):
        services.audit_timeline(container, c["box"], tid)
    with pytest.raises(AuthorizationError):
        services.edit_revision(container, tid, c["owner"], "Not an authorized portal edit")


@pytest.mark.parametrize("field", ["reviewed_document", "reviewed_mapping", "reviewed_action"])
def test_review_flags_require_literal_true(field):
    value = {
        "expected_version": 1,
        "revision_id": str(uuid4()),
        "operation_id": str(uuid4()),
        "payload_hash": "a" * 64,
        "idempotency_key": "review-flags-test",
        "review_sha256": "b" * 64,
        "choice": "approve",
        "reviewed_document": True,
        "reviewed_mapping": True,
        "reviewed_action": True,
    }
    value[field] = False
    with pytest.raises(ValidationError):
        p.Decision.model_validate(value)


def test_direct_sql_cannot_forge_closure_or_rewrite_review_or_claim(session, portal_case):
    s, c = session, portal_case
    tid, _, _ = create(s, c)
    approve(s, c, tid)
    with pytest.raises(DBAPIError), s.begin_nested():
        s.execute(
            text(
                "UPDATE tickets SET state='closed',closed_at=clock_timestamp(),version=version+1 WHERE id=:id"
            ),
            {"id": tid},
        )
        s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    with pytest.raises(DBAPIError), s.begin_nested():
        s.execute(
            text("UPDATE portal_work SET review_sha256=:sha WHERE ticket_id=:id"),
            {"id": tid, "sha": "0" * 64},
        )
    _, inv = call(
        s,
        c,
        execution.claim,
        tid,
        "submit",
        p.Bound(**bound(detail(s, c, tid))),
        catalog=c["catalog"],
        policy=POLICY,
    )
    assert inv
    with pytest.raises(DBAPIError), s.begin_nested():
        s.execute(text("DELETE FROM portal_work_claims WHERE id=:id"), {"id": inv.claim_id})


def test_real_routes_negotiate_closed_body_and_exact_recovery_without_runtime(session, portal_case):
    s, c = session, portal_case
    app = FastAPI()
    portal_work_routes.register(app, api.get_session, api._identity)
    app.dependency_overrides[api.get_session] = lambda: s
    app.dependency_overrides[portal_work_routes.default_policy] = lambda: POLICY
    app.dependency_overrides[portal_work_routes.portal_setup_routes.installed_catalog] = lambda: c[
        "catalog"
    ]
    headers = {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": c["owner"],
        "X-Cosmas-Portal-Work-Contract": "1",
    }
    with TestClient(app) as client:
        path = "/workspaces/" + c["wid"] + "/portal-work"
        request = proposal(s, c).public()
        first = client.post(path, headers=headers, json=request)
        assert first.status_code == 200, first.text
        exact = first.json()
        resolve = {k: exact[k] for k in ["command_kind", "idempotency_key", "request_sha256"]}
        assert client.post(path + "/resolve", headers=headers, json=resolve).json() == exact
        assert (
            client.post(
                path, headers=headers, json={**request, "url": "https://unreviewed.invalid"}
            ).status_code
            == 422
        )
        assert client.get(path + "?unknown=true", headers=headers).status_code == 426
        tid = exact["effect"]["ticket_id"]
        d = client.get(path + "/" + tid, headers=headers).json()
        assert (
            client.post(
                path + "/" + tid + "/submit", headers=headers, json=p.Bound(**bound(d)).public()
            ).status_code
            == 403
        )
        assert c["adapter"].effects == []


def test_routes_use_current_note_boundary_and_replay_without_current_services(session, portal_case):
    s, c = session, portal_case
    app, calls, unavailable = FastAPI(), [], False

    async def current_note(request, wid, session, identity, port, apply, *, note_id):
        assert str(wid) == c["wid"] and note_id == c["source"]["note_id"]
        assert identity.principal_id == c["owner"] and port == "invented-core-port"
        calls.append(note_id)
        if unavailable:
            raise ws.WorkspaceError("core_note_check_required", 409)
        return await run_in_threadpool(apply, None)

    class ClaimedOnly:
        async def invoke(self, inv, *, deadline):
            # Simulate a process stopping after durable admission, before provider I/O.
            assert inv and deadline

    def claimed_runtime():
        return ClaimedOnly()

    portal_work_routes.register(
        app,
        api.get_session,
        api._identity,
        execution_dependency=claimed_runtime,
        current_core_note=current_note,
        core_connection=lambda: "invented-core-port",
    )
    app.dependency_overrides[api.get_session] = lambda: s
    app.dependency_overrides[portal_work_routes.default_policy] = lambda: POLICY
    app.dependency_overrides[portal_work_routes.portal_setup_routes.installed_catalog] = lambda: c[
        "catalog"
    ]
    headers = {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": c["owner"],
        "X-Cosmas-Portal-Work-Contract": "1",
    }
    path = "/workspaces/" + c["wid"] + "/portal-work"
    with TestClient(app) as client:
        request = proposal(s, c).public()
        first = client.post(path, headers=headers, json=request)
        assert first.status_code == 200, first.text
        assert client.post(path, headers=headers, json=request).json() == first.json()
        tid = first.json()["effect"]["ticket_id"]
        d = detail(s, c, tid)
        approval = p.Decision(
            **bound(d),
            review_sha256=d["review_sha256"],
            choice="approve",
            reviewed_document=True,
            reviewed_mapping=True,
            reviewed_action=True,
        ).public()
        approved = client.post(path + "/" + tid + "/decide", headers=headers, json=approval)
        assert approved.status_code == 200, approved.text
        send = p.Bound(**bound(detail(s, c, tid))).public()
        admitted = client.post(path + "/" + tid + "/submit", headers=headers, json=send)
        assert admitted.status_code == 200, admitted.text
        assert len(calls) == 3
        unavailable = True
        app.dependency_overrides[claimed_runtime] = lambda: None
        assert (
            client.post(path + "/" + tid + "/submit", headers=headers, json=send).json()
            == admitted.json()
        )
        assert (
            client.post(path + "/" + tid + "/decide", headers=headers, json=approval).json()
            == approved.json()
        )
        assert len(calls) == 3 and c["adapter"].effects == []
        fresh = client.post(path, headers=headers, json=proposal(s, c).public())
        assert fresh.status_code == 409
        assert len(calls) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        {"reviewed_result": False},
        {"reviewed_observations": 1},
        {"outcome_confirmed": "true"},
        {"result_receipt_id": str(uuid4())},
        {"result_receipt_sha256": "0" * 64},
        {"evidence_sha256": "0" * 64},
        {"observation_head": {"sequence": 0, "sha256": "0" * 64}},
    ],
)
async def test_direct_sql_verify_rehash_cannot_bypass_exact_review_or_evidence(
    session, portal_case, changed
):
    s, c = session, portal_case
    tid, _, _ = create(s, c)
    approve(s, c, tid)
    await submit(s, c, tid)
    original_result = result(s, c, tid)
    d = detail(s, c, tid)
    request = {
        **bound(d),
        "observation_head": d["observation_head"],
        "evidence_sha256": d["evidence_sha256"],
        "result_receipt_id": original_result["effect"]["receipt_id"],
        "result_receipt_sha256": original_result["receipt_sha256"],
        "reviewed_result": True,
        "reviewed_observations": True,
        "outcome_confirmed": True,
        **changed,
    }
    rid, now = str(uuid4()), datetime.now(UTC)
    request_sha = public_digest(
        "cosmas-portal-work-request.v1",
        {
            "scope": {"kind": "workspace", "id": c["wid"]},
            "command_kind": "verify",
            "request": request,
        },
    )
    response = {
        **{k: v for k, v in original_result.items() if k != "receipt_sha256"},
        "command_kind": "verify",
        "idempotency_key": request["idempotency_key"],
        "request_sha256": request_sha,
        "effect": {
            **original_result["effect"],
            "receipt_id": rid,
            "version": d["version"] + 1,
            "state": "closed",
            "effect": "verified",
            "recorded_at": now.isoformat(),
        },
    }
    receipt_sha = public_digest("cosmas-portal-work-receipt.v1", response)
    response["receipt_sha256"] = receipt_sha
    with pytest.raises(DBAPIError) as caught, s.begin_nested():
        s.execute(
            text("UPDATE tickets SET state='closed',closed_at=:at,version=version+1 WHERE id=:id"),
            {"id": tid, "at": now},
        )
        s.execute(
            cast(Table, PortalWorkReceipt.__table__)
            .insert()
            .values(
                id=rid,
                ticket_id=tid,
                workspace_id=c["wid"],
                box_id=c["box"],
                owner_id=c["owner"],
                version=d["version"] + 1,
                command_kind="verify",
                idempotency_key=request["idempotency_key"],
                request=request,
                request_sha256=request_sha,
                response=response,
                receipt_sha256=receipt_sha,
                recorded_at=now,
            )
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"
    assert any(
        message in str(caught.value.orig)
        for message in [
            "current portal evidence required",
            "unambiguous owner-verified portal result required",
        ]
    )
    verify(s, c, tid)
    assert detail(s, c, tid)["state"] == "closed"


@pytest.mark.parametrize(
    "mutation", ["sequence", "public_hash", "head_hash", "extra_public_field", "failure_state"]
)
def test_direct_sql_observation_requires_exact_hash_chain_and_closed_projection(
    session, portal_case, mutation
):
    s, c = session, portal_case
    tid, _, _ = create(s, c)
    approve(s, c, tid)
    _, inv = call(
        s,
        c,
        execution.claim,
        tid,
        "submit",
        p.Bound(**bound(detail(s, c, tid))),
        catalog=c["catalog"],
        policy=POLICY,
    )
    assert inv
    d, now, oid = detail(s, c, tid), datetime.now(UTC), str(uuid4())
    sequence = 2 if mutation == "sequence" else 1
    public = {
        "id": oid,
        "sequence": sequence,
        "operation_id": d["operation_id"],
        "kind": "failure",
        "mode": "submit",
        "state": "accepted" if mutation == "failure_state" else "unknown",
        "observed_at": now.isoformat(),
    }
    if mutation == "extra_public_field":
        public["private_document"] = "Invented but forbidden field"
    sha = public_digest("cosmas-portal-work-observation.v1", public)
    if mutation == "public_hash":
        sha = "0" * 64
    public["sha256"] = sha
    head_sha = public_digest(
        "cosmas-portal-work-head.v1",
        {
            "operation_id": d["operation_id"],
            "sequence": sequence,
            "previous_sha256": d["observation_head"]["sha256"],
            "observation_sha256": sha,
        },
    )
    if mutation == "head_hash":
        head_sha = "0" * 64
    with pytest.raises(DBAPIError) as caught, s.begin_nested():
        s.execute(
            cast(Table, PortalWorkObservation.__table__)
            .insert()
            .values(
                id=oid,
                ticket_id=tid,
                workspace_id=c["wid"],
                box_id=c["box"],
                owner_id=c["owner"],
                claim_id=inv.claim_id,
                sequence=sequence,
                kind="failure",
                private_observation={"safe_error": "transport_unconfirmed"},
                public_observation=public,
                public_sha256=sha,
                head_sha256=head_sha,
                observed_at=now,
            )
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"
    assert any(
        message in str(caught.value.orig)
        for message in ["portal observation chain", "portal failure evidence"]
    )
    assert detail(s, c, tid)["observation_head"] == d["observation_head"]
    execution.settle(s, inv, failure=private.VendorError("transport_unconfirmed", attempted=True))
    assert detail(s, c, tid)["observation_head"]["sequence"] == 1
