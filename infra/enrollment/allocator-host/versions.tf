terraform {
  required_version = "= 1.12.5"
  required_providers {
    azurerm = { source = "registry.opentofu.org/hashicorp/azurerm", version = "= 4.81.0" }
  }
  # Local backend for plan/validate only. Never point this module at clinical state.
  backend "local" {}
}

provider "azurerm" {
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
  features {
    resource_group { prevent_deletion_if_contains_resources = true }
  }
}
