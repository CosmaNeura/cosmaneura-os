mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      object_id       = "00000000-0000-4000-8000-000000000003"
      subscription_id = "00000000-0000-4000-8000-000000000001"
      tenant_id       = "00000000-0000-4000-8000-000000000002"
    }
  }

  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01"
    }
  }

  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-cosmas-os-beta-deploy-lab01"
      client_id    = "00000000-0000-4000-8000-000000000005"
      principal_id = "00000000-0000-4000-8000-000000000006"
    }
  }

  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Storage/storageAccounts/cmbetatflab01abc123"
    }
  }

  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Storage/storageAccounts/cmbetatflab01abc123/blobServices/default/containers/tfstate"
    }
  }

  mock_resource "azurerm_virtual_network" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-lab01"
    }
  }

  mock_resource "azurerm_network_interface" {
    defaults = {
      id                 = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/networkInterfaces/nic-cosmas-os-beta-runner-lab01"
      private_ip_address = "10.254.0.36"
    }
  }

  mock_resource "azurerm_linux_virtual_machine" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Compute/virtualMachines/vm-cosmas-os-beta-runner-lab01"
    }
  }

  mock_resource "azurerm_public_ip" {
    defaults = {
      id         = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/publicIPAddresses/pip-cosmas-os-beta-runner-egress-lab01"
      ip_address = "192.0.2.10"
    }
  }

  mock_resource "azurerm_network_security_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/networkSecurityGroups/nsg-cosmas-os-beta-runner-lab01"
    }
  }

  mock_resource "azurerm_nat_gateway" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/natGateways/nat-cosmas-os-beta-runner-lab01"
    }
  }

  mock_resource "azurerm_subnet" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-lab01/subnets/snet-private-endpoints"
    }
  }

  mock_resource "azurerm_private_dns_zone" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
    }
  }

  mock_resource "azurerm_private_endpoint" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/privateEndpoints/pe-state-blob-lab01"
    }
  }
}

mock_provider "random" {
  mock_resource "random_string" {
    defaults = {
      result = "abc123"
    }
  }
}

variables {
  subscription_id                   = "00000000-0000-4000-8000-000000000001"
  tenant_id                         = "00000000-0000-4000-8000-000000000002"
  beta_id                           = "lab01"
  box_id                            = "00000000-0000-4000-8000-000000000004"
  human_deploy_evidence_reference   = "deploy:test"
  region_evidence_reference         = "region:test"
  runner_network_evidence_reference = "network:test"
  runner_admin_ssh_public_key       = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIF/eL0FJr4tZHTbXoX1MfcEO88lXLh5geZG3rhLcPcDE test@example.invalid"
  runner_image_version              = "22.04.202608060"
  monthly_budget_amount             = 350
  budget_start_date                 = "2026-09-01T00:00:00Z"
  budget_contact_emails             = ["owner@example.invalid"]
}

