"""The retained shell origin receives no shortcut around signed private ownership."""
import pytest
from tests.integration import test_workspace_auth as shared

signed_workspace = shared.signed_workspace
pytestmark = pytest.mark.parametrize("signed_workspace", ["apple"], indirect=True)

# Exercise the same persistence, current identity and foreign-owner checks from
# the Apple authorized party, using the real offline RSA token verifier.
test_apple_reopens_same_private_history = shared.test_two_signed_sessions_reopen_the_same_private_history
test_apple_rejects_invalid_identity = shared.test_invalid_or_unbound_signed_requests_cannot_read
test_apple_rejects_synthetic_headers = shared.test_identity_headers_and_unsigned_seeding_are_rejected


def test_apple_requires_the_explicit_server_gate(signed_workspace):
    case = signed_workspace
    case.configuration.workspace_apple_local_transport_enabled = False
    response = case.client.get(f"/workspaces/{case.workspace['id']}",
        headers={"Authorization": "Bearer " + case.token(), "Origin": "capacitor://localhost"})
    assert response.status_code == 404
    assert "Invented encounter" not in response.text


@pytest.mark.parametrize("party", ["null", "capacitor://localhost/", "capacitor://other", "app://cosmas"])
def test_origin_header_cannot_substitute_for_signed_authorized_party(signed_workspace, party):
    case = signed_workspace
    response = case.client.get(f"/workspaces/{case.workspace['id']}",
        headers={"Authorization": "Bearer " + case.token(azp=party), "Origin": "capacitor://localhost"})
    assert response.status_code == 401
    assert "Invented encounter" not in response.text
