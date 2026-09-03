resource "azurerm_virtual_network" "beta" {
  name                = local.vnet_name
  resource_group_name = data.azurerm_resource_group.beta.name
  location            = data.azurerm_resource_group.beta.location
  address_space       = var.vnet_address_space
  tags                = local.tags
}

resource "azurerm_subnet" "container_apps" {
  name                 = "snet-container-apps"
  resource_group_name  = data.azurerm_resource_group.beta.name
  virtual_network_name = azurerm_virtual_network.beta.name
  address_prefixes     = var.aca_subnet_prefixes

  delegation {
    name = "container-apps"

    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = data.azurerm_resource_group.beta.name
  virtual_network_name = azurerm_virtual_network.beta.name
  address_prefixes     = var.postgres_subnet_prefixes

  delegation {
    name = "postgres-flexible-server"

    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                 = "snet-private-endpoints"
  resource_group_name  = data.azurerm_resource_group.beta.name
  virtual_network_name = azurerm_virtual_network.beta.name
  address_prefixes     = var.private_endpoint_subnet_prefixes

  private_endpoint_network_policies = "Disabled"
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "${local.name_token}.postgres.database.azure.com"
  resource_group_name = data.azurerm_resource_group.beta.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone" "key_vault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = data.azurerm_resource_group.beta.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone" "redis" {
  name                = "privatelink.redis.azure.net"
  resource_group_name = data.azurerm_resource_group.beta.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone" "acr" {
  count = local.registry_is_private ? 1 : 0

  name                = "privatelink.azurecr.io"
  resource_group_name = data.azurerm_resource_group.beta.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "link-postgres-${var.beta_id}"
  resource_group_name   = data.azurerm_resource_group.beta.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.beta.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_virtual_network_peering" "beta_to_state" {
  name                         = "peer-beta-to-state-${var.beta_id}"
  resource_group_name          = data.azurerm_resource_group.beta.name
  virtual_network_name         = azurerm_virtual_network.beta.name
  remote_virtual_network_id    = var.state_vnet_id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = false
  allow_gateway_transit        = false
  use_remote_gateways          = false
}

resource "azurerm_virtual_network_peering" "state_to_beta" {
  name                         = "peer-state-to-beta-${var.beta_id}"
  resource_group_name          = local.state_resource_group_name
  virtual_network_name         = local.state_vnet_name
  remote_virtual_network_id    = azurerm_virtual_network.beta.id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = false
  allow_gateway_transit        = false
  use_remote_gateways          = false
}

# Use the bootstrap zone for both state and workload Blob endpoints. Linking a
# VNet to two same-named private zones would create ambiguous DNS behavior.
resource "azurerm_private_dns_zone_virtual_network_link" "state_blob_to_beta" {
  name                  = "link-state-blob-to-beta-${var.beta_id}"
  resource_group_name   = local.state_resource_group_name
  private_dns_zone_name = "privatelink.blob.core.windows.net"
  virtual_network_id    = azurerm_virtual_network.beta.id
  registration_enabled  = false
  tags                  = local.tags

  depends_on = [azurerm_virtual_network_peering.state_to_beta]
}

resource "azurerm_private_dns_zone_virtual_network_link" "key_vault" {
  name                  = "link-key-vault-${var.beta_id}"
  resource_group_name   = data.azurerm_resource_group.beta.name
  private_dns_zone_name = azurerm_private_dns_zone.key_vault.name
  virtual_network_id    = azurerm_virtual_network.beta.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "redis" {
  name                  = "link-redis-${var.beta_id}"
  resource_group_name   = data.azurerm_resource_group.beta.name
  private_dns_zone_name = azurerm_private_dns_zone.redis.name
  virtual_network_id    = azurerm_virtual_network.beta.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "acr" {
  count = local.registry_is_private ? 1 : 0

  name                  = "link-acr-${var.beta_id}"
  resource_group_name   = data.azurerm_resource_group.beta.name
  private_dns_zone_name = azurerm_private_dns_zone.acr[0].name
  virtual_network_id    = azurerm_virtual_network.beta.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres_to_runner" {
  name                  = "link-postgres-to-runner-${var.beta_id}"
  resource_group_name   = data.azurerm_resource_group.beta.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = var.state_vnet_id
  registration_enabled  = false
  tags                  = local.tags

  depends_on = [azurerm_virtual_network_peering.beta_to_state]
}

resource "azurerm_private_dns_zone_virtual_network_link" "key_vault_to_runner" {
  name                  = "link-key-vault-to-runner-${var.beta_id}"
  resource_group_name   = data.azurerm_resource_group.beta.name
  private_dns_zone_name = azurerm_private_dns_zone.key_vault.name
  virtual_network_id    = var.state_vnet_id
  registration_enabled  = false
  tags                  = local.tags

  depends_on = [azurerm_virtual_network_peering.beta_to_state]
}

resource "azurerm_private_dns_zone_virtual_network_link" "redis_to_runner" {
  name                  = "link-redis-to-runner-${var.beta_id}"
  resource_group_name   = data.azurerm_resource_group.beta.name
  private_dns_zone_name = azurerm_private_dns_zone.redis.name
  virtual_network_id    = var.state_vnet_id
  registration_enabled  = false
  tags                  = local.tags

  depends_on = [azurerm_virtual_network_peering.beta_to_state]
}

resource "azurerm_private_dns_zone_virtual_network_link" "acr_to_runner" {
  count = local.registry_is_private ? 1 : 0

  name                  = "link-acr-to-runner-${var.beta_id}"
  resource_group_name   = data.azurerm_resource_group.beta.name
  private_dns_zone_name = azurerm_private_dns_zone.acr[0].name
  virtual_network_id    = var.state_vnet_id
  registration_enabled  = false
  tags                  = local.tags

  depends_on = [azurerm_virtual_network_peering.beta_to_state]
}
