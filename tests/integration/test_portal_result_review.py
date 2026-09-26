"""Private result evidence read from committed PostgreSQL by a fresh HTTP session.

The portal adapter is explicitly synthetic. This qualifies local disclosure and
review, not a real portal, device, or external delivery.
"""

import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_portal_work import (
    POLICY,
    approve,
    bound,
    create,
    detail,
    gates,  # noqa: F401 -- opt in to the same explicit synthetic gates
    portal_case,
    read_status,
    result,
    submit,
)

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import app as api
from cosmas_os.api import portal_work_routes
from cosmas_os.api import portal_work_schemas as schema
from cosmas_os.application import portal_setup, portal_work, services, vendor_work
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.models import PatientLink, Principal
from cosmas_os.portal_work_models import PortalWorkReceipt


def http_app(factory, c):
    app = FastAPI()
    portal_work_routes.register(app, api.get_session, api._identity)
    app.dependency_overrides[api.get_session] = factory
    app.dependency_overrides[portal_work_routes.default_policy] = lambda: POLICY
    app.dependency_overrides[portal_work_routes.portal_setup_routes.installed_catalog] = lambda: c[
        "catalog"
    ]
    return app


def headers(c, actor=None):
    return {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": actor or c["owner"],
        "X-Cosmas-Portal-Work-Contract": "1",
    }


def verify_request(d):
    return schema.Verify(
        **bound(d),
        observation_head=d["observation_head"],
        evidence_sha256=d["evidence_sha256"],
        result_receipt_id=d["current_result"]["receipt_id"],
        result_receipt_sha256=d["current_result"]["receipt_sha256"],
        reviewed_result=True,
        reviewed_observations=True,
        outcome_confirmed=True,
    )


