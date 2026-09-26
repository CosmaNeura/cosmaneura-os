"""Installed activity routes: real signed verifier, PostgreSQL, and current access."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from tests.integration.test_model_activity import ledger, reserve, value
from tests.integration.test_model_work_admission import command
from tests.integration.test_model_work_api import case as _model_case
from tests.integration.test_workspace_capture import capture_case as capture_case

from cosmas_os.api import app as api
from cosmas_os.application import model_work, provider_team, workspace
from cosmas_os.config import Settings
from cosmas_os.models import EncounterWorkspace, ExternalIdentity, PatientLink, Principal

PATH = "/provider-team/activity/attention"
ORIGIN = "http://localhost:5173"
model_case = _model_case


@pytest.fixture
def installed(model_case):
    f = model_case
    f.box, f.owner = f.binding.box_id, f.binding.principal_id
    f.activity_headers = {
        **f.headers,
        "X-Cosmas-Draft-Recovery": "2",
        "Origin": ORIGIN,
    }
    return f


def error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json() == {"detail": code}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert len(response.content) <= 1024


def test_activity_default_is_independent_and_off():
    assert "workspace_ai_activity_enabled" in Settings.model_fields
    assert Settings(_env_file=None).workspace_ai_activity_enabled is False


def test_activity_routes_installed_only_as_two_exact_reads():
    found = {
        getattr(route, "path", ""): getattr(route, "methods", None)
        for route in api.app.routes
        if getattr(route, "path", "").startswith("/provider-team/activity")
    }
    assert found == {
        "/provider-team/activity/{view}": {"GET"},
        "/provider-team/activity/{view}/{cursor}": {"GET"},
    }


def test_default_off_then_on_history_without_model_or_setup_authority(installed):
    f = installed
    aid, _ = reserve(f)
    before = ledger(f)
    off = f.client.get(PATH, headers=f.activity_headers)
    error(off, 404, "activity_unavailable")
    assert aid not in off.text
    f.configuration.workspace_ai_activity_enabled = True
    f.configuration.workspace_llm_backend = "disabled"
    f.configuration.workspace_team_setup_enabled = False
    on = f.client.get(PATH, headers=f.activity_headers)
    page = value(on)
    assert on.headers["access-control-allow-origin"] == ORIGIN
    assert page["owner_id"] == f.owner
    assert [row["admission"]["id"] for row in page["rows"]] == [aid]
    identity = f.client.get("/provider-team/identity", headers=f.activity_headers).json()
    assert identity["actor_id"] == page["owner_id"]
    assert identity["recovery_scope"] == page["recovery_scope"]
    entry = page["rows"][0]["encounter"]
    current = f.client.get("/workspaces/" + entry["workspace_id"], headers=f.activity_headers)
    assert current.status_code == 200, current.text
    assert current.json()["appointment_id"] == entry["appointment_id"]
    assert before == ledger(f) and f.calls == []
    saved_team = f.client.get("/provider-team", headers=f.activity_headers)
    assert saved_team.status_code == 200, saved_team.text
    root = Path(os.environ["MODEL_ACTIVITY_EVIDENCE_ROOT"])
    root.mkdir(exist_ok=True)
    (root / "actual-main-activity.json").write_text(
        json.dumps(
            {
                "disabled": {"status": off.status_code, "body": off.json()},
                "enabled": page,
                "signed_identity": identity,
                "fresh_encounter": current.json(),
                "current_team": saved_team.json(),
                "model_calls": len(f.calls),
                "ledger_unchanged": before == ledger(f),
            },
            indent=2,
        )
        + "\n"
    )
    f.configuration.workspace_enabled = False
    error(f.client.get(PATH, headers=f.activity_headers), 404, "activity_unavailable")


def test_staff_owned_work_is_visible_without_an_admin_flag_and_peer_work_is_private(installed):
    f = installed
    f.configuration.workspace_ai_activity_enabled = True
    owner_aid, _ = reserve(f)
    with Session(f.engine) as session:
        staff = Principal(
            box_id=f.box,
            principal_type="human",
            display_name="Invented activity staff",
            is_owner=False,
        )
        session.add(staff)
        session.flush()
        binding = ExternalIdentity(
            box_id=f.box,
            principal_id=staff.id,
            provider="clerk",
            issuer=f.configuration.clerk_issuer,
            subject="user_activity_main_staff",
            organization_id=f.configuration.clerk_organization_id,
            reviewed_by="Invented reviewer",
            evidence_ref="synthetic:main-activity",
        )
        session.add(binding)
        session.flush()
        appointment = session.get(EncounterWorkspace, f.workspace["id"])
        assert appointment is not None
        staff_workspace = workspace.create(
            session, f.box, staff.id, appointment.appointment_id, "invented-activity-main-staff"
        )
        provider_team.save(
            session,
            f.box,
            staff.id,
            expected=0,
            key="invented-activity-staff-team",
            configuration=provider_team.default_configuration(),
        )
        staff_aid, _ = model_work.reserve_conversation(
            session,
            f.box,
            staff.id,
            staff_workspace["id"],
            external_identity_id=binding.id,
            **command(),
        )
        staff_id = staff.id
    headers = {
        **f.activity_headers,
        "Authorization": "Bearer " + f.token(sub="user_activity_main_staff"),
    }
    before = ledger(f)
    staff_page = value(f.client.get(PATH, headers=headers))
    owner_page = value(f.client.get(PATH, headers=f.activity_headers))
    assert staff_page["owner_id"] == staff_id
    assert [row["admission"]["id"] for row in staff_page["rows"]] == [staff_aid]
    assert [row["admission"]["id"] for row in owner_page["rows"]] == [owner_aid]
    assert f.owner not in json.dumps(staff_page) and owner_aid not in json.dumps(staff_page)
    assert staff_aid not in json.dumps(owner_page)
    foreign = f.client.get("/workspaces/" + f.workspace["id"], headers=headers)
    assert foreign.status_code == 404
    assert before == ledger(f) and f.calls == []


def test_revoked_identity_and_changed_patient_never_disclose_old_activity(installed):
    f = installed
    f.configuration.workspace_ai_activity_enabled = True
    aid, _ = reserve(f)
    assert value(f.client.get(PATH, headers=f.activity_headers))["rows"]
    with Session(f.engine) as session:
        patient = session.get(PatientLink, f.patient_link_id)
        assert patient is not None
        patient.revoked_at = datetime.now(UTC)
        session.commit()
    page = value(f.client.get(PATH, headers=f.activity_headers))
    assert page["rows"] == [] and page["coverage"]["withheld_total"] == 1
    assert aid not in json.dumps(page)
    with Session(f.engine) as session:
        binding = session.get(ExternalIdentity, f.identity_id)
        assert binding is not None
        binding.active = False
        session.commit()
    error(f.client.get(PATH, headers=f.activity_headers), 403, "activity_access_denied")


def test_patient_revocation_during_read_fences_main_app_disclosure(installed, monkeypatch):
    f = installed
    f.configuration.workspace_ai_activity_enabled = True
    reserve(f)
    original = model_work.usage

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        with Session(f.engine) as session:
            patient = session.get(PatientLink, f.patient_link_id)
            assert patient is not None
            patient.revoked_at = datetime.now(UTC)
            session.commit()
        return result

    monkeypatch.setattr(model_work, "usage", revoke)
    error(f.client.get(PATH, headers=f.activity_headers), 404, "activity_unavailable")
    assert f.calls == []


@pytest.mark.parametrize("change", ["identity", "feature"])
def test_final_main_app_authority_fence_rechecks_identity_and_feature(
    installed, monkeypatch, change
):
    f = installed
    f.configuration.workspace_ai_activity_enabled = True
    reserve(f)
    original = model_work.usage

    def change_authority(*args, **kwargs):
        result = original(*args, **kwargs)
        if change == "feature":
            f.configuration.workspace_ai_activity_enabled = False
        else:
            with Session(f.engine) as session:
                binding = session.get(ExternalIdentity, f.identity_id)
                assert binding is not None
                binding.active = False
                session.commit()
        return result

    monkeypatch.setattr(model_work, "usage", change_authority)
    status, code = (
        (403, "activity_access_denied") if change == "identity" else (404, "activity_unavailable")
    )
    error(f.client.get(PATH, headers=f.activity_headers), status, code)
    assert f.calls == []


def test_main_app_expired_signature_and_synthetic_identity_have_no_activity_access(installed):
    f = installed
    f.configuration.workspace_ai_activity_enabled = True
    reserve(f)
    before = ledger(f)
    expired = {
        **f.activity_headers,
        "Authorization": "Bearer " + f.token(exp=datetime.now(UTC) - timedelta(minutes=5)),
    }
    error(f.client.get(PATH, headers=expired), 401, "activity_authentication_required")
    f.configuration.auth_mode = "synth_headers"
    f.configuration.workspace_authenticated_enabled = False
    synthetic = {key: val for key, val in f.activity_headers.items() if key != "Authorization"}
    synthetic.update({"X-Box-Id": f.box, "X-Actor-Principal-Id": f.owner})
    error(f.client.get(PATH, headers=synthetic), 403, "activity_access_denied")
    assert before == ledger(f) and f.calls == []


@pytest.mark.parametrize(
    "case,status,code",
    [
        ("missing_team", 426, "team_contract_required"),
        ("duplicate_team", 426, "team_contract_required"),
        ("missing_recovery", 426, "workspace_client_update_required"),
        ("query", 422, "invalid_activity_request"),
        ("body", 422, "invalid_activity_request"),
        ("cursor", 422, "invalid_activity_request"),
        ("post", 405, "invalid_activity_request"),
        ("unsigned", 401, "activity_authentication_required"),
    ],
)
def test_main_app_contract_failures_have_closed_cors_envelopes(installed, case, status, code):
    f = installed
    f.configuration.workspace_ai_activity_enabled = True
    before = ledger(f)
    path, method, body = PATH, "GET", None
    headers = dict(f.activity_headers)
    if case == "missing_team":
        del headers["X-Cosmas-Team-Contract"]
    elif case == "missing_recovery":
        del headers["X-Cosmas-Draft-Recovery"]
    elif case == "unsigned":
        del headers["Authorization"]
    elif case == "query":
        path += "?next=anything"
    elif case == "body":
        body = b"{}"
    elif case == "cursor":
        path += "/unbounded-cursor"
    elif case == "post":
        method = "POST"
    pairs = list(headers.items())
    if case == "duplicate_team":
        pairs.append(("X-Cosmas-Team-Contract", "2"))
    error(f.client.request(method, path, headers=pairs, content=body), status, code)
    assert before == ledger(f) and f.calls == []


def test_activity_preflight_is_outermost_and_never_authenticates(installed):
    f = installed

    def forbidden():
        raise AssertionError("preflight has no identity or action authority")

    api.app.dependency_overrides[api._identity] = forbidden
    try:
        headers = {
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-cosmas-team-contract,x-cosmas-draft-recovery",
        }
        good = f.client.options(PATH, headers=headers)
        assert good.status_code == 200 and good.headers["access-control-allow-origin"] == ORIGIN
        denied = f.client.options(PATH, headers={**headers, "Origin": "https://unapproved.invalid"})
        assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers
    finally:
        api.app.dependency_overrides.pop(api._identity, None)
