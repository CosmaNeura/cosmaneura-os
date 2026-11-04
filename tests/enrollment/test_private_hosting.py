"""Private allocator failure/recovery boundaries; invented provider data only."""
import base64
import importlib.util
import io
import json
import re
import shlex
import stat
import subprocess
import tarfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4, uuid5

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from cosmas_os.adapters.gpt41 import ENDPOINT, GPT41Connector
from cosmas_os.config import Settings
from cosmas_os.enrollment.allocation import WorkspaceAllocationRequest
from cosmas_os.enrollment.domain import (
    BAA_DOC_ID,
    BAA_SHA256,
    BAA_VERSION,
    EnrollmentError,
    HumanIdentity,
)
from cosmas_os.enrollment.hosting import (
    GOOGLE_SECRET_NAMES,
    MODEL_SECRET_NAMES,
    REVIEWED_MODEL,
    SECRET_NAMES,
    HostingConfiguration,
    OpenTofuWorkspaceAllocator,
    box_admission_key,
    box_google_custody_key,
    canonical,
)
from cosmas_os.enrollment.hosting_build import build_allocated_web
from cosmas_os.enrollment.hosting_cloud import AzureAllocationBackend
from cosmas_os.enrollment.hosting_dns import bind_allocated_dns
from cosmas_os.enrollment.migration import upgrade
from cosmas_os.enrollment.models import Membership, Practice
from cosmas_os.enrollment.provisioning import BOX_NAMESPACE, WorkspacePlan
from cosmas_os.enrollment.service import EnrollmentService
from cosmas_os.enrollment.synthetic import SyntheticCommerce, synthetic_settings
from cosmas_os.ports.bot_capabilities import BotContext

ENVIRONMENT_FIXTURE = {
    "staging": {"issuer": "https://hosting-fixture.clerk.accounts.dev", "key": "pk_test_", "short": "stg",
                "app": "https://onboarding.staging.cosmas.ai", "api": "https://enrollment-api.staging.cosmas.ai"},
    "production": {"issuer": "https://clerk.cosmas.ai", "key": "pk_live_", "short": "prd",
                   "app": "https://app.cosmas.ai", "api": "https://enrollment-api.cosmas.ai"},
}


@pytest.fixture
def hosted(tmp_path):
    yield from _hosted(tmp_path, "staging")


@pytest.fixture
def production_hosted(tmp_path):
    yield from _hosted(tmp_path, "production")


def _hosted(tmp_path, environment):
    e = ENVIRONMENT_FIXTURE[environment]
    source = Path(__file__).resolve().parents[2]
    settings = synthetic_settings()
    settings.clerk_issuer = e["issuer"]
    settings.clerk_publishable_key = e["key"] + base64.b64encode((e["issuer"][8:] + "$").encode()).decode()
    settings.native_account_enabled = True
    settings.native_authorized_origins = ["capacitor://localhost", "app://cosmas"]
    settings.workspace_allocation_enabled = True
    settings.provisioning_enabled = True
    settings.database_url = SecretStr("sqlite:///" + str(tmp_path / "registry.db"))
    engine = create_engine(settings.database_url.get_secret_value())
    upgrade(engine)
    service = EnrollmentService(sessionmaker(engine, expire_on_commit=False), settings, SyntheticCommerce(settings))
    human = HumanIdentity(settings.clerk_issuer, "user_host1", "sess_host1", "owner@example.invalid", "Invented Owner")
    service.profile(human, str(uuid4()), {"expected_revision": 0, "display_name": "Invented Owner", "title": "Owner"})
    service.practice(human, str(uuid4()), {"expected_revision": service.status(human)["revision"], "legal_name": "Invented Practice LLC",
        "display_name": "Invented Practice", "address_line1": "123 Invented Street", "address_line2": "", "city": "Invented City",
        "region": "NY", "postal_code": "10001", "country": "US", "administrative_email": "office@example.invalid",
        "human_seats": 1, "covered_entity": True})
    service.accept(human, str(uuid4()), {"expected_revision": service.status(human)["revision"], "doc_id": BAA_DOC_ID,
        "version": BAA_VERSION, "sha256": BAA_SHA256, "signature_name": "Invented Owner", "signature_title": "Owner",
        "authority_confirmed": True, "accepted": True})
    practice = service.status(human)["practice"]["id"]
    # Registration ran under the synthetic fixture; allocation runs in the selected environment.
    settings.data_mode = "production" if environment == "production" else "synthetic"
    box, org = str(uuid5(BOX_NAMESPACE, practice)), "org_host1"
    subscription, tenant = str(uuid4()), str(uuid4())
    group, registry = f"rg-cosmabot-enrollment-{environment}-fixture1", f"acrcbotenr{e['short']}fixture1.azurecr.io"
    scope = f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
    foundation = {"contract_version": "enrollment-foundation.v1", "environment": environment, "subscription_id": subscription,
        "tenant_id": tenant, "resource_group_name": group, "location": "eastus2", "registry_server": registry,
        "vnet_id": scope + "Microsoft.Network/virtualNetworks/owned", "container_app_environment_id": scope + "Microsoft.App/managedEnvironments/owned",
        "container_registry_id": scope + "Microsoft.ContainerRegistry/registries/" + registry.split(".")[0],
        "postgres_subnet_id": scope + "Microsoft.Network/virtualNetworks/owned/subnets/postgres",
        "private_endpoint_subnet_id": scope + "Microsoft.Network/virtualNetworks/owned/subnets/endpoints",
        **{kind + "_private_dns_zone_id": scope + "Microsoft.Network/privateDnsZones/" + name for kind, name in
           (("vault", "privatelink.vaultcore.azure.net"), ("blob", "privatelink.blob.core.windows.net"), ("redis", "privatelink.redis.azure.net"))},
        "state_backend": {"resource_group_name": group, "storage_account_name": f"stcbotenr{e['short']}fixture1", "container_name": "enrollment-runtime-state", "use_azuread_auth": True}}
    token = tmp_path / "invented-dns-token"
    token.write_text("invented-provider-boundary-only")
    token.chmod(0o600)
    value = {"contract_version": "cosmas-private-hosting.v1", "enabled": True, "synthetic_only": environment == "staging",
        "foundation": foundation, "account": {"app_origin": e["app"],
            "api_origin": e["api"], "issuer": settings.clerk_issuer,
            "publishable_key": settings.clerk_publishable_key, "audience": settings.clerk_audience},
        "release": {"source_commit": "2" * 40, "api_image": registry + "/api@sha256:" + "3" * 64,
                    "job_image": registry + "/allocated-job@sha256:" + "4" * 64},
        "worker_client_id": str(uuid4()), "worker_object_id": str(uuid4()), "source_repository": str(source),
        "state_root": str(tmp_path / "owned-worker-state"), "cloudflare_zone_id": "5" * 32,
        "cloudflare_token_file": str(token), "native_origins": settings.native_authorized_origins}
    config = HostingConfiguration(value)
    allocator = OpenTofuWorkspaceAllocator(service, config)
    destination = allocator.destination(WorkspaceAllocationRequest(practice, box, "unused", human.subject, human.issuer))
    service.record_workspace(practice, box_id=box, organization_id=org, url=destination.workspace_url, proof_sha256="1" * 64,
        status="provisioning", workspace_api_origin=destination.api_origin, source_commit=destination.source_commit,
        image_sha256=destination.image_sha256)
    plan = WorkspacePlan(practice, box, org, human.subject, human.issuer, destination.api_origin,
        destination.workspace_url, destination.source_commit, destination.image_sha256)
    operation = str(uuid4())
    yield SimpleNamespace(config=config, value=value, allocator=allocator, service=service, plan=plan, operation=operation,
        deployment=allocator._deployment(plan, operation), source=source, scope=scope)
    engine.dispose()


