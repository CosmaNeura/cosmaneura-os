"""Chief sees saved hosted proposals without interpreting approval as booking."""

from unittest.mock import Mock

from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.integration.test_appointment_execution_api import signed_case as _signed_case
from tests.integration.test_hosted_appointment_proposals import (
    capture_case as _capture_case,
)
from tests.integration.test_hosted_appointment_proposals import (
    decide,
    proposed,
)
from tests.integration.test_hosted_appointment_proposals import (
    proposal_case as _proposal_case,
)
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.application import appointment_execution as execution
from cosmas_os.application import operations_status as operations
from cosmas_os.application import workspace as ws
from cosmas_os.models import ExternalIdentity, Operation

capture_case = _capture_case
proposal_case = _proposal_case
signed_case = _signed_case
signed_workspace = _signed_workspace


def test_chief_reads_current_hosted_proposal_with_matching_commitment(proposal_case, monkeypatch):
    f = proposal_case
    item = decide(f, proposed(f))
    monkeypatch.setattr(operations, "runtime", f.configuration)
    with Session(f.engine) as s:
        snapshot = ws.read(s, f.box, f.owner, f.wid)
        # Link projection only: this test does not manufacture a patient mapping
        # or mutate clinical entries to make the operation available.
        snapshot["entries"].append({"kind": "work_link", "id": "invented-selector",
            "ticket": {"id": item["ticket_id"], "lane": "scheduling_appointment"}})
        current = operations.read(s, f.box, f.owner, f.wid, kind="scheduling",
            record_id=item["ticket_id"], configuration=f.configuration)
        linked = operations.linked(s, f.box, f.owner, f.wid, snapshot, {"role": "chief"})
        assert len(linked) == 1
        assert {k: v for k, v in linked[0].items() if k != "observed_at"} == {
            k: v for k, v in current.items() if k != "observed_at"}
        assert current["state"] == "approved"
        assert current["next_step"]["code"] == "review_saved_proposal"
        assert current["evidence"]["external_outcome"] == "not_established"
        assert current["evidence"]["commitment"]
        assert "not available yet" in current["next_step"]["label"]
    assert len(f.receiver.calls) == 1


def test_reauthentication_releases_sql_before_local_receiver_dispatch(session, signed_case):
    signed, case = signed_case
    def reauthenticate():
        assert session.scalar(select(ExternalIdentity.id).where(ExternalIdentity.id == case.identity))
        assert session.in_transaction()
    port = Mock()
    def submit(operation):
        assert not session.in_transaction()
        return case.port.result(operation)
    port.submit.side_effect = submit
    result = execution.run(session, signed.box, signed.actor, case.wid, case.item["ticket_id"],
        external_identity_id=case.identity, reauthenticate=reauthenticate, port=port,
        operation_id=case.approved["operation_id"], revision_id=case.item["revision_id"],
        digest=case.item["payload_hash"], mode="submit", configuration=signed.configuration)
    assert result["appointment_saved"] and port.submit.call_count == 1
    assert session.get(Operation, result["operation_id"]).status == "succeeded"
