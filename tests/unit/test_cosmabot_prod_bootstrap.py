"""CI-visible re-export of production foundation BootstrapSafety tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "infra/beta/vm/prod/foundation/tests/test_bootstrap_local.py"

spec = importlib.util.spec_from_file_location("cosmabot_prod_foundation_bootstrap_tests", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)

# EncryptionProof needs a pinned tofu binary; keep it out of the unit suite.
BootstrapSafety = module.BootstrapSafety
