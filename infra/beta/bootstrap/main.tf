data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "state" {
  name     = local.state_resource_group_name
  location = var.location
  tags     = local.tags

  depends_on = [terraform_data.prerequisite_guard]

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_resource_group" "workload" {
  name     = local.workload_resource_group_name
  location = var.location
  tags     = local.tags

  depends_on = [terraform_data.prerequisite_guard]

  lifecycle {
    prevent_destroy = true
  }
}

# The human bootstrap identity owns this subscription-level notification-only
# budget. The later deploy UAMI is deliberately resource-group scoped.
resource "azurerm_consumption_budget_subscription" "beta" {
  name            = "budget-cosmas-os-beta-${var.beta_id}"
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = var.monthly_budget_amount
  time_grain      = "Monthly"

  time_period {
    start_date = var.budget_start_date
  }

  filter {
    dimension {
      name     = "ResourceGroupName"
      operator = "In"
      values = [
        azurerm_resource_group.state.name,
        azurerm_resource_group.workload.name,
      ]
    }
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = var.budget_contact_emails
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = var.budget_contact_emails
  }

  depends_on = [terraform_data.prerequisite_guard]
}

resource "azurerm_user_assigned_identity" "deploy" {
  name                = local.deploy_identity_name
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location
  tags                = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_virtual_network" "state" {
  name                = local.state_vnet_name
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location
  address_space       = var.state_vnet_address_space
  tags                = local.tags
}

resource "azurerm_subnet" "state_private_endpoints" {
  name                 = local.state_subnet_name
  resource_group_name  = azurerm_resource_group.state.name
  virtual_network_name = azurerm_virtual_network.state.name
  address_prefixes     = var.state_private_endpoint_subnet_prefixes

  private_endpoint_network_policies = "Disabled"
}

resource "azurerm_storage_account" "state" {
  name                              = local.state_storage_account_name
  resource_group_name               = azurerm_resource_group.state.name
  location                          = azurerm_resource_group.state.location
  account_tier                      = "Standard"
  account_replication_type          = "LRS"
  min_tls_version                   = "TLS1_2"
  public_network_access_enabled     = false
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  infrastructure_encryption_enabled = true
  tags                              = local.tags

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }

    container_delete_retention_policy {
      days = 30
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_private_dns_zone" "state_blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.state.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "state_blob" {
  name                  = "link-state-blob-${var.beta_id}"
  resource_group_name   = azurerm_resource_group.state.name
  private_dns_zone_name = azurerm_private_dns_zone.state_blob.name
  virtual_network_id    = azurerm_virtual_network.state.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_endpoint" "state_blob" {
  name                = "pe-state-blob-${var.beta_id}"
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location
  subnet_id           = azurerm_subnet.state_private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-state-blob-${var.beta_id}"
    private_connection_resource_id = azurerm_storage_account.state.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "state-blob"
    private_dns_zone_ids = [azurerm_private_dns_zone.state_blob.id]
  }
}

resource "azurerm_role_assignment" "deploy_state" {
  scope                            = azurerm_storage_account.state.id
  role_definition_name             = "Storage Blob Data Contributor"
  principal_id                     = azurerm_user_assigned_identity.deploy.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "deploy_state_reader" {
  scope                            = azurerm_resource_group.state.id
  role_definition_name             = "Reader"
  principal_id                     = azurerm_user_assigned_identity.deploy.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "deploy_state_network" {
  scope                            = azurerm_virtual_network.state.id
  role_definition_name             = "Network Contributor"
  principal_id                     = azurerm_user_assigned_identity.deploy.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "deploy_state_private_dns" {
  scope                            = azurerm_private_dns_zone.state_blob.id
  role_definition_name             = "Private DNS Zone Contributor"
  principal_id                     = azurerm_user_assigned_identity.deploy.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "deploy_workload" {
  scope                            = azurerm_resource_group.workload.id
  role_definition_name             = "Contributor"
  principal_id                     = azurerm_user_assigned_identity.deploy.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "deploy_workload_rbac" {
  scope                            = azurerm_resource_group.workload.id
  role_definition_name             = "User Access Administrator"
  principal_id                     = azurerm_user_assigned_identity.deploy.principal_id
  skip_service_principal_aad_check = true
}
