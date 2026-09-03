resource "azurerm_key_vault" "beta" {
  name                          = local.key_vault_name
  resource_group_name           = data.azurerm_resource_group.beta.name
  location                      = data.azurerm_resource_group.beta.location
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  soft_delete_retention_days    = 90
  purge_protection_enabled      = true
  rbac_authorization_enabled    = true
  public_network_access_enabled = false
  tags                          = local.tags

  network_acls {
    bypass         = "None"
    default_action = "Deny"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_private_endpoint" "key_vault" {
  name                = "pe-key-vault-${var.beta_id}"
  resource_group_name = data.azurerm_resource_group.beta.name
  location            = data.azurerm_resource_group.beta.location
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-key-vault-${var.beta_id}"
    private_connection_resource_id = azurerm_key_vault.beta.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "key-vault"
    private_dns_zone_ids = [azurerm_private_dns_zone.key_vault.id]
  }

  depends_on = [
    azurerm_private_dns_zone_virtual_network_link.key_vault,
    azurerm_private_dns_zone_virtual_network_link.key_vault_to_runner,
  ]
}

resource "azurerm_role_assignment" "runtime_key_vault_secrets" {
  scope                            = azurerm_key_vault.beta.id
  role_definition_name             = "Key Vault Secrets User"
  principal_id                     = azurerm_user_assigned_identity.runtime.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "deploy_key_vault_secrets" {
  scope                            = azurerm_key_vault.beta.id
  role_definition_name             = "Key Vault Secrets Officer"
  principal_id                     = data.azurerm_user_assigned_identity.deploy.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_key_vault_secret" "database_url" {
  count = var.deploy_workloads && var.runtime_database_url != null ? 1 : 0

  name         = "database-url"
  value        = var.runtime_database_url
  key_vault_id = azurerm_key_vault.beta.id
  content_type = "Cosmas OS early-adopter beta DATABASE_URL"
  tags         = local.tags

  depends_on = [
    azurerm_private_endpoint.key_vault,
    azurerm_private_dns_zone_virtual_network_link.key_vault_to_runner,
    azurerm_role_assignment.deploy_key_vault_secrets,
  ]

  lifecycle {
    precondition {
      condition     = strcontains(var.runtime_database_url, "@${azurerm_postgresql_flexible_server.beta.fqdn}:5432/cosmas_os?sslmode=verify-full&sslrootcert=system")
      error_message = "runtime_database_url must target the dedicated private beta PostgreSQL server and cosmas_os database with verify-full TLS using the system CA bundle."
    }
  }
}

resource "azurerm_key_vault_secret" "redis_url" {
  count = var.deploy_workloads ? 1 : 0

  name         = "redis-url"
  value        = local.redis_url
  key_vault_id = azurerm_key_vault.beta.id
  content_type = "Cosmas OS early-adopter beta REDIS_URL"
  tags         = local.tags

  depends_on = [
    azurerm_private_endpoint.key_vault,
    azurerm_private_dns_zone_virtual_network_link.key_vault_to_runner,
    azurerm_role_assignment.deploy_key_vault_secrets,
  ]
}

resource "azurerm_key_vault_secret" "clinic_approval_reference" {
  count = var.deploy_workloads && local.is_authorized_beta && var.clinic_approval_reference != null ? 1 : 0

  name         = "clinic-approval-reference"
  value        = var.clinic_approval_reference
  key_vault_id = azurerm_key_vault.beta.id
  content_type = "Cosmas OS early-adopter beta clinic approval evidence reference"
  tags         = local.tags

  depends_on = [
    azurerm_private_endpoint.key_vault,
    azurerm_role_assignment.deploy_key_vault_secrets,
  ]
}

resource "azurerm_key_vault_secret" "baa_evidence_reference" {
  count = var.deploy_workloads && local.is_authorized_beta && var.baa_evidence_reference != null ? 1 : 0

  name         = "baa-evidence-reference"
  value        = var.baa_evidence_reference
  key_vault_id = azurerm_key_vault.beta.id
  content_type = "Cosmas OS early-adopter beta BAA evidence reference"
  tags         = local.tags

  depends_on = [
    azurerm_private_endpoint.key_vault,
    azurerm_role_assignment.deploy_key_vault_secrets,
  ]
}

resource "azurerm_key_vault_secret" "phi_authorization_reference" {
  count = var.deploy_workloads && local.is_authorized_beta && var.phi_authorization_reference != null ? 1 : 0

  name         = "phi-authorization-reference"
  value        = var.phi_authorization_reference
  key_vault_id = azurerm_key_vault.beta.id
  content_type = "Cosmas OS authorized beta PHI release authorization reference"
  tags         = local.tags

  depends_on = [
    azurerm_private_endpoint.key_vault,
    azurerm_role_assignment.deploy_key_vault_secrets,
  ]
}

resource "azurerm_key_vault_secret" "human_deploy_evidence_reference" {
  count = var.deploy_workloads ? 1 : 0

  name         = "human-deploy-evidence-reference"
  value        = var.human_deploy_evidence_reference
  key_vault_id = azurerm_key_vault.beta.id
  content_type = "Cosmas OS early-adopter beta human deploy evidence reference"
  tags         = local.tags

  depends_on = [
    azurerm_private_endpoint.key_vault,
    azurerm_role_assignment.deploy_key_vault_secrets,
  ]
}

# This per-deployment random key authenticates short-lived, sanitized
# acceptance-state envelopes across separate manual Job executions. It is
# generated once in private Terraform state and is exposed only to the runtime
# UAMI through a Key Vault-backed Container Apps Job secret reference.
resource "random_id" "runtime_acceptance_hmac_key" {
  count       = var.deploy_workloads && !local.is_authorized_beta ? 1 : 0
  byte_length = 32
}

resource "azurerm_key_vault_secret" "runtime_acceptance_hmac_key" {
  count = var.deploy_workloads && !local.is_authorized_beta ? 1 : 0

  name         = "runtime-acceptance-hmac-key"
  value        = random_id.runtime_acceptance_hmac_key[0].hex
  key_vault_id = azurerm_key_vault.beta.id
  content_type = "Cosmas OS D3 short-lived synthetic acceptance-state HMAC key"
  tags         = local.tags

  depends_on = [
    azurerm_private_endpoint.key_vault,
    azurerm_role_assignment.deploy_key_vault_secrets,
  ]

  lifecycle {
    prevent_destroy = true
  }
}
