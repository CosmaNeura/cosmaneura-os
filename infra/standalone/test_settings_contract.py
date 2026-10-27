"""Generated public host inputs must validate against the actual additive runtime."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import unittest
from pathlib import Path

from cosmas_os.config import Settings
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION

ROOT = Path(__file__).resolve().parents[2]


class ExplicitSettings(Settings):
    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return (init_settings,)


class HostSettingsContract(unittest.TestCase):
    def rendered(self, policy: str, features: bool = False) -> dict:
        program = """
import {readFile} from 'node:fs/promises';
import {render} from './infra/standalone/render.mjs';
const input=JSON.parse(await readFile('./infra/standalone/invented-host-input.json','utf8'));
if(process.argv[1]==='shared_staging'){
  input.identity_policy='shared_staging';input.identity.profile='operational-staging-v1';
  input.identity.audience='';input.identity.frontendOrigin='https://invented-own-practice.clerk.accounts.dev';
  input.identity.publishableKey='pk_test_'+Buffer.from('invented-own-practice.clerk.accounts.dev$').toString('base64');
}
if(process.argv[2]==='features'){
  input.resource_scope='owned-cosmabot-vm-instance';input.web_origin='https://staging.cosmas.ai';input.api_origin='https://api.staging.cosmas.ai';
  input.identity.apiOrigin=input.api_origin;input.tls.hostnames=['staging.cosmas.ai','api.staging.cosmas.ai'];
  input.beta_features={model:{origin:'https://invented-owned-chief.openai.azure.com',endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'},
    google:{client_id:'invented-client.apps.googleusercontent.com',callback_uri:input.api_origin+'/connections/google/callback',return_origin:input.web_origin}};
}
const files=render(input);console.log(JSON.stringify({environment:files['api-public.json'],contract:files['host-preparation.json']}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", program, policy, "features" if features else "base"],
            cwd=ROOT,
            env={"PATH": os.environ["PATH"]},
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_both_explicit_generated_identity_policies_match_the_real_backend_contract(self):
        for policy in ("audience", "shared_staging"):
            with self.subTest(policy=policy):
                rendered = self.rendered(policy)
                public = rendered["environment"]
                contract = rendered["contract"]
                self.assertEqual(set(public) - {key.upper() for key in Settings.model_fields}, set())
                booleans = {key.upper() for key, field in Settings.model_fields.items() if field.annotation is bool}
                self.assertEqual(booleans - set(public), set())
                self.assertEqual(contract["database"]["schema_revision"], EXPECTED_SCHEMA_REVISION)
                # Invented process-only values; no file, account or database is opened.
                database = contract["database"]
                password = secrets.token_urlsafe(32)
                private = {
                    "database_url": f"postgresql+psycopg://{database['role']}:{password}@127.0.0.1:{database['port']}/{database['name']}",
                    "human_deploy_evidence_ref": "invented preparation fixture, not deployment approval",
                }
                settings = ExplicitSettings(**{key.lower(): value for key, value in public.items()}, **private)
                settings.validate_runtime_configuration()
                self.assertTrue(settings.workspace_available)
                self.assertEqual(settings.clerk_session_policy, policy)
                self.assertEqual(settings.clerk_audience, contract["clerk_session_proof"]["audience"])
                if policy == "audience":
                    self.assertEqual(settings.clerk_audience, "invented-cosmabot-application-api")
                else:
                    self.assertEqual(settings.clerk_audience, "")
                self.assertFalse(settings.workspace_core_connection_available)
                self.assertFalse(settings.workspace_capture_available)

    def test_owned_vm_feature_public_inputs_match_real_settings_with_only_declared_secrets(self):
        import base64

        for policy in ("audience", "shared_staging"):
            with self.subTest(policy=policy):
                output = self.rendered(policy, features=True)
                public, contract = output["environment"], output["contract"]
                database = contract["database"]
                private = {
                    "database_url": f"postgresql+psycopg://{database['role']}:invented-password@127.0.0.1:{database['port']}/{database['name']}",
                    "human_deploy_evidence_ref": "invented feature preparation only",
                    "workspace_llm_api_key": "invented-model-key",
                    "google_connection_client_secret": "invented-google-secret",
                    "google_connection_encryption_key": base64.urlsafe_b64encode(b"x" * 32).decode(),
                }
                self.assertEqual({name.upper() for name in private}, set(contract["private_environment"]["exact_names"]))
                self.assertFalse(set(public).intersection(name.upper() for name in private))
                settings = ExplicitSettings(**{key.lower(): value for key, value in public.items()}, **private)
                settings.validate_runtime_configuration()
                self.assertTrue(settings.workspace_llm_available)
                self.assertTrue(settings.workspace_google_message_available)
                self.assertTrue(settings.workspace_google_calendar_available)
                self.assertFalse(settings.workspace_core_connection_available)
                self.assertFalse(settings.workspace_agent_tools_enabled)
                self.assertFalse(settings.workspace_routines_enabled)


if __name__ == "__main__":
    unittest.main()
