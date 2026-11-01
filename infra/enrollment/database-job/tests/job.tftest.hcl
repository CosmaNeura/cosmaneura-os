mock_provider "azurerm" {
  mock_resource "azurerm_resource_group" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234" }
  }
  mock_resource "azurerm_virtual_network" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.Network/virtualNetworks/vnet" }
  }
  mock_resource "azurerm_subnet" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.Network/virtualNetworks/vnet/subnets/subnet" }
  }
  mock_resource "azurerm_private_dns_zone" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.Network/privateDnsZones/zone" }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.OperationalInsights/workspaces/law" }
  }
  mock_resource "azurerm_container_app_environment" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.App/managedEnvironments/cae" }
  }
  mock_resource "azurerm_postgresql_flexible_server" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.DBforPostgreSQL/flexibleServers/server", "fqdn" : "psql-cosmabot-enrollment-staging-mock1234.postgres.database.azure.com" }
  }
  mock_resource "azurerm_container_registry" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.ContainerRegistry/registries/acrcbotenrstgmock1234", "login_server" : "acrcbotenrstgmock1234.azurecr.io" }
  }
  mock_resource "azurerm_key_vault" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.KeyVault/vaults/kv-cbot-enr-stg-mock1234", "vault_uri" : "https://kv-cbot-enr-stg-mock1234.vault.azure.net/" }
  }
  mock_resource "azurerm_storage_account" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.Storage/storageAccounts/stcbotenrstgmock1234" }
  }
  mock_resource "azurerm_storage_container" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.Storage/storageAccounts/stcbotenrstgmock1234/blobServices/default/containers/enrollment-runtime-state" }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = { "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-db", "principal_id" : "00000000-0000-4000-8000-000000000099" }
  }
}
variables {
  subscription_id   = "00000000-0000-4000-8000-000000000001"
  tenant_id         = "00000000-0000-4000-8000-000000000002"
  foundation_file   = "tests/foundation.json"
  image             = "acrcbotenrstgmock1234.azurecr.io/enrollment-database@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  operation         = "migrate"
  create_job        = true
  secret_references = { migration = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-migration-database-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", runtime = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-database-url/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
}
run "manual_migration_job" {
  command = plan
  assert {
    condition = (length(azurerm_container_app_job.database) == 1 &&
      length(azurerm_container_app_job.database[0].manual_trigger_config) == 1 &&
      length(azurerm_container_app_job.database[0].schedule_trigger_config) == 0 &&
      length(azurerm_container_app_job.database[0].event_trigger_config) == 0 &&
      azurerm_container_app_job.database[0].replica_retry_limit == 0 &&
      one(azurerm_container_app_job.database[0].manual_trigger_config).parallelism == 1 &&
      length(azurerm_role_assignment.secret) == 2 &&
      alltrue([for assignment in azurerm_role_assignment.secret : !endswith(assignment.scope, "/enrollment-bootstrap-database-url")]) &&
    azurerm_role_assignment.pull.role_definition_name == "AcrPull" && !output.manual_job.started && !output.manual_job.qualified)
    error_message = "Job must be manual/single, with no admin credential or runtime/deployment grant."
  }
}
run "reject_tagged_image" {
  command = plan
  variables { image = "acrcbotenrstgmock1234.azurecr.io/enrollment-database:latest" }
  expect_failures = [terraform_data.guard]
}
run "reject_bootstrap_secret_in_migration" {
  command = plan
  variables {
    secret_references = { migration = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-bootstrap-database-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", runtime = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-database-url/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
  }
  expect_failures = [terraform_data.guard]
}
run "runtime_check_has_one_secret" {
  command = plan
  variables {
    operation         = "check"
    secret_references = { runtime = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-database-url/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
  }
  assert {
    condition     = length(azurerm_role_assignment.secret) == 1
    error_message = "Read-only check must not read the migration/admin login."
  }
}
