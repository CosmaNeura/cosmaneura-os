"""Actual FastAPI body/header/response contract against isolated PostgreSQL."""

import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_vendor_work import (  # noqa: F401
    bound,
    call,
    gates,
    proposal,
)
from tests.integration.test_vendor_work import (
    vendor_case as vendor_case,
)

from cosmas_os.api import app as api
from cosmas_os.api import vendor_work_schemas as p
from cosmas_os.application import vendor_artifacts, vendor_work


@pytest.fixture
def client(session):
    api.app.dependency_overrides[api.get_session] = lambda: session
    try:
        with TestClient(api.app) as client:
            yield client
    finally:
        api.app.dependency_overrides.clear()


def headers(case):
    return {
        "X-Box-Id": case["box"],
        "X-Actor-Principal-Id": case["actor"],
        "X-Cosmas-Vendor-Contract": "1",
    }


def root(case):
    return f"/workspaces/{case['wid']}/vendor-work"


def test_actual_http_proposal_review_approval_resolution_and_private_queue(
    client, session, vendor_case, tmp_path
):
    c = vendor_case
    h = headers(c)
    url = root(c)
    selected = client.get(url + "/options", headers=h)
    assert selected.status_code == 200
    p.Options.model_validate(selected.json())
    request = proposal(c)
    created = client.post(url, headers=h, json=request.public())
    assert created.status_code == 200, created.text
    result = p.CommandResponse.model_validate(created.json())
    tid = result.effect.ticket_id
    detail = client.get(url + "/" + tid, headers=h)
    assert detail.status_code == 200
    d = p.Detail.model_validate(detail.json()).public()
    assert result.request_sha256 == p.request_digest(
        "propose", {"kind": "workspace", "id": c["wid"]}, request
    )
    approval = p.VendorDecision(**bound(d, review_sha256=d["review_sha256"], choice="approve"))
    decided = client.post(url + "/" + tid + "/decide", headers=h, json=approval.public())
    assert decided.status_code == 200, decided.text
    assert decided.json()["summary"]["effect"] == "approved"
    resolved = client.post(
        url + "/resolve",
        headers=h,
        json={
            "command_kind": "propose",
            "idempotency_key": request.idempotency_key,
            "request_sha256": result.request_sha256,
        },
    )
    assert resolved.status_code == 200 and resolved.json()["effect"] == created.json()["effect"]
    queue = client.get(
        "/queue", headers={k: v for k, v in h.items() if k != "X-Cosmas-Vendor-Contract"}
    )
    assert queue.status_code == 200 and tid not in str(queue.json())
    assert (
        client.get(
            "/tickets/" + tid + "/timeline",
            headers={k: v for k, v in h.items() if k != "X-Cosmas-Vendor-Contract"},
        ).status_code
        == 403
    )
    assert created.headers["cache-control"] == "no-store"
    import json

    captures = {
        "options": selected.json(),
        "proposal_receipt": created.json(),
        "detail_pending": detail.json(),
        "approval_receipt": decided.json(),
        "resolved_proposal": resolved.json(),
        "detail_approved": client.get(url + "/" + tid, headers=h).json(),
        "catalog": client.get(url, headers=h).json(),
        "observations_empty": client.get(url + "/" + tid + "/observations", headers=h).json(),
    }
    (tmp_path / "actual-http-public-fixtures.json").write_text(
        json.dumps(captures, ensure_ascii=False, indent=2) + "\n"
    )


@pytest.mark.parametrize("header", [None, "2", "1,1", ""])
def test_missing_foreign_combined_header_rejected(client, vendor_case, header):
    c = vendor_case
    h = headers(c)
    if header is None:
        h.pop("X-Cosmas-Vendor-Contract")
    else:
        h["X-Cosmas-Vendor-Contract"] = header
    response = client.get(root(c) + "/options", headers=h)
    assert response.status_code == 426
    assert response.json() == {"contract_version": 1, "error": {"code": "vendor_contract_required"}}


