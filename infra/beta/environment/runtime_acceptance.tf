# This job is intentionally manual and unscheduled. It runs only in the
# synthetic D3 beta after workloads exist, under the exact runtime UAMI and
# exact accepted API digest. The protected runner is the only supported start
# and evidence-retrieval path.
resource "azurerm_container_app_job" "runtime_acceptance" {
  count = var.deploy_workloads && !local.is_authorized_beta && var.image_digest != null ? 1 : 0

  name                         = local.runtime_acceptance_job_name
  resource_group_name          = data.azurerm_resource_group.beta.name
  location                     = var.location
  container_app_environment_id = azurerm_container_app_environment.beta.id
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 0
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

  secret {
    name                = "human-deploy-evidence-reference"
    identity            = azurerm_user_assigned_identity.runtime.id
    key_vault_secret_id = azurerm_key_vault_secret.human_deploy_evidence_reference[0].versionless_id
  }

  secret {
    name                = "acceptance-hmac-key"
    identity            = azurerm_user_assigned_identity.runtime.id
    key_vault_secret_id = azurerm_key_vault_secret.runtime_acceptance_hmac_key[0].versionless_id
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "runtime-acceptance"
      image   = local.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "cosmas_os.cli"]
      args    = ["verify-beta-runtime", "--confirm-synthetic-only", "--confirm-runtime-uami"]

      env {
        name  = "COSMAS_ENV"
        value = "early_adopter_beta"
      }

      env {
        name  = "DATA_MODE"
        value = "synthetic"
      }

      env {
        name  = "AUTH_MODE"
        value = "clerk_jwt"
      }

      env {
        name  = "CORS_ALLOWED_ORIGINS"
        value = local.web_origin
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
        value = local.web_origin
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.runtime.client_id
      }

      env {
        name  = "EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID"
        value = azurerm_user_assigned_identity.runtime.client_id
      }

      env {
        name        = "COSMAS_ACCEPTANCE_HMAC_KEY"
        secret_name = "acceptance-hmac-key"
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
    azurerm_private_endpoint.acr,
    azurerm_private_endpoint.blob,
    azurerm_private_endpoint.key_vault,
    azurerm_private_endpoint.redis,
    azurerm_role_assignment.runtime_acr_pull,
    azurerm_role_assignment.runtime_blob[0],
    azurerm_role_assignment.runtime_key_vault_secrets,
  ]
}
