locals {
  jobs = merge(
    local.d.create_migration_jobs ? { for key in keys(local.practices) : "${key}-migrate" => { practice = key, operation = "migrate" } } : {},
    local.d.create_owner_reservation_jobs ? { for key in keys(local.practices) : "${key}-reserve" => { practice = key, operation = "reserve" } } : {}
  )
  job_secrets = { for key, job in local.jobs : key => {
    for name, reference in local.practices[job.practice].secret_references : name => reference
    if job.operation == "reserve" || contains(["DATABASE_ADMIN_URL", "DATABASE_URL"], name)
  } }
  job_grants = merge({}, [for key, secrets in local.job_secrets : { for name, reference in secrets : "${key}-${name}" => { job = key, practice = local.jobs[key].practice, name = local.secret_keys[name] } }]...)
}
resource "azurerm_user_assigned_identity" "job" {
  for_each            = local.jobs
  name                = "id-job-${local.names[each.value.practice]}-${each.value.operation}"
  resource_group_name = local.f.resource_group_name
  location            = local.f.location
  tags                = local.tags
}
resource "azurerm_role_assignment" "job_pull" {
  for_each             = local.jobs
  scope                = local.f.container_registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.job[each.key].principal_id
}
resource "azurerm_role_assignment" "job_secret" {
  for_each             = local.job_grants
  scope                = "${azurerm_key_vault.box[each.value.practice].id}/secrets/${each.value.name}"
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.job[each.value.job].principal_id
}
resource "azurerm_container_app_job" "box" {
  for_each                     = local.jobs
  name                         = "job-${local.names[each.value.practice]}-${each.value.operation}"
  resource_group_name          = local.f.resource_group_name
  location                     = local.f.location
  container_app_environment_id = local.f.container_app_environment_id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 0
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.job[each.key].id]
  }
  registry {
    server   = local.f.registry_server
    identity = azurerm_user_assigned_identity.job[each.key].id
  }
  dynamic "secret" {
    for_each = local.job_secrets[each.key]
    content {
      name                = local.secret_keys[secret.key]
      identity            = azurerm_user_assigned_identity.job[each.key].id
      key_vault_secret_id = secret.value
    }
  }
  template {
    container {
      name    = "workspace-preparation"
      image   = local.d.release.job_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "/app/enrollment_workspace_job.py"]
      args    = [each.value.operation]
      dynamic "env" {
        for_each = merge(local.practices[each.value.practice].api_env, {
          AZURE_STORAGE_ACCOUNT_URL = trimsuffix(azurerm_storage_account.box[each.value.practice].primary_blob_endpoint, "/")
          AZURE_BLOB_CONTAINER      = azurerm_storage_container.box[each.value.practice].name
          AZURE_CLIENT_ID           = azurerm_user_assigned_identity.job[each.key].client_id
          EXPECTED_SCHEMA_REVISION  = local.d.expected_schema_revision
          RESERVED_OWNER_SUBJECT    = local.practices[each.value.practice].plan.owner_subject
          OWNER_MANIFEST_SHA256     = local.practices[each.value.practice].owner_manifest_sha256
          BOX_POSTGRES_HOST         = azurerm_postgresql_flexible_server.box[each.value.practice].fqdn
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.job_secrets[each.key]
        content {
          name        = env.key
          secret_name = local.secret_keys[env.key]
        }
      }
    }
  }
  tags       = local.tags
  depends_on = [terraform_data.guard, azurerm_role_assignment.job_pull, azurerm_role_assignment.job_secret, azurerm_private_endpoint.box, azurerm_postgresql_flexible_server_database.box]
}
output "manual_jobs" {
  value = { for key, job in azurerm_container_app_job.box : key => { name = job.name, started = false, owner_ready = false, workspace_ready = false } }
}
