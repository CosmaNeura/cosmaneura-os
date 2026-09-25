"""Actual private matching workspace choices; no Inbox source submission."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.integration.test_inbox_work import ON, headers, ingest, snapshot, triage
from tests.integration.test_inbox_work import inbox_case as inbox_case
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.api import app as api
from cosmas_os.api import inbox_review_routes as routes
from cosmas_os.api import inbox_work_routes as base
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import inbox_review_options as options
from cosmas_os.application import inbox_work as flow
from cosmas_os.application import workspace as ws
from cosmas_os.models import AppointmentObservation, PatientLink, Principal


@pytest.fixture
def client(session, inbox_case):
    app = FastAPI()
    app.dependency_overrides[api.get_session] = lambda: session
    for module in (base, routes):
        module.register(
            app,
            api.get_session,
            api._identity,
            policy_dependency=lambda: ON,
            registry_dependency=lambda: inbox_case["registry"],
        )
    with TestClient(app) as current:
        yield current


def test_only_owned_matching_patient_options_are_offered(session, inbox_case, client, tmp_path):
    c = inbox_case
    iid = ingest(session, c)["item_id"]
    foreign_link = PatientLink(
        box_id=c["box"],
        source_pair_key=str(uuid4()),
        label="Unrelated invented patient",
        state="confirmed",
        confirmed_by_principal_id=c["actor"],
        attested_at=datetime.now(UTC),
    )
    session.add(foreign_link)
    session.flush()
    appointment = AppointmentObservation(
        box_id=c["box"],
        patient_link_id=foreign_link.id,
        external_id=str(uuid4()),
        source="synthetic",
        start_at=datetime.now(UTC),
        patient_label="Unrelated private encounter",
    )
    session.add(appointment)
    session.commit()
    unrelated = ws.create(session, c["box"], c["actor"], appointment.id, "unrelated-inbox-options")
    result = client.get("/inbox/" + iid + "/review-options", headers=headers(c))
    assert result.status_code == 200, result.text
    value = result.json()
    assert [x["workspace_id"] for x in value["choices"]] == [c["wid"]]
    assert unrelated["id"] not in result.text and "Unrelated private encounter" not in result.text
    assert value["patient_link_id"] == c["correspondence"].patient_link_id
    unsigned = {k: v for k, v in value.items() if k != "options_sha256"}
    assert value["options_sha256"] == public.public_digest(
        "cosmas-inbox-review-options.v1", unsigned
    )
    assert value["choices"][0]["expected_workspace_revision"] == 3
    (tmp_path / "actual-inbox-review-options.json").write_text(json.dumps(value, indent=2))


@pytest.mark.parametrize("mode", ["staff", "peer", "registry", "disabled", "conflict", "failure"])
def test_options_deny_missing_authority_and_ambiguous_source(session, inbox_case, client, mode):
    c = inbox_case
    iid = ingest(session, c)["item_id"]
    if mode in {"staff", "peer"}:
        person = Principal(
            box_id=c["box"],
            principal_type="human",
            display_name="Other local human",
            state="active",
            is_owner=mode == "peer",
        )
        session.add(person)
        session.commit()
        r = client.get("/inbox/" + iid + "/review-options", headers=headers(c, person.id))
        assert r.status_code == 404
    else:
        if mode == "registry":
            c["registry_state"]["registry"] = flow.EMPTY_REGISTRY
        elif mode == "conflict":
            ingest(session, c, snapshot(c, text_="Equal version conflict"))
        elif mode == "failure":
            flow.read_failed(
                session,
                c["grant"],
                "options-failed-read",
                "response_invalid",
                registry=c["registry"],
                policy=ON,
            )
        with pytest.raises(ws.WorkspaceError):
            options.read(
                session,
                c["box"],
                c["actor"],
                iid,
                registry=c["registry"],
                policy=flow.DEFAULT_POLICY if mode == "disabled" else ON,
            )


def test_final_options_disclosure_rechecks_registry(session, inbox_case):
    c = inbox_case
    iid = ingest(session, c)["item_id"]
    session.info["inbox_final_authority"] = lambda: c["registry_state"].update(
        registry=flow.EMPTY_REGISTRY
    )
    with pytest.raises(ws.WorkspaceError, match="inbox_binding_unavailable"):
        options.read(session, c["box"], c["actor"], iid, registry=c["registry"], policy=ON)
    session.info.pop("inbox_final_authority")


def test_options_bind_new_source_and_refuse_exhausted_review_capacity(session, inbox_case):
    c = inbox_case
    iid = ingest(session, c)["item_id"]
    before = options.read(session, c["box"], c["actor"], iid, registry=c["registry"], policy=ON)
    ingest(session, c, snapshot(c, 1, text_="A changed incoming source"))
    after = options.read(session, c["box"], c["actor"], iid, registry=c["registry"], policy=ON)
    assert after["source_id"] != before["source_id"]
    assert after["source_sha256"] != before["source_sha256"]
    assert after["item_version"] == before["item_version"] + 1
    assert after["options_sha256"] != before["options_sha256"]
    for _ in range(94):
        triage(session, c, iid, "source_exception")
    with pytest.raises(ws.WorkspaceError, match="inbox_history_limit"):
        options.read(session, c["box"], c["actor"], iid, registry=c["registry"], policy=ON)
