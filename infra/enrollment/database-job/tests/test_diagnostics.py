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
