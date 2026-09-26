resource "azurerm_container_app" "web" {
  count = var.deploy_workloads && var.web_image_digest != null ? 1 : 0

  name                         = local.web_name
  resource_group_name          = data.azurerm_resource_group.beta.name
  container_app_environment_id = azurerm_container_app_environment.beta.id
  revision_mode                = "Single"
  max_inactive_revisions       = 3
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.web.id]
  }

  registry {
    server   = azurerm_container_registry.beta.login_server
    identity = azurerm_user_assigned_identity.web.id
  }

  template {
    min_replicas = var.web_min_replicas
    max_replicas = var.web_max_replicas

    container {
      name   = "web"
      image  = local.web_image
      cpu    = var.web_cpu
      memory = var.web_memory

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
        initial_delay           = 2
        interval_seconds        = 10
        timeout                 = 2
        failure_count_threshold = 3
        success_count_threshold = 1
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/healthz"
        initial_delay           = 10
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

  lifecycle {
    precondition {
      condition     = var.web_origin == local.web_origin
      error_message = "web_origin must exactly match the HTTPS origin derived from the dedicated D3 Container App environment."
    }
  }

  depends_on = [azurerm_role_assignment.web_acr_pull]
}

resource "azurerm_container_app_custom_domain" "web" {
  count = var.deploy_workloads && var.web_image_digest != null && var.web_custom_domain != null && var.web_custom_domain_dns_ready ? 1 : 0

  name             = var.web_custom_domain
  container_app_id = azurerm_container_app.web[0].id

  lifecycle {
    # Azure fills these asynchronously for its managed certificate. AzureRM
    # requires both fields to be ignored to prevent replacement loops.
    ignore_changes = [
      certificate_binding_type,
      container_app_environment_certificate_id,
    ]
  }
}
