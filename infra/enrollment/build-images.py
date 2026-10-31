#!/usr/bin/env python3
"""Prepare private BuildKit ACR tasks; queue/collect are explicit operator actions.

No cloud process runs during prepare. Dockerfiles and security/scanner pins come
from the selected commit, never from the working tree. Inputs/receipts stay out
of the uploaded context; only the seven public account fields become arguments.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

PUBLIC_NAMES = {
    "VITE_ENROLLMENT_ENABLED", "VITE_ENROLLMENT_ACCOUNT_ONLY",
    "VITE_ENROLLMENT_ACCOUNT_ORIGIN", "VITE_ENROLLMENT_API_BASE",
    "VITE_ENROLLMENT_CLERK_ISSUER", "VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY", "VITE_BUILD_SHA",
}
ACCOUNT = "https://onboarding.staging.cosmas.ai"
API = "https://enrollment-api.staging.cosmas.ai"
RECIPE = "cosmabot-acr-task.yaml"


def private_read(path: Path, limit: int = 1_000_000) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > limit):
            raise ValueError("protected owner regular 0600 file required")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read(limit + 1)
    finally:
        os.close(fd)


def write(path: Path, value: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def foundation(path: Path) -> dict:
    raw = json.loads(private_read(path))
    f = raw.get("foundation", {}).get("value", raw)
    return owned_foundation(f)


def owned_foundation(f: dict) -> dict:
    suffix = re.fullmatch(r"rg-cosmabot-enrollment-staging-([a-z0-9]{6,8})", f.get("resource_group_name", ""))
    if not suffix or f.get("contract_version") != "enrollment-foundation.v1" or f.get("environment") != "staging":
        raise ValueError("dedicated staging foundation required")
    for name in ("subscription_id", "tenant_id"):
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", f.get(name, "")):
            raise ValueError("foundation identity required")
    registry = "acrcbotenrstg" + suffix[1]
    expected_id = (f"/subscriptions/{f['subscription_id']}/resourceGroups/{f['resource_group_name']}"
                   f"/providers/Microsoft.ContainerRegistry/registries/{registry}")
    if (f.get("container_registry_id") != expected_id or f.get("registry_server") != registry + ".azurecr.io"
            or f.get("location") not in {"centralus", "eastus2"}):
        raise ValueError("exact owned staging registry required")
    return {name: f[name] for name in ("subscription_id", "tenant_id", "resource_group_name", "container_registry_id", "registry_server", "location", "contract_version", "environment")}


def public_config(path: Path, commit: str) -> dict:
    p = json.loads(private_read(path))
    if (set(p) != PUBLIC_NAMES or any(not isinstance(value, str) for value in p.values())
            or p["VITE_ENROLLMENT_ENABLED"] != "true" or p["VITE_ENROLLMENT_ACCOUNT_ONLY"] != "true"
            or p["VITE_ENROLLMENT_ACCOUNT_ORIGIN"] != ACCOUNT or p["VITE_ENROLLMENT_API_BASE"] != API
            or p["VITE_BUILD_SHA"] != commit):
        raise ValueError("exact source and seven public account fields required")
    issuer = p["VITE_ENROLLMENT_CLERK_ISSUER"]
    match = re.fullmatch(r"https://([a-z0-9]+(?:-[a-z0-9]+)*\.clerk\.accounts\.dev)", issuer)
    key = p["VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY"]
    if not match or not re.fullmatch(r"pk_test_[A-Za-z0-9+/=_-]+", key):
        raise ValueError("Development public Clerk identity required")
    decoded = base64.b64decode(key[8:], altchars=b"-_", validate=True).decode()
    if decoded != match[1] + "$":
        raise ValueError("Development issuer and public key mismatch")
    return p


def protected_values(paths: list[Path]) -> list[bytes]:
    """Read only explicitly selected files; never persist/print values or hashes."""
    values = []
    for path in paths:
        raw = private_read(path)
        if path.suffix == ".env":
            for line in raw.decode().splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                name, sep, value = line.removeprefix("export ").partition("=")
                if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                    raise ValueError("simple protected env assignments required")
                if name.endswith("PUBLISHABLE_KEY") or not re.search(r"SECRET|TOKEN|PASSWORD|DATABASE_URL|PRIVATE_KEY", name):
                    continue
                parsed = shlex.split(value, comments=True)
                if len(parsed) != 1:
                    raise ValueError("bounded protected env value required")
                values.append(parsed[0].encode())
        else:
            values.append(raw.removesuffix(b"\n"))
    if not values or any(len(value) < 12 or b"\x00" in value for value in values):
        raise ValueError("at least one bounded protected credential value required")
    return values


def scan(context: Path, values: list[bytes]) -> str:
    digest = hashlib.sha256()
    for path in sorted(context.rglob("*")):
        if path.is_symlink():
            raise ValueError("context symlinks forbidden")
        digest.update(path.relative_to(context).as_posix().encode() + b"\0" + str(stat.S_IMODE(path.stat().st_mode)).encode() + b"\0")
        if not path.is_file():
            continue
        content = path.read_bytes()
        if any(value in content for value in values):
            raise ValueError("protected credential found in build context")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def git_archive(source: Path, commit: str) -> bytes:
    if not source.is_absolute() or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("absolute canonical source and full commit required")
    found = subprocess.run(["git", "rev-parse", "--verify", commit + "^{commit}"], cwd=source,
                           check=True, capture_output=True, timeout=30).stdout.decode().strip()
    if found != commit:
        raise ValueError("exact committed source required")
    return subprocess.run(["git", "archive", "--format=tar", commit], cwd=source,
                          check=True, capture_output=True, timeout=120).stdout


def extract(archive: bytes, output: Path) -> None:
    output.mkdir(mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for member in stream:
            parts = Path(member.name).parts
            if not parts or member.name.startswith("/") or ".." in parts or not (member.isdir() or member.isfile()):
                raise ValueError("only regular committed context files permitted")
            path = output / member.name
            if member.isdir():
                path.mkdir(mode=0o755, parents=True, exist_ok=True)
                path.chmod(0o755)
            else:
                path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                with stream.extractfile(member) as content:
                    path.write_bytes(content.read())
                # The outer context stays private0700. COPY descendants must
                # retain committed read/execute modes for the non-root image.
                path.chmod(0o755 if member.mode & 0o111 else 0o644)


def recipe(kind: str, image: str, public: dict, trivy: str) -> dict:
    dockerfile = "Dockerfile" if kind == "api" else "Dockerfile.web"
    arguments = ["-t", image, "-f", dockerfile]
    if kind == "account":
        arguments += ["--build-arg", "WEB_BUILD_PROFILE=enrollment"]
        for name, value in sorted(public.items()):
            arguments += ["--build-arg", name + "=" + value]
    arguments.append(".")
    if kind == "api":
        code = """import importlib,json,os,subprocess,sys,time,urllib.request