run "synthetic_lab_omits_clinic_baa_and_phi_evidence" {
  command = plan

  assert {
    condition = (
      output.deployment_mode == "synthetic_lab" &&
      output.data_classification == "synthetic-only"
    )
    error_message = "The default bootstrap mode must remain explicitly synthetic-only."
  }

  assert {
    condition = (
      one(azurerm_storage_account.state.blob_properties).versioning_enabled == true &&
      one(one(azurerm_storage_account.state.blob_properties).delete_retention_policy).days == 30 &&
      one(one(azurerm_storage_account.state.blob_properties).container_delete_retention_policy).days == 30
    )
    error_message = "The bootstrap tfstate account must retain versioning and 30-day Blob/container soft-delete protection."
  }

  assert {
    condition = (
      azurerm_consumption_budget_subscription.beta.amount == 350 &&
      one([
        for filter in azurerm_consumption_budget_subscription.beta.filter :
        toset(one([for dimension in filter.dimension : dimension.values]))
        ]) == toset([
        azurerm_resource_group.state.name,
        azurerm_resource_group.workload.name,
      ])
    )
    error_message = "The notification-only $350 budget must aggregate the exact state/runner and workload resource groups."
  }

  assert {
    condition = (
      local.tags.deployment_mode == "synthetic_lab" &&
      local.tags.data_classification == "synthetic-only" &&
      local.tags.box_scope == "dedicated"
    )
    error_message = "Synthetic Lab resources must retain explicit mode, classification, and dedicated-Box tags."
  }

  assert {
    condition     = length(terraform_data.authorized_beta_mode_lock) == 0
    error_message = "Synthetic Lab must not claim an authorized-beta mode lock."
  }

  assert {
    condition = (
      azurerm_linux_virtual_machine.deploy_runner.disable_password_authentication == true &&
      azurerm_linux_virtual_machine.deploy_runner.secure_boot_enabled == true &&
      azurerm_linux_virtual_machine.deploy_runner.vtpm_enabled == true &&
      one(azurerm_linux_virtual_machine.deploy_runner.source_image_reference).version == "22.04.202608060" &&
      one(one(azurerm_linux_virtual_machine.deploy_runner.identity).identity_ids) == azurerm_user_assigned_identity.deploy.id &&
      length(azurerm_network_interface.deploy_runner.ip_configuration) == 1 &&
      one(azurerm_network_interface.deploy_runner.ip_configuration).public_ip_address_id == null &&
      azurerm_subnet.deploy_runner.default_outbound_access_enabled == false
    )
    error_message = "The protected deployment runner must be password-disabled, Trusted Launch hardened, private-only, and attached to the exact deploy identity."
  }

  assert {
    condition = (
      toset(one([
        for rule in azurerm_network_security_group.deploy_runner.security_rule : rule.destination_port_ranges
        if rule.name == "AllowPrivateDeploymentPorts"
      ])) == toset(["443", "5432", "10000"]) &&
      one([
        for rule in azurerm_network_security_group.deploy_runner.security_rule : rule.access
        if rule.name == "DenyAllInbound"
      ]) == "Deny" &&
      one([
        for rule in azurerm_network_security_group.deploy_runner.security_rule : rule.destination_address_prefix
        if rule.name == "AllowAzureDnsUdp"
      ]) == "168.63.129.16" &&
      one([
        for rule in azurerm_network_security_group.deploy_runner.security_rule : rule.destination_address_prefix
        if rule.name == "AllowAzureDnsTcp"
      ]) == "168.63.129.16" &&
      output.state_vnet_id == azurerm_virtual_network.state.id &&
      output.state_blob_private_dns_zone_id == azurerm_private_dns_zone.state_blob.id &&
      output.runner_subnet_id == azurerm_subnet.deploy_runner.id &&
      output.runner_network_security_group_id == azurerm_network_security_group.deploy_runner.id &&
      output.runner_nat_gateway_id == azurerm_nat_gateway.deploy_runner.id
    )
    error_message = "Runner networking must deny inbound/default outbound, permit only reviewed private service ports, and expose exact handoff IDs."
  }

  assert {
    condition = (
      azurerm_role_assignment.deploy_state.scope == azurerm_storage_account.state.id &&
      azurerm_role_assignment.deploy_state.role_definition_name == "Storage Blob Data Contributor" &&
      azurerm_role_assignment.deploy_state_network.scope == azurerm_virtual_network.state.id &&
      azurerm_role_assignment.deploy_state_network.role_definition_name == "Network Contributor" &&
      azurerm_role_assignment.deploy_state_private_dns.scope == azurerm_private_dns_zone.state_blob.id &&
      azurerm_role_assignment.deploy_state_private_dns.role_definition_name == "Private DNS Zone Contributor"
    )
    error_message = "The deploy identity must have only the scoped state Blob, state VNet, and private-DNS rights needed by the guarded workflow."
  }
}

run "authorized_beta_rejects_missing_clinic" {
  command = plan

  variables {
    deployment_mode             = "authorized_beta"
    baa_evidence_reference      = "baa:test"
    phi_authorization_reference = "phi:test"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "authorized_beta_rejects_missing_baa" {
  command = plan

  variables {
    deployment_mode             = "authorized_beta"
    clinic_legal_name           = "Invented Test Clinic"
    phi_authorization_reference = "phi:test"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "authorized_beta_rejects_missing_phi_authorization" {
  command = plan

  variables {
    deployment_mode        = "authorized_beta"
    clinic_legal_name      = "Invented Test Clinic"
    baa_evidence_reference = "baa:test"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "authorized_beta_accepts_all_phi_prerequisites" {
  command = plan

  variables {
    deployment_mode             = "authorized_beta"
    clinic_legal_name           = "Invented Test Clinic"
    baa_evidence_reference      = "baa:test"
    phi_authorization_reference = "phi:test"
  }

  assert {
    condition = (
      output.deployment_mode == "authorized_beta" &&
      output.data_classification == "phi-authorized"
    )
    error_message = "The PHI-capable bootstrap mode must be labeled authorized_beta and phi-authorized."
  }

  assert {
    condition     = length(terraform_data.authorized_beta_mode_lock) == 1
    error_message = "Authorized beta must create a non-downgradable mode lock."
  }
}

run "rejects_unreviewed_runner_image_version" {
  command = plan

  variables {
    runner_image_version = "22.04.202608200"
  }

  expect_failures = [var.runner_image_version]
}
