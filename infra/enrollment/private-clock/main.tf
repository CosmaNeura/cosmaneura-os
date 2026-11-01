variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "foundation_file" { type = string }
variable "resource_name_suffix" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9]{6,8}$", var.resource_name_suffix))
    error_message = "Use a fresh reviewed 6–8 character staging suffix."
  }
}
variable "bootstrap_key_file" {
  type      = string
  sensitive = true
}
variable "postgres_admin_password" {
  type      = string
  sensitive = true
  ephemeral = true
}
variable "binding_sha256" {
  type        = map(string)
  default     = {}
  description = "Only canonical approved private binding hashes, never the binding documents or vendor/customer data."
  validation {
    condition     = length(var.binding_sha256) == 0 || toset(keys(var.binding_sha256)) == toset(["a", "b"]) && length(toset(values(var.binding_sha256))) == 2 && alltrue([for h in values(var.binding_sha256) : can(regex("^[0-9a-f]{64}$", h))])
    error_message = "Closed capacity may be unbound; otherwise exactly two distinct protected hashes are required."
  }
}
variable "operation" {
  type    = string
  default = "check"
  validation {
    condition     = contains(["bootstrap", "check"], var.operation)
    error_message = "Only explicit manual bootstrap or restricted journal check is supported."
  }
}
variable "create_job" {
  type    = bool
  default = false
}
variable "image" {
  type    = string
  default = ""
}
variable "secret_references" {
  type        = map(string)
  default     = {}
  description = "Selected exact versioned owned private KV references only. Values never enter OpenTofu."
}
variable "runtime_principal_ids" {
  type        = map(string)
  default     = {}
  description = "Optional exact already-owned composition workload principal IDs, each granted only its own journal credential."
  validation {
    condition     = alltrue([for slot, id in var.runtime_principal_ids : contains(["a", "b"], slot) && can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", id))]) && length(toset(values(var.runtime_principal_ids))) == length(var.runtime_principal_ids)
    error_message = "Use distinct explicitly reviewed composition principal IDs only."
  }
}
locals {
  raw      = jsondecode(file(var.foundation_file))
  f        = try(local.raw.foundation.value, local.raw)
  prefix   = "/subscriptions/${var.subscription_id}/resourceGroups/${local.f.resource_group_name}/providers"
  name     = "psql-cbot-clock-stg-${var.resource_name_suffix}"
  tags     = { product = "cosmabot", component = "private-stripe-clock-journal", environment = "staging", clinical_data = "false", hosted_qualified = "false" }
  names    = { admin = "enrollment-private-clock-bootstrap-url", a = "enrollment-private-clock-journal-a-url", b = "enrollment-private-clock-journal-b-url", bindings = "enrollment-private-clock-bindings" }
  selected = var.operation == "bootstrap" ? toset(keys(local.names)) : toset(["a", "b", "bindings"])
}
resource "terraform_data" "guard" {
  lifecycle {
    precondition {
      condition     = length(var.binding_sha256) == 2 || !var.create_job && length(var.runtime_principal_ids) == 0
      error_message = "Two frozen binding hashes are required before any job or composition secret grant."
    }
    precondition {
      condition = (local.f.contract_version == "enrollment-foundation.v1" && local.f.environment == "staging" && local.f.postgres_database == "cosmabot_enrollment" &&
        local.f.subscription_id == var.subscription_id && local.f.tenant_id == var.tenant_id && contains(["centralus", "eastus2"], local.f.location) &&
        can(regex("^rg-cosmabot-enrollment-staging-[a-z0-9]{6,8}$", local.f.resource_group_name)) &&
        startswith(local.f.vnet_id, "${local.prefix}/Microsoft.Network/virtualNetworks/") && local.f.postgres_subnet_id == "${local.f.vnet_id}/subnets/snet-postgres" &&
        startswith(local.f.container_app_environment_id, "${local.prefix}/Microsoft.App/managedEnvironments/") &&
        startswith(local.f.container_registry_id, "${local.prefix}/Microsoft.ContainerRegistry/registries/") &&
        local.f.registry_server == "${split("/", local.f.container_registry_id)[8]}.azurecr.io" &&
        startswith(local.f.key_vault_id, "${local.prefix}/Microsoft.KeyVault/vaults/") &&
      local.f.key_vault_uri == "https://${split("/", local.f.key_vault_id)[8]}.vault.azure.net/")
      error_message = "Use exact owned private staging foundation coordinates only; no central database modification."
    }
    precondition {
      condition = (!var.create_job && length(var.secret_references) == 0 && var.image == "" || var.create_job &&
        startswith(var.image, "${local.f.registry_server}/") && can(regex("@sha256:[0-9a-f]{64}$", var.image)) &&
        toset(keys(var.secret_references)) == local.selected &&
      alltrue([for name, ref in var.secret_references : can(regex("^[0-9a-f]{32}$", trimprefix(ref, "${local.f.key_vault_uri}secrets/${lookup(local.names, name, "invalid")}/")))]))
      error_message = "Jobs require the owned immutable image and exact selected versioned journal-only secrets."
    }
  }
}
resource "azurerm_private_dns_zone" "clock" {
  name                = "clock-${var.resource_name_suffix}.postgres.database.azure.com"
  resource_group_name = local.f.resource_group_name
  tags                = local.tags
  depends_on          = [terraform_data.guard]
  lifecycle { prevent_destroy = true }
}
resource "azurerm_private_dns_zone_virtual_network_link" "clock" {
  name                  = "clock-${var.resource_name_suffix}"
  resource_group_name   = local.f.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.clock.name
  virtual_network_id    = local.f.vnet_id
  registration_enabled  = false
  tags                  = local.tags
}
resource "azurerm_postgresql_flexible_server" "clock" {
  name                              = local.name
  resource_group_name               = local.f.resource_group_name
  location                          = local.f.location
  version                           = "16"
  sku_name                          = "B_Standard_B1ms"
  storage_mb                        = 32768
  auto_grow_enabled                 = false
  backup_retention_days             = 7
  geo_redundant_backup_enabled      = false
  public_network_access_enabled     = false
  delegated_subnet_id               = local.f.postgres_subnet_id
  private_dns_zone_id               = azurerm_private_dns_zone.clock.id
  administrator_login               = "clock_bootstrap"
  administrator_password_wo         = var.postgres_admin_password
  administrator_password_wo_version = 1
  authentication {
    password_auth_enabled         = true
    active_directory_auth_enabled = false
  }
  tags       = local.tags
  depends_on = [azurerm_private_dns_zone_virtual_network_link.clock]
  lifecycle { prevent_destroy = true }
}
resource "azurerm_postgresql_flexible_server_configuration" "tls" {
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.clock.id
  value     = "on"
}
resource "azurerm_postgresql_flexible_server_database" "clock" {
  name      = "cosmabot_enrollment_clock_lab"
  server_id = azurerm_postgresql_flexible_server.clock.id
  charset   = "UTF8"
  collation = "en_US.utf8"
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "runtime" {
  for_each             = var.runtime_principal_ids
  scope                = "${local.f.key_vault_id}/secrets/${local.names[each.key]}"
  role_definition_name = "Key Vault Secrets User"
  principal_id         = each.value
  depends_on           = [terraform_data.guard]
}
output "private_clock" {
  value = {
    contract_version         = "enrollment-private-clock-infrastructure.v1", environment = "staging", hosted_qualified = false,
    subscription_id          = var.subscription_id, tenant_id = var.tenant_id, resource_group_name = local.f.resource_group_name, location = local.f.location,
    postgres_server_id       = azurerm_postgresql_flexible_server.clock.id, postgres_fqdn = azurerm_postgresql_flexible_server.clock.fqdn,
    postgres_database        = azurerm_postgresql_flexible_server_database.clock.name, postgres_admin_login = "clock_bootstrap",
    journal_logins           = { a = "clock_journal_a", b = "clock_journal_b" }, binding_sha256 = var.binding_sha256,
    key_vault_id             = local.f.key_vault_id, key_vault_uri = local.f.key_vault_uri, secret_names = local.names,
    manual_job_created       = var.create_job, manual_job_started = false,
    runtime_grants_created   = length(var.runtime_principal_ids) > 0,
    vnet_id                  = local.f.vnet_id, postgres_subnet_id = local.f.postgres_subnet_id,
    source_database_modified = false
  }
}
