"""CI collection wrapper for infra/standalone/package/test_entrypoint.py.

Source of truth stays under infra/standalone/package/. This module re-exports
every pytest-collected name so python-tests-migrate (backend-2) runs the suite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "standalone"
    / "package"
    / "test_entrypoint.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "tests.unit._standalone_package_entrypoint_source",
    _PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

# Re-bind fixtures, helpers, and test_* callables into this module so pytest
# collects them as tests/unit/test_standalone_package_entrypoint.py::...
for _name, _value in vars(_MODULE).items():
    if _name.startswith("test_") or _name in {
        "mounted",
        "real_profile",
        "feature_inputs",
        "entrypoint",
        "standalone",
        "offline",
        "pytest",
        "google_values",
        "model_values",
        "microsoft_values",
    }:
        globals()[_name] = _value

assert any(name.startswith("test_") for name in globals()), (
    "standalone package entrypoint tests must be re-exported for CI collection"
)
