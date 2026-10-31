resource "azurerm_user_assigned_identity" "job" {
  count               = var.create_job ? 1 : 0
  name                = "id-clock-${var.operation}-${var.resource_name_suffix}"
  resource_group_name = local.f.resource_group_name
  location            = local.f.location
  tags                = local.tags
  depends_on          = [terraform_data.guard]
}
resource "azurerm_role_assignment" "pull" {
  count                = var.create_job ? 1 : 0
  scope                = local.f.container_registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.job[0].principal_id
}
resource "azurerm_role_assignment" "secret" {
  for_each             = var.create_job ? local.selected : toset([])
  scope                = "${local.f.key_vault_id}/secrets/${local.names[each.value]}"
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.job[0].principal_id
}
resource "azurerm_container_app_job" "clock" {
  count                        = var.create_job ? 1 : 0
  name                         = "job-clock-${var.operation}-${var.resource_name_suffix}"
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
    identity_ids = [azurerm_user_assigned_identity.job[0].id]
  }
  registry {
    server   = local.f.registry_server
    identity = azurerm_user_assigned_identity.job[0].id
  }
  dynamic "secret" {
    for_each = var.secret_references
    content {
      name                = secret.key
      identity            = azurerm_user_assigned_identity.job[0].id
      key_vault_secret_id = secret.value
    }
  }
  template {
    container {
      name    = "clock-journal"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "/app/private_clock_database.py"]
      args    = [var.operation]
      env {
        name  = "PRIVATE_CLOCK_DATABASE_HOST"
        value = azurerm_postgresql_flexible_server.clock.fqdn
      }
      dynamic "env" {
        for_each = var.binding_sha256
        content {
          name  = "PRIVATE_CLOCK_BINDING_${upper(env.key)}_SHA256"
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.secret_references
        content {
          name        = "PRIVATE_CLOCK_${upper(env.key)}"
          secret_name = env.key
        }
      }
    }
  }
  tags = local.tags
  depends_on = [terraform_data.guard, azurerm_role_assignment.pull, azurerm_role_assignment.secret,
  azurerm_postgresql_flexible_server_database.clock, azurerm_postgresql_flexible_server_configuration.tls]
}
