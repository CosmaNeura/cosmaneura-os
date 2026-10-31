terraform {
  required_version = ">= 1.9.0"
  required_providers {
    azurerm = { source = "registry.opentofu.org/hashicorp/azurerm", version = "~> 4.81" }
  }
  backend "azurerm" { use_azuread_auth = true }
}

provider "azurerm" {
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
  features {
    key_vault { purge_soft_delete_on_destroy = false }
    resource_group { prevent_deletion_if_contains_resources = true }
  }
}

variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "environment" {
  type = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "Use a dedicated staging or production enrollment environment."
  }
}
variable "resource_group_name" {
  type = string
  validation {
    condition     = can(regex("^rg-cosmabot-enrollment-(staging|production)-[a-z0-9-]{3,32}$", var.resource_group_name))
    error_message = "Enrollment requires its own named resource group; do not reuse a clinical or Core group."
  }
}
variable "location" { type = string }
variable "container_app_environment_id" { type = string }
variable "container_registry_id" { type = string }
variable "registry_server" { type = string }
variable "key_vault_id" { type = string }
variable "key_vault_uri" { type = string }
variable "rendered_directory" {
  type        = string
  description = "Protected output from the matching infra/enrollment/render.mjs source. Contains secret references, never credential values."
}
variable "deploy_workload" {
  type        = bool
  default     = false
  description = "Keep false until the separate foundation, exact image and dedicated enrollment migration are qualified."
}
variable "database_preparation_qualified" {
  type        = bool
  default     = false
  description = "Actual separate database migration/role/isolation check completed. A rendered plan is not this evidence."
}

locals {
  public_env = jsondecode(file("${var.rendered_directory}/public-env.json"))
  secrets    = jsondecode(file("${var.rendered_directory}/secret-references.json"))
  contract   = jsondecode(file("${var.rendered_directory}/deployment-contract.json"))
  rg_scope   = lower("/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/")
  tags       = { product = "cosmabot", component = "customer-enrollment", environment = var.environment, clinical_data = "false" }
}

resource "terraform_data" "guard" {
  input = { source_commit = local.contract.source_commit, image = local.contract.image }
  lifecycle {
    precondition {
      condition     = local.contract.environment == var.environment && local.contract.rendered_only && !local.contract.deployed
      error_message = "Use the matching environment's reviewed rendered contract; rendering is not deployment evidence."
    }
    precondition {
      condition = alltrue([for id in [var.container_app_environment_id, var.container_registry_id, var.key_vault_id] :
      startswith(lower(id), local.rg_scope)])
      error_message = "Enrollment identity, registry, network and vault must remain in its independent resource group."
    }
    precondition {
      condition     = startswith(local.contract.image, "${var.registry_server}/") && can(regex("@sha256:[0-9a-f]{64}$", local.contract.image))
      error_message = "The exact enrollment image must be in the selected owned ACR."
    }
    precondition {
      condition = (can(regex("^https://[a-z0-9-]+[.]vault[.]azure[.]net/$", var.key_vault_uri)) &&
        endswith(lower(var.key_vault_id), "/vaults/${split(".", trimprefix(var.key_vault_uri, "https://"))[0]}") &&
      alltrue([for reference in values(local.secrets.secret_definitions) : startswith(reference, "${var.key_vault_uri}secrets/")]))
      error_message = "All versioned secrets must resolve in the selected dedicated enrollment vault."
    }
    precondition {
      condition     = !var.deploy_workload || var.database_preparation_qualified
      error_message = "Qualify the independent enrollment database/schema and non-admin runtime role before startup."
    }
    precondition {
      condition = (alltrue([for name in keys(local.public_env) : startswith(name, "ENROLLMENT_")]) &&
        alltrue([for name in keys(local.secrets.secret_env) : contains([
          "ENROLLMENT_DATABASE_URL", "ENROLLMENT_CLERK_SECRET_KEY", "ENROLLMENT_INVITATION_SECRET", "ENROLLMENT_STRIPE_SECRET_KEY", "ENROLLMENT_STRIPE_WEBHOOK_SECRET"
      ], name)]))
      error_message = "The enrollment runtime must not inherit clinical, Core or unrelated provider credentials."
    }
  }
}

resource "azurerm_user_assigned_identity" "enrollment" {
  depends_on          = [terraform_data.guard]
  name                = "id-cosmabot-enrollment-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = local.tags
}

resource "azurerm_role_assignment" "registry" {
  scope                = var.container_registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.enrollment.principal_id
}

resource "azurerm_role_assignment" "secrets" {
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.enrollment.principal_id
}

resource "azurerm_container_app" "enrollment" {
  count                        = var.deploy_workload ? 1 : 0
  name                         = "ca-cosmabot-enrollment-${var.environment}"
  resource_group_name          = var.resource_group_name
  container_app_environment_id = var.container_app_environment_id
  revision_mode                = "Single"
  max_inactive_revisions       = 3
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.enrollment.id]
  }
  registry {
    server   = var.registry_server
    identity = azurerm_user_assigned_identity.enrollment.id
  }
  dynamic "secret" {
    for_each = local.secrets.secret_definitions
    content {
      name                = secret.key
      identity            = azurerm_user_assigned_identity.enrollment.id
      key_vault_secret_id = secret.value
    }
  }
  template {
    min_replicas = 1
    max_replicas = 2
    container {
      name    = "enrollment"
      image   = local.contract.image
      cpu     = 0.5
      memory  = "1Gi"
      command = slice(local.contract.startup_command, 0, 1)
      args    = slice(local.contract.startup_command, 1, length(local.contract.startup_command))
      dynamic "env" {
        for_each = local.public_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secrets.secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      startup_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        interval_seconds        = 5
        timeout                 = 2
        failure_count_threshold = 30
      }
      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/ready"
        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 3
        success_count_threshold = 1
      }
    }
  }
  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8000
    transport                  = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
  depends_on = [terraform_data.guard, azurerm_role_assignment.registry, azurerm_role_assignment.secrets]
}

output "configuration_source" { value = local.contract.source_commit }
output "workload_created" { value = var.deploy_workload }
output "enrollment_fqdn" { value = try(azurerm_container_app.enrollment[0].ingress[0].fqdn, null) }
