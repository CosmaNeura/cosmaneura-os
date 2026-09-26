"""Signed admission with committed synthetic rows and independent revocations."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.api import app as api
from cosmas_os.application import services as svc
from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, PatientLink
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_capture import (
    CoreCaptureAdmissionSnapshot,
    CoreCaptureBindingSnapshot,
    CoreInteractionCredential,
    CoreMountToken,
)


def ref(kind):
    return kind + "_" + "0" * 25 + "1"


class LocalCore:
    def __init__(self):
        self.calls = []
        self.after = lambda _: None
        self.saved = None

    def step(self, name):
        self.calls.append(name)
        self.after(name)

    def exchange_context(self, selection, bearer):
        assert isinstance(bearer, SecretStr)
        self.step("exchange")
        now = datetime.now(UTC)
        return CoreMountToken(
            context_token=SecretStr("synthetic_context_0001"),
            token_type="Bearer",
            issued_at=now,
            refresh_after=now + timedelta(minutes=1),
            expires_at=now + timedelta(minutes=5),
        )

    def resolve_context(self, selection, token):
        self.step("resolve")
        return CoreInteractionCredential(
            mount_context_token=token.context_token,
            interaction_ref="synthetic_interaction_0001",
            client_turn_id=uuid4(),
        )

    def resolve_binding(self, selection, credential):
        self.step("binding")
        return CoreCaptureBindingSnapshot(
            contract_version="1",
            binding_ref=ref("scribe_capture_binding"),
            workspace_id=selection.workspace_id,
            appointment_ref=selection.appointment_ref,
            actor_ref=selection.expected_actor_ref,
            tenant_ref=selection.expected_tenant_ref,
            request_nonce=uuid4(),
            checked_at=datetime.now(UTC),
        )

    def admit_capture(self, binding, credential, attestation, key, *, expected_session_id=None, configured_capture=None):
        self.step("admit")
        if self.saved is None:
            if attestation is None:
                raise ConnectorUnavailable("capture_consent_required")
            self.saved = CoreCaptureAdmissionSnapshot(
                contract_version="1",
                operation_ref=ref("scribe_admission"),
                binding_ref=binding.binding_ref,
                workspace_id=binding.workspace_id,
                appointment_ref=binding.appointment_ref,
                consent_record_id=uuid4(),
                session_id=uuid4(),
                status="admitted",
                request_nonce=uuid4(),
                checked_at=datetime.now(UTC),
            )
        if expected_session_id is not None:
            assert self.saved.session_id == expected_session_id
        return self.saved

    def close(self):
        pass


@pytest.fixture
def capture_case(engine, monkeypatch, request):
    with Session(engine) as session:
        seeded = svc.provision_box(svc.Container(session), "Invented W8d practice")
        seeded["clerk_issuer"] = f"https://clerk-{uuid4().hex}.example.invalid"
        generator = cast(Any, _signed_workspace).__wrapped__(session, seeded, monkeypatch, request)
        case = next(generator)
        case.configuration.workspace_capture_backend = "core"
        case.configuration.core_capture_origin = "https://core.example.invalid"
        case.configuration.core_capture_scope = "api://synthetic-core/.default"
        case.configuration.core_capture_managed_identity_client_id = str(uuid4())
        assert case.configuration.runtime_configuration_errors() == []
        case.appointment.source = "cosmaneura_core"
        case.appointment.external_id = ref("appointment")
        account = CoreCaptureAccount(
            external_identity_id=case.binding.id,
            core_actor_ref=ref("authority_actor"),
            core_tenant_ref=ref("authority_tenant"),
            reviewed_by="Invented reviewer",
            evidence_ref="synthetic:review",
            reviewed_at=datetime.now(UTC),
        )
        session.add_all([case.appointment, account])
        session.commit()
        case.account_id, case.identity_id, case.patient_link_id = (
            account.id,
            case.binding.id,
            case.appointment.patient_link_id,
        )
        case.engine, case.session, case.port = engine, session, LocalCore()
        case.path = f"/workspaces/{case.workspace['id']}/capture/admission"
        # Match production request ownership: a capture deadline must never
        # inherit a different request's SQLAlchemy session budget.
        def request_session():
            with Session(engine) as owned:
                yield owned

        api.app.dependency_overrides[api.get_session] = request_session
        api.app.dependency_overrides[api._capture_connection] = lambda: case.port
        try:
            yield case
        finally:
            api.app.dependency_overrides.pop(api._capture_connection, None)
            generator.close()


def admit(case, attestation: bool | dict[str, object] = True, **changes):
    consent = (
        {
            "modality": "in_person",
            "participant_regions": ["US-NY"],
            "method": "verbal_attestation",
            "all_parties_consented": True,
            "granted_at": datetime.now(UTC).isoformat(),
        }
        if attestation is True
        else (attestation or None)
    )
    return case.client.post(
        case.path,
        headers={"Authorization": "Bearer " + case.token()},
        json={"idempotency_key": uuid4().hex, "attestation": consent, **changes},
    )


def test_signed_workspace_prepares_and_reopens_same_session_without_recording(capture_case):
    f = capture_case
    consent = admit(f, attestation=False)
    assert consent.status_code == 409 and consent.json()["detail"] == "capture_consent_required"
    first = admit(f)
    reopened = admit(f, attestation=False)
    assert first.status_code == reopened.status_code == 200
    assert first.json() == reopened.json() and first.json()["status"] == "prepared"
    assert first.headers["cache-control"] == "no-store"
    assert "context" not in first.text and "appointment_" not in first.text
    assert f.port.calls == ["exchange", "resolve", "binding", "admit"] * 3


@pytest.mark.parametrize("phase", ["exchange", "resolve", "binding", "admit"])
@pytest.mark.parametrize("target", ["identity", "account", "patient"])
def test_independent_revocation_stops_next_phase_or_disclosure(capture_case, phase, target):
    f = capture_case

    def revoke(observed):
        if phase != observed:
            return
        with Session(f.engine) as s:
            s.execute(text("SET LOCAL lock_timeout = '1s'"))
            if target == "identity":
                row = s.get(ExternalIdentity, f.identity_id)
                assert row is not None
                row.active = False
            elif target == "account":
                row = s.get(CoreCaptureAccount, f.account_id)
                assert row is not None
                row.revoked_at = datetime.now(UTC)
            else:
                row = s.get(PatientLink, f.patient_link_id)
                assert row is not None
                row.revoked_at = datetime.now(UTC)
            s.commit()

    f.port.after = revoke
    result = admit(f)
    assert result.status_code in {403, 404, 409}
    assert len(f.port.calls) == ["exchange", "resolve", "binding", "admit"].index(phase) + 1
    assert "session_id" not in result.text


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign_workspace",
        "unbound_user",
        "body_identity",
        "false_consent",
        "truthy",
        "duplicate",
        "oversized",
    ],
)
def test_untrusted_requests_never_reach_core(capture_case, mutation):
    f = capture_case
    headers = {"Authorization": "Bearer " + f.token()}
    if mutation == "foreign_workspace":
        f.path = f"/workspaces/{uuid4()}/capture/admission"
        result = admit(f)
    elif mutation == "unbound_user":
        result = f.client.post(
            f.path,
            headers={"Authorization": "Bearer " + f.token(sub="user_foreign")},
            json={"idempotency_key": uuid4().hex},
        )
    elif mutation == "duplicate":
        result = f.client.post(
            f.path,
            headers={**headers, "Content-Type": "application/json"},
            content='{"idempotency_key":"first-key","idempotency_key":"second-key"}',
        )
    elif mutation == "oversized":
        result = admit(f, extra="private_sentinel" * 200)
    elif mutation == "body_identity":
        result = admit(f, patient_id="private_sentinel")
    else:
        result = admit(
            f,
            attestation={
                "modality": "in_person",
                "participant_regions": ["US-NY"],
                "method": "verbal_attestation",
                "all_parties_consented": False if mutation == "false_consent" else 1,
                "granted_at": datetime.now(UTC).isoformat(),
            },
        )
    assert result.status_code in {403, 404, 422}
    assert not f.port.calls and "private_sentinel" not in result.text


def test_review_history_is_immutable_and_one_active_mapping_is_allowed(capture_case):
    f = capture_case
    with Session(f.engine) as s:
        row = s.get(CoreCaptureAccount, f.account_id)
        assert row is not None
        row.core_actor_ref = ref("authority_actor")[:-1] + "2"
        with pytest.raises(DBAPIError):
            s.commit()
        s.rollback()
        original = s.get(CoreCaptureAccount, f.account_id)
        assert original is not None
        s.add(
            CoreCaptureAccount(
                external_identity_id=original.external_identity_id,
                core_actor_ref=original.core_actor_ref,
                core_tenant_ref=original.core_tenant_ref,
                reviewed_by="Another invented reviewer",
                evidence_ref="synthetic:duplicate",
                reviewed_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        original = s.get(CoreCaptureAccount, f.account_id)
        assert original is not None
        original.revoked_at = datetime.now(UTC)
        s.commit()
        original.revoked_at = None
        with pytest.raises(DBAPIError):
            s.commit()
        s.rollback()
        original = s.get(CoreCaptureAccount, f.account_id)
        assert original is not None
        s.delete(original)
        with pytest.raises(DBAPIError):
            s.commit()
        s.rollback()
        original = s.get(CoreCaptureAccount, f.account_id)
        assert original is not None and original.revoked_at is not None
        replacement = CoreCaptureAccount(
            external_identity_id=original.external_identity_id,
            core_actor_ref=original.core_actor_ref,
            core_tenant_ref=original.core_tenant_ref,
            reviewed_by="Invented replacement reviewer",
            evidence_ref="synthetic:new-review",
            reviewed_at=datetime.now(UTC),
        )
        s.add(replacement)
        s.commit()
        assert replacement.id != original.id
