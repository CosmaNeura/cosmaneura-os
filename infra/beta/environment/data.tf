data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "beta" {
  name = local.resource_group_name
}

data "azurerm_resource_group" "state" {
  name = local.state_resource_group_name
}

data "azurerm_user_assigned_identity" "deploy" {
  name                = local.deploy_identity_name
  resource_group_name = local.state_resource_group_name
}
