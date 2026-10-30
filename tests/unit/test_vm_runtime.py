"""No containers/cloud: current Settings, real certificate checks, Compose parser."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

RUNTIME = Path(__file__).resolve().parents[2] / "infra/beta/vm/runtime"
sys.path.insert(0, str(RUNTIME))
try:
    SPEC = importlib.util.spec_from_file_location("cosmas_vm_renderer", RUNTIME / "render.py")
    vm = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(vm)
    import entrypoint
finally:
    sys.path.remove(str(RUNTIME))

PASSWORD = "SyntheticOnlyPassword_0123456789_AbCdEf"
ADMIN = "SyntheticOnlyAdmin_9876543210_aBcDeF"
REDIS_PASSWORD = "SyntheticOnlyBroker_0123456789_ZyXwVu"


def certificate(common, issuer=None, issuer_key=None, *, expired=False, authority_key_id=True):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer.subject if issuer else name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=3))
        .not_valid_after(now + timedelta(days=-1 if expired else 7))
        .add_extension(x509.BasicConstraints(ca=issuer is None, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=issuer is not None,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=issuer is None,
                crl_sign=issuer is None,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
    )
    if authority_key_id:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key((issuer_key or key).public_key()),
            critical=False,
        )
    if issuer:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common)]), critical=False
        ).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    return key, builder.sign(issuer_key or key, hashes.SHA256())


def private(path, value):
    path.write_text(value)
    path.chmod(0o400)


@pytest.fixture
def installed(tmp_path, monkeypatch):
    # The fixture uses this user's UID only; production CLI requires 0/10001/999.
    for module, name in (
        (entrypoint, "API_UID"),
        (vm, "API_UID"),
        (vm, "DATA_UID"),
        (vm, "ROOT_UID"),
    ):
        monkeypatch.setattr(module, name, os.getuid())
    root = tmp_path / "protected" / "synthetic-review"
    root.mkdir(parents=True, mode=0o700)
    for service in ("api", "worker", "prepare", "postgres", "redis", "tls"):
        (root / service).mkdir(mode=0o700)
    _, _, _, booleans = entrypoint.setting_contract()
    environment = {name: "false" for name in booleans}
    environment.update(entrypoint.BASE)
    environment.update(
        {
            "WORKSPACE_TEAM_SETUP_ENABLED": "true",
            "WORKSPACE_ROUTINES_ENABLED": "true",
            "WORKSPACE_LLM_BACKEND": "azure_gpt41",
            "CORS_ALLOWED_ORIGINS": "https://staging.cosmas.ai",
            "CLERK_AUTHORIZED_PARTIES": "https://staging.cosmas.ai",
            "CLERK_ISSUER": "https://clerk.synthetic.invalid",
            "CLERK_JWKS_URL": "https://clerk.synthetic.invalid/.well-known/jwks.json",
            "CLERK_ORGANIZATION_ID": "org_synthetic",
            "CLERK_AUDIENCE": "cosmas-synthetic",
            "BETA_BOX_ID": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "AZURE_STORAGE_ACCOUNT_URL": "https://syntheticobjects.blob.core.windows.net",
            "AZURE_BLOB_CONTAINER": "synthetic",
        }
    )
    config = {
        "version": 1,
        "release_id": "synthetic-review",
        "source_commit": "a" * 40,
        "images": {
            "api": "syntheticacr.azurecr.io/api@sha256:" + "1" * 64,
            "web": "syntheticacr.azurecr.io/web@sha256:" + "2" * 64,
            "postgres": "postgres:16.13-bookworm@sha256:" + "3" * 64,
            "redis": "redis:7.2.13-bookworm@sha256:" + "4" * 64,
            "proxy": "caddy:2.10.2-alpine@sha256:" + "5" * 64,
        },
        "web_origin": "https://staging.cosmas.ai",
        "api_origin": "https://api.staging.cosmas.ai",
        "runtime": {
            "environment": environment,
            "secret_names": ["HUMAN_DEPLOY_EVIDENCE_REF", "WORKSPACE_LLM_API_KEY"],
            "runtime_identity_client_id": "aaaaaaaa-bbbb-4ccc-8ddd-ffffffffffff",
        },
        "tls_sha256": {},
        "image_review_reference": "synthetic-review:invented-not-images",
    }
    for service in ("api", "worker"):
        for name, value in {
            "DATABASE_PASSWORD": PASSWORD,
            "REDIS_PASSWORD": REDIS_PASSWORD,
            "HUMAN_DEPLOY_EVIDENCE_REF": "invented-owner-review",
            "WORKSPACE_LLM_API_KEY": "invented-model-secret-no-provider",
        }.items():
            private(root / service / name, value)
    private(root / "postgres/POSTGRES_PASSWORD", ADMIN)
    private(root / "prepare/POSTGRES_PASSWORD", ADMIN)
    private(root / "prepare/DATABASE_PASSWORD", PASSWORD)
    private(root / "redis/REDIS_PASSWORD", REDIS_PASSWORD)
    private(
        root / "redis/users.acl",
        "user default reset on #"
        + hashlib.sha256(REDIS_PASSWORD.encode()).hexdigest()
        + " ~* &* +@all",
    )
    ca_key, ca = certificate("Synthetic private root")
    _, public_ca = certificate("Synthetic substitute for image public root bundle")
    (root / "tls/private-ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (root / "tls/public-roots.pem").write_bytes(public_ca.public_bytes(serialization.Encoding.PEM))
    for service in ("postgres", "redis"):
        key, cert = certificate(service, ca, ca_key)
        private(
            root / service / "server.key",
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
        )
        (root / "tls" / f"{service}.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    config["tls_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "tls").iterdir()
    }
    output = tmp_path / "release" / config["release_id"]
    output.parent.mkdir()
    return config, root, output


def test_render_runs_real_settings_and_compose_parser_without_secret_output(installed):
    config, root, output = installed
    vm.render(config, root, output, Path("/var/lib/cosmabot"))
    document = json.loads((output / "compose.json").read_text())
    services = document["services"]
    assert set(services) == {
        "api",
        "worker",
        "web",
        "postgres",
        "redis",
        "proxy",
        "database_prepare",
    }
    assert services["api"]["entrypoint"][-1] == "api"
    assert services["worker"]["entrypoint"][-1] == "worker"
    assert services["api"]["image"] == services["worker"]["image"]
    assert services["database_prepare"]["profiles"] == ["prepare"]
    assert services["database_prepare"]["networks"] == {
        "backend": {"ipv4_address": "172.30.240.12"}
    }
    assert all("ports" not in service for name, service in services.items() if name != "proxy")
    assert all(
        service["read_only"] and service["cap_drop"] == ["ALL"] for service in services.values()
    )
    assert (
        document["networks"]["backend"]["internal"] and document["networks"]["frontend"]["internal"]
    )
    assert (
        "egress" not in services["postgres"]["networks"]
        and "egress" not in services["web"]["networks"]
    )
    for path in output.iterdir():
        raw = path.read_bytes()
        assert all(
            secret.encode() not in raw
            for secret in [PASSWORD, ADMIN, REDIS_PASSWORD, "invented-model-secret-no-provider"]
        )
    executable = shutil.which("docker-compose")
    if executable is None:
        pytest.skip("Standalone Compose parser not installed")
    result = subprocess.run(
        [
            executable,
            "-f",
            str(output / "compose.json"),
            "--profile",
            "prepare",
            "config",
            "--quiet",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_only_proxy_adds_capability_required_by_official_caddy(installed):
    config, root, output = installed
    services = vm.compose(config, output, root, Path("/var/lib/cosmabot"))["services"]
    for name, service in services.items():
        assert service["cap_drop"] == ["ALL"]
        assert service.get("cap_add", []) == (["NET_BIND_SERVICE"] if name == "proxy" else [])
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["read_only"] is True
    proxy = services["proxy"]
    assert proxy["user"] == "10001:10001"
    assert proxy["ports"] == ["80:8080", "443:8443"]
    assert set(proxy["networks"]) == {"frontend", "egress"}
    assert "http_port 8080" in vm.caddy(config)
    assert "https_port 8443" in vm.caddy(config)


@pytest.mark.parametrize("version", [1, 2])
def test_backup_profile_preserves_app_access_and_binds_rendered_files(installed, version):
    config, root, output = installed
    config["version"] = version
    if version == 2:
        config["postgres_backup"] = {
            "mode": "wal-g-host-v1", "host_address": "172.30.240.1/32"
        }
    vm.render(config, root, output, Path("/var/lib/cosmabot"))
    postgres = (output / "postgresql.conf").read_bytes()
    hba = (output / "pg_hba.conf").read_bytes()
    receipt = json.loads((output / "RENDER.json").read_text())
    for name, raw in (("postgresql.conf", postgres), ("pg_hba.conf", hba)):
        assert receipt["files"][name] == hashlib.sha256(raw).hexdigest()
    if version == 1:
        # Exact configuration of existing releases before backup support.
        assert hashlib.sha256(postgres).hexdigest() == (
            "1fb92a6eecb607dbc63553b448b2e3af1bb200b53c65a872d6244d5bb9bb3dca"
        )
        assert hashlib.sha256(hba).hexdigest() == (
            "a7d00896c8e3a97fd3479928721728c167ce722ab6f88d5907896b0c64f97193"
        )
    else:
        lines = hba.decode().splitlines()
        backup_rules = [line for line in lines if "cosmabot_backup" in line]
        assert {tuple(line.split()) for line in backup_rules} == {
            ("hostssl", database, "cosmabot_backup", "172.30.240.1/32", "scram-sha-256")
            for database in ("postgres", "replication")
        }
        assert "\n".join(line for line in lines if line not in backup_rules) + "\n" == vm.PG_HBA
        assert lines[-2:] == ["host all all 0.0.0.0/0 reject", "host all all ::/0 reject"]
        assert "max_slot_wal_keep_size = '4096MB'" in postgres.decode()
    document = json.loads((output / "compose.json").read_text())
    assert "ports" not in document["services"]["postgres"]
    assert "postgres_backup" not in json.loads((output / "runtime.json").read_text())
    assert receipt["manifest_sha256"] == hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@pytest.mark.parametrize("profile", [
    None, True, {}, "wal-g-host-v1",
    {"mode": "wal-g-host-v1", "host_address": "172.30.240.0/24"},
    {"mode": "wal-g-host-v1", "host_address": "172.30.240.10/32"},
    {"mode": "wal-g-host-v1", "host_address": "172.30.240.1/32", "password": "invented"},
    {"mode": "other", "host_address": "172.30.240.1/32"},
])
def test_backup_profile_rejects_implicit_or_expanded_access(installed, profile):
    config, root, output = installed
    config.update(version=2, postgres_backup=profile)
    with pytest.raises(vm.Refused, match="exact_host_backup_profile"):
        vm.render(config, root, output, Path("/var/lib/cosmabot"))
    assert not output.exists()


@pytest.mark.parametrize("version, include_profile", [(1, True), (2, False), (True, False)])
def test_backup_profile_requires_explicit_manifest_version(installed, version, include_profile):
    config, root, output = installed
    config["version"] = version
    if include_profile:
        config["postgres_backup"] = dict(vm.POSTGRES_BACKUP)
    with pytest.raises(vm.Refused, match="manifest_shape"):
        vm.render(config, root, output, Path("/var/lib/cosmabot"))
    assert not output.exists()


def use_web_host(config, host):
    web = f"https://{host}"
    api = f"https://api.{host}"
    config["web_origin"] = web
    config["api_origin"] = api
    environment = config["runtime"]["environment"]
    environment["CORS_ALLOWED_ORIGINS"] = web
    environment["CLERK_AUTHORIZED_PARTIES"] = web
    return config


def test_beta_cosmas_host_renders_and_stays_synthetic(installed):
    config, root, output = installed
    use_web_host(config, "beta.cosmas.ai")
    vm.render(config, root, output, Path("/var/lib/cosmabot"))
    runtime = json.loads((output / "runtime.json").read_text())
    assert runtime["environment"]["DATA_MODE"] == "synthetic"
    assert runtime["environment"]["COSMAS_ENV"] == "early_adopter_beta"
    caddy = (output / "Caddyfile").read_text()
    assert "https://beta.cosmas.ai" in caddy
    assert "api.beta.cosmas.ai" in caddy
    assert "staging.cosmas.ai" not in caddy


@pytest.mark.parametrize(
    ("web", "api"),
    [
        ("https://app.cosmaneura.com", "https://api.cosmaneura.com"),
        ("https://cosmas.ai", "https://api.cosmas.ai"),
        ("https://www.cosmas.ai", "https://api.www.cosmas.ai"),
        ("https://app.cosmas.ai", "https://api.cosmas.ai"),
        ("https://foo.cosmaneura.com", "https://api.foo.cosmaneura.com"),
        ("https://random.example.invalid", "https://api.random.example.invalid"),
        ("https://beta.cosmas.ai", "https://api.staging.cosmas.ai"),
        ("https://staging.cosmas.ai", "https://api.beta.cosmas.ai"),
    ],
)
def test_vm_refuses_cosmas_addresses_and_random_hosts(installed, web, api):
    config, root, output = installed
    config["web_origin"] = web
    config["api_origin"] = api
    with pytest.raises(vm.Refused):
        vm.render(config, root, output, Path("/var/lib/cosmabot"))
    assert not output.exists()


@pytest.mark.parametrize(
    "updates",
    [
        {"DATA_MODE": "authorized_beta"},
        {"COSMAS_ENV": "production"},
    ],
)
def test_beta_host_cannot_leave_synthetic_mode(installed, updates):
    config, root, output = installed
    use_web_host(config, "beta.cosmas.ai")
    config["runtime"]["environment"].update(updates)
    with pytest.raises(vm.Refused):
        vm.render(config, root, output, Path("/var/lib/cosmabot"))
    assert not output.exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c["images"].update(api="syntheticacr.azurecr.io/api:latest"),
        lambda c: c["images"].update(postgres="postgres:17.3-bookworm@sha256:" + "3" * 64),
        lambda c: c.update(api_origin="http://api.staging.cosmas.ai"),
        lambda c: c["runtime"]["environment"].update(DATA_MODE="authorized_beta"),
        lambda c: c["runtime"]["environment"].update(AUTH_MODE="synth_headers"),
        lambda c: c["runtime"]["environment"].update(DATABASE_URL="postgresql://leaked-secret"),
        lambda c: c["runtime"]["environment"].update(SSL_CERT_FILE="/tmp/untrusted-ca.pem"),
        lambda c: c["runtime"]["environment"].update(WORKSPACE_UNKNOWN_ENABLED="true"),
        lambda c: c["runtime"]["environment"].pop("WORKSPACE_ROUTINES_ENABLED"),
    ],
)
def test_manifest_refuses_unsafe_or_implicit_profiles(installed, change):
    config, root, output = installed
    change(config)
    with pytest.raises(vm.Refused):
        vm.render(config, root, output, Path("/var/lib/cosmabot"))
    assert not output.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "world_readable",
        "symlink",
        "mixed_worker",
        "wrong_acl",
        "shared_admin",
        "wrong_certificate",
        "changed_ca",
    ],
)
def test_protected_input_failures_leave_no_candidate(installed, fault):
    config, root, output = installed
    if fault == "world_readable":
        (root / "api/DATABASE_PASSWORD").chmod(0o444)
    elif fault == "symlink":
        path = root / "api/DATABASE_PASSWORD"
        path.unlink()
        path.symlink_to(root / "worker/DATABASE_PASSWORD")
    elif fault == "mixed_worker":
        (root / "worker/DATABASE_PASSWORD").chmod(0o600)
        private(root / "worker/DATABASE_PASSWORD", ADMIN)
    elif fault == "wrong_acl":
        (root / "redis/users.acl").chmod(0o600)
        private(root / "redis/users.acl", "user default on nopass ~* +@all")
    elif fault == "shared_admin":
        for service in ("postgres", "prepare"):
            (root / service / "POSTGRES_PASSWORD").chmod(0o600)
            private(root / service / "POSTGRES_PASSWORD", PASSWORD)
    elif fault == "wrong_certificate":
        (root / "tls/postgres.crt").write_bytes((root / "tls/redis.crt").read_bytes())
        config["tls_sha256"]["postgres.crt"] = hashlib.sha256(
            (root / "tls/postgres.crt").read_bytes()
        ).hexdigest()
    else:
        (root / "tls/private-ca.pem").write_bytes((root / "tls/public-roots.pem").read_bytes())
    with pytest.raises(vm.Refused):
        vm.render(config, root, output, Path("/var/lib/cosmabot"))
    assert not output.exists()


def test_environment_ignores_operator_env_and_uses_verified_tls(installed, monkeypatch):
    config, root, _ = installed
    monkeypatch.setenv("DATABASE_URL", "postgresql://ambient-leak")
    monkeypatch.setenv("DATA_MODE", "authorized_beta")
    values = entrypoint.load_environment(config["runtime"], root / "api")
    assert values["DATABASE_URL"].endswith(
        "@postgres:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    )
    assert values["REDIS_URL"].endswith("@redis:6379/0?ssl_cert_reqs=required")
    assert values["DATA_MODE"] == "synthetic"
    assert values["AZURE_CLIENT_ID"] == config["runtime"]["runtime_identity_client_id"]
    assert "POSTGRES_PASSWORD" not in values and ADMIN not in values.values()


@pytest.mark.parametrize("role", ["prepare", "api", "worker"])
def test_exec_environment_pins_mounted_ca_and_discards_ambient_trust(installed, monkeypatch, role):
    config, root, _ = installed
    monkeypatch.setattr(sys, "argv", ["entrypoint.py", role])
    for name, value in {
        "SSL_CERT_FILE": "/tmp/untrusted-ca.pem",
        "SSL_CERT_DIR": "/tmp/untrusted-ca-directory",
        "PGSSLROOTCERT": "/tmp/untrusted-postgres-ca.pem",
        "PGSSLMODE": "disable",
    }.items():
        monkeypatch.setenv(name, value)

    def mounted_configuration(path):
        assert path == Path("/opt/cosmabot/runtime/runtime.json")
        return config["runtime"]

    read_private = entrypoint.read_private

    def mounted_secret(path, uid):
        assert path.parent == Path("/run/cosmabot/secrets")
        return read_private(root / role / path.name, uid)

    captured = {}

    def capture_exec(program, command, environment):
        captured.update(program=program, command=command, environment=environment)

    monkeypatch.setattr(entrypoint, "read_json", mounted_configuration)
    monkeypatch.setattr(entrypoint, "read_private", mounted_secret)
    monkeypatch.setattr(entrypoint.os, "execvpe", capture_exec)
    assert entrypoint.main() == 1  # Only the real exec is replaced; no process starts.
    environment = captured["environment"]
    assert captured["program"] == {"prepare": "python", "api": "uvicorn", "worker": "celery"}[role]
    assert environment["SSL_CERT_FILE"] == "/etc/ssl/certs/ca-certificates.crt"
    assert not {"SSL_CERT_DIR", "PGSSLROOTCERT", "PGSSLMODE"} & environment.keys()
    urls = ["DATABASE_URL", "DATABASE_ADMIN_URL"] if role == "prepare" else ["DATABASE_URL"]
    for name in urls:
        assert environment[name].endswith(
            "@postgres:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
        )
    if role != "prepare":
        assert "DATABASE_ADMIN_URL" not in environment
        assert environment["REDIS_URL"].endswith("@redis:6379/0?ssl_cert_reqs=required")


def test_certificate_hostname_and_trust_verified_even_when_hashes_match(installed):
    config, root, output = installed
    ca_key, ca = certificate("New synthetic root")
    key, wrong = certificate("wrong-private-host", ca, ca_key)
    (root / "tls/private-ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (root / "tls/postgres.crt").write_bytes(wrong.public_bytes(serialization.Encoding.PEM))
    (root / "postgres/server.key").chmod(0o600)
    private(
        root / "postgres/server.key",
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )
    for name in ("private-ca.pem", "postgres.crt"):
        config["tls_sha256"][name] = hashlib.sha256((root / "tls" / name).read_bytes()).hexdigest()
    with pytest.raises(vm.Refused, match="chain_or_hostname"):
        vm.render(config, root, output, Path("/var/lib/cosmabot"))


@pytest.mark.parametrize("malformed_service", ["postgres", "redis"])
def test_strict_certificate_check_rejects_missing_authority_key_id(installed, malformed_service):
    config, root, output = installed
    ca_key, ca = certificate("Synthetic strict verification root")
    (root / "tls/private-ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for service in ("postgres", "redis"):
        key, cert = certificate(service, ca, ca_key, authority_key_id=service != malformed_service)
        key_path = root / service / "server.key"
        key_path.chmod(0o600)
        private(
            key_path,
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
        )
        (root / "tls" / f"{service}.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    for name in ("private-ca.pem", "postgres.crt", "redis.crt"):
        config["tls_sha256"][name] = hashlib.sha256((root / "tls" / name).read_bytes()).hexdigest()
    # The previous chain/purpose/hostname check accepted this malformed leaf.
    permissive = subprocess.run(
        [
            "openssl",
            "verify",
            "-CAfile",
            str(root / "tls/private-ca.pem"),
            "-purpose",
            "sslserver",
            "-verify_hostname",
            malformed_service,
            str(root / "tls" / f"{malformed_service}.crt"),
        ],
        capture_output=True,
        check=False,
    )
    assert permissive.returncode == 0
    with pytest.raises(vm.Refused, match="service_certificate_chain_or_hostname"):
        vm.render(config, root, output, Path("/var/lib/cosmabot"))
    assert not output.exists()


def test_existing_release_is_never_overwritten(installed):
    config, root, output = installed
    output.mkdir()
    (output / "owner-file").write_text("retain")
    with pytest.raises(vm.Refused, match="new_release"):
        vm.render(config, root, output, Path("/var/lib/cosmabot"))
    assert (output / "owner-file").read_text() == "retain"


def test_duplicate_json_key_is_refused_without_reflecting_its_value(tmp_path):
    path = tmp_path / "ambiguous.json"
    path.write_text('{"runtime":{"mode":"safe","mode":"do-not-echo-this-value"}}')
    with pytest.raises(vm.Refused, match="duplicate_json_key") as refused:
        entrypoint.read_json(path)
    assert "do-not-echo-this-value" not in str(refused.value)


@pytest.mark.parametrize("fail_during_replacement", [False, True])
def test_imds_guard_installs_deny_before_replacement_and_has_only_two_exceptions(
    tmp_path, fail_during_replacement
):
    """Execute the actual shell, replacing only host commands with a netfilter model."""
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "id").write_text("#!/bin/sh\necho 0\n")
    (binary / "id").chmod(0o700)
    state = tmp_path / "rules.json"
    initial = {"DOCKER-USER": [["-j", "ACCEPT"]], "COSMABOT-IMDS": [["-j", "ACCEPT"]]}
    state.write_text(json.dumps(initial))
    (binary / "iptables").write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, sys
from pathlib import Path
path=Path(os.environ['RULES'])
rules=json.loads(path.read_text())
args=sys.argv[1:]
if args[0]=='-w': args=args[1:]
op,chain=args[:2]
rule=args[2:]
if os.environ.get('FAIL_REPLACE')=='yes' and op=='-A': sys.exit(1)
if op=='-S':
    if chain not in rules: sys.exit(1)
    print('-N '+chain)
    for r in rules[chain]: print('-A '+chain+' '+' '.join(r))
elif op=='-C': sys.exit(0 if rule in rules.get(chain,[]) else 1)
elif op=='-N': rules[chain]=[]
elif op=='-F': rules[chain]=[]
elif op=='-A': rules[chain].append(rule)
elif op=='-I': rules[chain].insert(int(rule[0])-1,rule[1:])
elif op=='-D': rules[chain].remove(rule)
else: sys.exit(2)
path.write_text(json.dumps(rules))
"""
    )
    (binary / "iptables").chmod(0o700)
    env = {
        "PATH": str(binary) + ":/usr/bin:/bin",
        "RULES": str(state),
        "FAIL_REPLACE": "yes" if fail_during_replacement else "no",
    }
    result = subprocess.run(
        ["/bin/sh", str(RUNTIME / "imds-guard.sh")], env=env, capture_output=True, text=True
    )
    rules = json.loads(state.read_text())
    first = rules["DOCKER-USER"][0]
    if fail_during_replacement:
        assert result.returncode != 0
        assert first == [
            "-d",
            "169.254.169.254/32",
            "-m",
            "comment",
            "--comment",
            "cosmabot-imds-install-deny",
            "-j",
            "REJECT",
        ]
    else:
        assert result.returncode == 0, result.stderr
        assert first == ["-d", "169.254.169.254/32", "-j", "COSMABOT-IMDS"]
        assert rules["COSMABOT-IMDS"] == [
            ["-i", "br-cm-egress", "-s", "172.30.241.10/32", "-j", "RETURN"],
            ["-i", "br-cm-egress", "-s", "172.30.241.11/32", "-j", "RETURN"],
            ["-j", "REJECT"],
        ]
        assert rules["DOCKER-USER"][-1] == ["-j", "ACCEPT"]  # Unrelated host policy retained.
        again = subprocess.run(
            ["/bin/sh", str(RUNTIME / "imds-guard.sh")], env=env, capture_output=True, text=True
        )
        assert again.returncode == 0 and json.loads(state.read_text()) == rules


