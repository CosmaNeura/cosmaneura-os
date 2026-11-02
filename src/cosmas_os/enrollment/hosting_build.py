"""Automatic public-only, exact-source web build with actual ACR security gates."""
from __future__ import annotations

import hashlib
import io
import re
import shlex
import shutil
import tarfile
from pathlib import Path

from .hosting import GOOGLE_SECRET_NAMES, canonical


def build_allocated_web(backend, state: dict) -> str:
    config, d = backend.config, state["deployment"]
    plan, account = d["practice"]["plan"], config.account
    google = d.get("google")
    feature_profile = "standalone-practice-v1"
    if google is not None:
        public_env, references = d["practice"]["api_env"], d["practice"]["secret_references"]
        vault = "kvca" + plan["practice_id"].replace("-", "")[:20]
        if (config.google is None or google != {name: config.google[name] for name in ("client_id", "callback_uri")}
                or google["callback_uri"] != account["api_origin"] + "/connections/google/callback"
                or any(public_env.get(name) != "true" for name in ("WORKSPACE_GOOGLE_CONNECTION_ENABLED", "WORKSPACE_GOOGLE_MESSAGE_ENABLED",
                                                                 "WORKSPACE_GOOGLE_CALENDAR_ENABLED", "GOOGLE_CONNECTION_BROKER_ENABLED"))
                or public_env.get("GOOGLE_CONNECTION_CLIENT_ID") != google["client_id"]
                or public_env.get("GOOGLE_CONNECTION_CALLBACK_URI") != google["callback_uri"]
                or public_env.get("GOOGLE_CONNECTION_BROKER_ORIGIN") != account["api_origin"]
                or public_env.get("GOOGLE_CONNECTION_RETURN_ORIGIN") != d["practice"]["web_origin"]
                or any(not re.fullmatch(re.escape("https://" + vault + ".vault.azure.net/secrets/" + secret + "/") + r"[a-f0-9]{32}",
                                        references.get(name, "")) for name, secret in GOOGLE_SECRET_NAMES.items())):
            raise ValueError("registered Google web UI requires the exact enabled runtime and both Box-only secret references")
        feature_profile = "independent-beta-v1"
    repository = config.foundation["registry_server"]
    registry = repository.split(".", 1)[0]
    tag = "allocated-workspace-web:" + d["operation_id"]
    image = repository + "/" + tag
    found = state.get("web_build", {})
    if found.get("image_digest"):
        return repository + "/allocated-workspace-web@sha256:" + found["image_digest"]
    assert backend.directory is not None
    context = backend.directory / "web-context"
    source = config.release["source_commit"]
    if context.exists() and not found:
        # Before the build journal is saved no queue call can have happened.
        # Discard an interrupted private extraction rather than queueing a
        # partial context or trusting stale files as selected release source.
        if context.is_symlink():
            raise ValueError("owned regular private build context required")
        shutil.rmtree(context)
    if not context.exists():
        commit = backend._command(["git", "-C", str(config.source), "rev-parse", "--verify", source + "^{commit}"]).decode().strip()
        if commit != source:
            raise ValueError("exact committed build source required")
        archive = backend._command(["git", "-C", str(config.source), "archive", "--format=tar", source], timeout=120, maximum=128_000_000)
        context.mkdir(mode=0o700)
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            for item in stream:
                path = Path(item.name)
                if path.is_absolute() or ".." in path.parts or not (item.isdir() or item.isfile()):
                    raise ValueError("only regular committed build files allowed")
                destination = context / path
                if item.isdir():
                    destination.mkdir(mode=0o755, parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                    content = stream.extractfile(item)
                    assert content is not None
                    with content:
                        destination.write_bytes(content.read())
                    destination.chmod(0o755 if item.mode & 0o111 else 0o644)
        ci = (context / ".github/workflows/synth-ci.yml").read_text()
        pins = set(re.findall(r"aquasec/trivy@sha256:[a-f0-9]{64}", ci))
        if len(pins) != 1:
            raise ValueError("one unchanged CI scanner digest required")
        profile = {"contract_version": "cosmas-allocated-web-image.v1", "source_commit": source,
                   "practice_id": plan["practice_id"], "box_id": plan["box_id"], "organization_id": plan["organization_id"],
                   "api_origin": plan["api_origin"], "workspace_url": plan["workspace_url"], "base_api_image": config.release["api_image"]}
        if google is not None:
            profile["google"] = google
        profile_raw = canonical(profile)
        proof = hashlib.sha256(profile_raw).hexdigest()
        (context / "allocated-web-profile.json").write_bytes(profile_raw)
        public = {"VITE_BUILD_SHA": source, "VITE_CLERK_PUBLISHABLE_KEY": account["publishable_key"],
                  "VITE_WORKSPACE_HOSTED_API_ORIGIN": plan["api_origin"], "VITE_WORKSPACE_WEB_ORIGIN": d["practice"]["web_origin"],
                  "VITE_WORKSPACE_ORGANIZATION_ID": plan["organization_id"], "VITE_WORKSPACE_DATA_MODE": "synthetic",
                  "VITE_WORKSPACE_FEATURE_PROFILE": feature_profile, "VITE_WORKSPACE_CAPTURE_MODE": "disabled",
                  "VITE_CAPTURE_UPLOAD_ORIGINS": "", "VITE_COSMANEURA_WEB_ORIGIN": "", "VITE_ENROLLMENT_API_BASE": account["api_origin"],
                  "VITE_MESSAGES_ENABLED": "true", "APP_IMAGE": config.release["api_image"]}
        arguments = ["-t", image, "-f", "infra/enrollment/allocated-workspace/Dockerfile.web"]
        for name, value in sorted(public.items()):
            arguments += ["--build-arg", name + "=" + value]
        arguments += ["."]
        code = ("import hashlib,json,pathlib,os;assert os.getuid()==10001;"
                "p=pathlib.Path('/app/allocated-web-profile.json').read_bytes();"
                "assert hashlib.sha256(p).hexdigest()==" + repr(proof) + ";"
                "v=json.loads(pathlib.Path('/app/practice-web/version.json').read_text());assert v['commit']==" + repr(source) + ";"
                "b=json.loads(pathlib.Path('/app/practice-web/cosmas-workspace-build.json').read_text());assert b['apiOrigin']==" + repr(plan["api_origin"]) + ";"
                "f=json.loads(pathlib.Path('/app/practice-web/cosmas-beta-features.json').read_text());"
                "assert f['organizationId']==" + repr(plan["organization_id"]) + ";"
                "assert f['profile']==" + repr(feature_profile) + ";"
                "assert f['platformAccess']=='disabled' and f['captureMode']=='disabled';"
                + ("assert all(n in f['enabledFlags'] for n in ['VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED','VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED','VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED']);" if google is not None else "") +
                "print('COSMAS_ALLOCATED_WEB_VALIDATED:" + proof + "')")
        recipe = {"version": "v1.1.0", "stepTimeout": 1800, "steps": [
            {"id": "build", "build": shlex.join(arguments), "env": ["DOCKER_BUILDKIT=1"]},
            {"id": "validate", "cmd": image + " -B -c " + shlex.quote(code), "entryPoint": "python", "when": ["build"], "timeout": 120},
            {"id": "scan", "cmd": next(iter(pins)) + " image --image-src docker --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --no-progress " + image,
             "when": ["validate"], "timeout": 900},
            {"id": "push", "push": [image], "when": ["scan"], "timeout": 600},
        ]}
        (context / "allocated-web-task.json").write_bytes(canonical(recipe))
        found = {"image": image, "profile_sha256": proof, "recipe_sha256": hashlib.sha256(canonical(recipe)).hexdigest(), "queue_intent": True}
        state["web_build"] = found
        backend._checkpoint(state)
    if "run_id" not in found:
        # A lost queue reply must not blindly start another run. Resolve its
        # exact stable output tag from ACR; a still-unidentified run stays queued.
        if found.get("queue_sent"):
            runs = backend._json(["az", "acr", "task", "list-runs", "--registry", registry, "--top", "100", "--output", "json"])
            matched = [run for run in runs if any(item.get("repository") == "allocated-workspace-web" and item.get("tag") == d["operation_id"]
                       for item in run.get("outputImages", []))]
            if len(matched) != 1:
                raise RuntimeError("exact public web build handle remains unresolved; no duplicate was queued")
            found["run_id"] = matched[0]["runId"]
        else:
            found["queue_sent"] = True
            backend._checkpoint(state)
            run = backend._json(["az", "acr", "run", "--registry", registry, "--file", "allocated-web-task.json", "--no-logs", "--output", "json", str(context)], timeout=2400)
            found["run_id"] = run["runId"]
        backend._checkpoint(state)
    for _ in range(120):
        run = backend._json(["az", "acr", "task", "show-run", "--registry", registry, "--run-id", found["run_id"], "--output", "json"])
        if run.get("status") == "Succeeded":
            break
        if run.get("status") in {"Failed", "Canceled", "Error", "Timeout"}:
            raise RuntimeError("exact public web image build failed; retain its handle")
        backend.sleep(15)
    else:
        raise RuntimeError("exact public web image build remains pending")
    logs = backend._command(["az", "acr", "task", "logs", "--registry", registry, "--run-id", found["run_id"]], timeout=60).decode()
    for step in ("validate", "scan", "push"):
        if not re.search(r"Step ID: " + step + r".*marked as successful", logs):
            raise ValueError("actual ACR validation/scanner/push step did not pass")
    if "COSMAS_ALLOCATED_WEB_VALIDATED:" + found["profile_sha256"] not in logs:
        raise ValueError("actual image validation differs from exact source/practice profile")
    outputs = [item for item in run.get("outputImages", []) if item.get("repository") == "allocated-workspace-web" and item.get("tag") == d["operation_id"]]
    if len(outputs) != 1 or not re.fullmatch(r"sha256:[a-f0-9]{64}", outputs[0].get("digest", "")):
        raise ValueError("actual image output digest missing")
    digest = outputs[0]["digest"]
    for selected in (tag, "allocated-workspace-web@" + digest):
        backend._command(["az", "acr", "repository", "update", "--name", registry, "--image", selected,
                          "--write-enabled", "false", "--delete-enabled", "false", "--output", "none"])
        attributes = backend._json(["az", "acr", "repository", "show", "--name", registry, "--image", selected, "--output", "json"])["changeableAttributes"]
        if attributes.get("writeEnabled") is not False or attributes.get("deleteEnabled") is not False:
            raise ValueError("actual web tag/digest lock missing")
    found["image_digest"] = digest.removeprefix("sha256:")
    found["actual_validation_passed"] = found["actual_trivy_passed"] = True
    backend._checkpoint(state)
    return repository + "/allocated-workspace-web@" + digest
