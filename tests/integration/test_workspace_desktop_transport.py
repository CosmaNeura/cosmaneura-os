"""Desktop authorized-party support preserves the existing signed authority checks."""
import pytest
from tests.integration import test_workspace_auth as shared

signed_workspace = shared.signed_workspace
pytestmark = pytest.mark.parametrize("signed_workspace", ["desktop"], indirect=True)

test_desktop_reopens_private_history = shared.test_two_signed_sessions_reopen_the_same_private_history
test_desktop_rejects_invalid_identity = shared.test_invalid_or_unbound_signed_requests_cannot_read
test_desktop_rejects_synthetic_headers = shared.test_identity_headers_and_unsigned_seeding_are_rejected


def test_desktop_requires_the_explicit_server_gate(signed_workspace):
    case = signed_workspace
    case.configuration.workspace_desktop_local_transport_enabled = False
    response = case.client.get(f"/workspaces/{case.workspace['id']}",
        headers={"Authorization": "Bearer " + case.token(), "Origin": "app://cosmas"})
    assert response.status_code == 404
    assert "Invented encounter" not in response.text


@pytest.mark.parametrize("party", ["null", "app://cosmas/", "app://other", "capacitor://localhost"])
def test_desktop_origin_does_not_replace_signed_authorized_party(signed_workspace, party):
    case = signed_workspace
    response = case.client.get(f"/workspaces/{case.workspace['id']}",
        headers={"Authorization": "Bearer " + case.token(azp=party), "Origin": "app://cosmas"})
    assert response.status_code == 401
    assert "Invented encounter" not in response.text
