"""Alembic loads shipped migrations without installing them as a Python package."""

import os
import subprocess
import sys
from pathlib import Path


def test_clinical_note_upgrade_loads_prior_guard_outside_the_repository(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = """
import importlib.util
import sys
from pathlib import Path
from alembic import command
from alembic.config import Config

root = Path(sys.argv[1])
assert importlib.util.find_spec('migrations') is None
config = Config(str(root / 'alembic.ini'))
config.set_main_option('script_location', str(root / 'migrations'))
config.set_main_option('prepend_sys_path', str(root / 'src'))
config.attributes['configure_logger'] = False
command.upgrade(config, 'e3a90d77b812:head', sql=True)
"""
    result = subprocess.run([sys.executable, "-c", script, str(root)], cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(root / "src"), "PYTHONNOUSERSITE": "1",
             "COSMAS_ENV": "synth_os", "DATA_MODE": "synthetic",
             "DATABASE_URL": "postgresql+psycopg://invented:invented@127.0.0.1:1/invented"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "CREATE FUNCTION public.clinical_note_source_valid" in result.stdout
    assert "CREATE CONSTRAINT TRIGGER clinical_note_source_guard" in result.stdout
    assert "version_num='j79f1d5a2340'" in result.stdout
