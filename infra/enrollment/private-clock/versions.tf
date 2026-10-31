terraform {
  required_version = "= 1.12.5"
  required_providers {
    azurerm = { source = "registry.opentofu.org/hashicorp/azurerm", version = "= 4.81.0" }
  }
  backend "local" {}
  encryption {
    key_provider "pbkdf2" "bootstrap" {
      passphrase    = trimspace(file(var.bootstrap_key_file))
      key_length    = 32
      iterations    = 600000
      salt_length   = 32
      hash_function = "sha512"
    }
    method "aes_gcm" "bootstrap" { keys = key_provider.pbkdf2.bootstrap }
    state {
      method   = method.aes_gcm.bootstrap
      enforced = true
    }
    plan {
      method   = method.aes_gcm.bootstrap
      enforced = true
    }
  }
}
provider "azurerm" {
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
  features {
    resource_group { prevent_deletion_if_contains_resources = true }
  }
}
