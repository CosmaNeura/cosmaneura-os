# This job has no schedule and Terraform never starts it. A named human creates
# it only after the foundation and digest push, then starts one manual execution
# and records the sanitized output plus Azure execution identity separately.
resource "azurerm_container_app_job" "database_preparation" {
  count = var.enable_database_preparation_job && var.database_preparation_image_digest != null && var.runtime_database_url != null ? 1 : 0

  name                         = local.database_job_name
  resource_group_name          = data.azurerm_resource_group.beta.name
  location                     = var.location
  container_app_environment_id = azurerm_container_app_environment.beta.id
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 0
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.database_preparation[0].id]
  }

  registry {
    server   = azurerm_container_registry.beta.login_server
    identity = azurerm_user_assigned_identity.database_preparation[0].id
  }

  secret {
    name  = "database-admin-url"
    value = local.database_admin_url
  }

  secret {
    name  = "database-runtime-url"
    value = var.runtime_database_url
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "database-preparation"
      image   = local.database_preparation_image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "cosmas_os.cli"]
      args    = ["prepare-beta-database", "--confirm-forward-only"]

      env {
        name  = "COSMAS_ENV"
        value = "early_adopter_beta"
      }

      env {
        name        = "DATABASE_ADMIN_URL"
        secret_name = "database-admin-url"
      }

      env {
        name        = "DATABASE_URL"
        secret_name = "database-runtime-url"
      }
    }
  }

  depends_on = [
    azurerm_private_endpoint.acr,
    azurerm_role_assignment.database_preparation_acr_pull,
    azurerm_postgresql_flexible_server_database.app,
  ]

  lifecycle {
    precondition {
      condition     = strcontains(var.runtime_database_url, "@${azurerm_postgresql_flexible_server.beta.fqdn}:5432/cosmas_os?sslmode=verify-full&sslrootcert=system")
      error_message = "The database preparation job runtime URL must target the dedicated private beta database with verify-full TLS using the system CA bundle."
    }
  }
}
