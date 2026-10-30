"""Exercise native/Docker startup sequencing without launching real services."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

MOCK = r'''#!PYTHON
import json, os, pathlib, sys, time
name = pathlib.Path(sys.argv[0]).name
state_path = pathlib.Path(os.environ["COSMAS_STARTUP_TEST_STATE"])
state = json.loads(state_path.read_text())
state["calls"].append([name, *sys.argv[1:]])
state_path.write_text(json.dumps(state))
if name == "python3":
    if len(sys.argv) == 3 and sys.argv[1] == "-" and sys.argv[2].isdigit():
        sys.stdin.read()
        service = "postgres" if sys.argv[2] == "54329" else "redis"
        sys.exit(0 if service in state.get("busy", []) else 1)
    os.execv(os.environ["COSMAS_STARTUP_TEST_PYTHON"],
             [os.environ["COSMAS_STARTUP_TEST_PYTHON"], *sys.argv[1:]])
if name == "psql":
    if state.pop("psql_hang_once", False):
        state_path.write_text(json.dumps(state))
        time.sleep(60)
    if state.get("postgres"):
        print("1"); sys.exit(0)
    sys.exit(1)
if name == "redis-cli":
    if state.get("redis"):
        print("PONG"); sys.exit(0)
    sys.exit(1)
if name == "docker-compose":
    if sys.argv[1] == "up":
        if state.get("start_failure"): sys.exit(1)
        for service in sys.argv[3:]:
            if not state.get("health_failure"):
                state[service] = True
        state_path.write_text(json.dumps(state))
        sys.exit(0)
    if "exec" in sys.argv:
        service = sys.argv[3]
        if not state.get(service): sys.exit(1)
        if service == "redis": print("PONG")
        sys.exit(0)
if name == "docker" and sys.argv[1:3] == ["image", "inspect"]:
    print("sha256:test" if "Id" in sys.argv[3] else "2026-10-30T00:00:00Z")
if name == "git": sys.exit(1)
sys.exit(0)
'''


class LocalServicesStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        for name in ("ensure-local-services.sh", "dev-up.sh", "ci-local.sh", "release-artifact.sh"):
            shutil.copyfile(REPO / "scripts" / name, self.root / "scripts" / name)
        (self.root / ".env.example").write_text("COSMAS_ENV=synth_os\n")
        (self.root / "scripts/install-client-deps.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
        (self.root / "scripts/install-client-deps.sh").chmod(0o755)
        (self.root / "web").mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("bash", "dirname", "cp", "seq", "grep", "mkdir", "date", "tr"):
            target = shutil.which(name)
            assert target is not None, name
            (self.bin / name).symlink_to(target)
        for name in ("python3", "docker-compose", "docker", "uv", "corepack", "git", "sleep"):
            self.mock_tool(name)
        self.state_path = self.root / "state.json"
        self.env = dict(os.environ, PATH=str(self.bin), COSMAS_STARTUP_TEST_STATE=str(self.state_path),
                        COSMAS_STARTUP_TEST_PYTHON=sys.executable)

    def mock_tool(self, name):
        path = self.bin / name
        path.write_text(MOCK.replace("#!PYTHON", "#!" + sys.executable))
        path.chmod(0o755)

    def prepare(self, host_clients=True, **state):
        if host_clients:
            self.mock_tool("psql")
            self.mock_tool("redis-cli")
        self.state_path.write_text(json.dumps({"calls": [], **state}))

    def run_script(self, script="ensure-local-services.sh", *args):
        return subprocess.run([str(self.bin / "bash"), str(self.root / "scripts" / script), *args],
                              cwd=self.root, env=self.env, capture_output=True, text=True, timeout=30)

    def calls(self, name):
        return [row[1:] for row in json.loads(self.state_path.read_text())["calls"] if row[0] == name]

    def startups(self):
        return [row for row in self.calls("docker-compose") if row[0] == "up"]

    def test_cloud_native_services_reused_by_dev_and_ci(self):
        self.prepare(postgres=True, redis=True)
        for script in ("dev-up.sh", "ci-local.sh"):
            result = self.run_script(script)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls("docker-compose"), [])
        self.assertTrue(self.calls("uv"))

    def test_docker_only_host_and_repeat_start(self):
        self.prepare(host_clients=False)
        for _ in range(2):
            result = self.run_script("ensure-local-services.sh", "postgres", "redis")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.startups(), [["up", "-d", "postgres", "redis"]])

    def test_only_missing_service_started(self):
        for present, missing in (("postgres", "redis"), ("redis", "postgres")):
            with self.subTest(present=present):
                self.prepare(**{present: True})
                result = self.run_script("ensure-local-services.sh", "postgres", "redis")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.startups(), [["up", "-d", missing]])

    def test_release_requests_only_postgres(self):
        self.prepare(postgres=True, redis=False)
        result = self.run_script("release-artifact.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls("docker-compose"), [])
        self.assertEqual(self.calls("redis-cli"), [])
        self.assertTrue(any(row[0] == "run" for row in self.calls("docker")))

    def test_start_failure_prevents_migrations(self):
        self.prepare(start_failure=True)
        result = self.run_script("dev-up.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls("uv"), [])

    def test_readiness_failure_prevents_migrations(self):
        self.prepare(health_failure=True)
        result = self.run_script("dev-up.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not become ready", result.stderr)
        self.assertEqual(self.calls("uv"), [])

    def test_stalled_query_is_bounded_and_existing_service_reused(self):
        self.prepare(postgres=True, redis=True, psql_hang_once=True, busy=["postgres"])
        result = self.run_script("dev-up.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls("docker-compose"), [])
        self.assertTrue(self.calls("uv"))

    def test_busy_unhealthy_endpoint_not_replaced(self):
        self.prepare(busy=["postgres"], redis=True)
        result = self.run_script("dev-up.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.startups(), [])
        self.assertEqual(self.calls("uv"), [])


if __name__ == "__main__":
    unittest.main()
