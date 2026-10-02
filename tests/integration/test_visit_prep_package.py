import json
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from tests.integration.test_workspace_bot_tasks import install as install_team
from tests.integration.test_workspace_capture import capture_case as _capture_case
from tests.unit.test_core_visit_prep import wire

from cosmas_os.api import app as api
from cosmas_os.api.visit_prep_routes import install
from cosmas_os.application import provider_team
from cosmas_os.models import CoreCaptureAccount, ExternalIdentity
from cosmas_os.ports.core_visit_prep import CoreVisitPrepReceipt

capture_case = _capture_case


@pytest.mark.parametrize("revoke", [None, "identity", "account", "flag"])
def test_signed_cosmabot_route_reads_without_an_encounter_grant(capture_case, monkeypatch, revoke):
    f = capture_case
    f.configuration.workspace_core_connection_enabled = True
    f.configuration.core_connection_tenant_ref = "authority_tenant_" + "0" * 25 + "1"
    f.configuration.workspace_visit_prep_enabled = True
    f.configuration.core_visit_prep_scope = "api://invented-visit-prep/.default"
    f.configuration.core_visit_prep_managed_identity_client_id = str(uuid4())
    monkeypatch.setattr(provider_team, "runtime_settings", f.configuration)
    install_team(f)
    f.session.commit()
    value = wire()
    calls = []

    class Port:
        def read(self, request, bearer):
            calls.append(request)
            value.update(
                preparation_ref=request.preparation_ref,
                workspace_id=str(request.workspace_id),
                request_nonce=str(request.request_nonce),
                connection_sha256=request.connection_sha256,
            )
            if revoke == "flag":
                f.configuration.workspace_visit_prep_enabled = False
            elif revoke:
                with Session(f.engine) as session:
                    if revoke == "identity":
                        session.get(ExternalIdentity, f.identity_id).active = False
                    else:
                        session.get(CoreCaptureAccount, f.account_id).revoked_at = datetime.now(UTC)
                    session.commit()
            return CoreVisitPrepReceipt.model_validate_json(json.dumps(value), strict=True)

    @contextmanager
    def connection(settings, budget):
        yield Port()

    # Existing app is already installed; substitute only the port seam.
    import cosmas_os.api.visit_prep_routes as routes

    monkeypatch.setattr(routes, "visit_prep_connection", connection)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    install(
        app,
        settings=lambda: f.configuration,
        session_factory=lambda: Session(f.engine),
        identity_dependency=api._identity,
        workspace_gate=lambda **kwargs: None,
        connection_factory=connection,
    )
    response = TestClient(app).post(
        "/provider-team/visit-prep/read",
        json={
            "preparation_ref": value["preparation_ref"],
            "connection_sha256": value["connection_sha256"],
            "workspace_id": str(uuid4()),
            "request_nonce": str(uuid4()),
            "bot": {"address": "visit_prep", "team_revision": 1},
        },
        headers={"Authorization": "Bearer " + f.token(), "X-Cosmas-Visit-Prep-Contract": "1"},
    )
    if revoke:
        assert response.status_code in {401, 403, 503}
        assert "Invented report" not in response.text
    else:
        assert response.status_code == 200, response.text
        assert response.json()["package"] == value["package"]
        assert response.headers["cache-control"] == "no-store"
    assert len(calls) == 1
