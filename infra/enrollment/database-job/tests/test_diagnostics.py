"""Operational failure receipts locate a constraint without disclosing driver data."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

spec = importlib.util.spec_from_file_location("enrollment_database_diagnostics", Path(__file__).resolve().parents[1] / "database.py")
database = importlib.util.module_from_spec(spec)
spec.loader.exec_module(database)


@pytest.mark.parametrize("error,expected_class,expected_code", [
    (ValueError("runtime may not access managed service databases"), "ValueError", "runtime_managed_database_access"),
    (ValueError("postgresql://invented-user:private-sentinel@example.invalid/invented"), "ValueError", "operation_failed"),
    (OperationalError("SELECT private-sentinel", {"password": "private-sentinel"}, RuntimeError("private-sentinel")), "OperationalError", "operation_failed"),
])
def test_failed_runtime_check_reports_only_bounded_constraint_and_disposes_engines(monkeypatch, capsys, error, expected_class, expected_code):
    disposed = []
    monkeypatch.setattr(database.sys, "argv", ["database.py", "check"])
    monkeypatch.setattr(database, "engines_from_environment", lambda operation: {"runtime": SimpleNamespace(dispose=lambda: disposed.append("runtime"))})

    def fail_check(engines):
        raise error

    monkeypatch.setattr(database, "check", fail_check)
    assert database.main() == 1
    output = capsys.readouterr()
    assert output.out == "" and "private-sentinel" not in output.err
    assert json.loads(output.err) == {"error": "enrollment_database_preparation_failed", "class": expected_class,
        "operation": "check", "stage": "check", "code": expected_code}
    assert disposed == ["runtime"]


def test_provider_mismatch_projection_is_fixed_bounded_and_never_discloses_raw_names():
    rows = [{"database": "azure_sys", "owner": "private-sentinel", "grantee_oid": 23,
             "grantee": "private-sentinel", "grantor": "private-sentinel", "privilege": "private-sentinel",
             "grantable": True} for _ in range(33)]
    rows.append({"database": "private-sentinel", "owner": "private-sentinel"})
    receipt = database.failure_receipt("check", "check", database.ProviderBaselineMismatch(rows))
    assert receipt["class"] == "ValueError" and receipt["code"] == "managed_database_ownership_acl"
    assert "private-sentinel" not in json.dumps(receipt)
    projection = receipt["provider_baseline_projection"]
    assert len(projection) == 2 and {row["database"] for row in projection} == {"azure_sys", "azure_maintenance"}
    managed = next(row for row in projection if row["database"] == "azure_sys")
    assert managed == {"database": "azure_sys", "present": True, "owner": "unknown",
        "acl": [{"grantee": "unknown", "grantor": "unknown", "privilege": "unknown", "grantable": True,
                 "grantable_known": True} for _ in range(8)], "acl_truncated": True}
