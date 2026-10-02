"""Actual signed personal setup writes under the prepared PostgreSQL runtime role."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration import test_scheduling_patient_setup as shared
from tests.integration.test_workspace_auth import signed_workspace

from cosmas_os.api import app as api
from cosmas_os.application import database_preparation as preparation
from cosmas_os.application import scheduling_patient_setup as setup
from cosmas_os.application import services as services
from cosmas_os.application import workspace as ws
from cosmas_os.application.capture_deadline import own_capture_session
from cosmas_os.models import Operation, SchedulingPatientAccount
from cosmas_os.scheduling_patient_models import (
    SchedulingPatientMappingReview,
    SchedulingPatientSetupRequest,
    SchedulingPatientSetupSnapshot,
)

DEFINERS = (
    "public.guard_patient_setup_request()",
    "public.guard_patient_setup_snapshot()",
    "public.guard_patient_setup_settlement()",
    "public.guard_personal_patient_mapping()",
)
INVOKERS = (
    "public.patient_setup_canonical(jsonb,integer)",
    "public.patient_setup_digest(text,jsonb)",
    "public.patient_setup_identity_valid(jsonb)",
    "public.patient_setup_payload_valid(text,jsonb)",
    "public.patient_setup_source_context(uuid)",
    "public.patient_setup_request_current(uuid,boolean)",
    "public.patient_setup_snapshot_valid(uuid)",
    "public.patient_setup_mapping_hash(public.scheduling_patient_mapping_reviews)",
    "public.immutable_patient_setup()",
)


@pytest.fixture
def restricted(engine, monkeypatch):
    """Commit an unmapped invented visit; every setup command uses role credentials.

    The ordinary fixture uses an outer rollback transaction that an independent
    connection cannot see. This owned Session makes only this case visible;
    nothing is copied from a clinical account or live receiver.
    """
    role = "patient_runtime_test_" + uuid4().hex[:12]
    runtime_url = engine.url.set(username=role, password="invented-runtime-password-1234")
    runtime_engine = create_engine(runtime_url, echo=False, hide_parameters=True)
    quoted_role = engine.dialect.identifier_preparer.quote_identifier(role)
    signed_generator = patient_generator = None
    f = None
    with Session(engine) as owned, monkeypatch.context() as patch:
        try:
            seed = services.provision_box(services.Container(owned), "Invented restricted patient setup")
            # This fixture commits across cases; the shared signed fixture uses
            # the seeded issuer for both its stored identity and signed token.
            seed["clerk_issuer"] = "https://clerk-" + uuid4().hex + ".example.invalid"
            signed_generator = cast(Any, signed_workspace).__wrapped__(owned, seed, patch, SimpleNamespace())
            signed = next(signed_generator)
            patient_generator = cast(Any, shared.http_case).__wrapped__(signed, owned, patch)
            f = next(patient_generator)
            owned.commit()
            assert owned.scalar(select(func.count()).select_from(SchedulingPatientAccount).where(
                SchedulingPatientAccount.box_id == f.box)) == 0
            owned.commit()
            evidence = preparation.prepare_beta_database(engine.url.render_as_string(hide_password=False),
                runtime_url.render_as_string(hide_password=False), require_verify_full=False)
            assert evidence.status == "ready" and evidence.runtime_role_non_admin
            assert evidence.runtime_ddl_denied and evidence.audit_update_denied and evidence.audit_delete_denied
            with engine.connect() as connection:
                admin_role = connection.scalar(text("SELECT current_user"))

            def request_session():
                with Session(runtime_engine) as current:
                    yield own_capture_session(current)

            patch.setitem(api.app.dependency_overrides, api.get_session, request_session)
            reservations = []
            def observed_before_io():
                assert f is not None and not f.s.in_transaction()
                with Session(runtime_engine) as other:
                    assert other.scalar(text("SELECT current_user")) == role
                    request = other.scalar(select(SchedulingPatientSetupRequest).where(
                        SchedulingPatientSetupRequest.workspace_id == f.wid).order_by(
                            SchedulingPatientSetupRequest.ordinal.desc()).limit(1))
                    assert request is not None
                    assert other.scalar(select(SchedulingPatientSetupSnapshot.id).where(
                        SchedulingPatientSetupSnapshot.request_id == request.id)) is None
                    reservations.append((request.kind, request.id))
            f.port.after = observed_before_io
            yield SimpleNamespace(f=f, engine=runtime_engine, admin_engine=engine, role=role,
                admin_role=admin_role, reservations=reservations)
        finally:
            # No background job or provider write is installed by this fixture.
            # Keep the binding context until all owned HTTP clients have closed.
            if patient_generator is not None:
                patient_generator.close()
            if signed_generator is not None:
                signed_generator.close()
            runtime_engine.dispose()
            with engine.begin() as connection:
                if connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": role}):
                    connection.execute(text(f"DROP OWNED BY {quoted_role}"))
                    connection.execute(text(f"DROP ROLE {quoted_role}"))


def assert_runtime_contract(r):
    with r.engine.connect() as connection:
        assert connection.scalar(text("SELECT current_user")) == r.role != r.admin_role
        attributes = connection.execute(text("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
            "FROM pg_roles WHERE rolname=current_user")).one()
        assert not any(attributes)
        assert connection.scalar(text("SELECT NOT EXISTS(SELECT 1 FROM pg_auth_members m "
            "JOIN pg_roles member ON member.oid=m.member WHERE member.rolname=current_user)")) is True
        permitted = set(connection.scalars(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND has_function_privilege(current_user,p.oid,'EXECUTE')")))
        assert permitted == set(preparation._runtime_validator_oids(connection) or ()) and len(permitted) == 7
        for signature in DEFINERS + INVOKERS:
            row = connection.execute(text("""SELECT p.prosecdef,p.proconfig,pg_get_userbyid(p.proowner),
                has_function_privilege(current_user,p.oid,'EXECUTE'),
                NOT EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
                    WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
                FROM pg_proc p WHERE p.oid=to_regprocedure(:name)"""), {"name": signature}).one()
            assert row[0] is (signature in DEFINERS)
            assert "search_path=pg_catalog" in (row[1] or [])
            assert row[2] == r.admin_role != r.role and row[3] is False and row[4] is True
        for table in ("scheduling_patient_setup_requests", "scheduling_patient_setup_snapshots", "scheduling_patient_mapping_reviews"):
            assert connection.scalar(text("SELECT has_table_privilege(current_user,:table,'SELECT') "
                "AND has_table_privilege(current_user,:table,'INSERT') AND has_table_privilege(current_user,:table,'UPDATE') "
                "AND has_table_privilege(current_user,:table,'DELETE') "
                "AND NOT has_table_privilege(current_user,:table,'TRIGGER')"), {"table": "public." + table}) is True
    for expression in ("public.patient_setup_request_current(gen_random_uuid(),false)",
        "public.patient_setup_payload_valid('preview','{}'::jsonb)", "public.guard_patient_setup_request()"):
        with r.engine.connect() as connection, pytest.raises(DBAPIError) as refusal:
            connection.execute(text("SELECT " + expression))
        assert getattr(refusal.value.orig, "sqlstate", None) == "42501"
    with r.engine.connect() as connection, pytest.raises(DBAPIError) as refusal:
        connection.execute(text("CREATE TABLE public.patient_runtime_forbidden_probe(id integer)"))
    assert getattr(refusal.value.orig, "sqlstate", None) == "42501"


def preview(r):
    f = r.f
    body = {"action": "preview", "expected_revision": f.before["revision"], "idempotency_key": str(uuid4()),
        "search": {"kind": "search", "query": "Invented Jordan", "birth_date": None}}
    response = f.client.post(f.path, headers=f.headers, json=body)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return body, response.json()


def confirmed(r):
    _, observed = preview(r)
    body = shared.confirmation(r.f, observed)
    body = {"action": "confirm", "idempotency_key": body.pop("key"), **body}
    response = r.f.client.post(r.f.path, headers=r.f.headers, json=body)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return body, response.json()


def test_signed_initially_unmapped_runtime_preview_confirm_inspect_and_masked_replay(restricted):
    r, f = restricted, restricted.f
    assert_runtime_contract(r)
    command, receipt = confirmed(r)
    assert receipt["status"] == "saved" and not receipt["source_withheld"] and receipt["mapping"]
    assert f.port.calls == ["preview", "verify"] and [kind for kind, _ in r.reservations] == ["preview", "confirm"]
    reopened = f.client.post(f.path, headers=f.headers, json={"action": "inspect", "request_id": receipt["request_id"]})
    assert reopened.status_code == 200 and reopened.json() == receipt
    assert f.client.post(f.path, headers=f.headers, json=command).json() == receipt
    with Session(r.engine) as s:
        assert s.scalar(text("SELECT current_user")) == r.role
        assert s.scalar(select(func.count()).select_from(SchedulingPatientMappingReview).where(
            SchedulingPatientMappingReview.box_id == f.box)) == 1
        assert s.scalar(select(func.count()).select_from(SchedulingPatientAccount).where(
            SchedulingPatientAccount.box_id == f.box)) == 1
        mapping = s.get(SchedulingPatientAccount, receipt["mapping"]["mapping_id"])
        assert mapping is not None and mapping.reviewed_by == f.actor
        current = ws.read(s, f.box, f.actor, f.wid)
        assert current["note"] == f.before["note"] and current["entries"] == f.before["entries"]
        assert s.scalar(select(func.count()).select_from(Operation).where(Operation.box_id == f.box)) == 0
    f.grant = "c" * 64
    masked = f.client.post(f.path, headers=f.headers, json=command)
    assert masked.status_code == 200 and masked.json()["source_withheld"] and masked.json()["mapping"] is None
    assert masked.json()["request_id"] == receipt["request_id"] and masked.json()["source_sha256"] == receipt["source_sha256"]
    assert masked.json()["request_sha256"] == receipt["request_sha256"] and "Invented Jordan" not in masked.text
    assert f.port.calls == ["preview", "verify"]
    assert_runtime_contract(r)


@pytest.mark.parametrize("fault", ["cross_owner", "wrong_hash", "string_revision"])
def test_forged_runtime_custody_reservation_cannot_commit(restricted, fault):
    r, f = restricted, restricted.f
    _, observed = preview(r)
    with Session(r.engine) as s:
        original = s.get(SchedulingPatientSetupRequest, observed["request_id"])
        assert original is not None
        values = {column.name: deepcopy(getattr(original, column.name)) for column in original.__table__.columns}
        values["id"], values["idempotency_key"], values["request_nonce"] = str(uuid4()), str(uuid4()), str(uuid4())
        values["ordinal"] += 1
        values["command"]["idempotency_key"] = values["idempotency_key"]
        if fault == "cross_owner":
            values["owner_id"] = str(uuid4())
        elif fault == "string_revision":
            values["command"]["expected_revision"] = str(values["expected_revision"])
        values["request_sha256"] = "f" * 64 if fault == "wrong_hash" else setup.request_hash(f.wid, values["command"])
        s.add(SchedulingPatientSetupRequest(**values))
        with pytest.raises(DBAPIError) as failure:
            s.commit()
        assert getattr(failure.value.orig, "sqlstate", None) == "23514"
        s.rollback()
    assert f.port.calls == ["preview"]


def test_runtime_forged_preview_review_and_unreviewed_mapping_are_refused(restricted):
    r, f = restricted, restricted.f
    _, observed = preview(r)
    with Session(r.engine) as s:
        snapshot = s.scalar(select(SchedulingPatientSetupSnapshot).where(
            SchedulingPatientSetupSnapshot.request_id == observed["request_id"]))
        assert snapshot is not None
        review_id, mapping_id = str(uuid4()), str(uuid4())
        account = s.get(SchedulingPatientSetupRequest, observed["request_id"])
        assert account is not None
        mapping = SchedulingPatientAccount(id=mapping_id, box_id=f.box, patient_link_id=f.patient,
            practice_id=account.selection["practice_id"], patient_id=str(uuid4()), reviewed_by=f.actor,
            evidence_ref="scheduling-patient:v1:" + review_id, reviewed_at=datetime.now(UTC))
        s.add(mapping)
        s.flush()
        with pytest.raises(DBAPIError) as failure:
            s.commit()
        assert getattr(failure.value.orig, "sqlstate", None) == "23514"
        s.rollback()
        s.add(mapping)
        s.flush()
        s.add(SchedulingPatientMappingReview(id=review_id, workspace_id=f.wid, box_id=f.box, owner_id=f.actor,
            patient_link_id=f.patient, request_id=observed["request_id"], snapshot_id=snapshot.id, mapping_id=mapping_id,
            reviewed_same_patient=True, reviewed_exact_identity=True, mapping_sha256="f" * 64))
        with pytest.raises(DBAPIError) as failure:
            s.commit()
        assert getattr(failure.value.orig, "sqlstate", None) == "23514"
        s.rollback()
        assert s.scalar(select(func.count()).select_from(SchedulingPatientMappingReview).where(
            SchedulingPatientMappingReview.box_id == f.box)) == 0
    assert f.port.calls == ["preview"]