assert os.getuid()==10001
for module in ('cosmas_os.api.app','cosmas_os.enrollment.api','uvicorn'): importlib.import_module(module)
env={'PATH':os.environ['PATH'],'PYTHONPATH':'/app/src','ENROLLMENT_ENABLED':'false','ENROLLMENT_DATA_MODE':'synthetic'}
p=subprocess.Popen([sys.executable,'-m','cosmas_os.enrollment.api'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 for attempt in range(100):
  if p.poll() is not None: raise RuntimeError('Enrollment module exited before startup')
  try:
   with urllib.request.urlopen('http://127.0.0.1:8000/enrollment/v1/config',timeout=1) as response:
    body=json.load(response); assert body['contract_version']=='enrollment.v1' and body['enabled'] is False and body['activation_available'] is False and body['billing_configured'] is False
   break
  except OSError: time.sleep(.1)
 else: raise RuntimeError('Enrollment module did not serve closed configuration')
finally:
 p.terminate()
 try: p.wait(timeout=5)
 except subprocess.TimeoutExpired: p.kill(); p.wait()
"""
        validation = {"cmd": image + " -B -c " + shlex.quote(code), "entryPoint": "python"}
    else:
        checks = {
            "source_commit": public["VITE_BUILD_SHA"], "application_origin": ACCOUNT,
            "enrollment_api_origin": API, "clerk_issuer": public["VITE_ENROLLMENT_CLERK_ISSUER"],
            "kind": "enrollment-account", "environment": "staging",
        }
        shell = "set -eu; test \"$(id -u)\" != 0; nginx -t; "
        for name, value in checks.items():
            pattern = '"' + name + '"[[:space:]]*:[[:space:]]*"' + re.escape(value) + '"'
            shell += "grep -Eq " + shlex.quote(pattern) + " /usr/share/nginx/html/cosmas-enrollment-build.json; "
        for name, value in (("account_only", "true"), ("clinical_workspace", "false")):
            shell += "grep -Eq " + shlex.quote('"' + name + '"[[:space:]]*:[[:space:]]*' + value) + " /usr/share/nginx/html/cosmas-enrollment-build.json; "
        pattern = '"commit"[[:space:]]*:[[:space:]]*"' + public["VITE_BUILD_SHA"] + '"'
        shell += "grep -Eq " + shlex.quote(pattern) + " /usr/share/nginx/html/version.json; "
        shell += "grep -rlF " + shlex.quote(public["VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY"]) + " /usr/share/nginx/html/assets >/dev/null; "
        shell += "nginx -g 'daemon off;' & pid=$!; trap 'kill $pid; wait $pid || true' EXIT; "
        shell += "i=0; until curl --fail --silent http://127.0.0.1:8080/healthz >/dev/null; do i=$((i+1)); test $i -lt 30; sleep 1; done"
        validation = {"cmd": image + " -ec " + shlex.quote(shell), "entryPoint": "/bin/sh"}
    return {"version": "v1.1.0", "stepTimeout": 1800, "steps": [
        {"id": "build", "build": shlex.join(arguments), "env": ["DOCKER_BUILDKIT=1"]},
        {"id": "validate", **validation, "when": ["build"], "timeout": 120},
        {"id": "scan", "cmd": trivy
            + " image --image-src docker --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --no-progress " + image,
         "when": ["validate"], "timeout": 900},
        {"id": "push", "push": [image], "when": ["scan"], "timeout": 600},
    ]}


def prepare(source: Path, commit: str, public_path: Path, foundation_path: Path, secret_paths: list[Path], output: Path) -> dict:
    if not output.is_absolute() or output.exists() or output.resolve().is_relative_to(source.resolve()):
        raise ValueError("fresh private output outside source required")
    f, public, values = foundation(foundation_path), public_config(public_path, commit), protected_values(secret_paths)
    archive = git_archive(source, commit)
    output.mkdir(mode=0o700)
    try:
        suffix = commit + "-" + secrets.token_hex(6)
        jobs = {}
        for kind in ("api", "account"):
            context = output / kind
            extract(archive, context)
            dockerfile = context / ("Dockerfile" if kind == "api" else "Dockerfile.web")
            if "RUN --network=none" not in dockerfile.read_text() or "@sha256:" not in dockerfile.read_text():
                raise ValueError("reviewed pinned offline-install Dockerfile required")
            ci = (context / ".github/workflows/synth-ci.yml").read_text()
            pins = re.findall(r'aquasec/trivy@sha256:[0-9a-f]{64}', ci)
            if len(set(pins)) != 1:
                raise ValueError("one committed CI Trivy digest required")
            image = f["registry_server"] + "/enrollment/" + kind + ":" + suffix
            ignore_source = context / (".dockerignore" if kind == "api" else "Dockerfile.web.dockerignore")
            baseline = ignore_source.read_bytes()
            # ACR YAML runs select the root ignore file, not Dockerfile.web's
            # ignore. The sole source-file overlay is that committed policy;
            # explicitly include the generated public task definition.
            (context / ".dockerignore").write_bytes(baseline.rstrip(b"\n") + b"\n!" + RECIPE.encode() + b"\n")
            write(context / RECIPE, recipe(kind, image, public, pins[0]))
            jobs[kind] = {"image_tag": image, "context_sha256": scan(context, values),
                          "dockerfile_sha256": hashlib.sha256(dockerfile.read_bytes()).hexdigest(),
                          "committed_ignore_sha256": hashlib.sha256(baseline).hexdigest()}
        manifest = {"contract_version": "enrollment-image-build.v1", "source_commit": commit,
                    "foundation": f, "jobs": jobs, "public_config_sha256": hashlib.sha256(private_read(public_path)).hexdigest(),
                    "protected_secret_files": [str(path) for path in secret_paths], "credential_values_uploaded": False,
                    "prepared": True, "queued": False, "pushed": False, "hosted_journey_qualified": False}
        write(output / "prepared.json", manifest)
        return {"prepared": True, "contexts": 2, "queued": False, "pushed": False, "credentials_found": 0}
    except BaseException:
        shutil.rmtree(output)
        raise


def azure(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    if any(name in os.environ for name in ("AZURE_CORE_LOG_LEVEL", "AZURE_LOG_LEVEL", "AZURE_HTTP_LOGGING_ENABLED")):
        raise ValueError("Azure credential debugging forbidden")
    env = {name: value for name, value in os.environ.items() if name in {"PATH", "HOME", "AZURE_CONFIG_DIR", "LANG", "LC_ALL", "TMPDIR"}}
    return subprocess.run(["az", *command], check=True, capture_output=True, timeout=timeout, env=env)


def load_prepared(directory: Path, kind: str) -> tuple[dict, dict]:
    m = json.loads(private_read(directory / "prepared.json"))
    if m.get("contract_version") != "enrollment-image-build.v1" or kind not in {"api", "account"}:
        raise ValueError("prepared owned build required")
    m["foundation"] = owned_foundation(m["foundation"])
    job = m["jobs"][kind]
    prefix = m["foundation"]["registry_server"] + "/enrollment/" + kind + ":"
    if not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{40}-[0-9a-f]{12}", job["image_tag"]) or job["image_tag"][len(prefix):40 + len(prefix)] != m["source_commit"]:
        raise ValueError("owned image and source binding required")
    if scan(directory / kind, protected_values([Path(path) for path in m["protected_secret_files"]])) != job["context_sha256"]:
        raise ValueError("prepared build changed")
    return m, job


def queue(directory: Path, kind: str) -> dict:
    m, job = load_prepared(directory, kind)
    f = m["foundation"]
    account = json.loads(azure(["account", "show", "--query", "{id:id,tenantId:tenantId,state:state}", "-o", "json"]).stdout)
    if account != {"id": f["subscription_id"], "tenantId": f["tenant_id"], "state": "Enabled"}:
        raise ValueError("wrong Azure account")
    registry = f["registry_server"].split(".")[0]
    actual = json.loads(azure(["acr", "show", "--name", registry, "--resource-group", f["resource_group_name"],
                               "--subscription", f["subscription_id"], "--query", "{id:id,loginServer:loginServer}", "-o", "json"]).stdout)
    if actual != {"id": f["container_registry_id"], "loginServer": f["registry_server"]}:
        raise ValueError("wrong staging registry")
    # Never automatically repeat a timed-out/unknown queue operation.
    write(directory / (kind + "-queue-intent.json"), {"image_tag": job["image_tag"], "context_sha256": job["context_sha256"]})
    result = azure(["acr", "run", "--registry", registry, "--resource-group", f["resource_group_name"],
                    "--subscription", f["subscription_id"], "--file", RECIPE, "--platform", "linux/amd64",
                    "--timeout", "3600", "--no-wait", "--no-logs", "--output", "json", str(directory / kind)], 300)
    run_ids = set()
    try:
        value = json.loads(result.stdout)
        if isinstance(value, dict) and value.get("runId"):
            run_ids.add(value["runId"])
    except (ValueError, TypeError):
        pass
    # Older quick-task CLIs return no JSON. Capture only the official queue-ID
    # line; never forward source-upload SAS URLs or full CLI streams.
    run_ids.update(re.findall(r"^\s*(?:WARNING: )?Queued a run with ID: ([a-zA-Z0-9_-]+)\s*$", result.stderr.decode(), re.M))
    if len(run_ids) != 1 or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", next(iter(run_ids), "")):
        raise ValueError("queue outcome needs operator reconciliation; do not requeue")
    run_id = next(iter(run_ids))
    write(directory / (kind + "-queued.json"), {"run_id": run_id, "image_tag": job["image_tag"], "source_commit": m["source_commit"]})
    return {"queued": True, "run_id_recorded": True, "pushed_verified": False}


def collect(directory: Path, kind: str, receipt: Path) -> dict:
    m, job = load_prepared(directory, kind)
    queued = json.loads(private_read(directory / (kind + "-queued.json")))
    if queued["image_tag"] != job["image_tag"] or queued["source_commit"] != m["source_commit"]:
        raise ValueError("queue binding changed")
    f = m["foundation"]
    registry = f["registry_server"].split(".")[0]
    run = json.loads(azure(["acr", "task", "show-run", "--registry", registry, "--resource-group", f["resource_group_name"],
                           "--subscription", f["subscription_id"], "--run-id", queued["run_id"], "--output", "json"]).stdout)
    if run.get("runId") != queued["run_id"] or run.get("status") not in {"Queued", "Started", "Running", "Succeeded", "Failed", "Canceled", "Error", "Timeout"}:
        raise ValueError("actual task status required")
    image = None
    if run["status"] == "Succeeded":
        repository_tag = job["image_tag"].split("/", 1)[1]
        metadata = json.loads(azure(["acr", "repository", "show", "--name", registry, "--subscription", f["subscription_id"],
                                    "--image", repository_tag, "--output", "json"]).stdout)
        digest = metadata.get("digest", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("actual registry manifest digest required")
        repository, tag = repository_tag.rsplit(":", 1)
        outputs = [item for item in run.get("outputImages", []) if item.get("registry") == f["registry_server"]
                   and item.get("repository") == repository and item.get("tag") == tag and item.get("digest") == digest]
        if len(outputs) != 1:
            raise ValueError("successful run and registry image digest disagree")
        image = f["registry_server"] + "/" + repository + "@" + digest
    result = {"contract_version": "enrollment-image-receipt.v1", "source_commit": m["source_commit"], "kind": kind,
              "run_id": queued["run_id"], "status": run["status"], "image": image, "context_sha256": job["context_sha256"],
              "buildkit": True, "image_validation_passed": bool(image), "trivy_passed": bool(image),
              "pushed_verified": bool(image), "deployed": False, "hosted_journey_qualified": False}
    if not receipt.is_absolute() or receipt.is_relative_to(directory / kind):
        raise ValueError("receipt must stay outside uploaded context")
    write(receipt, result)
    return {"status": run["status"], "pushed_verified": bool(image), "digest_recorded": bool(image), "deployed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    for name in ("source", "public-config", "foundation", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--secret-file", type=Path, action="append", required=True)
    for command in ("queue", "collect"):
        p = commands.add_parser(command)
        p.add_argument("--prepared", type=Path, required=True)
        p.add_argument("--kind", choices=("api", "account"), required=True)
        if command == "collect":
            p.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.source, args.commit, args.public_config, args.foundation, args.secret_file, args.output)
        elif args.command == "queue":
            result = queue(args.prepared, args.kind)
        else:
            result = collect(args.prepared, args.kind, args.receipt)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        # Neither CLI stderr nor exception messages may expose protected input.
        print(json.dumps({"error": "enrollment_image_build_failed", "class": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
