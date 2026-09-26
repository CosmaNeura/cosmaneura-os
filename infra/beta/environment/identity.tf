resource "azurerm_user_assigned_identity" "runtime" {
  name                = local.runtime_identity_name
  resource_group_name = data.azurerm_resource_group.beta.name
  location            = var.location
  tags                = local.tags
}

# The static browser host must not inherit the API/worker identity's Blob or
# Key Vault access. Its only role assignment is ACR pull below.
resource "azurerm_user_assigned_identity" "web" {
  name                = local.web_identity_name
  resource_group_name = data.azurerm_resource_group.beta.name
  location            = var.location
  tags                = local.tags
}

# The migration job must not inherit the API/worker identity. This identity can
# pull only the reviewed image; its database credentials are isolated as
# Container Apps Job secrets and are never readable by a runtime revision.
resource "azurerm_user_assigned_identity" "database_preparation" {
  count = var.enable_database_preparation_job ? 1 : 0

  name                = local.database_identity_name
  resource_group_name = data.azurerm_resource_group.beta.name
  location            = var.location
  tags                = local.tags
}
