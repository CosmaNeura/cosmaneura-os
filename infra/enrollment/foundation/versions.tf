terraform {
  required_version = "= 1.12.5"
  required_providers {
    azurerm = { source = "registry.opentofu.org/hashicorp/azurerm", version = "= 4.81.0" }
  }
  # Bootstrap into a fresh private directory, never a clinical/product backend.
  backend "local" {}
}

provider "azurerm" {
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
  storage_use_azuread             = true
  features {
    storage { data_plane_available = false }
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
    resource_group { prevent_deletion_if_contains_resources = true }
  }
}

terraform {
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
