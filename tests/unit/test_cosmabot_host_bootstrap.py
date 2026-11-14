"""CI-visible re-export of CosmaBot host bootstrap refusal tests.

Collected by scripts/check-backend-local.py backend suites (python-tests-migrate).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "infra/beta/vm/host/tests/test_bootstrap_host.py"

spec = importlib.util.spec_from_file_location("cosmabot_host_bootstrap_tests", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)

NewHostRefusals = module.NewHostRefusals
ProdProfileBootstrap = module.ProdProfileBootstrap
