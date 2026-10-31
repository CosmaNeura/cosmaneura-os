from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from cosmas_os.enrollment.domain import EnrollmentError
from cosmas_os.enrollment.provisioning import ClerkProvisioningPort, EnrollmentProvisioner
from cosmas_os.enrollment.synthetic import create_synthetic_app


class ClerkTransport:
    def __init__(self):
        self.org = None
        self.members = []
        self.creates = 0
        self.lost = True

    def __call__(self, request):
        import json

        if request.method == "POST" and request.url.path == "/v1/organizations":
            body = json.loads(request.content)
            self.org = {**body, "id": "org_invented"}
            self.members.append({"organization": {"id": self.org["id"]}, "role": "org:admin",
                                 "public_user_data": {"user_id": body["created_by"]}})
            self.creates += 1
            if self.lost:
                self.lost = False
                raise httpx.ReadTimeout("Synthetic lost create response")
            return httpx.Response(200, json=self.org)
        if request.url.path.endswith("/memberships"):
            if request.method == "POST":
                body = json.loads(request.content)
                self.members.append({"organization": {"id": "org_invented"}, "role": body["role"],
                                     "public_user_data": {"user_id": body["user_id"]}})
                return httpx.Response(200, json=self.members[-1])
            subject = request.url.params.get("user_id")
            return httpx.Response(200, json={"data": [r for r in self.members if r["public_user_data"]["user_id"] == subject]})
        return httpx.Response(200, json=self.org) if self.org else httpx.Response(404)


@pytest.fixture
def lab():
    app = create_synthetic_app()
    app.state.enrollment_settings.allowed_workspace_origins.append("https://workspace.example.invalid")
    with TestClient(app) as client:
        token = client.post("/lab/session", json={"user": "owner-a"}).json()["token"]
        headers = {"Authorization": "Bearer " + token}

        def write(path, value, method="POST"):
            state = client.get("/enrollment/v1/status", headers=headers).json()
            response = client.request(method, "/enrollment/v1" + path,
                                      headers={**headers, "Idempotency-Key": str(uuid4())},
                                      json={"expected_revision": state["revision"], **value})
            assert response.status_code == 200, response.text
            return response.json()

        write("/profile", {"display_name": "Alex Example", "title": "Owner"}, "PUT")
        write("/practice", {"legal_name": "Example Practice LLC", "display_name": "Example Practice",
            "address_line1": "123 Example Street", "city": "Example City", "region": "NY", "postal_code": "10001",
            "administrative_email": "office@example.invalid", "human_seats": 2, "covered_entity": True}, "PUT")
        baa = client.get("/enrollment/v1/baa/current", headers=headers).json()
        state = write("/baa/accept", {"doc_id": baa["doc_id"], "version": baa["version"], "sha256": baa["sha256"],
            "signature_name": "Alex Example", "signature_title": "Owner", "authority_confirmed": True, "accepted": True})
        transport = ClerkTransport()
        clerk = ClerkProvisioningPort("sk_test_invented", client=httpx.Client(transport=httpx.MockTransport(transport)))
        provisioner = EnrollmentProvisioner(app.state.enrollment_service, clerk)
        yield client, headers, provisioner, transport, state["practice"]["id"]


def prepare(provisioner, practice):
    return provisioner.prepare(practice, api_origin="https://api.workspace.example.invalid",
                               workspace_url="https://workspace.example.invalid/", source_commit="1" * 40,
                               image_sha256="2" * 64)


def runtime(plan, *, role="owner", ready=True, access="connected", patch=None):
    def respond(request):
        if request.url.path == "/practice-access/enrollment-qualification":
            return httpx.Response(200, json={"contract_version": 1, "state": access, "role": role,
                "box_id": plan.box_id, "organization_id": plan.organization_id, "issuer": plan.issuer,
                "subject": plan.owner_subject, "source_commit": plan.source_commit, "image_sha256": plan.image_sha256,
                **(patch or {})},
                                  headers={"Cache-Control": "no-store", "X-Cosmas-Workspace-Protocol": "1"})
        if request.url.path == "/ready" and not ready:
            return httpx.Response(503, json={"detail": "not ready"})
        return httpx.Response(200, json={"status": "ready" if request.url.path == "/ready" else "ok"})
    return httpx.Client(transport=httpx.MockTransport(respond))


