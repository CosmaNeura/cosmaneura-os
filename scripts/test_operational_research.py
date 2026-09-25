"""Research startup selection and composition; no publisher or account access."""

import copy
import json
import unittest

import test_operational_connections as connections_fixture
from operational_research import add_research


class OperationalResearch(unittest.TestCase):
    def setUp(self):
        connections = connections_fixture.OperationalConnections()
        connections.setUp()
        self.base = connections.prepare()
        self.profile = json.loads((connections_fixture.ROOT / "docs/operational-research.example.json").read_text())

    def test_composes_full_maps_and_keeps_athena_separate(self):
        self.profile["enabled"] = True
        result = add_research(self.base, self.profile)
        config = result["os.services.tfvars.json"]
        self.assertEqual(len(config["workspace_features"]), 36)
        for flag in ["WORKSPACE_RESEARCH_IO_ENABLED", "WORKSPACE_GOOGLE_CONNECTION_ENABLED",
                     "WORKSPACE_MICROSOFT_CONNECTION_ENABLED"]:
            self.assertTrue(config["workspace_features"][flag])
            self.assertTrue(result["os.athena-readonly.tfvars.json"]["workspace_features"][flag])
        self.assertFalse(config["workspace_features"]["WORKSPACE_ATHENA_CONNECTION_ENABLED"])
        self.assertTrue(result["os.athena-readonly.tfvars.json"]["workspace_features"]["WORKSPACE_ATHENA_CONNECTION_ENABLED"])
        self.assertEqual(result["provider-registration.json"], self.base["provider-registration.json"])
        self.assertFalse(self.base["os.services.tfvars.json"]["workspace_features"]["WORKSPACE_RESEARCH_IO_ENABLED"])
        public = config["workspace_public_configuration"]
        self.assertNotIn("RESEARCH_OPENFDA_API_KEY", public)
        self.assertEqual(json.loads(public["RESEARCH_DATASET_MAPPINGS"]), self.profile["dataset_mappings"])
        self.assertFalse(result["research-configuration.json"]["publisher_acceptance_performed"])

    def test_unkeyed_sources_and_explicit_off_need_no_credentials(self):
        self.profile.update(sources=["pubmed", "clinical_trials", "dailymed", "rxnorm",
                                     "cms_coverage", "npi_registry"],
                            dataset_mappings={}, openfda_api_key=None)
        result = add_research(self.base, self.profile)
        config = result["os.services.tfvars.json"]
        self.assertFalse(config["workspace_features"]["WORKSPACE_RESEARCH_IO_ENABLED"])
        self.assertNotIn("RESEARCH_OPENFDA_API_KEY", config["workspace_secret_references"])
        self.assertEqual(config["workspace_public_configuration"]["RESEARCH_DATASET_MAPPINGS"], "{}")

    def test_invalid_or_incomplete_source_selection_is_rejected(self):
        cases = [
            lambda p: p.update(enabled="true"),
            lambda p: p.update(version=True),
            lambda p: p.update(sources=["pubmed", "pubmed"]),
            lambda p: p.update(sources=["https://arbitrary.invalid"]),
            lambda p: p.update(sources=[{}]),
            lambda p: p.update(openfda_api_key=None),
            lambda p: p.update(openfda_api_key="plaintext"),
            lambda p: p.update(openfda_api_key=self.base["os.services.tfvars.json"]["workspace_secret_references"]["GOOGLE_CONNECTION_CLIENT_SECRET"]),
            lambda p: p.update(dataset_mappings={}),
            lambda p: p["dataset_mappings"]["cms_open_data"].update(query_field="unknown"),
            lambda p: p["dataset_mappings"]["cms_open_data"].update(dataset_id={}),
            lambda p: p["dataset_mappings"]["medicare_care_compare"].update(metadata_sha256="unpinned"),
            lambda p: p["dataset_mappings"]["medicare_care_compare"].update(distribution_index=True),
            lambda p: p["dataset_mappings"]["cms_open_data"].update(endpoint="https://arbitrary.invalid"),
            lambda p: p.update(sources=["pubmed"]),
        ]
        for change in cases:
            profile = copy.deepcopy(self.profile)
            change(profile)
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                add_research(self.base, profile)


if __name__ == "__main__":
    unittest.main()
