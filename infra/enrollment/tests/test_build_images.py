from __future__ import annotations

import base64
import importlib.util
import json
import shlex
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("enrollment_build_images", ROOT / "infra/enrollment/build-images.py")
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


def private(path, value):
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    path.chmod(0o600)
    return path


@pytest.fixture
def build_case(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("Dockerfile", "Dockerfile.web", "Dockerfile.web.dockerignore", ".dockerignore", ".github/workflows/synth-ci.yml",
                 "infra/enrollment/database-job/Dockerfile", "infra/enrollment/database-job/database.py",
                 "infra/enrollment/private-clock/Dockerfile", "infra/enrollment/private-clock/database.py",
                 "src/cosmas_os/enrollment/models.py", "src/cosmas_os/enrollment/migration.py",
                 "src/cosmas_os/enrollment/private_clock_lab.py"):
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    (source / "web").mkdir()
    (source / "web/package.json").write_text('{"committed":true}')
    subprocess.run(["git", "init", "--quiet", source], check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "-c", "user.name=Synthetic operator", "-c", "user.email=operator@example.invalid", "commit", "--quiet", "-m", "fixture"], cwd=source, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source).decode().strip()
    f = json.loads((ROOT / "infra/enrollment/database-job/tests/foundation.json").read_text())
    public = {"VITE_ENROLLMENT_ENABLED": "true", "VITE_ENROLLMENT_ACCOUNT_ONLY": "true",
              "VITE_ENROLLMENT_ACCOUNT_ORIGIN": images.ACCOUNT, "VITE_ENROLLMENT_API_BASE": images.API,
              "VITE_ENROLLMENT_CLERK_ISSUER": "https://synthetic-only.clerk.accounts.dev",
              "VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY": "pk_test_" + base64.b64encode(b"synthetic-only.clerk.accounts.dev$").decode(),
              "VITE_BUILD_SHA": commit}
    return SimpleNamespace(source=source, commit=commit, foundation=private(tmp_path / "foundation.json", f),
                           public=private(tmp_path / "public.json", public), secret=private(tmp_path / "private.env", "CLERK_SECRET_KEY=invented-private-test-value-never-vendor\n"),
                           output=tmp_path / "output")


def prepare(c):
    return images.prepare(c.source, c.commit, c.public, c.foundation, [c.secret], c.output)


def test_committed_context_preserves_dockerfiles_and_uses_web_ignore_only_overlay(build_case):
    c = build_case
    original = (c.source / "Dockerfile.web").read_bytes()
    (c.source / "Dockerfile.web").write_text("uncommitted invalid Dockerfile")
    (c.source / "web/working.env").write_text(c.secret.read_text())
    assert prepare(c) == {"prepared": True, "contexts": 2, "queued": False, "pushed": False, "credentials_found": 0}
    assert (c.output / "account/Dockerfile.web").read_bytes() == original
    assert not (c.output / "account/web/working.env").exists()
    assert stat.S_IMODE((c.output / "account").stat().st_mode) == 0o700
    assert stat.S_IMODE((c.output / "account/web").stat().st_mode) == 0o755
    assert stat.S_IMODE((c.output / "account/web/package.json").stat().st_mode) == 0o644
    ignore = (c.source / "Dockerfile.web.dockerignore").read_bytes().rstrip(b"\n")
    assert (c.output / "account/.dockerignore").read_bytes() == ignore + b"\n!cosmabot-acr-task.yaml\n"
    task = json.loads((c.output / "account/cosmabot-acr-task.yaml").read_text())
    assert task["steps"][0]["env"] == ["DOCKER_BUILDKIT=1"]
    assert task["steps"][-1]["when"] == ["scan"]
    assert "aquasec/trivy@sha256:" in task["steps"][-2]["cmd"]
    assert "--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1" in task["steps"][-2]["cmd"]
    assert c.secret.read_text().split("=", 1)[1].strip() not in json.dumps(task)
    assert images.load_prepared(c.output, "account")[0]["credential_values_uploaded"] is False


