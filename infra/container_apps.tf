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

  registry {
    server   = azurerm_container_registry.synth.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  secret {
    name                = "database-url"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
  }

  secret {
    name                = "redis-url"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = azurerm_key_vault_secret.redis_url.versionless_id
  }

  template {
    min_replicas = 0
    # LocalBlobAdapter is per-replica ephemeral storage in D2 synth.
    max_replicas = 1

    container {
      name   = "api"
      image  = var.api_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "COSMAS_ENV"
        value = "synth_os"
      }

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }

      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }

      env {
        name  = "BLOB_ROOT"
        value = "/tmp/cosmas-os-blobs"
      }

      env {
        name  = "SYNC_WORKER"
        value = "false"
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

  depends_on = [
    azurerm_role_assignment.acr_pull,
    azurerm_role_assignment.kv_secrets_user_apps,
  ]
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

  registry {
    server   = azurerm_container_registry.synth.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  secret {
    name                = "database-url"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
  }

  secret {
    name                = "redis-url"
    identity            = azurerm_user_assigned_identity.apps.id
    key_vault_secret_id = azurerm_key_vault_secret.redis_url.versionless_id
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name    = "worker"
      image   = var.worker_image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["celery"]
      args = [
        "-A",
        "cosmas_os.worker.celery_app:celery_app",
        "worker",
        "--loglevel=INFO",
        "--concurrency=1",
      ]

      env {
        name  = "COSMAS_ENV"
        value = "synth_os"
      }

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }

      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }

      env {
        name  = "BLOB_ROOT"
        value = "/tmp/cosmas-os-blobs"
      }

      env {
        name  = "SYNC_WORKER"
        value = "false"
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.acr_pull,
    azurerm_role_assignment.kv_secrets_user_apps,
  ]
}
