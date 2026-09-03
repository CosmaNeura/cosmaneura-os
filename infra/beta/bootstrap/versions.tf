terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "registry.terraform.io/hashicorp/azurerm"
      version = "~> 4.81"
    }
    random = {
      source  = "registry.terraform.io/hashicorp/random"
      version = "~> 3.6"
    }
  }

  # This one-time root creates the remote backend used by ../environment.
  # Its own state must remain in a human-controlled, encrypted location.
}
