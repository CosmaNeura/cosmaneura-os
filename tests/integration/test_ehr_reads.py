"""Real SQL and signed API EHR source journey with an in-process Elation fixture."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from tests.integration.test_handoff_review import isolate_http_request, request_sessions
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.adapters.elation_read import SCOPES, ElationReadScope
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.api import app as api_module
from cosmas_os.application import ehr_reads as ehr
from cosmas_os.application import provider_team
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.ehr_read_models import EhrReadBinding, EhrReadRequest, EhrReadSnapshot

signed_workspace = _signed_workspace


class InventedElation:
    def __init__(self, session):
        self.session = session
        self.calls = []
        self.fail = False
        self.more = False
        self.after = lambda: None
        self.change_appointment = lambda row: row
        self.change_patient = lambda row: row
        self.starts_at = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)

    def appointment(self):
        return self.change_appointment(dict(id=940, practice=910, patient=930, physician=920,
            scheduled_date=self.starts_at.isoformat().replace("+00:00", "Z"), duration=30,
            status={"status": "Confirmed"}, time_slot_type="appointment", deleted_date=None))

    def __call__(self, request):
        assert not self.session.in_transaction(), "No SQL transaction may cross provider I/O"
        assert request.url.host == "sandbox.elationemr.com"
        self.calls.append((request.method, request.url.path))
        if request.url.path == "/api/2.0/oauth2/token/":
            assert request.method == "POST"
            return httpx.Response(200, json=dict(access_token="synthetic-token", token_type="Bearer",
                expires_in=3600, scope=SCOPES))
        assert request.method == "GET"
        self.after()
        if self.fail:
            raise httpx.ReadTimeout("invented provider failure", request=request)
        if request.url.path == "/api/2.0/practices/910/":
            return httpx.Response(200, json=dict(id=910, name="Invented Elation Clinic", status="active",
                timezone="UTC", physicians=[920]))
        if request.url.path == "/api/2.0/appointments/":
            self.starts_at = datetime.fromisoformat(request.url.params["from_date"].replace("Z", "+00:00")) + timedelta(minutes=30)
            return httpx.Response(200, json=dict(results=[self.appointment()], previous=None,
                next="https://sandbox.elationemr.com/api/2.0/appointments/?cursor=synthetic-next" if self.more else None))
        if request.url.path == "/api/2.0/appointments/940/":
            return httpx.Response(200, json=self.appointment())
        if request.url.path == "/api/2.0/patients/930/":
            return httpx.Response(200, json=self.change_patient(dict(id=930, caregiver_practice=910,
                first_name="Alex", last_name="Example", dob="1980-01-02", primary_physician=920, deleted_date=None)))
        raise AssertionError("Unexpected synthetic endpoint")


@pytest.fixture
def ehr_case(signed_workspace, session, monkeypatch):
    """Compact signed TestClient fixture also reused by the root's actual-UI lab.

    f.client/token/workspace are the existing signed workspace helper; f.headers()
    returns fresh authenticated EHR headers. f.provider is a deterministic
    MockTransport handler, f.binding the DB record, f.port the synthetic runtime.
    No model, Scribe or external service is installed.
    """
    f = signed_workspace
    monkeypatch.setattr(f.configuration, "workspace_ehr_read_enabled", True)
    monkeypatch.setattr(provider_team, "runtime_settings", f.configuration)
    scope = ElationReadScope(UUID(f.box), UUID(f.actor), uuid4(), uuid4(), 910, "Invented Elation Clinic")
    binding = EhrReadBinding(box_id=f.box, owner_id=f.actor, account_id=f.binding.id,
        vendor="elation", connection_id=str(scope.connection_id), credential_generation=str(scope.credential_generation),
        practice_id="910", practice_name=scope.practice_name, environment="sandbox",
        binding_digest=scope.commitment(), state="active")
    session.add(binding)
    session.commit()
    provider = InventedElation(session)
    port = SyntheticElationReads((scope,), httpx.MockTransport(provider),
        enabled=lambda: f.configuration.workspace_ehr_read_available)
    monkeypatch.setattr(api_module.app.state, "ehr_reads", port, raising=False)
    fresh_sessions = request_sessions(session)

    def request_session():
        for owned in fresh_sessions():
            provider.session = owned
            try:
                yield owned
            finally:
                provider.session = session

    monkeypatch.setitem(api_module.app.dependency_overrides, api_module.get_session, request_session)
    monkeypatch.setattr(f.client, "request", isolate_http_request(f.client, session))
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = SimpleNamespace(client=f.client, token=f.token, workspace=f.workspace, box=f.box, owner=f.actor,
        account=f.binding.id, configuration=f.configuration, binding=binding, binding_id=binding.id, scope=scope, port=port,
        provider=provider, s=session, starts_at=start, ends_at=start + timedelta(days=1))
    result.headers = lambda: {"Authorization": "Bearer " + f.token(), "X-Cosmas-Ehr-Read": "1"}
    with ehr.install_runtime_reader(lambda: port):
        yield result


def observe_body(f, key="ehr-observe-1", **changes):
    return dict(action="observe", connection_id=str(f.scope.connection_id), binding_sha256=f.scope.commitment(),
        starts_at=f.starts_at.isoformat(), ends_at=f.ends_at.isoformat(), idempotency_key=key, **changes)


def action(f, body):
    return f.client.post("/connections/ehr/reads", headers=f.headers(), json=body)


def observed(f, key="ehr-observe-1"):
    response = action(f, observe_body(f, key))
    assert response.status_code == 200, response.text
    return response.json()


def verify_body(f, receipt, key="ehr-verify-1"):
    item = receipt["observation"]["items"][0]
    return dict(action="verify", connection_id=str(f.scope.connection_id), binding_sha256=f.scope.commitment(),
        observation_id=receipt["observation_id"], observation_sha256=receipt["source_sha256"],
        item_handle=item["handle"], item_sha256=item["sha256"], idempotency_key=key)


def verified(f, receipt=None, key="ehr-verify-1"):
    receipt = observed(f) if receipt is None else receipt
    response = action(f, verify_body(f, receipt, key))
    assert response.status_code == 200, response.text
    return response.json()


def review_body(f, receipt, key="ehr-review-1"):
    item = receipt["observation"]["item"]
    return dict(expected_revision=f.workspace["revision"], idempotency_key=key,
        observation_id=receipt["observation_id"], observation_sha256=receipt["source_sha256"],
        item_handle=item["handle"], item_sha256=item["sha256"], reviewed_visit=True,
        reviewed_patient_identity=True, reviewed_exact_snapshot=True, reviewed_untrusted_source=True)


def review(f, receipt, body=None):
    return f.client.post(f"/workspaces/{f.workspace['id']}/ehr-read/review", headers=f.headers(),
        json=review_body(f, receipt) if body is None else body)


def revoke(f):
    session = f.provider.session
    binding = session.get(EhrReadBinding, f.binding_id)
    assert binding is not None
    binding.state = "revoked"
    binding.revoked_at = datetime.now(UTC)
    session.commit()


def test_status_is_honest_default_off_and_never_contacts_a_provider(ehr_case):
    f = ehr_case
    response = action(f, {"action": "status"})
    assert response.status_code == 200
    assert response.json()["status"] == "ready" and response.json()["mode"] == "synthetic"
    f.configuration.workspace_ehr_read_enabled = False
    assert action(f, {"action": "status"}).json()["status"] == "not_enabled"
    assert action(f, observe_body(f)).status_code == 404
    assert f.provider.calls == []


def test_signed_window_verification_review_and_exact_recovery_use_one_shared_source(ehr_case):
    f = ehr_case
    window = observed(f)
    assert window["connection_id"] == str(f.scope.connection_id)
    assert window["binding_sha256"] == f.scope.commitment()
    assert window["payload_sha256"] == payload_hash(window["observation"])
    assert "patient_id" not in str(window) and "Alex" not in str(window)
    assert len(f.provider.calls) == 3
    visit = verified(f, window)
    assert visit["observation"]["item"]["patient"] == {
        "first_name": "Alex", "last_name": "Example", "birth_date": "1980-01-02"}
    assert len(f.provider.calls) == 6
    for receipt in (window, visit):
        assert action(f, {"action": "inspect", "observation_id": receipt["observation_id"]}).json() == receipt
        assert action(f, {"action": "resolve", "idempotency_key": receipt["observation_key"]}).json() == receipt
    assert action(f, observe_body(f)).json() == window
    assert action(f, verify_body(f, window)).json() == visit
    saved = review(f, visit)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()
    assert receipt["source_withheld"] is False
    entry = next(row for row in receipt["workspace"]["entries"] if row["id"] == receipt["entry_id"])
    assert entry["kind"] == "ehr_read_source" and entry["ehr_source_state"] == "current"
    assert entry["content"] == ehr.source_content(visit["observation"])
    replayed = review(f, visit).json()
    for field in ("entry_id", "entry_revision", "source", "request_sha256", "source_withheld"):
        assert replayed[field] == receipt[field]
    assert replayed["workspace"]["revision"] == receipt["workspace"]["revision"]
    assert next(row for row in replayed["workspace"]["entries"] if row["id"] == receipt["entry_id"]) == entry
    assert len(f.provider.calls) == 6
    assert f.s.scalar(select(func.count()).select_from(EhrReadRequest).where(EhrReadRequest.account_id == f.account)) == 2


def test_timeout_reservation_survives_without_repeat_and_resolves_unconfirmed(ehr_case):
    f = ehr_case
    f.provider.fail = True
    failed = action(f, observe_body(f))
    assert failed.status_code == 503 and failed.json()["detail"] == "ehr_read_timeout"
    calls = len(f.provider.calls)
    f.provider.fail = False
    resolved = action(f, {"action": "resolve", "idempotency_key": "ehr-observe-1"})
    assert resolved.json()["status"] == "unconfirmed"
    replay = action(f, observe_body(f))
    assert replay.status_code == 503 and replay.json()["detail"] == "ehr_read_unconfirmed"
    assert len(f.provider.calls) == calls
    assert action(f, {"action": "resolve", "idempotency_key": "missing-1"}).json()["status"] == "not_found"


def test_exact_pending_request_cannot_be_reused_with_new_dates(ehr_case):
    f = ehr_case
    observed(f)
    body = observe_body(f)
    body["ends_at"] = (f.ends_at + timedelta(days=1)).isoformat()
    calls = len(f.provider.calls)
    response = action(f, body)
    assert response.status_code == 409 and response.json()["detail"] == "idempotency_conflict"
    assert len(f.provider.calls) == calls


def test_changed_appointment_or_foreign_practice_patient_never_creates_verified_snapshot(ehr_case):
    f = ehr_case
    window = observed(f)
    f.provider.change_appointment = lambda row: {**row, "patient": 931}
    result = action(f, verify_body(f, window))
    assert result.status_code == 503 and result.json()["detail"] == "ehr_read_record_unavailable"
    assert not any(path.startswith("/api/2.0/patients/") for _, path in f.provider.calls)
    f.provider.change_appointment = lambda row: row
    f.provider.change_patient = lambda row: {**row, "caregiver_practice": 911}
    result = action(f, verify_body(f, window, "ehr-verify-foreign"))
    assert result.status_code == 503 and result.json()["detail"] == "ehr_read_response_invalid"
    assert f.s.scalar(select(func.count()).select_from(EhrReadSnapshot).join(EhrReadRequest,
        EhrReadRequest.id == EhrReadSnapshot.observation_id).where(EhrReadRequest.account_id == f.account)) == 1


def test_partial_page_is_explicit_and_browser_cannot_request_continuation(ehr_case):
    f = ehr_case
    f.provider.more = True
    window = observed(f)
    assert window["observation"]["coverage"] == "more_rows_available"
    calls = len(f.provider.calls)
    body = observe_body(f, "ehr-more-1")
    body["cursor"] = "synthetic-next"
    assert action(f, body).status_code == 422
    assert len(f.provider.calls) == calls
    visit = verified(f, window)
    assert "Showing this page; more appointments may be available." in ehr.source_content(visit["observation"])


def test_revoke_hides_read_content_and_review_replay_returns_masked_same_receipt(ehr_case):
    f = ehr_case
    visit = verified(f)
    saved = review(f, visit).json()
    calls = len(f.provider.calls)
    revoke(f)
    inspected = action(f, {"action": "inspect", "observation_id": visit["observation_id"]})
    assert inspected.status_code == 409 and "Alex" not in inspected.text
    recovered = review(f, visit)
    assert recovered.status_code == 200, recovered.text
    result = recovered.json()
    assert result["entry_id"] == saved["entry_id"] and result["source_withheld"] is True
    entry = next(row for row in result["workspace"]["entries"] if row["id"] == saved["entry_id"])
    assert entry["content"] == "" and entry["ehr_source_state"] == "unavailable"
    assert len(f.provider.calls) == calls


def test_revocation_during_io_withholds_entire_response(ehr_case):
    f = ehr_case
    f.provider.after = lambda: revoke(f)
    response = action(f, observe_body(f))
    assert response.status_code == 503 and response.json()["detail"] == "ehr_read_binding_changed"
    assert "Alex" not in response.text


def test_window_refresh_supersedes_previous_verified_source_without_erasing_history(ehr_case):
    f = ehr_case
    visit = verified(f)
    saved = review(f, visit).json()
    observed(f, "ehr-window-new")
    response = action(f, {"action": "inspect", "observation_id": visit["observation_id"]})
    assert response.status_code == 409 and response.json()["detail"] == "ehr_read_superseded"
    workspace = ws.read(f.s, f.box, f.owner, f.workspace["id"])
    entry = next(row for row in workspace["entries"] if row["id"] == saved["entry_id"])
    assert entry["ehr_source_state"] == "unavailable" and entry["content"] == ""


@pytest.mark.parametrize("field,value", [("reviewed_patient_identity", 1), ("reviewed_visit", False),
                                        ("reviewed_exact_snapshot", "true"), ("reviewed_untrusted_source", None)])
def test_review_requires_exact_human_confirmations(ehr_case, field, value):
    f = ehr_case
    visit = verified(f)
    body = review_body(f, visit)
    body[field] = value
    calls = len(f.provider.calls)
    assert review(f, visit, body).status_code == 422
    assert len(f.provider.calls) == calls


def test_forged_item_and_reading_another_account_fail_before_io(ehr_case):
    f = ehr_case
    window = observed(f)
    body = verify_body(f, window)
    body["item_handle"] = str(uuid4())
    calls = len(f.provider.calls)
    assert action(f, body).status_code == 409
    foreign = deepcopy(observe_body(f, "ehr-foreign-1"))
    foreign["connection_id"] = str(uuid4())
    assert action(f, foreign).status_code == 409
    invalid = f.client.post("/connections/ehr/reads", json=observe_body(f),
        headers={"Authorization": "Bearer " + f.token(sub="unbound-user"), "X-Cosmas-Ehr-Read": "1"})
    assert invalid.status_code == 403
    assert len(f.provider.calls) == calls


def test_actual_signed_route_requires_authentication_and_contract_header(ehr_case):
    f = ehr_case
    assert f.client.post("/connections/ehr/reads", json=observe_body(f)).status_code == 401
    response = f.client.post("/connections/ehr/reads", headers={"Authorization": "Bearer " + f.token()},
        json=observe_body(f))
    assert response.status_code == 422 and response.json()["detail"] == "invalid_ehr_read_request"
    assert f.provider.calls == []


def test_changed_installed_timezone_cannot_reopen_an_old_patient_snapshot(ehr_case):
    f = ehr_case
    visit = verified(f)
    calls = len(f.provider.calls)
    f.port.timezone = "America/New_York"
    response = action(f, {"action": "inspect", "observation_id": visit["observation_id"]})
    assert response.status_code == 409 and response.json()["detail"] == "ehr_read_binding_changed"
    assert "Alex" not in response.text and len(f.provider.calls) == calls
