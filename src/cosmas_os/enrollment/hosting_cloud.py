"""Concrete Azure/OpenTofu/DNS executor for the private allocation worker.

Importing or preparing this module makes no cloud calls. Every execution needs
the explicit host configuration, same registered plan and owned persistent state.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx

from .hosting import (
    GOOGLE_SECRET_NAMES,
    SECRET_NAMES,
    HostingConfiguration,
    box_admission_key,
    box_google_custody_key,
    canonical,
    private_read,
)


class AzureAllocationBackend:
    def __init__(self, configuration: HostingConfiguration, *, run=subprocess.run, client=None, sleep=time.sleep):
        self.config, self.run, self.client, self.sleep = configuration, run, client, sleep
        self.directory = None

    def _command(self, argv: list[str], *, env=None, timeout=900, maximum=4_000_000) -> bytes:
        selected = env or self._environment()
        try:
            result = self.run(argv, env=selected, capture_output=True, check=True, timeout=timeout,
                              cwd=self.directory, umask=0o077)
            if len(result.stdout) > maximum:
                raise ValueError("bounded private command output required")
            return result.stdout
        except (OSError, subprocess.SubprocessError):
            # CLI streams/arguments can contain private provider material.
            raise RuntimeError("private allocation provider operation pending") from None

    def _json(self, argv: list[str], **kwargs):
        return json.loads(self._command(argv, **kwargs))

    def _environment(self):
        if self.directory is None:
            raise ValueError("private operation directory required")
        blocked = ("AZURE_CORE_LOG_LEVEL", "AZURE_LOG_LEVEL", "AZURE_HTTP_LOGGING_ENABLED", "TF_LOG", "TF_LOG_PATH")
        if any(name in os.environ for name in blocked):
            raise ValueError("credential/provider debug logging refused")
        values = {name: value for name, value in os.environ.items()
                  if not name.startswith(("TF_", "ARM_")) and name not in {"AZURE_CONFIG_DIR", "TOFU_ENCRYPTION"}}
        values.update(AZURE_CONFIG_DIR=str(self.directory / "azure-auth"), TF_INPUT="0", TF_WORKSPACE="default",
                      TF_DATA_DIR=str(self.directory / "provider-data"), ARM_USE_CLI="false", ARM_USE_MSI="true",
                      ARM_USE_OIDC="false", ARM_CLIENT_ID=self.config.value["worker_client_id"],
                      ARM_SUBSCRIPTION_ID=self.config.foundation["subscription_id"], ARM_TENANT_ID=self.config.foundation["tenant_id"])
        return values

    def _write(self, name: str, value: bytes):
        if self.directory is None or "/" in name or name.startswith("."):
            raise ValueError("private operation filename required")
        target = self.directory / name
        temporary = self.directory / (name + ".new-" + uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    def _checkpoint(self, state: dict):
        self._write("operation.json", canonical(state))

    def _open(self, deployment: dict) -> dict:
        root = self.config.state_root
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o777 != 0o700:
            raise ValueError("owned persistent private worker directory required")
        plan = deployment["practice"]["plan"]
        self.directory = root / (plan["practice_id"] + "-" + deployment["operation_id"])
        self.directory.mkdir(mode=0o700, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_uid != os.getuid() or self.directory.stat().st_mode & 0o777 != 0o700:
            raise ValueError("owned private operation directory required")
        signed_scope = json.loads(json.dumps(deployment))
        signed_scope.pop("_owner_manifest")
        signed_scope["practice"].pop("owner_manifest_sha256")
        # Display-name changes do not replace the first persisted reservation
        # manifest or strand retries of the same immutable practice/release.
        immutable = hashlib.sha256(canonical(signed_scope)).hexdigest()
        path = self.directory / "operation.json"
        if path.exists():
            state = json.loads(private_read(path))
            if state.get("input_sha256") != immutable or state.get("operation_id") != deployment["operation_id"]:
                raise ValueError("saved allocation differs from reviewed input")
            return state
        state = {"contract_version": "cosmas-host-allocation-journal.v1", "input_sha256": immutable,
                 "operation_id": deployment["operation_id"], "deployment": deployment, "phase": "queued"}
        self._checkpoint(state)
        return state

    def preflight(self, *, new_resources=True):
        f = self.config.foundation
        source = self.config.release["source_commit"]
        head = self._command(["git", "-C", str(self.config.source), "rev-parse", "HEAD"]).decode().strip()
        dirty = self._command(["git", "-C", str(self.config.source), "status", "--porcelain", "--untracked-files=no"]).strip()
        if head != source or dirty:
            raise ValueError("private hosting requires the clean exact reviewed release source")
        prefix = "infra/enrollment/allocated-workspace/"
        expected = set(self._command(["git", "-C", str(self.config.source), "ls-tree", "-r", "--name-only", source, prefix]).decode().splitlines())
        module = self.config.source / prefix
        actual = {str(path.relative_to(self.config.source)) for path in module.rglob("*") if path.is_file()}
        if not expected or actual != expected or any(path.is_symlink() for path in module.rglob("*")):
            raise ValueError("the private allocation module must contain only the committed reviewed files")
        for path in sorted(expected):
            if self._command(["git", "-C", str(self.config.source), "show", source + ":" + path]) != (self.config.source / path).read_bytes():
                raise ValueError("private allocation source differs from selected commit")
        self._command(["az", "login", "--identity", "--client-id", self.config.value["worker_client_id"], "--output", "none"])
        self._command(["az", "account", "set", "--subscription", f["subscription_id"]])
        account = self._json(["az", "account", "show", "--query", "{id:id,tenantId:tenantId,state:state}", "--output", "json"])
        if account != {"id": f["subscription_id"], "tenantId": f["tenant_id"], "state": "Enabled"}:
            raise ValueError("private worker Azure context differs from dedicated foundation")
        version = self._json(["tofu", "version", "-json"])
        if version.get("terraform_version") != "1.12.5":
            raise ValueError("reviewed OpenTofu version required")
        if not new_resources:
            return
        for name, required in (("postgres_subnet_id", 8), ("private_endpoint_subnet_id", 4)):
            subnet = self._json(["az", "network", "vnet", "subnet", "show", "--ids", f[name], "--output", "json"])
            if subnet.get("id", "").lower() != f[name].lower():
                raise ValueError("actual owned subnet capacity unavailable")
            network = ipaddress.ip_network(subnet["addressPrefix"], strict=True)
            if network.version != 4 or network.num_addresses > 256:
                raise ValueError("bounded owned IPv4 allocation subnet required")
            available = 0
            for address in list(network.hosts())[3:-1]:
                observed = self._json(["az", "network", "vnet", "check-ip-address", "--resource-group", f["resource_group_name"],
                    "--name", f["vnet_id"].rsplit("/", 1)[1], "--ip-address", str(address), "--output", "json"])
                if observed.get("available") is True:
                    available += 1
                elif observed.get("available") is not False:
                    raise ValueError("actual subnet address availability is unknown")
                if available >= required:
                    break
            if available < required:
                raise RuntimeError("private allocation queued while subnet capacity is unavailable")

    def _apply(self, state: dict):
        d = {name: value for name, value in state["deployment"].items() if name != "_owner_manifest"}
        self._write("deployment.json", canonical(d))
        environment = self._environment()
        assert self.directory is not None
        for filename in ("state-key", "admin-password", "runtime-password"):
            if not (self.directory / filename).exists():
                self._write(filename, secrets.token_urlsafe(48).encode())
        environment.update(TF_VAR_deployment_file=str(self.directory / "deployment.json"),
                           TF_VAR_encryption_key_file=str(self.directory / "state-key"),
                           TF_VAR_postgres_admin_passwords=json.dumps({"box": private_read(self.directory / "admin-password").decode()}))
        module = self.config.source / "infra/enrollment/allocated-workspace"
        backend = self.config.foundation["state_backend"]
        arguments = ["tofu", "-chdir=" + str(module), "init", "-input=false", "-reconfigure", "-lockfile=readonly"]
        for name in ("resource_group_name", "storage_account_name", "container_name"):
            arguments.append("-backend-config=" + name + "=" + backend[name])
        arguments += ["-backend-config=use_azuread_auth=true", "-backend-config=use_msi=true",
                      "-backend-config=key=cosmabot-enrollment/staging/allocated/" + d["practice"]["plan"]["practice_id"] + ".tfstate"]
        self._command(arguments, env=environment)
        self._command(["tofu", "-chdir=" + str(module), "apply", "-input=false", "-auto-approve", "-no-color"], env=environment, timeout=2400)
        resources = self._json(["tofu", "-chdir=" + str(module), "output", "-json", "workspace_resources"], env=environment)["box"]
        plan = d["practice"]["plan"]
        if any(resources.get(name) != plan[name] for name in ("practice_id", "box_id", "organization_id")):
            raise ValueError("actual allocated resources differ from registered practice")
        for name in ("postgres_server_id", "key_vault_id", "redis_id", "storage_id", "runtime_identity_id"):
            if not resources.get(name, "").lower().startswith(self.config.scope.lower()):
                raise ValueError("allocated resource leaves dedicated enrollment group")
        expected_host = "psql-cbaw-" + plan["practice_id"].replace("-", "") + ".postgres.database.azure.com"
        if resources["postgres_fqdn"] != expected_host:
            raise ValueError("allocated database differs from permanent Box")
        state["resources"] = resources
        self._checkpoint(state)
        return resources

    def _seed(self, state: dict, master: str):
        assert self.directory is not None
        d, resources = state["deployment"], state["resources"]
        references = d["practice"]["secret_references"]
        google = d.get("google")
        if google is not None and (self.config.google is None
                or google != {name: self.config.google[name] for name in ("client_id", "callback_uri")}):
            raise ValueError("saved Google broker differs from reviewed host input")
        secret_names = {**SECRET_NAMES, **(GOOGLE_SECRET_NAMES if google is not None else {})}
        if not set(references) <= set(secret_names):
            raise ValueError("unreviewed Box secret reference refused")
        if google is not None:
            vault = "kvca" + d["practice"]["plan"]["practice_id"].replace("-", "")[:20]
            if resources["key_vault_id"] != self.config.scope + "Microsoft.KeyVault/vaults/" + vault:
                raise ValueError("Google custody requires this Box's own vault")
            for name, secret in GOOGLE_SECRET_NAMES.items():
                if name in references and not re.fullmatch(
                        re.escape("https://" + vault + ".vault.azure.net/secrets/" + secret + "/") + r"[a-f0-9]{32}", references[name]):
                    raise ValueError("exact versioned Box Google secret reference unavailable")
        if set(references) == set(secret_names):
            return
        values = {}
        if not set(SECRET_NAMES) <= set(references):
            keys = self._json(["az", "rest", "--method", "post", "--url", "https://management.azure.com" + resources["redis_id"] + "/databases/default/listKeys?api-version=2024-11-01", "--output", "json"])
            redis_key = keys.get("primaryKey")
            if not isinstance(redis_key, str) or not redis_key:
                raise ValueError("private Box Redis credential unavailable")
            host = resources["postgres_fqdn"]
            values = {"REDIS_URL": "rediss://:" + quote(redis_key, safe="") + "@" + resources["redis_hostname"] + ":10000/0?ssl_cert_reqs=required",
                      "WORKSPACE_ENROLLMENT_ADMISSION_SECRET": box_admission_key(d, master),
                      "OWNER_MANIFEST": canonical(d["_owner_manifest"]).decode()}
            for name, role, filename in (("DATABASE_ADMIN_URL", "box_bootstrap", "admin-password"), ("DATABASE_URL", "box_runtime", "runtime-password")):
                values[name] = "postgresql+psycopg://" + role + ":" + quote(private_read(self.directory / filename).decode(), safe="") + "@" + host + ":5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
        if google is not None:
            if "GOOGLE_CONNECTION_CLIENT_SECRET" not in references:
                assert self.config.google is not None
                client_secret = private_read(Path(self.config.google["client_secret_file"]), maximum=8192).decode()
                if not client_secret or any(ord(char) < 33 or ord(char) > 126 for char in client_secret):
                    raise ValueError("bounded protected Google client secret required")
                values["GOOGLE_CONNECTION_CLIENT_SECRET"] = client_secret
            if "GOOGLE_CONNECTION_ENCRYPTION_KEY" not in references:
                values["GOOGLE_CONNECTION_ENCRYPTION_KEY"] = box_google_custody_key(d, master)
        vault = resources["key_vault_id"].rsplit("/", 1)[1]
        template = self.config.source / "infra/enrollment/allocated-workspace/secret.template.json"
        for name, value in values.items():
            if name in references:
                continue
            secret = secret_names[name]
            self._write("seed-parameters.json", canonical({"vaultName": {"value": vault}, "secretName": {"value": secret}, "secretValue": {"value": value}}))
            self._command(["az", "deployment", "group", "create", "--subscription", self.config.foundation["subscription_id"],
                "--resource-group", self.config.foundation["resource_group_name"], "--name", "allocation-" + d["operation_id"] + "-" + secret,
                "--template-file", str(template), "--parameters", "@" + str(self.directory / "seed-parameters.json"), "--output", "none"])
            reference = self._command(["az", "resource", "show", "--ids", resources["key_vault_id"] + "/secrets/" + secret,
                "--api-version", "2024-11-01", "--query", "properties.secretUriWithVersion", "--output", "tsv"]).decode().strip()
            if not reference.startswith("https://" + vault + ".vault.azure.net/secrets/" + secret + "/") or len(reference.rsplit("/", 1)[1]) != 32:
                raise ValueError("exact versioned Box secret reference unavailable")
            if name in GOOGLE_SECRET_NAMES and not re.fullmatch(r"[a-f0-9]{32}", reference.rsplit("/", 1)[1]):
                raise ValueError("exact versioned Box Google secret reference unavailable")
            references[name] = reference
            self._checkpoint(state)
        (self.directory / "seed-parameters.json").unlink(missing_ok=True)

    def _job(self, state: dict, operation: str) -> str:
        assert self.directory is not None
        d, r = state["deployment"], state["resources"]
        local = self.directory / (operation + "-receipt.json")
        name = "job-cbaw-" + d["practice"]["plan"]["practice_id"].replace("-", "") + "-" + operation
        handle_key = operation + "_execution"
        history_key = operation + "_executions"
        pending_key = operation + "_start_pending"
        history = state.setdefault(history_key, [])
        if handle_key not in state:
            previous = self._json(["az", "containerapp", "job", "execution", "list", "--name", name,
                "--resource-group", self.config.foundation["resource_group_name"], "--output", "json"])
            unknown = [item for item in previous if item["name"] not in history]
            if len(unknown) > 1:
                raise RuntimeError("private job has ambiguous executions; retain the actual handles")
            if unknown:
                # Recover a lost start reply rather than starting another job.
                state[handle_key] = unknown[0]["name"]
            else:
                if state.get(pending_key):
                    raise RuntimeError("private job start reply is unknown; await its actual execution")
                if len(history) >= 3:
                    raise RuntimeError("private job reached its bounded retry limit")
                state[pending_key] = True
                self._checkpoint(state)
                selected = self._json(["az", "containerapp", "job", "start", "--name", name,
                    "--resource-group", self.config.foundation["resource_group_name"], "--output", "json"])
                state[handle_key] = selected["name"]
            history.append(state[handle_key])
            state[pending_key] = False
            self._checkpoint(state)
        elif state[handle_key] not in history:
            # Preserve older journals that already saved their first handle.
            history.append(state[handle_key])
            self._checkpoint(state)
        for _ in range(60):
            status = self._json(["az", "containerapp", "job", "execution", "show", "--name", name,
                "--job-execution-name", state[handle_key], "--resource-group", self.config.foundation["resource_group_name"], "--output", "json"])
            phase = status.get("properties", {}).get("status")
            if phase == "Succeeded":
                break
            if phase == "Failed":
                # Only an observed terminal failure permits another execution;
                # retained history bounds retries and protects lost replies.
                state.pop(handle_key)
                self._checkpoint(state)
                raise RuntimeError("private job failed; its bounded retry remains pending")
            if phase in {"Stopped", "Canceled"}:
                raise RuntimeError("private job was stopped; preserve its exact execution")
            self.sleep(15)
        else:
            raise RuntimeError("private job remains pending")
        account = r["storage_id"].rsplit("/", 1)[1]
        self._command(["az", "storage", "blob", "download", "--auth-mode", "login", "--account-name", account,
            "--container-name", "hosting-receipts", "--name", d["operation_id"] + "/" + operation + ".json",
            "--file", str(local), "--overwrite", "--no-progress", "--output", "none"])
        os.chmod(local, 0o600)
        raw = private_read(local)
        receipt = json.loads(raw)
        plan = d["practice"]["plan"]
        expected = {name: plan[name] for name in ("practice_id", "box_id", "organization_id", "source_commit", "image_sha256")}
        if (receipt.get("contract") != "enrollment-workspace-" + ("migration" if operation == "migrate" else "reservation") + ".v1"
                or receipt.get("allocation_operation_id") != d["operation_id"]
                or any(receipt.get(name) != value for name, value in expected.items())
                or receipt.get("owner_ready") is not False or receipt.get("workspace_ready") is not False
                or operation == "reserve" and (receipt.get("owner_reserved") is not True
                    or receipt.get("owner_manifest_sha256") != d["practice"]["owner_manifest_sha256"])):
            raise ValueError("actual job evidence differs from immutable allocation")
        return hashlib.sha256(raw).hexdigest()

    def _dns(self, state: dict):
        d, r = state["deployment"], state["resources"]
        assert self.directory is not None
        environment = self._environment()
        environment.update(TF_VAR_deployment_file=str(self.directory / "deployment.json"), TF_VAR_encryption_key_file=str(self.directory / "state-key"),
                           TF_VAR_postgres_admin_passwords=json.dumps({"box": private_read(self.directory / "admin-password").decode()}))
        tokens = self._json(["tofu", "-chdir=" + str(self.config.source / "infra/enrollment/allocated-workspace"), "output", "-json", "domain_verification"], env=environment)["box"]
        from .hosting_dns import bind_allocated_dns

        bind_allocated_dns(self.config, d, r, tokens, client=self.client, run=self.run, sleep=self.sleep)

    def _tls(self, state: dict):
        assert self.directory is not None
        f, d = self.config.foundation, state["deployment"]
        plan = d["practice"]["plan"]
        client = self.client or httpx.Client(timeout=15, follow_redirects=False)
        for kind, origin in (("api", plan["api_origin"]), ("web", d["practice"]["web_origin"])):
            host = origin[8:]
            app = kind + "-cbaw-" + plan["practice_id"].replace("-", "")
            certificate_id = f["container_app_environment_id"] + "/managedCertificates/alloc-" + d["operation_id"] + "-" + kind
            url = "https://management.azure.com" + certificate_id + "?api-version=2025-07-01"
            inventory = self._json(["az", "rest", "--method", "get", "--url", "https://management.azure.com" + f["container_app_environment_id"] + "/managedCertificates?api-version=2025-07-01", "--output", "json"])
            existing = [item for item in inventory.get("value", []) if item.get("properties", {}).get("subjectName") == host]
            if len(existing) > 1:
                raise ValueError("ambiguous existing certificate for allocated hostname")
            if existing:
                certificate_id = existing[0]["id"]
                if (not certificate_id.lower().startswith((f["container_app_environment_id"] + "/managedCertificates/").lower())
                        or existing[0].get("properties", {}).get("provisioningState") in {"Failed", "Canceled"}):
                    raise ValueError("the existing owned certificate needs review; no duplicate was created")
                url = "https://management.azure.com" + certificate_id + "?api-version=2025-07-01"
            else:
                self._write("certificate-request.json", canonical({"location": f["location"], "properties": {"subjectName": host, "domainControlValidation": "CNAME"}}))
                self._command(["az", "rest", "--method", "put", "--url", url, "--body", "@" + str(self.directory / "certificate-request.json"), "--output", "none"])
            for _ in range(80):
                cert = self._json(["az", "rest", "--method", "get", "--url", url, "--output", "json"])
                if cert.get("properties", {}).get("subjectName") != host:
                    raise ValueError("managed certificate differs from allocated host")
                status = cert.get("properties", {}).get("provisioningState")
                if status == "Succeeded":
                    break
                if status in {"Failed", "Canceled"}:
                    raise RuntimeError("the exact managed certificate failed; preserve its identity")
                self.sleep(15)
            else:
                raise RuntimeError("the exact managed certificate remains pending")
            self._command(["az", "containerapp", "hostname", "bind", "--name", app, "--resource-group", f["resource_group_name"],
                           "--environment", f["container_app_environment_id"], "--hostname", host, "--certificate", certificate_id, "--output", "none"])
            actual = self._json(["az", "containerapp", "show", "--name", app, "--resource-group", f["resource_group_name"], "--output", "json"])
            domains = actual.get("properties", {}).get("configuration", {}).get("ingress", {}).get("customDomains", [])
            if not any(item.get("name") == host and item.get("certificateId", "").lower() == certificate_id.lower()
                       and item.get("bindingType") == "SniEnabled" for item in domains):
                raise ValueError("actual TLS binding is not ready")
            response = client.get(origin + ("/health" if kind == "api" else "/healthz"))
            response.raise_for_status()
            if kind == "api" and response.json().get("status") != "ok":
                raise ValueError("allocated API health differs from selected runtime")

    def allocate(self, deployment: dict, master: str):
        if not self.config.value["enabled"]:
            raise RuntimeError("private hosting is disabled")
        state = self._open(deployment)
        self.preflight(new_resources="resources" not in state)
        if state["phase"] == "allocated":
            # Re-measure current health/TLS after an interrupted registry reply.
            self._tls(state)
            return
        self._apply(state)
        self._seed(state, master)
        d = state["deployment"]
        d["create_migration_jobs"] = True
        self._apply(state)
        d["practice"]["migration_receipt_sha256"] = self._job(state, "migrate")
        self._checkpoint(state)
        d["create_owner_reservation_jobs"] = True
        self._apply(state)
        d["practice"]["reservation_receipt_sha256"] = self._job(state, "reserve")
        self._checkpoint(state)
        from .hosting_build import build_allocated_web

        d["practice"]["web_image"] = build_allocated_web(self, state)
        d["deploy_workloads"] = True
        self._apply(state)
        self._dns(state)
        d["practice"]["dns_ownership_qualified"] = True
        d["bind_domains"] = True
        self._apply(state)
        self._tls(state)
        state["phase"] = "allocated"
        self._checkpoint(state)
