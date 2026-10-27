"""Generated public host inputs must validate against the actual additive runtime."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import subprocess
import unittest

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
    def rendered(self, policy: str) -> dict:
        program = """
import {readFile} from 'node:fs/promises';
import {render} from './infra/standalone/render.mjs';
const input=JSON.parse(await readFile('./infra/standalone/invented-host-input.json','utf8'));
if(process.argv[1]==='shared_staging'){
  input.identity_policy='shared_staging';input.identity.profile='operational-staging-v1';
  input.identity.audience='';input.identity.frontendOrigin='https://invented-own-practice.clerk.accounts.dev';
  input.identity.publishableKey='pk_test_'+Buffer.from('invented-own-practice.clerk.accounts.dev$').toString('base64');
}
const files=render(input);console.log(JSON.stringify({environment:files['api-public.json'],contract:files['host-preparation.json']}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", program, policy],
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


if __name__ == "__main__":
    unittest.main()
