"""Strict, offline renderer for the approved synthetic VM staging architecture.

Run with the matching application's dependencies. It reads already installed
protected files, validates the actual Settings class, and emits public runtime
files plus a Compose document. It neither provisions secrets nor starts services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import ssl
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
from entrypoint import API_UID, Refused, load_environment, read_json, read_private, validate_public

ROOT_UID = 0
DATA_UID = 999
HERE = Path(__file__).resolve().parent
HASH = re.compile(r"[0-9a-f]{64}")
SCRIPT_NAMES = (
    "entrypoint.py",
    "redis-health.sh",
    "imds-guard.sh",
    "host-preflight.py",
    "start.sh",
    "cosmabot-staging.service",
)
NETWORKS = {
    "backend": ("172.30.240.0/24", "br-cm-backend", True),
    "egress": ("172.30.241.0/24", "br-cm-egress", False),
    "frontend": ("172.30.242.0/24", "br-cm-front", True),
}


def checked_path(path: Path) -> Path:
    if (
        not path.is_absolute()
        or str(path) != str(path.resolve())
        or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(path))
        or ".." in path.parts
    ):
        raise Refused("host_path_must_be_absolute_canonical")
    return path


def validate_manifest(value: dict) -> dict:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "version",
            "release_id",
            "source_commit",
            "images",
            "web_origin",
            "api_origin",
            "runtime",
            "tls_sha256",
            "image_review_reference",
        }
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise Refused("manifest_shape")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,47}", value["release_id"]):
        raise Refused("release_id")
    if not re.fullmatch(r"[0-9a-f]{40}", value["source_commit"]):
        raise Refused("source_commit")
    if not isinstance(value["image_review_reference"], str) or not re.fullmatch(
        r"[A-Za-z0-9:/._-]{8,240}", value["image_review_reference"]
    ):
        raise Refused("reviewed_image_identity_required")
    if (
        value["web_origin"] != "https://staging.cosmas.ai"
        or value["api_origin"] != "https://api.staging.cosmas.ai"
    ):
        raise Refused("selected_staging_origins_required")
    images = value["images"]
    if not isinstance(images, dict) or set(images) != {"api", "web", "postgres", "redis", "proxy"}:
        raise Refused("image_set")
    acr = r"[a-z0-9]{5,50}\.azurecr\.io/[a-z0-9][a-z0-9_./-]*@sha256:[0-9a-f]{64}"
    patterns = {
        "api": acr,
        "web": acr,
        "postgres": r"postgres:16\.[0-9]+-bookworm@sha256:[0-9a-f]{64}",
        "redis": r"redis:7\.[24]\.[0-9]+-bookworm@sha256:[0-9a-f]{64}",
        "proxy": r"caddy:2\.[0-9]+\.[0-9]+-alpine@sha256:[0-9a-f]{64}",
    }
    if any(
        not isinstance(images[name], str)
        or not re.fullmatch(patterns[name], images[name])
        or "/../" in images[name]
        for name in patterns
    ):
        raise Refused("reviewed_immutable_images_required")
    if images["api"].split("/")[0] != images["web"].split("/")[0]:
        raise Refused("dedicated_registry_required")
    tls = value["tls_sha256"]
    if (
        not isinstance(tls, dict)
        or set(tls) != {"public-roots.pem", "private-ca.pem", "postgres.crt", "redis.crt"}
        or any(not isinstance(item, str) or not HASH.fullmatch(item) for item in tls.values())
    ):
        raise Refused("reviewed_public_tls_files_required")
    validate_public(value["runtime"])
    env = value["runtime"]["environment"]
    expected_origins = [value["web_origin"]]
    for key, origin in (
        ("WORKSPACE_APPLE_HOSTED_TRANSPORT_ENABLED", "capacitor://localhost"),
        ("WORKSPACE_DESKTOP_HOSTED_TRANSPORT_ENABLED", "app://cosmas"),
    ):
        if env[key] == "true":
            expected_origins.append(origin)
    if any(
        set(env.get(key, "").split(",")) != set(expected_origins)
        for key in ("CORS_ALLOWED_ORIGINS", "CLERK_AUTHORIZED_PARTIES")
    ):
        raise Refused("exact_web_and_native_origins_required")
    callback_pairs = (
        (
            "WORKSPACE_GOOGLE_CONNECTION_ENABLED",
            "GOOGLE_CONNECTION_CALLBACK_URI",
            "GOOGLE_CONNECTION_RETURN_ORIGIN",
            "/connections/google/callback",
        ),
        (
            "WORKSPACE_MICROSOFT_CONNECTION_ENABLED",
            "MICROSOFT_CONNECTION_CALLBACK_URI",
            "MICROSOFT_CONNECTION_RETURN_ORIGIN",
            "/connections/microsoft/callback",
        ),
        (
            "WORKSPACE_SCHEDULING_LOGIN_ENABLED",
            "SCHEDULING_GOOGLE_CALLBACK_URI",
            "SCHEDULING_LOGIN_RETURN_ORIGIN",
            "/connections/scheduling/google/callback",
        ),
    )
    for flag, callback, return_key, suffix in callback_pairs:
        if env[flag] == "true" and (
            env.get(callback) != value["api_origin"] + suffix
            or env.get(return_key) != value["web_origin"]
        ):
            raise Refused("callback_origin_mismatch")
    core_identity = env.get("CORE_CAPTURE_MANAGED_IDENTITY_CLIENT_ID")
    if core_identity and core_identity != value["runtime"]["runtime_identity_client_id"]:
        raise Refused("core_identity_mismatch")
    return value


def validate_private_files(value: dict, root: Path) -> bytes:
    checked_path(root)
    if root.name != value["release_id"]:
        raise Refused("protected_release_directory_mismatch")
    metadata = root.stat()
    if metadata.st_uid != ROOT_UID or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise Refused("protected_root_permissions")
    for service, uid in (
        ("api", API_UID),
        ("worker", API_UID),
        ("prepare", API_UID),
        ("postgres", DATA_UID),
        ("redis", DATA_UID),
    ):
        directory = checked_path(root / service)
        metadata = directory.stat()
        if metadata.st_uid != uid or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise Refused("protected_service_directory_permissions")
    api = load_environment(value["runtime"], root / "api")
    worker = load_environment(value["runtime"], root / "worker")
    if api != worker:
        raise Refused("api_worker_configuration_mismatch")
    db_password = read_private(root / "api/DATABASE_PASSWORD", API_UID)
    redis_password = read_private(root / "api/REDIS_PASSWORD", API_UID)
    admin_password = read_private(root / "postgres/POSTGRES_PASSWORD", DATA_UID)
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", admin_password)
        or len(set(admin_password)) < 12
        or len({admin_password, db_password, redis_password}) != 3
        or read_private(root / "prepare/POSTGRES_PASSWORD", API_UID) != admin_password
        or read_private(root / "prepare/DATABASE_PASSWORD", API_UID) != db_password
        or read_private(root / "redis/REDIS_PASSWORD", DATA_UID) != redis_password
    ):
        raise Refused("separate_database_and_broker_credentials_required")
    expected_acl = (
        "user default reset on #"
        + hashlib.sha256(redis_password.encode()).hexdigest()
        + " ~* &* +@all"
    )
    if read_private(root / "redis/users.acl", DATA_UID) != expected_acl:
        raise Refused("dedicated_authenticated_redis_acl_required")
    public = {}
    for name, expected in value["tls_sha256"].items():
        path = checked_path(root / "tls" / name)
        raw = path.read_bytes()
        if b"PRIVATE KEY" in raw or hashlib.sha256(raw).hexdigest() != expected:
            raise Refused("public_tls_file_hash_mismatch")
        ssl.create_default_context(cafile=str(path)) if name.endswith(".pem") else None
        public[name] = raw
    for service in ("postgres", "redis"):
        key = root / service / "server.key"
        read_private(key, DATA_UID)
        try:
            ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(
                root / "tls" / f"{service}.crt", key
            )
            result = subprocess.run(
                [
                    "openssl",
                    "verify",
                    "-CAfile",
                    str(root / "tls/private-ca.pem"),
                    "-purpose",
                    "sslserver",
                    "-verify_hostname",
                    service,
                    str(root / "tls" / f"{service}.crt"),
                ],
                capture_output=True,
                check=False,
            )
            if result.returncode:
                raise Refused("service_certificate_chain_or_hostname")
        except (OSError, ssl.SSLError):
            raise Refused("service_certificate_pair") from None
    return public["public-roots.pem"].rstrip() + b"\n" + public["private-ca.pem"].rstrip() + b"\n"


def bind(source, target, *, read_only=True):
    return {
        "type": "bind",
        "source": str(source),
        "target": target,
        "read_only": read_only,
        "bind": {"create_host_path": False},
    }


def compose(value: dict, release: Path, protected: Path, data: Path) -> dict:
    images = value["images"]
    common = {
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "restart": "on-failure:3",
        "init": True,
        "stop_grace_period": "120s",
        "logging": {"driver": "local", "options": {"max-size": "10m", "max-file": "3"}},
        "pids_limit": 128,
    }
    runtime = "/opt/cosmabot/runtime"
    trust = bind(release / "system-ca.pem", "/etc/ssl/certs/ca-certificates.crt")
    configs = bind(release, runtime)
    services = {}
    for service, address in (("api", "10"), ("worker", "11")):
        services[service] = {
            **common,
            "image": images["api"],
            "user": "10001:10001",
            "entrypoint": ["python", f"{runtime}/entrypoint.py", service],
            "cpus": 0.5,
            "mem_limit": "1g",
            "tmpfs": ["/tmp:rw,noexec,nosuid,size=64m,uid=10001,gid=10001"],
            "volumes": [configs, trust, bind(protected / service, "/run/cosmabot/secrets")],
            "networks": {
                "backend": {"ipv4_address": f"172.30.240.{address}"},
                "egress": {"ipv4_address": f"172.30.241.{address}"},
            },
            "depends_on": {
                "postgres": {"condition": "service_healthy"},
                "redis": {"condition": "service_healthy"},
            },
            "healthcheck": {
                "test": [
                    "CMD",
                    "python",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:"
                    + ("8000" if service == "api" else "8001")
                    + "/ready',timeout=4).read()",
                ],
                "interval": "15s",
                "timeout": "5s",
                "retries": 3,
                "start_period": "60s",
            },
        }
    services["api"]["networks"]["frontend"] = {"ipv4_address": "172.30.242.10"}
    services["postgres"] = {
        **common,
        "image": images["postgres"],
        "user": "999:999",
        "cpus": 0.5,
        "mem_limit": "1536m",
        "shm_size": "256m",
        "environment": {
            "POSTGRES_USER": "postgres",
            "POSTGRES_DB": "cosmas_os",
            "POSTGRES_PASSWORD_FILE": "/run/cosmabot/secrets/POSTGRES_PASSWORD",
            "POSTGRES_INITDB_ARGS": "--auth-local=peer --auth-host=scram-sha-256",
        },
        "command": ["postgres", "-c", f"config_file={runtime}/postgresql.conf"],
        "tmpfs": [
            "/tmp:rw,noexec,nosuid,size=32m,uid=999,gid=999",
            "/var/run/postgresql:rw,nosuid,size=16m,uid=999,gid=999",
        ],
        "volumes": [
            configs,
            bind(protected / "postgres", "/run/cosmabot/secrets"),
            bind(protected / "tls/postgres.crt", "/run/cosmabot/server.crt"),
            bind(data / "postgres", "/var/lib/postgresql/data", read_only=False),
        ],
        "networks": {"backend": {"ipv4_address": "172.30.240.20"}},
        "healthcheck": {
            "test": ["CMD", "pg_isready", "-U", "postgres", "-d", "cosmas_os"],
            "interval": "5s",
            "timeout": "3s",
            "retries": 20,
        },
    }
    services["redis"] = {
        **common,
        "image": images["redis"],
        "user": "999:999",
        "cpus": 0.15,
        "mem_limit": "768m",
        "entrypoint": ["redis-server", f"{runtime}/redis.conf"],
        "tmpfs": ["/tmp:rw,noexec,nosuid,size=32m,uid=999,gid=999"],
        "volumes": [
            configs,
            bind(protected / "redis", "/run/cosmabot/secrets"),
            bind(protected / "tls/redis.crt", "/run/cosmabot/server.crt"),
            bind(data / "redis", "/data", read_only=False),
        ],
        "networks": {"backend": {"ipv4_address": "172.30.240.21"}},
        "healthcheck": {
            "test": ["CMD", "sh", f"{runtime}/redis-health.sh"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5,
        },
    }
    services["web"] = {
        **common,
        "image": images["web"],
        "user": "101:101",
        "cpus": 0.25,
        "mem_limit": "512m",
        "tmpfs": [
            "/tmp:rw,noexec,nosuid,size=32m,uid=101,gid=101",
            "/var/cache/nginx:rw,nosuid,size=32m,uid=101,gid=101",
        ],
        "networks": {"frontend": {"ipv4_address": "172.30.242.11"}},
        "healthcheck": {
            "test": ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"],
            "interval": "15s",
            "timeout": "5s",
            "retries": 3,
        },
    }
    services["proxy"] = {
        **common,
        "image": images["proxy"],
        "user": "10001:10001",
        # Official Caddy's file capability needs this bounding-set bit even on high ports.
        "cap_add": ["NET_BIND_SERVICE"],
        "cpus": 0.1,
        "mem_limit": "128m",
        "command": ["caddy", "run", "--config", f"{runtime}/Caddyfile", "--adapter", "caddyfile"],
        "ports": ["80:8080", "443:8443"],
        "tmpfs": ["/tmp:rw,noexec,nosuid,size=16m,uid=10001,gid=10001"],
        "volumes": [
            configs,
            bind(data / "caddy-data", "/data", read_only=False),
            bind(data / "caddy-config", "/config", read_only=False),
        ],
        "networks": {
            "frontend": {"ipv4_address": "172.30.242.12"},
            "egress": {"ipv4_address": "172.30.241.12"},
        },
        "depends_on": {
            "api": {"condition": "service_healthy"},
            "web": {"condition": "service_healthy"},
        },
    }
    services["database_prepare"] = {
        **common,
        "image": images["api"],
        "user": "10001:10001",
        "profiles": ["prepare"],
        "restart": "no",
        "cpus": 0.5,
        "mem_limit": "1g",
        "entrypoint": ["python", f"{runtime}/entrypoint.py", "prepare"],
        "tmpfs": ["/tmp:rw,noexec,nosuid,size=64m,uid=10001,gid=10001"],
        "volumes": [configs, trust, bind(protected / "prepare", "/run/cosmabot/secrets")],
        "networks": {"backend": {"ipv4_address": "172.30.240.12"}},
        "depends_on": {"postgres": {"condition": "service_healthy"}},
    }
    return {
        "name": "cosmabot-staging",
        "services": services,
        "networks": {
            name: {
                "driver": "bridge",
                "internal": internal,
                "enable_ipv6": False,
                "driver_opts": {"com.docker.network.bridge.name": bridge},
                "ipam": {"config": [{"subnet": subnet}]},
            }
            for name, (subnet, bridge, internal) in NETWORKS.items()
        },
    }


POSTGRES = """listen_addresses = '*'
port = 5432
ssl = on
ssl_min_protocol_version = 'TLSv1.2'
ssl_cert_file = '/run/cosmabot/server.crt'
ssl_key_file = '/run/cosmabot/secrets/server.key'
hba_file = '/opt/cosmabot/runtime/pg_hba.conf'
password_encryption = 'scram-sha-256'
max_connections = 40
shared_buffers = '256MB'
work_mem = '4MB'
maintenance_work_mem = '64MB'
log_statement = 'none'
log_min_error_statement = 'panic'
log_connections = off
log_disconnections = off
fsync = on
full_page_writes = on
synchronous_commit = on
"""
PG_HBA = """local all postgres peer
hostssl cosmas_os postgres 172.30.240.12/32 scram-sha-256
hostssl cosmas_os cosmas 172.30.240.10/32 scram-sha-256
hostssl cosmas_os cosmas 172.30.240.11/32 scram-sha-256
hostssl cosmas_os cosmas 172.30.240.12/32 scram-sha-256
host all all 0.0.0.0/0 reject
host all all ::/0 reject
"""
REDIS = """bind 0.0.0.0
protected-mode yes
port 0
tls-port 6379
tls-cert-file /run/cosmabot/server.crt
tls-key-file /run/cosmabot/secrets/server.key
tls-ca-cert-file /opt/cosmabot/runtime/system-ca.pem
tls-auth-clients no
tls-protocols "TLSv1.2 TLSv1.3"
aclfile /run/cosmabot/secrets/users.acl
dir /data
appendonly yes
appendfsync everysec
no-appendfsync-on-rewrite no
maxmemory 256mb
maxmemory-policy noeviction
save ""
"""


def caddy(value):
    web, api = value["web_origin"][8:], value["api_origin"][8:]
    return f"""{{
    admin off
    http_port 8080
    https_port 8443
}}
http://{web}, http://{api} {{
    redir https://{{host}}{{uri}} permanent
}}
https://{web} {{
    reverse_proxy web:8080
}}
https://{api} {{
    @private path /health /ready /docs /redoc /openapi.json
    respond @private 404
    reverse_proxy api:8000
}}
"""


def render(value: dict, protected: Path, output: Path, data: Path) -> None:
    validate_manifest(value)
    checked_path(output)
    # This is the Linux deployment path, not a directory on the rendering Mac.
    # The Linux host preflight checks the actual mount and ownership before start.
    if data != Path("/var/lib/cosmabot"):
        raise Refused("dedicated_data_mount_required")
    if output.name != value["release_id"] or output.exists():
        raise Refused("new_release_directory_required")
    trust = validate_private_files(value, protected)
    document = compose(value, output, protected, data)
    files = {name: (HERE / name).read_bytes() for name in SCRIPT_NAMES}
    files.update(
        {
            "compose.json": (json.dumps(document, indent=2) + "\n").encode(),
            "runtime.json": (json.dumps(value["runtime"], indent=2) + "\n").encode(),
            "system-ca.pem": trust,
            "postgresql.conf": POSTGRES.encode(),
            "pg_hba.conf": PG_HBA.encode(),
            "redis.conf": REDIS.encode(),
            "Caddyfile": caddy(value).encode(),
        }
    )
    receipt = {
        "version": 1,
        "source_commit": value["source_commit"],
        "images": value["images"],
        "image_review_reference": value["image_review_reference"],
        "manifest_sha256": hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
        "status": "rendered_only_not_deployed_or_recovery_qualified",
    }
    files["RENDER.json"] = (json.dumps(receipt, indent=2) + "\n").encode()
    output.mkdir(mode=0o755)
    try:
        for name, raw in files.items():
            path = output / name
            path.write_bytes(raw)
            path.chmod(0o444)
    except Exception:
        shutil.rmtree(output)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--protected-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--data-root", default=Path("/var/lib/cosmabot"), type=Path)
    args = parser.parse_args()
    try:
        value = read_json(args.manifest)
        render(value, args.protected_root, args.output, args.data_root)
    except Exception:
        print(
            "VM runtime rendering refused; inspect protected inputs locally. No credentials are printed.",
            file=sys.stderr,
        )
        return 1
    print(
        "Rendered public VM runtime files. No services were started; host isolation and recovery acceptance remain required."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
