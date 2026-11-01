"""Public owned coordinates shared by the private journal operator helpers."""
from __future__ import annotations

import json
import re

DATABASE = "cosmabot_enrollment_clock_lab"
LOGINS = {"admin": "clock_bootstrap", "a": "clock_journal_a", "b": "clock_journal_b"}
NAMES = {"admin": "enrollment-private-clock-bootstrap-url", "a": "enrollment-private-clock-journal-a-url",
         "b": "enrollment-private-clock-journal-b-url", "bindings": "enrollment-private-clock-bindings"}


def foundation(raw: bytes) -> dict:
    value = json.loads(raw)
    f = value.get("foundation", {}).get("value", value)
    if (f.get("contract_version") != "enrollment-foundation.v1" or f.get("environment") != "staging"
            or f.get("location") not in {"centralus", "eastus2"} or f.get("postgres_database") != "cosmabot_enrollment"
            or not re.fullmatch(r"rg-cosmabot-enrollment-staging-[a-z0-9]{6,8}", f.get("resource_group_name", ""))):
        raise ValueError("owned independent staging foundation required")
    for key in ("subscription_id", "tenant_id"):
        if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", f.get(key, "")):
            raise ValueError("reviewed Azure identity required")
    prefix = f"/subscriptions/{f['subscription_id']}/resourceGroups/{f['resource_group_name']}/providers"
    for key, provider in {"vnet_id": "Microsoft.Network/virtualNetworks", "container_app_environment_id": "Microsoft.App/managedEnvironments",
                          "container_registry_id": "Microsoft.ContainerRegistry/registries", "key_vault_id": "Microsoft.KeyVault/vaults"}.items():
        if not re.fullmatch(re.escape(f"{prefix}/{provider}/") + r"[a-z0-9-]+", f.get(key, "")):
            raise ValueError("exact owned resource coordinates required")
    if (f.get("postgres_subnet_id") != f"{f['vnet_id']}/subnets/snet-postgres"
            or f.get("key_vault_uri") != f"https://{f['key_vault_id'].split('/')[-1]}.vault.azure.net/"
            or f.get("registry_server") != f"{f['container_registry_id'].split('/')[-1]}.azurecr.io"):
        raise ValueError("exact private network/vault/registry scope required")
    return f


def coordinates(raw: bytes) -> dict:
    c = json.loads(raw)
    if (c.get("contract_version") != "enrollment-private-clock-infrastructure.v1" or c.get("environment") != "staging"
            or c.get("hosted_qualified") is not False or c.get("source_database_modified") is not False
            or c.get("postgres_database") != DATABASE or c.get("postgres_admin_login") != LOGINS["admin"]
            or c.get("journal_logins") != {s: LOGINS[s] for s in ("a", "b")} or c.get("secret_names") != NAMES):
        raise ValueError("actual private journal coordinates required")
    if not re.fullmatch(r"psql-cbot-clock-stg-[a-z0-9]{6,8}\.postgres\.database\.azure\.com", c.get("postgres_fqdn", "")):
        raise ValueError("owned separate journal PostgreSQL host required")
    prefix = f"/subscriptions/{c.get('subscription_id')}/resourceGroups/{c.get('resource_group_name')}/providers"
    if c.get("postgres_server_id") != f"{prefix}/Microsoft.DBforPostgreSQL/flexibleServers/{c['postgres_fqdn'].split('.')[0]}":
        raise ValueError("exact owned separate server required")
    # Validate shared foundation coordinates using only the already exported public fields.
    if (not re.fullmatch(r"rg-cosmabot-enrollment-staging-[a-z0-9]{6,8}", c.get("resource_group_name", ""))
            or c.get("location") not in {"centralus", "eastus2"}
            or not re.fullmatch(re.escape(f"{prefix}/Microsoft.KeyVault/vaults/") + r"kv-cbot-enr-stg-[a-z0-9]{6,8}", c.get("key_vault_id", ""))
            or c.get("key_vault_uri") != f"https://{c.get('key_vault_id', '').split('/')[-1]}.vault.azure.net/"):
        raise ValueError("exact owned private vault required")
    hashes = c.get("binding_sha256", {})
    if (not isinstance(hashes, dict) or hashes and (set(hashes) != {"a", "b"} or len(set(hashes.values())) != 2 or any(not re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes.values()))
            or not hashes and (c.get("manual_job_created") is not False or c.get("runtime_grants_created") is not False)):
        raise ValueError("two immutable binding hashes required")
    return c
