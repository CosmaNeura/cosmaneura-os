"""The browser receives an allocation policy only from isolated synthetic settings."""

import pytest

from cosmas_os.enrollment.config import EnrollmentSettings


@pytest.mark.parametrize("allocation,data_mode,policy", [
    (False, "disabled", "exact"),
    (False, "synthetic", "exact"),
    (True, "disabled", "exact"),
    (True, "production", "exact"),
    (True, "synthetic", "synthetic-practice-uuid-staging-v1"),
])
def test_public_workspace_origin_policy_requires_enabled_synthetic_allocation(allocation, data_mode, policy):
    settings = EnrollmentSettings(_env_file=None, workspace_allocation_enabled=allocation, data_mode=data_mode)
    public = settings.public_config()
    assert public["workspace_origin_policy"] == policy
    assert public["allowed_workspace_origins"] == settings.allowed_workspace_origins
    assert "workspace_allocation_enabled" not in public
