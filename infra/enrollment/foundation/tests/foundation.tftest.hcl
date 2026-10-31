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
  subscription_id            = "00000000-0000-4000-8000-000000000001"
  tenant_id                  = "00000000-0000-4000-8000-000000000002"
  resource_name_suffix       = "mock1234"
  vnet_address_prefix        = "10.248.0.0/20"
  release_operator_object_id = "00000000-0000-4000-8000-000000000003"
  state_operator_ipv4        = "198.51.100.10"
  postgres_admin_password    = "synthetic-only-not-a-real-password-1234567890"
}
run "isolated_staging_foundation" {
  command = plan
  assert {
    condition = (azurerm_resource_group.enrollment.name == "rg-cosmabot-enrollment-staging-mock1234" &&
      azurerm_postgresql_flexible_server_database.enrollment.name == "cosmabot_enrollment" &&
      !azurerm_postgresql_flexible_server.enrollment.public_network_access_enabled &&
      azurerm_postgresql_flexible_server.enrollment.sku_name == "B_Standard_B1ms" &&
      azurerm_postgresql_flexible_server.enrollment.storage_mb == 32768 &&
      azurerm_postgresql_flexible_server_configuration.tls.value == "on" &&
      !azurerm_key_vault.enrollment.public_network_access_enabled &&
      azurerm_key_vault.enrollment.rbac_authorization_enabled && azurerm_key_vault.enrollment.purge_protection_enabled &&
      length(azurerm_private_endpoint.service) == 1 &&
      length(azurerm_subnet.container_apps.address_prefixes) == 1 &&
    one(azurerm_subnet.container_apps.address_prefixes) == "10.248.0.0/23")
    error_message = "Database/vault must remain private in their own enrollment network/database."
  }
  assert {
    condition = (azurerm_container_registry.enrollment.sku == "Basic" &&
      azurerm_container_registry.enrollment.public_network_access_enabled &&
      !azurerm_container_registry.enrollment.admin_enabled && !azurerm_container_registry.enrollment.anonymous_pull_enabled &&
      !azurerm_storage_account.state.shared_access_key_enabled &&
      !azurerm_storage_account.state.allow_nested_items_to_be_public &&
      azurerm_storage_account.state.min_tls_version == "TLS1_2" &&
      one(azurerm_storage_account.state.network_rules).default_action == "Deny" &&
      one(azurerm_storage_account.state.network_rules).ip_rules == toset(["198.51.100.10"]) &&
      one(azurerm_storage_account.state.network_rules).bypass == toset(["None"]) &&
      azurerm_role_assignment.release_state.scope == azurerm_storage_container.runtime_state.id &&
    !output.foundation.application_deployed && !output.foundation.database_qualified && !output.foundation.runtime_ready)
    error_message = "Only the code registry is public; state is exact-IP/Entra protected and foundation grants no readiness."
  }
}
run "reject_production" {
  command = plan
  variables { environment = "production" }
  expect_failures = [var.environment]
}
run "reject_shared_state" {
  command = plan
  variables { state_namespace = "clinical/backend" }
  expect_failures = [var.state_namespace]
}
run "reject_open_state" {
  command = plan
  variables { state_operator_ipv4 = "0.0.0.0/0" }
  expect_failures = [var.state_operator_ipv4]
}
run "reject_broad_operator_range" {
  command = plan
  variables { state_operator_ipv4 = "198.51.100.0/24" }
  expect_failures = [var.state_operator_ipv4]
}
run "reject_private_operator_address" {
  command = plan
  variables { state_operator_ipv4 = "10.1.2.3" }
  expect_failures = [var.state_operator_ipv4]
}
run "reject_noncanonical_network" {
  command = plan
  variables { vnet_address_prefix = "10.248.0.1/20" }
  expect_failures = [var.vnet_address_prefix]
}
run "reject_small_network" {
  command = plan
  variables { vnet_address_prefix = "10.248.0.0/24" }
  expect_failures = [var.vnet_address_prefix]
}