def bearer(plan, subject=None):
    # Synthetic unverified transport fixture, not a live Clerk session.
    return jwt.encode({"iss": plan.issuer, "sub": subject or plan.owner_subject,
                       "org_id": plan.organization_id}, "invented-test-secret-at-least-32-characters", algorithm="HS256")


def test_lost_clerk_response_reuses_exact_practice_and_never_starts_trial(lab):
    client, headers, provisioner, transport, practice = lab
    first = prepare(provisioner, practice)
    second = prepare(provisioner, practice)
    assert first == second
    assert transport.creates == 1
    state = client.get("/enrollment/v1/status", headers=headers).json()
    assert state["stage"] == "activation_pending"
    assert state["billing"]["status"] == "none" and state["billing"]["trial_ends_at"] is None
    transport.org["private_metadata"]["cosmas_enrollment"]["owner_subject"] = "user_other"
    with pytest.raises(EnrollmentError, match="saved practice"):
        prepare(provisioner, practice)


def test_only_matching_live_runtime_access_can_qualify_member(lab):
    client, headers, provisioner, _, practice = lab
    plan = prepare(provisioner, practice)
    with pytest.raises(EnrollmentError):
        provisioner.qualify_member(replace(plan, api_origin="https://api.evil.example"),
                                  subject=plan.owner_subject, bearer=bearer(plan), client=runtime(plan))
    for probe in [runtime(plan, ready=False), runtime(plan, role="member"), runtime(plan, access="request_required"),
                  runtime(plan, patch={"box_id": str(uuid4())}), runtime(plan, patch={"image_sha256": "3" * 64}),
                  runtime(plan, patch={"source_commit": "4" * 40})]:
        with pytest.raises(EnrollmentError):
            provisioner.qualify_member(plan, subject=plan.owner_subject, bearer=bearer(plan), client=probe)
        assert client.get("/enrollment/v1/status", headers=headers).json()["stage"] == "activation_pending"
    proof = provisioner.qualify_member(plan, subject=plan.owner_subject, bearer=bearer(plan), client=runtime(plan))
    assert len(proof["sha256"]) == 64 and "Bearer" not in str(proof)
    state = client.get("/enrollment/v1/status", headers=headers).json()
    assert state["stage"] == "payment"
    assert state["workspace"]["url"] is None
    assert state["billing"]["status"] == "none" and state["billing"]["trial_ends_at"] is None


def test_fresh_staff_membership_is_prepared_without_workspace_access_and_rechecks_private_binding(lab):
    client, headers, provisioner, transport, practice = lab
    plan = prepare(provisioner, practice)
    state = client.get("/enrollment/v1/status", headers=headers).json()
    invitation = client.post("/enrollment/v1/invitations", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_revision": state["revision"], "email": "staff-a@example.invalid", "role": "staff", "can_sign": False})
    assert invitation.status_code == 200
    token = client.post("/lab/session", json={"user": "staff-a"}).json()["token"]
    staff = {"Authorization": "Bearer " + token}
    state = client.get("/enrollment/v1/status", headers=staff).json()
    joined = client.post("/enrollment/v1/join", headers={**staff, "Idempotency-Key": str(uuid4())},
                         json={"expected_revision": state["revision"], "token": invitation.json()["token"]})
    assert joined.status_code == 200
    before = len(transport.members)
    provisioner.prepare_memberships(practice)
    assert len(transport.members) == before + 1
    assert transport.members[-1]["role"] == "org:member"
    assert client.get("/enrollment/v1/status", headers=staff).json()["workspace"]["url"] is None
    transport.org["private_metadata"]["cosmas_enrollment"]["owner_subject"] = "user_other"
    with pytest.raises(EnrollmentError):
        provisioner.prepare_memberships(practice)
    with pytest.raises(EnrollmentError):
        provisioner.qualify_member(plan, subject=plan.owner_subject, bearer=bearer(plan), client=runtime(plan))
    assert len(transport.members) == before + 1
