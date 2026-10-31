resource "azurerm_container_registry" "enrollment" {
  name                          = "acrcbotenrstg${var.resource_name_suffix}"
  resource_group_name           = azurerm_resource_group.enrollment.name
  location                      = var.location
  sku                           = "Basic"
  admin_enabled                 = false
  anonymous_pull_enabled        = false
  data_endpoint_enabled         = false
  public_network_access_enabled = true
  network_rule_bypass_option    = "None"
  tags                          = local.tags
  lifecycle { prevent_destroy = true }
}
resource "azurerm_key_vault" "enrollment" {
  name                          = "kv-cbot-enr-stg-${var.resource_name_suffix}"
  resource_group_name           = azurerm_resource_group.enrollment.name
  location                      = var.location
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  soft_delete_retention_days    = 90
  purge_protection_enabled      = true
  rbac_authorization_enabled    = true
  public_network_access_enabled = false
  network_acls {
    bypass         = "None"
    default_action = "Deny"
  }
  tags = local.tags
  lifecycle { prevent_destroy = true }
}
resource "azurerm_storage_account" "state" {
  name                              = "stcbotenrstg${var.resource_name_suffix}"
  resource_group_name               = azurerm_resource_group.enrollment.name
  location                          = var.location
  account_kind                      = "StorageV2"
  account_tier                      = "Standard"
  account_replication_type          = "LRS"
  min_tls_version                   = "TLS1_2"
  public_network_access_enabled     = true
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  infrastructure_encryption_enabled = true
  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
    ip_rules       = [var.state_operator_ipv4]
  }
  blob_properties {
    versioning_enabled = true
    delete_retention_policy { days = 7 }
    container_delete_retention_policy { days = 7 }
  }
  tags = local.tags
  lifecycle { prevent_destroy = true }
}
# This provider path uses ARM, not a public Blob data-plane exception.
resource "azurerm_storage_container" "runtime_state" {
  name                  = "enrollment-runtime-state"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
  lifecycle { prevent_destroy = true }
}
locals {
  private_services = {
    vault = { id = azurerm_key_vault.enrollment.id, group = "vault" }
  }
}
resource "azurerm_private_endpoint" "service" {
  for_each            = local.private_services
  name                = "pe-${each.key}-${local.name}"
  resource_group_name = azurerm_resource_group.enrollment.name
  location            = var.location
  subnet_id           = azurerm_subnet.private_endpoints.id
  private_service_connection {
    name                           = "psc-${each.key}"
    private_connection_resource_id = each.value.id
    subresource_names              = [each.value.group]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = each.key
    private_dns_zone_ids = [azurerm_private_dns_zone.service[each.key].id]
  }
  tags       = local.tags
  depends_on = [azurerm_private_dns_zone_virtual_network_link.service]
}

resource "azurerm_role_assignment" "release_registry" {
  scope                = azurerm_container_registry.enrollment.id
  role_definition_name = "AcrPush"
  principal_id         = var.release_operator_object_id
}
resource "azurerm_role_assignment" "release_state" {
  scope                = azurerm_storage_container.runtime_state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.release_operator_object_id
}
