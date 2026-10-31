mock_provider "azurerm" {
  mock_resource "azurerm_private_dns_zone" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.Network/privateDnsZones/example.postgres.database.azure.com" }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.ManagedIdentity/userAssignedIdentities/example", principal_id = "00000000-0000-4000-8000-000000000090", client_id = "00000000-0000-4000-8000-000000000091" }
  }
  mock_resource "azurerm_key_vault" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.KeyVault/vaults/example", vault_uri = "https://kv-cews-mock5678-a.vault.azure.net/" }
  }
  mock_resource "azurerm_postgresql_flexible_server" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.DBforPostgreSQL/flexibleServers/example", fqdn = "psql-cews-stg-mock5678-a.postgres.database.azure.com" }
  }
  mock_resource "azurerm_storage_account" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.Storage/storageAccounts/example", primary_blob_endpoint = "https://stcewsmock5678a.blob.core.windows.net/" }
  }
  mock_resource "azurerm_storage_container" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.Storage/storageAccounts/example/blobServices/default/containers/box-artifacts" }
  }
  mock_resource "azurerm_managed_redis" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.Cache/redisEnterprise/example", hostname = "redis-cews-stg-mock5678-a.eastus2.redis.azure.net" }
  }
  mock_resource "azurerm_container_app" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.App/containerApps/example" }
  }
}
variables {
  deployment_file          = "tests/.generated-stores.json"
  postgres_admin_passwords = { a = "synthetic-only-admin-password-a-never-live", b = "synthetic-only-admin-password-b-never-live" }
}
run "stores_only_before_admission" {
  command = plan
  assert {
    condition = (length(azurerm_postgresql_flexible_server.box) == 2 && length(azurerm_postgresql_flexible_server_database.box) == 2 &&
      alltrue([for server in values(azurerm_postgresql_flexible_server.box) : !server.public_network_access_enabled]) &&
      alltrue([for database in values(azurerm_postgresql_flexible_server_database.box) : database.name == "cosmas_os"]) &&
      length(azurerm_storage_account.box) == 2 && length(azurerm_managed_redis.box) == 2 && length(azurerm_key_vault.box) == 2 &&
      length(azurerm_private_endpoint.box) == 6 &&
      length(azurerm_container_app.runtime) == 0 && length(azurerm_container_app.web) == 0 && length(azurerm_container_app_job.box) == 0 &&
      azurerm_postgresql_flexible_server.box["a"].name != azurerm_postgresql_flexible_server.box["b"].name &&
      azurerm_user_assigned_identity.runtime["a"].name != azurerm_user_assigned_identity.runtime["b"].name &&
    !output.workspace_resources.a.owner_ready && !output.workspace_resources.b.registry_workspace_ready)
    error_message = "Each Box must retain private separate stores/identity; no workload or readiness before qualification."
  }
}
run "centralus_private_stores_preserve_closed_admission" {
  command = plan
  variables { deployment_file = "tests/.generated-centralus.json" }
  assert {
    condition = (alltrue([for server in values(azurerm_postgresql_flexible_server.box) : server.location == "centralus" && !server.public_network_access_enabled]) &&
      alltrue([for vault in values(azurerm_key_vault.box) : vault.location == "centralus" && !vault.public_network_access_enabled]) &&
      alltrue([for store in values(azurerm_storage_account.box) : store.location == "centralus" && !store.public_network_access_enabled]) &&
      alltrue([for broker in values(azurerm_managed_redis.box) : broker.location == "centralus" && broker.public_network_access == "Disabled" && broker.high_availability_enabled]) &&
      length(azurerm_private_endpoint.box) == 6 &&
      length(azurerm_container_app.runtime) == 0 && length(azurerm_container_app.web) == 0 && length(azurerm_container_app_job.box) == 0 &&
    !output.workspace_resources.a.owner_ready && !output.workspace_resources.b.registry_workspace_ready)
    error_message = "Central US must preserve private independent stores and cannot activate a workspace or owner."
  }
}
run "unsupported_foundation_location_denied" {
  command = plan
  variables { deployment_file = "tests/.generated-unsupported-location.json" }
  expect_failures = [terraform_data.guard]
}
run "manual_migration_identity_has_only_its_database_refs" {
  command = plan
  variables { deployment_file = "tests/.generated-migrate.json" }
  assert {
    condition = (length(azurerm_container_app_job.box) == 2 && length(azurerm_role_assignment.job_secret) == 4 &&
      alltrue([for job in values(azurerm_container_app_job.box) : length(job.manual_trigger_config) == 1 &&
        length(job.schedule_trigger_config) == 0 && length(job.event_trigger_config) == 0 && job.replica_retry_limit == 0 &&
      toset([for secret in job.secret : secret.name]) == toset(["database-url", "database-admin-url"])]) &&
    length(azurerm_container_app.runtime) == 0 && !output.manual_jobs["a-migrate"].started)
    error_message = "Migration is manual, with a separate identity and only the selected Box admin/runtime database secrets."
  }
}
run "qualified_runtime_preserves_admission_and_excludes_administrator_secrets" {
  command = plan
  variables { deployment_file = "tests/.generated-workloads.json" }
  assert {
    condition = (length(azurerm_container_app.runtime) == 4 && length(azurerm_container_app.web) == 2 &&
      length(azurerm_role_assignment.runtime_secret) == 6 &&
      alltrue([for app in values(azurerm_container_app.runtime) : toset([for secret in app.secret : secret.name]) == toset(["database-url", "redis-url", "enrollment-admission-key"])]) &&
      alltrue([for app in values(azurerm_container_app.web) : length(app.secret) == 0]) &&
      one(azurerm_container_app.runtime["a-api"].identity).identity_ids == toset([azurerm_user_assigned_identity.runtime["a"].id]) &&
      one(azurerm_container_app.runtime["b-worker"].identity).identity_ids == toset([azurerm_user_assigned_identity.runtime["b"].id]) &&
      alltrue([for assignment in values(azurerm_role_assignment.runtime_secret) : !endswith(assignment.scope, "/database-admin-url") && !endswith(assignment.scope, "/owner-manifest")]) &&
      alltrue([for env in one(azurerm_container_app.runtime["a-api"].template).container[0].env : env.name != "WORKSPACE_ENROLLMENT_PRACTICE_ID" || env.value == "10000000-0000-4000-8000-000000000001"]) &&
      alltrue([for env in one(azurerm_container_app.runtime["b-worker"].template).container[0].env : env.name != "WORKSPACE_ENROLLMENT_PRACTICE_ID" || env.value == "10000000-0000-4000-8000-000000000002"]) &&
    !output.workspace_resources.a.registry_workspace_ready && !output.workspace_resources.b.owner_ready)
    error_message = "Deployment must preserve exact practice admission, secret-free web and runtime exclusion of administrator/reservation authority."
  }
}
