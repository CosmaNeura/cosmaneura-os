# Invented values only; all Azure resources are mocked. No provider credentials or cloud calls.
mock_provider "azurerm" {
  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-runtime"
      client_id    = "00000000-0000-4000-8000-000000000010"
      principal_id = "aaaaaaaa-0000-4000-8000-000000000011"
    }
  }
  mock_resource "azurerm_linux_virtual_machine" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Compute/virtualMachines/vm-workload"
    }
  }
  mock_resource "azurerm_managed_disk" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Compute/disks/data-workload"
    }
  }
  mock_resource "azurerm_network_interface" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Network/networkInterfaces/nic-workload"
    }
  }
  mock_resource "azurerm_public_ip" {
    defaults = {
      id         = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Network/publicIPAddresses/pip-workload"
      ip_address = "192.0.2.10"
    }
  }
  mock_resource "azurerm_virtual_network" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Network/virtualNetworks/vnet-workload"
    }
  }
  mock_resource "azurerm_subnet" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Network/virtualNetworks/vnet-workload/subnets/subnet"
    }
  }
  mock_resource "azurerm_network_security_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Network/networkSecurityGroups/nsg-workload"
    }
  }
  mock_resource "azurerm_private_dns_zone" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
    }
  }
  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.KeyVault/vaults/kv-staging"
      vault_uri = "https://kv-staging.vault.azure.net/"
    }
  }
  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.ContainerRegistry/registries/acrstage"
      login_server = "acrstage.azurecr.io"
    }
  }
  mock_resource "azurerm_storage_account" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Storage/storageAccounts/stmock"
      primary_blob_endpoint = "https://stmock.blob.core.windows.net/"
    }
  }
  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Storage/storageAccounts/stmock/blobServices/default/containers/objects"
    }
  }
  mock_resource "azurerm_monitor_action_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.Insights/actionGroups/ag-staging"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-vm-staging-eus2-lab01/providers/Microsoft.OperationalInsights/workspaces/law-staging"
    }
  }
}

variables {
  subscription_id            = "00000000-0000-4000-8000-000000000001"
  tenant_id                  = "00000000-0000-4000-8000-000000000002"
  resource_name_suffix       = "mock1234"
  state_namespace            = "cosmabot-vm/eastus2/lab01/local-initial"
  vnet_address_prefix        = "10.248.0.0/24"
  admin_username             = "cosmasoperator"
  admin_ssh_public_key       = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIF/eL0FJr4tZHTbXoX1MfcEO88lXLh5geZG3rhLcPcDE test@example.invalid"
  ubuntu_image_version       = "22.04.202608060"
  release_operator_object_id = "00000000-0000-4000-8000-000000000003"
  alert_contact_email        = "operator@example.invalid"
}
run "private_eastus2_foundation" {
  command = plan
  assert {
    condition = (
      azurerm_resource_group.staging.name == "rg-cosmas-os-vm-staging-eus2-lab01" &&
      azurerm_linux_virtual_machine.workload.name == "vm-cosmabot-staging-eus2-lab01" &&
      azurerm_linux_virtual_machine.workload.location == "eastus2" &&
      azurerm_linux_virtual_machine.workload.size == "Standard_D2s_v5" &&
      one(azurerm_linux_virtual_machine.workload.os_disk).disk_size_gb == 64 &&
      azurerm_managed_disk.data.disk_size_gb == 128 &&
      azurerm_virtual_machine_data_disk_attachment.data.lun == 0
    )
    error_message = "Foundation must create the selected new East US 2 D2s_v5 host and persistent disks."
  }
  assert {
    condition = (
      azurerm_linux_virtual_machine.workload.disable_password_authentication &&
      azurerm_linux_virtual_machine.workload.secure_boot_enabled &&
      azurerm_linux_virtual_machine.workload.vtpm_enabled &&
      azurerm_linux_virtual_machine.workload.custom_data == null &&
      azurerm_linux_virtual_machine.workload.user_data == null &&
      one(azurerm_linux_virtual_machine.workload.source_image_reference).version == "22.04.202608060" &&
      one(azurerm_linux_virtual_machine.workload.identity).type == "UserAssigned" &&
      length(one(azurerm_linux_virtual_machine.workload.identity).identity_ids) == 1 &&
      one(one(azurerm_linux_virtual_machine.workload.identity).identity_ids) == azurerm_user_assigned_identity.runtime.id
    )
    error_message = "The host must have key-only auth, pinned image, secure boot and one runtime identity, without app/secret user data."
  }
  assert {
    condition = (
      length(azurerm_network_security_group.workload.security_rule) == 3 &&
      toset([for rule in azurerm_network_security_group.workload.security_rule : rule.destination_port_range if rule.access == "Allow"]) == toset(["80", "443"]) &&
      alltrue([for rule in azurerm_network_security_group.workload.security_rule : rule.direction == "Inbound"]) &&
      length([for rule in azurerm_network_security_group.workload.security_rule : rule if rule.access == "Deny" && rule.priority == 4000 && rule.source_address_prefix == "*" && rule.destination_port_range == "*"]) == 1 &&
      !azurerm_subnet.workload.default_outbound_access_enabled &&
      azurerm_public_ip.workload.sku == "Standard"
    )
    error_message = "Allow only web TLS/ACME ingress, override default VNet ingress and use explicit public-IP outbound."
  }
  assert {
    condition = (
      azurerm_container_registry.staging.sku == "Premium" &&
      !azurerm_container_registry.staging.public_network_access_enabled &&
      !azurerm_container_registry.staging.admin_enabled &&
      !azurerm_container_registry.staging.anonymous_pull_enabled &&
      azurerm_container_registry.staging.network_rule_bypass_option == "None" &&
      !azurerm_key_vault.staging.public_network_access_enabled &&
      azurerm_key_vault.staging.rbac_authorization_enabled &&
      azurerm_key_vault.staging.purge_protection_enabled &&
      length(azurerm_private_endpoint.service) == 4 &&
      length(azurerm_private_dns_zone.service) == 3
    )
    error_message = "Registry, vault and both Blob accounts must retain the selected private network posture."
  }
  assert {
    condition = alltrue([for account in azurerm_storage_account.objects :
      account.account_kind == "StorageV2" && account.account_replication_type == "LRS" && account.access_tier == "Hot" &&
      account.min_tls_version == "TLS1_2" && !account.public_network_access_enabled && !account.shared_access_key_enabled &&
      !account.allow_nested_items_to_be_public && account.infrastructure_encryption_enabled
      ]) && (
      one(azurerm_storage_account.objects["backup"].blob_properties).versioning_enabled &&
      !one(azurerm_storage_account.objects["application"].blob_properties).versioning_enabled &&
      alltrue([for container in azurerm_storage_container.objects : container.container_access_type == "private"])
    )
    error_message = "Dedicated private OAuth storage must separate application deletion semantics from backup recovery protection."
  }
  assert {
    condition = (
      azurerm_role_assignment.runtime_application_blob.role_definition_name == "Storage Blob Data Contributor" &&
      azurerm_role_assignment.runtime_application_blob.scope == azurerm_storage_container.objects["application"].id &&
      azurerm_role_assignment.runtime_application_blob.principal_id == azurerm_user_assigned_identity.runtime.principal_id &&
      azurerm_role_assignment.release_registry.role_definition_name == "AcrPush" &&
      azurerm_role_assignment.release_registry.principal_id == var.release_operator_object_id &&
      azurerm_role_assignment.release_secrets.role_definition_name == "Key Vault Secrets Officer" &&
      azurerm_role_assignment.release_secrets.principal_id == var.release_operator_object_id &&
      length(azurerm_monitor_metric_alert.vm) == 3 &&
      azurerm_log_analytics_workspace.staging.daily_quota_gb == 0.1 &&
      !output.foundation.application_deployed && output.foundation.bootstrap_required
    )
    error_message = "Release authority must stay off VM; platform alerts and foundation output must not claim an app deployment."
  }
}

