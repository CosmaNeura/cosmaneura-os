from __future__ import annotations

import pytest

from cosmas_os.adapters.azure import AzureBlobAdapter
from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.application import services as svc
from cosmas_os.application.seed import SYNTH_CSV
from cosmas_os.config import settings
from cosmas_os.domain.enums import (
    DecisionKind,
    OperationStatus,
    PrincipalState,
    PrincipalType,
    TicketState,
)
from cosmas_os.domain.rules import AuthorizationError, DomainError
from cosmas_os.models import ActionRevision, Operation, Principal


def _open_ticket(container: svc.Container, seeded: dict[str, object]):
    box_id = str(seeded["box_id"])
    owner_id = str(seeded["owner_id"])
    agents = seeded["agents"]
    assert isinstance(agents, dict)
    chaser_id = str(agents["chaser"])
    appointment_id = svc.import_schedule(container, box_id, SYNTH_CSV)[0]
    link = svc.attest_patient_link(
        container,
        box_id,
        owner_id,
        "csv:jordan-lee",
        "Jordan Lee",
    )
    ticket = svc.detect_and_open_chase(
        container,
        box_id,
        chaser_id,
        appointment_id,
        link.id,
    )
    return ticket, link


def _add_human(
    container: svc.Container,
    box_id: str,
    *,
    name: str,
    state: PrincipalState = PrincipalState.ACTIVE,
    is_owner: bool = False,
) -> Principal:
    human = Principal(
        box_id=box_id,
        principal_type=PrincipalType.HUMAN.value,
        display_name=name,
        state=state.value,
        is_owner=is_owner,
    )
    container.session.add(human)
    container.session.commit()
    return human


def test_cross_box_principals_cannot_mutate_ticket_or_box_resources(container, seeded):
    ticket, link = _open_ticket(container, seeded)
    other = svc.provision_box(container, "Other Clinic")
    other_owner_id = str(other["owner_id"])

    with pytest.raises(AuthorizationError, match="outside the Box"):
        svc.edit_revision(container, ticket.id, other_owner_id, "Cross-Box edit")
    with pytest.raises(AuthorizationError, match="outside the Box"):
        svc.decide(container, ticket.id, other_owner_id, DecisionKind.APPROVE)
    with pytest.raises(AuthorizationError, match="outside the Box"):
        svc.simulate_upload_and_verify(container, ticket.id, other_owner_id, b"front", b"back")
    with pytest.raises(AuthorizationError, match="outside the Box"):
        svc.close_ticket(container, ticket.id, other_owner_id)
    with pytest.raises(AuthorizationError, match="outside the Box"):
        svc.revoke_patient_link(container, link.id, other_owner_id)
    with pytest.raises(AuthorizationError, match="outside the Box"):
        svc.disable_agent(container, other_owner_id, str(seeded["agents"]["chaser"]))


def test_chase_rejects_cross_box_agent_and_patient_link(container, seeded):
    box_id = str(seeded["box_id"])
    appointment_id = svc.import_schedule(container, box_id, SYNTH_CSV)[0]
    other = svc.provision_box(container, "Other Clinic")
    other_link = svc.attest_patient_link(
        container,
        str(other["box_id"]),
        str(other["owner_id"]),
        "csv:other-patient",
        "Other Patient",
    )

    with pytest.raises(AuthorizationError, match="outside the Box"):
        svc.detect_and_open_chase(
            container,
            box_id,
            str(other["agents"]["chaser"]),
            appointment_id,
            other_link.id,
        )
    with pytest.raises(DomainError, match="unconfirmed PatientLink"):
        svc.detect_and_open_chase(
            container,
            box_id,
            str(seeded["agents"]["chaser"]),
            appointment_id,
            other_link.id,
        )


@pytest.mark.parametrize("state", [PrincipalState.DISABLED, PrincipalState.TOMBSTONED])
def test_inactive_human_cannot_act(container, seeded, state: PrincipalState):
    ticket, link = _open_ticket(container, seeded)
    owner = container.session.get(Principal, str(seeded["owner_id"]))
    assert owner is not None
    owner.state = state.value
    container.session.commit()

    with pytest.raises(AuthorizationError, match="active human"):
        svc.edit_revision(container, ticket.id, owner.id, "Inactive edit")
    with pytest.raises(AuthorizationError, match="active human"):
        svc.decide(container, ticket.id, owner.id, DecisionKind.APPROVE)
    with pytest.raises(AuthorizationError, match="active human"):
        svc.disable_agent(container, owner.id, str(seeded["agents"]["chaser"]))
    with pytest.raises(AuthorizationError, match="active human"):
        svc.revoke_patient_link(container, link.id, owner.id)


def test_active_human_member_can_edit_and_approve_but_not_administer_box(container, seeded):
    ticket, link = _open_ticket(container, seeded)
    staff = _add_human(container, str(seeded["box_id"]), name="Staff Member")

    revision = svc.edit_revision(container, ticket.id, staff.id, "Reviewed synthetic edit")
    decision = svc.decide(
        container,
        ticket.id,
        staff.id,
        DecisionKind.APPROVE,
        expected_revision_id=revision.id,
    )

    assert decision["decision"] == "approved"
    assert decision["operation_id"]
    with pytest.raises(AuthorizationError, match="owner authority"):
        svc.disable_agent(container, staff.id, str(seeded["agents"]["chaser"]))
    with pytest.raises(AuthorizationError, match="owner authority"):
        svc.revoke_patient_link(container, link.id, staff.id)


