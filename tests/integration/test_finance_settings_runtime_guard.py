"""The finance HTTP execution allowlist remains sealed to its two concrete runtimes."""

import pytest
from tests.integration.test_finance_api import client as client
from tests.integration.test_finance_api import headers, no_service, root
from tests.integration.test_finance_work import POLICY, approved, bound
from tests.integration.test_finance_work import finance_case as finance_case
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.application import finance_execution
from cosmas_os.application.finance_execution import FinanceExecution
from cosmas_os.application.finance_settings_execution import FinanceSettingsExecution
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.finance_models import FinanceSubmitClaim
from cosmas_os.models import Operation


class UnexpectedFinance(FinanceExecution):
    pass


class UnexpectedSettings(FinanceSettingsExecution):
    pass


@pytest.mark.parametrize("runtime_type", [UnexpectedFinance, UnexpectedSettings, object])
def test_unreviewed_runtime_type_is_rejected_before_submit_claim(
    client, session, finance_case, runtime_type
):
    c = finance_case
    tid, _, d = approved(session, c)

    async def forbidden(_):
        raise AssertionError("No unknown runtime can request credentials")

    runtime = (
        runtime_type(lambda: session, forbidden, policy=POLICY)
        if runtime_type is not object
        else object()
    )
    client.app.dependency_overrides[no_service] = lambda: lambda identity: runtime
    try:
        response = client.post(root(c) + "/" + tid + "/submit", headers=headers(c), json=bound(d))
        assert (
            response.status_code == 503
            and response.json()["error"]["code"] == "finance_unavailable"
        )
        assert session.get(FinanceSubmitClaim, d["summary"]["operation_id"]) is None
        assert session.get(Operation, d["summary"]["operation_id"]).attempt_count == 0
    finally:
        client.app.dependency_overrides.pop(no_service, None)


def test_endpoint_wrapper_keeps_unapproved_error_codes_private(
    client, session, finance_case, monkeypatch
):
    c = finance_case
    tid, _, d = approved(session, c)

    async def forbidden(_):
        raise AssertionError("No credentials are needed for a rejected admission")

    runtime = FinanceExecution(lambda: session, forbidden, policy=POLICY)

    def fail(*args, **kwargs):
        raise WorkspaceError("invented_internal_secret_code", 409)

    monkeypatch.setattr(finance_execution, "claim_submit", fail)
    client.app.dependency_overrides[no_service] = lambda: lambda identity: runtime
    try:
        response = client.post(root(c) + "/" + tid + "/submit", headers=headers(c), json=bound(d))
        assert response.status_code == 409
        assert response.json() == {"contract_version": 1, "error": {"code": "finance_unavailable"}}
        assert "invented_internal" not in response.text
        assert session.get(FinanceSubmitClaim, d["summary"]["operation_id"]) is None
    finally:
        client.app.dependency_overrides.pop(no_service, None)
