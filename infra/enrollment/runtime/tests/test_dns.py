"""Synthetic DNS propagation/ownership checks; no live queries."""
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("enrollment_dns", Path(__file__).parents[1] / "verify-dns.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StagingDnsTests(unittest.TestCase):
    def query(self, host="onboarding.staging.cosmas.ai"):
        return {"hostname": host, "cname_target": "ca-account.synthetic.centralus.azurecontainerapps.io",
                "verification_id": "synthetic-ownership-token"}

    def runner(self, query, broken=None):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            resolver, name, kind = argv[-3:]
            value = query["cname_target"] + "." if kind == "CNAME" else '"synthetic-ownership-" "token"'
            if broken and broken(resolver, name, kind):
                value = "wrong.example." if kind == "CNAME" else '"wrong-ownership-token"'
            return SimpleNamespace(stdout=f"{name}. 300 IN {kind} {value}\n")
        return run, calls

    def test_both_owned_domains_require_both_record_types_at_both_resolvers(self):
        for host in module.HOSTS:
            query = self.query(host)
            run, calls = self.runner(query)
            result = module.verify(query, run)
            self.assertEqual(result["verified"], "true")
            self.assertEqual(result["hostname"], host)
            self.assertEqual(len(calls), 4)
            self.assertEqual(len(result["records_sha256"]), 64)

    def test_pending_wrong_or_proxied_dns_and_wrong_ownership_deny_certificate_stage(self):
        for broken in (lambda r, n, k: r == "@8.8.8.8", lambda r, n, k: k == "TXT", lambda r, n, k: k == "CNAME"):
            query = self.query()
            run, _ = self.runner(query, broken)
            with self.assertRaises(ValueError):
                module.verify(query, run)
        with self.assertRaises(ValueError):
            module.verify(self.query(), lambda *a, **k: SimpleNamespace(stdout=""))

    def test_foreign_beta_prod_and_caller_targets_are_rejected_before_dns(self):
        for patch in ({"hostname": "staging.cosmas.ai"}, {"hostname": "onboarding.staging.cosmas.ai.evil.example"},
                      {"hostname": "app.cosmas.ai"}, {"cname_target": "proxy.example"},
                      {"verification_id": "not\na\ntoken"}, {"dns_ready": "true"}):
            with self.assertRaises(ValueError):
                module.verify({**self.query(), **patch}, lambda *a, **k: self.fail("No foreign query should run"))

    def test_stale_asuid_records_cannot_qualify_a_replaced_container_app(self):
        query = self.query()
        query["verification_id"] = "replacement-app-ownership-token"
        run, _ = self.runner(query)
        with self.assertRaises(ValueError):
            module.verify(query, run)


if __name__ == "__main__":
    unittest.main()
