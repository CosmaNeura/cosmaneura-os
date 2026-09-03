resource "azurerm_storage_account" "synth" {
  name                     = local.storage_name
  resource_group_name      = azurerm_resource_group.synth.name
  location                 = azurerm_resource_group.synth.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = local.tags
}

resource "azurerm_storage_container" "blobs" {
  name                  = "synth-blobs"
  storage_account_id    = azurerm_storage_account.synth.id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "blob_contrib" {
  scope                = azurerm_storage_account.synth.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}
