"""Real owned PostgreSQL + signed invented identity, with external HTTP denied.

Run explicitly with COSMABOT_STANDALONE_TESTS=1 against a fresh migrated database
named cosmabot_standalone_* and its independently installed UUID ownership marker.
The normal shared test database must never be relabelled or truncated for this lab.
"""

import json
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from tests.unit.test_practice_access import verifier
from tests.unit.test_standalone_practice_manifest import manifest_input

from cosmas_os.api.auth import AccessDenied, AuthenticationFailed, authenticate_request
from cosmas_os.api.practice_access_routes import verified
from cosmas_os.api.practice_access_schemas import CompletePracticeSetup
from cosmas_os.application import practice_access, practice_setup, workspace
from cosmas_os.application.standalone_practice import (
    StandalonePracticeError,
    StandalonePracticeManifest,
    reserve_standalone_practice,
    seed_standalone_practice,
)
from cosmas_os.config import Settings
from cosmas_os.models import (
    AppointmentObservation,
    AuditEvent,
    BoxContext,
    CoreCaptureAccount,
    EncounterWorkspace,
    ExternalIdentity,
    PatientLink,
    Principal,
    Ticket,
)
from cosmas_os.practice_setup_models import PracticeOwnerReservation


@pytest.fixture
def case(session, tmp_path, monkeypatch):
    if os.environ.get("COSMABOT_STANDALONE_TESTS") != "1":
        pytest.skip("requires an explicitly owned standalone qualification database")
    database = session.scalar(text("SELECT current_database()"))
    marker = session.scalar(text("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()"))
    if not database.startswith("cosmabot_standalone_") or not str(marker).startswith("cosmabot-standalone:"):
        pytest.fail("standalone qualification database ownership was not established")
    instance = UUID(marker.removeprefix("cosmabot-standalone:"))
    assert instance.version == 4
    value = manifest_input()
    value.update(database_name=database, instance_id=str(instance), dataset_id=str(uuid4()))
    value["identity"].update(box_id=str(uuid4()), clerk_issuer=f"https://{instance}.cosmabot.invalid",
                             clerk_organization_id="org_cosmabot_" + instance.hex)
    manifest = StandalonePracticeManifest.model_validate(value)
    values = json.loads((Path(__file__).parents[1] / "fixtures/hosted-workspace-settings.json").read_text())
    values.update(cosmas_env="standalone_synthetic", standalone_instance_id=str(instance),
        standalone_root=str(tmp_path), standalone_jwks_path=str(tmp_path / "keys/jwks.json"),
        beta_box_id=str(manifest.identity.box_id), clerk_issuer=manifest.identity.clerk_issuer,
        clerk_jwks_url=manifest.identity.clerk_issuer + "/.well-known/jwks.json",
        clerk_audience="cosmabot-standalone:" + str(instance),
        clerk_organization_id=manifest.identity.clerk_organization_id,
        human_deploy_evidence_ref=manifest.identity.evidence_ref,
        database_url=session.bind.engine.url.render_as_string(hide_password=False),
        redis_url="", blob_backend="local", blob_root=str(tmp_path / "blobs"),
        azure_storage_account_url=None, azure_blob_container=None,
        workspace_hosted_enabled=False, cors_allowed_origins="http://127.0.0.1:51547",
        clerk_authorized_parties="http://127.0.0.1:51547", workspace_llm_endpoint="")
    config = Settings(_env_file=None, **values)
    config.validate_runtime_configuration()
    calls = []

    def denied(*_args, **_kwargs):
        calls.append("external_http")
        raise AssertionError("independent practice attempted external HTTP")

    async def denied_async(*_args, **_kwargs):
        return denied()

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied_async)
    owner = practice_access.VerifiedMember(config.beta_box_id, config.clerk_issuer,
                                          config.clerk_organization_id, manifest.identity.clerk_subject)
    c = SimpleNamespace(session=session, manifest=manifest, config=config, owner=owner, calls=calls)
    c.checked, c.token = verifier(c)
    yield c
    assert calls == []


def count(c, model):
    return c.session.scalar(select(func.count()).select_from(model))


def reserve(c):
    return reserve_standalone_practice(c.session, c.config, c.manifest)


