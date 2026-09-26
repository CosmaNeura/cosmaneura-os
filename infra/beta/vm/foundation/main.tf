locals {
  resource_group_name = "rg-cosmas-os-vm-staging-eus2-lab01"
  vm_name             = "vm-cosmabot-staging-eus2-lab01"
  vnet_name           = "vnet-cosmabot-staging-eus2-lab01"
  tags = {
    product             = "cosmabot"
    track               = "B"
    env                 = "vm-synthetic-staging"
    data_classification = "synthetic-only"
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
resource "azurerm_resource_group" "staging" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.tags
  lifecycle { prevent_destroy = true }
}
resource "azurerm_user_assigned_identity" "runtime" {
  name                = "id-cosmabot-vm-runtime-eus2-lab01"
  resource_group_name = azurerm_resource_group.staging.name
  location            = var.location
  tags                = local.tags
}
