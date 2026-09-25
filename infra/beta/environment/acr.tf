resource "azurerm_container_registry" "beta" {
  name                          = local.acr_name
  resource_group_name           = data.azurerm_resource_group.beta.name
  location                      = var.location
  sku                           = local.registry_is_private ? "Premium" : "Basic"
  admin_enabled                 = false
  anonymous_pull_enabled        = false
  public_network_access_enabled = !local.registry_is_private
  network_rule_bypass_option    = local.registry_is_private ? "None" : "AzureServices"
  tags                          = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_private_endpoint" "acr" {
  count = local.registry_is_private ? 1 : 0

  name                = "pe-acr-${var.beta_id}"
  resource_group_name = data.azurerm_resource_group.beta.name
  location            = var.location
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-acr-${var.beta_id}"
    private_connection_resource_id = azurerm_container_registry.beta.id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "acr"
    private_dns_zone_ids = [azurerm_private_dns_zone.acr[0].id]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.acr]
}

resource "azurerm_role_assignment" "runtime_acr_pull" {
  scope                            = azurerm_container_registry.beta.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_user_assigned_identity.runtime.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "web_acr_pull" {
  scope                            = azurerm_container_registry.beta.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_user_assigned_identity.web.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "database_preparation_acr_pull" {
  count = var.enable_database_preparation_job ? 1 : 0

  scope                            = azurerm_container_registry.beta.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_user_assigned_identity.database_preparation[0].principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "deploy_acr_push" {
  scope                            = azurerm_container_registry.beta.id
  role_definition_name             = "AcrPush"
  principal_id                     = data.azurerm_user_assigned_identity.deploy.principal_id
  skip_service_principal_aad_check = true
}