@pytest.mark.parametrize("change", ["foreign-registry", "workspace-setting", "wrong-issuer", "legacy-issuer", "wrong-commit"])
def test_denied_foreign_or_mixed_inputs_leave_no_context(build_case, change):
    c = build_case
    path = c.foundation if change == "foreign-registry" else c.public
    data = json.loads(path.read_text())
    if change == "foreign-registry":
        data["registry_server"] = "existingbeta.azurecr.io"
    elif change == "workspace-setting":
        data["VITE_WORKSPACE_ORGANIZATION_ID"] = "org_existing"
    elif change == "wrong-issuer":
        data["VITE_ENROLLMENT_CLERK_ISSUER"] = "https://different.clerk.accounts.dev"
    elif change == "legacy-issuer":
        data["VITE_ENROLLMENT_CLERK_ISSUER"] = "https://clerk.staging.cosmas.ai"
        data["VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY"] = "pk_test_" + base64.b64encode(b"clerk.staging.cosmas.ai$").decode()
    else:
        data["VITE_BUILD_SHA"] = "a" * 40
    private(path, data)
    with pytest.raises(ValueError):
        prepare(c)
    assert not c.output.exists()


def test_prepared_non_root_copy_modes_cannot_change_before_queue(build_case):
    c = build_case
    prepare(c)
    (c.output / "account/web").chmod(0o700)
    with pytest.raises(ValueError, match="changed"):
        images.load_prepared(c.output, "account")


def test_committed_credential_is_denied_and_partial_context_removed(build_case):
    c = build_case
    (c.source / "web/package.json").write_text(c.secret.read_text())
    subprocess.run(["git", "add", "."], cwd=c.source, check=True)
    subprocess.run(["git", "-c", "user.name=Synthetic operator", "-c", "user.email=operator@example.invalid", "commit", "--quiet", "-m", "synthetic credential denial"], cwd=c.source, check=True)
    c.commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=c.source).decode().strip()
    p = json.loads(c.public.read_text())
    p["VITE_BUILD_SHA"] = c.commit
    private(c.public, p)
    with pytest.raises(ValueError, match="protected credential"):
        prepare(c)
    assert not c.output.exists()


def fake_azure(c, monkeypatch, *, output=b"", error=b"WARNING: Queued a run with ID: cjsynthetic1\n"):
    f = images.foundation(c.foundation)
    calls = []
    def run(command, timeout=60):
        calls.append(command)
        if command[:2] == ["account", "show"]:
            data = {"id": f["subscription_id"], "tenantId": f["tenant_id"], "state": "Enabled"}
        elif command[:2] == ["acr", "show"]:
            data = {"id": f["container_registry_id"], "loginServer": f["registry_server"]}
        elif command[:2] == ["acr", "run"]:
            return SimpleNamespace(stdout=output, stderr=error)
        else:
            pytest.fail("unexpected Azure operation")
        return SimpleNamespace(stdout=json.dumps(data).encode(), stderr=b"")
    monkeypatch.setattr(images, "azure", run)
    return calls


def test_queue_records_actual_non_json_id_and_cannot_duplicate(build_case, monkeypatch):
    c = build_case
    prepare(c)
    calls = fake_azure(c, monkeypatch)
    assert images.queue(c.output, "api")["run_id_recorded"] is True
    assert json.loads((c.output / "api-queued.json").read_text())["run_id"] == "cjsynthetic1"
    assert "--no-wait" in calls[-1] and "--no-logs" in calls[-1]
    with pytest.raises(FileExistsError):
        images.queue(c.output, "api")
    assert sum(command[:2] == ["acr", "run"] for command in calls) == 1


def test_unknown_queue_does_not_retry_or_claim_success(build_case, monkeypatch):
    c = build_case
    prepare(c)
    calls = fake_azure(c, monkeypatch, output=b"", error=b"unrecognized response")
    with pytest.raises(ValueError, match="reconciliation"):
        images.queue(c.output, "api")
    assert (c.output / "api-queue-intent.json").exists()
    assert not (c.output / "api-queued.json").exists()
    with pytest.raises(FileExistsError):
        images.queue(c.output, "api")
    assert sum(command[:2] == ["acr", "run"] for command in calls) == 1


