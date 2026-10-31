"""Recovery uses the immutable runtime account binding, never request URLs."""
from uuid import uuid4

import pytest
from fastapi import Response
from pydantic import SecretStr

from cosmas_os.api import app as product
from cosmas_os.config import Settings


def managed_runtime(account="https://onboarding.staging.cosmas.ai"):
    control = "https://enrollment-api.staging.cosmas.ai"
    return Settings(_env_file=None, cosmas_env="early_adopter_beta", auth_mode="clerk_jwt",
        workspace_enrollment_managed=True, workspace_enrollment_practice_id=str(uuid4()),
        beta_box_id=str(uuid4()), clerk_organization_id="org_invented",
        workspace_enrollment_api_origin=control,
        workspace_enrollment_origin_allowlist=control + "," + account,
        workspace_enrollment_account_origin=account,
        workspace_enrollment_admission_secret=SecretStr("a" * 64))


@pytest.mark.parametrize("account", ["https://onboarding.staging.cosmas.ai", "https://staging.cosmas.ai", "https://app.cosmas.ai"])
def test_config_reports_only_the_validated_exact_managed_account_binding(monkeypatch, account):
    runtime = managed_runtime(account)
    monkeypatch.setattr(product, "settings", runtime)
    response = Response()
    assert product.enrollment_runtime_config(response) == {
        "enrollment_managed": True, "enrollment_account_origin": account,
        "enrollment_recovery_url": account + "/onboarding",
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("changed", [
    {"workspace_enrollment_managed": False},
    {"workspace_enrollment_account_origin": "https://foreign.invalid"},
    {"workspace_enrollment_account_origin": "https://onboarding.staging.cosmas.ai/onboarding"},
    {"workspace_enrollment_admission_secret": SecretStr("invalid")},
])
def test_unmanaged_or_unbound_account_never_publishes_recovery(monkeypatch, changed):
    runtime = managed_runtime().model_copy(update=changed)
    monkeypatch.setattr(product, "settings", runtime)
    value = product.enrollment_runtime_config(Response())
    assert value["enrollment_account_origin"] is None
    assert value["enrollment_recovery_url"] is None
