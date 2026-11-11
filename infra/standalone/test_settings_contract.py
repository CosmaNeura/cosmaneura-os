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
    def rendered(
        self,
        policy: str,
        features: bool = False,
        host: str = "staging",
        capture_tools: bool = False,
    ) -> dict:
        program = """
import {readFile} from 'node:fs/promises';
import {render} from './infra/standalone/render.mjs';
const input=JSON.parse(await readFile('./infra/standalone/invented-host-input.json','utf8'));
if(process.argv[1]==='shared_staging'){
  input.identity_policy='shared_staging';input.identity.profile='operational-staging-v1';
  input.identity.audience='';input.identity.frontendOrigin='https://invented-own-practice.clerk.accounts.dev';
  input.identity.publishableKey='pk_test_'+Buffer.from('invented-own-practice.clerk.accounts.dev$').toString('base64');
}
const webHost=process.argv[3]==='beta'?'beta.cosmas.ai':'staging.cosmas.ai';
if(process.argv[2]==='features'||process.argv[2]==='capture_tools'){
  input.resource_scope='owned-cosmabot-vm-instance';input.web_origin='https://'+webHost;input.api_origin='https://api.'+webHost;
  input.identity.apiOrigin=input.api_origin;input.tls.hostnames=[webHost,'api.'+webHost];
  input.beta_features={model:{origin:'https://invented-owned-chief.openai.azure.com',endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'},
    google:{client_id:'invented-client.apps.googleusercontent.com',callback_uri:input.api_origin+'/connections/google/callback',return_origin:input.web_origin}};
}
if(process.argv[2]==='capture_tools'){
  input.syntheticBetaCaptureAndTools=true;
  input.core_capture_origin='https://staging-app.cosmaneura.com';
  input.core_web_origin='https://staging-app.cosmaneura.com';
  input.core_capture_scope='api://invented-core-audience/.default';
  input.core_capture_managed_identity_client_id='00000000-0000-4000-8000-0000000000aa';
}
const files=render(input);console.log(JSON.stringify({environment:files['api-public.json'],contract:files['host-preparation.json']}));
"""
        mode = "capture_tools" if capture_tools else ("features" if features else "base")
        result = subprocess.run(
            ["node", "--input-type=module", "-e", program, policy, mode, host],
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

    def test_beta_host_stays_standalone_synthetic(self):
        import base64

        output = self.rendered("audience", features=True, host="beta")
        public, contract = output["environment"], output["contract"]
        self.assertEqual(public["COSMAS_ENV"], "standalone_clerk_synthetic")
        self.assertEqual(public["DATA_MODE"], "synthetic")
        self.assertTrue(contract["synthetic_only"])
        self.assertFalse(contract["deployment_authorized"])
        self.assertIn("https://beta.cosmas.ai", public["CORS_ALLOWED_ORIGINS"])
        database = contract["database"]
        private = {
            "database_url": f"postgresql+psycopg://{database['role']}:invented-password@127.0.0.1:{database['port']}/{database['name']}",
            "human_deploy_evidence_ref": "invented feature preparation only",
            "workspace_llm_api_key": "invented-model-key",
            "google_connection_client_secret": "invented-google-secret",
            "google_connection_encryption_key": base64.urlsafe_b64encode(b"x" * 32).decode(),
        }
        settings = ExplicitSettings(**{key.lower(): value for key, value in public.items()}, **private)
        settings.validate_runtime_configuration()
        switched = {key.lower(): value for key, value in public.items()}
        switched["data_mode"] = "authorized_beta"
        refused = ExplicitSettings(**switched, **private)
        with self.assertRaises(RuntimeError):
            refused.validate_runtime_configuration()

    def test_synthetic_beta_capture_tools_opt_in_matches_runtime_and_keeps_real_patient_off(self):
        import base64

        from cosmas_os.ports.agent_connectors import CONNECTOR_TOOL_NAMES
        from cosmas_os.ports.agent_delivery_tools import DELIVERY_TOOL_NAMES
        from cosmas_os.ports.agent_tools import TOOL_NAMES

        output = self.rendered("audience", capture_tools=True, host="staging")
        public, contract = output["environment"], output["contract"]
        self.assertEqual(public["WORKSPACE_AGENT_TOOLS_ENABLED"], "true")
        self.assertEqual(public["WORKSPACE_CAPTURE_BACKEND"], "core")
        self.assertEqual(public["WORKSPACE_CAPTURE_NOTES_ENABLED"], "true")
        self.assertEqual(public["WORKSPACE_CAPTURE_PROXY_ENABLED"], "true")
        self.assertEqual(public["WORKSPACE_CAPTURE_PROXY_ORIGIN"], "https://api.staging.cosmas.ai")
        self.assertEqual(public["CORE_CAPTURE_ORIGIN"], "https://staging-app.cosmaneura.com")
        self.assertEqual(public["CORE_WEB_ORIGIN"], "https://staging-app.cosmaneura.com")
        self.assertNotIn("REAL_PATIENT_RECORDING_ENABLED", public)
        self.assertFalse(contract["optional_runtime_features"]["real_patient_recording_process_switch"])
        self.assertTrue(contract["optional_runtime_features"]["capture_and_agent_tools"])
        self.assertEqual(
            contract["optional_runtime_features"]["capture_content"],
            "live microphone audio on a synthetic-only host; never relabelled as invented",
        )
        self.assertEqual(contract["platform_connections"][0]["kind"], "core_staging_capture")
        # Sibling platform paths stay dark with capture/tools opted in.
        for flag in (
            "WORKSPACE_CORE_CONNECTION_ENABLED",
            "WORKSPACE_CORE_RECORD_ENABLED",
            "WORKSPACE_SESSION_PREP_ENABLED",
            "WORKSPACE_ATHENA_CONNECTION_ENABLED",
            "WORKSPACE_PREP_ENABLED",
            "WORKSPACE_PREP_WORK_ENABLED",
            "WORKSPACE_ROUTINES_ENABLED",
            "WORKSPACE_CAPTURE_CORRECTIONS_ENABLED",
            "WORKSPACE_CAPTURE_RECOVERY_ENABLED",
            "WORKSPACE_CAPTURE_SOURCE_ENABLED",
            "WORKSPACE_CAPTURE_LONG_VISITS_ENABLED",
        ):
            self.assertEqual(public[flag], "false", flag)
        database = contract["database"]
        private = {
            "database_url": f"postgresql+psycopg://{database['role']}:invented-password@127.0.0.1:{database['port']}/{database['name']}",
            "human_deploy_evidence_ref": "invented capture-tools preparation only",
            "workspace_llm_api_key": "invented-model-key",
            "google_connection_client_secret": "invented-google-secret",
            "google_connection_encryption_key": base64.urlsafe_b64encode(b"x" * 32).decode(),
        }
        settings = ExplicitSettings(**{key.lower(): value for key, value in public.items()}, **private)
        settings.validate_runtime_configuration()
        self.assertTrue(settings.workspace_capture_available)
        self.assertTrue(settings.workspace_agent_tools_enabled)
        self.assertFalse(settings.real_patient_recording_enabled)
        self.assertFalse(settings.workspace_core_connection_available)
        self.assertFalse(settings.workspace_core_record_enabled)
        self.assertFalse(settings.workspace_session_prep_enabled)
        self.assertFalse(settings.workspace_athena_connection_enabled)
        self.assertFalse(settings.workspace_prep_enabled)
        self.assertFalse(settings.workspace_routines_enabled)
        self.assertFalse(settings.workspace_capture_corrections_enabled)
        self.assertFalse(settings.workspace_capture_recovery_enabled)
        self.assertFalse(settings.workspace_capture_source_enabled)
        self.assertFalse(settings.workspace_capture_long_visits_enabled)
        # Tool families reachable when agent tools are on (agent_tools.py:217-225,
        # model_work.py:790-800). Base tools are local; connector/delivery families
        # can touch real Google/Microsoft account content when those overlays are on.
        self.assertEqual(
            TOOL_NAMES,
            (
                "list_selected_sources",
                "read_selected_source",
                "read_saved_teammate_draft",
                "read_current_operation_status",
            ),
        )
        self.assertEqual(
            CONNECTOR_TOOL_NAMES,
            ("propose_research_query", "execute_reviewed_research", "read_research_result"),
        )
        self.assertEqual(DELIVERY_TOOL_NAMES, ("execute_reviewed_delivery", "read_delivery_status"))
        self.assertTrue(settings.workspace_google_message_available)
        self.assertEqual(
            contract["optional_runtime_features"]["google_content"],
            "actual consenting account content; never relabelled as invented",
        )
        # Process guard still refuses turning real-patient recording on via env.
        refused = ExplicitSettings(
            **{key.lower(): value for key, value in public.items()},
            **private,
            real_patient_recording_enabled=True,
        )
        self.assertTrue(
            any("REAL_PATIENT_RECORDING_ENABLED must remain false" in item
                for item in refused.runtime_configuration_errors())
        )


if __name__ == "__main__":
    unittest.main()
