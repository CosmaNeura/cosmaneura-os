resource "azurerm_resource_group" "synth" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}
