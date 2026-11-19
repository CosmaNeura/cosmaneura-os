"""Alembic graph must have exactly one head equal to EXPECTED_SCHEMA_REVISION."""

from pathlib import Path

from alembic.script import ScriptDirectory

from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

ROOT = Path(__file__).resolve().parents[2]


def test_alembic_has_exactly_one_expected_head():
    heads = ScriptDirectory(str(ROOT / "migrations")).get_heads()
    assert len(heads) == 1
    assert heads == [EXPECTED_SCHEMA_REVISION]