def test_hosting_destination_and_public_runtime_are_registered_native_and_separate(hosted):
    c = hosted
    destination = c.allocator.destination(WorkspaceAllocationRequest(c.plan.practice_id, c.plan.box_id, "unused", c.plan.owner_subject, c.plan.issuer))
    assert destination.api_origin == c.plan.api_origin and destination.workspace_url == c.plan.workspace_url
    public = c.deployment["practice"]["api_env"]
    assert public["WORKSPACE_APPLE_HOSTED_TRANSPORT_ENABLED"] == public["WORKSPACE_DESKTOP_HOSTED_TRANSPORT_ENABLED"] == "true"
    assert public["BETA_BOX_ID"] == c.plan.box_id and public["CLERK_ORGANIZATION_ID"] == c.plan.organization_id
    assert not any("CORE" in name or "SECRET" in name or name in {"DATABASE_URL", "REDIS_URL"} for name in public)
    assert c.deployment["deploy_workloads"] is c.deployment["bind_domains"] is False
    key = box_admission_key(c.deployment, "invented-master-" + "0" * 64)
    assert len(key) == 64 and "invented" not in key


def google_host(hosted, tmp_path):
    value = json.loads(json.dumps(hosted.value))
    secret = tmp_path / "invented-google-client-secret"
    secret.write_text("invented-client-secret-for-provider-boundary-only")
    secret.chmod(0o600)
    value["google"] = {"client_id": "invented-host.apps.googleusercontent.com",
                       "callback_uri": value["account"]["api_origin"] + "/connections/google/callback",
                       "client_secret_file": str(secret)}
    value["state_root"] = str(tmp_path / "google-worker-state")
    settings = hosted.service.settings
    settings.runtime_admission_secret = SecretStr("invented-host-master-" + "0" * 64)
    settings.google_callback_broker_enabled = True
    settings.google_callback_broker_origin = value["account"]["api_origin"]
    settings.google_callback_client_id = value["google"]["client_id"]
    config = HostingConfiguration(value)
    allocator = OpenTofuWorkspaceAllocator(hosted.service, config)
    return SimpleNamespace(config=config, allocator=allocator, deployment=allocator._deployment(hosted.plan, hosted.operation), secret=secret)


def box_references(deployment, names):
    vault = "kvca" + deployment["practice"]["plan"]["practice_id"].replace("-", "")[:20]
    return {name: "https://" + vault + ".vault.azure.net/secrets/" + secret + "/" + "1" * 32 for name, secret in names.items()}


def test_google_allocation_opt_in_preserves_default_plan_and_requires_matching_account_broker(hosted, tmp_path):
    optional = google_host(hosted, tmp_path)
    default = json.loads(json.dumps(optional.deployment))
    assert default.pop("google") == {name: optional.config.google[name] for name in ("client_id", "callback_uri")}
    added = {name: default["practice"]["api_env"].pop(name) for name in list(default["practice"]["api_env"])
             if name.startswith(("GOOGLE_", "WORKSPACE_GOOGLE_"))}
    assert default == hosted.deployment
    assert all(added[name] == "true" for name in ("WORKSPACE_GOOGLE_CONNECTION_ENABLED", "WORKSPACE_GOOGLE_MESSAGE_ENABLED",
                                               "WORKSPACE_GOOGLE_CALENDAR_ENABLED", "GOOGLE_CONNECTION_BROKER_ENABLED"))
    assert added["GOOGLE_CONNECTION_CALLBACK_URI"] == hosted.config.account["api_origin"] + "/connections/google/callback"
    assert added["GOOGLE_CONNECTION_RETURN_ORIGIN"] == hosted.deployment["practice"]["web_origin"]
    assert str(optional.secret).encode() not in canonical(optional.deployment)
    assert optional.secret.read_bytes() not in canonical(optional.deployment)
    settings = hosted.service.settings
    for name, bad in (("google_callback_broker_enabled", False), ("google_callback_client_id", "other.apps.googleusercontent.com"),
                      ("google_callback_broker_origin", "https://other.example.invalid")):
        saved = getattr(settings, name)
        setattr(settings, name, bad)
        with pytest.raises(EnrollmentError, match="Google broker configuration"):
            optional.allocator._deployment(hosted.plan, hosted.operation)
        setattr(settings, name, saved)
    for pair in (None, {}, {**optional.config.google, "client_id": ""},
                 {**optional.config.google, "callback_uri": hosted.plan.api_origin + "/connections/google/callback"},
                 {**optional.config.google, "client_secret_file": "relative-secret"},
                 {**optional.config.google, "client_secret_file": str(hosted.source / "unreviewed-secret")},
                 {**optional.config.google, "client_secret_file": str(hosted.source.parent / "decoy" / ".." / hosted.source.name / "unreviewed-secret")},
                 {**optional.config.google, "scope": "gmail.send"}):
        value = json.loads(json.dumps(optional.config.value))
        value["google"] = pair
        with pytest.raises(ValueError, match="Google broker"):
            HostingConfiguration(value)