run "reject_region" {
  command = plan
  variables {
    location = "centralus"
  }
  expect_failures = [var.location]
}
run "reject_state_reuse" {
  command = plan
  variables {
    state_namespace = "managed/foundation.tfstate"
  }
  expect_failures = [var.state_namespace]
}
run "reject_public_network" {
  command = plan
  variables {
    vnet_address_prefix = "8.8.8.0/24"
  }
  expect_failures = [var.vnet_address_prefix]
}
run "reject_host_bits" {
  command = plan
  variables {
    vnet_address_prefix = "10.248.0.1/24"
  }
  expect_failures = [var.vnet_address_prefix]
}
run "reject_ipv6" {
  command = plan
  variables {
    vnet_address_prefix = "fd00::/64"
  }
  expect_failures = [var.vnet_address_prefix]
}
run "reject_small_network" {
  command = plan
  variables {
    vnet_address_prefix = "10.248.0.0/28"
  }
  expect_failures = [var.vnet_address_prefix]
}
run "reject_latest_image" {
  command = plan
  variables {
    ubuntu_image_version = "latest"
  }
  expect_failures = [var.ubuntu_image_version]
}
run "reject_private_key_input" {
  command = plan
  variables {
    admin_ssh_public_key = "-----BEGIN OPENSSH PRIVATE KEY-----"
  }
  expect_failures = [var.admin_ssh_public_key]
}
run "reject_root_admin" {
  command = plan
  variables {
    admin_username = "root"
  }
  expect_failures = [var.admin_username]
}
run "reject_invalid_subscription" {
  command = plan
  variables {
    subscription_id = "default"
  }
  expect_failures = [var.subscription_id]
}
run "reject_missing_operator" {
  command = plan
  variables {
    release_operator_object_id = ""
  }
  expect_failures = [var.release_operator_object_id]
}
run "reject_invalid_alert_recipient" {
  command = plan
  variables {
    alert_contact_email = "not-email"
  }
  expect_failures = [var.alert_contact_email]
}

run "reject_unreviewed_image" {
  command = plan
  variables {
    ubuntu_image_version = "22.04.202608200"
  }
  expect_failures = [var.ubuntu_image_version]
}

run "reject_runtime_identity_as_privileged_operator" {
  command = plan
  variables {
    release_operator_object_id = "AAAAAAAA-0000-4000-8000-000000000011"
  }
  expect_failures = [azurerm_role_assignment.release_registry, azurerm_role_assignment.release_secrets]
}
