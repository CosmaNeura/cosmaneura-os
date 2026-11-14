"""Local refusals for secrets_transport; CI proof lives in tests/unit/test_secrets_transport.py."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "secrets_transport_host", MODULE / "secrets_transport.py"
)
transport = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = transport
spec.loader.exec_module(transport)


class SecretsTransportRefusals(unittest.TestCase):
    def test_run_command_forbidden(self):
        with self.assertRaises(transport.Refused):
            transport.refuse_run_command_transport()

    def test_staging_vault_refused(self):
        with self.assertRaises(transport.Refused):
            transport.validate_prod_coordinates(
                profile=transport.PROFILE,
                resource_group=transport.RESOURCE_GROUP,
                vault_name="kv-cbot-stg-lab01",
            )

    def test_cosmascode_tag_refused(self):
        with self.assertRaises(transport.Refused):
            transport.validate_llm_source_account(
                {
                    transport.SOURCE_ACCOUNT_TAG: (
                        "https://cosmascode.services.ai.azure.com/openai/v1"
                    )
                }
            )


if __name__ == "__main__":
    unittest.main()
