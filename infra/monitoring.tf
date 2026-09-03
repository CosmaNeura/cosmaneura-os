resource "azurerm_log_analytics_workspace" "synth" {
  name                = local.law_name
  resource_group_name = azurerm_resource_group.synth.name
  location            = azurerm_resource_group.synth.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}