def test_google_seed_keeps_custody_in_this_box_and_recovers_without_admin_or_redis_credentials(hosted, tmp_path):
    optional = google_host(hosted, tmp_path)
    backend = optional.allocator.backend
    state = backend._open(optional.deployment)
    refs = state["deployment"]["practice"]["secret_references"]
    refs.update(box_references(optional.deployment, SECRET_NAMES))
    vault = "kvca" + hosted.plan.practice_id.replace("-", "")[:20]
    state["resources"] = {"key_vault_id": hosted.scope + "Microsoft.KeyVault/vaults/" + vault}
    original_vault = state["resources"]["key_vault_id"]
    state["resources"]["key_vault_id"] = hosted.scope + "Microsoft.KeyVault/vaults/unrelated-vault"
    with pytest.raises(ValueError, match="this Box's own vault"):
        backend._seed(state, hosted.service.settings.runtime_admission_secret.get_secret_value())
    state["resources"]["key_vault_id"] = original_vault
    seeded, calls = {}, []
    def cli(arguments, **kwargs):
        calls.append(arguments)
        if arguments[:4] == ["az", "deployment", "group", "create"]:
            body = json.loads((backend.directory / "seed-parameters.json").read_text())
            assert body["vaultName"]["value"] == vault
            seeded[body["secretName"]["value"]] = body["secretValue"]["value"]
            reply = b""
        else:
            assert arguments[:3] == ["az", "resource", "show"]
            secret_name = arguments[arguments.index("--ids") + 1].rsplit("/", 1)[1]
            reply = ("https://" + vault + ".vault.azure.net/secrets/" + secret_name + "/" + "2" * 32).encode()
        return subprocess.CompletedProcess(arguments, 0, stdout=reply, stderr=b"")
    backend.run = cli
    master = hosted.service.settings.runtime_admission_secret.get_secret_value()
    backend._seed(state, master)
    assert set(seeded) == set(GOOGLE_SECRET_NAMES.values())
    assert set(refs) == set(SECRET_NAMES) | set(GOOGLE_SECRET_NAMES)
    assert seeded[GOOGLE_SECRET_NAMES["GOOGLE_CONNECTION_CLIENT_SECRET"]] == optional.secret.read_text()
    custody = seeded[GOOGLE_SECRET_NAMES["GOOGLE_CONNECTION_ENCRYPTION_KEY"]]
    assert len(base64.urlsafe_b64decode(custody)) == 32 and custody == box_google_custody_key(optional.deployment, master)
    assert custody != box_admission_key(optional.deployment, master)
    other = json.loads(json.dumps(optional.deployment))
    other["practice"]["plan"]["box_id"] = str(uuid4())
    assert box_google_custody_key(other, master) != custody
    assert not (backend.directory / "admin-password").exists() and not (backend.directory / "seed-parameters.json").exists()
    before = list(calls)
    optional.secret.unlink()
    backend._seed(state, master)
    assert calls == before


def test_google_web_plan_requires_runtime_refs_and_reuses_existing_minimal_profile_without_public_secrets(hosted, tmp_path):
    optional = google_host(hosted, tmp_path)
    backend = optional.allocator.backend
    state = backend._open(optional.deployment)
    with pytest.raises(ValueError, match="both Box-only secret references"):
        build_allocated_web(backend, state)
    assert "web_build" not in state
    state["deployment"]["practice"]["secret_references"].update(box_references(optional.deployment, GOOGLE_SECRET_NAMES))
    refs = state["deployment"]["practice"]["secret_references"]
    original_ref = refs["GOOGLE_CONNECTION_CLIENT_SECRET"]
    for invalid in (original_ref.replace(".vault.azure.net", "-other.vault.azure.net"), original_ref[:-32] + "z" * 32):
        refs["GOOGLE_CONNECTION_CLIENT_SECRET"] = invalid
        with pytest.raises(ValueError, match="both Box-only secret references"):
            build_allocated_web(backend, state)
        assert "web_build" not in state
    refs["GOOGLE_CONNECTION_CLIENT_SECRET"] = original_ref
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        data = b"image: aquasec/trivy@sha256:" + b"1" * 64
        item = tarfile.TarInfo(".github/workflows/synth-ci.yml")
        item.size = len(data)
        tar.addfile(item, io.BytesIO(data))
    calls = []
    def cli(arguments, **kwargs):
        calls.append(arguments)
        if arguments[0] == "git":
            reply = archive.getvalue() if "archive" in arguments else hosted.config.release["source_commit"].encode()
            return subprocess.CompletedProcess(arguments, 0, stdout=reply, stderr=b"")
        raise subprocess.CalledProcessError(1, arguments)
    backend.run = cli
    with pytest.raises(RuntimeError, match="provider operation pending"):
        build_allocated_web(backend, state)
    context = backend.directory / "web-context"
    recipe = json.loads((context / "allocated-web-task.json").read_text())
    words = shlex.split(recipe["steps"][0]["build"])
    env = dict(words[index + 1].split("=", 1) for index, word in enumerate(words) if word == "--build-arg")
    assert env["VITE_WORKSPACE_FEATURE_PROFILE"] == "independent-beta-v1"
    assert not any("SECRET" in name or name in {"google", "client_secret_file"} for name in env)
    assert str(optional.secret) not in json.dumps(recipe) and optional.secret.read_text() not in json.dumps(recipe)
    # Resolve the exact public recipe with the existing Dockerfile's fixed web aliases.
    script = "import {resolveBetaFeatureProfile} from './clients/shared/beta-feature-profile.mjs';const env=JSON.parse(process.argv[1]);delete env.APP_IMAGE;env.VITE_WORKSPACE_HOSTED_CLIENT='web';env.VITE_API_BASE=env.VITE_WORKSPACE_HOSTED_API_ORIGIN;console.log(JSON.stringify(resolveBetaFeatureProfile(env).manifest));"
    actual = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(env)], cwd=hosted.source,
                            check=True, capture_output=True, text=True)
    manifest = json.loads(actual.stdout)
    assert manifest["profile"] == "independent-beta-v1" and manifest["organizationId"] == hosted.plan.organization_id
    assert manifest["platformAccess"] == "disabled" and manifest["captureMode"] == "disabled"
    assert {"VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED", "VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED", "VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED"} <= set(manifest["enabledFlags"])
    assert not any(name in manifest["enabledFlags"] for name in ("VITE_CORE_CONNECTION_ENABLED", "VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED", "VITE_WORKSPACE_SCHEDULING_ENABLED"))


