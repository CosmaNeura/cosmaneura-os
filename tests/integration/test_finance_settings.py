"""Real PostgreSQL owner settings, admission atomicity and payment authority fencing."""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_finance_work import POLICY as WORK_POLICY
from tests.integration.test_finance_work import bound as work_bound
from tests.integration.test_finance_work import call as work_call
from tests.integration.test_finance_work import proposal as payment_proposal
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import immediate
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import app as api
from cosmas_os.api import finance_setup_routes as routes
from cosmas_os.api import finance_setup_schemas as schema
from cosmas_os.api import finance_work_schemas as payment_schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import finance_execution, finance_setup, finance_work, services
from cosmas_os.application import finance_settings as flow
from cosmas_os.application import workspace as ws
from cosmas_os.application.finance_settings_execution import FinanceSettingsExecution
from cosmas_os.config import settings
from cosmas_os.finance_models import FinanceConnectionVersion, FinanceCustomerVersion
from cosmas_os.finance_setup_models import FinanceSetup
from cosmas_os.models import EncounterWorkspace, Principal
from cosmas_os.ports.vendor_connectors import ConnectionSelection

POLICY = flow.FinanceSetupPolicy(enabled=True)


@pytest.fixture
def case(session, vendor_case):
    c = vendor_case
    selected = ConnectionSelection(
        vendor="stripe",
        connection_id=uuid4(),
        box_id=UUID(c["box"]),
        owner_id=UUID(c["actor"]),
        environment="sandbox",
        remote_account_id="acct_SettingsInvented",
        credential_ref=uuid4(),
        configuration_sha256="a" * 64,
    )
    catalog = flow.Catalog((flow.Installation(selected, "Invented installed Stripe sandbox"),))
    profile = next(iter(catalog.installations.values())).public()
    request = schema.AccountProposal(
        setup_id=str(uuid4()),
        expected_version=0,
        idempotency_key="account-proposal-" + str(uuid4()),
        installation_id=profile["installation_id"],
        installation_sha256=profile["installation_sha256"],
        label="Invented reviewed billing account",
        permissions=schema.Permissions(read_status=True, create_unconfirmed_intents=True),
    )
    return {
        **c,
        "installed": catalog,
        "account_request": request,
        "patient_id": session.get(EncounterWorkspace, c["wid"]).patient_link_id,
    }


def call(s, c, method, *args, **kwargs):
    return method(s, c["box"], c["actor"], *args, **kwargs)


def detail(s, c, sid):
    return call(s, c, flow.detail, sid, c["installed"], policy=POLICY)


def bound(d, **extra):
    value = d["summary"]
    return {
        "setup_id": value["setup_id"],
        "expected_version": value["version"],
        "revision_id": value["revision_id"],
        "review_sha256": value["review_sha256"],
        "idempotency_key": "finance-setup-" + str(uuid4()),
        **extra,
    }


def activation(d):
    return schema.Activation(
        **bound(
            d,
            reviewed_account=True,
            reviewed_environment=True,
            confirm_local_activation=True,
            **({"reviewed_patient_customer": True} if d["summary"]["kind"] == "customer" else {}),
        )
    )


def command(s, c, kind, request, *, policy=POLICY):
    return call(s, c, flow.command, kind, request, c["installed"], policy=policy)


def account(s, c):
    request = c["account_request"]
    call(s, c, flow.propose, "propose_account", request, c["installed"], policy=POLICY)
    command(s, c, "activate", activation(detail(s, c, request.setup_id)))
    return detail(s, c, request.setup_id)


def customer_request(c, a, **extra):
    b = bound(a)
    b.pop("idempotency_key")
    return schema.CustomerProposal.model_validate(
        {
            "setup_id": str(uuid4()),
            "expected_version": 0,
            "idempotency_key": "customer-proposal-" + str(uuid4()),
            "account": b,
            "patient_link_id": c["patient_id"],
            "customer_id": "cus_SettingsInvented",
            "label": "Invented verified billing customer",
            **extra,
        }
    )


def ready(s, c):
    a = account(s, c)
    request = customer_request(c, a)
    call(s, c, flow.propose, "propose_customer", request, c["installed"], policy=POLICY)
    command(s, c, "activate", activation(detail(s, c, request.setup_id)))
    return a, detail(s, c, request.setup_id)


def payment_case(s, c, a, m):
    return {
        **c,
        "finance_connection": finance_setup.connection_view(
            s.get(FinanceConnectionVersion, a["review"]["connection_version_id"])
        ),
        "customer": finance_setup.customer_view(
            s.get(FinanceCustomerVersion, m["review"]["customer_version_id"])
        ),
    }


