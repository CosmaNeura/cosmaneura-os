from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text

from cosmas_os.application.beta_bootstrap import (
    BetaBootstrapManifest,
    bootstrap_beta_identity,
)
from cosmas_os.application.beta_identity_admin import (
    bind_beta_identity,
    deactivate_beta_identity,
)
from cosmas_os.application.offboarding_acceptance import (
    OFFBOARDING_ACCEPTANCE_CONTRACT,
    OffboardingAcceptanceError,
    baseline_beta_offboarding_acceptance,
    verify_beta_offboarding_acceptance,
)
from cosmas_os.config import Settings
from cosmas_os.models import ExternalIdentity, Principal

BOX_ID = "00000000-0000-4000-8000-000000000301"
HMAC_KEY = bytes.fromhex("c3" * 32)


def _empty_database(session) -> None:
    session.execute(
        text(
            "TRUNCATE external_identities, capability_configs, artifacts, audit_events, "
            "operations, decisions, action_revisions, tickets, appointment_observations, "
            "patient_links, principals, box_contexts CASCADE"
        )
    )


def _runtime() -> Settings:
    return Settings(
        cosmas_env="early_adopter_beta",
        data_mode="synthetic",
        auth_mode="clerk_jwt",
        cors_allowed_origins="https://beta.example.invalid",
        synth_seed=False,
        blob_backend="azure",
        azure_storage_account_url="https://storage.example.invalid",
        azure_blob_container="box-data",
        clerk_issuer="https://clerk.example.invalid",
        clerk_jwks_url="https://clerk.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-beta-api",
        clerk_organization_id="org_test_beta",
        clerk_authorized_parties="https://beta.example.invalid",
        beta_box_id=BOX_ID,
        human_deploy_evidence_ref="deploy:test-review",
        database_url=(
            "postgresql+psycopg://test:test@pg.example.invalid/cosmas_os?"
            "sslmode=verify-full&sslrootcert=system"
        ),
        redis_url=(
            "rediss://:invented-secret@redis.example.invalid:6380/0?ssl_cert_reqs=required"
        ),
        sync_worker=False,
    )


def _setup_target(session) -> tuple[Principal, ExternalIdentity]:
    runtime = _runtime()
    bootstrap_beta_identity(
        session,
        runtime,
        BetaBootstrapManifest.model_validate(
            {
                "schema_version": "cosmas-os/d3-beta-bootstrap/v1",
                "box_id": BOX_ID,
                "clinic_display_name": "Cosmas Synthetic Beta Lab",
                "owner_display_name": "Taylor Owner",
                "clerk_issuer": runtime.clerk_issuer,
                "clerk_subject": "user_test_beta_owner",
                "clerk_organization_id": runtime.clerk_organization_id,
                "reviewed_by": "Test Reviewer",
                "evidence_ref": "deploy:test-review",
            }
        ),
    )
    owner = session.scalar(
        select(Principal).where(Principal.box_id == BOX_ID, Principal.is_owner.is_(True))
    )
    assert owner is not None
    bind_beta_identity(
        session,
        runtime,
        actor_principal_id=owner.id,
        clerk_subject="user_test_offboarding",
        display_name="Synthetic Offboarding Tester",
        evidence_ref="identity-review:test-offboarding-target",
    )
    target = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.subject == "user_test_offboarding"
        )
    )
    assert target is not None
    return owner, target