@pytest.mark.parametrize("status,digest_matches", [("Running", True), ("Succeeded", True), ("Succeeded", False)])
def test_receipt_requires_actual_completed_run_and_matching_registry_digest(build_case, monkeypatch, status, digest_matches):
    c = build_case
    prepare(c)
    m, job = images.load_prepared(c.output, "api")
    private(c.output / "api-queued.json", {"run_id": "cjsynthetic1", "source_commit": c.commit, "image_tag": job["image_tag"]})
    repository_tag = job["image_tag"].split("/", 1)[1]
    repository, tag = repository_tag.rsplit(":", 1)
    digest = "sha256:" + "a" * 64
    def run(command, timeout=60):
        if command[:3] == ["acr", "task", "show-run"]:
            data = {"runId": "cjsynthetic1", "status": status,
                    "outputImages": [{"registry": m["foundation"]["registry_server"], "repository": repository,
                                      "tag": tag, "digest": digest if digest_matches else "sha256:" + "b" * 64}]}
        elif command[:3] == ["acr", "repository", "show"]:
            assert status == "Succeeded"
            data = {"digest": digest}
        else:
            pytest.fail("unexpected Azure operation")
        return SimpleNamespace(stdout=json.dumps(data).encode())
    monkeypatch.setattr(images, "azure", run)
    receipt = c.output / "measured.json"
    if not digest_matches:
        with pytest.raises(ValueError, match="disagree"):
            images.collect(c.output, "api", receipt)
        assert not receipt.exists()
    else:
        assert images.collect(c.output, "api", receipt)["pushed_verified"] is (status == "Succeeded")
        data = json.loads(receipt.read_text())
        assert data["image_validation_passed"] is (status == "Succeeded")
        assert data["deployed"] is False and data["hosted_journey_qualified"] is False


def app_receipt(c):
    f = images.foundation(c.foundation)
    return private(c.public.parent / "api-image-receipt.json", {
        "contract_version": "enrollment-image-receipt.v1", "source_commit": c.commit,
        "kind": "api", "run_id": "cjsynthetic1", "status": "Succeeded",
        "image": f["registry_server"] + "/enrollment/api@sha256:" + "a" * 64,
        "context_sha256": "b" * 64, "buildkit": True, "image_validation_passed": True,
        "trivy_passed": True, "pushed_verified": True, "deployed": False,
        "hosted_journey_qualified": False, "reference_marker": "invented-reference-never-upload-this-file",
    })


def prepare_job(c, kind="database-job", *, fix=None):
    return images.prepare_job(c.source, c.commit, kind, c.foundation, app_receipt(c), c.commit,
                              [c.secret], c.output, fix)


def test_database_job_uses_exact_verified_base_and_minimal_unchanged_context(build_case):
    c = build_case
    assert prepare_job(c)["contexts"] == 1
    m, job = images.load_prepared(c.output, "database-job")
    context = c.output / "database-job"
    assert {str(p.relative_to(context)) for p in context.rglob("*") if p.is_file()} == {
        ".dockerignore", images.RECIPE, "infra/enrollment/database-job/Dockerfile", "infra/enrollment/database-job/database.py"}
    for name in ("Dockerfile", "database.py"):
        assert (context / "infra/enrollment/database-job" / name).read_bytes() == (c.source / "infra/enrollment/database-job" / name).read_bytes()
    task = json.loads((context / images.RECIPE).read_text())
    build = shlex.split(task["steps"][0]["build"])
    assert build[build.index("--build-arg") + 1] == "APP_IMAGE=" + m["application_image_receipt"]["image"]
    assert sum(token == "--build-arg" for token in build) == 1
    assert task["steps"][0]["env"] == ["DOCKER_BUILDKIT=1"]
    assert task["steps"][-1]["when"] == ["scan"]
    code = shlex.split(task["steps"][1]["cmd"])[-1]
    compile(code, "<database image validation>", "exec")
    assert "os.getuid()==10001" in code and "enrollment_runtime" in code and "result.returncode==1" in code
    assert "invented-reference-never-upload-this-file" not in "".join(p.read_text() for p in context.rglob("*") if p.is_file())
    assert job["dockerfile_sha256"] and m["database_job_qualified"] is False


@pytest.mark.parametrize("change", ["unscanned", "foreign-image", "wrong-source"])
def test_job_denies_unverified_foreign_or_mixed_application_receipt(build_case, change):
    c = build_case
    receipt = app_receipt(c)
    data = json.loads(receipt.read_text())
    if change == "unscanned":
        data["trivy_passed"] = False
    elif change == "foreign-image":
        data["image"] = "existingbeta.azurecr.io/enrollment/api@sha256:" + "a" * 64
    else:
        data["source_commit"] = "a" * 40
    private(receipt, data)
    with pytest.raises(ValueError, match="application receipt"):
        images.prepare_job(c.source, c.commit, "database-job", c.foundation, receipt, c.commit, [c.secret], c.output)
    assert not c.output.exists()