def test_duplicate_header_and_unrelated_route_rejected(client, vendor_case):
    c = vendor_case
    h = headers(c)
    response = client.get(
        root(c) + "/options", headers=[*h.items(), ("X-Cosmas-Vendor-Contract", "1")]
    )
    assert response.status_code == 426
    assert client.get("/health", headers=h).status_code == 426
    h["X-Cosmas-Artifact-Write-Key"] = "invented-key"
    assert client.get(root(c) + "/options", headers=h).status_code == 400


@pytest.mark.parametrize(
    "body",
    [
        b'{"idempotency_key":"one","idempotency_key":"two"}',
        b'{"x":NaN}',
        b"[]",
        b"{}" + b" " * 32769,
    ],
)
def test_actual_http_raw_ambiguity_and_size_reject(client, vendor_case, body):
    h = {**headers(vendor_case), "Content-Type": "application/json", "Content-Length": "1"}
    response = client.post(root(vendor_case), headers=h, content=body)
    assert response.status_code in {400, 413}
    assert response.json()["error"]["code"] == "invalid_vendor_request"


def test_default_off_io_is_not_approval_or_send_authority(client, session, vendor_case):
    c = vendor_case
    h = headers(c)
    url = root(c)
    receipt = call(session, c, vendor_work.propose, proposal(c))
    tid = receipt["effect"]["ticket_id"]
    d = call(session, c, vendor_work.detail, tid)
    call(
        session,
        c,
        vendor_work.decide,
        tid,
        p.VendorDecision(**bound(d, review_sha256=d["review_sha256"], choice="approve")),
    )
    d = client.get(url + "/" + tid, headers=h).json()
    assert not d["availability"]["submit"]["allowed"]
    response = client.post(url + "/" + tid + "/submit", headers=h, json=bound(d))
    assert (
        response.status_code == 403
        and response.json()["error"]["code"] == "vendor_feature_disabled"
    )


def test_extra_queries_and_unknown_fields_rejected(client, vendor_case):
    c = vendor_case
    h = headers(c)
    assert client.get(root(c) + "/options?token=forbidden", headers=h).status_code == 400
    request = proposal(c).public()
    request["credential_ref"] = "never-from-renderer"
    response = client.post(root(c), headers=h, json=request)
    assert response.status_code == 400 and "credential_ref" not in response.text


def test_explicit_pdf_preview_returns_exact_bytes_and_no_public_storage_path(
    client, session, vendor_case, tmp_path
):
    from cosmas_os.adapters.vendor_artifacts import LocalVendorArtifactStore

    c = vendor_case
    h = headers(c)
    data = b"%PDF-1.7\nInvented W36 exact preview\n%%EOF"
    aid = str(uuid4())
    request = p.VendorArtifactIntent(
        artifact_id=aid,
        idempotency_key="artifact-" + str(uuid4()),
        source=p.ReviewedSource(**c["source"]),
        sha256=hashlib.sha256(data).hexdigest(),
        byte_length=len(data),
        media_type="application/pdf",
    )
    store = LocalVendorArtifactStore(tmp_path / "owned-artifacts")
    api.app.dependency_overrides[api._vendor_artifact_store] = lambda: store
    intent = client.post(
        f"/workspaces/{c['wid']}/vendor-artifacts", headers=h, json=request.public()
    )
    assert intent.status_code == 200, intent.text
    admission = vendor_artifacts.begin_content(
        session, c["box"], c["actor"], c["wid"], aid, "write-invented-pdf"
    )
    outcome = vendor_artifacts.write_content(store, admission.token, data)
    vendor_artifacts.settle_in_session(session, admission.token, outcome)
    session.commit()
    response = client.get(f"/workspaces/{c['wid']}/vendor-artifacts/{aid}/content", headers=h)
    assert response.status_code == 200, response.text
    assert response.content == data and response.headers["content-type"] == "application/pdf"
    assert str(tmp_path) not in str(intent.json())


