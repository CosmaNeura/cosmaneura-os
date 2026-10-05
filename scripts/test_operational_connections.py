"""Focused optional connector input checks; no accounts, providers or services."""

import ast
import copy
import importlib.util
import json
import unittest
from pathlib import Path

from operational_connections import (
    GOOGLE_CALENDAR_SCOPE,
    GOOGLE_FULL_MESSAGE_SCOPE,
    GOOGLE_SCOPES,
    GOOGLE_SOURCE_FLAGS,
    add_connections,
)

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
        self.assertEqual(set(selected["workspace_features"]), set(self.base["os.services.tfvars.json"]["workspace_features"]))
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

    def test_legacy_input_keeps_source_features_dark_and_matches_normal_consent(self):
        result = self.prepare()
        google = result["provider-registration.json"]["accounts"]["google"]
        self.assertEqual(google["scopes"], GOOGLE_SCOPES.split() + [GOOGLE_CALENDAR_SCOPE])
        self.assertEqual(google["accepted_legacy_scopes"], GOOGLE_SCOPES.split())
        self.assertEqual(google["source_features"], {"full_message": False, "calendar": False})
        self.assertNotIn("full_message_consent_scopes", google)
        for flag in GOOGLE_SOURCE_FLAGS.values():
            self.assertFalse(result["os.services.tfvars.json"]["workspace_features"][flag])
            self.assertFalse(result["os.athena-readonly.tfvars.json"]["workspace_features"][flag])
        self.assertFalse(result["provider-registration.json"]["account_consent_performed"])

    def test_registration_scopes_match_existing_adapter_constants(self):
        tree = ast.parse((ROOT / "src/cosmas_os/adapters/google_connection.py").read_text())
        scopes = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                  and node.targets[0].id in {"SCOPES", "CALENDAR_SCOPE", "FULL_MAIL_SCOPE"}}
        self.assertEqual(scopes, {"SCOPES": GOOGLE_SCOPES, "CALENDAR_SCOPE": GOOGLE_CALENDAR_SCOPE,
                                 "FULL_MAIL_SCOPE": GOOGLE_FULL_MESSAGE_SCOPE})

    def test_google_source_features_are_explicit_independent_and_preserve_complete_maps(self):
        for full_message, calendar in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(full_message=full_message, calendar=calendar):
                selected = {"full_message": full_message, "calendar": calendar}
                self.connections["google"]["enabled"] = selected
                result = self.prepare()
                service = result["os.services.tfvars.json"]["workspace_features"]
                athena = result["os.athena-readonly.tfvars.json"]["workspace_features"]
                google = result["provider-registration.json"]["accounts"]["google"]
                self.assertEqual(len(service), len(self.base["os.services.tfvars.json"]["workspace_features"]))
                for name, flag in GOOGLE_SOURCE_FLAGS.items():
                    self.assertIs(service[flag], selected[name])
                    self.assertIs(athena[flag], selected[name])
                self.assertEqual(google["source_features"], selected)
                self.assertNotIn(GOOGLE_FULL_MESSAGE_SCOPE, google["scopes"])
                if full_message:
                    self.assertEqual(google["full_message_consent_scopes"], google["scopes"] + [GOOGLE_FULL_MESSAGE_SCOPE])
                else:
                    self.assertNotIn("full_message_consent_scopes", google)
                self.assertFalse(self.base["os.services.tfvars.json"]["workspace_features"]["WORKSPACE_GOOGLE_MESSAGE_ENABLED"])
                self.assertFalse(result["provider-registration.json"]["provider_registration_performed"])
                self.assertFalse(result["provider-registration.json"]["account_consent_performed"])

    def test_google_source_selections_reject_partial_null_coerced_and_unknown_inputs(self):
        for enabled in (None, [], {}, {"full_message": True}, {"full_message": True, "calendar": 1},
                        {"full_message": "true", "calendar": False}, {"full_message": False, "calendar": None},
                        {"full_message": False, "calendar": False, "send": False}):
            with self.subTest(enabled=enabled):
                self.connections["google"]["enabled"] = enabled
                with self.assertRaises(ValueError):
                    self.prepare()

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
