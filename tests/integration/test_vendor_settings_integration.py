"""Registered managed settings, private C1 admission and exact runtime boundaries."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.requests import Request
from tests.integration.test_vendor_settings import (
    ON,
    account,
    account_request,
    recipient,
    view,
)
from tests.integration.test_vendor_settings import setup_case as setup_case
from tests.integration.test_vendor_work import bound, proposal
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import app as api
from cosmas_os.api import vendor_setup_schemas as p
from cosmas_os.application import note_review, services, vendor_work
from cosmas_os.application import vendor_settings as setup
from cosmas_os.application import vendor_settings_admission as admission
from cosmas_os.application.vendor_execution import VendorExecution
from cosmas_os.application.vendor_settings_execution import VendorSettingsExecution
from cosmas_os.config import Settings
from cosmas_os.models import AuditEvent, Principal, Ticket
from cosmas_os.vendor_models import VendorSubmitClaim
from cosmas_os.vendor_setup_models import VendorSetupReceipt


@pytest.fixture
def production(session, setup_case, monkeypatch):
    app = FastAPI(middleware=list(api.app.user_middleware))
    app.exception_handlers.update(api.app.exception_handlers)
    app.include_router(api.app.router)
    def request_session():
        # The middleware owns each Session for one request budget. Keep the
        # fixture's outer transaction, but give each request its own Session.
        try:
            with Session(bind=session.get_bind(), join_transaction_mode="create_savepoint") as scoped:
                yield scoped
        finally:
            session.expire_all()
    app.dependency_overrides[api.get_session] = request_session
    state = {"catalog": setup_case["installed"]}
    app.dependency_overrides[api._vendor_installed_catalog] = lambda: state["catalog"]
    app.dependency_overrides[api._vendor_setup_policy] = lambda: ON
    monkeypatch.setattr(api.settings, "vendor_io_enabled", True)
    with TestClient(app) as client:
        yield client, state, app


def headers(c, *, kind="setup", actor=None):
    return {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": actor or c["actor"],
        "X-Cosmas-Draft-Recovery": "2",
        "X-Cosmas-Vendor-Setup-Contract" if kind == "setup" else "X-Cosmas-Vendor-Contract": "1",
    }


def prepare(client, session, c, *, managed=True):
    request = proposal(c).public()
    if managed:
        a = account(session, c)
        recipient(session, c, a)
        detail = view(session, c, a)
        options = client.get(
            f"/workspaces/{c['wid']}/vendor-work/options", headers=headers(c, kind="work")
        ).json()
        connection = next(
            x
            for x in options["connections"]
            if x["id"] == detail["review"]["connection_version_id"]
        )
        correspondence = next(
            x for x in options["correspondences"] if x["connection_id"] == connection["id"]
        )
        request["connection"] = {k: connection[k] for k in ("id", "revision", "public_sha256")}
        request["correspondence"] = {
            k: correspondence[k] for k in ("id", "revision", "public_sha256")
        }
    root = f"/workspaces/{c['wid']}/vendor-work"
    created = client.post(root, json=request, headers=headers(c, kind="work"))
    assert created.status_code == 200, created.text
    path = root + "/" + created.json()["effect"]["ticket_id"]
    d = client.get(path, headers=headers(c, kind="work")).json()
    approved = client.post(
        path + "/decide",
        json=bound(d, review_sha256=d["review_sha256"], choice="approve"),
        headers=headers(c, kind="work"),
    )
    assert approved.status_code == 200, approved.text
    d = client.get(path, headers=headers(c, kind="work")).json()
    return root, path, d, request


def test_registered_settings_default_off_and_empty_registry():
    settings = Settings()
    assert settings.vendor_setup_enabled is False
    request = Request({"type": "http", "app": FastAPI()})
    assert api._vendor_installed_catalog(request) is setup.EMPTY_CATALOG
    assert api._vendor_execution_factory(request) is None


def test_registered_owner_settings_recovery_cors_and_private_history(
    production, session, setup_case, tmp_path
):
    client, state, app = production
    c = setup_case
    h = headers(c) | {"Origin": list(api.settings.allowed_origins)[0]}
    req = account_request(c)
    response = client.post("/vendor-settings/propose_account", headers=h, json=req.public())
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert response.headers["access-control-allow-origin"] == h["Origin"]
    assert response.headers["cache-control"] == "no-store"
    path = "/vendor-settings/" + req.setup_id
    saved = client.get(path + "/history", headers=h).json()
    p.History.model_validate(saved)
    old = client.post(
        "/vendor-settings/resolve",
        headers=h,
        json={
            "command_kind": "propose_account",
            "idempotency_key": req.idempotency_key,
            "request_sha256": receipt["request_sha256"],
        },
    )
    assert old.json() == receipt
    state["catalog"] = setup.EMPTY_CATALOG
    app.dependency_overrides[api._vendor_setup_policy] = lambda: setup.DEFAULT_POLICY
    assert (
        client.post("/vendor-settings/propose_account", headers=h, json=req.public()).json()
        == receipt
    )
    for is_owner in (False, True):
        user = Principal(
            box_id=c["box"],
            principal_type="human",
            display_name="Invented unrelated viewer",
            state="active",
            is_owner=is_owner,
        )
        session.add(user)
        session.commit()
        for endpoint in (path, path + "/history"):
            denied = client.get(endpoint, headers=headers(c, actor=user.id))
            assert denied.status_code == 404 and req.setup_id not in denied.text
        generic = headers(c, actor=user.id)
        generic.pop("X-Cosmas-Vendor-Setup-Contract")
        assert req.setup_id not in client.get("/queue", headers=generic).text
        assert (
            client.get("/tickets/" + req.setup_id + "/timeline", headers=generic).status_code == 400
        )
        assert req.setup_id not in client.get("/practice-work", headers=generic).text
    wire = json.dumps(saved)
    assert "credential_ref" not in wire and "internal_endpoint_id" not in wire
    (tmp_path / "registered-vendor-settings.json").write_text(
        json.dumps({"request": req.public(), "receipt": receipt, "history": saved}, indent=2)
    )


@pytest.mark.parametrize("status", [401, 403, 404])
def test_registered_auth_denial_is_closed_and_origin_readable(production, setup_case, status):
    client, _, app = production

    def denied():
        raise HTTPException(status, "Private authentication diagnostic sentinel")

    app.dependency_overrides[api._identity] = denied
    h = headers(setup_case) | {"Origin": list(api.settings.allowed_origins)[0]}
    response = client.get("/vendor-settings", headers=h)
    assert response.status_code == status
    assert response.json() == {"error": {"code": "vendor_setup_unavailable"}}
    assert response.headers["access-control-allow-origin"] == h["Origin"]
    assert response.headers["cache-control"] == "no-store"


def test_registered_preflight_does_not_authenticate(production):
    client, _, app = production

    def forbidden():
        raise AssertionError("Preflight authenticated")

    app.dependency_overrides[api._identity] = forbidden
    h = {
        "Origin": list(api.settings.allowed_origins)[0],
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,x-cosmas-vendor-setup-contract",
    }
    assert client.options("/vendor-settings/activate", headers=h).status_code == 200
    denied = client.options(
        "/vendor-settings/activate", headers=h | {"Origin": "https://unapproved.invalid"}
    )
    assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers


@pytest.mark.parametrize(
    "mode", ["base_for_managed", "unknown_subclass", "missing_registry", "runtime_registry_loss"]
)
def test_managed_denial_spends_no_claim_or_secret(production, session, setup_case, mode):
    client, state, app = production
    c = setup_case
    root, path, d, request = prepare(client, session, c)
    secrets = []

    async def credentials(*args):
        secrets.append(args)
        raise AssertionError("Rejected selection resolved a credential")

    class Unknown(VendorSettingsExecution):
        pass

    cls = (
        VendorExecution
        if mode == "base_for_managed"
        else Unknown
        if mode == "unknown_subclass"
        else VendorSettingsExecution
    )

    def factory(identity):
        kwargs = (
            {}
            if cls is VendorExecution
            else {
                "installed_catalog": lambda: (
                    setup.EMPTY_CATALOG if mode == "runtime_registry_loss" else state["catalog"]
                )
            }
        )
        return cls(api.SessionLocal, credentials, identity_current=identity, **kwargs)

    app.dependency_overrides[api._vendor_execution_factory] = lambda: factory
    if mode == "missing_registry":
        state["catalog"] = setup.EMPTY_CATALOG
        selected = client.get(root + "/options", headers=headers(c, kind="work")).json()
        assert (
            next(x for x in selected["connections"] if x["id"] == request["connection"]["id"])[
                "availability"
            ]
            == "disabled"
        )
        current = client.get(path, headers=headers(c, kind="work")).json()
        assert current["availability"]["submit"] == {
            "allowed": False,
            "reason": "selection_changed",
        }
        rejected = client.post(
            root,
            json=request | {"idempotency_key": str(uuid4()), "proposed_operation_id": str(uuid4())},
            headers=headers(c, kind="work"),
        )
        assert rejected.status_code == 409
    result = client.post(path + "/submit", json=bound(d), headers=headers(c, kind="work"))
    assert result.status_code == (503 if mode == "unknown_subclass" else 409), result.text
    session.expire_all()
    assert session.get(VendorSubmitClaim, d["summary"]["operation_id"]) is None
    assert not secrets


def test_runtime_pairing_preserves_explicit_legacy_and_denies_base_managed(session, setup_case):
    c = setup_case
    legacy = VendorExecution(None, None)
    a = account(session, c)
    native = view(session, c, a)["review"]["connection_version_id"]
    managed_runtime = VendorSettingsExecution(None, None, installed_catalog=lambda: c["installed"])
    assert admission.runtime_matches(session, c["config"].id, legacy)
    assert not admission.runtime_matches(session, native, legacy)
    assert admission.runtime_matches(session, native, managed_runtime)
    assert not admission.runtime_matches(session, c["config"].id, managed_runtime)


def test_concurrent_managed_reads_do_not_upgrade_owner_lock(engine, tmp_path):
    # A fixture's outer rollback transaction is invisible to other connections.
    # Seed a separate invented committed practice for this actual two-session check.
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented concurrent settings readers",
        )
        make = getattr(vendor_case, "__wrapped__", None)
        make_setup = getattr(setup_case, "__wrapped__", None)
        assert callable(make) and callable(make_setup)
        c = make_setup(make(s, seed))
        assert isinstance(c, dict)
        a = account(s, c)
        native = view(s, c, a)["review"]["connection_version_id"]
        s.commit()
    barrier = Barrier(2)

    def read():
        with Session(engine) as s:
            s.execute(text("SET LOCAL lock_timeout = '2s'"))
            w = vendor_work._owner(s, c["box"], c["actor"], c["wid"])
            barrier.wait(timeout=5)
            assert admission.require(s, w, native, c["installed"])
            s.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(read), pool.submit(read)]
        for future in futures:
            future.result(timeout=8)


def test_private_setup_audit_cannot_collide_with_generic_ticket_namespace(session, setup_case):
    c = setup_case
    request = account_request(c)
    ticket = Ticket(
        id=request.setup_id,
        box_id=c["box"],
        lane="artifact_chase",
        state="draft",
        created_by_principal_id=c["actor"],
    )
    session.add(ticket)
    session.add(
        AuditEvent(
            box_id=c["box"],
            aggregate_type="ticket",
            aggregate_id=ticket.id,
            actor_principal_id=c["actor"],
            event_type="ticket.created",
            outcome="draft",
            detail={},
        )
    )
    session.commit()
    setup.propose(
        session, c["box"], c["actor"], "propose_account", request, c["installed"], policy=ON
    )
    timeline = services.audit_timeline(services.Container(session), c["box"], ticket.id)
    assert [item["event_type"] for item in timeline] == ["ticket.created"]


def test_changed_reviewed_source_denies_managed_claim(production, session, setup_case):
    client, state, app = production
    c = setup_case
    _, path, detail, _ = prepare(client, session, c)

    async def forbidden(*args):
        raise AssertionError("Changed source must not resolve a credential")

    app.dependency_overrides[api._vendor_execution_factory] = lambda: (
        lambda identity: VendorSettingsExecution(
            api.SessionLocal,
            forbidden,
            identity_current=identity,
            installed_catalog=lambda: state["catalog"],
        )
    )
    note_review.save(
        session,
        c["box"],
        c["actor"],
        c["wid"],
        expected=3,
        key="changed-reviewed-source-" + str(uuid4()),
        base_note_id=c["source"]["note_id"],
        source_reply_id=None,
        content="Invented changed private note requiring fresh review",
    )
    response = client.post(path + "/submit", headers=headers(c, kind="work"), json=bound(detail))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "vendor_source_changed"
    assert session.get(VendorSubmitClaim, detail["summary"]["operation_id"]) is None


def test_final_registered_reauthentication_loss_rolls_back_proposal(
    production, session, setup_case, monkeypatch
):
    client, _, app = production
    request = account_request(setup_case)
    calls = 0
    original = api._identity

    def reauthenticate(**kwargs):
        nonlocal calls
        calls += 1
        if calls >= 2:
            from cosmas_os.application.workspace import WorkspaceError

            raise WorkspaceError("vendor_work_unavailable", 403)
        return original(**kwargs)

    monkeypatch.setattr(api, "_identity", reauthenticate)
    response = client.post(
        "/vendor-settings/propose_account", json=request.public(), headers=headers(setup_case)
    )
    assert response.status_code == 403
    session.rollback()
    assert (
        session.scalar(
            select(VendorSetupReceipt.id).where(VendorSetupReceipt.setup_id == request.setup_id)
        )
        is None
    )