@pytest.mark.parametrize("entrypoint", ["execute", "reconcile"])
def test_operation_rejects_cross_box_relationships(container, seeded, entrypoint: str):
    ticket, _ = _open_ticket(container, seeded)
    other = svc.provision_box(container, "Other Clinic")
    revision = container.session.get(ActionRevision, ticket.current_revision_id)
    assert revision is not None
    ticket.state = TicketState.APPROVED.value
    operation = Operation(
        box_id=str(other["box_id"]),
        ticket_id=ticket.id,
        action_revision_id=revision.id,
        idempotency_key=f"op:{revision.id}",
        adapter="notify",
        status=(
            OperationStatus.PENDING.value
            if entrypoint == "execute"
            else OperationStatus.UNKNOWN.value
        ),
    )
    container.session.add(operation)
    container.session.commit()

    with pytest.raises(DomainError, match="operation scope mismatch"):
        if entrypoint == "execute":
            svc.execute_operation(container, operation.id)
        else:
            svc.reconcile_unknown(container, operation.id)
    assert container.notify.attempts == {}


def test_timeline_rejects_ticket_from_another_box(container, seeded):
    ticket, _ = _open_ticket(container, seeded)
    other = svc.provision_box(container, "Other Clinic")

    with pytest.raises(AuthorizationError, match="outside the Box"):
        svc.audit_timeline(container, str(other["box_id"]), ticket.id)

    timeline = svc.audit_timeline(container, str(seeded["box_id"]), ticket.id)
    assert any(event["event_type"] == "ticket.opened" for event in timeline)


def test_edit_rejects_cross_box_current_revision(container, seeded):
    ticket, _ = _open_ticket(container, seeded)
    other = svc.provision_box(container, "Other Clinic")
    other_ticket, _ = _open_ticket(container, other)
    other_revision = container.session.get(ActionRevision, other_ticket.current_revision_id)
    assert other_revision is not None
    ticket.current_revision_id = other_revision.id
    container.session.commit()

    with pytest.raises(DomainError, match="revision scope mismatch"):
        svc.edit_revision(container, ticket.id, str(seeded["owner_id"]), "Cross-Box edit")
    assert other_revision.invalidated is False


def test_upload_rejects_cross_box_appointment(container, seeded):
    ticket, _ = _open_ticket(container, seeded)
    other = svc.provision_box(container, "Other Clinic")
    other_appointment_id = svc.import_schedule(container, str(other["box_id"]), SYNTH_CSV)[0]
    ticket.appointment_id = other_appointment_id
    container.session.commit()

    with pytest.raises(DomainError, match="appointment scope mismatch"):
        svc.simulate_upload_and_verify(
            container,
            ticket.id,
            str(seeded["owner_id"]),
            b"front",
            b"back",
        )


def test_owner_can_still_disable_and_revoke(container, seeded):
    _, link = _open_ticket(container, seeded)

    svc.disable_agent(container, str(seeded["owner_id"]), str(seeded["agents"]["chaser"]))
    svc.revoke_patient_link(container, link.id, str(seeded["owner_id"]))

    assert link.state == "revoked"


def test_container_selects_local_blob_backend(container, monkeypatch, tmp_path):
    root = tmp_path / "local-blobs"
    monkeypatch.setattr(settings, "blob_backend", "local")
    monkeypatch.setattr(settings, "blob_root", str(root))

    selected = svc.Container(container.session)

    assert isinstance(selected.blob, LocalBlobAdapter)
    assert selected.blob.root == root


def test_container_selects_box_scoped_managed_identity_blob_backend(
    container,
    seeded,
    monkeypatch,
):
    sentinel = object()
    calls: dict[str, str] = {}

    def fake_from_managed_identity(*, account_url: str, container_name: str, box_id: str):
        calls.update(account_url=account_url, container_name=container_name, box_id=box_id)
        return sentinel

    monkeypatch.setattr(settings, "blob_backend", "azure")
    monkeypatch.setattr(settings, "azure_storage_account_url", "https://storage.example.invalid")
    monkeypatch.setattr(settings, "azure_blob_container", "beta-artifacts")
    monkeypatch.setattr(settings, "beta_box_id", str(seeded["box_id"]))
    monkeypatch.setattr(
        AzureBlobAdapter,
        "from_managed_identity",
        staticmethod(fake_from_managed_identity),
    )

    selected = svc.Container(container.session)

    assert selected.blob is sentinel
    assert calls == {
        "account_url": "https://storage.example.invalid",
        "container_name": "beta-artifacts",
        "box_id": str(seeded["box_id"]),
    }


def test_container_fails_closed_when_azure_blob_configuration_is_missing(container, monkeypatch):
    monkeypatch.setattr(settings, "blob_backend", "azure")
    monkeypatch.setattr(settings, "azure_storage_account_url", None)
    monkeypatch.setattr(settings, "azure_blob_container", None)
    monkeypatch.setattr(settings, "beta_box_id", None)

    with pytest.raises(
        RuntimeError,
        match="AZURE_STORAGE_ACCOUNT_URL, AZURE_BLOB_CONTAINER, BETA_BOX_ID",
    ):
        svc.Container(container.session)