def approved_payment(s, c, a, m):
    c = payment_case(s, c, a, m)
    receipt = work_call(s, c, finance_work.propose, payment_proposal(c), policy=WORK_POLICY)
    tid = receipt["effect"]["ticket_id"]
    d = work_call(s, c, finance_work.detail, tid)
    work_call(
        s,
        c,
        finance_work.decide,
        tid,
        payment_schema.FinanceDecision(
            **work_bound(d, review_sha256=d["review_sha256"], choice="approve")
        ),
        policy=WORK_POLICY,
    )
    return c, tid, work_call(s, c, finance_work.detail, tid)


@pytest.fixture
def client(session, case):
    app = FastAPI()
    app.dependency_overrides[api.get_session] = lambda: session
    app.dependency_overrides[routes.installed_catalog] = lambda: case["installed"]
    app.dependency_overrides[routes.setup_policy] = lambda: POLICY
    routes.register(app, api.get_session, api._identity, reauthenticate=api._vendor_reauthenticate)
    with TestClient(app) as client:
        yield client


def headers(c):
    return {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": c["actor"],
        "X-Cosmas-Finance-Setup-Contract": "1",
    }


def test_actual_account_and_patient_mapping_review_activation_and_receipts(
    session, client, case, tmp_path
):
    c, h = case, headers(case)
    initial = client.get("/finance-setup", headers=h)
    assert initial.status_code == 200, initial.text
    assert len(initial.json()["installed_accounts"]) == 1
    assert (
        str(next(iter(c["installed"].installations.values())).selection.credential_ref)
        not in initial.text
    )
    requests, receipts, details = [], [], []
    request = c["account_request"]
    for kind, value in [("propose_account", request)]:
        response = client.post("/finance-setup/" + kind, headers=h, json=value.public())
        assert response.status_code == 200, response.text
        requests.append({"kind": kind, "request": value.public()})
        receipts.append(response.json())
    a = client.get("/finance-setup/" + request.setup_id, headers=h).json()
    assert a["summary"]["availability"] == "available" and not a["summary"]["usable_locally"]
    native = session.get(FinanceConnectionVersion, a["review"]["connection_version_id"])
    assert not native.write_enabled and not native.read_enabled
    act = activation(a)
    response = client.post("/finance-setup/activate", headers=h, json=act.public())
    assert response.status_code == 200, response.text
    requests.append({"kind": "activate", "request": act.public()})
    receipts.append(response.json())
    a = client.get("/finance-setup/" + request.setup_id, headers=h).json()
    details.append(a)
    mreq = customer_request(c, a)
    response = client.post("/finance-setup/propose_customer", headers=h, json=mreq.public())
    assert response.status_code == 200, response.text
    requests.append({"kind": "propose_customer", "request": mreq.public()})
    receipts.append(response.json())
    m = client.get("/finance-setup/" + mreq.setup_id, headers=h).json()
    assert not session.get(FinanceCustomerVersion, m["review"]["customer_version_id"]).is_current
    act = activation(m)
    response = client.post("/finance-setup/activate", headers=h, json=act.public())
    assert response.status_code == 200, response.text
    requests.append({"kind": "activate", "request": act.public()})
    receipts.append(response.json())
    m = client.get("/finance-setup/" + mreq.setup_id, headers=h).json()
    details.append(m)
    assert m["summary"]["usable_locally"] and a["summary"]["usable_locally"]
    for vector, receipt in zip(requests, receipts, strict=True):
        again = client.post("/finance-setup/" + vector["kind"], headers=h, json=vector["request"])
        assert again.status_code == 200 and again.json() == receipt
        resolved = client.post(
            "/finance-setup/resolve",
            headers=h,
            json={
                "command_kind": receipt["command_kind"],
                "idempotency_key": receipt["idempotency_key"],
                "request_sha256": receipt["request_sha256"],
            },
        )
        assert resolved.json() == receipt
    options = work_call(session, c, finance_work.options, policy=WORK_POLICY)
    assert any(x["availability"] == "reviewed" for x in options["customers"])
    immediate(session)
    (tmp_path / "actual-finance-setup-fixtures.json").write_text(
        json.dumps(
            {
                "catalog": initial.json(),
                "commands": requests,
                "receipts": receipts,
                "details": details,
                "active_catalog": client.get("/finance-setup", headers=h).json(),
                "history": client.get(
                    "/finance-setup/" + mreq.setup_id + "/history", headers=h
                ).json(),
            },
            indent=2,
        )
        + "\n"
    )


