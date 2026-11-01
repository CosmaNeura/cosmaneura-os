resource "azurerm_virtual_network" "enrollment" {
  name                = "vnet-${local.name}"
  resource_group_name = azurerm_resource_group.enrollment.name
  location            = var.location
  address_space       = [var.vnet_address_prefix]
  tags                = local.tags
}
resource "azurerm_subnet" "container_apps" {
  name                            = "snet-container-apps"
  resource_group_name             = azurerm_resource_group.enrollment.name
  virtual_network_name            = azurerm_virtual_network.enrollment.name
  address_prefixes                = [cidrsubnet(var.vnet_address_prefix, 3, 0)] # /23, isolated Consumption workload profile
  default_outbound_access_enabled = false
  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "postgres" {
  name                            = "snet-postgres"
  resource_group_name             = azurerm_resource_group.enrollment.name
  virtual_network_name            = azurerm_virtual_network.enrollment.name
  address_prefixes                = [cidrsubnet(var.vnet_address_prefix, 6, 8)] # /26
  default_outbound_access_enabled = false
  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "private_endpoints" {
  name                              = "snet-private-endpoints"
  resource_group_name               = azurerm_resource_group.enrollment.name
  virtual_network_name              = azurerm_virtual_network.enrollment.name
  address_prefixes                  = [cidrsubnet(var.vnet_address_prefix, 6, 9)]
  private_endpoint_network_policies = "Disabled"
  default_outbound_access_enabled   = false
}
locals {
  private_dns = { vault = "privatelink.vaultcore.azure.net" }
}
resource "azurerm_private_dns_zone" "service" {
  for_each            = local.private_dns
  name                = each.value
  resource_group_name = azurerm_resource_group.enrollment.name
  tags                = local.tags
}
resource "azurerm_private_dns_zone_virtual_network_link" "service" {
  for_each              = local.private_dns
  name                  = "link-enrollment-${each.key}"
  resource_group_name   = azurerm_resource_group.enrollment.name
  private_dns_zone_name = azurerm_private_dns_zone.service[each.key].name
  virtual_network_id    = azurerm_virtual_network.enrollment.id
  registration_enabled  = false
}
resource "azurerm_private_dns_zone" "postgres" {
  name                = "enrollment-${var.resource_name_suffix}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.enrollment.name
  tags                = local.tags
}
resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "link-enrollment-postgres"
  resource_group_name   = azurerm_resource_group.enrollment.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.enrollment.id
  registration_enabled  = false
}
