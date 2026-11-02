"""Actual enrollment HTTP/RS256/store paths with invented Clerk and Stripe evidence."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import asdict, replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from cosmas_os.adapters.enrollment_admission import (
    ADMISSION_UNAVAILABLE,
    EnrollmentAdmissionAdapter,
    RuntimeAdmissionError,
)
from cosmas_os.config import Settings
from cosmas_os.enrollment.admission import (
    ADMISSION_HEADER,
    AdmissionRequest,
    derive_runtime_admission_key,
    encode,
    signature,
)
from cosmas_os.enrollment.api import create_app
from cosmas_os.enrollment.auth import ClerkEnrollmentVerifier
from cosmas_os.enrollment.domain import (
    BAA_DOC_ID,
    BAA_SHA256,
    BAA_VERSION,
    EnrollmentError,
    HumanIdentity,
    now_utc,
)
from cosmas_os.enrollment.migration import upgrade
from cosmas_os.enrollment.models import Account, Command, Membership, Practice
from cosmas_os.enrollment.provisioning import (
    BoundWorkspaceConfirmer,
    EnrollmentProvisioner,
    WorkspacePlan,
)
from cosmas_os.enrollment.service import EnrollmentService
from cosmas_os.enrollment.synthetic import SyntheticCommerce, synthetic_settings
from cosmas_os.enrollment.workspace import (
    NATIVE_PROOF_CONTRACT,
    NativeWorkspaceConfirmationRequest,
    NativeWorkspaceProof,
    NativeWorkspaceProofRegistry,
    NativeWorkspaceRecordedAuthority,
    NativeWorkspaceScope,
    WorkspaceConfirmationRequest,
)

APPLE = "capacitor://localhost"
DESKTOP = "app://cosmas"


def invented_native_measurement(scope):
    return {"contract_version": "cosmas-native-workspace-measurement.v1",
        "request": {"method": "GET", "url": scope.workspace_api_origin + "/practice-access/native-qualification",
                    "native_origin": scope.native_origin},
        "response": {"status_code": 200, "headers": {"cache-control": "no-store", "x-cosmas-workspace-protocol": "1"},
            "body": {"contract_version": 1, "state": "connected", "role": "owner", "box_id": scope.box_id,
                "organization_id": scope.organization_id, "issuer": scope.issuer, "subject": "user_fixture",
                "session_id": "sess_fixture", "source_commit": scope.source_commit, "image_sha256": scope.image_sha256,
                "native_origin": scope.native_origin, "initial_setup_complete": True}}}


@pytest.fixture
def native_case(tmp_path):
    settings = synthetic_settings()
    settings.clerk_issuer = "https://native-fixture.clerk.accounts.dev"
    settings.clerk_publishable_key = "pk_test_" + base64.b64encode(b"native-fixture.clerk.accounts.dev$").decode()
    settings.native_account_enabled = True
    settings.native_authorized_origins = [APPLE, DESKTOP]
    settings.allowed_workspace_origins = ["https://practice.example.invalid"]
    settings.provisioning_enabled = False
    settings.database_url = SecretStr("sqlite:///" + str(tmp_path / "registry.sqlite"))
    engine = create_engine(settings.database_url.get_secret_value(), connect_args={"check_same_thread": False})
    upgrade(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    commerce = SyntheticCommerce(settings)
    service = EnrollmentService(factory, settings, commerce)
    human = HumanIdentity(settings.clerk_issuer, "user_fixture", "sess_fixture", "verified@example.invalid", "Example Human")
    service.profile(human, str(uuid4()), {"expected_revision": 0, "display_name": "Example Human", "title": "Owner"})
    service.practice(human, str(uuid4()), {"expected_revision": service.status(human)["revision"],
        "legal_name": "Invented Native Practice LLC", "display_name": "Invented Native Practice",
        "address_line1": "123 Invented Street", "address_line2": "", "city": "Invented City", "region": "NY",
        "postal_code": "10001", "country": "US", "administrative_email": "office@example.invalid",
        "human_seats": 2, "covered_entity": True})
    service.accept(human, str(uuid4()), {"expected_revision": service.status(human)["revision"],
        "doc_id": BAA_DOC_ID, "version": BAA_VERSION, "sha256": BAA_SHA256,
        "signature_name": "Example Human", "signature_title": "Owner", "authority_confirmed": True, "accepted": True})
    practice_id = service.status(human)["practice"]["id"]
    box_id, org = str(uuid4()), "org_fixture123"
    service.record_workspace(practice_id, box_id=box_id, organization_id=org,
        url="https://practice.example.invalid", proof_sha256="1" * 64,
        workspace_api_origin="https://api.practice.example.invalid", source_commit="2" * 40, image_sha256="3" * 64)
    with factory.begin() as session:
        practice = session.get(Practice, practice_id)
        practice.subscription_status = "trialing"
        practice.stripe_subscription_id = "sub_invented"
        practice.billing_verified_at = now_utc()
        practice.trial_ends_at = now_utc() + timedelta(days=14)
    evidence = {"active": True, "verified": True, "member": True, "banned": False, "locked": False}
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_keys(self, refresh):
            return [SimpleNamespace(key_id="key_fixture", key=key.public_key())]

    def clerk(request):
        if "/sessions/" in request.url.path:
            return httpx.Response(200, json={"id": human.session_id, "user_id": human.subject,
                "status": "active" if evidence["active"] else "revoked"})
        if "/memberships" in request.url.path:
            return httpx.Response(200, json={"data": [{"public_user_data": {"user_id": human.subject},
                "organization": {"id": org}}] if evidence["member"] else []})
        return httpx.Response(200, json={"id": human.subject, "banned": evidence["banned"], "locked": evidence["locked"],
            "primary_email_address_id": "email_fixture", "first_name": "Example", "last_name": "Human",
            "email_addresses": [{"id": "email_fixture", "email_address": human.email,
                "verification": {"status": "verified" if evidence["verified"] else "unverified"}}]})

    verifier = ClerkEnrollmentVerifier(settings, client=httpx.Client(transport=httpx.MockTransport(clerk)), jwks_client=Keys())

    def token(changes=None, remove=(), *, browser=False):
        wall = int(time.time())
        claims = {"iss": settings.clerk_issuer, "sub": human.subject, "sid": human.session_id,
                  "iat": wall, "nbf": wall, "exp": wall + 300, "org_id": org, "email": "untrusted@example.invalid"}
        if browser:
            claims["azp"] = settings.public_app_origin
        claims.update(changes or {})
        for name in remove:
            claims.pop(name, None)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key_fixture"})

    def scope(origin=APPLE):
        return NativeWorkspaceScope(practice_id, box_id, org, "https://api.practice.example.invalid",
            "https://practice.example.invalid", "2" * 40, "3" * 64, settings.clerk_issuer, origin)

    authority = NativeWorkspaceProofRegistry([NativeWorkspaceProof.from_measurement(scope(origin),
        invented_native_measurement(scope(origin))) for origin in (APPLE, DESKTOP)])
    app = create_app(settings, engine=engine, verifier=verifier, commerce=commerce, native_workspace_authority=authority)
    with TestClient(app) as client:
        yield SimpleNamespace(settings=settings, factory=factory, service=app.state.enrollment_service,
            human=human, evidence=evidence, token=token, verifier=verifier, authority=authority, scope=scope,
            client=client, app=app, practice_id=practice_id, box_id=box_id, org=org)


def profile(case, **changes):
    return case.client.post("/enrollment/v1/native/workspace-profile",
        headers={"Authorization": "Bearer " + case.token(), "Origin": APPLE},
        json={"client": "apple", "nonce": str(uuid4()), **changes})


def test_ready_native_profile_comes_from_signed_human_registered_practice_and_separate_measurement(native_case):
    c = native_case
    nonce = str(uuid4())
    response = profile(c, nonce=nonce)
    assert response.status_code == 200, response.text
    value = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert value["nonce"] == nonce and value["native_origin"] == APPLE
    assert value["session"] == {"issuer": c.settings.clerk_issuer, "subject": c.human.subject, "session_id": c.human.session_id}
    assert value["nativeIdentity"] == {"version": 1, "profile": "operational-staging-v1", "client": "apple",
        "apiOrigin": c.scope().workspace_api_origin, "frontendOrigin": c.settings.clerk_issuer,
        "publishableKey": c.settings.clerk_publishable_key, "organizationId": c.org, "audience": ""}
    assert value["practice"] == {"practice_id": c.practice_id, "box_id": c.box_id}
    assert value["workspace"]["native_qualification_sha256"] == c.authority.require(c.scope()).qualification_sha256
    assert value["workspace"]["workspace_proof_sha256"] == value["workspace"]["member_proof_sha256"] == "1" * 64
    assert 0 < value["expires_at"] - value["issued_at"] <= 30
    assert "token" not in value and "email" not in value["session"]


def test_native_profile_never_follows_a_baa_offer_version_bump(native_case, monkeypatch):
    c = native_case
    monkeypatch.setattr("cosmas_os.enrollment.service.BAA_VERSION", "9.9")
    monkeypatch.setattr("cosmas_os.enrollment.service.BAA_SHA256", "a" * 64)
    assert profile(c).status_code == 200
    assert c.service.status(c.human)["agreement"]["version"] == "2.3"


@pytest.mark.parametrize("field,value", [("workspace_status", "failed"), ("workspace_proof_sha256", None),
    ("subscription_status", "canceled"), ("source_commit", "b" * 40), ("image_sha256", "c" * 64),
    ("workspace_api_origin", "https://api.other.example.invalid"), ("human_seats", 11)])
def test_unready_unentitled_or_replaced_practice_cannot_supply_native_profile(native_case, field, value):
    c = native_case
    with c.factory.begin() as session:
        setattr(session.get(Practice, c.practice_id), field, value)
    assert profile(c).status_code in (403, 409, 503)


def test_browser_ready_alone_and_unready_member_do_not_qualify_native(native_case):
    c = native_case
    c.service.native_workspace_authority = None
    assert c.service.status(c.human)["stage"] == "ready"
    assert profile(c).status_code == 503
    c.service.native_workspace_authority = c.authority
    with c.factory.begin() as session:
        member = session.scalar(select(Membership).where(Membership.practice_id == c.practice_id))
        member.workspace_ready = False
    assert profile(c).status_code == 409


@pytest.mark.parametrize("field", ["active", "verified", "member", "banned", "locked"])
def test_live_session_user_email_and_org_removal_block_native_profile(native_case, field):
    c = native_case
    c.evidence[field] = field in ("banned", "locked")
    assert profile(c).status_code in (401, 403)


@pytest.mark.parametrize("changes", [{"url": "https://other.example.invalid"}, {"practice_id": str(uuid4())},
    {"email": "verified@example.invalid"}, {"localStorage": {"existing_user": True}}, {"client": "desktop"}])
def test_native_profile_rejects_caller_destinations_identity_flags_and_wrong_client(native_case, changes):
    assert profile(native_case, **changes).status_code in (401, 422)


def test_unregistered_native_account_is_not_created_by_profile_lookup(native_case):
    c = native_case
    with c.factory.begin() as session:
        account = session.scalar(select(Account).where(Account.subject == c.human.subject))
        account.subject = "user_old_fixture"
    assert profile(c).status_code == 403
    with c.factory() as session:
        assert session.scalar(select(Account).where(Account.subject == c.human.subject)) is None


def test_default_browser_requires_azp_even_when_native_path_is_enabled(native_case):
    c = native_case
    assert c.verifier.verify(c.token(browser=True)).subject == c.human.subject
    with pytest.raises(EnrollmentError):
        c.verifier.verify(c.token())
    assert c.verifier.verify_native(c.token(), native_origin=APPLE).email == c.human.email
    c.settings.native_account_enabled = False
    assert c.client.get("/enrollment/v1/status", headers={"Authorization": "Bearer " + c.token(browser=True)}).status_code == 200
    assert profile(c).status_code == 503


@pytest.mark.parametrize("changes", [{"azp": None}, {"azp": ""}, {"azp": "https://app.example.invalid"},
    {"azp": DESKTOP}, {"aud": None}, {"aud": ""}, {"aud": ["invented"]}, {"iss": "https://other.clerk.accounts.dev"}])
def test_native_missing_party_policy_does_not_admit_null_wrong_party_or_audience(native_case, changes):
    with pytest.raises(EnrollmentError):
        native_case.verifier.verify_native(native_case.token(changes), native_origin=APPLE)


def test_native_explicit_scalar_audience_stays_exact(native_case):
    c = native_case
    c.settings.clerk_audience = "invented-native-audience"
    assert c.verifier.verify_native(c.token({"aud": c.settings.clerk_audience}), native_origin=APPLE).subject == c.human.subject
    for value in (None, "", "wrong", [c.settings.clerk_audience]):
        with pytest.raises(EnrollmentError):
            c.verifier.verify_native(c.token({"aud": value}), native_origin=APPLE)


def test_scoped_native_session_must_have_exact_live_org(native_case):
    c = native_case
    assert c.verifier.verify_native_scoped(c.token(), c.org, native_origin=APPLE).subject == c.human.subject
    with pytest.raises(EnrollmentError):
        c.verifier.verify_native_scoped(c.token({"org_id": "org_other"}), c.org, native_origin=APPLE)
    c.evidence["member"] = False
    with pytest.raises(EnrollmentError):
        c.verifier.verify_native_scoped(c.token(), c.org, native_origin=APPLE)


def test_default_admission_wire_omits_new_native_provenance_and_rejects_null_or_worker(native_case):
    c = native_case
    body = AdmissionRequest(practice_id=c.practice_id, box_id=c.box_id, organization_id=c.org,
        issuer=c.settings.clerk_issuer, subject=c.human.subject, purpose="workspace", nonce=str(uuid4()),
        issued_at=int(time.time()), token_sha256=hashlib.sha256(c.token().encode()).hexdigest())
    default = body.model_dump()
    assert set(default) == {"contract_version", "practice_id", "box_id", "organization_id", "issuer", "subject",
        "purpose", "nonce", "issued_at", "token_sha256", "operation_id", "approval_sha256"}
    assert "native_origin" not in body.model_dump_json()
    assert AdmissionRequest.model_validate(default).model_dump() == default
    with pytest.raises(ValidationError):
        AdmissionRequest.model_validate({**default, "native_origin": None})
    with pytest.raises(ValidationError):
        AdmissionRequest.model_validate({**default, "native_origin": APPLE, "purpose": "worker"})


def test_signed_managed_native_admission_requires_current_host_proof_and_preserves_browser(native_case):
    c = native_case
    token = c.token()
    key = derive_runtime_admission_key(c.settings.runtime_admission_secret.get_secret_value(), c.practice_id, c.box_id, c.org)
    request = AdmissionRequest(practice_id=c.practice_id, box_id=c.box_id, organization_id=c.org,
        issuer=c.settings.clerk_issuer, subject=c.human.subject, purpose="workspace", native_origin=APPLE,
        nonce=str(uuid4()), issued_at=int(time.time()), token_sha256=hashlib.sha256(token.encode()).hexdigest())
    raw = encode(request.model_dump())
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json",
               ADMISSION_HEADER: signature(key, raw, direction="request", nonce=request.nonce)}
    result = c.client.post("/enrollment/v1/runtime/admission", content=raw, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["decision"] == "allow" and result.json()["native_origin"] == APPLE
    assert result.headers[ADMISSION_HEADER] == signature(key, result.content, direction="response", nonce=request.nonce)
    c.service.native_workspace_authority = None
    assert c.client.post("/enrollment/v1/runtime/admission", content=raw, headers=headers).status_code == 503
    browser = c.token({"azp": "https://practice.example.invalid"})
    default = request.model_dump()
    default.pop("native_origin")
    default["token_sha256"] = hashlib.sha256(browser.encode()).hexdigest()
    raw = encode(default)
    headers = {"Authorization": "Bearer " + browser, "Content-Type": "application/json",
               ADMISSION_HEADER: signature(key, raw, direction="request", nonce=request.nonce)}
    result = c.client.post("/enrollment/v1/runtime/admission", content=raw, headers=headers)
    assert result.status_code == 200 and result.json()["decision"] == "allow"
    assert "native_origin" not in result.json()


def test_existing_beta_admission_bypasses_native_flags_proof_and_network(monkeypatch):
    monkeypatch.setattr("cosmas_os.adapters.enrollment_admission.existing_user_admission",
        lambda *args: {"decision": "allow", "existing_user": True, "enforced": False})
    adapter = EnrollmentAdmissionAdapter(Settings(_env_file=None), native_origin=APPLE)
    assert adapter.authorize("not-sent", "user_existing")["existing_user"] is True


def test_runtime_native_adapter_carries_signed_origin_through_actual_enrollment_http(native_case):
    c = native_case
    key = derive_runtime_admission_key(c.settings.runtime_admission_secret.get_secret_value(), c.practice_id, c.box_id, c.org)
    runtime = Settings(_env_file=None, cosmas_env="early_adopter_beta", data_mode="synthetic", auth_mode="clerk_jwt",
        workspace_enabled=True, workspace_authenticated_enabled=True, workspace_hosted_enabled=True,
        workspace_apple_hosted_transport_enabled=True, workspace_enrollment_managed=True,
        workspace_enrollment_practice_id=c.practice_id, beta_box_id=c.box_id,
        clerk_issuer=c.settings.clerk_issuer, clerk_organization_id=c.org, clerk_session_policy="enrollment_default", clerk_audience="",
        clerk_authorized_parties=APPLE, cors_allowed_origins=APPLE,
        workspace_enrollment_api_origin="https://enrollment.example.invalid",
        workspace_enrollment_origin_allowlist="https://enrollment.example.invalid,https://app.example.invalid",
        workspace_enrollment_admission_secret=SecretStr(key), workspace_enrollment_account_origin="https://app.example.invalid")
    observed = []

    def wire(request):
        observed.append(json.loads(request.content))
        result = c.client.post(request.url.path, content=request.content, headers=dict(request.headers))
        return httpx.Response(result.status_code, content=result.content, headers=dict(result.headers))

    adapter = EnrollmentAdmissionAdapter(runtime, native_origin=APPLE,
        client=httpx.Client(transport=httpx.MockTransport(wire)))
    result = adapter.authorize(c.token(), c.human.subject)
    assert result["native_origin"] == APPLE and observed[0]["native_origin"] == APPLE
    assert result["enforced"] is True and result["practice_id"] == c.practice_id
    runtime.workspace_apple_hosted_transport_enabled = False
    with pytest.raises(RuntimeAdmissionError) as error:
        adapter.authorize(c.token(), c.human.subject)
    assert error.value.code == ADMISSION_UNAVAILABLE and error.value.status == 503
    assert len(observed) == 1


def test_root_native_registry_requires_exact_measured_scope_and_private_input(native_case, tmp_path):
    c = native_case
    proof = NativeWorkspaceProof.from_measurement(c.scope(), invented_native_measurement(c.scope()))
    with pytest.raises(EnrollmentError):
        NativeWorkspaceProofRegistry([proof, proof])
    with pytest.raises(EnrollmentError):
        c.authority.require(replace(c.scope(), source_commit="f" * 40))
    path = tmp_path / "native-proof.json"
    path.write_text(json.dumps({"contract_version": NATIVE_PROOF_CONTRACT,
        "proofs": [{"scope": asdict(proof.scope), "qualification_sha256": proof.qualification_sha256,
                    "measurement": proof.measurement}]}))
    path.chmod(0o600)
    assert NativeWorkspaceProofRegistry.from_path(path).require(c.scope()) == proof
    path.chmod(0o644)
    with pytest.raises(EnrollmentError):
        NativeWorkspaceProofRegistry.from_path(path)
    path.chmod(0o600)
    linked = tmp_path / "linked-proof.json"
    linked.symlink_to(path)
    with pytest.raises(EnrollmentError):
        NativeWorkspaceProofRegistry.from_path(linked)


@pytest.mark.parametrize("field,value", [("native_origin", DESKTOP), ("session_id", ""),
    ("initial_setup_complete", False), ("source_commit", "f" * 40), ("image_sha256", "f" * 64)])
def test_hash_or_browser_ready_metadata_cannot_substitute_for_native_measurement(native_case, field, value):
    c = native_case
    measurement = invented_native_measurement(c.scope())
    measurement["response"]["body"][field] = value
    with pytest.raises(EnrollmentError):
        NativeWorkspaceProof.from_measurement(c.scope(), measurement)
    with pytest.raises(EnrollmentError):
        NativeWorkspaceProof.from_measurement(c.scope(), invented_native_measurement(c.scope()), "4" * 64)


def test_native_enrollment_operations_use_real_body_validators_and_registered_state(native_case):
    c = native_case
    headers = {"Authorization": "Bearer " + c.token(), "Origin": APPLE}
    def revision():
        return c.client.get("/enrollment/v1/native/status", headers=headers).json()["revision"]
    assert c.client.get("/enrollment/v1/native/config", headers={"Origin": APPLE}).status_code == 200
    for path in ("/practices", "/baa/current", "/baa/receipt", "/quote"):
        assert c.client.get("/enrollment/v1/native" + path, headers=headers).status_code == 200
    response = c.client.put("/enrollment/v1/native/profile", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_revision": revision(), "display_name": "Native Example Human", "title": "Owner"})
    assert response.status_code == 200 and response.json()["profile"]["display_name"] == "Native Example Human"
    response = c.client.post("/enrollment/v1/native/select-practice", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_revision": revision(), "practice_id": c.practice_id})
    assert response.status_code == 200 and response.json()["practice"]["id"] == c.practice_id
    response = c.client.post("/enrollment/v1/native/invitations", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_revision": revision(), "email": "invented-staff@example.invalid", "role": "staff", "can_sign": False})
    assert response.status_code == 200
    current_revision = revision()
    c.settings.native_account_enabled = False
    assert c.client.put("/enrollment/v1/native/profile", headers=headers,
        json={"expected_revision": current_revision, "display_name": "Blocked Native", "title": "Owner"}).status_code == 503


def test_browser_confirmation_dataclass_remains_exact_original_shape(native_case):
    c = native_case
    request = WorkspaceConfirmationRequest(c.practice_id, c.box_id, c.org, c.scope().workspace_api_origin,
        c.scope().workspace_url, c.scope().source_commit, c.scope().image_sha256, c.settings.clerk_issuer,
        c.human.subject, c.human.email, c.human.display_name, "owner")
    assert set(asdict(request)) == {"practice_id", "box_id", "organization_id", "workspace_api_origin", "workspace_url",
        "source_commit", "image_sha256", "issuer", "subject", "email", "display_name", "role"}


def test_new_native_signup_can_save_profile_practice_and_baa_without_borrowing_old_practice(native_case):
    c = native_case
    with c.factory.begin() as session:
        account = session.scalar(select(Account).where(Account.subject == c.human.subject))
        account.subject = "user_retained_old"
    headers = {"Authorization": "Bearer " + c.token(remove=("org_id",)), "Origin": APPLE}
    def write(path, body, method="POST"):
        saved = c.client.get("/enrollment/v1/native/status", headers=headers).json()
        response = c.client.request(method, "/enrollment/v1/native" + path,
            headers={**headers, "Idempotency-Key": str(uuid4())}, json={"expected_revision": saved["revision"], **body})
        assert response.status_code == 200, response.text
        return response.json()
    write("/profile", {"display_name": "New Native Owner", "title": "Owner"}, "PUT")
    state = write("/practice", {"legal_name": "New Invented Practice LLC", "display_name": "New Invented Practice",
        "address_line1": "123 New Street", "city": "Invented City", "region": "NY", "postal_code": "10001",
        "country": "US", "administrative_email": "new-office@example.invalid", "human_seats": 1, "covered_entity": True}, "PUT")
    assert state["practice"]["id"] != c.practice_id and state["workspace"]["box_id"] is None
    document = c.client.get("/enrollment/v1/native/baa/current", headers=headers).json()
    state = write("/baa/accept", {"doc_id": document["doc_id"], "version": document["version"], "sha256": document["sha256"],
        "signature_name": "New Native Owner", "signature_title": "Owner", "authority_confirmed": True, "accepted": True})
    assert state["stage"] == "activation_pending" and state["agreement"]["accepted"]
    assert c.client.get("/enrollment/v1/native/baa/receipt", headers=headers).status_code == 200
    response = c.client.post("/enrollment/v1/native/checkout", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_revision": state["revision"]})
    assert response.status_code == 503
    assert not c.app.state.enrollment_service.commerce.sessions


def native_confirmer(case, patch=None, confirming_human=None):
    c = case
    scope = c.scope()
    plan = WorkspacePlan(scope.practice_id, scope.box_id, scope.organization_id, c.human.subject, scope.issuer,
        scope.workspace_api_origin, scope.workspace_url, scope.source_commit, scope.image_sha256)
    binding = {"contract": "cosmas-enrollment-workspace.v1", "practice_id": plan.practice_id,
        "box_id": plan.box_id, "owner_subject": c.human.subject, "issuer": plan.issuer}
    clerk = SimpleNamespace(request=lambda *args: {"id": c.org, "slug": "cosmas-" + c.practice_id,
        "created_by": c.human.subject, "private_metadata": {"cosmas_enrollment": binding}}, membership=lambda *args: None)
    provisioner = EnrollmentProvisioner(c.service, clerk)
    observed = []
    actor = confirming_human or c.human
    role = "member" if confirming_human else "owner"
    def runtime(request):
        observed.append((request.url.path, request.headers.get("origin")))
        if request.url.path == "/practice-access/setup":
            return httpx.Response(200, json={"contract_version": 1, "state": "owner_ready"},
                headers={"Cache-Control": "no-store", "X-Cosmas-Workspace-Protocol": "1"})
        if request.url.path == "/practice-access/native-qualification":
            return httpx.Response(200, json={**invented_native_measurement(scope)["response"]["body"],
                "subject": actor.subject, "session_id": actor.session_id, "role": role, **(patch or {})},
                headers={"Cache-Control": "no-store", "X-Cosmas-Workspace-Protocol": "1"})
        if request.url.path == "/practice-access/enrollment-qualification":
            body = {**invented_native_measurement(scope)["response"]["body"], "subject": actor.subject, "role": role,
                "enrollment_admission": {"contract_version": "cosmas-enrollment-admission.v1", "enforced": True,
                    "practice_id": c.practice_id, "purpose": "qualification"}}
            body.pop("native_origin")
            body.pop("session_id")
            return httpx.Response(200, json=body,
                headers={"Cache-Control": "no-store", "X-Cosmas-Workspace-Protocol": "1"})
        return httpx.Response(200, json={"status": "ready" if request.url.path == "/ready" else "ok"})
    actual_qualify = provisioner.qualify_member
    provisioner.qualify_member = lambda plan, **kwargs: actual_qualify(plan,
        client=httpx.Client(transport=httpx.MockTransport(runtime)), **kwargs)
    confirmer = BoundWorkspaceConfirmer(c.service, clerk)
    confirmer.provisioner = provisioner
    request = NativeWorkspaceConfirmationRequest(plan.practice_id, plan.box_id, plan.organization_id, plan.api_origin,
        plan.workspace_url, plan.source_commit, plan.image_sha256, plan.issuer, actor.subject,
        actor.email, actor.display_name, "staff" if confirming_human else "owner", APPLE)
    return confirmer, request, observed


def test_initial_native_confirmation_prepares_only_then_requires_exact_scoped_session(native_case):
    c = native_case
    confirmer, request, observed = native_confirmer(c)
    assert confirmer.confirm(request, c.token(remove=("org_id",))).proof_sha256 is None
    assert observed == []
    with pytest.raises(EnrollmentError):
        confirmer.confirm(request, c.token({"org_id": "org_wrong"}))
    result = confirmer.confirm(request, c.token())
    assert result.proof_sha256 and ("/practice-access/native-qualification", APPLE) in observed
    assert all(origin == APPLE for _, origin in observed)


@pytest.mark.parametrize("patch", [{"native_origin": DESKTOP}, {"session_id": "sess_other"}, {"initial_setup_complete": False}])
def test_native_confirmation_never_marks_member_ready_from_browser_or_wrong_session_proof(native_case, patch):
    c = native_case
    confirmer, _, _ = native_confirmer(c, patch)
    with c.factory.begin() as session:
        member = session.scalar(select(Membership).where(Membership.practice_id == c.practice_id))
        member.workspace_ready = False
    with pytest.raises(EnrollmentError):
        c.service.confirm_workspace(c.human, str(uuid4()), c.service.status(c.human)["revision"],
            c.token(), confirmer, native_origin=APPLE)
    with c.factory() as session:
        assert not session.scalar(select(Membership).where(Membership.practice_id == c.practice_id)).workspace_ready


def test_native_bootstrap_records_real_qualification_before_card_and_survives_authority_restart(native_case):
    c = native_case
    c.service.native_workspace_authority = NativeWorkspaceRecordedAuthority(c.factory)
    c.settings.provisioning_enabled = True
    with c.factory.begin() as session:
        practice = session.get(Practice, c.practice_id)
        practice.workspace_status = "provisioning"
        practice.subscription_status = "none"
        practice.stripe_subscription_id = None
        practice.billing_verified_at = None
        practice.trial_ends_at = None
        member = session.scalar(select(Membership).where(Membership.practice_id == c.practice_id))
        member.workspace_ready = False
        member.workspace_proof_sha256 = None
    body = AdmissionRequest(practice_id=c.practice_id, box_id=c.box_id, organization_id=c.org,
        issuer=c.settings.clerk_issuer, subject=c.human.subject, purpose="qualification", native_origin=APPLE,
        nonce=str(uuid4()), issued_at=int(time.time()), token_sha256=hashlib.sha256(c.token().encode()).hexdigest())
    assert c.service.runtime_admission(c.human, body)["decision"] == "allow"
    with pytest.raises(EnrollmentError):
        c.service.require_native_workspace(c.human, APPLE)
    assert not c.service.commerce.sessions
    confirmer, _, observed = native_confirmer(c)
    state = c.service.confirm_workspace(c.human, str(uuid4()), c.service.status(c.human)["revision"],
        c.token(), confirmer, native_origin=APPLE)
    assert state["workspace"]["status"] == "ready"
    assert ("/practice-access/native-qualification", APPLE) in observed
    # A newly constructed authority reads the persisted actual measurement;
    # neither a per-customer proof file nor a runtime admission probe is needed.
    restarted = NativeWorkspaceRecordedAuthority(c.factory)
    proof = restarted.require(c.scope())
    assert proof.measurement["response"]["body"]["session_id"] == c.human.session_id
    c.service.native_workspace_authority = restarted
    denied = profile(c)
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "enrollment_billing_required"
    headers = {"Authorization": "Bearer " + c.token(), "Origin": APPLE, "Idempotency-Key": str(uuid4())}
    checkout = c.client.post("/enrollment/v1/native/checkout", headers=headers, json={"expected_revision": state["revision"]})
    assert checkout.status_code == 200, checkout.text
    assert c.service.commerce.create_count == 1
    session_id = next(iter(c.service.commerce.sessions))
    c.service.commerce.complete(session_id)
    recovered = c.client.post("/enrollment/v1/native/recover", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_revision": c.service.status(c.human)["revision"]})
    assert recovered.status_code == 200, recovered.text
    assert profile(c).status_code == 200
    with c.factory() as session:
        receipt = session.scalar(select(Command).where(Command.operation == "workspace_confirm")).response
        assert "native_qualification" in receipt
        assert "workspace_token" not in json.dumps(receipt)
        assert "email" not in json.dumps(receipt["native_qualification"])


@pytest.mark.parametrize("mutation", ["digest", "scope", "incomplete"])
def test_recorded_native_authority_rejects_tampered_or_incomplete_confirmation(native_case, mutation):
    c = native_case
    confirmer, _, _ = native_confirmer(c)
    c.service.confirm_workspace(c.human, str(uuid4()), c.service.status(c.human)["revision"],
        c.token(), confirmer, native_origin=APPLE)
    with c.factory.begin() as session:
        command = session.scalar(select(Command).where(Command.operation == "workspace_confirm"))
        receipt = json.loads(json.dumps(command.response))
        if mutation == "digest":
            receipt["native_qualification"]["qualification_sha256"] = "0" * 64
        elif mutation == "scope":
            receipt["native_qualification"]["scope"]["image_sha256"] = "f" * 64
        else:
            receipt["completed"] = False
        command.response = receipt
    with pytest.raises(EnrollmentError):
        NativeWorkspaceRecordedAuthority(c.factory).require(c.scope())


def test_invited_native_staff_uses_bounded_registration_before_pure_transport_measurement(native_case):
    c = native_case
    staff = HumanIdentity(c.settings.clerk_issuer, "user_invented_staff", "sess_invented_staff",
        "invented-staff@example.invalid", "Invented Staff")
    invite = c.service.invite(c.human, str(uuid4()), {"expected_revision": c.service.status(c.human)["revision"],
        "email": staff.email, "role": "staff", "can_sign": False})
    c.service.join(staff, str(uuid4()), {"expected_revision": 0, "token": invite["token"]})
    confirmer, _, observed = native_confirmer(c, confirming_human=staff)
    token = c.token({"sub": staff.subject, "sid": staff.session_id})
    state = c.service.confirm_workspace(staff, str(uuid4()), c.service.status(staff)["revision"],
        token, confirmer, native_origin=APPLE)
    preparation = ("/practice-access/enrollment-qualification", APPLE)
    measurement = ("/practice-access/native-qualification", APPLE)
    assert observed.index(preparation) < observed.index(measurement)
    assert state["workspace"]["status"] == "ready"
    with c.factory() as session:
        account = session.scalar(select(Account).where(Account.subject == staff.subject))
        member = session.scalar(select(Membership).where(Membership.account_id == account.id))
        assert member.role == "staff" and member.workspace_ready
        receipt = session.scalar(select(Command).where(Command.account_id == account.id, Command.operation == "workspace_confirm")).response
        assert receipt["native_qualification"]["measurement"]["response"]["body"]["subject"] == staff.subject


@pytest.mark.parametrize("template", [
    "https://{other}.staging.cosmas.ai", "https://accounts.staging.cosmas.ai", "https://app.staging.cosmas.ai",
    "https://staging.cosmas.ai", "https://{practice}.staging.cosmas.ai.evil.invalid",
    "http://{practice}.staging.cosmas.ai", "https://{practice}.staging.cosmas.ai:443",
    "https://user@{practice}.staging.cosmas.ai", "https://{practice}.staging.cosmas.ai/Chief",
    "https://{practice}.staging.cosmas.ai?practice=1", "https://{practice}.staging.cosmas.ai#Chief",
])
def test_allocated_namespace_rejects_wrong_practice_reserved_hosts_and_non_origins(native_case, template):
    c = native_case
    c.settings.workspace_allocation_enabled = True
    value = template.format(practice=c.practice_id, other=str(uuid4()))
    assert not c.settings.registered_workspace_origin(value, c.practice_id)


def test_allocated_namespace_is_opt_in_synthetic_and_preserves_exact_reviewed_origins(native_case):
    c = native_case
    value = "https://" + c.practice_id + ".staging.cosmas.ai"
    assert c.settings.registered_workspace_origin("https://practice.example.invalid", c.practice_id)
    assert not c.settings.registered_workspace_origin(value, c.practice_id)
    c.settings.workspace_allocation_enabled = True
    assert c.settings.registered_workspace_origin(value, c.practice_id)
    assert not c.settings.registered_workspace_origin(value, c.practice_id.upper())
    c.settings.data_mode = "production"
    assert not c.settings.registered_workspace_origin(value, c.practice_id)
    assert c.settings.registered_workspace_origin("https://practice.example.invalid", c.practice_id)


def test_canonical_allocated_practice_origin_is_bound_to_registered_profile_and_runtime_scope(native_case):
    c = native_case
    origin = "https://" + c.practice_id + ".staging.cosmas.ai"
    api_origin = "https://api." + c.practice_id + ".staging.cosmas.ai"
    with c.factory.begin() as session:
        practice = session.get(Practice, c.practice_id)
        practice.workspace_url = origin + "/Chief"
        practice.workspace_api_origin = api_origin
    scope = NativeWorkspaceScope(c.practice_id, c.box_id, c.org, api_origin, origin + "/Chief",
        "2" * 40, "3" * 64, c.settings.clerk_issuer, APPLE)
    c.service.native_workspace_authority = NativeWorkspaceProofRegistry([
        NativeWorkspaceProof.from_measurement(scope, invented_native_measurement(scope))])
    assert profile(c).status_code == 503
    c.settings.workspace_allocation_enabled = True
    c.settings.provisioning_enabled = True
    response = profile(c)
    assert response.status_code == 200, response.text
    assert response.json()["nativeIdentity"]["apiOrigin"] == api_origin
    request = AdmissionRequest(practice_id=c.practice_id, box_id=c.box_id, organization_id=c.org,
        issuer=c.settings.clerk_issuer, subject=c.human.subject, purpose="workspace", native_origin=APPLE,
        nonce=str(uuid4()), issued_at=int(time.time()), token_sha256=hashlib.sha256(c.token().encode()).hexdigest())
    assert c.service.runtime_authorized_parties(request) == [origin]
    with c.factory.begin() as session:
        practice = session.get(Practice, c.practice_id)
        practice.workspace_url = "https://" + str(uuid4()) + ".staging.cosmas.ai/Chief"
    assert profile(c).status_code == 503