def complete(c, member=None, **claim_changes):
    bearer = "Bearer " + c.token(member or c.owner, **claim_changes)
    admitted = verified(c.config, bearer, c.checked)
    command = CompletePracticeSetup(idempotency_key=uuid4(),
        practice_name=c.manifest.identity.clinic_display_name,
        display_name=c.manifest.identity.owner_display_name, confirm=True)
    result = practice_setup.complete(c.session, c.config, admitted, command, fence=lambda: None)
    assert result["state"] == "owner_ready"
    return authenticate_request(c.session, c.config, authorization=bearer,
                                box_header=None, actor_header=None, verifier=c.checked)


def test_reservation_is_atomic_idempotent_and_grants_no_login_or_records(case):
    c = case
    first = reserve(c)
    assert first == reserve(c)
    assert first["phase"] == "reserved" and first["owner_binding_checked"] is False
    assert count(c, BoxContext) == count(c, PracticeOwnerReservation) == 1
    assert count(c, Principal) == count(c, ExternalIdentity) == count(c, PatientLink) == 0
    assert count(c, AuditEvent) == 1
    with pytest.raises(AccessDenied, match="not provisioned"):
        authenticate_request(c.session, c.config, authorization="Bearer " + c.token(c.owner),
                             box_header=None, actor_header=None, verifier=c.checked)


def test_refuses_any_existing_practice_without_relabelling_or_granting_access(case):
    c = case
    original_id = str(uuid4())
    c.session.add(BoxContext(id=original_id, display_name="Existing invented Lab"))
    c.session.commit()
    with pytest.raises(StandalonePracticeError, match="empty_database_required"):
        reserve(c)
    assert c.session.get(BoxContext, original_id).display_name == "Existing invented Lab"
    assert count(c, PracticeOwnerReservation) == count(c, ExternalIdentity) == 0


def test_refuses_other_database_name_and_stale_migration(case):
    c = case
    other = c.manifest.model_copy(update={"database_name": "cosmabot_standalone_other"})
    with pytest.raises(StandalonePracticeError, match="database_ownership_required"):
        reserve_standalone_practice(c.session, c.config, other)
    c.session.execute(text("UPDATE alembic_version SET version_num='invented_wrong_head'"))
    with pytest.raises(StandalonePracticeError, match="migrated_database_required"):
        reserve(c)
    assert count(c, BoxContext) == 0


def test_other_valid_instance_namespace_cannot_reuse_owned_database(case):
    c = case
    instance = uuid4()
    issuer = f"https://{instance}.cosmabot.invalid"
    organization = "org_cosmabot_" + instance.hex
    data = c.manifest.model_dump(mode="json")
    data.update(instance_id=str(instance))
    data["identity"].update(clerk_issuer=issuer, clerk_organization_id=organization)
    manifest = StandalonePracticeManifest.model_validate(data)
    runtime = c.config.model_copy(update={"standalone_instance_id": str(instance),
        "clerk_issuer": issuer, "clerk_jwks_url": issuer + "/.well-known/jwks.json",
        "clerk_audience": "cosmabot-standalone:" + str(instance), "clerk_organization_id": organization})
    runtime.validate_runtime_configuration()
    with pytest.raises(StandalonePracticeError, match="database_ownership_required"):
        reserve_standalone_practice(c.session, runtime, manifest)
    assert count(c, BoxContext) == count(c, ExternalIdentity) == 0


def test_changed_manifest_or_reserved_identity_cannot_replay(case):
    c = case
    reserve(c)
    changed = c.manifest.model_dump(mode="json")
    changed["patients"][0]["label"] = "Invented Changed Person"
    with pytest.raises(StandalonePracticeError, match="manifest_conflict"):
        reserve_standalone_practice(c.session, c.config, StandalonePracticeManifest.model_validate(changed))
    row = c.session.get(PracticeOwnerReservation, c.config.beta_box_id)
    row.subject = "user_invented_different_owner"
    with pytest.raises(DBAPIError, match="owner reservation is immutable"):
        c.session.commit()
    c.session.rollback()
    assert c.session.get(PracticeOwnerReservation, c.config.beta_box_id).subject == c.owner.subject
    assert reserve(c)["phase"] == "reserved"
    assert count(c, Principal) == count(c, PatientLink) == 0


def test_seed_waits_for_exact_signed_owner_and_never_matches_email(case):
    c = case
    reserve(c)
    with pytest.raises(StandalonePracticeError, match="verified_owner_setup_required"):
        seed_standalone_practice(c.session, c.config, c.manifest)
    other = practice_access.VerifiedMember(c.owner.box_id, c.owner.issuer, c.owner.organization_id,
                                           "user_invented_other_subject")
    with pytest.raises(practice_access.PracticeAccessError):
        complete(c, other, email="invented-same-address@example.invalid")
    c.session.rollback()
    assert count(c, ExternalIdentity) == count(c, PatientLink) == 0
    complete(c, email="invented-same-address@example.invalid")
    assert seed_standalone_practice(c.session, c.config, c.manifest)["owner_binding_checked"] is True


