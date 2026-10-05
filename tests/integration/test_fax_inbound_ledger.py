"""Dark generic fax foundation: retained scope/F8 ledger, no registered API or HTTP."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from cosmas_os.application import fax_inbound as ledger
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.config import settings
from cosmas_os.fax_inbound_models import FaxInboundCommand, FaxInboundGrant, FaxInboundImage
from cosmas_os.ports.fax_inbound import MetadataPage, ReceivedFax
from cosmas_os.ports.vendor_connectors import ConnectionSelection


@pytest.fixture
def dark_fax(session, seeded, monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    f = SimpleNamespace(s=session, box=seeded["box_id"], owner=seeded["owner_id"], active=True)
    f.item = ledger.Installation(ConnectionSelection(vendor="documo", environment="production",
        box_id=f.box, owner_id=f.owner, connection_id=uuid4(), credential_ref=uuid4(),
        configuration_sha256="a" * 64, remote_account_id=str(uuid4())), "Invented café inbox", True)
    f.current = lambda item: f.active and item == f.item
    f.expires = datetime.now(UTC) + timedelta(hours=23)
    return f


def grant(f, key="dark-fax-grant-1"):
    return ledger.grant(f.s, f.box, f.owner, f.item, key=key, expires_at=f.expires,
        reviewed_account=True, image_enabled=True, current=f.current)


def observe(f, g):
    ends = datetime.now(UTC) - timedelta(seconds=1)
    _, intent = ledger.reserve_observation(f.s, f.box, f.owner, g["grant_id"],
        key="dark-fax-observe-1", starts_at=ends-timedelta(days=1), ends_at=ends, limit=25, current=f.current)
    scope = intent[2]
    fax = ReceivedFax(scope.key(), (str(uuid4()),), ends-timedelta(minutes=1), 1,
        None, False, True, sender_label="Invented Clínica José", sender_number="+1 (212) 555-0199")
    return ledger.settle_observation(f.s, f.box, f.owner, intent,
        MetadataPage(scope, (fax,), "none", "b" * 64), current=f.current)


def proposal(f, g, obs):
    return ledger.propose(f.s, f.box, f.owner, key="dark-fax-propose-1", grant_id=g["grant_id"],
        observation_id=obs["observation_id"], observation_sha256=obs["source_sha256"],
        source_sha256=obs["items"][0]["source_sha256"], current=f.current)


def test_dark_grant_observation_exact_f8_review_and_db_only_recovery(dark_fax):
    f = dark_fax
    g = grant(f)
    assert grant(f) == g
    obs = observe(f, g)
    assert obs["items"][0]["sender_label"] == "Invented Clínica José"
    assert obs["items"][0]["sender_identity"] == "provider_reported_unverified"
    p = proposal(f, g, obs)
    public = ledger.proposal(f.s, f.box, f.owner, p["ticket_id"], p["revision_id"], current=f.current)
    assert public["state"] == "pending_approval" and public["label"] == "Invented café inbox"
    approved = ledger.decide(f.s, f.box, f.owner, key="dark-fax-approve-1", ticket_id=p["ticket_id"],
        revision_id=p["revision_id"], expected_version=p["version"], choice="approve",
        reviewed_exact_fax=True, current=f.current)
    assert approved["state"] == "approved" and approved["approval_sha256"]
    assert ledger.resolve(f.s, f.box, f.owner, key="dark-fax-observe-1", current=f.current) == obs
    assert f.s.scalar(select(func.count()).select_from(FaxInboundImage)) == 1
    assert f.s.scalar(select(func.count()).select_from(FaxInboundCommand)) == 4


def test_dark_foreign_agent_and_changed_account_cannot_recover_or_approve(dark_fax, seeded):
    f = dark_fax
    g, obs = grant(f), None
    obs = observe(f, g)
    p = proposal(f, g, obs)
    with pytest.raises(WorkspaceError):
        ledger.proposal(f.s, f.box, seeded["agents"]["chief"], p["ticket_id"], p["revision_id"], current=f.current)
    f.s.rollback()
    f.active = False
    with pytest.raises(WorkspaceError, match="fax_inbound_permission_unavailable"):
        ledger.decide(f.s, f.box, f.owner, key="dark-fax-refused-1", ticket_id=p["ticket_id"],
            revision_id=p["revision_id"], expected_version=p["version"], choice="approve",
            reviewed_exact_fax=True, current=f.current)


def test_dark_exact_ack_required_and_revocation_is_terminal(dark_fax):
    f = dark_fax
    g = grant(f)
    obs = observe(f, g)
    p = proposal(f, g, obs)
    with pytest.raises(WorkspaceError, match="fax_inbound_approval_changed"):
        ledger.decide(f.s, f.box, f.owner, key="dark-fax-not-reviewed", ticket_id=p["ticket_id"],
            revision_id=p["revision_id"], expected_version=p["version"], choice="approve",
            reviewed_exact_fax=False, current=f.current)
    f.s.rollback()
    ledger.revoke(f.s, f.box, f.owner, g["grant_id"], key="dark-fax-revoke-1")
    with pytest.raises(WorkspaceError, match="fax_inbound_permission_unavailable"):
        ledger.resolve(f.s, f.box, f.owner, key="dark-fax-observe-1", current=f.current)
    f.s.rollback()
    with pytest.raises(DBAPIError), f.s.begin_nested():
        f.s.execute(text("UPDATE fax_inbound_grants SET revoked_at=NULL WHERE id=:id"), {"id": g["grant_id"]})
    assert f.s.get(FaxInboundGrant, g["grant_id"]).revoked_at is not None