def test_job_receipt_authority_tamper_prevents_queue_before_azure(build_case, monkeypatch):
    c = build_case
    prepare_job(c)
    receipt = c.public.parent / "api-image-receipt.json"
    data = json.loads(receipt.read_text())
    data["reference_marker"] = "changed"
    private(receipt, data)
    monkeypatch.setattr(images, "azure", lambda *args: pytest.fail("changed authority may not reach Azure"))
    with pytest.raises(ValueError, match="authority changed"):
        images.queue(c.output, "database-job")


@pytest.mark.parametrize("fix", [None, "not-a-commit"])
def test_private_clock_is_closed_without_explicit_committed_fix(build_case, fix):
    c = build_case
    with pytest.raises(ValueError, match="clock retry fix"):
        prepare_job(c, "private-clock", fix=fix)
    assert not c.output.exists()


def test_private_clock_rejects_old_base_and_accepts_only_matching_fixed_source(build_case):
    c = build_case
    old = c.commit
    with pytest.raises(ValueError, match="regression source"):
        prepare_job(c, "private-clock", fix=old)
    lab = c.source / "src/cosmas_os/enrollment/private_clock_lab.py"
    lab.write_text(lab.read_text() + "\n# Synthetic publisher gate fixture; no clock qualification.\n")
    regression = c.source / "tests/enrollment/test_private_clock_lab.py"
    regression.parent.mkdir(parents=True)
    regression.write_text("# Synthetic accepted-source ancestry fixture only.\n")
    subprocess.run(["git", "add", "."], cwd=c.source, check=True)
    subprocess.run(["git", "-c", "user.name=Synthetic operator", "-c", "user.email=operator@example.invalid", "commit", "--quiet", "-m", "synthetic clock source gate"], cwd=c.source, check=True)
    fixed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=c.source).decode().strip()
    with pytest.raises(ValueError, match="same exact"):
        images.prepare_job(c.source, fixed, "private-clock", c.foundation, app_receipt(c), old, [c.secret], c.output, fixed)
    c.commit = fixed
    assert prepare_job(c, "private-clock", fix=fixed)["prepared"] is True
    manifest, _ = images.load_prepared(c.output, "private-clock")
    assert manifest["clock_retry_fix_commit"] == fixed and manifest["private_clock_qualified"] is False
    task = json.loads((c.output / "private-clock" / images.RECIPE).read_text())
    compile(shlex.split(task["steps"][1]["cmd"])[-1], "<private clock job validation>", "exec")


def test_database_job_queue_and_collect_preserve_digest_and_unqualified_database_state(build_case, monkeypatch):
    c = build_case
    prepare_job(c)
    fake_azure(c, monkeypatch)
    assert images.queue(c.output, "database-job")["run_id_recorded"] is True
    m, job = images.load_prepared(c.output, "database-job")
    repository_tag = job["image_tag"].split("/", 1)[1]
    repository, tag = repository_tag.rsplit(":", 1)
    digest = "sha256:" + "c" * 64
    def run(command, timeout=60):
        if command[:3] == ["acr", "task", "show-run"]:
            data = {"runId": "cjsynthetic1", "status": "Succeeded", "outputImages": [{"registry": m["foundation"]["registry_server"], "repository": repository, "tag": tag, "digest": digest}]}
        elif command[:3] == ["acr", "repository", "show"]:
            data = {"digest": digest}
        else:
            pytest.fail("unexpected Azure operation")
        return SimpleNamespace(stdout=json.dumps(data).encode())
    monkeypatch.setattr(images, "azure", run)
    receipt = c.output / "job-image.json"
    assert images.collect(c.output, "database-job", receipt)["pushed_verified"] is True
    data = json.loads(receipt.read_text())
    assert data["base_application_image"] == m["application_image_receipt"]["image"]
    assert data["database_job_qualified"] is False and data["private_clock_qualified"] is False
    assert data["hosted_journey_qualified"] is False and data["deployed"] is False
