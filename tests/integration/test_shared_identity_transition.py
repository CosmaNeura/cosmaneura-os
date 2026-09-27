import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from cosmas_os.api.auth import authenticate_request
from cosmas_os.config import Settings
from cosmas_os.models import AuditEvent, BoxContext, CoreCaptureAccount, ExternalIdentity, Principal

spec = importlib.util.spec_from_file_location("shared_identity_operator",
    Path(__file__).resolve().parents[2] / "infra/beta/vm/operator/workspace_identity.py")
operator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = operator
spec.loader.exec_module(operator)


@pytest.fixture
def transition_case(session, seeded):
    source = ExternalIdentity(box_id=seeded["box_id"], principal_id=seeded["owner_id"],
        provider="clerk", issuer="https://identity.example.invalid", subject="user_original",
        organization_id="org_original", active=True, reviewed_by="Invented reviewer", evidence_ref="test:original")
    session.add(source)
    session.flush()
    plan = operator.Transition(contract="cosmas-shared-staging-identity-v1", transition_id=str(uuid4()),
        box_id=source.box_id, owner_id=source.principal_id, source_id=source.id, target_id=str(uuid4()),
        source_issuer=source.issuer, source_subject=source.subject, source_organization=source.organization_id,
        target_issuer="https://invented.clerk.accounts.dev", target_subject="user_shared", target_organization="org_shared",
        reviewed_by="Invented reviewer", evidence_ref="test:shared-transition", target_membership_verified=True,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat())
    runtime = Settings(_env_file=None, cosmas_env="early_adopter_beta", data_mode="synthetic",
        auth_mode="clerk_jwt", synth_seed=False, sync_worker=False, blob_backend="azure",
        azure_storage_account_url="https://storage.example.invalid", azure_blob_container="box-data",
        database_url="postgresql+psycopg://test:test@pg.example.invalid/cosmas_os?sslmode=verify-full&sslrootcert=system",
        redis_url="rediss://:invented-secret@redis.example.invalid:6380/0?ssl_cert_reqs=required",
        beta_box_id=source.box_id, clerk_issuer=source.issuer, clerk_organization_id=source.organization_id,
        clerk_audience="cosmas-api", clerk_jwks_url=source.issuer + "/.well-known/jwks.json",
        clerk_authorized_parties="https://beta.example.invalid", cors_allowed_origins="https://beta.example.invalid",
        human_deploy_evidence_ref="test:reviewed-staging")
    return source, plan, runtime


