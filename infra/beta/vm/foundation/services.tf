resource "azurerm_container_registry" "staging" {
  name                          = "acrcbotstgeus2${var.resource_name_suffix}"
  resource_group_name           = azurerm_resource_group.staging.name
  location                      = var.location
  sku                           = "Premium"
  admin_enabled                 = false
  anonymous_pull_enabled        = false
  data_endpoint_enabled         = true
  public_network_access_enabled = false
  network_rule_bypass_option    = "None"
  tags                          = local.tags
  lifecycle { prevent_destroy = true }
}
resource "azurerm_key_vault" "staging" {
  name                          = "kv-cbot-stg-${var.resource_name_suffix}"
  resource_group_name           = azurerm_resource_group.staging.name
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
resource "azurerm_storage_account" "objects" {
  for_each                          = toset(["application", "backup"])
  name                              = "stcbot${each.key == "application" ? "app" : "bak"}${var.resource_name_suffix}"
  resource_group_name               = azurerm_resource_group.staging.name
  location                          = var.location
  account_kind                      = "StorageV2"
  account_tier                      = "Standard"
  account_replication_type          = "LRS"
  access_tier                       = "Hot"
  min_tls_version                   = "TLS1_2"
  public_network_access_enabled     = false
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  infrastructure_encryption_enabled = true
  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
  }
  blob_properties {
    versioning_enabled = each.key == "backup"
    dynamic "delete_retention_policy" {
      for_each = each.key == "backup" ? [1] : []
      content { days = 7 }
    }
    dynamic "container_delete_retention_policy" {
      for_each = each.key == "backup" ? [1] : []
      content { days = 7 }
    }
  }
  tags = local.tags
  lifecycle { prevent_destroy = true }
}
# AzureRM 4.81's storage_account_id path uses ARM BlobContainers, not private data-plane creation.
resource "azurerm_storage_container" "objects" {
  for_each              = azurerm_storage_account.objects
  name                  = each.key == "application" ? "box-artifacts" : "postgres-backups"
  storage_account_id    = each.value.id
  container_access_type = "private"
  lifecycle { prevent_destroy = true }
}
locals {
  private_services = {
    acr         = { resource_id = azurerm_container_registry.staging.id, subresource = "registry", dns = "acr" }
    vault       = { resource_id = azurerm_key_vault.staging.id, subresource = "vault", dns = "vault" }
    application = { resource_id = azurerm_storage_account.objects["application"].id, subresource = "blob", dns = "blob" }
    backup      = { resource_id = azurerm_storage_account.objects["backup"].id, subresource = "blob", dns = "blob" }
  }
}
resource "azurerm_private_endpoint" "service" {
  for_each            = local.private_services
  name                = "pe-cbot-${each.key}-eus2-lab01"
  resource_group_name = azurerm_resource_group.staging.name
  location            = var.location
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags
  private_service_connection {
    name                           = "psc-${each.key}"
    private_connection_resource_id = each.value.resource_id
    subresource_names              = [each.value.subresource]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = each.value.dns
    private_dns_zone_ids = [azurerm_private_dns_zone.service[each.value.dns].id]
  }
  depends_on = [azurerm_private_dns_zone_virtual_network_link.service]
}
resource "azurerm_role_assignment" "runtime_application_blob" {
  scope                            = azurerm_storage_container.objects["application"].id
  role_definition_name             = "Storage Blob Data Contributor"
  principal_id                     = azurerm_user_assigned_identity.runtime.principal_id
  skip_service_principal_aad_check = true
}
resource "azurerm_role_assignment" "release_registry" {
  scope                = azurerm_container_registry.staging.id
  role_definition_name = "AcrPush"
  principal_id         = var.release_operator_object_id
  lifecycle {
    precondition {
      condition     = lower(var.release_operator_object_id) != lower(azurerm_user_assigned_identity.runtime.principal_id)
      error_message = "The off-VM release operator must differ from the VM runtime identity."
    }
  }
}
resource "azurerm_role_assignment" "release_secrets" {
  scope                = azurerm_key_vault.staging.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = var.release_operator_object_id
  lifecycle {
    precondition {
      condition     = lower(var.release_operator_object_id) != lower(azurerm_user_assigned_identity.runtime.principal_id)
      error_message = "The VM runtime identity may not provision or retrieve vault secrets."
    }
  }
}
