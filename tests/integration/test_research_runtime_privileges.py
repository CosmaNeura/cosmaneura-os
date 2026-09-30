"""Signed Research lifecycle under the actual restricted database role, offline."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from tests.integration.test_workspace_capture import capture_case  # noqa: F401

from cosmas_os.adapters.gpt41 import GPT41Connector
from cosmas_os.adapters.public_research import PublicResearch, record
from cosmas_os.api import app as api
from cosmas_os.application import database_preparation as preparation
from cosmas_os.application import provider_team as team
from cosmas_os.application import research_analysis
from cosmas_os.models import EncounterWorkspace, WorkspaceEntry
from cosmas_os.ports.research import research_digest
from cosmas_os.research_models import ResearchRun


@pytest.fixture
def runtime_research(request, monkeypatch):
    f = request.getfixturevalue("capture_case")
    admin_url = f.engine.url.render_as_string(hide_password=False)
    role = "research_runtime_test_" + uuid4().hex[:12]
    runtime_url = make_url(admin_url).set(username=role, password="invented-runtime-password-1234")
    runtime_text = runtime_url.render_as_string(hide_password=False)
    runtime_engine = create_engine(runtime_url, echo=False, hide_parameters=True)
    bot_id = str(uuid4())
    configuration = team.default_configuration()
    configuration["bots"].append({"role": "research", "instance_id": bot_id, "name": "Research",
        "enabled": True, "include_notebook": False, "include_evidence": False})
    version = team.save(f.session, f.box, f.actor, expected=0, key="invented-runtime-research-team",
                        configuration=configuration)
    f.configuration.workspace_research_enabled = True
    f.configuration.workspace_research_io_enabled = True
    f.configuration.research_sources = "clinical_trials"
    monkeypatch.setattr(api, "SessionLocal", lambda: Session(runtime_engine))
    calls = []
    command = {"contract_version": 1, "idempotency_key": "invented-runtime-research-lookup",
        "expected_revision": 1, "team_revision": version["revision"], "bot": bot_id,
        "topic": "trials", "sources": ["clinical_trials"], "query": "Invented clinical study",
        "public_query_confirmed": True}

    def lookup(_port, source, query, *, check):
        check()
        calls.append((source, query))
        # An independently connected restricted role can see the durable intent
        # before provider I/O begins. No admin-backed Session serves the route.
        with Session(runtime_engine) as session:
            assert session.scalar(text("SELECT current_user")) == role
            row = session.scalar(select(ResearchRun).where(ResearchRun.workspace_id == f.workspace["id"]))
            assert row is not None and row.state == "running"
            assert row.request_sha256 == research_digest(command)
        return [record(source, query, "a" * 64, identity="NCT12345678", title="Invented clinical study",
            url="https://clinicaltrials.gov/study/NCT12345678", excerpt="Wholly invented registry excerpt.",
            updated="2026-09-20", scope="limited",
            fields=(("Recruitment status", "RECRUITING"), ("Phase", "PHASE2"),
                    ("Interventions", "Type: BIOLOGICAL; Name: Invented cell intervention"),
                    ("Locations", "Facility: Invented Research Center; Site status: RECRUITING"),
                    ("Eligibility", "Invented study criteria; no individual eligibility determination.")))]

    monkeypatch.setattr(PublicResearch, "lookup", lookup)
    quoted_role = f.engine.dialect.identifier_preparer.quote_identifier(role)
    try:
        evidence = preparation.prepare_beta_database(admin_url, runtime_text, require_verify_full=False)
        assert evidence.status == "ready" and evidence.runtime_role_non_admin
        yield SimpleNamespace(case=f, engine=runtime_engine, role=role, quoted_role=quoted_role,
            admin_url=admin_url, runtime_url=runtime_url, runtime_text=runtime_text, calls=calls,
            command=command, headers={"Authorization": "Bearer " + f.token(), "X-Cosmas-Research-Contract": "1"},
            path=f"/workspaces/{f.workspace['id']}/research")
    finally:
        runtime_engine.dispose()
        with f.engine.begin() as connection:
            exists = connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": role})
            if exists:
                connection.execute(text(f"DROP OWNED BY {quoted_role}"))
                connection.execute(text(f"DROP ROLE {quoted_role}"))


def test_restricted_role_recovers_missing_helper_then_searches_resolves_and_saves(runtime_research):
    r, f = runtime_research, runtime_research.case
    with f.engine.begin() as connection:
        connection.execute(text(f"REVOKE EXECUTE ON FUNCTION public.finance_settings_keys(jsonb,text[]) FROM {r.quoted_role}"))
    assert not preparation._verify_runtime_role(r.runtime_text, r.runtime_url)["non_admin"]
    failed = f.client.post(r.path + "/search", headers=r.headers, json=r.command)
    assert failed.status_code == 503 and r.calls == []
    resolve = {"contract_version": 1, "idempotency_key": r.command["idempotency_key"]}
    assert f.client.post(r.path + "/resolve", headers=r.headers, json=resolve).status_code == 404
    with Session(r.engine) as session:
        assert session.scalar(select(func.count()).select_from(ResearchRun).where(
            ResearchRun.workspace_id == f.workspace["id"])) == 0

    preparation.prepare_beta_database(r.admin_url, r.runtime_text, require_verify_full=False)
    completed = f.client.post(r.path + "/search", headers=r.headers, json=r.command)
    assert completed.status_code == 200, completed.text
    result = completed.json()
    assert result["state"] == "completed" and len(result["results"]) == 1 and len(r.calls) == 1
    assert f.client.post(r.path + "/resolve", headers=r.headers, json=resolve).json() == result
    assert f.client.post(r.path + "/search", headers=r.headers, json=r.command).json() == result
    assert len(r.calls) == 1
    source_hash = result["results"][0]["sha256"]
    save = {"contract_version": 1, "idempotency_key": "invented-runtime-research-save",
        "expected_revision": 1, "source_hashes": [source_hash]}
    save_path = r.path + "/" + result["run_id"] + "/save"
    saved = f.client.post(save_path, headers=r.headers, json=save)
    assert saved.status_code == 200, saved.text
    assert saved.json()["entry_revision"] == 2
    saved_resolve = {"contract_version": 1, "idempotency_key": save["idempotency_key"]}
    assert f.client.post(save_path + "/resolve", headers=r.headers, json=saved_resolve).json() == saved.json()
    assert f.client.post(save_path, headers=r.headers, json=save).json() == saved.json()
    assert len(r.calls) == 1
    receipt = saved.json()
    with Session(r.engine) as session:
        entry = session.get(WorkspaceEntry, receipt["entry_id"])
        assert entry is not None
        saved_text = entry.content
        assert "PHASE2" not in saved_text  # Historical immutable excerpt format.
        workspace = session.get(EncounterWorkspace, f.workspace["id"])
        command = {"content": "Compare the selected trial; do not determine individual eligibility.",
            "research_analysis": {"version": 1, "consented": True, "entries": [{
                "entry_id": receipt["entry_id"], "entry_revision": receipt["entry_revision"],
                "run_id": receipt["run_id"], "save_request_sha256": receipt["request_sha256"]}]}}
        context = research_analysis.build_context(session, workspace,
            {"role": "research", "response_style": "brief"}, command)
        prepared = GPT41Connector(lambda: pytest.fail("Model credentials accessed")).prepare(context)
        source = prepared["sources"][0]
        for detail in ("RECRUITING", "PHASE2", "Invented cell intervention", "Invented Research Center",
                       "no individual eligibility determination", "2026-09-20", source_hash,
                       "Reported result scope: limited", "Wholly invented registry excerpt."):
            assert detail in source["text"]
        assert source["truncated"] is False and source["source_id"] == entry.id
        session.refresh(entry)
        assert entry.content == saved_text


def test_runtime_only_executes_exact_pure_validators_and_readiness_detects_extra_grants(runtime_research):
    r = runtime_research
    with r.engine.connect() as connection:
        permitted = set(connection.scalars(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND has_function_privilege(current_user,p.oid,'EXECUTE')")))
        assert permitted == set(preparation._runtime_validator_oids(connection) or ())
        assert len(permitted) == 7
        # sha256(bytea) is PostgreSQL's built-in pg_catalog function, not an
        # extension or another public helper needing expanded permission.
        assert connection.scalar(text("SELECT to_regprocedure('sha256(bytea)') = to_regprocedure('pg_catalog.sha256(bytea)')"))
        invented = {"probe": "invented-runtime-validation", "version": 1}
        assert connection.scalar(text("SELECT public.research_json_digest(CAST(:value AS jsonb))"),
                                 {"value": json.dumps(invented)}) == research_digest(invented)
        assert not connection.scalar(text("SELECT has_function_privilege(current_user,'public.research_run_guard()','EXECUTE')"))
    with r.case.engine.begin() as connection:
        connection.execute(text(f"GRANT EXECUTE ON FUNCTION public.research_run_guard() TO {r.quoted_role}"))
    assert not preparation._verify_runtime_role(r.runtime_text, r.runtime_url)["non_admin"]
    preparation.prepare_beta_database(r.admin_url, r.runtime_text, require_verify_full=False)
    assert preparation._verify_runtime_role(r.runtime_text, r.runtime_url)["non_admin"]


def test_preparation_rejects_non_validator_signature_without_broadening_role(runtime_research, monkeypatch):
    r = runtime_research
    monkeypatch.setattr(preparation, "_RUNTIME_VALIDATORS", (*preparation._RUNTIME_VALIDATORS, "public.research_run_guard()"))
    with pytest.raises(preparation.DatabasePreparationError, match="validators are missing or unsafe"):
        preparation.prepare_beta_database(r.admin_url, r.runtime_text, require_verify_full=False)
    with r.engine.connect() as connection:
        assert not connection.scalar(text("SELECT has_function_privilege(current_user,'public.research_run_guard()','EXECUTE')"))
        assert connection.scalar(text("SELECT has_function_privilege(current_user,'public.research_json_digest(jsonb)','EXECUTE')"))
