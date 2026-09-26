"""Independent PostgreSQL sessions and actual local custody around injected portal I/O."""

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from tests.integration.test_portal_work import (
    POLICY,
    approve,
    bound,
    create,
    detail,
    portal_case,
    result,
    verify,
)

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import portal_setup_schemas as setup_schema
from cosmas_os.api import portal_work_schemas as p
from cosmas_os.application import portal_setup as setup
from cosmas_os.application import portal_work as flow
from cosmas_os.application import portal_work_execution as execution
from cosmas_os.application import services
from cosmas_os.config import settings
from cosmas_os.models import Operation
from cosmas_os.portal_work_models import PortalWorkClaim


@pytest.fixture
def runtime_case(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    monkeypatch.setattr(settings, "portal_setup_enabled", True)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as s:
        seeded = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented portal runtime",
        )
        c = cast(Any, portal_case).__wrapped__(s, seeded, tmp_path)
        tid, _, _ = create(s, c)
        approve(s, c, tid)
        request = p.Bound(**bound(detail(s, c, tid)))
        receipt, inv = execution.claim(
            s,
            c["box"],
            c["owner"],
            c["wid"],
            tid,
            "submit",
            request,
            catalog=c["catalog"],
            policy=POLICY,
        )
    assert inv

    async def authority():
        return True

    runtime = execution.PortalWorkExecution(
        sessions,
        catalog=c["catalog"],
        artifact_store=c["store"],
        identity_current=authority,
        policy_current=lambda: POLICY,
    )
    return c, tid, request, receipt, inv, runtime, sessions, tmp_path


@pytest.mark.asyncio
async def test_real_custody_independent_sessions_then_referral_and_verified_result(runtime_case):
    c, tid, request, receipt, inv, runtime, sessions, _ = runtime_case
    await runtime.invoke(inv)
    with sessions() as s:
        assert detail(s, c, tid)["acceptance"] == "accepted"
        assert s.get(Operation, str(inv.command.operation_id)).attempt_count == 1
        saved = flow.resolve(
            s,
            c["box"],
            c["owner"],
            c["wid"],
            p.Resolve(
                command_kind="submit",
                idempotency_key=request.idempotency_key,
                request_sha256=receipt["request_sha256"],
            ),
        )
        assert saved == receipt
        referral, _, _ = create(
            s,
            c,
            action="referral.submit",
            summary="Invented referral to selected specialist",
            uploaded_operation_id=str(inv.command.operation_id),
        )
        approve(s, c, referral)
        d = detail(s, c, referral)
        _, send = execution.claim(
            s,
            c["box"],
            c["owner"],
            c["wid"],
            referral,
            "submit",
            p.Bound(**bound(d)),
            catalog=c["catalog"],
            policy=POLICY,
        )
    assert send
    await runtime.invoke(send)
    c["adapter"].state = "received"
    with sessions() as s:
        d = detail(s, c, referral)
        _, read = execution.claim(
            s,
            c["box"],
            c["owner"],
            c["wid"],
            referral,
            "status",
            p.Bound(**bound(d)),
            catalog=c["catalog"],
            policy=POLICY,
        )
    assert read
    await runtime.invoke(read)
    with sessions() as s:
        result(s, c, referral)
        verify(s, c, referral)
        assert detail(s, c, referral)["verification"] == "verified"
    assert len(c["adapter"].effects) == 2


@pytest.mark.asyncio
async def test_revoked_mapping_after_claim_prevents_invocation(runtime_case):
    c, tid, _, _, inv, runtime, sessions, _ = runtime_case
    d = c["setup"]
    with sessions() as s:
        setup.command(
            s,
            c["box"],
            c["owner"],
            "disable",
            setup_schema.Disable(
                connection_id=d["connection_id"],
                revision_id=d["revision_id"],
                expected_version=d["version"],
                review_sha256=d["review_sha256"],
                idempotency_key="runtime-disable-" + str(uuid4()),
                confirm_disable=True,
            ),
            c["catalog"],
        )
    await runtime.invoke(inv)
    with sessions() as s:
        assert detail(s, c, tid)["acceptance"] == "unknown"
        assert s.get(PortalWorkClaim, inv.claim_id).dispatch == "settled"
    assert c["adapter"].effects == []


@pytest.mark.asyncio
async def test_changed_exact_pdf_blocks_any_provider_call(runtime_case):
    c, tid, _, _, inv, runtime, sessions, root = runtime_case
    path = next((root / "documents").rglob("*.pdf"))
    before = path.read_bytes()
    path.write_bytes(before.replace(b"Invented", b"Changed!", 1))
    await runtime.invoke(inv)
    with sessions() as s:
        assert detail(s, c, tid)["acceptance"] == "unknown"
    assert c["adapter"].effects == []


@pytest.mark.asyncio
async def test_foreground_cancel_retains_late_acceptance_without_repeat(runtime_case):
    c, tid, request, receipt, inv, runtime, sessions, _ = runtime_case
    entered = asyncio.Event()
    release = asyncio.Event()
    original = c["adapter"].submit

    async def delayed(prepared, approval):
        entered.set()
        await release.wait()
        return await original(prepared, approval)

    c["adapter"].submit = delayed
    foreground = asyncio.create_task(runtime.invoke(inv))
    await asyncio.wait_for(entered.wait(), 3)
    foreground.cancel()
    with pytest.raises(asyncio.CancelledError):
        await foreground
    with sessions() as s:
        saved, again = execution.claim(
            s,
            c["box"],
            c["owner"],
            c["wid"],
            tid,
            "submit",
            request,
            catalog=c["catalog"],
            policy=POLICY,
        )
        assert saved == receipt and again is None
    release.set()
    await asyncio.wait_for(asyncio.gather(*runtime.pending), 3)
    with sessions() as s:
        assert detail(s, c, tid)["acceptance"] == "accepted"
    assert len(c["adapter"].effects) == 1


@pytest.mark.asyncio
async def test_preparation_cannot_bypass_final_mapping_gate(runtime_case):
    c, tid, _, _, inv, runtime, sessions, _ = runtime_case
    original = c["adapter"].prepare
    d = c["setup"]

    def changed(command, document=None):
        prepared = original(command, document)
        with sessions() as s:
            setup.command(
                s,
                c["box"],
                c["owner"],
                "disable",
                setup_schema.Disable(
                    connection_id=d["connection_id"],
                    revision_id=d["revision_id"],
                    expected_version=d["version"],
                    review_sha256=d["review_sha256"],
                    idempotency_key="preparation-disable-" + str(uuid4()),
                    confirm_disable=True,
                ),
                c["catalog"],
            )
        return prepared

    c["adapter"].prepare = changed
    await runtime.invoke(inv)
    assert c["adapter"].effects == []
    with sessions() as s:
        assert detail(s, c, tid)["acceptance"] == "unknown"


@pytest.mark.asyncio
async def test_spent_operation_attempt_and_adapter_cannot_be_reset_by_sql(runtime_case):
    from sqlalchemy.exc import DBAPIError

    c, _, _, _, inv, runtime, sessions, _ = runtime_case
    await runtime.invoke(inv)
    for clause in ["attempt_count=0", "adapter='notify'", "attempt_count=2"]:
        with sessions() as s, pytest.raises(DBAPIError):
            s.execute(
                text("UPDATE operations SET " + clause + " WHERE id=:id"),
                {"id": str(inv.command.operation_id)},
            )
            s.commit()