def rows(session, model):
    return [{column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in session.scalars(select(model).order_by(model.id))]


def test_apply_is_additive_audited_idempotent_and_keeps_the_same_workspace_owner(session, transition_case):
    source, plan, runtime = transition_case
    boxes, people, original = rows(session, BoxContext), rows(session, Principal), rows(session, ExternalIdentity)
    before_audit = session.scalar(select(func.count()).select_from(AuditEvent))
    assert operator.transition(session, runtime, plan, "plan")["status"] == "ready"
    assert rows(session, ExternalIdentity) == original
    assert operator.transition(session, runtime, plan, "apply")["status"] == "applied"
    assert operator.transition(session, runtime, plan, "apply")["status"] == "already_applied"
    assert rows(session, BoxContext) == boxes and rows(session, Principal) == people
    assert next(row for row in rows(session, ExternalIdentity) if row["id"] == source.id) == original[0]
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == before_audit + 1
    runtime.clerk_issuer, runtime.clerk_organization_id = plan.target_issuer, plan.target_organization

    class VerifiedSharedSession:
        def verify(self, token):
            return {"sub": plan.target_subject, "org_id": plan.target_organization}

    identity = authenticate_request(session, runtime, authorization="Bearer invented", box_header=None,
                                    actor_header=None, verifier=VerifiedSharedSession())
    assert (identity.box_id, identity.principal_id, identity.external_identity_id) == (plan.box_id, plan.owner_id, plan.target_id)


def test_rollback_preserves_original_binding_and_history_and_can_use_renewed_maintenance(session, transition_case):
    source, plan, runtime = transition_case
    original = rows(session, ExternalIdentity)
    operator.transition(session, runtime, plan, "apply")
    renewed = plan.model_copy(update={"expires_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat()})
    assert renewed.digest() == plan.digest()
    assert operator.transition(session, runtime, renewed, "rollback")["status"] == "rolled_back"
    assert operator.transition(session, runtime, renewed, "rollback")["status"] == "already_rolled_back"
    assert session.get(ExternalIdentity, plan.target_id).active is False
    assert next(row for row in rows(session, ExternalIdentity) if row["id"] == source.id) == original[0]
    with pytest.raises(operator.Refused, match="cannot_reapply"):
        operator.transition(session, runtime, renewed, "apply")


@pytest.mark.parametrize("change", ["source_subject", "source_revoked", "owner_disabled", "owner_not_owner", "wrong_runtime"])
def test_changed_authority_refuses_without_new_identity_or_audit(session, transition_case, change):
    source, plan, runtime = transition_case
    if change == "source_subject":
        source.subject = "user_other"
    elif change == "source_revoked":
        source.active = False
    elif change == "wrong_runtime":
        runtime.beta_box_id = str(uuid4())
    else:
        owner = session.get(Principal, plan.owner_id)
        if change == "owner_disabled":
            owner.state = "disabled"
        else:
            owner.is_owner = False
    session.flush()
    before, audit = rows(session, ExternalIdentity), rows(session, AuditEvent)
    with pytest.raises(operator.Refused):
        operator.transition(session, runtime, plan, "apply")
    assert rows(session, ExternalIdentity) == before and rows(session, AuditEvent) == audit


def test_existing_target_is_never_adopted_or_overwritten(session, transition_case):
    _, plan, runtime = transition_case
    target = ExternalIdentity(id=plan.target_id, box_id=plan.box_id, principal_id=plan.owner_id,
        provider="clerk", issuer=plan.target_issuer, subject=plan.target_subject, organization_id=plan.target_organization,
        reviewed_by="Different reviewer", evidence_ref="test:unrelated")
    session.add(target)
    session.flush()
    before = rows(session, ExternalIdentity)
    with pytest.raises(operator.Refused, match="target_binding_changed"):
        operator.transition(session, runtime, plan, "apply")
    assert rows(session, ExternalIdentity) == before


def test_existing_core_grant_requires_explicit_connection_transition(session, transition_case):
    source, plan, runtime = transition_case
    session.add(CoreCaptureAccount(external_identity_id=source.id,
        core_actor_ref="authority_actor_" + "0" * 26, core_tenant_ref="authority_tenant_" + "0" * 26,
        reviewed_by="Invented reviewer", evidence_ref="test:existing-core", reviewed_at=datetime.now(UTC)))
    session.flush()
    with pytest.raises(operator.Refused, match="connected_account_requires_separate_transition"):
        operator.transition(session, runtime, plan, "apply")
    assert session.get(ExternalIdentity, plan.target_id) is None


def test_expired_or_changed_manifest_and_transaction_failure_leave_binding_absent(session, transition_case):
    _, plan, runtime = transition_case
    for expires in ["2020-01-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00", "2026-09-27T00:00:00"]:
        with pytest.raises(operator.Refused):
            operator.transition(session, runtime, plan.model_copy(update={"expires_at": expires}), "apply")
    with pytest.raises(RuntimeError), session.begin_nested():
        operator.transition(session, runtime, plan, "apply")
        raise RuntimeError("invented commit failure")
    assert session.get(ExternalIdentity, plan.target_id) is None
    raw = plan.model_dump_json()
    assert operator.load_plan(raw) == plan
    with pytest.raises(operator.Refused, match="duplicate_manifest_field"):
        operator.load_plan(raw.replace('"contract":', '"target_id":"invented-duplicate","contract":', 1))
    for changed in [{"target_membership_verified": False}, {"target_membership_verified": 1},
                    {"extra": "refused"}, {"target_issuer": "https://production.invalid"}]:
        with pytest.raises(ValueError):
            operator.load_plan(json.dumps(plan.model_dump() | changed))
