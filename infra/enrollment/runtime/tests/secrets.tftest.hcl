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
  subscription_id              = "00000000-0000-4000-8000-000000000001"
  tenant_id                    = "00000000-0000-4000-8000-000000000002"
  resource_group_name          = "rg-cosmabot-enrollment-staging-mock1234"
  environment                  = "staging"
  location                     = "eastus2"
  container_app_environment_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.App/managedEnvironments/cae"
  container_registry_id        = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.ContainerRegistry/registries/acrcbotenrstgmock1234"
  registry_server              = "acrcbotenrstgmock1234.azurecr.io"
  key_vault_id                 = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.KeyVault/vaults/kv-cbot-enr-stg-mock1234"
  key_vault_uri                = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/"
  rendered_directory           = "tests/rendered"
  deploy_workload              = false
}
run "per_secret_runtime_access" {
  command = plan
  assert {
    condition = (length(azurerm_role_assignment.secrets) == 2 &&
      alltrue([for assignment in azurerm_role_assignment.secrets : assignment.scope != var.key_vault_id &&
        assignment.role_definition_name == "Key Vault Secrets User" &&
        !endswith(assignment.scope, "/enrollment-bootstrap-database-url") &&
      !endswith(assignment.scope, "/enrollment-migration-database-url")]) &&
    length(azurerm_container_app.enrollment) == 0)
    error_message = "Runtime must not inherit the vault's bootstrap/migration credentials or start before qualification."
  }
}
run "reject_runtime_bootstrap_mount" {
  command = plan
  variables { rendered_directory = "tests/bootstrap" }
  expect_failures = [terraform_data.guard]
}
