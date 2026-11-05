mock_provider "azurerm" {
  mock_resource "azurerm_subnet" {
    defaults = {
      "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-production-mockhost/providers/Microsoft.Network/virtualNetworks/vnet-cosmabot-enrollment-production-mockhost/subnets/snet-allocator-host"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      "id" : "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-production-mockhost/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-cosmabot-enrollment-allocator-production"
      "client_id" : "00000000-0000-4000-8000-0000000000aa"
      "principal_id" : "00000000-0000-4000-8000-0000000000bb"
    }
  }
}

variables {
  subscription_id     = "00000000-0000-4000-8000-000000000001"
  tenant_id           = "00000000-0000-4000-8000-000000000002"
  environment         = "production"
  resource_group_name = "rg-cosmabot-enrollment-production-mockhost"
  location            = "centralus"
  vnet_name           = "vnet-cosmabot-enrollment-production-mockhost"
  host_subnet_prefix  = "10.248.2.128/26"
}

run "stays_dark_by_default" {
  command = plan

  assert {
    condition     = var.create_resources == false
    error_message = "Allocator-host resources must default off so plans bill nothing."
  }
  assert {
    condition     = length(azurerm_subnet.allocator_host) == 0 && length(azurerm_user_assigned_identity.allocator) == 0
    error_message = "Held create_resources=false must plan zero Azure resources."
  }
  assert {
    condition = (output.allocator_host.create_resources == false &&
      output.allocator_host.resources_created == false &&
      output.allocator_host.worker_started == false &&
      output.allocator_host.hosting_configuration_enabled == false &&
      output.allocator_host.p2_extra_box_authorized == false &&
      output.allocator_host.stripe_live_mode == false &&
      output.allocator_host.practice_uuid_limit == 1 &&
      output.allocator_host.worker_client_id == null &&
      output.allocator_host.host_subnet_id == null)
    error_message = "Dark output must keep activation holds false and IDs empty."
  }
}

run "create_without_hold_release_fails" {
  command = plan
  variables {
    create_resources = true
  }
  expect_failures = [terraform_data.holds]
}

run "create_with_hold_release_plans_identity_and_subnet" {
  command = plan
  variables {
    create_resources    = true
    hold_release_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }

  assert {
    condition     = length(azurerm_subnet.allocator_host) == 1 && length(azurerm_user_assigned_identity.allocator) == 1
    error_message = "Authorized create_resources must plan the non-delegated host subnet and worker identity."
  }
  assert {
    condition = (one(azurerm_subnet.allocator_host).name == "snet-allocator-host" &&
      !one(azurerm_subnet.allocator_host).default_outbound_access_enabled &&
      one(azurerm_user_assigned_identity.allocator).name == "id-cosmabot-enrollment-allocator-production" &&
      output.allocator_host.practice_uuid_limit == 1 &&
      output.allocator_host.worker_started == false &&
      output.allocator_host.p2_extra_box_authorized == false)
    error_message = "Created host recipe must stay non-delegated, private-outbound-off, and still not start the worker or authorize P2."
  }
}