@pytest.mark.parametrize(
    "inventory,inventory_exit,allowed",
    [
        pytest.param("", 0, True, id="empty-project"),
        pytest.param(
            "a1:postgres:running\nb2:redis:running\nc3:api:exited\nd4:worker:exited\n"
            "e5:web:dead\nf6:proxy:exited\na7:database_prepare:exited\nb8:old_service:dead",
            0,
            True,
            id="only-data-active",
        ),
        pytest.param("a1:api:running", 0, False, id="api-running"),
        pytest.param("a1:worker:restarting", 0, False, id="worker-restarting"),
        pytest.param("a1:api:paused", 0, False, id="api-paused"),
        pytest.param("a1:proxy:created", 0, False, id="proxy-created"),
        pytest.param("a1:worker:removing", 0, False, id="worker-removing"),
        pytest.param("a1:web:running", 0, False, id="web-running"),
        pytest.param("a1:database_prepare:running", 0, False, id="surviving-one-off"),
        pytest.param("a1:old_service:running", 0, False, id="active-orphan"),
        pytest.param("", 42, False, id="failed-empty-inventory"),
        pytest.param("a1:postgres:running", 42, False, id="failed-partial-inventory"),
        pytest.param("a1:api:unknown", 0, False, id="unknown-application-state"),
        pytest.param("a1:postgres:unknown", 0, False, id="unknown-data-state"),
        pytest.param("a1::running", 0, False, id="missing-service-label"),
        pytest.param("a1:api:exited:extra", 0, False, id="malformed-row"),
    ],
)
def test_prepare_uses_complete_checked_inventory_before_migration(
    tmp_path, inventory, inventory_exit, allowed
):
    """Execute the real wrapper with host commands stubbed; never contact Docker."""
    binary = tmp_path / "bin"
    binary.mkdir()
    stub = binary / "command-stub"
    stub.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, sys
