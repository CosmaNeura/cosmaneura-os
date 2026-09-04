#!/usr/bin/env python3
"""Exact-digest rollback/forward acceptance for the protected D3 runner.

The state file is private and resumable. Standard output is a single bounded,
self-hashed JSON record. No tag is accepted as an image reference.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID

ARM_API_VERSION = "2024-03-01"
STATE_CONTRACT = "cosmas-os-d3-release-recovery-state-v1"
EVIDENCE_CONTRACT = "cosmas-os-d3-release-recovery-acceptance-v1"
MAX_PRIVATE_FILE_BYTES = 256 * 1024

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
_RELEASE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
_RESOURCE_GROUP = re.compile(r"^[A-Za-z0-9._()\-]{1,90}$")
_BETA_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,18}[a-z0-9]$")
_REGISTRY = re.compile(r"^[a-z0-9]{5,50}\.azurecr\.io$")
_REVISION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$")


class RecoveryError(RuntimeError):
    """A fail-closed release recovery assertion failed."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...


class SubprocessRunner:
    def run(self, argv: Sequence[str]) -> CommandResult:
        completed = subprocess.run(  # noqa: S603 - validated argv; shell is never used
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class Release:
    source_sha: str
    release_id: str
    api_digest: str
    web_digest: str


@dataclass(frozen=True)
class Config:
    operation: Literal["rollback", "forward"]
    subscription_id: str
    resource_group: str
    beta_id: str
    registry: str
    runtime_identity_id: str
    web_identity_id: str
    api_ready_url: str
    web_health_url: str
    current: Release
    prior: Release
    approval_sha256: str
    rollback_state_sha256: str | None
    state_path: Path
    poll_attempts: int
    poll_interval_seconds: int

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> Config:
        def required(name: str) -> str:
            value = environment.get(name, "")
            if not value or value != value.strip() or any(c in value for c in "\r\n\x00"):
                raise RecoveryError("release recovery configuration invalid")
            return value

        operation = required("COSMAS_RECOVERY_OPERATION")
        if operation not in {"rollback", "forward"}:
            raise RecoveryError("release recovery configuration invalid")
        subscription_id = required("COSMAS_RECOVERY_SUBSCRIPTION_ID").lower()
        resource_group = required("COSMAS_RECOVERY_RESOURCE_GROUP")
        beta_id = required("COSMAS_RECOVERY_BETA_ID")
        registry = required("COSMAS_RECOVERY_REGISTRY").lower()
        runtime_identity_id = required("COSMAS_RECOVERY_RUNTIME_IDENTITY_ID")
        web_identity_id = required("COSMAS_RECOVERY_WEB_IDENTITY_ID")
        api_ready_url = required("COSMAS_RECOVERY_API_READY_URL")
        web_health_url = required("COSMAS_RECOVERY_WEB_HEALTH_URL")
        approval_sha256 = required("COSMAS_RECOVERY_APPROVAL_SHA256")
        rollback_state_sha256 = environment.get(
            "COSMAS_RECOVERY_ROLLBACK_STATE_SHA256", ""
        )
        state_path = Path(required("COSMAS_RECOVERY_STATE_PATH"))

        current = Release(
            source_sha=required("COSMAS_RECOVERY_CURRENT_SOURCE_SHA"),
            release_id=required("COSMAS_RECOVERY_CURRENT_RELEASE_ID"),
            api_digest=required("COSMAS_RECOVERY_CURRENT_API_DIGEST"),
            web_digest=required("COSMAS_RECOVERY_CURRENT_WEB_DIGEST"),
        )
        prior = Release(
            source_sha=required("COSMAS_RECOVERY_PRIOR_SOURCE_SHA"),
            release_id=required("COSMAS_RECOVERY_PRIOR_RELEASE_ID"),
            api_digest=required("COSMAS_RECOVERY_PRIOR_API_DIGEST"),
            web_digest=required("COSMAS_RECOVERY_PRIOR_WEB_DIGEST"),
        )
        if (
            not _UUID.fullmatch(subscription_id)
            or str(UUID(subscription_id)) != subscription_id
            or not _RESOURCE_GROUP.fullmatch(resource_group)
            or not _BETA_ID.fullmatch(beta_id)
            or not _REGISTRY.fullmatch(registry)
            or not _SHA256.fullmatch(approval_sha256)
            or (
                operation == "rollback"
                and rollback_state_sha256 != ""
            )
            or (
                operation == "forward"
                and not _SHA256.fullmatch(rollback_state_sha256)
            )
            or not state_path.is_absolute()
            or current.source_sha == prior.source_sha
            or current.release_id == prior.release_id
            or current.api_digest == prior.api_digest
            or current.web_digest == prior.web_digest
        ):
            raise RecoveryError("release recovery configuration invalid")
        for release in (current, prior):
            if (
                not _SOURCE_SHA.fullmatch(release.source_sha)
                or not _RELEASE.fullmatch(release.release_id)
                or not _DIGEST.fullmatch(release.api_digest)
                or not _DIGEST.fullmatch(release.web_digest)
            ):
                raise RecoveryError("release recovery configuration invalid")

        expected_prefix = (
            f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/"
        ).lower()
        if (
            not runtime_identity_id.lower().startswith(expected_prefix)
            or not web_identity_id.lower().startswith(expected_prefix)
            or runtime_identity_id.lower() == web_identity_id.lower()
        ):
            raise RecoveryError("release recovery configuration invalid")
        _validate_url(api_ready_url, "/ready")
        _validate_url(web_health_url, "/healthz")
        try:
            attempts = int(environment.get("COSMAS_RECOVERY_POLL_ATTEMPTS", "60"))
            interval = int(environment.get("COSMAS_RECOVERY_POLL_INTERVAL_SECONDS", "10"))
        except ValueError:
            raise RecoveryError("release recovery configuration invalid") from None
        if not 1 <= attempts <= 90 or not 0 <= interval <= 30:
            raise RecoveryError("release recovery configuration invalid")
        return cls(
            operation=operation,  # type: ignore[arg-type]
            subscription_id=subscription_id,
            resource_group=resource_group,
            beta_id=beta_id,
            registry=registry,
            runtime_identity_id=runtime_identity_id,
            web_identity_id=web_identity_id,
            api_ready_url=api_ready_url,
            web_health_url=web_health_url,
            current=current,
            prior=prior,
            approval_sha256=approval_sha256,
            rollback_state_sha256=(
                rollback_state_sha256 if operation == "forward" else None
            ),
            state_path=state_path,
            poll_attempts=attempts,
            poll_interval_seconds=interval,
        )


def _validate_url(value: str, required_path: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.path != required_path
        or parsed.query
        or parsed.fragment
    ):
        raise RecoveryError("release recovery configuration invalid")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        raise RecoveryError("release recovery timestamp invalid")
    return now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resource_id(config: Config, kind: str) -> str:
    return (
        f"/subscriptions/{config.subscription_id}/resourceGroups/{config.resource_group}/"
        f"providers/Microsoft.App/containerApps/ca-{kind}-cosmas-beta-{config.beta_id}"
    )


def _image(config: Config, kind: str, release: Release) -> str:
    repository = "cosmas-os-web" if kind == "web" else "cosmas-os"
    digest = release.web_digest if kind == "web" else release.api_digest
    return f"{config.registry}/{repository}@{digest}"


def _arm_url(resource_id: str, *, revisions: bool = False) -> str:
    suffix = "/revisions" if revisions else ""
    return f"https://management.azure.com{resource_id}{suffix}?api-version={ARM_API_VERSION}"


def _az_json(runner: CommandRunner, argv: Sequence[str]) -> dict[str, Any]:
    result = runner.run(argv)
    if result.returncode != 0:
        raise RecoveryError("Azure release recovery operation failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RecoveryError("Azure release recovery response invalid") from None
    if not isinstance(value, dict):
        raise RecoveryError("Azure release recovery response invalid")
    return value


def _az_get(runner: CommandRunner, resource_id: str, *, revisions: bool = False) -> dict[str, Any]:
    return _az_json(
        runner,
        [
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            _arm_url(resource_id, revisions=revisions),
            "--only-show-errors",
            "--output",
            "json",
        ],
    )


def _required_private_file(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    info = resolved.stat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
        or not 0 < info.st_size <= MAX_PRIVATE_FILE_BYTES
    ):
        raise RecoveryError("release recovery state invalid")
    return resolved


def _write_state(path: Path, value: dict[str, Any]) -> None:
    if not path.is_absolute():
        raise RecoveryError("release recovery state invalid")
    parent = path.parent.resolve(strict=True)
    info = parent.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RecoveryError("release recovery state invalid")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(value))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _binding(config: Config) -> dict[str, Any]:
    return {
        "subscription_id": config.subscription_id,
        "resource_group": config.resource_group,
        "beta_id": config.beta_id,
        "registry": config.registry,
        "runtime_identity_id": config.runtime_identity_id.lower(),
        "web_identity_id": config.web_identity_id.lower(),
        "api_ready_url": config.api_ready_url,
        "web_health_url": config.web_health_url,
        "current": vars(config.current),
        "prior": vars(config.prior),
    }


def _read_state(config: Config) -> dict[str, Any]:
    source = _required_private_file(config.state_path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RecoveryError("release recovery state invalid") from None
    if not isinstance(value, dict) or value.get("contract") != STATE_CONTRACT:
        raise RecoveryError("release recovery state invalid")
    expected = value.get("state_sha256")
    payload = {key: item for key, item in value.items() if key != "state_sha256"}
    if (
        not isinstance(expected, str)
        or not hmac.compare_digest(expected, _sha256_json(payload))
        or value.get("binding") != _binding(config)
    ):
        raise RecoveryError("release recovery state invalid")
    return value


def _save_state(config: Config, state: dict[str, Any]) -> None:
    payload = {key: value for key, value in state.items() if key != "state_sha256"}
    _write_state(config.state_path, {**payload, "state_sha256": _sha256_json(payload)})


def _identity_id(app: dict[str, Any]) -> str:
    identity = app.get("identity")
    if not isinstance(identity, dict) or identity.get("type") != "UserAssigned":
        raise RecoveryError("Container App identity boundary invalid")
    identities = identity.get("userAssignedIdentities")
    if not isinstance(identities, dict) or len(identities) != 1:
        raise RecoveryError("Container App identity boundary invalid")
    return str(next(iter(identities))).lower()


def _configuration_hash(app: dict[str, Any]) -> str:
    properties = copy.deepcopy(app.get("properties"))
    if not isinstance(properties, dict):
        raise RecoveryError("Container App configuration invalid")
    template = properties.get("template")
    if not isinstance(template, dict) or not isinstance(template.get("containers"), list):
        raise RecoveryError("Container App configuration invalid")
    template.pop("revisionSuffix", None)
    for container in template["containers"]:
        if not isinstance(container, dict):
            raise RecoveryError("Container App configuration invalid")
        container.pop("image", None)
    stable = {
        "identity": app.get("identity"),
        "tags": app.get("tags"),
        "configuration": properties.get("configuration"),
        "template": template,
    }
    return _sha256_json(stable)


def _validate_route(config: Config, kind: str, app: dict[str, Any]) -> None:
    configuration = app["properties"].get("configuration")
    if not isinstance(configuration, dict) or configuration.get("activeRevisionsMode") != "Single":
        raise RecoveryError("Container App route invalid")
    ingress = configuration.get("ingress")
    if kind == "worker":
        if ingress is not None and ingress != {}:
            raise RecoveryError("worker unexpectedly exposes ingress")
        return
    if not isinstance(ingress, dict):
        raise RecoveryError("Container App route invalid")
    expected_port = 8080 if kind == "web" else 8000
    traffic = ingress.get("traffic")
    if (
        ingress.get("external") is not True
        or ingress.get("allowInsecure") is not False
        or ingress.get("targetPort") != expected_port
        or not isinstance(traffic, list)
        or len(traffic) != 1
        or traffic[0].get("weight") != 100
        or traffic[0].get("label") not in {None, ""}
        or traffic[0].get("latestRevision") is not True
        or traffic[0].get("revisionName") not in {None, ""}
    ):
        raise RecoveryError("Container App route invalid")
    fqdn = str(ingress.get("fqdn", "")).lower()
    health_url = config.web_health_url if kind == "web" else config.api_ready_url
    health_host = (urlsplit(health_url).hostname or "").lower()
    custom_domains = ingress.get("customDomains") or []
    custom_names = {
        str(item.get("name", "")).lower()
        for item in custom_domains
        if isinstance(item, dict)
    }
    if health_host != fqdn and health_host not in custom_names:
        raise RecoveryError("health route is not bound to the exact Container App")


def _validate_topology(
    config: Config,
    topology: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    release: Release,
    *,
    baseline_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    revision_ids: dict[str, str] = {}
    configuration_hashes: dict[str, str] = {}
    for kind in ("api", "worker", "web"):
        app, revisions = topology[kind]
        resource_id = _resource_id(config, kind)
        expected_image = _image(config, kind, release)
        expected_identity = config.web_identity_id if kind == "web" else config.runtime_identity_id
        properties = app.get("properties")
        tags = app.get("tags")
        if not isinstance(properties, dict) or not isinstance(tags, dict):
            raise RecoveryError("Container App binding invalid")
        template = properties.get("template")
        containers = template.get("containers") if isinstance(template, dict) else None
        registries = properties.get("configuration", {}).get("registries")
        if (
            str(app.get("id", "")).lower() != resource_id.lower()
            or _identity_id(app) != expected_identity.lower()
            or tags.get("track") != "B"
            or tags.get("env") != "early_adopter_beta"
            or tags.get("deployment_mode") != "synthetic_lab"
            or tags.get("data_classification") != "synthetic-only"
            or not isinstance(containers, list)
            or len(containers) != 1
            or containers[0].get("name") != kind
            or containers[0].get("image") != expected_image
            or not isinstance(registries, list)
            or len(registries) != 1
            or str(registries[0].get("server", "")).lower() != config.registry
            or str(registries[0].get("identity", "")).lower() != expected_identity.lower()
            or properties.get("provisioningState") != "Succeeded"
        ):
            raise RecoveryError("Container App binding invalid")
        latest = properties.get("latestRevisionName")
        ready = properties.get("latestReadyRevisionName")
        if not isinstance(latest, str) or latest != ready or not _REVISION_NAME.fullmatch(latest):
            raise RecoveryError("Container App readiness invalid")
        values = revisions.get("value")
        if not isinstance(values, list):
            raise RecoveryError("Container App revision response invalid")
        active = [item for item in values if isinstance(item, dict) and item.get("properties", {}).get("active") is True]
        if len(active) != 1:
            raise RecoveryError("Container App active revision set invalid")
        revision = active[0]
        revision_properties = revision.get("properties")
        if not isinstance(revision_properties, dict):
            raise RecoveryError("Container App active revision is invalid")
        revision_containers = (
            revision_properties.get("template", {}).get("containers")
            if isinstance(revision_properties.get("template"), dict)
            else None
        )
        minimum_replicas = 0 if kind == "web" else 1
        if (
            revision.get("name") != latest
            or str(revision.get("id", "")).lower()
            != f"{resource_id}/revisions/{latest}".lower()
            or not isinstance(revision_containers, list)
            or len(revision_containers) != 1
            or revision_containers[0].get("name") != kind
            or revision_containers[0].get("image") != expected_image
            or revision_properties.get("healthState") != "Healthy"
            or revision_properties.get("provisioningState") != "Provisioned"
            or not isinstance(revision_properties.get("replicas", 0), int)
            or revision_properties.get("replicas", 0) < minimum_replicas
        ):
            raise RecoveryError("Container App active revision is not healthy at the exact digest")
        _validate_route(config, kind, app)
        configuration_hashes[kind] = _configuration_hash(app)
        if baseline_hashes is not None and not hmac.compare_digest(
            configuration_hashes[kind], baseline_hashes.get(kind, "")
        ):
            raise RecoveryError("Container App configuration drifted during release recovery")
        revision_ids[kind] = str(revision["id"])
    return {
        "revision_ids": revision_ids,
        "configuration_sha256": configuration_hashes,
        "routes_verified": True,
        "revisions_healthy": True,
    }


def _get_topology(config: Config, runner: CommandRunner) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    return {
        kind: (
            _az_get(runner, _resource_id(config, kind)),
            _az_get(runner, _resource_id(config, kind), revisions=True),
        )
        for kind in ("api", "worker", "web")
    }


def _current_image(app: dict[str, Any]) -> str:
    try:
        containers = app["properties"]["template"]["containers"]
        if not isinstance(containers, list) or len(containers) != 1:
            raise KeyError
        value = containers[0]["image"]
    except (KeyError, TypeError):
        raise RecoveryError("Container App image invalid") from None
    if not isinstance(value, str) or "@sha256:" not in value:
        raise RecoveryError("mutable Container App image is forbidden")
    return value


def _patch_image(config: Config, runner: CommandRunner, kind: str, app: dict[str, Any], image: str) -> None:
    if not image.startswith(f"{config.registry}/") or re.search(r"@sha256:[0-9a-f]{64}$", image) is None:
        raise RecoveryError("mutable Container App image is forbidden")
    properties = app.get("properties")
    template = copy.deepcopy(properties.get("template")) if isinstance(properties, dict) else None
    if not isinstance(template, dict) or not isinstance(template.get("containers"), list):
        raise RecoveryError("Container App template invalid")
    containers = template["containers"]
    if len(containers) != 1 or containers[0].get("name") != kind:
        raise RecoveryError("Container App template invalid")
    template.pop("revisionSuffix", None)
    containers[0]["image"] = image
    parent = config.state_path.parent.resolve(strict=True)
    descriptor, request_name = tempfile.mkstemp(prefix=f".recovery-{kind}.", suffix=".json", dir=parent)
    request = Path(request_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json({"properties": {"template": template}}))
        result = runner.run(
            [
                "az",
                "rest",
                "--method",
                "patch",
                "--url",
                _arm_url(_resource_id(config, kind)),
                "--body",
                f"@{request}",
                "--only-show-errors",
                "--output",
                "none",
            ]
        )
    finally:
        request.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RecoveryError("Container App exact-digest update failed")


def _probe_health(config: Config, runner: CommandRunner) -> None:
    for kind, url, expected in (
        ("api", config.api_ready_url, {"status": "ready", "env": "early_adopter_beta"}),
        ("web", config.web_health_url, "ok"),
    ):
        result = runner.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--fail",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--max-time",
                "30",
                url,
            ]
        )
        if result.returncode != 0 or len(result.stdout.encode()) > 4096:
            raise RecoveryError(f"{kind} readiness probe failed")
        if kind == "api":
            try:
                actual = json.loads(result.stdout)
            except json.JSONDecodeError:
                raise RecoveryError("API readiness response invalid") from None
            if actual != expected:
                raise RecoveryError("API readiness response invalid")
        elif result.stdout.strip() != expected:
            raise RecoveryError("web health response invalid")


def _wait_for_release(
    config: Config,
    runner: CommandRunner,
    release: Release,
    baseline_hashes: Mapping[str, str],
) -> dict[str, Any]:
    for attempt in range(config.poll_attempts):
        try:
            topology = _get_topology(config, runner)
            result = _validate_topology(
                config, topology, release, baseline_hashes=baseline_hashes
            )
            _probe_health(config, runner)
            return result
        except RecoveryError:
            if attempt + 1 == config.poll_attempts:
                raise
            time.sleep(config.poll_interval_seconds)
    raise RecoveryError("release recovery did not converge")


def _transition(
    config: Config,
    runner: CommandRunner,
    source: Release,
    target: Release,
    baseline_hashes: Mapping[str, str],
) -> dict[str, Any]:
    for kind in ("api", "worker", "web"):
        app = _az_get(runner, _resource_id(config, kind))
        actual = _current_image(app)
        source_image = _image(config, kind, source)
        target_image = _image(config, kind, target)
        if actual == target_image:
            continue
        if actual != source_image:
            raise RecoveryError("live image is outside the approved recovery pair")
        if not hmac.compare_digest(_configuration_hash(app), baseline_hashes.get(kind, "")):
            raise RecoveryError("Container App configuration drifted before recovery update")
        _patch_image(config, runner, kind, app, target_image)
    return _wait_for_release(config, runner, target, baseline_hashes)


def _new_state(config: Config, baseline: dict[str, Any], now: datetime) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract": STATE_CONTRACT,
        "phase": "rollback_requested",
        "created_at": _timestamp(now),
        "binding": _binding(config),
        "rollback_authorizations": [
            {"approval_sha256": config.approval_sha256},
        ],
        "forward_authorizations": [],
        "baseline": baseline,
        "rollback": None,
        "forward": None,
    }


