"""Real SQL and concurrent setup admission; no service calls."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_vendor_settings import (
    ON,
    account,
    account_request,
    activate,
    binding,
    call,
    command,
    recipient,
    recipient_request,
    view,
)
from tests.integration.test_vendor_settings import setup_case as setup_case
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.application import vendor_settings as flow
from cosmas_os.application import workspace as ws
from cosmas_os.models import PatientLink
from cosmas_os.vendor_models import VendorConnectionVersion, VendorCorrespondenceVersion
from cosmas_os.vendor_setup_models import VendorSetupReceipt, VendorSetupRevision


def immediate(s):
    s.flush()
    s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    s.execute(text("SET CONSTRAINTS ALL DEFERRED"))


@pytest.mark.parametrize("kind", ["account", "recipient"])
def test_direct_sql_cannot_reenable_disabled_native_binding(session, setup_case, kind):
    c = setup_case
    a = account(session, c)
    r = recipient(session, c, a)
    target = a if kind == "account" else r
    d = view(session, c, target)
    command(session, c, target, "disable")
    with pytest.raises(DBAPIError, match="managed .* state mismatch"), session.begin_nested():
        if kind == "account":
            native = session.get(VendorConnectionVersion, d["review"]["connection_version_id"])
            native.is_current = True
            native.write_enabled = True
        else:
            native = session.get(
                VendorCorrespondenceVersion, d["review"]["correspondence_version_id"]
            )
            native.is_current = True
        immediate(session)


def test_managed_account_cannot_gain_unreviewed_recipient_binding(session, setup_case):
    c = setup_case
    a = account(session, c)
    r = recipient(session, c, a)
    d = view(session, c, r)
    original = session.get(VendorCorrespondenceVersion, d["review"]["correspondence_version_id"])
    fields = {column.name: getattr(original, column.name) for column in original.__table__.columns}
    fields.update(id=str(uuid4()), family_id=str(uuid4()))
    with (
        pytest.raises(DBAPIError, match="managed recipient binding requires setup review"),
        session.begin_nested(),
    ):
        session.add(VendorCorrespondenceVersion(**fields))
        immediate(session)


@pytest.mark.parametrize(
    "table", ["vendor_setups", "vendor_setup_revisions", "vendor_setup_receipts"]
)
def test_setting_history_is_immutable(session, setup_case, table):
    c = setup_case
    a = account(session, c)
    d = view(session, c, a)
    address = (
        a["effect"]["setup_id"]
        if table == "vendor_setups"
        else d["review"]["revision_id"]
        if table == "vendor_setup_revisions"
        else a["receipt_id"]
    )
    with pytest.raises(DBAPIError, match="immutable"), session.begin_nested():
        session.execute(text(f"DELETE FROM {table} WHERE id=:id"), {"id": address})


def test_missing_receipt_or_forged_review_cannot_commit(session, setup_case):
    c = setup_case
    req = account_request(c)
    first = call(session, c, flow.propose, "propose_account", req, c["installed"], policy=ON)
    d = view(session, c, first)
    original = session.get(VendorSetupRevision, d["review"]["revision_id"])
    values = {column.name: getattr(original, column.name) for column in original.__table__.columns}
    values.update(id=str(uuid4()), revision=2, review={**values["review"], "label": "forged"})
    with pytest.raises(DBAPIError, match="review binding mismatch"), session.begin_nested():
        session.add(VendorSetupRevision(**values))
        immediate(session)


def test_final_authority_failure_rolls_back_native_flags_and_receipt(session, setup_case):
    c = setup_case
    req = account_request(c)
    first = call(session, c, flow.propose, "propose_account", req, c["installed"], policy=ON)
    d = view(session, c, first)

    def deny():
        raise ws.WorkspaceError("vendor_setup_unavailable", 403)

    session.info["vendor_setup_authority"] = deny
    try:
        with (
            pytest.raises(ws.WorkspaceError, match="vendor_setup_unavailable"),
            session.begin_nested(),
        ):
            activate(session, c, first)
    finally:
        session.info.pop("vendor_setup_authority", None)
    native = session.get(VendorConnectionVersion, d["review"]["connection_version_id"])
    assert native is not None and not native.is_current and not native.write_enabled
    assert call(session, c, flow.history, req.setup_id)["items"][-1]["receipt"] == first


def test_changed_patient_denies_recipient_activation_but_allows_disable(session, setup_case):
    c = setup_case
    a = account(session, c)
    req = recipient_request(c, a)
    first = call(session, c, flow.propose, "propose_recipient", req, c["installed"], policy=ON)
    patient = session.get(PatientLink, req.patient_link_id)
    patient.state = "unconfirmed"
    session.commit()
    with pytest.raises(ws.WorkspaceError, match="vendor_patient_unavailable"):
        activate(
            session,
            c,
            first,
            reviewed_patient=True,
            reviewed_recipient=True,
            reviewed_permission=True,
        )
    assert command(session, c, first, "disable")["effect"]["state"] == "disabled"


def test_identical_concurrent_command_has_one_receipt_and_binding(engine, setup_case, session):
    c = setup_case
    req = account_request(c)
    # The vendor fixture is transaction-isolated; retain an explicit independent
    # invented fixture for workers instead of committing another test's state.
    from pathlib import Path

    from tests.integration.test_vendor_settings import setup_case as setup_fixture
    from tests.integration.test_vendor_work import vendor_case as vendor_fixture

    from cosmas_os.adapters.local import LocalBlobAdapter
    from cosmas_os.application import services

    with Session(engine) as s:
        seed = services.provision_box(
            services.Container(
                s,
                blob=LocalBlobAdapter(
                    Path(
                        "/Users/jw/Desktop/Cosmas/cosmas-beta-local-recovery-20260921/w36-vendor-settings/race-blobs"
                    )
                    / str(uuid4())
                ),
            ),
            "Invented setup race",
        )
        make = getattr(vendor_fixture, "__wrapped__", None)
        assert callable(make)
        base = make(s, seed)
        make_setup = getattr(setup_fixture, "__wrapped__", None)
        assert callable(make_setup)
        c = make_setup(base)
        assert isinstance(c, dict)
        req = account_request(c)
        s.commit()
    barrier = Barrier(2)

    def apply():
        with Session(engine) as s:
            barrier.wait()
            return call(s, c, flow.propose, "propose_account", req, c["installed"], policy=ON)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: apply(), range(2)))
    assert first == second
    with Session(engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(VendorSetupReceipt)
                .where(VendorSetupReceipt.setup_id == req.setup_id)
            )
            == 1
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(VendorSetupRevision)
                .where(VendorSetupRevision.setup_id == req.setup_id)
            )
            == 1
        )


def test_fully_rehashed_wrong_vendor_capabilities_are_rejected_by_sql(session, setup_case):
    from cosmas_os.api.vendor_work_schemas import public_digest
    from cosmas_os.vendor_setup_models import VendorSetup

    c = setup_case
    request = account_request(c)
    first = call(session, c, flow.propose, "propose_account", request, c["installed"], policy=ON)
    d = view(session, c, first)
    old_revision = session.get(VendorSetupRevision, d["review"]["revision_id"])
    old_native = session.get(VendorConnectionVersion, d["review"]["connection_version_id"])
    assert old_revision is not None and old_native is not None
    setup_id, revision_id, connection_id, installation_id = map(
        str, [uuid4(), uuid4(), uuid4(), uuid4()]
    )
    review = {
        **old_revision.review,
        "setup_id": setup_id,
        "revision_id": revision_id,
        "connection_version_id": connection_id,
        "installed": {
            **old_revision.review["installed"],
            "installation_id": installation_id,
            "capabilities": ["srfax_fax"],
        },
        "permissions": {**old_revision.review["permissions"], "actions": ["srfax_fax"]},
    }
    native_values = {
        column.name: getattr(old_native, column.name) for column in old_native.__table__.columns
    }
    private = {**native_values["private_selection"], "connection_id": connection_id}
    public = {**native_values["public_view"], "id": connection_id, "actions": ["srfax_fax"]}
    public["public_sha256"] = public_digest(
        "cosmas-vendor-public-selection.v1",
        {k: v for k, v in public.items() if k != "public_sha256"},
    )
    native_values.update(
        id=connection_id,
        family_id=setup_id,
        private_selection=private,
        private_sha256=public_digest("cosmas-vendor-selection.v1", private),
        public_view=public,
        public_sha256=public["public_sha256"],
    )
    revision_values = {
        column.name: getattr(old_revision, column.name) for column in old_revision.__table__.columns
    }
    revision_values.update(
        id=revision_id,
        setup_id=setup_id,
        installation_id=installation_id,
        connection_version_id=connection_id,
        review=review,
        review_sha256=public_digest("cosmas-vendor-setup-review.v1", review),
    )
    with pytest.raises(DBAPIError, match="review binding mismatch"), session.begin_nested():
        session.add(
            VendorSetup(
                id=setup_id,
                box_id=c["box"],
                owner_id=c["actor"],
                kind="account",
                installation_id=installation_id,
                created_at=old_revision.created_at,
            )
        )
        session.flush()
        session.add(VendorConnectionVersion(**native_values))
        session.flush()
        session.add(VendorSetupRevision(**revision_values))
        immediate(session)


def test_fully_rehashed_false_activation_attestation_is_rejected_by_sql(session, setup_case):
    from cosmas_os.api.vendor_work_schemas import public_digest, timestamp
    from cosmas_os.application.vendor_work import _clock

    c = setup_case
    request = account_request(c)
    first = call(session, c, flow.propose, "propose_account", request, c["installed"], policy=ON)
    d = view(session, c, first)
    now = _clock(session)
    receipt_id = str(uuid4())
    forged = {
        **binding(first),
        "idempotency_key": "forged-activation-" + str(uuid4()),
        "reviewed_account": False,
        "reviewed_environment": True,
        "reviewed_sender": True,
        "reviewed_capabilities": True,
        "confirm_local_activation": True,
    }
    scope = {"box_id": c["box"], "owner_id": c["actor"]}
    digest = public_digest(
        "cosmas-vendor-setup-request.v1",
        {"scope": scope, "command_kind": "activate", "request": forged},
    )
    response = {
        **first,
        "command_kind": "activate",
        "idempotency_key": forged["idempotency_key"],
        "request_sha256": digest,
        "receipt_id": receipt_id,
        "recorded_at": timestamp(now),
        "effect": {**first["effect"], "version": 2, "state": "active"},
    }
    response["receipt_sha256"] = public_digest(
        "cosmas-vendor-setup-receipt.v1",
        {k: v for k, v in response.items() if k != "receipt_sha256"},
    )
    with pytest.raises(DBAPIError, match="command transition mismatch"), session.begin_nested():
        native = session.get(VendorConnectionVersion, d["review"]["connection_version_id"])
        assert native is not None
        native.is_current = True
        native.read_enabled = True
        native.write_enabled = True
        session.add(
            VendorSetupReceipt(
                id=receipt_id,
                box_id=c["box"],
                owner_id=c["actor"],
                setup_id=request.setup_id,
                revision_id=first["effect"]["revision_id"],
                version=2,
                command_kind="activate",
                state="active",
                idempotency_key=forged["idempotency_key"],
                request=forged,
                request_sha256=digest,
                response=response,
                receipt_sha256=response["receipt_sha256"],
                recorded_at=now,
            )
        )
        immediate(session)
