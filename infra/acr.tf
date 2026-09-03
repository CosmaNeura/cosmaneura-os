resource "azurerm_container_registry" "synth" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.synth.name
  location            = azurerm_resource_group.synth.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.synth.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}