def run_recovery(
    config: Config,
    runner: CommandRunner,
    *,
    now: datetime,
) -> dict[str, Any]:
    if config.operation == "rollback":
        if config.state_path.exists() or config.state_path.is_symlink():
            state = _read_state(config)
            if state.get("phase") not in {"rollback_requested", "rolled_back"}:
                raise RecoveryError("release recovery phase invalid")
        else:
            topology = _get_topology(config, runner)
            baseline = _validate_topology(config, topology, config.current)
            state = _new_state(config, baseline, now)
            _save_state(config, state)
            state = _read_state(config)
        rollback_authorization = {"approval_sha256": config.approval_sha256}
        rollback_authorizations = state.get("rollback_authorizations")
        if not isinstance(rollback_authorizations, list) or not rollback_authorizations:
            raise RecoveryError("release rollback authorization history invalid")
        if rollback_authorization in rollback_authorizations:
            if rollback_authorizations[-1] != rollback_authorization:
                raise RecoveryError("stale release rollback authorization replayed")
        else:
            rollback_authorizations.append(rollback_authorization)
            _save_state(config, state)
            state = _read_state(config)
        baseline_hashes = state["baseline"]["configuration_sha256"]
        result = _transition(config, runner, config.current, config.prior, baseline_hashes)
        state["phase"] = "rolled_back"
        state["rollback"] = {"completed_at": _timestamp(now), **result}
        _save_state(config, state)
        status = "rolled_back_healthy"
    else:
        state = _read_state(config)
        if state.get("phase") not in {
            "rolled_back",
            "forward_requested",
            "forwarded",
        }:
            raise RecoveryError("release recovery phase invalid")
        if not isinstance(state.get("rollback"), dict):
            raise RecoveryError("release rollback state incomplete")
        forward_authorization = {
            "approval_sha256": config.approval_sha256,
            "rollback_state_sha256": config.rollback_state_sha256,
        }
        forward_authorization_changed = False
        if state.get("phase") == "rolled_back":
            if not hmac.compare_digest(
                str(state.get("state_sha256", "")),
                str(config.rollback_state_sha256),
            ):
                raise RecoveryError("forward authorization targets a different rollback state")
            state["forward_authorizations"] = [forward_authorization]
            forward_authorization_changed = True
        else:
            authorizations = state.get("forward_authorizations")
            if (
                not isinstance(authorizations, list)
                or not authorizations
                or any(
                    not isinstance(item, dict)
                    or item.get("rollback_state_sha256")
                    != config.rollback_state_sha256
                    for item in authorizations
                )
            ):
                raise RecoveryError("release forward authorization history invalid")
            if forward_authorization in authorizations:
                if authorizations[-1] != forward_authorization:
                    raise RecoveryError("stale release forward authorization replayed")
            else:
                authorizations.append(forward_authorization)
                forward_authorization_changed = True
        baseline_hashes = state["baseline"]["configuration_sha256"]
        if state.get("phase") != "forwarded":
            state["phase"] = "forward_requested"
            forward_authorization_changed = True
        if forward_authorization_changed:
            _save_state(config, state)
        result = _transition(config, runner, config.prior, config.current, baseline_hashes)
        state["phase"] = "forwarded"
        state["forward"] = {"completed_at": _timestamp(now), **result}
        _save_state(config, state)
        status = "forward_restored_healthy"

    saved = _read_state(config)
    payload = {
        "schema_version": 1,
        "contract": EVIDENCE_CONTRACT,
        "operation": config.operation,
        "status": status,
        "completed_at": _timestamp(now),
        "current": vars(config.current),
        "prior": vars(config.prior),
        "approval_sha256": config.approval_sha256,
        "rollback_state_sha256": (
            config.rollback_state_sha256
            if config.operation == "forward"
            else saved["state_sha256"]
        ),
        "baseline_revision_ids": saved["baseline"]["revision_ids"],
        "result_revision_ids": result["revision_ids"],
        "route_binding_verified": result["routes_verified"],
        "readiness_verified": result["revisions_healthy"],
        "public_health_verified": True,
        "configuration_unchanged_except_exact_digest": True,
        "mutable_tags_used": False,
        "state_sha256": saved["state_sha256"],
    }
    return {**payload, "evidence_sha256": _sha256_json(payload)}


def main() -> int:
    try:
        config = Config.from_environment(os.environ)
        evidence = run_recovery(config, SubprocessRunner(), now=datetime.now(UTC))
    except Exception:  # noqa: BLE001 - never reflect Azure or private-state details
        print(_canonical_json({"contract": EVIDENCE_CONTRACT, "status": "failed"}))
        return 1
    print(_canonical_json(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
