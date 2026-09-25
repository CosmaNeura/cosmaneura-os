"""Real routine SQL on an owned local DB with an explicit hosted URL test double.

Only the engine URL observed by the connection gate is substituted. All owner,
source, mutation and report queries execute against the migrated test database;
this does not claim a hosted network or TLS connection.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from tests.integration.test_routines import configuration as schedule
from tests.integration.test_shared_work import delivered, people
from tests.unit.test_hosted_workspace_config import hosted
from tests.unit.test_routines_hosted_gate import HOSTED_DATABASE

from cosmas_os.application import follow_up, provider_team, routines, shared_work
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    Decision,
    FollowUpReceipt,
    Operation,
    PatientLink,
    RoutineRevision,
    RoutineRun,
    WorkHandoff,
)


class HostedSession:
    def __init__(self, session, url):
        self.session = session
        self.url = make_url(url)

    def get_bind(self):
        return SimpleNamespace(engine=SimpleNamespace(url=self.url))

    def __getattr__(self, name):
        return getattr(self.session, name)


def delivery_counts(session):
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model))
        for model in (Decision, Operation, FollowUpReceipt, WorkHandoff)
    }


def test_hosted_due_brief_and_readback_preserve_scope_and_delivery_guards(
    session, seeded, monkeypatch
):
    # Only this local fixture setup creates a synthetic delivered follow-up.
    case, item = delivered(session, seeded)
    box, owner = case[:2]
    unrelated_owner = people(session, box)[0]
    foreign = svc.provision_box(svc.Container(session), "Other invented routine practice")
    foreign_case, foreign_item = delivered(session, foreign)
    provider_team.save(
        session,
        box,
        owner,
        expected=0,
        key="hosted-routine-team",
        configuration=provider_team.default_configuration(),
    )
    configuration = hosted(
        database_url=HOSTED_DATABASE, beta_box_id=box, workspace_routines_enabled=True
    )
    configuration.validate_runtime_configuration()
    monkeypatch.setattr(routines, "settings", configuration)
    monkeypatch.setattr(follow_up, "settings", configuration)
    hosted_session = HostedSession(session, configuration.database_url)
    before = delivery_counts(session)

    saved = routines.save(
        hosted_session,
        box,
        owner,
        "chief",
        expected=0,
        team_revision=1,
        key="hosted-routine-schedule",
        configuration=schedule(),
    )
    revision = session.scalar(
        select(RoutineRevision).where(RoutineRevision.agent_id == saved["agent_id"])
    )
    due = revision.created_at.astimezone(UTC).replace(
        hour=8, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    monkeypatch.setattr(routines, "_now", lambda _session: due)

    result = routines.run_once(hosted_session, box, owner, "chief")
    assert result["status"] == "completed"
    report = routines.read_run(hosted_session, box, owner, "chief", result["run"]["id"])
    assert [row["ticket_id"] for row in report["items"]] == [item["ticket_id"]]
    assert report["counts"]["open"] == 1 and not report["model_used"]
    assert "Private invented agenda" not in str(report)
    assert foreign_item["ticket_id"] not in str(report)
    assert routines.run_once(hosted_session, box, owner, "chief")["status"] == "already_run"
    assert session.scalar(select(func.count()).select_from(RoutineRun)) == 1

    # The same read path cannot grant an unrelated colleague or Box access.
    assert (
        shared_work.catalog(hosted_session, box, unrelated_owner, vendor=True, _routine_read=True)[
            "items"
        ]
        == []
    )
    for selected_box, selected_owner in ((box, unrelated_owner), foreign_case[:2]):
        with pytest.raises(ws.WorkspaceError):
            routines.read_run(
                hosted_session, selected_box, selected_owner, "chief", result["run"]["id"]
            )
    with pytest.raises(ws.WorkspaceError):
        shared_work.catalog(hosted_session, foreign_case[0], owner, vendor=True, _routine_read=True)

    # A routine may observe old local evidence, but cannot create delivery effects.
    with pytest.raises(ws.WorkspaceError, match="follow_up_connection_required"):
        follow_up.deliver(
            hosted_session,
            box,
            owner,
            case[2]["id"],
            item["ticket_id"],
            revision_id=item["revision_id"],
            digest=item["payload_hash"],
        )
    with pytest.raises(ws.WorkspaceError, match="follow_up_connection_required"):
        shared_work.complete(
            hosted_session,
            box,
            owner,
            item["ticket_id"],
            revision_id=item["revision_id"],
            digest=item["payload_hash"],
            key="must-not-complete",
            evidence="Invented evidence",
        )
    assert delivery_counts(session) == before

    # Stored report context is still reauthorized against the current source.
    session.get(PatientLink, case[3]).revoked_at = datetime.now(UTC)
    session.commit()
    withdrawn = routines.read_run(hosted_session, box, owner, "chief", result["run"]["id"])
    assert withdrawn["items"] == [] and withdrawn["withheld_sources"]
    assert delivery_counts(session) == before
