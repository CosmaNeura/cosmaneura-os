"""Shared account projections use real sealed Google custody without lock upgrades."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from tests.unit.test_google_full_mail_consent import FULL_SCOPES, full_start
from tests.unit.test_personal_connection_failure import connection as connection

from cosmas_os.adapters.google_connection import GooglePersonalConnection
from cosmas_os.application import google_message as messages
from cosmas_os.application import workspace as ws
from cosmas_os.models import AppointmentObservation, EncounterWorkspace, PatientLink


@pytest.mark.parametrize("connection", [GooglePersonalConnection], indirect=True)
def test_two_workspace_readers_share_current_sealed_account_without_upgrade_deadlock(
    connection, monkeypatch
):
    f = connection
    f.scopes = FULL_SCOPES
    fields = full_start(f)
    assert f.service.callback(fields["state"][0], "synthetic_PRIVATE_code")
    wids = []
    with f.factory() as session:
        for _ in range(2):
            link = PatientLink(
                box_id=f.identity.box_id,
                source_pair_key="concurrent-google:" + str(uuid4()),
                label="Invented reader",
                state="confirmed",
                confirmed_by_principal_id=f.identity.principal_id,
                attested_at=datetime.now(UTC),
            )
            session.add(link)
            session.flush()
            appointment = AppointmentObservation(
                box_id=f.identity.box_id,
                patient_link_id=link.id,
                external_id=str(uuid4()),
                source="synthetic",
                start_at=datetime.now(UTC),
                patient_label="Invented reader",
            )
            session.add(appointment)
            session.commit()
            wids.append(
                ws.create(
                    session,
                    f.identity.box_id,
                    f.identity.principal_id,
                    appointment.id,
                    "reader:" + str(uuid4()),
                )["id"]
            )
    checkpoint = Barrier(2)
    original_human = ws._human
    first_seen = set()

    def human(s, box, actor, *, creating=False):
        result = original_human(s, box, actor, creating=creating)
        if not creating and id(s) not in first_seen:
            first_seen.add(id(s))
            checkpoint.wait(timeout=5)
        return result

    monkeypatch.setattr(ws, "_human", human)
    before = len(f.requests)

    def reader(wid):
        with f.factory() as session:
            session.execute(text("SET LOCAL lock_timeout='2s'"))
            workspace = session.get(EncounterWorkspace, wid)
            ws._workspace(session, f.identity.box_id, f.identity.principal_id, wid)
            account = messages._identity(
                session, f.identity.box_id, f.identity.principal_id, f.account
            )
            binding = f.service.message_binding(f.identity, require_full=True, session=session)
            assert binding.account_id == account.id and workspace.id == wid
            status = f.service.message_status(f.identity, session=session)
            assert status["full_mail_read"] is True
            return binding.grant_sha256

    # Exiting the executor drains both requests even when an assertion fails.
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(reader, wids))
    assert outputs[0] == outputs[1] and len(f.requests) == before