from pathlib import Path
name=Path(sys.argv[0]).name
args=sys.argv[1:]
if name=='id': print('0')
elif name=='uname': print('Linux')
elif name in ('flock', 'python3', 'sh'): pass
elif name=='docker':
    expected=['container','ls','--all','--filter',
              'label=com.docker.compose.project=cosmabot-staging','--format',
              '{{.ID}}:{{.Label "com.docker.compose.service"}}:{{.State}}']
    assert args==expected, args
    print(Path(os.environ['INVENTORY']).read_text(), end='')
    sys.exit(int(os.environ['INVENTORY_EXIT']))
elif name=='docker-compose':
    assert args[:4]==['--project-name','cosmabot-staging','--file',
                      os.environ['RELEASE']+'/compose.json'], args
    action=args[4:]
    if action==['config','--quiet']: pass
    else:
        assert action==['--profile','prepare','run','--rm','--no-deps',
                        'database_prepare'], action
        Path(os.environ['MIGRATION']).write_text(json.dumps(action))
else: sys.exit(99)
"""
    )
    stub.chmod(0o700)
    for command in ("id", "uname", "flock", "python3", "sh", "docker", "docker-compose"):
        (binary / command).symlink_to(stub)
    release = tmp_path / "release"
    release.mkdir()
    script = release / "start.sh"
    script.write_text(
        (RUNTIME / "start.sh").read_text().replace("/run/cosmabot", str(tmp_path / "run"))
    )
    inventory_path = tmp_path / "inventory"
    inventory_path.write_text(inventory)
    migration = tmp_path / "migration"
    result = subprocess.run(
        ["/bin/sh", str(script), str(release), "prepare"],
        env={
            "PATH": str(binary) + ":/usr/bin:/bin",
            "RELEASE": str(release),
            "INVENTORY": str(inventory_path),
            "INVENTORY_EXIT": str(inventory_exit),
            "MIGRATION": str(migration),
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is allowed, result.stderr
    assert migration.exists() is allowed
    if inventory_exit:
        assert "Container inventory failed" in result.stderr
