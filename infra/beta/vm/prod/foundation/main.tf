locals {
  resource_group_name = "rg-cosmabot-prod-eus2-01"
  vm_name             = "vm-cosmabot-prod-eus2-01"
  vnet_name           = "vnet-cosmabot-prod-eus2-01"
  tags = {
    product             = "cosmabot"
    track               = "B"
    env                 = "vm-production"
    data_classification = "production-authorized"
    managed             = "opentofu"
  }
  private_dns_names = {
    acr   = "privatelink.azurecr.io"
    vault = "privatelink.vaultcore.azure.net"
    blob  = "privatelink.blob.core.windows.net"
  }
}
resource "terraform_data" "state_namespace" {
  input = var.state_namespace
}
resource "azurerm_resource_group" "production" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.tags
  lifecycle { prevent_destroy = true }
}
resource "azurerm_user_assigned_identity" "runtime" {
  name                = "id-cosmabot-vm-runtime-prod-eus2-01"
  resource_group_name = azurerm_resource_group.production.name
  location            = var.location
  tags                = local.tags
}
