locals {
  name = "cosmabot-enrollment-staging-${var.resource_name_suffix}"
  tags = { product = "cosmabot", component = "customer-enrollment-foundation", environment = "staging", clinical_data = "false" }
}
resource "azurerm_resource_group" "enrollment" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
  lifecycle { prevent_destroy = true }
}
resource "azurerm_log_analytics_workspace" "enrollment" {
  name                = "law-${local.name}"
  resource_group_name = azurerm_resource_group.enrollment.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.1
  tags                = local.tags
}
resource "azurerm_container_app_environment" "enrollment" {
  name                           = "cae-${local.name}"
  resource_group_name            = azurerm_resource_group.enrollment.name
  location                       = var.location
  infrastructure_subnet_id       = azurerm_subnet.container_apps.id
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.enrollment.id
  internal_load_balancer_enabled = false
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
  tags = local.tags
}

resource "azurerm_postgresql_flexible_server" "enrollment" {
  name                              = "psql-${local.name}"
  resource_group_name               = azurerm_resource_group.enrollment.name
  location                          = var.location
  version                           = "16"
  sku_name                          = "B_Standard_B1ms"
  storage_mb                        = 32768
  auto_grow_enabled                 = true
  backup_retention_days             = 7
  geo_redundant_backup_enabled      = false
  public_network_access_enabled     = false
  delegated_subnet_id               = azurerm_subnet.postgres.id
  private_dns_zone_id               = azurerm_private_dns_zone.postgres.id
  administrator_login               = "enrollment_bootstrap"
  administrator_password_wo         = var.postgres_admin_password
  administrator_password_wo_version = var.postgres_admin_password_version
  authentication {
    password_auth_enabled         = true
    active_directory_auth_enabled = false
  }
  tags       = local.tags
  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
  lifecycle { prevent_destroy = true }
}
resource "azurerm_postgresql_flexible_server_configuration" "tls" {
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.enrollment.id
  value     = "on"
}
resource "azurerm_postgresql_flexible_server_database" "enrollment" {
  name      = "cosmabot_enrollment"
  server_id = azurerm_postgresql_flexible_server.enrollment.id
  charset   = "UTF8"
  collation = "en_US.utf8"
  lifecycle { prevent_destroy = true }
}