@pytest.mark.asyncio
async def test_fresh_http_owner_reads_and_verifies_committed_result_without_rewriting(
    engine, tmp_path
):
    # Independent committed preparation, then close every original Session.
    with Session(engine, expire_on_commit=False) as s:
        seeded = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented cross-device portal review",
        )
        c = cast(Any, portal_case).__wrapped__(s, seeded, tmp_path / "custody")
        options = vendor_work.options(s, c["box"], c["owner"], c["wid"])
        setups = portal_setup.catalog(s, c["box"], c["owner"], c["catalog"])
        upload, _, _ = create(s, c)
        assert detail(s, c, upload)["current_result"] is None
        approve(s, c, upload)
        _, _, inv = await submit(s, c, upload)
        tid, _, _ = create(
            s,
            c,
            action="referral.submit",
            summary="Invented fresh-device referral review.",
            uploaded_operation_id=str(inv.command.operation_id),
        )
        approve(s, c, tid)
        await submit(s, c, tid)
        await read_status(s, c, tid, "received")
        receipt = result(s, c, tid)
        row = s.get(PortalWorkReceipt, receipt["effect"]["receipt_id"])
        assert row is not None
        original_request = copy.deepcopy(row.request)
        original_receipt = copy.deepcopy(row.response)
        observers = []
        for label in ["Invented staff", "Invented peer"]:
            p = Principal(
                id=str(uuid4()), box_id=c["box"], principal_type="human", display_name=label
            )
            s.add(p)
            observers.append(p.id)
        s.commit()
    sessions = []

    def fresh_session():
        with Session(engine, expire_on_commit=False) as fresh:
            sessions.append(fresh)
            yield fresh

    prefix = f"/workspaces/{c['wid']}/portal-work"
    vectors = {
        "provenance": "Actual committed PostgreSQL and FastAPI, independent Session per request; injected synthetic portal only.",
        "identity": {"boxId": c["box"], "actorId": c["owner"]},
        "workspace_id": c["wid"],
        "options": options,
        "setup_catalog": setups,
    }
    with TestClient(http_app(fresh_session, c)) as client:
        got = client.get(prefix + "/" + tid, headers=headers(c))
        assert got.status_code == 200, got.text
        assert got.headers["cache-control"] == "no-store"
        d = got.json()
        assert d["latest_result"] == original_receipt
        assert d["current_result"] == {
            "receipt_id": receipt["effect"]["receipt_id"],
            "receipt_sha256": receipt["receipt_sha256"],
            "request_sha256": receipt["request_sha256"],
            "recorded_at": receipt["effect"]["recorded_at"],
            "request": original_request,
        }
        vectors["result_detail"] = d
        vectors["no_result_detail"] = client.get(prefix + "/" + upload, headers=headers(c)).json()
        assert vectors["no_result_detail"]["current_result"] is None
        catalog = client.get(prefix, headers=headers(c)).json()
        assert all("current_result" not in item for item in catalog["items"])
        assert original_request["evidence"] not in json.dumps(catalog)
        vectors["catalog"] = catalog
        observations = client.get(prefix + "/" + tid + "/observations", headers=headers(c))
        assert observations.status_code == 200
        vectors["observations"] = observations.json()
        for peer in observers:
            for path in [prefix, prefix + "/" + tid, prefix + "/" + tid + "/observations"]:
                denied = client.get(path, headers=headers(c, peer))
                assert denied.status_code == 404, denied.text
                assert original_request["evidence"] not in denied.text
        command = verify_request(d)
        # A new explicit verification binds only to the original server result.
        verified = client.post(
            prefix + "/" + tid + "/verify", headers=headers(c), json=command.public()
        )
        assert verified.status_code == 200, verified.text
        vectors["verify_operation"] = {
            "version": 1,
            "scope": d["scope"],
            "kind": "verify",
            "target_id": tid,
            "request": command.public(),
            "request_sha256": schema.request_digest(c["wid"], "verify", command),
        }
        vectors["verify_receipt"] = verified.json()
        vectors["verified_detail"] = client.get(prefix + "/" + tid, headers=headers(c)).json()
        assert vectors["verified_detail"]["state"] == "closed"
        resolver = {
            "command_kind": "result",
            "idempotency_key": original_request["idempotency_key"],
            "request_sha256": receipt["request_sha256"],
        }
        recovered = client.post(prefix + "/resolve", headers=headers(c), json=resolver)
        assert recovered.json() == original_receipt
        vectors["result_resolved"] = recovered.json()
        # A late observation reopens verification, while preserving the saved
        # historical result text and exact immutable proof for owner review.
        with Session(engine, expire_on_commit=False) as later:
            await read_status(later, c, tid, "unknown")
        changed = client.get(prefix + "/" + tid, headers=headers(c)).json()
        assert changed["state"] == "approved"
        assert changed["current_result"] == d["current_result"]
        assert changed["observation_head"] != d["observation_head"]
        vectors["changed_detail"] = changed
        vectors["changed_observations"] = client.get(
            prefix + "/" + tid + "/observations", headers=headers(c)
        ).json()
        stale = client.post(
            prefix + "/" + tid + "/verify",
            headers=headers(c),
            json=verify_request(changed).public(),
        )
        assert stale.status_code == 409
        with Session(engine, expire_on_commit=False) as later:
            await read_status(later, c, tid, "received")
            newer = result(later, c, tid)
        vectors["newer_result_detail"] = client.get(prefix + "/" + tid, headers=headers(c)).json()
        assert (
            vectors["newer_result_detail"]["current_result"]["receipt_id"]
            == newer["effect"]["receipt_id"]
        )
        assert (
            client.post(prefix + "/resolve", headers=headers(c), json=resolver).json()
            == original_receipt
        )
        with Session(engine, expire_on_commit=False) as audit:
            assert (
                audit.scalar(
                    select(func.count())
                    .select_from(PortalWorkReceipt)
                    .where(
                        PortalWorkReceipt.ticket_id == tid,
                        PortalWorkReceipt.command_kind == "result",
                    )
                )
                == 2
            )  # Only the two explicitly recorded results; read/verify adds none.
            stored = audit.get(PortalWorkReceipt, receipt["effect"]["receipt_id"])
            assert stored is not None and stored.response == original_receipt
            link = audit.get(PatientLink, c["link"])
            assert link is not None
            link.revoked_at = datetime.now(UTC)
            audit.commit()
        denied = client.get(prefix + "/" + tid, headers=headers(c))
        assert denied.status_code == 404
        assert original_request["evidence"] not in denied.text
    assert len({id(session) for session in sessions}) == len(sessions)
    assert len(c["adapter"].effects) == 2  # Only explicit upload and referral send.
    (tmp_path / "actual-portal-result-review.json").write_text(json.dumps(vectors, indent=2) + "\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["evidence", "key", "scope", "version", "receipt", "extra"])
async def test_disclosure_rejects_corrupted_original_or_receipt(session, portal_case, mutation):
    s, c = session, portal_case
    tid, _, _ = create(s, c)
    approve(s, c, tid)
    await submit(s, c, tid)
    receipt = result(s, c, tid)
    row = s.get(PortalWorkReceipt, receipt["effect"]["receipt_id"])
    cloned = SimpleNamespace(
        **{
            column.name: copy.deepcopy(getattr(row, column.name))
            for column in PortalWorkReceipt.__table__.columns
        }
    )
    if mutation == "evidence":
        cloned.request["evidence"] = "Invented forged text that was never recorded."
    elif mutation == "key":
        cloned.request["idempotency_key"] = "another-result-key"
    elif mutation == "scope":
        cloned.owner_id = str(uuid4())
    elif mutation == "version":
        cloned.version += 1
    elif mutation == "receipt":
        cloned.response["effect"]["recorded_at"] = "2026-09-21T00:00:00.000000Z"
    else:
        cloned.request["unreviewed_text"] = "extra"
    w = portal_work.owner(s, c["box"], c["owner"], c["wid"])
    t, r, _ = portal_work.bound(s, w, tid)
    with pytest.raises(WorkspaceError) as failed:
        portal_work.current_result(w, t, r, cloned)
    assert failed.value.code == "portal_work_integrity"
    assert detail(s, c, tid)["current_result"]["request"]["evidence"] == row.request["evidence"]


@pytest.mark.asyncio
async def test_final_disclosure_fence_denies_result_after_read(session, portal_case):
    s, c = session, portal_case
    tid, _, _ = create(s, c)
    approve(s, c, tid)
    await submit(s, c, tid)
    result(s, c, tid)

    def denied():
        raise WorkspaceError("portal_work_unavailable", 403)

    s.info["portal_work_authority"] = denied
    with pytest.raises(WorkspaceError) as caught:
        detail(s, c, tid)
    assert caught.value.status == 403
    s.info.pop("portal_work_authority")
