"""Real signed API/SQL; only observed engine URL is a hosted façade, not TLS proof."""
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_hosted_routines import HostedSession, delivery_counts
from tests.integration.test_shared_work import delivered, people
from tests.integration.test_workspace_auth import signed_workspace
from tests.unit.test_hosted_workspace_config import hosted
from tests.unit.test_routines_hosted_gate import HOSTED_DATABASE

from cosmas_os.api import app as api
from cosmas_os.application import follow_up, shared_work
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import AuditEvent, PatientLink

__all__ = ["signed_workspace"]


def configuration(monkeypatch, box):
    value = hosted(database_url=HOSTED_DATABASE, beta_box_id=box, workspace_routines_enabled=False)
    value.validate_runtime_configuration()
    monkeypatch.setattr(follow_up, "settings", value)
    return value


def test_hosted_saved_catalog_preserves_owner_and_current_source_without_writes(session, seeded, monkeypatch):
    case, item = delivered(session, seeded)
    staff = people(session, case[0])[0]
    foreign = svc.provision_box(svc.Container(session), "Other invented practice")
    foreign_case, foreign_item = delivered(session, foreign)
    value = configuration(monkeypatch, case[0])
    observed = HostedSession(session, value.database_url)
    before = delivery_counts(session)
    audits = session.scalar(select(func.count()).select_from(AuditEvent))
    assert shared_work.catalog(observed, case[0], staff, vendor=True)["items"] == []
    result = shared_work.catalog(observed, case[0], case[1], vendor=True)
    assert [v["ticket_id"] for v in result["items"]] == [item["ticket_id"]]
    assert foreign_item["ticket_id"] not in str(result)
    assert "Private invented agenda" not in str(result) and "workspace_id" not in str(result)
    assert shared_work.read(observed, case[0], case[1], item["ticket_id"]) == item
    with pytest.raises(ws.WorkspaceError):
        shared_work.catalog(observed, foreign_case[0], case[1])
    with pytest.raises(ws.WorkspaceError):
        shared_work.read(observed, case[0], staff, item["ticket_id"])
    with pytest.raises(ws.WorkspaceError, match="follow_up_connection_required"):
        shared_work.act(cast(Session, observed), case[0], case[1], item["ticket_id"], expected=item["version"],
            revision_id=item["revision_id"], digest=item["payload_hash"], key="not-offered",
            kind="offer", recipient=staff)
    with pytest.raises(ws.WorkspaceError, match="follow_up_connection_required"):
        shared_work.complete(observed, case[0], case[1], item["ticket_id"],
            revision_id=item["revision_id"], digest=item["payload_hash"], key="not-completed", evidence="Invented")
    session.get(PatientLink, case[3]).revoked_at = datetime.now(UTC)
    session.commit()
    assert shared_work.catalog(observed, case[0], case[1])["items"] == []
    assert delivery_counts(session) == before
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == audits


@pytest.mark.parametrize("changes", [
    {"data_mode": "authorized_beta", "clinic_approval_ref": "invented:clinic",
     "baa_evidence_ref": "invented:baa", "phi_authorization_ref": "invented:phi"},
    {"human_deploy_evidence_ref": None}, {"workspace_authenticated_enabled": False},
])
def test_hosted_unapproved_or_nonsynthetic_profile_refuses_read(session, seeded, monkeypatch, changes):
    value = configuration(monkeypatch, seeded["box_id"])
    for name, setting in changes.items():
        setattr(value, name, setting)
    with pytest.raises(ws.WorkspaceError, match="shared_work_connection_required"):
        shared_work.catalog(HostedSession(session, value.database_url), seeded["box_id"], seeded["owner_id"])


def test_hosted_read_cannot_substitute_another_host_database_or_local_connection(session, seeded, monkeypatch):
    configuration(monkeypatch, seeded["box_id"])
    for changed in (HOSTED_DATABASE.replace("@postgres:", "@unapproved.invalid:"),
                    HOSTED_DATABASE.replace("/cosmas_os?", "/other_database?"),
                    "postgresql+psycopg://invented@127.0.0.1/w1a_rehearsal"):
        with pytest.raises(ws.WorkspaceError, match="shared_work_connection_required"):
            shared_work.catalog(HostedSession(session, changed), seeded["box_id"], seeded["owner_id"])


@pytest.mark.parametrize("signed_workspace", ["desktop"], indirect=True)
def test_signed_hosted_empty_catalog_reopen_and_revocation(signed_workspace, session, monkeypatch):
    f = signed_workspace
    value = configuration(monkeypatch, f.box)
    # Preserve the fixture's real signed issuer/audience and local RSA verifier.
    value.clerk_issuer = f.configuration.clerk_issuer
    value.clerk_jwks_url = f.configuration.clerk_jwks_url
    value.clerk_audience = f.configuration.clerk_audience
    value.clerk_authorized_parties += ",app://cosmas"
    value.cors_allowed_origins += ",app://cosmas"
    value.workspace_desktop_hosted_transport_enabled = True
    value.validate_runtime_configuration()
    monkeypatch.setattr(api, "settings", value)
    previous = api.app.dependency_overrides[api.get_session]
    def observed_session():
        yield HostedSession(session, value.database_url)
    api.app.dependency_overrides[api.get_session] = observed_session
    headers = {"Authorization": "Bearer " + f.token(), "X-Cosmas-Vendor-Contract": "1"}
    try:
        before = delivery_counts(session)
        for _ in range(2):
            response = f.client.get("/practice-work", headers=headers)
            assert response.status_code == 200 and response.json()["items"] == []
            assert response.headers["cache-control"] == "no-store"
        assert f.client.get("/practice-work", headers={**headers,
            "Authorization": "Bearer " + f.token(sub="unbound")}).status_code == 403
        def unapproved_session():
            yield HostedSession(session, value.database_url.replace("@postgres:", "@unapproved.invalid:"))
        api.app.dependency_overrides[api.get_session] = unapproved_session
        assert f.client.get("/practice-work", headers=headers).status_code == 403
        api.app.dependency_overrides[api.get_session] = observed_session
        value.data_mode = "authorized_beta"
        value.clinic_approval_ref = value.baa_evidence_ref = value.phi_authorization_ref = "invented:approved"
        assert f.client.get("/practice-work", headers=headers).status_code == 403
        value.data_mode = "synthetic"
        f.binding.active = False
        session.commit()
        assert f.client.get("/practice-work", headers=headers).status_code == 403
        assert delivery_counts(session) == before
    finally:
        api.app.dependency_overrides[api.get_session] = previous
