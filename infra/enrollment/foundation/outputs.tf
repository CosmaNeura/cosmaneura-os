output "foundation" {
  description = "Owned resource coordinates only; not application, database-role, vendor or journey qualification."
  value = {
    contract_version             = "enrollment-foundation.v1"
    environment                  = "staging"
    application_deployed         = false
    database_qualified           = false
    runtime_ready                = false
    resource_group_name          = azurerm_resource_group.enrollment.name
    location                     = var.location
    subscription_id              = var.subscription_id
    tenant_id                    = var.tenant_id
    vnet_id                      = azurerm_virtual_network.enrollment.id
    postgres_subnet_id           = azurerm_subnet.postgres.id
    private_endpoint_subnet_id   = azurerm_subnet.private_endpoints.id
    vault_private_dns_zone_id    = azurerm_private_dns_zone.service["vault"].id
    vnet_address_prefix          = var.vnet_address_prefix
    container_app_environment_id = azurerm_container_app_environment.enrollment.id
    container_registry_id        = azurerm_container_registry.enrollment.id
    registry_server              = azurerm_container_registry.enrollment.login_server
    key_vault_id                 = azurerm_key_vault.enrollment.id
    key_vault_uri                = azurerm_key_vault.enrollment.vault_uri
    postgres_server_id           = azurerm_postgresql_flexible_server.enrollment.id
    postgres_fqdn                = azurerm_postgresql_flexible_server.enrollment.fqdn
    postgres_database            = azurerm_postgresql_flexible_server_database.enrollment.name
    postgres_admin_login         = azurerm_postgresql_flexible_server.enrollment.administrator_login
    migration_login              = "enrollment_migrator"
    runtime_login                = "enrollment_runtime"
    state_backend = {
      resource_group_name  = azurerm_resource_group.enrollment.name
      storage_account_name = azurerm_storage_account.state.name
      container_name       = azurerm_storage_container.runtime_state.name
      key                  = "cosmabot-enrollment/staging/runtime-v1.tfstate"
      use_azuread_auth     = true
    }
  }
}
