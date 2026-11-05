locals {
  tags = {
    product       = "cosmabot"
    component     = "enrollment-allocator-host"
    environment   = var.environment
    clinical_data = var.environment == "production" ? "true" : "false"
  }
  identity_name = "id-cosmabot-enrollment-allocator-${var.environment}"
  subnet_name   = "snet-allocator-host"
}

resource "terraform_data" "holds" {
  input = {
    create_resources    = var.create_resources
    hold_release_sha256 = var.hold_release_sha256
    environment         = var.environment
    practice_uuid_limit = 1
    worker_started      = false
    hosting_enabled     = false
    p2_extra_box        = false
    stripe_live_mode    = false
  }

  lifecycle {
    precondition {
      condition     = !var.create_resources || can(regex("^[0-9a-f]{64}$", var.hold_release_sha256))
      error_message = "Creating allocator-host resources requires an explicit hold-release receipt digest; leave create_resources false to stay dark."
    }
    precondition {
      condition     = startswith(var.resource_group_name, "rg-cosmabot-enrollment-${var.environment}-")
      error_message = "Allocator host environment must match the dedicated enrollment resource group."
    }
    precondition {
      condition     = startswith(var.vnet_name, "vnet-cosmabot-enrollment-${var.environment}-")
      error_message = "Allocator host VNet name must match the dedicated enrollment environment."
    }
  }
}

resource "azurerm_subnet" "allocator_host" {
  count                             = var.create_resources ? 1 : 0
  name                              = local.subnet_name
  resource_group_name               = var.resource_group_name
  virtual_network_name              = var.vnet_name
  address_prefixes                  = [var.host_subnet_prefix]
  private_endpoint_network_policies = "Enabled"
  default_outbound_access_enabled   = false
}

resource "azurerm_user_assigned_identity" "allocator" {
  count               = var.create_resources ? 1 : 0
  name                = local.identity_name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = local.tags
}
