"""Actual PostgreSQL portal configuration history with an explicitly injected test profile."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Table, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from tests.unit.test_vendor_portal_contract import SyntheticInMemoryPortal, selection

from cosmas_os.adapters.vendor_connectors.portals import (
    PRODUCTION_PORTALS,
    PortalBinding,
    PortalRegistry,
)
from cosmas_os.api import app as api
from cosmas_os.api import portal_setup_routes
from cosmas_os.api import portal_setup_schemas as p
from cosmas_os.api.vendor_work_schemas import public_digest, timestamp
from cosmas_os.application import portal_setup as flow
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.config import settings
from cosmas_os.models import PatientLink, Principal
from cosmas_os.portal_models import PortalSetupReceipt, PortalSetupRevision


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setitem(settings.__dict__, "portal_setup_enabled", True)


@pytest.fixture
def case(session, seeded):
    box, owner = seeded["box_id"], seeded["owner_id"]
    patient = PatientLink(
        box_id=box,
        source_pair_key=str(uuid4()),
        label="Invented portal patient",
        state="confirmed",
        confirmed_by_principal_id=owner,
        attested_at=datetime.now(UTC),
    )
    session.add(patient)
    session.commit()
    adapter = SyntheticInMemoryPortal()
    chosen = selection().model_copy(
        update={"connection_id": uuid4(), "box_id": UUID(box), "owner_id": UUID(owner)}
    )
    registry = PortalRegistry((PortalBinding(adapter.profile, adapter),))
    catalog = flow.Catalog(
        registry, (flow.Installation(chosen, adapter.profile, "Invented portal"),)
    )
    request = p.Proposal(
        connection_id=str(uuid4()),
        expected_version=0,
        idempotency_key="portal-proposal-" + str(uuid4()),
        installation_id=str(chosen.connection_id),
        profile_sha256=adapter.profile.commitment(),
        configuration_sha256=chosen.configuration_sha256,
        capabilities=["referral.read"],
        mappings=p.Mappings(
            patient_link_id=patient.id,
            practice_reference="synthetic_practice",
            patient_reference="invented_patient",
            recipient_reference="invented_recipient",
            practice_label="Invented practice",
            recipient_label="Invented recipient",
        ),
    )
    return {
        "box": box,
        "owner": owner,
        "patient": patient,
        "adapter": adapter,
        "catalog": catalog,
        "request": request,
    }


def propose(s, c, request=None):
    return flow.propose(s, c["box"], c["owner"], request or c["request"], c["catalog"])


def detail(s, c):
    return flow.detail(s, c["box"], c["owner"], c["request"].connection_id, c["catalog"])


def bound(d) -> dict[str, Any]:
    return dict(
        connection_id=d["connection_id"],
        expected_version=d["version"],
        idempotency_key="portal-command-" + str(uuid4()),
        revision_id=d["revision_id"],
        review_sha256=d["review_sha256"],
    )


def activation(d):
    return p.Activation(
        **bound(d),
        reviewed_profile=True,
        reviewed_practice=True,
        reviewed_patient=True,
        reviewed_recipient=True,
        confirm_local_activation=True,
    )


def command(s, c, kind, request):
    return flow.command(s, c["box"], c["owner"], kind, request, c["catalog"])


def test_owner_proposes_reviews_activates_disables_and_revokes_without_provider_call(session, case):
    c = case
    first = propose(session, c)
    assert first["effect"]["state"] == "pending_review"
    assert propose(session, c) == first
    current = detail(session, c)
    assert not current["usable_locally"]
    with pytest.raises(WorkspaceError, match="portal_connection_inactive"):
        flow.active_correspondence(
            session, c["box"], c["owner"], current["connection_id"], "referral.read", c["catalog"]
        )
    request = activation(current)
    active = command(session, c, "activate", request)
    assert command(session, c, "activate", request) == active
    selected, mappings, records = flow.active_correspondence(
        session, c["box"], c["owner"], current["connection_id"], "referral.read", c["catalog"]
    )
    assert (
        str(mappings.patient_mapping_id)
        == detail(session, c)["review"]["mapping_ids"]["patient_mapping_id"]
    )
    assert records.patient_reference == "invented_patient" and selected.vendor == "portal"
    disabled = command(
        session, c, "disable", p.Disable(**bound(detail(session, c)), confirm_disable=True)
    )
    assert disabled["effect"]["state"] == "disabled"
    command(session, c, "activate", activation(detail(session, c)))
    revoked = command(
        session, c, "revoke", p.Revoke(**bound(detail(session, c)), confirm_revoke=True)
    )
    assert (
        revoked["effect"]["state"] == "revoked"
        and len(flow.history(session, c["box"], c["owner"], current["connection_id"])["receipts"])
        == 5
    )
    with pytest.raises(WorkspaceError, match="portal_setup_changed"):
        command(session, c, "activate", activation(detail(session, c)))
    assert c["adapter"].effects == [] and PRODUCTION_PORTALS._bindings == {}


def test_mapping_revision_pauses_active_configuration_and_old_receipt_still_resolves(
    session, case, monkeypatch
):
    c = case
    first = propose(session, c)
    command(session, c, "activate", activation(detail(session, c)))
    d = detail(session, c)
    request = c["request"].model_copy(
        update={
            "expected_version": d["version"],
            "idempotency_key": "portal-revised-" + str(uuid4()),
            "mappings": c["request"].mappings.model_copy(
                update={"recipient_reference": "another_recipient"}
            ),
        }
    )
    second = propose(session, c, request)
    assert second["effect"]["state"] == "pending_review" and detail(session, c)["revision"] == 2
    monkeypatch.setitem(settings.__dict__, "portal_setup_enabled", False)
    saved = flow.resolve(
        session,
        c["box"],
        c["owner"],
        p.Resolve(
            command_kind="propose",
            idempotency_key=c["request"].idempotency_key,
            request_sha256=first["request_sha256"],
        ),
    )
    assert saved == first and propose(session, c) == first
    command(session, c, "disable", p.Disable(**bound(detail(session, c)), confirm_disable=True))
    assert (
        session.scalar(
            select(func.count())
            .select_from(PortalSetupRevision)
            .where(PortalSetupRevision.connection_id == d["connection_id"])
        )
        == 2
    )


@pytest.mark.parametrize("change", ["configuration", "profile", "patient"])
def test_activation_requires_current_profile_configuration_and_patient(session, case, change):
    c = case
    propose(session, c)
    request = activation(detail(session, c))
    if change == "configuration":
        item = next(iter(c["catalog"].installations.values()))
        c["catalog"].installations[str(item.selection.connection_id)] = flow.Installation(
            item.selection.model_copy(update={"configuration_sha256": "0" * 64}),
            item.profile,
            item.label,
        )
    elif change == "profile":
        c["adapter"].profile = c["adapter"].profile.model_copy(
            update={"receipt_parser_version": "changed"}
        )
    else:
        c["patient"].revoked_at = datetime.now(UTC)
        session.commit()
    with pytest.raises(WorkspaceError):
        command(session, c, "activate", request)
    assert (
        session.scalar(
            select(func.count())
            .select_from(PortalSetupReceipt)
            .where(PortalSetupReceipt.connection_id == c["request"].connection_id)
        )
        == 1
    )


@pytest.mark.parametrize("change", ["profile_hash", "practice", "cross_patient", "unsupported"])
def test_invalid_proposal_cannot_create_active_mapping(session, case, change):
    c = case
    data = c["request"].public()
    if change == "profile_hash":
        data["profile_sha256"] = "0" * 64
    if change == "practice":
        data["mappings"]["practice_reference"] = "wrong_practice"
    if change == "cross_patient":
        data["mappings"]["patient_link_id"] = str(uuid4())
    if change == "unsupported":
        # A documented profile can be installed with an unsupported individual capability.
        item = next(iter(c["catalog"].installations.values()))
        changed = item.profile.model_copy(
            update={
                "capabilities": tuple(
                    cap.model_copy(update={"evidence": "unsupported"})
                    if cap.capability == "referral.read"
                    else cap
                    for cap in item.profile.capabilities
                )
            }
        )
        c["catalog"].installations[str(item.selection.connection_id)] = flow.Installation(
            item.selection, changed, item.label
        )
    with pytest.raises(WorkspaceError):
        propose(session, c, p.Proposal.model_validate(data))


def test_other_human_and_unconfigured_portal_never_gain_owner_authority(session, case):
    c = case
    propose(session, c)
    peer = Principal(
        box_id=c["box"], principal_type="human", display_name="Invented peer", is_owner=False
    )
    session.add(peer)
    session.commit()
    with pytest.raises(WorkspaceError):
        flow.catalog(session, c["box"], peer.id, c["catalog"])
    with pytest.raises(WorkspaceError):
        flow.resolve(
            session,
            c["box"],
            peer.id,
            p.Resolve(
                command_kind="propose",
                idempotency_key=c["request"].idempotency_key,
                request_sha256="0" * 64,
            ),
        )
    assert flow.catalog(session, c["box"], c["owner"])["profiles"] == []
    assert (
        flow.detail(session, c["box"], c["owner"], c["request"].connection_id)["availability"]
        == "portal_profile_unavailable"
    )


@pytest.mark.parametrize(
    "field,value",
    [("reviewed_profile", False), ("reviewed_patient", "true"), ("confirm_local_activation", 1)],
)
def test_strict_activation_confirmation(field, value):
    data = dict(
        connection_id=str(uuid4()),
        expected_version=1,
        idempotency_key="invented-key",
        revision_id=str(uuid4()),
        review_sha256="a" * 64,
        reviewed_profile=True,
        reviewed_practice=True,
        reviewed_patient=True,
        reviewed_recipient=True,
        confirm_local_activation=True,
    )
    data[field] = value
    with pytest.raises(ValidationError):
        p.Activation.model_validate(data)


@pytest.mark.parametrize(
    "value", ["https://portal.example.invalid", "token with spaces", "../patient", "*"]
)
def test_mapping_references_never_accept_urls_paths_or_wildcards(value):
    with pytest.raises(ValidationError):
        p.Mappings(
            patient_link_id=str(uuid4()),
            practice_reference=value,
            patient_reference="p",
            recipient_reference="r",
            practice_label="P",
            recipient_label="R",
        )


def test_database_retains_immutable_review_and_receipt_history(session, case):
    propose(session, case)
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(
            text("UPDATE portal_setup_revisions SET review_sha256=:sha WHERE connection_id=:id"),
            {"sha": "0" * 64, "id": case["request"].connection_id},
        )
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(
            text("DELETE FROM portal_setup_receipts WHERE connection_id=:id"),
            {"id": case["request"].connection_id},
        )


def test_actual_http_closed_requests_and_exact_recovery(session, case):
    c = case
    app = FastAPI()
    portal_setup_routes.register(app, api.get_session, api._identity)
    app.dependency_overrides[api.get_session] = lambda: session
    app.dependency_overrides[portal_setup_routes.installed_catalog] = lambda: c["catalog"]
    headers = {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": c["owner"],
        "X-Cosmas-Portal-Contract": "1",
    }
    with TestClient(app) as client:
        assert client.get("/portal-setup", headers=headers).status_code == 200
        first = client.post("/portal-setup/propose", headers=headers, json=c["request"].public())
        assert first.status_code == 200, first.text
        assert first.headers["cache-control"] == "no-store"
        exact = first.json()
        restored = client.post(
            "/portal-setup/resolve",
            headers=headers,
            json={
                "command_kind": "propose",
                "idempotency_key": c["request"].idempotency_key,
                "request_sha256": exact["request_sha256"],
            },
        )
        assert restored.json() == exact
        d = client.get("/portal-setup/" + c["request"].connection_id, headers=headers).json()
        data = activation(d).public()
        data["reviewed_profile"] = False
        assert client.post("/portal-setup/activate", headers=headers, json=data).status_code == 422
        bad = {**c["request"].public(), "url": "https://unreviewed.example.invalid"}
        assert client.post("/portal-setup/propose", headers=headers, json=bad).status_code == 422
        assert client.get("/portal-setup?extra=yes", headers=headers).status_code == 426
        assert (
            client.get(
                "/portal-setup",
                headers={k: v for k, v in headers.items() if k != "X-Cosmas-Portal-Contract"},
            ).status_code
            == 426
        )
        approved = client.post(
            "/portal-setup/activate", headers=headers, json=activation(d).public()
        )
        assert approved.status_code == 200, approved.text
        assert c["adapter"].effects == []


def forged_receipt(c, request, revision, kind="activate") -> dict[str, Any]:
    value = request.public()
    rid = str(uuid4())
    now = datetime.now(UTC)
    digest = flow.request_digest(c["box"], c["owner"], kind, request)
    state = {
        "propose": "pending_review",
        "activate": "active",
        "disable": "disabled",
        "revoke": "revoked",
    }[kind]
    response = {
        "contract_version": 1,
        "outcome": "recorded",
        "scope": {"box_id": c["box"], "owner_id": c["owner"]},
        "connection_id": request.connection_id,
        "command_kind": kind,
        "idempotency_key": request.idempotency_key,
        "request_sha256": digest,
        "receipt_id": rid,
        "recorded_at": timestamp(now),
        "effect": {
            "version": request.expected_version + 1,
            "revision_id": revision.id,
            "state": state,
            "review_sha256": revision.review_sha256,
        },
    }
    sha = public_digest("cosmas-portal-setup-receipt.v1", response)
    response["receipt_sha256"] = sha
    return dict(
        id=rid,
        box_id=c["box"],
        owner_id=c["owner"],
        connection_id=request.connection_id,
        revision_id=revision.id,
        version=request.expected_version + 1,
        state=state,
        command_kind=kind,
        idempotency_key=request.idempotency_key,
        request=value,
        request_sha256=digest,
        response=response,
        receipt_sha256=sha,
        recorded_at=now,
    )


def rehash(row):
    row["request_sha256"] = public_digest(
        "cosmas-portal-setup-request.v1",
        {
            "scope": {"box_id": row["box_id"], "owner_id": row["owner_id"]},
            "command_kind": row["command_kind"],
            "request": row["request"],
        },
    )
    row["response"]["request_sha256"] = row["request_sha256"]
    row["receipt_sha256"] = public_digest(
        "cosmas-portal-setup-receipt.v1",
        {k: v for k, v in row["response"].items() if k != "receipt_sha256"},
    )
    row["response"]["receipt_sha256"] = row["receipt_sha256"]


@pytest.mark.parametrize(
    "change",
    [
        "false_review",
        "string_review",
        "missing_review",
        "extra_request",
        "stale_version",
        "wrong_revision",
        "wrong_review",
        "receipt_outcome",
        "receipt_contract",
        "receipt_extra",
        "receipt_time",
        "request_hash",
        "receipt_hash",
        "revoked_patient",
    ],
)
def test_sql_forged_activation_never_records_a_reviewed_configuration(session, case, change):
    c = case
    propose(session, c)
    d = detail(session, c)
    row = forged_receipt(c, activation(d), session.get(PortalSetupRevision, d["revision_id"]))
    if change == "false_review":
        row["request"]["reviewed_profile"] = False
    if change == "string_review":
        row["request"]["reviewed_patient"] = "true"
    if change == "missing_review":
        del row["request"]["reviewed_practice"]
    if change == "extra_request":
        row["request"]["access_token"] = "invented-not-a-credential"
    if change == "stale_version":
        row["request"]["expected_version"] = 0
    if change == "wrong_revision":
        row["request"]["revision_id"] = str(uuid4())
    if change == "wrong_review":
        row["request"]["review_sha256"] = "0" * 64
    if change == "receipt_outcome":
        row["response"]["outcome"] = "not_found"
    if change == "receipt_contract":
        row["response"]["contract_version"] = 2
    if change == "receipt_extra":
        row["response"]["private_endpoint"] = "invented"
    if change == "receipt_time":
        row["response"]["recorded_at"] = "2020-01-01T00:00:00Z"
    rehash(row)
    if change == "request_hash":
        row["request_sha256"] = "0" * 64
    if change == "receipt_hash":
        row["receipt_sha256"] = "0" * 64
    if change == "revoked_patient":
        c["patient"].revoked_at = datetime.now(UTC)
        session.commit()
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(insert(cast(Table, PortalSetupReceipt.__table__)).values(**row))
    assert (
        session.scalar(
            select(func.count())
            .select_from(PortalSetupReceipt)
            .where(PortalSetupReceipt.connection_id == d["connection_id"])
        )
        == 1
    )


def test_sql_request_cannot_expand_the_reviewed_capabilities(session, case):
    c = case
    propose(session, c)
    d = detail(session, c)
    old = session.get(PortalSetupRevision, d["revision_id"])
    row = {
        column.name: deepcopy(getattr(old, column.name))
        for column in PortalSetupRevision.__table__.columns
    }
    row.update(id=str(uuid4()), revision=2)
    session.execute(insert(cast(Table, PortalSetupRevision.__table__)).values(**row))
    revised = session.get(PortalSetupRevision, row["id"])
    request = c["request"].model_copy(
        update={"expected_version": 1, "idempotency_key": "portal-new-capabilities"}
    )
    receipt = forged_receipt(c, request, revised, "propose")
    receipt["request"]["capabilities"] = ["document.upload", "referral.read"]
    rehash(receipt)
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(insert(cast(Table, PortalSetupReceipt.__table__)).values(**receipt))


def test_gate_disable_preserves_owner_control_and_history(session, case, monkeypatch):
    c = case
    propose(session, c)
    command(session, c, "activate", activation(detail(session, c)))
    monkeypatch.setitem(settings.__dict__, "portal_setup_enabled", False)
    catalog = flow.catalog(session, c["box"], c["owner"], c["catalog"])
    assert catalog["profiles"] == [] and not catalog["connections"][0]["usable_locally"]
    command(session, c, "disable", p.Disable(**bound(detail(session, c)), confirm_disable=True))
    command(session, c, "revoke", p.Revoke(**bound(detail(session, c)), confirm_revoke=True))
    assert detail(session, c)["state"] == "revoked"