def test_customer_change_invalidates_old_approval_and_requires_new_activation(session, case):
    a, m = ready(session, case)
    c, tid, d = approved_payment(session, case, a, m)
    request = customer_request(
        c,
        a,
        setup_id=m["summary"]["setup_id"],
        expected_version=m["summary"]["version"],
        customer_id="cus_ChangedInvented",
    )
    saved = call(
        session, c, flow.propose, "propose_customer", request, c["installed"], policy=POLICY
    )
    fresh = detail(session, c, request.setup_id)
    assert fresh["summary"]["state"] == "pending_review"
    assert fresh["review"]["customer_version_id"] != m["review"]["customer_version_id"]
    assert not session.get(FinanceCustomerVersion, m["review"]["customer_version_id"]).is_current
    with pytest.raises(ws.WorkspaceError, match="finance_selection_changed"):
        work_call(
            session,
            c,
            finance_execution.claim_submit,
            tid,
            public.BoundCommand(**work_bound(d)),
            policy=WORK_POLICY,
        )
    command(session, c, "activate", activation(fresh))
    assert (
        call(session, c, flow.propose, "propose_customer", request, c["installed"], policy=POLICY)
        == saved
    )
    immediate(session)


def test_account_disable_and_reactivation_cannot_revive_customer_payment_approval(session, case):
    a, m = ready(session, case)
    c, tid, d = approved_payment(session, case, a, m)
    command(session, c, "disable", schema.Disable(**bound(a), confirm_disable=True))
    disabled = detail(session, c, a["summary"]["setup_id"])
    command(session, c, "activate", activation(disabled))
    assert not session.get(FinanceCustomerVersion, m["review"]["customer_version_id"]).is_current
    assert (
        detail(session, c, m["summary"]["setup_id"])["summary"]["availability"]
        == "finance_account_changed"
    )
    with pytest.raises(ws.WorkspaceError, match="finance_selection_changed"):
        work_call(
            session,
            c,
            finance_execution.claim_submit,
            tid,
            public.BoundCommand(**work_bound(d)),
            policy=WORK_POLICY,
        )
    immediate(session)


@pytest.mark.parametrize("stage", ["account", "customer"])
def test_legacy_admission_commit_is_atomic_with_settings_receipt(session, case, stage):
    c = case
    if stage == "customer":
        a = account(session, c)
        request, kind, model = customer_request(c, a), "propose_customer", FinanceCustomerVersion
    else:
        request, kind, model = c["account_request"], "propose_account", FinanceConnectionVersion
    before = session.scalar(select(func.count()).select_from(model))
    session.commit()

    def deny():
        raise ws.WorkspaceError("finance_setup_unavailable", 403)

    session.info["finance_setup_authority"] = deny
    try:
        with pytest.raises(ws.WorkspaceError):
            call(session, c, flow.propose, kind, request, c["installed"], policy=POLICY)
        session.rollback()
    finally:
        session.info.pop("finance_setup_authority", None)
    assert session.scalar(select(func.count()).select_from(model)) == before
    assert session.get(FinanceSetup, request.setup_id) is None


def test_disabled_gate_keeps_exact_recovery_and_explicit_revoke(session, case):
    c = case
    a = account(session, c)
    disabled = command(
        session,
        c,
        "disable",
        schema.Disable(**bound(a), confirm_disable=True),
        policy=flow.DEFAULT_POLICY,
    )
    again = call(
        session,
        c,
        flow.resolve,
        schema.Resolve(
            command_kind="disable",
            idempotency_key=disabled["idempotency_key"],
            request_sha256=disabled["request_sha256"],
        ),
    )
    assert again == disabled
    current = detail(session, c, a["summary"]["setup_id"])
    with pytest.raises(ws.WorkspaceError, match="finance_setup_disabled"):
        command(session, c, "activate", activation(current), policy=flow.DEFAULT_POLICY)
    revoked = command(
        session,
        c,
        "revoke",
        schema.Revoke(**bound(current), confirm_revoke=True),
        policy=flow.DEFAULT_POLICY,
    )
    assert revoked["effect"]["state"] == "revoked"
    with pytest.raises(ws.WorkspaceError, match="finance_setup_changed"):
        command(session, c, "activate", activation(detail(session, c, a["summary"]["setup_id"])))
    immediate(session)


