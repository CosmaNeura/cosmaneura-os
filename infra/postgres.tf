resource "azurerm_postgresql_flexible_server" "synth" {
  name                   = local.postgres_name
  resource_group_name    = azurerm_resource_group.synth.name
  location               = var.postgres_location
  version                = "16"
  administrator_login    = var.postgres_admin_login
  administrator_password = var.postgres_admin_password

  sku_name   = var.postgres_sku_name
  storage_mb = 32768

  backup_retention_days        = 7
  geo_redundant_backup_enabled = false

  public_network_access_enabled = var.enable_public_postgres

  authentication {
    password_auth_enabled         = true
    active_directory_auth_enabled = false
  }

  tags = local.tags
}

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = "cosmas_os"
  server_id = azurerm_postgresql_flexible_server.synth.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure" {
  count = var.enable_public_postgres ? 1 : 0

  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.synth.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}