def _request(session, target: ExternalIdentity) -> str:
    now = session.scalar(select(func.now()))
    assert isinstance(now, datetime)
    return json.dumps(
        {
            "schema_version": 1,
            "contract": "cosmas-os-d3-offboarding-request-v1",
            "box_id": BOX_ID,
            "clerk_issuer": "https://clerk.example.invalid",
            "clerk_organization_id": "org_test_beta",
            "clerk_subject": target.subject,
            "principal_id": target.principal_id,
            "approved_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reviewer_reference": "owner-review:d3-offboarding-test",
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _verification(state) -> str:
    return json.dumps(
        {
            "prior_state": state.model_dump(),
            "owner_confirmation": {
                "schema_version": 1,
                "owner_assertion": (
                    "I CONFIRM D3 CLERK OFFBOARDING AND LIVE ACCESS DENIAL"
                ),
                "challenge": state.confirmation_challenge,
                "baseline_evidence_sha256": state.evidence_sha256,
                "confirmed_at": state.issued_at,
                "confirmation_reference": "clerk-dashboard:test-offboarding",
                "clerk_organization_membership_removed": True,
                "clerk_sessions_revoked": True,
                "live_access_denied": True,
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def test_offboarding_acceptance_binds_target_and_proves_app_denial(session) -> None:
    _empty_database(session)
    owner, target = _setup_target(session)
    runtime = _runtime()
    request = _request(session, target)

    state = baseline_beta_offboarding_acceptance(session, runtime, request, HMAC_KEY)

    serialized = state.sanitized_json()
    assert target.subject not in serialized
    assert target.principal_id not in serialized
    assert BOX_ID not in serialized
    assert state.status == "ready_for_owner"
    assert state.required_deactivation_evidence_ref.startswith("d3-offboarding:")

    deactivate_beta_identity(
        session,
        runtime,
        actor_principal_id=owner.id,
        clerk_subject=target.subject,
        evidence_ref=state.required_deactivation_evidence_ref,
    )
    evidence = verify_beta_offboarding_acceptance(
        session,
        runtime,
        _verification(state),
        HMAC_KEY,
    )

    result = evidence.sanitized_json()
    assert evidence.contract == OFFBOARDING_ACCEPTANCE_CONTRACT
    assert evidence.status == "verified"
    assert evidence.target_binding_inactive
    assert evidence.target_principal_disabled
    assert evidence.deactivation_audit_delta == 1
    assert evidence.application_inactive_binding_denied
    assert evidence.clerk_org_membership_removal_human_attested
    assert evidence.clerk_sessions_revoked_human_attested
    assert evidence.live_access_denial_human_attested
    assert target.subject not in result
    assert target.principal_id not in result
    assert BOX_ID not in result


def test_offboarding_verify_rejects_tampered_or_unperformed_handoff(session) -> None:
    _empty_database(session)
    _owner, target = _setup_target(session)
    state = baseline_beta_offboarding_acceptance(
        session,
        _runtime(),
        _request(session, target),
        HMAC_KEY,
    )

    tampered = json.loads(_verification(state))
    tampered["owner_confirmation"]["challenge"] = "0" * 64
    with pytest.raises(OffboardingAcceptanceError, match="offboarding acceptance failed"):
        verify_beta_offboarding_acceptance(
            session,
            _runtime(),
            json.dumps(tampered),
            HMAC_KEY,
        )

    with pytest.raises(OffboardingAcceptanceError, match="offboarding acceptance failed"):
        verify_beta_offboarding_acceptance(
            session,
            _runtime(),
            _verification(state),
            HMAC_KEY,
        )


def test_offboarding_baseline_rejects_owner_and_wrong_identity_binding(session) -> None:
    _empty_database(session)
    owner, target = _setup_target(session)
    owner_binding = session.scalar(
        select(ExternalIdentity).where(ExternalIdentity.principal_id == owner.id)
    )
    assert owner_binding is not None

    with pytest.raises(OffboardingAcceptanceError, match="offboarding acceptance failed"):
        baseline_beta_offboarding_acceptance(
            session,
            _runtime(),
            _request(session, owner_binding),
            HMAC_KEY,
        )

    wrong = json.loads(_request(session, target))
    wrong["principal_id"] = "00000000-0000-4000-8000-000000000399"
    with pytest.raises(OffboardingAcceptanceError, match="offboarding acceptance failed"):
        baseline_beta_offboarding_acceptance(
            session,
            _runtime(),
            json.dumps(wrong),
            HMAC_KEY,
        )
