terraform {
  required_version = "= 1.12.5"
  required_providers {
    azurerm = { source = "registry.opentofu.org/hashicorp/azurerm", version = "= 4.81.0" }
  }
  backend "azurerm" { use_azuread_auth = true }
}
provider "azurerm" {
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
  features {
    resource_group { prevent_deletion_if_contains_resources = true }
  }
}
variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "foundation_file" { type = string }
variable "image" {
  type        = string
  description = "Exact reviewed database-job image in the new enrollment ACR, referenced by SHA-256, never a tag."
}
variable "operation" {
  type = string
  validation {
    condition     = contains(["bootstrap", "migrate", "check"], var.operation)
    error_message = "Only bootstrap, migrate or read-only grant/schema check is permitted."
  }
}
variable "secret_references" {
  type        = map(string)
  description = "Exact versioned KV URLs only: migration and runtime, plus admin for bootstrap. No values."
}
variable "create_job" {
  type    = bool
  default = false
}
locals {
  foundation            = jsondecode(file(var.foundation_file))
  f                     = try(local.foundation.foundation.value, local.foundation)
  names                 = var.operation == "bootstrap" ? toset(["admin", "migration", "runtime"]) : (var.operation == "migrate" ? toset(["migration", "runtime"]) : toset(["runtime"]))
  expected_secret_names = { admin = "enrollment-bootstrap-database-url", migration = "enrollment-migration-database-url", runtime = "enrollment-database-url" }
  tags                  = { product = "cosmabot", component = "enrollment-database-preparation", environment = "staging", clinical_data = "false" }
}
resource "terraform_data" "guard" {
  lifecycle {
    precondition {
      condition = (local.f.contract_version == "enrollment-foundation.v1" && local.f.environment == "staging" &&
        local.f.subscription_id == var.subscription_id && local.f.tenant_id == var.tenant_id &&
        can(regex("^rg-cosmabot-enrollment-staging-[a-z0-9]{6,8}$", local.f.resource_group_name)) &&
      local.f.postgres_database == "cosmabot_enrollment")
      error_message = "Use this independent staging foundation, never another product/database."
    }
    precondition {
      condition = (startswith(var.image, "${local.f.registry_server}/") && can(regex("@sha256:[0-9a-f]{64}$", var.image)) &&
        toset(keys(var.secret_references)) == local.names &&
      alltrue([for name, reference in var.secret_references : can(regex("^[0-9a-f]{32}$", trimprefix(reference, "${local.f.key_vault_uri}secrets/${local.expected_secret_names[name]}/")))]))
      error_message = "Use the exact owned image and selected versioned database secrets only."
    }
    precondition {
      condition = alltrue([for id in [local.f.container_app_environment_id, local.f.container_registry_id, local.f.key_vault_id] :
      startswith(lower(id), lower("/subscriptions/${var.subscription_id}/resourceGroups/${local.f.resource_group_name}/providers/"))])
      error_message = "All job resources must belong to the independent enrollment resource group."
    }
  }
}
resource "azurerm_user_assigned_identity" "database" {
  name                = "id-enrollment-db-${var.operation}"
  resource_group_name = local.f.resource_group_name
  location            = local.f.location
  tags                = local.tags
  depends_on          = [terraform_data.guard]
}
resource "azurerm_role_assignment" "pull" {
  scope                = local.f.container_registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.database.principal_id
}
resource "azurerm_role_assignment" "secret" {
  for_each             = local.names
  scope                = "${local.f.key_vault_id}/secrets/${local.expected_secret_names[each.value]}"
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.database.principal_id
}
resource "azurerm_container_app_job" "database" {
  count                        = var.create_job ? 1 : 0
  name                         = "job-enrollment-db-${var.operation}"
  resource_group_name          = local.f.resource_group_name
  location                     = local.f.location
  container_app_environment_id = local.f.container_app_environment_id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.database.id]
  }
  registry {
    server   = local.f.registry_server
    identity = azurerm_user_assigned_identity.database.id
  }
  dynamic "secret" {
    for_each = var.secret_references
    content {
      name                = secret.key
      identity            = azurerm_user_assigned_identity.database.id
      key_vault_secret_id = secret.value
    }
  }
  template {
    container {
      name    = "database"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "/app/enrollment_database_admin.py"]
      args    = [var.operation]
      env {
        name  = "ENROLLMENT_DATABASE_HOST"
        value = local.f.postgres_fqdn
      }
      dynamic "env" {
        for_each = var.secret_references
        content {
          name        = "ENROLLMENT_${upper(env.key)}_DATABASE_URL"
          secret_name = env.key
        }
      }
    }
  }
  tags       = local.tags
  depends_on = [terraform_data.guard, azurerm_role_assignment.pull, azurerm_role_assignment.secret]
}
output "manual_job" {
  value = { created = var.create_job, started = false, operation = var.operation, job_name = try(azurerm_container_app_job.database[0].name, null), qualified = false }
}
