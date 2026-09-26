resource "azurerm_virtual_network" "staging" {
  name                = local.vnet_name
  resource_group_name = azurerm_resource_group.staging.name
  location            = var.location
  address_space       = [var.vnet_address_prefix]
  tags                = local.tags
}
resource "azurerm_subnet" "workload" {
  name                            = "snet-workload"
  resource_group_name             = azurerm_resource_group.staging.name
  virtual_network_name            = azurerm_virtual_network.staging.name
  address_prefixes                = [cidrsubnet(var.vnet_address_prefix, 2, 0)]
  default_outbound_access_enabled = false
}
resource "azurerm_subnet" "private_endpoints" {
  name                              = "snet-private-endpoints"
  resource_group_name               = azurerm_resource_group.staging.name
  virtual_network_name              = azurerm_virtual_network.staging.name
  address_prefixes                  = [cidrsubnet(var.vnet_address_prefix, 2, 1)]
  private_endpoint_network_policies = "Disabled"
  default_outbound_access_enabled   = false
}
resource "azurerm_network_security_group" "workload" {
  name                = "nsg-cosmabot-staging-eus2-lab01"
  resource_group_name = azurerm_resource_group.staging.name
  location            = var.location
  tags                = local.tags
  security_rule {
    name                       = "https"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "acme-http-and-https-redirect"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }
  # Overrides Azure's default VNet/LoadBalancer inbound allows as well as Internet.
  security_rule {
    name                       = "deny-all-other-ingress"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}
resource "azurerm_subnet_network_security_group_association" "workload" {
  subnet_id                 = azurerm_subnet.workload.id
  network_security_group_id = azurerm_network_security_group.workload.id
}
resource "azurerm_public_ip" "workload" {
  name                = "pip-cosmabot-staging-eus2-lab01"
  resource_group_name = azurerm_resource_group.staging.name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  ip_version          = "IPv4"
  tags                = local.tags
}
resource "azurerm_network_interface" "workload" {
  name                = "nic-cosmabot-staging-eus2-lab01"
  resource_group_name = azurerm_resource_group.staging.name
  location            = var.location
  tags                = local.tags
  ip_configuration {
    name                          = "workload"
    subnet_id                     = azurerm_subnet.workload.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.workload.id
  }
  depends_on = [azurerm_subnet_network_security_group_association.workload]
}
resource "azurerm_private_dns_zone" "service" {
  for_each            = local.private_dns_names
  name                = each.value
  resource_group_name = azurerm_resource_group.staging.name
  tags                = local.tags
}
resource "azurerm_private_dns_zone_virtual_network_link" "service" {
  for_each              = local.private_dns_names
  name                  = "link-${each.key}-staging"
  resource_group_name   = azurerm_resource_group.staging.name
  private_dns_zone_name = azurerm_private_dns_zone.service[each.key].name
  virtual_network_id    = azurerm_virtual_network.staging.id
  registration_enabled  = false
  tags                  = local.tags
}
