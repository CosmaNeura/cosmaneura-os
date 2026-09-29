import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

path = Path(__file__).with_name("prepare-operational-startup.py")
spec = importlib.util.spec_from_file_location("operational_startup", path)
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)


class OperationalStartup(unittest.TestCase):
    def setUp(self):
        self.bindings = json.loads(
            (
                path.parents[1] / "docs/operational-service-bindings.example.json"
            ).read_text()
        )
        self.identity = {
            "frontendOrigin": "https://identity.example.invalid",
            "apiOrigin": "https://api.example.invalid",
        }

    def test_actual_caller_scope_cohort_and_scheduling_audience_are_shared(self):
        result = startup.compile_inputs(self.identity, self.bindings)
        os = result["os.services.tfvars.json"]
        core = result["core.services.tfvars.json"]
        scribe = result["scribe.service.tfvars.json"]
        scheduling = result["scheduling.services.tfvars.json"]
        self.assertEqual(
            os["workspace_expected_runtime_client_id"],
            core["core_beta_authority"]["companion_client_id"],
        )
        self.assertEqual(
            core["core_beta_authority"]["caller_client_id"],
            self.bindings["core"]["sovereign_client_id"],
        )
        self.assertEqual(
            core["core_beta_authority"]["scribe_receiver_client_id"],
            self.bindings["core"]["scribe_receiver_client_id"],
        )
        self.assertEqual(
            os["workspace_public_configuration"]["CORE_CAPTURE_SCOPE"],
            "api://" + core["core_beta_authority"]["audience"] + "/.default",
        )
        self.assertEqual(
            core["scribe_service_scope"],
            "api://" + scribe["workflow_api_audience"] + "/.default",
        )
        self.assertEqual(
            core["core_beta_connection_binding"]["scribe_workflow_client_id"],
            scribe["trusted_platform_client_id"],
        )
        self.assertEqual(
            os["workspace_public_configuration"]["SCHEDULING_GOOGLE_CLIENT_ID"],
            scheduling["google_staff_oidc_audience"],
        )
        for worker in ["speech", "translation"]:
            values = result[f"scribe.{worker}-consumer.tfvars.json"]
            key = (
                "transcription_consumer_tenant_id"
                if worker == "speech"
                else "translation_consumer_tenant_id"
            )
            self.assertEqual(
                values[key], scribe["scribe_capture_features"]["tenant_ids"][0]
            )
        self.assertFalse(result["service-bindings.json"]["deployable_now"])

    def test_scheduling_api_mount_is_emitted_without_relaxing_other_origins(self):
        self.bindings["scheduling"]["origin"] += "/api"
        result = startup.compile_inputs(self.identity, self.bindings)
        self.assertEqual(
            result["os.services.tfvars.json"]["workspace_public_configuration"]["SCHEDULING_ORIGIN"],
            self.bindings["scheduling"]["origin"],
        )
        for service, field in (("core", "origin"), ("scribe", "origin"), ("core", "web_origin")):
            with self.subTest(service=service, field=field):
                altered = copy.deepcopy(self.bindings)
                altered[service][field] += "/api"
                with self.assertRaises(ValueError):
                    startup.compile_inputs(self.identity, altered)

    def test_scheduling_base_rejects_ambiguous_and_arbitrary_paths(self):
        for suffix in ("/api/", "/API", "/api/v1", "/%61pi", "/api/..", "/api?x=1", "/api#x"):
            with self.subTest(suffix=suffix):
                altered = copy.deepcopy(self.bindings)
                altered["scheduling"]["origin"] += suffix
                with self.assertRaises(ValueError):
                    startup.compile_inputs(self.identity, altered)

    def test_worker_and_athena_layers_are_separate_from_service_startup(self):
        result = startup.compile_inputs(self.identity, self.bindings)
        service = result["scribe.service.tfvars.json"]
        self.assertFalse(service["scribe_capture_features"]["configured_job"])
        self.assertTrue(service["scribe_capture_features"]["continuation"])
        self.assertTrue(service["scribe_capture_features"]["long_visits"])
        self.assertNotIn("enable_transcription_consumer", service)
        self.assertNotIn("enable_translation_consumer", service)
        self.assertFalse(
            result["core.services.tfvars.json"]["core_beta_features"][
                "ATHENA_APPOINTMENT_READ_ENABLED"
            ]
        )
        athena = result["core.athena-readonly.tfvars.json"]["core_beta_features"]
        self.assertTrue(athena["ATHENA_APPOINTMENT_READ_ENABLED"])
        self.assertTrue(athena["ATHENA_VISIT_LINK_ENABLED"])
        self.assertFalse(any("ATHENA" in key and "WRITE" in key for key in athena))
        self.assertNotIn(
            "enable_transcription_consumer", result["scribe.speech-grants.tfvars.json"]
        )
        self.assertNotIn(
            "enable_translation_consumer",
            result["scribe.translation-grants.tfvars.json"],
        )

    def test_invalid_bindings_and_plaintext_credentials_are_rejected(self):
        changes = [
            lambda b: b.update(version=1),
            lambda b: b["core"].pop("sovereign_client_id"),
            lambda b: b["core"].update(sovereign_client_id=b["os_runtime_client_id"]),
            lambda b: b["core"].update(
                scribe_receiver_client_id=b["os_runtime_client_id"]
            ),
            lambda b: b["core"].update(
                scribe_receiver_client_id=b["core"]["sovereign_client_id"]
            ),
            lambda b: b["core"].update(
                scribe_receiver_client_id=b["core"]["scribe_workflow_client_id"]
            ),
            lambda b: b["core"].update(scribe_receiver_client_id=None),
            lambda b: b["core"].update(api_audience=b["scribe"]["api_audience"]),
            lambda b: b.update(
                os_runtime_client_id=b["core"]["scribe_workflow_client_id"]
            ),
            lambda b: b["scribe"].update(
                practice_id="00000000-0000-0000-0000-000000000000"
            ),
            lambda b: b["translation_provider"].update(
                endpoint="https://different.openai.azure.com/openai/v1"
            ),
            lambda b: b["core"].update(authority_tenant_ref="not-a-reviewed-tenant"),
            lambda b: b["secret_references"]["WORKSPACE_LLM_API_KEY"].update(
                value="plaintext-is-not-supported"
            ),
            lambda b: b["scheduling"].update(origin="http://localhost:8000"),
            lambda b: b.update(capture_upload_origins=[]),
        ]
        for change in changes:
            with self.subTest(change=change):
                altered = copy.deepcopy(self.bindings)
                change(altered)
                with self.assertRaises(ValueError):
                    startup.compile_inputs(self.identity, altered)

    def test_companion_capture_does_not_require_a_separate_scribe_receiver(self):
        self.bindings["core"]["scribe_receiver_client_id"] = ""
        result = startup.compile_inputs(self.identity, self.bindings)
        authority = result["core.services.tfvars.json"]["core_beta_authority"]
        self.assertEqual(authority["scribe_receiver_client_id"], "")
        self.assertEqual(
            authority["companion_client_id"], self.bindings["os_runtime_client_id"]
        )

    def test_translation_preserves_both_account_bound_azure_endpoint_forms(self):
        for domain in ("openai.azure.com", "services.ai.azure.com"):
            with self.subTest(domain=domain):
                provider = self.bindings["translation_provider"]
                provider["endpoint"] = f"https://invented-w76.{domain}/openai/v1"
                result = startup.compile_inputs(self.identity, self.bindings)
                self.assertEqual(
                    result["scribe.translation-grants.tfvars.json"]["translation_provider"],
                    provider,
                )

    def test_translation_rejects_changed_account_or_noncanonical_endpoint(self):
        for domain in ("openai.azure.com", "services.ai.azure.com"):
            valid = f"https://invented-w76.{domain}/openai/v1"
            invalid = [
                valid.replace("invented-w76", "different"),
                valid.replace("https://", "http://"),
                valid.replace(domain, "arbitrary.example"),
                valid.replace("https://", "https://user:password@"),
                valid.replace("/openai/v1", ":443/openai/v1"),
                valid + "?api-version=1",
                valid + "#fragment",
                valid + "/",
                valid + "/chat/completions",
                valid.replace("invented-w76", "INVENTED-W76"),
                valid.replace(domain, domain + ".example"),
                valid.replace("invented-w76", "nested.invented-w76"),
            ]
            for endpoint in invalid:
                with self.subTest(endpoint=endpoint):
                    altered = copy.deepcopy(self.bindings)
                    altered["translation_provider"]["endpoint"] = endpoint
                    with self.assertRaises(ValueError):
                        startup.compile_inputs(self.identity, altered)
            for key, value in (
                ("resource_id", "not-an-account-resource"),
                ("deployment", "unsafe/deployment"),
            ):
                with self.subTest(domain=domain, key=key):
                    altered = copy.deepcopy(self.bindings)
                    altered["translation_provider"].update(endpoint=valid)
                    altered["translation_provider"][key] = value
                    with self.assertRaises(ValueError):
                        startup.compile_inputs(self.identity, altered)

    def test_duplicate_public_binding_keys_are_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "duplicate.json"
            file.write_text('{"version":1,"version":1}')
            with self.assertRaises(ValueError):
                startup.public_json(file)


if __name__ == "__main__":
    unittest.main()
