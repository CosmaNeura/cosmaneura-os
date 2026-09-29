import base64
import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr
from tests.unit.test_scheduling_contract import selection as selection
from tests.unit.test_scheduling_runtime import configuration as configuration

from cosmas_os.adapters.scheduling import HttpSchedulingAvailability
from cosmas_os.adapters.scheduling_google_login import SchedulingGoogleLogin, exact_origin
from cosmas_os.adapters.scheduling_identity import SchedulingIdentityVerifier
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling_enrollment import ConnectionContent, catalog_digest

ORIGIN = "https://scheduling.example.invalid"
TOKEN = SecretStr("invented-staff-token")


@pytest.mark.parametrize("base_path", ["", "/api"])
def test_identity_and_catalog_use_the_same_api_base(selection, base_path):
    content = ConnectionContent(
        practice={"id": selection.practice_id, "label": "Invented Practice"},
        actor_id=selection.expected_actor_id, role="staff", practitioner=None,
        locations=(), appointment_types=(),
    ).model_dump(mode="json")
    staff = {key: content[key] for key in ("actor_id", "role")}
    staff["practice_id"] = str(selection.practice_id)
    catalog = {**content, "observed_at": datetime.now(UTC).isoformat(),
               "catalog_sha256": catalog_digest(content)}
    paths = []

    def handler(request):
        paths.append(request.url.path)
        assert request.url.host == "scheduling.example.invalid"
        assert request.headers["authorization"] == "Bearer invented-staff-token"
        assert request.headers["x-practice-id"] == str(selection.practice_id)
        payload = staff if request.url.path.endswith("/staff") else catalog
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(payload).encode()),
                              headers={"Content-Type": "application/json", "Cache-Control": "no-store"})

    verifier = SchedulingIdentityVerifier(ORIGIN + base_path, transport=httpx.MockTransport(handler))
    try:
        verifier.confirm(selection, TOKEN)
        assert verifier.catalog(selection.practice_id, TOKEN).actor_id == selection.expected_actor_id
        assert paths == [base_path + "/v1/me/staff", base_path + "/v1/me/companion-connection"]
    finally:
        verifier.close()


@pytest.mark.parametrize("status", [200, 302, 404])
def test_api_identity_never_accepts_html_or_falls_back_to_site_root(selection, status):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(status, text="<html>Invented app shell</html>",
                              headers={"Location": ORIGIN + "/v1/me/staff"})

    verifier = SchedulingIdentityVerifier(ORIGIN + "/api", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ConnectorUnavailable, match="scheduling_identity_unavailable"):
            verifier.confirm(selection, TOKEN)
        assert paths == ["/api/v1/me/staff"]
    finally:
        verifier.close()


def test_only_the_exact_api_mount_is_an_allowed_scheduling_path():
    for suffix in ("/api/", "/API", "/api/v1", "/%61pi", "/api/..", "/api?x=1", "/api#x"):
        with pytest.raises(ValueError):
            exact_origin(ORIGIN + suffix, allow_api_path=True)
        with pytest.raises(ValueError):
            SchedulingIdentityVerifier(ORIGIN + suffix)
        with pytest.raises(ValueError):
            HttpSchedulingAvailability(ORIGIN + suffix, lambda _: pytest.fail("no credential I/O"))
    assert exact_origin(ORIGIN + "/api", allow_api_path=True) == ORIGIN + "/api"
    with pytest.raises(ValueError):
        exact_origin(ORIGIN + "/api")


def test_login_binds_credentials_to_api_base_and_keeps_return_origin_strict(configuration):
    configuration.workspace_scheduling_login_enabled = True
    configuration.scheduling_origin = ORIGIN
    configuration.scheduling_login_return_origin = "https://app.example.invalid"
    configuration.scheduling_google_callback_uri = "https://api.example.invalid/connections/scheduling/google/callback"
    configuration.scheduling_google_client_id = "invented.apps.googleusercontent.com"
    configuration.scheduling_google_client_secret = SecretStr("invented-secret")
    configuration.scheduling_login_encryption_key = SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode())
    def sessions():
        pytest.fail("configuration must not access the database")

    transport = httpx.MockTransport(lambda _: pytest.fail("configuration must not send HTTP"))
    root = SchedulingGoogleLogin(configuration, sessions, google_transport=transport, scheduling_transport=transport)
    try:
        root._enabled()
        configuration.scheduling_origin = ORIGIN + "/api"
        with pytest.raises(ConnectorUnavailable, match="scheduling_sign_in_unavailable"):
            root._enabled()
        mounted = SchedulingGoogleLogin(configuration, sessions, google_transport=transport, scheduling_transport=transport)
        try:
            mounted._enabled()
            assert mounted.config_digest != root.config_digest
            configuration.scheduling_login_return_origin += "/api"
            with pytest.raises(ValueError):
                SchedulingGoogleLogin(configuration, sessions, google_transport=transport, scheduling_transport=transport)
        finally:
            mounted.close()
    finally:
        root.close()
