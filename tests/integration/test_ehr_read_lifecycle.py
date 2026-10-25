"""Signed read disclosure races at the committed snapshot boundary."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_ehr_reads import (
    action,
    ehr_case,
    observe_body,
    observed,
    review,
    signed_workspace,
    verified,
    verify_body,
)

from cosmas_os.ehr_read_models import EhrReadBinding, EhrReadRequest, EhrReadSnapshot
from cosmas_os.models import EncounterWorkspace, PatientLink

__all__ = ["ehr_case", "signed_workspace"]


@pytest.mark.parametrize("kind", ["window", "verify"])
def test_committed_read_rechecks_binding_before_disclosing_receipt(ehr_case, monkeypatch, kind):
    f = ehr_case
    window = observed(f) if kind == "verify" else None
    command = verify_body(f, window) if window else observe_body(f)
    original_commit = Session.commit
    revoked = False

    def revoke_after_snapshot_commit(session):
        nonlocal revoked
        publish = not revoked and session is f.provider.session and session.scalar(
            select(EhrReadSnapshot.id).join(EhrReadRequest, EhrReadRequest.id == EhrReadSnapshot.observation_id)
            .where(EhrReadRequest.account_id == f.account, EhrReadRequest.kind == kind)) is not None
        original_commit(session)
        if publish:
            revoked = True
            binding = session.get(EhrReadBinding, f.binding_id)
            binding.state, binding.revoked_at = "revoked", datetime.now(UTC)
            original_commit(session)

    monkeypatch.setattr(Session, "commit", revoke_after_snapshot_commit)
    response = action(f, command)
    assert revoked, "Regression must revoke after a snapshot is durably committed"
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "ehr_read_binding_unavailable"}
    assert "Alex" not in response.text and "1980-01-02" not in response.text
    calls = len(f.provider.calls)
    read = f.s.scalar(select(EhrReadRequest).where(EhrReadRequest.account_id == f.account,
        EhrReadRequest.idempotency_key == command["idempotency_key"]))
    assert read is not None
    assert f.s.scalar(select(func.count()).select_from(EhrReadSnapshot).where(
        EhrReadSnapshot.observation_id == read.id)) == 1
    for recovery in ({"action": "inspect", "observation_id": read.id},
                     {"action": "resolve", "idempotency_key": command["idempotency_key"]}, command):
        recovered = action(f, recovery)
        assert recovered.status_code == 409 and "Alex" not in recovered.text
    assert len(f.provider.calls) == calls


def test_selected_visit_access_loss_blocks_read_and_review_recovery(ehr_case):
    f = ehr_case
    window = observed(f)
    visit = verified(f, window)
    assert review(f, visit).status_code == 200
    workspace = f.s.get(EncounterWorkspace, f.workspace["id"])
    link = f.s.get(PatientLink, workspace.patient_link_id)
    link.state, link.revoked_at = "revoked", datetime.now(UTC)
    f.s.commit()
    calls = len(f.provider.calls)
    for command in ({"action": "inspect", "observation_id": visit["observation_id"]},
                    {"action": "resolve", "idempotency_key": visit["observation_key"]},
                    verify_body(f, window)):
        result = action(f, command)
        assert result.status_code == 409 and result.json() == {"detail": "ehr_read_source_unavailable"}
        assert "Alex" not in result.text and "1980-01-02" not in result.text
    recovered = review(f, visit)
    assert recovered.status_code == 404 and recovered.json() == {"detail": "encounter_unavailable"}
    assert len(f.provider.calls) == calls
