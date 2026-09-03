terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "registry.opentofu.org/hashicorp/azurerm"
      version = "~> 4.81"
    }
    random = {
      source  = "registry.opentofu.org/hashicorp/random"
      version = "~> 3.6"
    }
  }

  # The fail-closed first-plan wrapper supplies coordinates from protected
  # bootstrap output. Never hand-author or reuse D2 or Track A state.
  backend "azurerm" {
    use_azuread_auth = true
  }
}
