resource "azurerm_user_assigned_identity" "apps" {
  name                = local.identity_name
  resource_group_name = azurerm_resource_group.synth.name
  location            = azurerm_resource_group.synth.location
  tags                = local.tags
}
