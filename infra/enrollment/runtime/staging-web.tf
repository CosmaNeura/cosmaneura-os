# This slice owns only the new account/API hosts, never the existing beta host.
variable "deploy_staging_web" {
  type        = bool
  default     = false
  description = "Create the independently built account-only web app after the central API/database qualification."
}
variable "staging_web_image" {
  type        = string
  default     = null
  nullable    = true
  description = "Reviewed account-only Dockerfile.web image in the dedicated enrollment ACR, pinned by digest."
}
variable "bind_staging_custom_domains" {
  type        = bool
  default     = false
  description = "Request the second DNS/TLS stage. This flag is not DNS evidence: current exact records must pass verify-dns.py."
}

resource "terraform_data" "staging_web_guard" {
  input = { web_image = var.staging_web_image, source_commit = local.contract.source_commit }
  lifecycle {
    precondition {
      condition = !var.deploy_staging_web || (var.environment == "staging" && var.deploy_workload &&
        local.contract.application_origin == "https://onboarding.staging.cosmas.ai" &&
        local.contract.enrollment_api_origin == "https://enrollment-api.staging.cosmas.ai" &&
        startswith(coalesce(var.staging_web_image, "unset"), "${var.registry_server}/") &&
      can(regex("@sha256:[0-9a-f]{64}$", coalesce(var.staging_web_image, "unset"))))
      error_message = "The central web requires the exact separate staging account/API pair, qualified API and dedicated immutable account image."
    }
    precondition {
      condition     = !var.bind_staging_custom_domains || (var.deploy_staging_web && var.deploy_workload && var.environment == "staging")
      error_message = "Create both isolated staging apps before requesting their owned custom-domain bindings."
    }
  }
}

resource "azurerm_user_assigned_identity" "staging_web" {
  count               = var.deploy_staging_web ? 1 : 0
  depends_on          = [terraform_data.guard, terraform_data.staging_web_guard]
  name                = "id-cosmabot-enrollment-web-staging"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = local.tags
}
resource "azurerm_role_assignment" "staging_web_registry" {
  count                = var.deploy_staging_web ? 1 : 0
  scope                = var.container_registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.staging_web[0].principal_id
}
resource "azurerm_container_app" "staging_web" {
  count                        = var.deploy_staging_web ? 1 : 0
  name                         = "ca-cosmabot-enroll-web-staging"
  resource_group_name          = var.resource_group_name
  container_app_environment_id = var.container_app_environment_id
  revision_mode                = "Single"
  max_inactive_revisions       = 3
  tags                         = local.tags
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.staging_web[0].id]
  }
  registry {
    server   = var.registry_server
    identity = azurerm_user_assigned_identity.staging_web[0].id
  }
  template {
    min_replicas = 1
    max_replicas = 2
    container {
      name   = "account-web"
      image  = var.staging_web_image
      cpu    = 0.25
      memory = "0.5Gi"
      startup_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/healthz"
        interval_seconds        = 5
        timeout                 = 2
        failure_count_threshold = 30
      }
      readiness_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/healthz"
        interval_seconds        = 10
        timeout                 = 2
        failure_count_threshold = 3
        success_count_threshold = 1
      }
      liveness_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/healthz"
        interval_seconds        = 30
        timeout                 = 2
        failure_count_threshold = 3
      }
    }
  }
  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8080
    transport                  = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
  depends_on = [terraform_data.staging_web_guard, azurerm_role_assignment.staging_web_registry]
}

locals {
  staging_account_routes = {
    account = {
      hostname         = "onboarding.staging.cosmas.ai"
      container_app_id = try(azurerm_container_app.staging_web[0].id, "")
      fqdn             = try(azurerm_container_app.staging_web[0].ingress[0].fqdn, "")
      verification_id  = try(azurerm_container_app.staging_web[0].custom_domain_verification_id, "")
    }
    api = {
      hostname         = "enrollment-api.staging.cosmas.ai"
      container_app_id = try(azurerm_container_app.enrollment[0].id, "")
      fqdn             = try(azurerm_container_app.enrollment[0].ingress[0].fqdn, "")
      verification_id  = try(azurerm_container_app.enrollment[0].custom_domain_verification_id, "")
    }
  }
}

# Refreshed during the domain plan/apply; a manifest or operator Boolean cannot
# substitute for the exact current public CNAME and asuid ownership records.
data "external" "staging_dns" {
  for_each = var.bind_staging_custom_domains ? local.staging_account_routes : {}
  program  = ["python3", "${path.module}/verify-dns.py"]
  query = {
    hostname        = each.value.hostname
    cname_target    = each.value.fqdn
    verification_id = each.value.verification_id
  }
  depends_on = [terraform_data.staging_web_guard]
}
resource "azurerm_container_app_custom_domain" "staging" {
  for_each         = var.bind_staging_custom_domains ? local.staging_account_routes : {}
  name             = each.value.hostname
  container_app_id = each.value.container_app_id
  lifecycle {
    precondition {
      condition     = data.external.staging_dns[each.key].result.verified == "true"
      error_message = "Both public resolvers must report the exact owned CNAME and asuid TXT before Azure creates and binds the managed certificate."
    }
    # AzureRM 4.81/Azure generate these asynchronously, matching the existing
    # beta web convention. Do not replace the app to chase certificate IDs.
    ignore_changes = [certificate_binding_type, container_app_environment_certificate_id]
  }
}

output "staging_account_dns_records" {
  description = "Exact public DNS publication records from the created apps; protected output includes only the public ownership TXT tokens, not credentials. Empty until both apps exist. Public DNS is not mutated."
  sensitive   = true
  value = var.deploy_staging_web && var.deploy_workload ? {
    for name, route in local.staging_account_routes : name => {
      hostname         = route.hostname
      container_app_id = route.container_app_id
      cname            = { type = "CNAME", name = route.hostname, value = route.fqdn }
      txt              = { type = "TXT", name = "asuid.${route.hostname}", value = route.verification_id }
    }
  } : {}
}
output "staging_account_web_fqdn" { value = try(azurerm_container_app.staging_web[0].ingress[0].fqdn, null) }
output "staging_account_domains_requested" { value = var.bind_staging_custom_domains }
output "staging_account_dns_checks" {
  value = { for name, check in data.external.staging_dns : name => check.result }
}
