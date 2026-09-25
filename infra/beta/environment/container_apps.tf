resource "azurerm_container_app_environment" "beta" {
  name                           = local.cae_name
  resource_group_name            = data.azurerm_resource_group.beta.name
  location                       = var.location
  infrastructure_subnet_id       = azurerm_subnet.container_apps.id
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.beta.id
  internal_load_balancer_enabled = false
  tags                           = local.tags
}

resource "azurerm_container_app" "api" {
  count = var.deploy_workloads && var.image_digest != null ? 1 : 0

  name                         = local.api_name
  resource_group_name          = data.azurerm_resource_group.beta.name
  container_app_environment_id = azurerm_container_app_environment.beta.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runtime.id]
  }

  registry {
    server   = azurerm_container_registry.beta.login_server
    identity = azurerm_user_assigned_identity.runtime.id
  }

  secret {
    name                = "database-url"
    identity            = azurerm_user_assigned_identity.runtime.id
    key_vault_secret_id = azurerm_key_vault_secret.database_url[0].versionless_id
  }

  secret {
    name                = "redis-url"
    identity            = azurerm_user_assigned_identity.runtime.id
    key_vault_secret_id = azurerm_key_vault_secret.redis_url[0].versionless_id
  }

  dynamic "secret" {
    for_each = local.is_authorized_beta ? {
      clinic-approval-reference   = azurerm_key_vault_secret.clinic_approval_reference[0].versionless_id
      baa-evidence-reference      = azurerm_key_vault_secret.baa_evidence_reference[0].versionless_id
      phi-authorization-reference = azurerm_key_vault_secret.phi_authorization_reference[0].versionless_id
    } : {}

    content {
      name                = secret.key
      identity            = azurerm_user_assigned_identity.runtime.id
      key_vault_secret_id = secret.value
    }
  }

  secret {
    name                = "human-deploy-evidence-reference"
    identity            = azurerm_user_assigned_identity.runtime.id
    key_vault_secret_id = azurerm_key_vault_secret.human_deploy_evidence_reference[0].versionless_id
  }

  dynamic "secret" {
    for_each = module.workspace_runtime.secret_definitions
    content {
      name                = secret.key
      identity            = azurerm_user_assigned_identity.runtime.id
      key_vault_secret_id = secret.value
    }
  }

  template {
    min_replicas = var.api_min_replicas
    max_replicas = var.api_max_replicas

    container {
      name   = "api"
      image  = local.image
      cpu    = var.api_cpu
      memory = var.api_memory

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
        initial_delay           = 5
        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 3
        success_count_threshold = 1
      }

      dynamic "env" {
        for_each = module.workspace_runtime.secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      dynamic "env" {
        for_each = local.workspace_runtime_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name  = "COSMAS_ENV"
        value = "early_adopter_beta"
      }

      env {
        name  = "DATA_MODE"
        value = local.runtime_data_mode
      }

      env {
        name  = "AUTH_MODE"
        value = "clerk_jwt"
      }

      env {
        name  = "CORS_ALLOWED_ORIGINS"
        value = join(",", local.workspace_client_origins)
      }

      env {
        name  = "SYNTH_SEED"
        value = "false"
      }

      env {
        name  = "BLOB_BACKEND"
        value = "azure"
      }

      env {
        name  = "BETA_BOX_ID"
        value = var.box_id
      }

      env {
        name  = "CLERK_ORGANIZATION_ID"
        value = var.clerk_org_id
      }

      env {
        name  = "CLERK_ISSUER"
        value = var.clerk_issuer_url
      }

      env {
        name  = "CLERK_JWKS_URL"
        value = var.clerk_jwks_url
      }

      env {
        name  = "CLERK_AUDIENCE"
        value = var.clerk_audience
      }

      env {
        name  = "CLERK_AUTHORIZED_PARTIES"
        value = join(",", local.workspace_client_origins)
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.runtime.client_id
      }

      dynamic "env" {
        for_each = local.is_authorized_beta ? {
          CLINIC_APPROVAL_REF   = "clinic-approval-reference"
          BAA_EVIDENCE_REF      = "baa-evidence-reference"
          PHI_AUTHORIZATION_REF = "phi-authorization-reference"
        } : {}

        content {
          name        = env.key
          secret_name = env.value
        }
      }

      env {
        name        = "HUMAN_DEPLOY_EVIDENCE_REF"
        secret_name = "human-deploy-evidence-reference"
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
        name  = "AZURE_STORAGE_ACCOUNT_URL"
        value = azurerm_storage_account.beta.primary_blob_endpoint
      }

      env {
        name  = "AZURE_BLOB_CONTAINER"
        value = azurerm_storage_container.artifacts[0].name
      }

      env {
        name  = "SYNC_WORKER"
        value = "false"
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

  depends_on = [
    terraform_data.workspace_profile_guard,
    azurerm_private_endpoint.acr,
    azurerm_private_endpoint.blob,
    azurerm_private_endpoint.key_vault,
    azurerm_private_endpoint.redis,
    azurerm_role_assignment.runtime_acr_pull,
    azurerm_role_assignment.runtime_blob[0],
    azurerm_role_assignment.runtime_key_vault_secrets,
  ]
}

resource "azurerm_container_app" "worker" {
  count = var.deploy_workloads && var.image_digest != null ? 1 : 0

  name                         = local.worker_name
  resource_group_name          = data.azurerm_resource_group.beta.name
  container_app_environment_id = azurerm_container_app_environment.beta.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runtime.id]
  }

  registry {
    server   = azurerm_container_registry.beta.login_server
    identity = azurerm_user_assigned_identity.runtime.id
  }

  secret {
    name                = "database-url"
    identity            = azurerm_user_assigned_identity.runtime.id
    key_vault_secret_id = azurerm_key_vault_secret.database_url[0].versionless_id
  }

  secret {
    name                = "redis-url"
    identity            = azurerm_user_assigned_identity.runtime.id
    key_vault_secret_id = azurerm_key_vault_secret.redis_url[0].versionless_id
  }

  dynamic "secret" {
    for_each = local.is_authorized_beta ? {
      clinic-approval-reference   = azurerm_key_vault_secret.clinic_approval_reference[0].versionless_id
      baa-evidence-reference      = azurerm_key_vault_secret.baa_evidence_reference[0].versionless_id
      phi-authorization-reference = azurerm_key_vault_secret.phi_authorization_reference[0].versionless_id
    } : {}

    content {
      name                = secret.key
      identity            = azurerm_user_assigned_identity.runtime.id
      key_vault_secret_id = secret.value
    }
  }

  secret {
    name                = "human-deploy-evidence-reference"
    identity            = azurerm_user_assigned_identity.runtime.id
    key_vault_secret_id = azurerm_key_vault_secret.human_deploy_evidence_reference[0].versionless_id
  }

  dynamic "secret" {
    for_each = module.workspace_runtime.secret_definitions
    content {
      name                = secret.key
      identity            = azurerm_user_assigned_identity.runtime.id
      key_vault_secret_id = secret.value
    }
  }

  template {
    min_replicas = var.worker_min_replicas
    max_replicas = var.worker_max_replicas

    container {
      name    = "worker"
      image   = local.image
      cpu     = var.worker_cpu
      memory  = var.worker_memory
      command = ["celery"]
      args = [
        "-A",
        "cosmas_os.worker.celery_app:celery_app",
        "worker",
        "--loglevel=INFO",
        "--concurrency=1",
      ]

      startup_probe {
        transport               = "HTTP"
        port                    = 8001
        path                    = "/ready"
        interval_seconds        = 5
        timeout                 = 5
        failure_count_threshold = 60
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8001
        path                    = "/ready"
        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 3
        success_count_threshold = 1
      }

      dynamic "env" {
        for_each = module.workspace_runtime.secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      dynamic "env" {
        for_each = local.workspace_runtime_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name  = "COSMAS_ENV"
        value = "early_adopter_beta"
      }

      env {
        name  = "DATA_MODE"
        value = local.runtime_data_mode
      }

      env {
        name  = "AUTH_MODE"
        value = "clerk_jwt"
      }

      env {
        name  = "CORS_ALLOWED_ORIGINS"
        value = join(",", local.workspace_client_origins)
      }

      env {
        name  = "SYNTH_SEED"
        value = "false"
      }

      env {
        name  = "BLOB_BACKEND"
        value = "azure"
      }

      env {
        name  = "BETA_BOX_ID"
        value = var.box_id
      }

      env {
        name  = "CLERK_ORGANIZATION_ID"
        value = var.clerk_org_id
      }

      env {
        name  = "CLERK_ISSUER"
        value = var.clerk_issuer_url
      }

      env {
        name  = "CLERK_JWKS_URL"
        value = var.clerk_jwks_url
      }

      env {
        name  = "CLERK_AUDIENCE"
        value = var.clerk_audience
      }

      env {
        name  = "CLERK_AUTHORIZED_PARTIES"
        value = join(",", local.workspace_client_origins)
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.runtime.client_id
      }

      dynamic "env" {
        for_each = local.is_authorized_beta ? {
          CLINIC_APPROVAL_REF   = "clinic-approval-reference"
          BAA_EVIDENCE_REF      = "baa-evidence-reference"
          PHI_AUTHORIZATION_REF = "phi-authorization-reference"
        } : {}

        content {
          name        = env.key
          secret_name = env.value
        }
      }

      env {
        name        = "HUMAN_DEPLOY_EVIDENCE_REF"
        secret_name = "human-deploy-evidence-reference"
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
        name  = "AZURE_STORAGE_ACCOUNT_URL"
        value = azurerm_storage_account.beta.primary_blob_endpoint
      }

      env {
        name  = "AZURE_BLOB_CONTAINER"
        value = azurerm_storage_container.artifacts[0].name
      }

      env {
        name  = "SYNC_WORKER"
        value = "false"
      }
    }
  }

  depends_on = [
    terraform_data.workspace_profile_guard,
    azurerm_private_endpoint.acr,
    azurerm_private_endpoint.blob,
    azurerm_private_endpoint.key_vault,
    azurerm_private_endpoint.redis,
    azurerm_role_assignment.runtime_acr_pull,
    azurerm_role_assignment.runtime_blob[0],
    azurerm_role_assignment.runtime_key_vault_secrets,
  ]
}
