resource "azurerm_container_app_environment" "synth" {
  name                       = local.cae_name
  resource_group_name        = azurerm_resource_group.synth.name
  location                   = azurerm_resource_group.synth.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.synth.id
  tags                       = local.tags
}

resource "azurerm_container_app" "api" {
  name                         = local.api_app_name
  resource_group_name          = azurerm_resource_group.synth.name
  container_app_environment_id = azurerm_container_app_environment.synth.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  template {
    min_replicas = 0
    max_replicas = 3

    container {
      name   = "api"
      image  = var.api_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "COSMAS_ENV"
        value = "synth_os"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

resource "azurerm_container_app" "worker" {
  name                         = local.worker_name
  resource_group_name          = azurerm_resource_group.synth.name
  container_app_environment_id = azurerm_container_app_environment.synth.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "worker"
      image  = var.worker_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "COSMAS_ENV"
        value = "synth_os"
      }
    }
  }
}
