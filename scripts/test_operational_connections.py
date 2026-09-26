"""Focused optional connector input checks; no accounts, providers or services."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

from operational_connections import add_connections

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "startup", ROOT / "scripts/prepare-operational-startup.py"
)
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)


class OperationalConnections(unittest.TestCase):
    def setUp(self):
        self.bindings = json.loads(
            (ROOT / "docs/operational-service-bindings.example.json").read_text()
        )
        self.connections = json.loads(
            (ROOT / "docs/operational-connectors.example.json").read_text()
        )
        self.identity = {
            "apiOrigin": "https://api.example.invalid",
            "frontendOrigin": "https://identity.example.invalid",
        }
        self.base = startup.compile_inputs(self.identity, self.bindings)

    def prepare(self):
        return add_connections(
            self.base, self.bindings, self.identity, self.connections
        )

    def test_complete_maps_native_callbacks_and_manifest_references(self):
        result = self.prepare()
        selected = result["os.services.tfvars.json"]
        self.assertEqual(len(selected["workspace_features"]), 36)
        self.assertTrue(
            selected["workspace_features"]["WORKSPACE_GOOGLE_CONNECTION_ENABLED"]
        )
        self.assertTrue(
            selected["workspace_features"]["WORKSPACE_MICROSOFT_CONNECTION_ENABLED"]
        )
        self.assertEqual(len(selected["workspace_secret_references"]), 8)
        self.assertFalse(selected["workspace_features"]["VENDOR_IO_ENABLED"])
        self.assertFalse(
            selected["workspace_features"]["WORKSPACE_ATHENA_CONNECTION_ENABLED"]
        )
        self.assertTrue(
            result["os.athena-readonly.tfvars.json"]["workspace_features"][
                "WORKSPACE_GOOGLE_CONNECTION_ENABLED"
            ]
        )
        self.assertEqual(
            result["native-connection-arguments.json"][
                "google_connection_callback_uri"
            ],
            "https://api.example.invalid/connections/google/callback",
        )
        self.assertFalse(
            self.base["os.services.tfvars.json"]["workspace_features"][
                "WORKSPACE_GOOGLE_CONNECTION_ENABLED"
            ]
        )

    def test_connections_are_independently_optional(self):
        self.connections.update(google=None, managed_services=None)
        result = self.prepare()
        self.assertNotIn(
            "workspace_managed_manifest", result["os.services.tfvars.json"]
        )
        self.assertEqual(
            result["service-bindings.json"]["optional_connections"], ["microsoft"]
        )
        self.assertNotIn(
            "google_connection_client_id", result["native-connection-arguments.json"]
        )

    def test_shared_client_custody_or_unsupported_scopes_are_rejected(self):
        cases = [
            lambda c: c["google"].update(
                client_id=self.bindings["scheduling"]["google_staff_client_id"]
            ),
            lambda c: c["microsoft"].update(
                encryption_key=c["google"]["encryption_key"]
            ),
            lambda c: c["google"].update(scopes=["gmail.modify"]),
            lambda c: c["microsoft"].update(tenant_id="common"),
            lambda c: c["google"].update(client_secret="plaintext"),
            lambda c: c["managed_services"]["enabled"].update(vendor_io="true"),
            lambda c: c["managed_services"]["manifest"].update(sha256="0" * 64),
        ]
        original = copy.deepcopy(self.connections)
        for mutation in cases:
            self.connections = copy.deepcopy(original)
            mutation(self.connections)
            with self.assertRaises(ValueError):
                self.prepare()


if __name__ == "__main__":
    unittest.main()