def test_actual_allocator_destination_is_accepted_by_shared_native_profile_contract(hosted):
    c = hosted
    destination = c.allocator.destination(WorkspaceAllocationRequest(c.plan.practice_id, c.plan.box_id,
        "unused", c.plan.owner_subject, c.plan.issuer))
    profile = {"contract_version": "cosmas-native-workspace-profile.v1", "client": "apple", "nonce": str(uuid4()),
        "native_origin": "capacitor://localhost", "data_mode": "synthetic",
        "nativeIdentity": {"version": 1, "profile": "operational-staging-v1", "client": "apple",
            "apiOrigin": destination.api_origin, "publishableKey": c.config.account["publishable_key"],
            "frontendOrigin": c.plan.issuer, "organizationId": c.plan.organization_id, "audience": c.config.account["audience"]},
        "practice": {"practice_id": c.plan.practice_id, "box_id": c.plan.box_id},
        "workspace": {"url": destination.workspace_url, "source_commit": destination.source_commit,
            "image_sha256": destination.image_sha256, "workspace_proof_sha256": "1" * 64,
            "member_proof_sha256": "5" * 64, "native_qualification_sha256": "6" * 64},
        "session": {"issuer": c.plan.issuer, "subject": c.plan.owner_subject, "session_id": "sess_host1"},
        "issued_at": 1800000000, "expires_at": 1800000120}
    # Cross the actual Python producer/JavaScript consumer boundary. Keeping
    # the shared validator strict catches route case or paired-origin drift.
    script = """
import {readFileSync} from 'node:fs';
import {validateRegisteredNativeProfile} from './clients/shared/native-practice-profile.mjs';
const value=validateRegisteredNativeProfile(JSON.parse(readFileSync(0,'utf8')));
console.log(JSON.stringify({url:value.workspace.url,api:value.nativeIdentity.apiOrigin}));
"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(profile),
        text=True, capture_output=True, check=True, cwd=c.source, timeout=20)
    assert json.loads(result.stdout) == {"url": destination.workspace_url, "api": destination.api_origin}


def test_new_destination_does_not_rewrite_a_different_saved_binding(hosted):
    c = hosted
    old = replace(c.plan, workspace_url=c.plan.workspace_url.replace("/chief", "/Chief"))
    with c.service.sessions.begin() as session:
        practice = session.get(Practice, c.plan.practice_id)
        assert practice is not None
        practice.workspace_url = old.workspace_url
    with pytest.raises(EnrollmentError, match="immutable release changed"):
        c.allocator.allocate(old, operation_id=c.operation)
    with c.service.sessions() as session:
        practice = session.get(Practice, c.plan.practice_id)
        assert practice is not None and practice.workspace_url == old.workspace_url
    assert not c.config.state_root.exists()


@pytest.mark.parametrize("mutation", ["production", "foreign_group", "foreign_dns", "mutable_image", "account", "extra"])
def test_host_configuration_rejects_foreign_or_unreviewed_inputs(hosted, mutation):
    value = json.loads(json.dumps(hosted.value))
    if mutation == "production":
        value["synthetic_only"] = False
    elif mutation == "foreign_group":
        value["foundation"]["resource_group_name"] = "cosmaneura-prod"
    elif mutation == "foreign_dns":
        value["foundation"]["blob_private_dns_zone_id"] = "/subscriptions/other/resourceGroups/other/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
    elif mutation == "mutable_image":
        value["release"]["api_image"] = value["foundation"]["registry_server"] + "/api:latest"
    elif mutation == "account":
        value["account"]["app_origin"] = "https://app.cosmaneura.com"
    else:
        value["ready"] = True
    with pytest.raises(ValueError):
        HostingConfiguration(value)


def test_disabled_hosting_and_fake_backend_make_no_provider_calls(hosted):
    c = hosted
    c.config.value["enabled"] = False
    with pytest.raises(EnrollmentError):
        c.allocator.allocate(c.plan, operation_id=c.operation)
    assert not c.config.state_root.exists()
    with pytest.raises(ValueError):
        OpenTofuWorkspaceAllocator(c.service, c.config, backend=SimpleNamespace(allocate=lambda *args: None))


@pytest.mark.parametrize("change", ["inactive", "not_owner"])
def test_revoked_or_changed_owner_cannot_start_private_provider_calls(hosted, change):
    c = hosted
    with c.service.sessions.begin() as session:
        member = session.scalar(select(Membership).where(Membership.practice_id == c.plan.practice_id))
        assert member is not None
        if change == "inactive":
            member.active = False
        else:
            member.role = "staff"
    with pytest.raises(EnrollmentError, match="ownership"):
        c.allocator.allocate(c.plan, operation_id=c.operation)
    assert not c.config.state_root.exists()


def test_private_operation_reuses_exact_scope_and_freezes_display_manifest(hosted):
    c = hosted
    backend = c.allocator.backend
    saved = backend._open(c.deployment)
    changed = json.loads(json.dumps(c.deployment))
    changed["_owner_manifest"]["owner_display_name"] = "Updated Display Name"
    changed["practice"]["owner_manifest_sha256"] = "f" * 64
    assert backend._open(changed)["deployment"]["_owner_manifest"] == saved["deployment"]["_owner_manifest"]
    changed["practice"]["plan"]["source_commit"] = "f" * 40
    with pytest.raises(ValueError):
        backend._open(changed)


def test_private_operation_refuses_symlink_state(hosted, tmp_path):
    c = hosted
    outside = tmp_path / "unrelated"
    outside.mkdir()
    c.config.state_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        c.allocator.backend._open(c.deployment)
    assert list(outside.iterdir()) == []


def test_actual_capacity_preflight_leaves_queued_without_terraform_apply(hosted):
    c = hosted
    calls = []
    def cli(arguments, **kwargs):
        calls.append(arguments)
        if arguments[0] == "git":
            if "rev-parse" in arguments:
                body = c.config.release["source_commit"].encode()
            elif "ls-tree" in arguments:
                body = "\n".join(str(path.relative_to(c.source)) for path in
                    (c.source / "infra/enrollment/allocated-workspace").rglob("*") if path.is_file()).encode()
            elif "show" in arguments:
                body = (c.source / arguments[-1].split(":", 1)[1]).read_bytes()
            else:
                body = b""
        elif arguments[:3] == ["az", "account", "show"]:
            body = canonical({"id": c.config.foundation["subscription_id"], "tenantId": c.config.foundation["tenant_id"], "state": "Enabled"})
        elif arguments[0] == "tofu":
            body = canonical({"terraform_version": "1.12.5"})
        elif "subnet" in arguments:
            body = canonical({"id": arguments[arguments.index("--ids") + 1], "addressPrefix": "10.240.8.0/29"})
        elif "check-ip-address" in arguments:
            body = canonical({"available": False})
        else:
            body = b""
        return subprocess.CompletedProcess(arguments, 0, stdout=body, stderr=b"")
    backend = AzureAllocationBackend(c.config, run=cli, sleep=lambda _: None)
    backend._open(c.deployment)
    with pytest.raises(RuntimeError, match="capacity"):
        backend.preflight()
    assert not any("apply" in arguments for arguments in calls)
    assert not (backend.directory / "admin-password").exists()


def test_redis_uses_supported_stable_provider_version_before_secret_preparation(hosted):
    c = hosted
    backend = c.allocator.backend
    state = backend._open(c.deployment)
    state["resources"] = {"redis_id": c.scope + "Microsoft.Cache/redisEnterprise/invented"}
    calls = []
    def cli(arguments, **kwargs):
        calls.append(arguments)
        raise subprocess.CalledProcessError(1, arguments)
    backend.run = cli
    with pytest.raises(RuntimeError, match="provider operation pending"):
        backend._seed(state, "invented-master-" + "0" * 64)
    assert len(calls) == 1
    assert calls[0] == ["az", "rest", "--method", "post", "--url",
        "https://management.azure.com" + state["resources"]["redis_id"] + "/databases/default/listKeys?api-version=2024-10-01",
        "--output", "json"]
    assert not (backend.directory / "seed-parameters.json").exists()


@pytest.mark.parametrize("lost_reference", [False, True])
def test_seed_enterprise_contract_and_all_secret_tracking_names_recover_without_exposure(hosted, tmp_path, capsys, lost_reference):
    optional = google_host(hosted, tmp_path)
    value = json.loads(json.dumps(optional.config.value))
    model_key = tmp_path / "invented-seed-model-key"
    model_key.write_text("invented-seed-model-key-only")
    model_key.chmod(0o600)
    value["model"] = {**REVIEWED_MODEL, "api_key_file": str(model_key)}
    config = HostingConfiguration(value)
    allocator = OpenTofuWorkspaceAllocator(hosted.service, config)
    deployment = allocator._deployment(hosted.plan, hosted.operation)
    backend = allocator.backend
    state = backend._open(deployment)
    refs = state["deployment"]["practice"]["secret_references"]
    vault = "kvca" + hosted.plan.practice_id.replace("-", "")[:20]
    state["resources"] = {
        "redis_id": hosted.scope + "Microsoft.Cache/redisEnterprise/invented-seed",
        "redis_hostname": "invented-seed.redis.azure.net",
        "postgres_fqdn": "psql-cbaw-" + hosted.plan.practice_id.replace("-", "") + ".postgres.database.azure.com",
        "key_vault_id": hosted.scope + "Microsoft.KeyVault/vaults/" + vault,
    }
    backend._write("admin-password", b"invented-seed-admin-only")
    backend._write("runtime-password", b"invented-seed-runtime-only")
    all_names = {**SECRET_NAMES, **GOOGLE_SECRET_NAMES, **MODEL_SECRET_NAMES}
    writes, calls, reply_lost = [], [], False

    def cli(arguments, **kwargs):
        nonlocal reply_lost
        calls.append(arguments)
        if arguments[:2] == ["az", "rest"]:
            expected = "https://management.azure.com" + state["resources"]["redis_id"] + "/databases/default/listKeys?api-version=2024-10-01"
            assert arguments == ["az", "rest", "--method", "post", "--url", expected, "--output", "json"]
            body = canonical({"primaryKey": "invented-seed-redis-only", "secondaryKey": "invented-unused-secondary"})
        elif arguments[:4] == ["az", "deployment", "group", "create"]:
            name = arguments[arguments.index("--name") + 1]
            # The synthetic provider rejects the real ARM limit rather than
            # accepting an invalid command and mirroring the name helper.
            if not re.fullmatch(r"[A-Za-z0-9_.()-]{1,64}", name):
                raise subprocess.CalledProcessError(1, arguments)
            parameter_file = backend.directory / "seed-parameters.json"
            assert stat.S_IMODE(parameter_file.stat().st_mode) == 0o600
            assert arguments[arguments.index("--parameters") + 1] == "@" + str(parameter_file)
            assert arguments[arguments.index("--output") + 1] == "none"
            parameters = json.loads(parameter_file.read_text())
            assert parameters["vaultName"]["value"] == vault
            secret = parameters["secretName"]["value"]
            assert secret in all_names.values() and parameters["secretValue"]["value"]
            writes.append((secret, name))
            body = b""
        else:
            assert arguments[:3] == ["az", "resource", "show"]
            secret = arguments[arguments.index("--ids") + 1].rsplit("/", 1)[1]
            if lost_reference and secret == "enrollment-admission-key" and not reply_lost:
                reply_lost = True
                raise subprocess.CalledProcessError(1, arguments, stderr=b"invented private provider material")
            body = ("https://" + vault + ".vault.azure.net/secrets/" + secret + "/" + "2" * 32).encode()
        return subprocess.CompletedProcess(arguments, 0, stdout=body, stderr=b"")

    backend.run = cli
    master = "invented-seed-master-" + "0" * 64
    if lost_reference:
        with pytest.raises(RuntimeError, match="^private allocation provider operation pending$"):
            backend._seed(state, master)
        assert set(refs) == {"REDIS_URL"}
        saved = backend._open(allocator._deployment(hosted.plan, hosted.operation))
        assert saved["deployment"]["practice"]["secret_references"] == refs
        state = saved
        refs = state["deployment"]["practice"]["secret_references"]
    backend._seed(state, master)
    assert writes[0] == ("redis-url", "allocation-" + hosted.operation + "-redis-url")
    assert set(refs) == set(all_names)
    tracking = {secret: name for secret, name in writes}
    assert len(tracking) == len(set(tracking.values())) == 8
    for secret, name in writes:
        assert tracking[secret] == name
        original = "allocation-" + hosted.operation + "-" + secret
        if len(original) <= 64:
            assert name == original
        else:
            assert re.fullmatch(r"allocation-[a-f0-9]{40}", name)
    if lost_reference:
        retried = [name for secret, name in writes if secret == "enrollment-admission-key"]
        assert len(retried) == 2 and retried[0] == retried[1]
        assert sum(secret == "redis-url" for secret, _ in writes) == 1
    before = list(calls)
    optional.secret.unlink()
    model_key.unlink()
    (backend.directory / "admin-password").unlink()
    (backend.directory / "runtime-password").unlink()
    backend._seed(state, master)
    assert calls == before and not (backend.directory / "seed-parameters.json").exists()
    journal = (backend.directory / "operation.json").read_text()
    captured = capsys.readouterr()
    for private in ("invented-seed-redis-only", "invented-seed-model-key-only", "invented-seed-admin-only",
                    "invented-seed-runtime-only", "invented private provider material"):
        assert private not in journal + captured.out + captured.err


def test_per_box_job_binding_uses_canonical_allocated_host_and_rejects_central_database(hosted):
    c = hosted
    spec = importlib.util.spec_from_file_location("owned_allocated_job", c.source / "infra/enrollment/allocated-workspace/job.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    host = "psql-cbaw-" + c.plan.practice_id.replace("-", "") + ".postgres.database.azure.com"
    environment = {**c.deployment["practice"]["api_env"], "EXPECTED_SCHEMA_REVISION": c.deployment["expected_schema_revision"],
        "RESERVED_OWNER_SUBJECT": c.plan.owner_subject, "BOX_POSTGRES_HOST": host,
        "DATABASE_ADMIN_URL": "postgresql+psycopg://box_bootstrap:invented@" + host + ":5432/cosmas_os?sslmode=verify-full&sslrootcert=system",
        "DATABASE_URL": "postgresql+psycopg://box_runtime:invented@" + host + ":5432/cosmas_os?sslmode=verify-full&sslrootcert=system"}
    assert module.binding(environment)["box_id"] == c.plan.box_id
    environment["BOX_POSTGRES_HOST"] = "enrollment.postgres.database.azure.com"
    with pytest.raises(ValueError):
        module.binding(environment)


def test_known_failed_job_has_bounded_retry_and_preserves_actual_execution_history(hosted):
    c = hosted
    backend = c.allocator.backend
    state = backend._open(c.deployment)
    state["resources"] = {"storage_id": c.scope + "Microsoft.Storage/storageAccounts/invented"}
    executions = []
    def cli(arguments, **kwargs):
        if "list" in arguments:
            body = json.dumps([{"name": name} for name in executions]).encode()
        elif "start" in arguments:
            executions.append("invented-execution-" + str(len(executions) + 1))
            body = canonical({"name": executions[-1]})
        else:
            body = canonical({"properties": {"status": "Failed"}})
        return subprocess.CompletedProcess(arguments, 0, stdout=body, stderr=b"")
    backend.run = cli
    for _ in range(3):
        with pytest.raises(RuntimeError, match="bounded retry remains pending"):
            backend._job(state, "migrate")
    with pytest.raises(RuntimeError, match="retry limit"):
        backend._job(state, "migrate")
    assert len(executions) == 3 and state["migrate_executions"] == executions
    assert "migrate_execution" not in state
    assert not (backend.directory / "migrate-receipt.json").exists()


def test_lost_job_start_reply_recovers_same_execution_and_requires_real_bound_receipt(hosted):
    c = hosted
    backend = c.allocator.backend
    state = backend._open(c.deployment)
    state["resources"] = {"storage_id": c.scope + "Microsoft.Storage/storageAccounts/invented"}
    calls = []
    executions = []
    def cli(arguments, **kwargs):
        calls.append(arguments)
        if "list" in arguments:
            body = json.dumps([{"name": name} for name in executions]).encode()
        elif "start" in arguments:
            executions.append("invented-lost-execution")
            raise subprocess.TimeoutExpired(arguments, 900)
        elif "download" in arguments:
            receipt = {"contract": "enrollment-workspace-migration.v1", "allocation_operation_id": c.operation,
                **{key: getattr(c.plan, key) for key in ("practice_id", "box_id", "organization_id", "source_commit", "image_sha256")},
                "owner_ready": False, "workspace_ready": False}
            Path(arguments[arguments.index("--file") + 1]).write_bytes(canonical(receipt))
            body = b""
        else:
            body = canonical({"properties": {"status": "Succeeded"}})
        return subprocess.CompletedProcess(arguments, 0, stdout=body, stderr=b"")
    backend.run = cli
    with pytest.raises(RuntimeError, match="provider operation pending"):
        backend._job(state, "migrate")
    assert state["migrate_start_pending"] is True
    assert len(backend._job(state, "migrate")) == 64
    assert sum("start" in arguments for arguments in calls) == 1
    assert state["migrate_execution"] == "invented-lost-execution"
    assert state["migrate_executions"] == executions


@pytest.mark.parametrize("failure", ["foreign_zone", "foreign_record", "propagation"])
def test_dns_validates_all_ownership_before_writes_and_requires_actual_propagation(hosted, failure):
    c = hosted
    writes = []
    def cloudflare(request):
        if request.method == "POST":
            body = json.loads(request.content)
            writes.append(body)
            return httpx.Response(200, json={"success": True, "result": body})
        if request.url.path.endswith("/dns_records"):
            rows = [] if failure != "foreign_record" else [{"type": request.url.params["type"], "name": request.url.params["name"],
                    "content": "foreign.azurecontainerapps.io", "proxied": False}]
            return httpx.Response(200, json={"success": True, "result": rows})
        return httpx.Response(200, json={"success": True, "result": {"id": c.value["cloudflare_zone_id"],
                    "name": "cosmaneura.com" if failure == "foreign_zone" else "cosmas.ai"}})
    resources = {"api_fqdn": "api-invented.azurecontainerapps.io", "web_fqdn": "web-invented.azurecontainerapps.io"}
    with pytest.raises((ValueError, RuntimeError)):
        bind_allocated_dns(c.config, c.deployment, resources, {"api": "invented-api-proof", "web": "invented-web-proof"},
            client=httpx.Client(transport=httpx.MockTransport(cloudflare)),
            run=lambda *args, **kwargs: SimpleNamespace(stdout=""), sleep=lambda _: None)
    assert len(writes) == (4 if failure == "propagation" else 0)


def test_web_image_does_not_pass_without_actual_validation_and_scanner_steps(hosted):
    c = hosted
    calls = []
    backend = c.allocator.backend
    state = backend._open(c.deployment)
    (backend.directory / "web-context").mkdir()
    state["web_build"] = {"run_id": "invented-run", "image": c.value["foundation"]["registry_server"] + "/allocated-workspace-web:" + c.operation,
        "profile_sha256": "f" * 64, "queue_sent": True}
    def cli(arguments, **kwargs):
        calls.append(arguments)
        if "show-run" in arguments:
            body = canonical({"status": "Succeeded", "outputImages": []})
        else:
            body = b"Step ID: validate marked as successful\nStep ID: scan marked as failed\n"
        return subprocess.CompletedProcess(arguments, 0, stdout=body, stderr=b"")
    backend.run = cli
    with pytest.raises(ValueError, match="scanner"):
        build_allocated_web(backend, state)
    assert not any("update" in arguments for arguments in calls)
    assert "image_digest" not in state["web_build"]


def test_interrupted_unqueued_web_context_is_discarded_before_rechecking_release(hosted):
    c = hosted
    backend = c.allocator.backend
    state = backend._open(c.deployment)
    context = backend.directory / "web-context"
    context.mkdir()
    (context / "unreviewed-stale-file").write_text("invented interrupted extraction")
    calls = []
    def cli(arguments, **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout=b"different-release", stderr=b"")
    backend.run = cli
    with pytest.raises(ValueError, match="exact committed build source"):
        build_allocated_web(backend, state)
    assert not context.exists()
    assert len(calls) == 1 and calls[0][0] == "git"
    assert "web_build" not in state


def _model_host(hosted, tmp_path):
    value = json.loads(json.dumps(hosted.value))
    key = tmp_path / "invented-model-key"
    key.write_text("invented-model-key-for-offline-provider-boundary-only")
    key.chmod(0o600)
    value["model"] = {**REVIEWED_MODEL, "api_key_file": str(key)}
    value["state_root"] = str(tmp_path / "model-worker-state")
    config = HostingConfiguration(value)
    allocator = OpenTofuWorkspaceAllocator(hosted.service, config)
    return SimpleNamespace(config=config, allocator=allocator, key=key,
        deployment=allocator._deployment(hosted.plan, hosted.operation))


def _model_runtime(deployment, key=None):
    values = {name.lower(): value == "true" if value in {"true", "false"} else value
              for name, value in deployment["practice"]["api_env"].items()}
    host = "psql-cbaw-" + deployment["practice"]["plan"]["practice_id"].replace("-", "") + ".postgres.database.azure.com"
    values.update(database_url="postgresql+psycopg://box_runtime:invented@" + host + ":5432/cosmas_os?sslmode=verify-full&sslrootcert=system",
        redis_url="rediss://:invented@inventedmodelbox.redis.azure.net:10000/0?ssl_cert_reqs=required",
        azure_storage_account_url="https://inventedmodelbox.blob.core.windows.net", azure_blob_container="box",
        workspace_enrollment_admission_secret=SecretStr("a" * 64), workspace_llm_api_key=key)
    # Construct from explicit invented fields, then run the actual runtime
    # validator; no environment/key-file configuration is consulted.
    result = Settings.model_construct(**values)
    result.validate_runtime_configuration()
    return result


def _seeded_model_state(selected, hosted):
    backend = selected.allocator.backend
    state = backend._open(selected.deployment)
    state["deployment"]["practice"]["secret_references"].update(
        box_references(selected.deployment, SECRET_NAMES))
    vault = "kvca" + hosted.plan.practice_id.replace("-", "")[:20]
    state["resources"] = {"key_vault_id": hosted.scope + "Microsoft.KeyVault/vaults/" + vault}
    return backend, state, vault


def test_model_selection_reaches_actual_config_and_pinned_adapter_without_public_key(hosted, tmp_path):
    option = _model_host(hosted, tmp_path)
    raw = canonical(option.deployment)
    assert option.key.read_bytes() not in raw and str(option.key).encode() not in raw
    assert option.deployment["model"] == REVIEWED_MODEL
    public = option.deployment["practice"]["api_env"]
    assert "WORKSPACE_LLM_API_KEY" not in public
    config = _model_runtime(option.deployment, SecretStr("invented-model-key"))
    assert config.workspace_llm_available and not config.workspace_agent_tools_enabled
    assert config.workspace_llm_endpoint + "/chat/completions" == ENDPOINT
    calls = []
    def respond(request):
        assert str(request.url) == ENDPOINT
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1" and body["store"] is False and "tools" not in body
        calls.append(body)
        return httpx.Response(200, json={"model": "gpt-4.1", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(
                {"answer": "Invented practice agenda ready for review.", "source_ids": []})}}]})
    connector = GPT41Connector(lambda: config.workspace_llm_api_key.get_secret_value(), transport=httpx.MockTransport(respond))
    reply = connector.review(BotContext("invented-workspace", 1, "chief", "Organize my notes", "brief", (), ()))
    assert reply.content == "Invented practice agenda ready for review." and len(calls) == 1
    missing = config.model_copy(update={"workspace_llm_api_key": None})
    assert not missing.workspace_llm_available and missing.runtime_configuration_errors()


def test_model_key_is_seeded_only_to_box_vault_and_completed_retry_never_reads_key(hosted, tmp_path):
    option = _model_host(hosted, tmp_path)
    backend, state, vault = _seeded_model_state(option, hosted)
    calls, seeded = [], {}
    def cli(arguments, **kwargs):
        calls.append(arguments)
        if arguments[:4] == ["az", "deployment", "group", "create"]:
            body = json.loads((backend.directory / "seed-parameters.json").read_text())
            assert body["vaultName"]["value"] == vault
            seeded[body["secretName"]["value"]] = body["secretValue"]["value"]
            return subprocess.CompletedProcess(arguments, 0, stdout=b"", stderr=b"")
        assert arguments[:3] == ["az", "resource", "show"]
        return subprocess.CompletedProcess(arguments, 0, stdout=("https://" + vault + ".vault.azure.net/secrets/workspace-llm-api-key/" + "2" * 32).encode(), stderr=b"")
    backend.run = cli
    backend._seed(state, "invented-master-" + "0" * 64)
    assert seeded == {"workspace-llm-api-key": option.key.read_text()}
    assert len(calls) == 2 and "WORKSPACE_LLM_API_KEY" in state["deployment"]["practice"]["secret_references"]
    assert option.key.read_bytes() not in (backend.directory / "operation.json").read_bytes()
    assert not (backend.directory / "seed-parameters.json").exists()
    assert not (backend.directory / "admin-password").exists()
    option.key.unlink()
    backend._seed(state, "invented-master-" + "0" * 64)
    assert len(calls) == 2


@pytest.mark.parametrize("fault", ["missing", "insecure"])
def test_unavailable_protected_key_cannot_seed_or_activate_model(hosted, tmp_path, fault):
    option = _model_host(hosted, tmp_path)
    backend, state, vault = _seeded_model_state(option, hosted)
    backend.run = lambda *_args, **_kwargs: pytest.fail("unavailable key reached a provider")
    state["resources"]["key_vault_id"] = hosted.scope + "Microsoft.KeyVault/vaults/unrelated"
    with pytest.raises(ValueError, match="this Box"):
        backend._seed(state, "invented-master")
    state["resources"]["key_vault_id"] = hosted.scope + "Microsoft.KeyVault/vaults/" + vault
    references = state["deployment"]["practice"]["secret_references"]
    references["WORKSPACE_LLM_API_KEY"] = "https://other.vault.azure.net/secrets/workspace-llm-api-key/" + "2" * 32
    with pytest.raises(ValueError, match="versioned Box model"):
        backend._seed(state, "invented-master")
    references.pop("WORKSPACE_LLM_API_KEY")
    if fault == "missing":
        option.key.unlink()
    else:
        option.key.chmod(0o644)
    with pytest.raises((FileNotFoundError, ValueError)):
        backend._seed(state, "invented-master")
    assert "WORKSPACE_LLM_API_KEY" not in state["deployment"]["practice"]["secret_references"]
    assert state["deployment"]["deploy_workloads"] is False


def test_all_allocated_role_requests_declare_service_principals_for_constrained_delegation():
    source = Path(__file__).resolve().parents[2]
    module = (source / "infra/enrollment/allocated-workspace/main.tf").read_text()
    assignments = re.findall(r'resource "azurerm_role_assignment" "[a-z_]+" \{(.*?)^\}', module, re.M | re.S)
    assert assignments
    allowed_roles = {"AcrPull", "Storage Blob Data Contributor", "Storage Blob Data Reader",
                     "Key Vault Secrets User", "Key Vault Secrets Officer"}
    for assignment in assignments:
        role = re.search(r'role_definition_name\s*=\s*"([^"]+)"', assignment)
        principal_type = re.search(r'principal_type\s*=\s*"([^"]+)"', assignment)
        principal = re.search(r'principal_id\s*=\s*([^\n]+)', assignment)
        assert role and role[1] in allowed_roles
        assert principal_type and principal_type[1] == "ServicePrincipal"
        assert principal and (principal[1].startswith("azurerm_user_assigned_identity.")
                              or principal[1] == "local.d.allocator_object_id")


def test_production_practice_runtime_holds_real_data_under_its_own_executed_baa(production_hosted):
    c = production_hosted
    d, public = c.deployment, c.deployment["practice"]["api_env"]
    practice = c.plan.practice_id
    assert c.plan.workspace_url == f"https://{practice}.workspace.cosmas.ai/chief"
    assert c.plan.api_origin == f"https://api.{practice}.workspace.cosmas.ai"
    assert d["environment"] == "production" and d["synthetic_only"] is False
    assert public["DATA_MODE"] == "authorized_beta" and public["CLERK_ISSUER"] == "https://clerk.cosmas.ai"
    with c.service.sessions() as session:
        practice_row = session.get(Practice, practice)
        assert practice_row is not None
        acceptance = c.service._acceptance(session, practice_row)
        assert acceptance is not None
    assert public["CLINIC_APPROVAL_REF"] == "cosmas-enrollment-practice:" + practice
    assert public["BAA_EVIDENCE_REF"] == f"cosmas-baa:{BAA_DOC_ID}:{BAA_VERSION}:{acceptance.id}"
    assert public["PHI_AUTHORIZATION_REF"] == f"cosmas-baa-phi:{acceptance.id}:{BAA_SHA256}"
    assert not any("SECRET" in name or "CORE" in name for name in public)
    # The runtime's own startup validation accepts exactly this public configuration.
    selected = Settings.model_validate({name.lower(): value for name, value in public.items()})
    assert selected.data_mode == "authorized_beta"
    assert not [error for error in selected.runtime_configuration_errors() if "authorized_beta" in error or "DATA_MODE" in error]


def test_staging_practice_runtime_stays_synthetic_without_baa_references(hosted):
    public = hosted.deployment["practice"]["api_env"]
    assert hosted.deployment["environment"] == "staging" and hosted.deployment["synthetic_only"] is True
    assert public["DATA_MODE"] == "synthetic"
    assert not {"CLINIC_APPROVAL_REF", "BAA_EVIDENCE_REF", "PHI_AUTHORIZATION_REF"} & set(public)
    assert hosted.plan.workspace_url.endswith(".staging.cosmas.ai/chief")


@pytest.mark.parametrize("mutation", ["synthetic_only", "staging_account", "development_issuer", "test_key",
                                      "staging_names", "staging_storage"])
def test_production_configuration_refuses_any_staging_or_development_input(production_hosted, mutation):
    value = json.loads(json.dumps(production_hosted.value))
    if mutation == "synthetic_only":
        value["synthetic_only"] = True
    elif mutation == "staging_account":
        value["account"]["app_origin"] = "https://onboarding.staging.cosmas.ai"
    elif mutation == "development_issuer":
        issuer = "https://hosting-fixture.clerk.accounts.dev"
        value["account"]["issuer"] = issuer
        value["account"]["publishable_key"] = "pk_live_" + base64.b64encode((issuer[8:] + "$").encode()).decode()
    elif mutation == "test_key":
        value["account"]["publishable_key"] = "pk_test_" + base64.b64encode(b"clerk.cosmas.ai$").decode()
    elif mutation == "staging_names":
        value["foundation"]["registry_server"] = "acrcbotenrstgfixture1.azurecr.io"
    else:
        value["foundation"]["state_backend"]["storage_account_name"] = "stcbotenrstgfixture1"
    with pytest.raises(ValueError):
        HostingConfiguration(value)


def test_production_hosting_refuses_a_synthetic_enrollment_registry(production_hosted):
    c = production_hosted
    c.service.settings.data_mode = "synthetic"
    with pytest.raises(EnrollmentError, match="unavailable"):
        c.allocator.destination(WorkspaceAllocationRequest(c.plan.practice_id, c.plan.box_id, "unused",
                                                           c.plan.owner_subject, c.plan.issuer))
    with pytest.raises(EnrollmentError, match="unavailable"):
        c.allocator._deployment(c.plan, c.operation)


def test_staging_hosting_refuses_a_production_enrollment_registry(hosted):
    hosted.service.settings.data_mode = "production"
    with pytest.raises(EnrollmentError, match="unavailable"):
        hosted.allocator._deployment(hosted.plan, hosted.operation)


def test_production_enrollment_registers_only_its_own_practice_uuid_workspace_hosts(production_hosted):
    settings, practice = production_hosted.service.settings, production_hosted.plan.practice_id
    assert settings.workspace_origin_policy() == "practice-uuid-production-v1"
    assert settings.registered_workspace_origin(f"https://{practice}.workspace.cosmas.ai", practice)
    assert not settings.registered_workspace_origin(f"https://{practice}.staging.cosmas.ai", practice)
    assert not settings.registered_workspace_origin(f"https://{uuid4()}.workspace.cosmas.ai", practice)


def test_production_allocator_destination_is_accepted_by_shared_native_profile_contract(production_hosted):
    c = production_hosted
    destination = c.allocator.destination(WorkspaceAllocationRequest(c.plan.practice_id, c.plan.box_id,
        "unused", c.plan.owner_subject, c.plan.issuer))
    profile = {"contract_version": "cosmas-native-workspace-profile.v1", "client": "apple", "nonce": str(uuid4()),
        "native_origin": "capacitor://localhost", "data_mode": "authorized_beta",
        "nativeIdentity": {"version": 1, "profile": "operational-beta-v1", "client": "apple",
            "apiOrigin": destination.api_origin, "publishableKey": c.config.account["publishable_key"],
            "frontendOrigin": c.plan.issuer, "organizationId": c.plan.organization_id,
            "audience": "cosmabot-practice-api"},
        "practice": {"practice_id": c.plan.practice_id, "box_id": c.plan.box_id},
        "workspace": {"url": destination.workspace_url, "source_commit": destination.source_commit,
            "image_sha256": destination.image_sha256, "workspace_proof_sha256": "1" * 64,
            "member_proof_sha256": "5" * 64, "native_qualification_sha256": "6" * 64},
        "session": {"issuer": c.plan.issuer, "subject": c.plan.owner_subject, "session_id": "sess_host1"},
        "issued_at": 1800000000, "expires_at": 1800000120}
    script = """
import {readFileSync} from 'node:fs';
import {validateRegisteredNativeProfile} from './clients/shared/native-practice-profile.mjs';
const value=validateRegisteredNativeProfile(JSON.parse(readFileSync(0,'utf8')));
console.log(JSON.stringify({url:value.workspace.url,api:value.nativeIdentity.apiOrigin,mode:value.data_mode}));
"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(profile),
        text=True, capture_output=True, check=True, cwd=c.source, timeout=20)
    assert json.loads(result.stdout) == {"url": destination.workspace_url, "api": destination.api_origin,
                                         "mode": "authorized_beta"}