def test_committed_http_raw_pdf_ingest_exact_replay_and_bad_retry(engine, tmp_path):
    import json
    import time

    from sqlalchemy.orm import Session

    from cosmas_os.adapters.local import LocalBlobAdapter
    from cosmas_os.adapters.vendor_artifacts import LocalVendorArtifactStore
    from cosmas_os.application import services as svc

    with Session(engine) as s:
        seeded = svc.provision_box(
            svc.Container(s, blob=LocalBlobAdapter(tmp_path / "seed-blobs")),
            "Invented W36 raw HTTP",
        )
        c = vendor_case.__wrapped__(s, seeded)

    def sessions():
        with Session(engine) as s:
            yield s
            assert "vendor_final_authority" not in s.info

    deadlines = []

    class DeadlineStore(LocalVendorArtifactStore):
        def put_verified(self, scope, data, *, deadline=None):
            assert deadline is not None and 0 < deadline - time.monotonic() <= 60
            deadlines.append(deadline)
            return super().put_verified(scope, data, deadline=deadline)

        def read_verified(self, scope, *, deadline=None):
            assert deadline is not None and 0 < deadline - time.monotonic() <= 60
            deadlines.append(deadline)
            return super().read_verified(scope, deadline=deadline)

    store = DeadlineStore(tmp_path / "content-store")
    api.app.dependency_overrides[api.get_session] = sessions
    api.app.dependency_overrides[api._vendor_artifact_store] = lambda: store
    data = b"%PDF-1.7\nInvented raw HTTP custody\n%%EOF"
    aid = str(uuid4())
    request = p.VendorArtifactIntent(
        artifact_id=aid,
        idempotency_key="intent-" + str(uuid4()),
        source=p.ReviewedSource(**c["source"]),
        sha256=hashlib.sha256(data).hexdigest(),
        byte_length=len(data),
        media_type="application/pdf",
    )
    h = headers(c)
    url = f"/workspaces/{c['wid']}/vendor-artifacts"
    try:
        with TestClient(api.app) as http:
            intent = http.post(url, headers=h, json=request.public())
            assert intent.status_code == 200, intent.text
            write = {
                **h,
                "Content-Type": "application/pdf",
                "X-Cosmas-Artifact-Write-Key": "same-local-content",
            }
            saved = http.put(url + "/" + aid + "/content", headers=write, content=data)
            assert saved.status_code == 200, saved.text
            assert saved.json()["artifact"]["state"] == "ready"
            exact = http.get(url + "/" + aid + "/content", headers=h)
            assert exact.status_code == 200 and exact.content == data
            replay = http.put(
                url + "/" + aid + "/content",
                headers=write,
                content=b"wrong bytes ignored for ready goal",
            )
            assert replay.status_code == 200 and replay.json()["effect"] == saved.json()["effect"]
            before_replay = len(deadlines)
            consumed = []

            def forbidden_body():
                consumed.append(True)
                raise AssertionError("Exact immutable-intent replay must not consume a body")
                yield b""

            streaming_replay = http.put(
                url + "/" + aid + "/content", headers=write, content=forbidden_body()
            )
            assert streaming_replay.status_code == 200 and not consumed
            assert len(deadlines) == before_replay
            assert http.get(url + "/" + aid + "/content", headers=h).content == data
            other = http.put(
                url + "/" + aid + "/content",
                headers={**write, "X-Cosmas-Artifact-Write-Key": "other-local-key"},
                content=data,
            )
            assert other.status_code == 409
            (tmp_path / "actual-http-artifact-fixtures.json").write_text(
                json.dumps(
                    {
                        "artifact_intent_receipt": intent.json(),
                        "artifact_content_receipt": saved.json(),
                        "artifact_replay_receipt": replay.json(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
    finally:
        api.app.dependency_overrides.clear()


def test_actual_http_shared_handoffs_result_and_historical_receipt(
    client, session, vendor_case, tmp_path
):
    import json

    from cosmas_os.models import Principal

    c = vendor_case
    owner = headers(c)
    colleague = Principal(
        box_id=c["box"], principal_type="human", display_name="Invented W36 staff", state="active"
    )
    session.add(colleague)
    session.commit()
    staff = {**owner, "X-Actor-Principal-Id": colleague.id}
    created = client.post(
        root(c), headers=owner, json=proposal(c, share_to_practice=True).public()
    ).json()
    tid = created["effect"]["ticket_id"]
    private_url = root(c) + "/" + tid
    shared_url = "/practice-work/" + tid
    d = client.get(private_url, headers=owner).json()
    approved = client.post(
        private_url + "/decide",
        headers=owner,
        json=p.VendorDecision(
            **bound(d, review_sha256=d["review_sha256"], choice="approve")
        ).public(),
    )
    assert approved.status_code == 200
    d = client.get(private_url, headers=owner).json()
    offer = p.VendorHandoff(
        expected_version=d["summary"]["version"],
        revision_id=d["summary"]["revision_id"],
        payload_hash=d["summary"]["payload_hash"],
        idempotency_key="http-offer-" + str(uuid4()),
        kind="offer",
        recipient_id=colleague.id,
    )
    offered = client.post(shared_url + "/handoffs", headers=owner, json=offer.public())
    assert offered.status_code == 200, offered.text
    offered_detail = client.get(shared_url, headers=staff)
    shared = p.SharedVendorDetail.model_validate(offered_detail.json()).public()
    accept = p.VendorHandoff(
        expected_version=shared["version"],
        revision_id=shared["revision_id"],
        payload_hash=shared["payload_hash"],
        idempotency_key="http-accept-" + str(uuid4()),
        kind="accept",
        offer_id=shared["pending_offer"]["id"],
    )
    accepted = client.post(shared_url + "/handoffs", headers=staff, json=accept.public())
    assert accepted.status_code == 200, accepted.text
    accepted_detail = client.get(shared_url, headers=staff)
    shared = p.SharedVendorDetail.model_validate(accepted_detail.json()).public()
    outcome = p.VendorStaffResult(
        expected_version=shared["version"],
        revision_id=shared["revision_id"],
        payload_hash=shared["payload_hash"],
        operation_id=shared["vendor_work"]["operation_id"],
        idempotency_key="http-result-" + str(uuid4()),
        observation_head=shared["vendor_work"]["observation_head"],
        evidence_sha256=shared["vendor_work"]["evidence_sha256"],
        disposition="reported_exception",
        evidence="Invented staff could not establish completion.",
    )
    result = client.post(shared_url + "/result", headers=staff, json=outcome.public())
    assert result.status_code == 200, result.text
    final = client.get(shared_url, headers=staff)
    assert final.status_code == 200 and final.json()["state"] == "approved"
    resolved = client.post(
        shared_url + "/vendor-command/resolve",
        headers=staff,
        json=p.VendorStaffResolve(
            command_kind="result",
            idempotency_key=outcome.idempotency_key,
            request_sha256=result.json()["request_sha256"],
        ).public(),
    )
    assert resolved.status_code == 200 and resolved.json()["effect"] == result.json()["effect"]
    assert "Invented secure message." not in final.text and c["source"]["note_id"] not in final.text
    (tmp_path / "actual-http-shared-fixtures.json").write_text(
        json.dumps(
            {
                "shared_offer_receipt": offered.json(),
                "shared_offered_detail": offered_detail.json(),
                "shared_accept_receipt": accepted.json(),
                "shared_accepted_detail": accepted_detail.json(),
                "shared_result_receipt": result.json(),
                "shared_result_detail": final.json(),
                "shared_result_resolved": resolved.json(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