def test_nonowner_wrong_scope_unknown_installation_and_changed_digest_are_denied(
    session, client, case
):
    c = case
    h = headers(c)
    another = Principal(
        box_id=c["box"],
        principal_type="human",
        state="active",
        is_owner=False,
        display_name="Invented nonowner",
    )
    session.add(another)
    session.commit()
    assert (
        client.get("/finance-setup", headers={**h, "X-Actor-Principal-Id": another.id}).status_code
        == 404
    )
    request = c["account_request"].public()
    for field, value in [("installation_id", str(uuid4())), ("installation_sha256", "0" * 64)]:
        invalid = {**request, field: value}
        r = client.post("/finance-setup/propose_account", headers=h, json=invalid)
        assert r.status_code == 409 and r.json()["error"]["code"] == "finance_installation_changed"
    saved = client.post("/finance-setup/propose_account", headers=h, json=request)
    assert saved.status_code == 200
    assert (
        client.post(
            "/finance-setup/propose_account", headers=h, json={**request, "label": "Altered"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/finance-setup/propose_account", headers=h, json={**request, "credential": "forbidden"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/finance-setup/propose_account",
            headers={**h, "Content-Type": "application/json"},
            content=b" " * 8193,
        ).status_code
        == 413
    )
    assert (
        client.get(
            "/finance-setup", headers={**h, "X-Cosmas-Finance-Setup-Contract": "2"}
        ).status_code
        == 426
    )


def test_sql_cannot_enable_pending_binding_or_rewrite_settings_history(session, case):
    c = case
    call(
        session,
        c,
        flow.propose,
        "propose_account",
        c["account_request"],
        c["installed"],
        policy=POLICY,
    )
    d = detail(session, c, c["account_request"].setup_id)
    immediate(session)
    for sql, value in [
        (
            "UPDATE finance_connection_versions SET write_enabled=true WHERE id=:id",
            d["review"]["connection_version_id"],
        ),
        (
            "UPDATE finance_setup_revisions SET review_sha256=repeat('0',64) WHERE id=:id",
            d["summary"]["revision_id"],
        ),
        ("DELETE FROM finance_setup_receipts WHERE id=:id", d["last_receipt"]["receipt_id"]),
    ]:
        with session.begin_nested() as nested:
            with pytest.raises(DBAPIError):
                session.execute(text(sql), {"id": value})
                immediate(session)
            nested.rollback()


def test_concurrent_identical_account_proposal_has_one_native_binding(
    engine, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented settings race",
        )
        c = globals()["case"].__wrapped__(s, globals()["vendor_case"].__wrapped__(s, seed))
        s.commit()
    paused, release = Event(), Event()

    def apply(first=False):
        with Session(engine, expire_on_commit=False) as s:
            if first:

                def fence():
                    paused.set()
                    assert release.wait(5)

                s.info["finance_setup_authority"] = fence
            return call(
                s,
                c,
                flow.propose,
                "propose_account",
                c["account_request"],
                c["installed"],
                policy=POLICY,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(apply, True)
        assert paused.wait(5)
        second = pool.submit(apply)
        release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    assert a == b
    with Session(engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(FinanceConnectionVersion)
                .where(FinanceConnectionVersion.owner_id == c["actor"])
            )
            == 1
        )


def test_removed_installation_after_claim_denies_before_credentials_or_transport(
    engine, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented settings authority",
        )
        c = globals()["case"].__wrapped__(s, globals()["vendor_case"].__wrapped__(s, seed))
        a, m = ready(s, c)
        c, tid, d = approved_payment(s, c, a, m)
        _, invocation = work_call(
            s,
            c,
            finance_execution.claim_submit,
            tid,
            public.BoundCommand(**work_bound(d)),
            policy=WORK_POLICY,
        )
    calls = []

    async def credentials(selection):
        calls.append("credential")
        raise AssertionError("No credential lookup permitted")

    async def identity():
        return True

    executor = FinanceSettingsExecution(
        lambda: Session(engine, expire_on_commit=False),
        credentials,
        policy=WORK_POLICY,
        identity_current=identity,
        installed_catalog=lambda: flow.EMPTY_CATALOG,
    )
    asyncio.run(executor.invoke(invocation, deadline=time.monotonic() + 10))
    assert calls == []
    with Session(engine) as s:
        current = work_call(s, c, finance_work.detail, tid)
        assert (
            current["summary"]["submit_claimed"]
            and current["summary"]["creation"] == "not_observed"
        )


def test_history_cap_reserves_disable_and_revoke_for_last_active_configuration(session, case):
    c = case
    d = account(session, c)
    while d["summary"]["version"] < 98:
        command(session, c, "disable", schema.Disable(**bound(d), confirm_disable=True))
        d = detail(session, c, d["summary"]["setup_id"])
        command(session, c, "activate", activation(d))
        d = detail(session, c, d["summary"]["setup_id"])
    assert d["summary"]["version"] == 98 and d["summary"]["usable_locally"]
    new = c["account_request"].model_copy(
        update={"expected_version": 98, "idempotency_key": "cap-change-" + str(uuid4())}
    )
    with pytest.raises(ws.WorkspaceError, match="finance_setup_limit"):
        call(session, c, flow.propose, "propose_account", new, c["installed"], policy=POLICY)
    disabled = command(session, c, "disable", schema.Disable(**bound(d), confirm_disable=True))
    assert disabled["effect"]["version"] == 99
    d = detail(session, c, d["summary"]["setup_id"])
    assert d["summary"]["availability"] == "finance_setup_limit"
    with pytest.raises(ws.WorkspaceError, match="finance_setup_limit"):
        command(session, c, "activate", activation(d))
    revoked = command(session, c, "revoke", schema.Revoke(**bound(d), confirm_revoke=True))
    assert revoked["effect"]["version"] == 100 and revoked["effect"]["state"] == "revoked"
    immediate(session)


def test_duplicate_targets_and_identity_changes_never_create_parallel_bindings(session, case):
    c = case
    a, m = ready(session, c)
    duplicate = c["account_request"].model_copy(
        update={"setup_id": str(uuid4()), "idempotency_key": "duplicate-" + str(uuid4())}
    )
    with pytest.raises(ws.WorkspaceError, match="finance_setup_already_exists"):
        call(session, c, flow.propose, "propose_account", duplicate, c["installed"], policy=POLICY)
    with pytest.raises(ws.WorkspaceError, match="finance_setup_already_exists"):
        call(
            session,
            c,
            flow.propose,
            "propose_customer",
            customer_request(c, a),
            c["installed"],
            policy=POLICY,
        )
    wrong = customer_request(
        c,
        a,
        setup_id=m["summary"]["setup_id"],
        expected_version=m["summary"]["version"],
        patient_link_id=str(uuid4()),
    )
    with pytest.raises(ws.WorkspaceError, match="finance_patient_unavailable"):
        call(session, c, flow.propose, "propose_customer", wrong, c["installed"], policy=POLICY)
    catalog = call(session, c, flow.catalog, c["installed"], policy=POLICY)
    customer = next(x for x in catalog["setups"] if x["kind"] == "customer")
    assert customer["target"] == {
        "kind": "customer",
        "account_setup_id": a["summary"]["setup_id"],
        "patient_link_id": c["patient_id"],
    }
    assert "cus_SettingsInvented" not in json.dumps(catalog)


@pytest.mark.parametrize("winner", ["disable", "submit"])
def test_committed_disable_and_payment_claim_race_preserves_current_authority(
    engine, tmp_path, monkeypatch, winner
):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")), "Invented disable race"
        )
        c = globals()["case"].__wrapped__(s, globals()["vendor_case"].__wrapped__(s, seed))
        a, m = ready(s, c)
        c, tid, d = approved_payment(s, c, a, m)
        disable = schema.Disable(**bound(m), confirm_disable=True)
        submit = public.BoundCommand(**work_bound(d))
    paused, release, started = Event(), Event(), Event()

    def apply(kind, first=False):
        with Session(engine, expire_on_commit=False) as s:
            if first:

                def fence():
                    paused.set()
                    assert release.wait(5)

                s.info[
                    "finance_setup_authority" if kind == "disable" else "finance_final_authority"
                ] = fence
            else:
                started.set()
            try:
                if kind == "disable":
                    return "recorded", command(s, c, "disable", disable)
                receipt, invocation = work_call(
                    s, c, finance_execution.claim_submit, tid, submit, policy=WORK_POLICY
                )
                return "recorded", invocation
            except ws.WorkspaceError as exc:
                s.rollback()
                return "rejected", exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(apply, winner, True)
        assert paused.wait(5)
        second = pool.submit(apply, "submit" if winner == "disable" else "disable")
        assert started.wait(5)
        release.set()
        first_result, second_result = first.result(timeout=5), second.result(timeout=5)
    assert first_result[0] == "recorded"
    if winner == "disable":
        assert second_result == ("rejected", "finance_selection_changed")
    else:
        assert second_result[0] == "recorded"
        invocation = first_result[1]

        async def never(_):
            raise AssertionError("A disabled mapping must not access credentials")

        executor = FinanceSettingsExecution(
            lambda: Session(engine),
            never,
            policy=WORK_POLICY,
            installed_catalog=lambda: c["installed"],
        )
        assert (
            executor.current_authority(invocation, invocation.command, invocation.approval, True)
            is False
        )
