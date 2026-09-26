"""Closed finance HTTP protocol over PostgreSQL, isolated from installed routes."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.integration.test_finance_work import POLICY, bound, proposal
from tests.integration.test_finance_work import finance_case as finance_case
from tests.integration.test_vendor_work import gates, vendor_case  # noqa: F401

from cosmas_os.api import app as api
from cosmas_os.api import finance_routes
from cosmas_os.api import finance_work_schemas as schema


def policy():
    return POLICY


def no_service():
    return None


@pytest.fixture
def client(session):
    app = FastAPI()
    app.dependency_overrides[api.get_session] = lambda: session
    finance_routes.install(
        app,
        get_session=api.get_session,
        identity_dependency=api._identity,
        policy_dependency=policy,
        execution_factory_dependency=no_service,
        event_route_dependency=no_service,
        core_connection=api._capture_connection,
        current_core_note=api._with_current_core_note,
        reauthenticate=api._vendor_reauthenticate,
        session_factory=api.SessionLocal,
    )

    @app.get("/health")
    def health():
        return {"ok": True}

    with TestClient(app) as client:
        yield client


def headers(c):
    return {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": c["actor"],
        "X-Cosmas-Finance-Contract": "1",
    }


def root(c):
    return f"/workspaces/{c['wid']}/finance-work"


def test_actual_finance_options_approval_result_and_recovery(
    client, session, finance_case, tmp_path
):
    c = finance_case
    h = headers(c)
    url = root(c)
    options = client.get(url + "/options", headers=h)
    assert options.status_code == 200, options.text
    schema.FinanceOptions.model_validate(options.json())
    assert (
        options.json()["expected_workspace_revision"] == 3
        and options.json()["source"] == c["source"]
    )
    request = proposal(
        c,
        expected_workspace_revision=options.json()["expected_workspace_revision"],
        source=options.json()["source"],
    )
    created = client.post(url, headers=h, json=request.public())
    assert created.status_code == 200, created.text
    schema.FinanceResponse.model_validate(created.json())
    tid = created.json()["effect"]["ticket_id"]
    detail = client.get(url + "/" + tid, headers=h)
    assert detail.status_code == 200, detail.text
    d = schema.FinanceDetail.model_validate(detail.json()).public()
    decision = client.post(
        url + "/" + tid + "/decide",
        headers=h,
        json=schema.FinanceDecision(
            **bound(d, review_sha256=d["review_sha256"], choice="approve")
        ).public(),
    )
    assert decision.status_code == 200, decision.text
    current = client.get(url + "/" + tid, headers=h).json()
    result = client.post(
        url + "/" + tid + "/result",
        headers=h,
        json=schema.FinanceResult(
            **bound(
                current,
                observation_head=current["summary"]["observation_head"],
                evidence_sha256=current["summary"]["evidence_sha256"],
                disposition="reported_unpaid",
                evidence="Invented payment has not occurred.",
            )
        ).public(),
    )
    assert result.status_code == 200, result.text
    final = client.get(url + "/" + tid, headers=h)
    final_value = schema.FinanceDetail.model_validate(final.json()).public()
    assert (
        final_value["summary"]["state"] == "approved"
        and final_value["latest_result"]["receipt_sha256"] == result.json()["receipt_sha256"]
    )
    recovered = client.post(
        url + "/resolve",
        headers=h,
        json={
            "command_kind": "propose",
            "idempotency_key": request.idempotency_key,
            "request_sha256": created.json()["request_sha256"],
        },
    )
    assert recovered.status_code == 200 and recovered.json()["effect"] == created.json()["effect"]
    page = client.get(url, headers=h)
    schema.FinanceCatalog.model_validate(page.json())
    observations = client.get(url + "/" + tid + "/observations", headers=h)
    schema.FinanceObservations.model_validate(observations.json())
    assert "cus_Invented" not in str([created.json(), final.json(), options.json()])
    assert final.headers["cache-control"] == "no-store"
    (tmp_path / "actual-finance-http-fixtures.json").write_text(
        json.dumps(
            {
                "options": options.json(),
                "proposal_receipt": created.json(),
                "pending_detail": detail.json(),
                "approval_receipt": decision.json(),
                "result_receipt": result.json(),
                "result_detail": final.json(),
                "proposal_resolved": recovered.json(),
                "catalog": page.json(),
                "observations": observations.json(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize("value", [None, "", "2", "1,1"])
def test_finance_exact_contract_header(client, finance_case, value):
    h = headers(finance_case)
    if value is None:
        h.pop("X-Cosmas-Finance-Contract")
    else:
        h["X-Cosmas-Finance-Contract"] = value
    result = client.get(root(finance_case) + "/options", headers=h)
    assert (
        result.status_code == 426 and result.json()["error"]["code"] == "finance_contract_required"
    )


def test_finance_strict_body_and_wrong_route_headers(client, finance_case):
    h = headers(finance_case)
    assert client.get("/health", headers=h).status_code == 426
    assert (
        client.get(
            root(finance_case) + "/options",
            headers=[*h.items(), ("X-Cosmas-Finance-Contract", "1")],
        ).status_code
        == 426
    )
    body = {**proposal(finance_case).public(), "confirm": True}
    response = client.post(root(finance_case), headers=h, json=body)
    assert response.status_code == 400 and "confirm" not in response.text
    duplicate = b'{"idempotency_key":"invented-one","idempotency_key":"invented-two"}'
    assert (
        client.post(
            root(finance_case), headers={**h, "Content-Type": "application/json"}, content=duplicate
        ).status_code
        == 400
    )
    assert (
        client.post(
            root(finance_case),
            headers={**h, "Content-Type": "application/json", "Content-Length": "1"},
            content=b" " * 16385,
        ).status_code
        == 413
    )
    assert client.get(root(finance_case) + "?credential=forbidden", headers=h).status_code == 400


def test_finance_unpaid_and_missing_service_do_not_trigger_processor(client, finance_case):
    c = finance_case
    h = headers(c)
    url = root(c)
    created = client.post(url, headers=h, json=proposal(c).public()).json()
    tid = created["effect"]["ticket_id"]
    d = client.get(url + "/" + tid, headers=h).json()
    approved = client.post(
        url + "/" + tid + "/decide",
        headers=h,
        json=schema.FinanceDecision(
            **bound(d, review_sha256=d["review_sha256"], choice="approve")
        ).public(),
    )
    assert approved.status_code == 200
    d = client.get(url + "/" + tid, headers=h).json()
    response = client.post(url + "/" + tid + "/submit", headers=h, json=bound(d))
    assert (
        response.status_code == 403
        and response.json()["error"]["code"] == "finance_feature_disabled"
    )
    assert not client.get(url + "/" + tid, headers=h).json()["summary"]["submit_claimed"]
