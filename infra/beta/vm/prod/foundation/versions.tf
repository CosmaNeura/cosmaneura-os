terraform {
  required_version = "= 1.12.5"
  required_providers {
    azurerm = {
      source  = "registry.opentofu.org/hashicorp/azurerm"
      version = "= 4.81.0"
    }
  }
  # Fresh encrypted local bootstrap; bootstrap_local.py pins its isolated absolute path.
  backend "local" {}
}
provider "azurerm" {
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
  storage_use_azuread             = true
  features {
    storage {
      data_plane_available = false
    }
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
    # Explicit pin: destroying/replacing the workload VM must delete its OS disk
    # (Azure portal Detach would otherwise leave osdisk-vm-cosmabot-prod-eus2-01).
    virtual_machine {
      delete_os_disk_on_deletion = true
    }
  }
}
