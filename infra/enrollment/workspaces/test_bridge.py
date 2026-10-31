"""Bounded preparation checks and opt-in, disposable two-Box PostgreSQL rehearsal."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from contextvars import Context
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

HERE = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location("workspace_bridge_" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def session_dependency(factory):
    def get_session():
        with factory() as session:
            yield session

    return get_session


job, prepare = load("job"), load("prepare")
sys.modules["prepare"] = prepare
seed = load("seed_secret")
sys.modules.pop("prepare")


@pytest.fixture
def files():
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            "import {candidate} from './infra/enrollment/workspaces/fixtures.mjs';"
            "import {render} from './infra/enrollment/workspaces/render.mjs';"
            "process.stdout.write(JSON.stringify(render(candidate())));",
        ],
        cwd=HERE.parents[2],
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def environment(files, key="a"):
    p = files["deployment.json"]["practices"][key]
    host = f"psql-cews-stg-mock5678-{key}.postgres.database.azure.com"
    return {
        **p["api_env"],
        "WORKSPACE_TEAM_SETUP_ENABLED": "true",
        "EXPECTED_SCHEMA_REVISION": files["deployment.json"]["expected_schema_revision"],
        "RESERVED_OWNER_SUBJECT": p["plan"]["owner_subject"],
        "BOX_POSTGRES_HOST": host,
        "DATABASE_ADMIN_URL": f"postgresql+psycopg://box_bootstrap:invented-admin-password-1234@{host}:5432/cosmas_os?sslmode=verify-full&sslrootcert=system",
        "DATABASE_URL": f"postgresql+psycopg://box_runtime:invented-runtime-password-5678@{host}:5432/cosmas_os?sslmode=verify-full&sslrootcert=system",
        "REDIS_URL": f"rediss://:invented@redis-cews-stg-mock5678-{key}.eastus2.redis.azure.net:10000/0?ssl_cert_reqs=required",
        "AZURE_STORAGE_ACCOUNT_URL": f"https://stcewsmock5678{key}.blob.core.windows.net",
        "AZURE_BLOB_CONTAINER": "box-artifacts",
        "WORKSPACE_ENROLLMENT_ADMISSION_SECRET": "e" * 64,
        "OWNER_MANIFEST_SHA256": p["owner_manifest_sha256"],
        "OWNER_MANIFEST": json.dumps(files[f"owner-{key}.json"], indent=2) + "\n",
    }


def test_rendered_runtime_matches_existing_hosted_configuration(files):
    from cosmas_os.config import Settings

    for key in ("a", "b"):
        runtime = Settings(
            _env_file=None,
            **{name.lower(): value for name, value in environment(files, key).items()},
        )
        assert runtime.runtime_configuration_errors() == [], " | ".join(
            runtime.runtime_configuration_errors()
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("DATA_MODE", "production"),
        ("BOX_POSTGRES_HOST", "central.postgres.database.azure.com"),
        ("BETA_BOX_ID", "00000000-0000-4000-8000-000000000000"),
        ("EXPECTED_SCHEMA_REVISION", "unreviewed-head"),
        ("CLERK_AUDIENCE", "named-template"),
    ],
)
def test_job_refuses_before_database_or_readiness(files, monkeypatch, field, value):
    env = environment(files)
    env[field] = value
    monkeypatch.setattr(
        job, "prepare_beta_database", lambda *_a, **_k: pytest.fail("DDL before binding")
    )
    with pytest.raises(ValueError):
        job.run("migrate", env)


def test_private_url_preparation_is_separate_and_all_inputs_checked_first(tmp_path):
    directory = tmp_path / "private"
    prepare.prepare(directory)
    key = tmp_path / "redis.key"
    prepare.write_private(key, b"\n")
    with pytest.raises(ValueError):
        prepare.urls(
            directory, "mock5678", "a", "redis-cews-stg-mock5678-a.eastus2.redis.azure.net", key
        )
    assert not list(directory.glob("*.url"))
    key.unlink()
    prepare.write_private(key, b"invented-not-a-live-key")
    for slot in ("a", "b"):
        result = prepare.urls(
            directory,
            "mock5678",
            slot,
            f"redis-cews-stg-mock5678-{slot}.eastus2.redis.azure.net",
            key,
        )
        assert not result["seeded"] and not result["qualified"]
    assert prepare.read_private(directory / "admin-a.url") != prepare.read_private(
        directory / "admin-b.url"
    )
    assert prepare.read_private(directory / "admin-a.password") != prepare.read_private(
        directory / "runtime-a.password"
    )
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in directory.iterdir())


def test_wrong_box_secret_refused_before_any_azure_call(files, tmp_path, monkeypatch):
    value = tmp_path / "value"
    prepare.write_private(value, environment(files, "b")["DATABASE_URL"].encode())
    monkeypatch.setattr(
        seed.subprocess, "run", lambda *_a, **_k: pytest.fail("Azure call before Box validation")
    )
    with pytest.raises(ValueError):
        seed.seed(files["deployment.json"], "a", "database-url", value, tmp_path / "reference")
    assert not (tmp_path / "reference").exists()


def test_arm_seed_transports_only_protected_parameter_file_and_returns_reference(
    files, tmp_path, monkeypatch
):
    d = files["deployment.json"]
    from pydantic import SecretStr

    from cosmas_os.enrollment import provisioning
    from cosmas_os.enrollment.admission import derive_runtime_admission_key
    from cosmas_os.enrollment.provisioning import WorkspacePlan

    plan = WorkspacePlan(**d["practices"]["a"]["plan"])
    master = "synthetic-admission-master-never-live"
    value = derive_runtime_admission_key(
        master, plan.practice_id, plan.box_id, plan.organization_id
    )
    path = tmp_path / "value"
    # Exercise the real protected CLI writer, then the new seeder boundary.
    settings = SimpleNamespace(
        registration_errors=lambda: [],
        provisioning_enabled=True,
        database_url=SecretStr("sqlite://"),
        runtime_admission_secret=SecretStr(master),
        clerk_secret_key=SecretStr("sk_test_invented"),
    )
    with monkeypatch.context() as patch:
        patch.setattr(provisioning, "EnrollmentSettings", lambda: settings)
        patch.setattr(
            provisioning, "create_engine", lambda *_a, **_k: SimpleNamespace(dispose=lambda: None)
        )
        patch.setattr(provisioning, "schema_ready", lambda _engine: True)
        patch.setattr(provisioning, "sessionmaker", lambda *_a, **_k: None)
        patch.setattr(provisioning, "EnrollmentService", lambda *_a: None)
        patch.setattr(provisioning, "ClerkProvisioningPort", lambda _key: None)
        patch.setattr(
            provisioning,
            "EnrollmentProvisioner",
            lambda *_a: SimpleNamespace(saved_plan=lambda _id: plan),
        )
        patch.setattr(
            sys,
            "argv",
            [
                "provisioning",
                "prepare-admission-key",
                "--practice-id",
                plan.practice_id,
                "--output",
                str(path),
            ],
        )
        assert provisioning.main() == 0
    assert prepare.read_private(path) == (value + "\n").encode()
    calls = []
    reference = (
        "https://kv-cews-mock5678-a.vault.azure.net/secrets/enrollment-admission-key/" + "e" * 32
    )

    def run(args, **kwargs):
        calls.append(args)
        assert value not in " ".join(args)
        assert kwargs["capture_output"] and kwargs["check"]
        if args[1:3] == ["account", "show"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "id": d["foundation"]["subscription_id"],
                        "tenantId": d["foundation"]["tenant_id"],
                        "state": "Enabled",
                    }
                ).encode()
            )
        if args[1:4] == ["deployment", "group", "create"]:
            parameters = Path(args[args.index("--parameters") + 1][1:])
            payload = json.loads(prepare.read_private(parameters))
            assert parameters.parent.stat().st_mode & 0o777 == 0o700
            assert payload["secretValue"]["value"] == value
            assert payload["vaultName"]["value"] == "kv-cews-mock5678-a"
            return SimpleNamespace(stdout=b"")
        assert args[1:3] == ["resource", "show"] and "properties.secretUriWithVersion" in args
        return SimpleNamespace(stdout=reference.encode())

    monkeypatch.setattr(seed.subprocess, "run", run)
    receipt = seed.seed(d, "a", "enrollment-admission-key", path, tmp_path / "reference")
    assert len(calls) == 3 and receipt["reference"] == reference and not receipt["value_returned"]
    assert value not in json.dumps(receipt)


@pytest.mark.parametrize("frame", ["leading", "double-lf", "crlf", "tab"])
def test_key_whitespace_and_owner_manifest_bytes_stay_strict(files, tmp_path, monkeypatch, frame):
    value = "d" * 64
    variants = {
        "leading": " " + value,
        "double-lf": value + "\n\n",
        "crlf": value + "\r\n",
        "tab": value + "\t",
    }
    path = tmp_path / "invalid-key"
    prepare.write_private(path, variants[frame].encode())
    monkeypatch.setattr(
        seed.subprocess, "run", lambda *_a, **_k: pytest.fail("Azure call for invalid key framing")
    )
    with pytest.raises(ValueError):
        seed.seed(
            files["deployment.json"], "a", "enrollment-admission-key", path, tmp_path / "reference"
        )
    raw = environment(files)["OWNER_MANIFEST"]
    seed.validate_value(files["deployment.json"], "a", "owner-manifest", raw)
    with pytest.raises(ValueError):
        seed.validate_value(files["deployment.json"], "a", "owner-manifest", raw[:-1])


@contextmanager
def postgres(directory):
    """Own a fresh loopback-only cluster; never inspect or stop another service."""
    binaries = Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
    directory.mkdir(mode=0o700)
    password = directory / "bootstrap.password"
    prepare.write_private(password, b"invented-admin-password-1234")
    data = directory / "data"
    subprocess.run(
        [
            str(binaries / "initdb"),
            "-D",
            str(data),
            "--username=box_bootstrap",
            "--auth-local=trust",
            "--auth-host=scram-sha-256",
            "--pwfile",
            str(password),
        ],
        check=True,
        capture_output=True,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    subprocess.run(
        [
            str(binaries / "pg_ctl"),
            "-D",
            str(data),
            "-l",
            str(directory / "postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {port} -k ''",
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    admin = f"postgresql+psycopg://box_bootstrap:invented-admin-password-1234@127.0.0.1:{port}/cosmas_os"
    try:
        engine = create_engine(
            admin.replace("/cosmas_os", "/postgres"), isolation_level="AUTOCOMMIT"
        )
        with engine.connect() as connection:
            connection.execute(text("CREATE DATABASE cosmas_os"))
        engine.dispose()
        runtime = (
            make_url(admin)
            .set(username="box_runtime", password="invented-runtime-password-5678")
            .render_as_string(hide_password=False)
        )
        yield admin, runtime
    finally:
        subprocess.run(
            [str(binaries / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"],
            check=True,
            capture_output=True,
        )


@pytest.mark.skipif(
    os.environ.get("ENROLLMENT_WORKSPACE_LOCAL_REHEARSAL") != "1",
    reason="Explicit owned loopback HTTP check only",
)
def test_static_practice_http_preserves_approval_page_browser_headers(
    tmp_path, monkeypatch, capsys
):
    static = load("serve_web")
    bundle = tmp_path / "public-dist"
    bundle.mkdir()
    (bundle / "index.html").write_text("<!doctype html><title>Invented practice</title>")
    monkeypatch.setattr(static, "ROOT", bundle)
    server = static.ThreadingHTTPServer(("127.0.0.1", 0), static.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}") as client:
            for path, status in (
                ("/chief?login_hint=invented", 200),
                ("/healthz", 200),
                ("/missing.js", 404),
            ):
                response = client.get(path)
                assert response.status_code == status
                assert response.headers["x-content-type-options"] == "nosniff"
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["referrer-policy"] == "no-referrer"
                assert response.headers["x-frame-options"] == "DENY"
                assert (
                    response.headers["strict-transport-security"]
                    == "max-age=31536000; includeSubDomains"
                )
                assert (
                    response.headers["permissions-policy"]
                    == "camera=(), geolocation=(), microphone=(), payment=()"
                )
                assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
        assert "login_hint" not in capsys.readouterr().err
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.skipif(
    os.environ.get("ENROLLMENT_WORKSPACE_LOCAL_REHEARSAL") != "1",
    reason="Explicit disposable loopback PostgreSQL rehearsal only",
)
def test_two_real_databases_private_jobs_then_signed_owner_setup_and_trial(
    files, tmp_path, monkeypatch
):
    from cosmas_os.adapters.enrollment_admission import EnrollmentAdmissionAdapter
    from cosmas_os.api import app as api
    from cosmas_os.api.auth import ClerkTokenVerifier
    from cosmas_os.config import Settings
    from cosmas_os.enrollment.admission import derive_runtime_admission_key
    from cosmas_os.enrollment.domain import EnrollmentError, HumanIdentity
    from cosmas_os.enrollment.models import Practice
    from cosmas_os.enrollment.provisioning import EnrollmentProvisioner
    from cosmas_os.enrollment.synthetic import create_synthetic_app
    from cosmas_os.models import BoxContext, ExternalIdentity, Principal
    from cosmas_os.practice_setup_models import PracticeOwnerReservation, PracticeSetupProfile

    central = create_synthetic_app()
    service, identities = central.state.enrollment_service, central.state.synthetic_identities
    import jwt

    subjects = {"owner-a": "user_examplea", "owner-b": "user_exampleb"}
    original_token = identities.token

    def fixture_token(user, organization_id=None, page_origin=None):
        claims = jwt.decode(
            original_token(user, organization_id),
            identities.key.public_key(),
            algorithms=["RS256"],
            issuer=service.settings.clerk_issuer,
        )
        claims["sub"] = subjects[user]
        if page_origin:
            claims["azp"] = page_origin
        return jwt.encode(claims, identities.key, algorithm="RS256", headers={"kid": "synthetic"})

    def fixture_verify(token):
        claims = jwt.decode(
            token,
            identities.key.public_key(),
            algorithms=["RS256"],
            issuer=service.settings.clerk_issuer,
        )
        user = next(user for user, subject in subjects.items() if subject == claims["sub"])
        email, name = identities.users[user]
        return HumanIdentity(claims["iss"], claims["sub"], claims["sid"], email, name)

    def fixture_member(subject, organization_id):
        user = next(user for user, candidate in subjects.items() if candidate == subject)
        email, name = identities.users[user]
        return HumanIdentity(service.settings.clerk_issuer, subject, "", email, name)

    def fixture_scoped(token, organization_id, *, authorized_parties=None):
        claims = jwt.decode(
            token,
            identities.key.public_key(),
            algorithms=["RS256"],
            issuer=service.settings.clerk_issuer,
        )
        if (
            claims.get("org_id") != organization_id
            or "aud" in claims
            or claims.get("azp") not in (authorized_parties or [service.settings.public_app_origin])
        ):
            raise EnrollmentError("runtime_scope_denied", "Synthetic fixture scope differs.", 403)
        return fixture_verify(token)

    monkeypatch.setattr(identities, "token", fixture_token)
    monkeypatch.setattr(identities, "verify", fixture_verify)
    monkeypatch.setattr(identities, "verify_registered_member", fixture_member)
    monkeypatch.setattr(identities, "verify_scoped", fixture_scoped)
    # The synthetic factory stays separate. These fixtures never call live Clerk.
    service.settings.allowed_workspace_origins = [
        "https://practice-a.staging.cosmas.ai",
        "https://practice-b.staging.cosmas.ai",
    ]
    organizations = {}

    class Clerk:
        def organization(self, slug, binding, name, owner, seats):
            org = {
                "id": "org_synthetic" + binding["practice_id"].replace("-", ""),
                "slug": slug,
                "created_by": owner,
                "private_metadata": {"cosmas_enrollment": binding},
            }
            organizations[org["id"]] = org
            return org

        def membership(self, org, subject, role):
            identities.verify_registered_member(subject, org)

        def request(self, method, path):
            assert method == "GET"
            return organizations[path.rsplit("/", 1)[-1]]

    provisioner = EnrollmentProvisioner(service, Clerk())
    completed = []
    with (
        TestClient(central) as control,
        postgres(tmp_path / "box-a") as a,
        postgres(tmp_path / "box-b") as b,
    ):
        for slot, urls in zip(("a", "b"), (a, b), strict=True):
            token = identities.token("owner-" + slot)
            headers = {
                "Authorization": "Bearer " + token,
                "X-Cosmas-Enrollment-Contract": "enrollment.v1",
            }

            def write(path, body, method="POST", headers=headers):
                state = control.get("/enrollment/v1/status", headers=headers).json()
                response = control.request(
                    method,
                    "/enrollment/v1" + path,
                    headers={**headers, "Idempotency-Key": str(uuid4())},
                    json={"expected_revision": state["revision"], **body},
                )
                assert response.status_code == 200, response.text
                return response.json()

            write("/profile", {"display_name": "Example Owner " + slot, "title": "Owner"}, "PUT")
            state = write(
                "/practice",
                {
                    "legal_name": "Example Practice " + slot,
                    "display_name": "Example Practice " + slot,
                    "address_line1": "1 Example Street",
                    "city": "Example",
                    "region": "NY",
                    "postal_code": "10001",
                    "administrative_email": "office@example.invalid",
                    "human_seats": 1,
                    "covered_entity": True,
                },
                "PUT",
            )
            document = control.get("/enrollment/v1/baa/current", headers=headers).json()
            write(
                "/baa/accept",
                {
                    "doc_id": document["doc_id"],
                    "version": document["version"],
                    "sha256": document["sha256"],
                    "signature_name": "Example Owner " + slot,
                    "signature_title": "Owner",
                    "authority_confirmed": True,
                    "accepted": True,
                },
            )
            plan = provisioner.prepare(
                state["practice"]["id"],
                api_origin=f"https://api.practice-{slot}.staging.cosmas.ai",
                workspace_url=f"https://practice-{slot}.staging.cosmas.ai/chief",
                source_commit="1" * 40,
                image_sha256="a" * 64,
            )
            revision = control.get("/enrollment/v1/status", headers=headers).json()["revision"]
            blocked = control.post(
                "/enrollment/v1/checkout",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"expected_revision": revision},
            )
            assert blocked.status_code == 409
            assert not any(
                item["client_reference_id"] == plan.practice_id
                for item in central.state.synthetic_commerce.sessions.values()
            )
            env = environment(files, slot)
            env.update(
                {
                    "BETA_BOX_ID": plan.box_id,
                    "WORKSPACE_ENROLLMENT_PRACTICE_ID": plan.practice_id,
                    "CLERK_ISSUER": plan.issuer,
                    "CLERK_JWKS_URL": plan.issuer + "/.well-known/jwks.json",
                    "CLERK_ORGANIZATION_ID": plan.organization_id,
                    "CLERK_AUTHORIZED_PARTIES": service.settings.public_app_origin
                    + ","
                    + files["deployment.json"]["practices"][slot]["web_origin"],
                    "CORS_ALLOWED_ORIGINS": service.settings.public_app_origin
                    + ","
                    + files["deployment.json"]["practices"][slot]["web_origin"],
                    "WORKSPACE_ENROLLMENT_API_ORIGIN": "https://enrollment.example.invalid",
                    "WORKSPACE_ENROLLMENT_ACCOUNT_ORIGIN": service.settings.public_app_origin,
                    "WORKSPACE_ENROLLMENT_ORIGIN_ALLOWLIST": "https://enrollment.example.invalid,"
                    + service.settings.public_app_origin,
                    "RESERVED_OWNER_SUBJECT": plan.owner_subject,
                    "WORKSPACE_ENROLLMENT_ADMISSION_SECRET": derive_runtime_admission_key(
                        service.settings.runtime_admission_secret.get_secret_value(),
                        plan.practice_id,
                        plan.box_id,
                        plan.organization_id,
                    ),
                }
            )
            manifest = {
                **files[f"owner-{slot}.json"],
                "box_id": plan.box_id,
                "clerk_issuer": plan.issuer,
                "clerk_organization_id": plan.organization_id,
                "clerk_subject": plan.owner_subject,
            }
            env["OWNER_MANIFEST"] = json.dumps(manifest, indent=2) + "\n"
            env["OWNER_MANIFEST_SHA256"] = hashlib.sha256(
                env["OWNER_MANIFEST"].encode()
            ).hexdigest()
            runtime = Settings(_env_file=None, **{key.lower(): value for key, value in env.items()})
            assert runtime.runtime_configuration_errors() == [], " | ".join(
                runtime.runtime_configuration_errors()
            )
            admin, restricted = urls
            with monkeypatch.context() as patch:
                patch.setattr(
                    job,
                    "prepare_beta_database",
                    lambda *_args, admin=admin, restricted=restricted: job_original_prepare(
                        admin, restricted, require_verify_full=False
                    ),
                )
                migration = job.run("migrate", env)
                assert (
                    migration["database"]["schema_at_expected_head"]
                    and migration["database"]["runtime_role_non_admin"]
                )
                patch.setattr(job, "Settings", lambda runtime=runtime: runtime)
                patch.setattr(
                    job,
                    "create_engine",
                    lambda *_args, admin=admin, **_kwargs: create_engine(
                        admin, hide_parameters=True
                    ),
                )
                reservation = job.run("reserve", env)
                assert reservation["owner_reserved"] and not reservation["workspace_ready"]
            sessions = sessionmaker(create_engine(restricted), expire_on_commit=False)
            with sessions() as session:
                assert session.scalar(select(func.count()).select_from(Principal)) == 0
                assert session.scalar(select(func.count()).select_from(BoxContext)) == 1
                assert not session.get(PracticeOwnerReservation, plan.box_id).consumed_at
                with pytest.raises(DBAPIError):
                    session.execute(
                        text("UPDATE practice_owner_reservations SET subject='forged' WHERE false")
                    )
                session.rollback()
            scoped = identities.token("owner-" + slot, plan.organization_id)

            class Keys:
                def get_signing_keys(self, refresh):
                    return [SimpleNamespace(key_id="synthetic", key=identities.key.public_key())]

            verifier = ClerkTokenVerifier(
                runtime, jwks_client=Keys(), start_background_refresh=False
            )

            def admission_transport(request):
                result = Context().run(
                    control.post,
                    request.url.path,
                    content=request.content,
                    headers=dict(request.headers),
                )
                return httpx.Response(
                    result.status_code, content=result.content, headers=dict(result.headers)
                )

            adapter = EnrollmentAdmissionAdapter(
                runtime, client=httpx.Client(transport=httpx.MockTransport(admission_transport))
            )
            with monkeypatch.context() as patch:
                patch.setattr(api, "settings", runtime)
                patch.setattr(api, "SessionLocal", sessions)
                patch.setattr(api, "_clerk_verifier", lambda *_args, verifier=verifier: verifier)
                patch.setattr(api, "_runtime_admission_adapter", lambda adapter=adapter: adapter)
                from cosmas_os.application import enrollment_access

                patch.setattr(
                    enrollment_access,
                    "EnrollmentAdmissionAdapter",
                    lambda _runtime, adapter=adapter: adapter,
                )

                api.app.dependency_overrides[api.get_session] = session_dependency(sessions)
                try:
                    with TestClient(api.app) as workspace:

                        def runtime_transport(request):
                            response = Context().run(
                                workspace.request,
                                request.method,
                                request.url.path,
                                headers=dict(request.headers),
                                content=request.content,
                            )
                            return httpx.Response(
                                response.status_code,
                                content=response.content,
                                headers=dict(response.headers),
                            )

                        http = httpx.Client(transport=httpx.MockTransport(runtime_transport))
                        auth = {
                            "Authorization": "Bearer " + scoped,
                            "X-Cosmas-Workspace-Protocol": "1",
                            "X-Cosmas-Practice-Access-Contract": "1",
                        }
                        assert workspace.get("/account/identity", headers=auth).status_code == 403
                        assert (
                            workspace.get(
                                "/practice-access/enrollment-qualification", headers=auth
                            ).status_code
                            == 403
                        )
                        proof = provisioner.qualify_member(
                            plan, subject=plan.owner_subject, bearer=scoped, client=http
                        )
                        assert proof["receipt"]["observations"][
                            "/practice-access/enrollment-qualification"
                        ]["initial_setup_complete"]
                        with sessions() as session:
                            assert session.get(PracticeOwnerReservation, plan.box_id).consumed_at
                            assert session.get(PracticeSetupProfile, plan.box_id)
                            assert session.scalar(
                                select(ExternalIdentity).where(
                                    ExternalIdentity.subject == plan.owner_subject
                                )
                            )
                            assert session.scalar(select(func.count()).select_from(Principal)) == 1
                        assert workspace.get("/account/identity", headers=auth).status_code == 403
                        checkout = write("/checkout", {})
                        assert checkout["status"] == "open"
                        assert workspace.get("/account/identity", headers=auth).status_code == 403
                        session_id = next(
                            key
                            for key, value in central.state.synthetic_commerce.sessions.items()
                            if value["client_reference_id"] == plan.practice_id
                        )
                        assert (
                            control.post(
                                "/lab/checkout/complete", json={"session_id": session_id}
                            ).status_code
                            == 200
                        )
                        # The account-origin bootstrap token cannot grant ordinary
                        # workspace access. Obtain a fresh token at the Box origin.
                        assert workspace.get("/account/identity", headers=auth).status_code == 403
                        workspace_token = fixture_token(
                            "owner-" + slot,
                            plan.organization_id,
                            plan.workspace_url.removesuffix("/chief"),
                        )
                        auth["Authorization"] = "Bearer " + workspace_token
                        assert workspace.get("/account/identity", headers=auth).status_code == 200
                        other = identities.token(
                            "owner-b" if slot == "a" else "owner-a",
                            plan.organization_id,
                            plan.workspace_url.removesuffix("/chief"),
                        )
                        assert (
                            workspace.get(
                                "/account/identity",
                                headers={**auth, "Authorization": "Bearer " + other},
                            ).status_code
                            == 403
                        )
                        with service.sessions.begin() as session:
                            session.get(Practice, plan.practice_id).subscription_status = "canceled"
                        assert workspace.get("/account/identity", headers=auth).status_code == 403
                        assert (
                            workspace.get("/config").json()["enrollment_recovery_url"]
                            == service.settings.public_app_origin + "/onboarding"
                        )
                        recovered = write("/recover", {})
                        assert recovered["billing"]["status"] == "trialing"
                        assert workspace.get("/account/identity", headers=auth).status_code == 200
                finally:
                    api.app.dependency_overrides.pop(api.get_session, None)
            sessions.kw["bind"].dispose()
            completed.append(asdict(plan))
        assert (
            len({item["box_id"] for item in completed})
            == len({item["organization_id"] for item in completed})
            == 2
        )
        for admin, _runtime in (a, b):
            engine = create_engine(admin)
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT count(*) FROM box_contexts")) == 1
            engine.dispose()


job_original_prepare = job.prepare_beta_database
