resource "azurerm_storage_account" "beta" {
  name                              = local.storage_name
  resource_group_name               = data.azurerm_resource_group.beta.name
  location                          = data.azurerm_resource_group.beta.location
  account_tier                      = "Standard"
  account_replication_type          = var.storage_replication_type
  min_tls_version                   = "TLS1_2"
  public_network_access_enabled     = false
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  infrastructure_encryption_enabled = true
  tags                              = local.tags

  blob_properties {
    versioning_enabled = false
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_container" "artifacts" {
  count = var.deploy_workloads ? 1 : 0

  name                  = "box-artifacts"
  storage_account_id    = azurerm_storage_account.beta.id
  container_access_type = "private"

  depends_on = [
    azurerm_private_endpoint.blob,
    azurerm_private_dns_zone_virtual_network_link.state_blob_to_beta,
    azurerm_role_assignment.deploy_blob_data,
  ]

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_role_assignment" "deploy_blob_data" {
  scope                            = azurerm_storage_account.beta.id
  role_definition_name             = "Storage Blob Data Contributor"
  principal_id                     = data.azurerm_user_assigned_identity.deploy.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_private_endpoint" "blob" {
  name                = "pe-blob-${var.beta_id}"
  resource_group_name = data.azurerm_resource_group.beta.name
  location            = data.azurerm_resource_group.beta.location
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-blob-${var.beta_id}"
    private_connection_resource_id = azurerm_storage_account.beta.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "blob"
    private_dns_zone_ids = [var.state_blob_private_dns_zone_id]
  }
}

resource "azurerm_role_assignment" "runtime_blob" {
  count = var.deploy_workloads ? 1 : 0

  scope                            = azurerm_storage_container.artifacts[0].id
  role_definition_name             = "Storage Blob Data Contributor"
  principal_id                     = azurerm_user_assigned_identity.runtime.principal_id
  skip_service_principal_aad_check = true
}