@pytest.mark.parametrize("claims", [{"iss": "https://other.cosmabot.invalid"}, {"org_id": "org_other"}, {"aud": "other"}])
def test_wrong_signed_issuer_org_or_audience_cannot_claim_practice(case, claims):
    c = case
    reserve(c)
    with pytest.raises((AccessDenied, AuthenticationFailed)):
        complete(c, **claims)
    assert count(c, Principal) == count(c, ExternalIdentity) == 0


def test_expired_reservation_cannot_claim_practice(case, monkeypatch):
    c = case
    reserve(c)
    expires = c.session.get(PracticeOwnerReservation, c.config.beta_box_id).expires_at
    monkeypatch.setattr(practice_access, "_now", lambda _session: expires + timedelta(seconds=1))
    with pytest.raises(practice_access.PracticeAccessError):
        complete(c)
    assert count(c, ExternalIdentity) == 0


def test_owned_schedule_opens_existing_workspace_api_and_retains_private_drafts(case, monkeypatch):
    from cosmas_os.api import app as api
    from cosmas_os.api.workspace_schemas import WorkspaceCreate

    c = case
    reserve(c)
    identity = complete(c)
    private = workspace.create_private_draft(c.session, identity.box_id, identity.principal_id,
                                             "Invented existing private draft", str(uuid4()))
    first = seed_standalone_practice(c.session, c.config, c.manifest)
    monkeypatch.setattr(api, "settings", c.config)
    catalog = api.workspace_catalog(c.session, identity)
    assert {row["appointment_id"] for row in catalog} == {str(a.id) for a in c.manifest.appointments}
    assert {row["source"] for row in catalog} == {"cosmabot_synthetic"}
    request = WorkspaceCreate(appointment_id=c.manifest.appointments[0].id, idempotency_key="standalone-open-visit")
    opened = api.create_workspace(request, c.session, identity)
    assert opened["entries"] == []
    saved = workspace.append(c.session, identity.box_id, identity.principal_id, opened["id"],
        expected=1, key="standalone-chief-draft", kind="conversation", content="Invented Chief workflow draft")
    assert seed_standalone_practice(c.session, c.config, c.manifest) == first
    assert api.create_workspace(request, c.session, identity)["entries"] == saved["workspace"]["entries"]
    assert c.session.get(EncounterWorkspace, private["id"]).appointment_id is None
    assert count(c, CoreCaptureAccount) == count(c, Ticket) == 0
    assert all(row.source_account_id is None and row.source_owner_id is None
               for row in c.session.scalars(select(PatientLink)))
    assert c.calls == []


def test_seed_receipt_and_record_tampering_fail_without_repair(case):
    c = case
    reserve(c)
    complete(c)
    seed_standalone_practice(c.session, c.config, c.manifest)
    row = c.session.get(PatientLink, str(c.manifest.patients[0].id))
    row.label = "Invented later edited label"
    c.session.commit()
    with pytest.raises(StandalonePracticeError, match="seed_conflict"):
        seed_standalone_practice(c.session, c.config, c.manifest)
    assert c.session.get(PatientLink, row.id).label == "Invented later edited label"
    receipt = c.session.scalar(select(AuditEvent).where(AuditEvent.event_type == "standalone_practice.seeded"))
    receipt.detail = {}
    c.session.commit()
    with pytest.raises(StandalonePracticeError, match="manifest_conflict"):
        seed_standalone_practice(c.session, c.config, c.manifest)


def test_revoked_owner_binding_does_not_seed_or_reassign(case):
    c = case
    reserve(c)
    complete(c)
    row = c.session.scalar(select(ExternalIdentity))
    row.active = False
    c.session.commit()
    with pytest.raises(practice_access.PracticeAccessError):
        seed_standalone_practice(c.session, c.config, c.manifest)
    assert count(c, PatientLink) == count(c, AppointmentObservation) == 0


def test_core_configuration_cannot_be_inherited(case):
    c = case
    runtime = c.config.model_copy(update={"core_capture_origin": "https://forbidden.example.invalid"})
    with pytest.raises(StandalonePracticeError):
        reserve_standalone_practice(c.session, runtime, c.manifest)
    assert count(c, BoxContext) == 0
