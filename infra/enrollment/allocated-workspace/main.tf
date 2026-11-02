terraform {
  required_version = "= 1.12.5"
  required_providers {
    azurerm = { source = "registry.opentofu.org/hashicorp/azurerm", version = "= 4.81.0" }
  }
  backend "azurerm" { use_azuread_auth = true }
  encryption {
    key_provider "pbkdf2" "cohort" {
      passphrase = trimspace(file(var.encryption_key_file))
      iterations = 600000
    }
    method "aes_gcm" "cohort" { keys = key_provider.pbkdf2.cohort }
    state {
      method   = method.aes_gcm.cohort
      enforced = true
    }
    plan {
      method   = method.aes_gcm.cohort
      enforced = true
    }
  }
}
variable "deployment_file" { type = string }
variable "encryption_key_file" { type = string }
variable "postgres_admin_passwords" {
  type      = map(string)
  sensitive = true
  ephemeral = true
  validation {
    condition     = toset(keys(var.postgres_admin_passwords)) == toset(["box"]) && alltrue([for value in values(var.postgres_admin_passwords) : length(value) >= 32 && length(value) <= 128])
    error_message = "Supply the protected ephemeral bootstrap password for this one Box."
  }
}
locals {
  d                = jsondecode(file(var.deployment_file))
  account_audience = try(local.d.account.audience, "")
  f                = local.d.foundation
  practices        = { box = local.d.practice }
  names            = { for key in keys(local.practices) : key => "cbaw-${replace(local.d.practice.plan.practice_id, "-", "")}" }
  tags             = { product = "cosmabot", component = "enrollment-practice-runtime", environment = "staging", clinical_data = "false" }
  scope            = lower("/subscriptions/${local.f.subscription_id}/resourceGroups/${local.f.resource_group_name}/providers/")
  google           = try(local.d.google, null)
  google_keys      = ["GOOGLE_CONNECTION_CLIENT_SECRET", "GOOGLE_CONNECTION_ENCRYPTION_KEY"]
  google_ready     = local.google != null && alltrue([for name in local.google_keys : contains(keys(local.d.practice.secret_references), name)])
  secret_keys      = merge({ DATABASE_URL = "database-url", REDIS_URL = "redis-url", WORKSPACE_ENROLLMENT_ADMISSION_SECRET = "enrollment-admission-key", DATABASE_ADMIN_URL = "database-admin-url", OWNER_MANIFEST = "owner-manifest" }, local.google == null ? {} : { GOOGLE_CONNECTION_CLIENT_SECRET = "google-connection-client-secret", GOOGLE_CONNECTION_ENCRYPTION_KEY = "google-connection-encryption-key" })
  runtime_secrets  = { for key, p in local.practices : key => { for name, reference in p.secret_references : name => reference if contains(concat(["DATABASE_URL", "REDIS_URL", "WORKSPACE_ENROLLMENT_ADMISSION_SECRET"], local.google == null ? [] : local.google_keys), name) } }
}
provider "azurerm" {
  subscription_id                 = local.f.subscription_id
  tenant_id                       = local.f.tenant_id
  resource_provider_registrations = "none"
  storage_use_azuread             = true
  features {
    storage { data_plane_available = false }
    key_vault {
      purge_soft_delete_on_destroy = false
    }
    resource_group { prevent_deletion_if_contains_resources = true }
  }
}
resource "terraform_data" "guard" {
  lifecycle {
    precondition {
      condition = (local.d.contract_version == "cosmas-allocated-workspace.v1" && local.d.version == 1 && local.d.environment == "staging" && local.d.synthetic_only &&
        local.f.contract_version == "enrollment-foundation.v1" && local.f.environment == "staging" &&
        local.d.account.app_origin == "https://onboarding.staging.cosmas.ai" && local.d.account.api_origin == "https://enrollment-api.staging.cosmas.ai" &&
        can(regex("^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", local.d.practice.plan.practice_id)) &&
        local.d.practice.web_origin == "https://${local.d.practice.plan.practice_id}.staging.cosmas.ai" &&
        local.d.practice.plan.api_origin == "https://api.${local.d.practice.plan.practice_id}.staging.cosmas.ai" &&
      local.d.practice.plan.workspace_url == "${local.d.practice.web_origin}/chief")
      error_message = "Only one registered canonical UUID practice in dedicated synthetic staging is supported."
    }
    precondition {
      condition     = alltrue([for id in [local.f.vnet_id, local.f.container_app_environment_id, local.f.container_registry_id, local.f.postgres_subnet_id, local.f.private_endpoint_subnet_id, local.f.vault_private_dns_zone_id, local.f.blob_private_dns_zone_id, local.f.redis_private_dns_zone_id] : startswith(lower(id), local.scope)])
      error_message = "All networking, DNS and registry references must remain in the dedicated enrollment resource group."
    }
    precondition {
      condition = (local.d.expected_schema_revision == jsondecode(file("${path.module}/../../beta/environment/release-schema.json")).schema_revision &&
        local.d.practice.plan.source_commit == local.d.release.source_commit && local.d.practice.plan.image_sha256 == split("@sha256:", local.d.release.api_image)[1] &&
      alltrue([for image in [local.d.release.api_image, local.d.release.job_image] : startswith(image, "${local.f.registry_server}/") && can(regex("@sha256:[0-9a-f]{64}$", image))]))
      error_message = "The exact existing migration head and immutable source/API/preparation images are required."
    }
    precondition {
      condition = alltrue([for name, reference in local.d.practice.secret_references : contains(keys(local.secret_keys), name) &&
      can(regex("^https://kvca${substr(replace(local.d.practice.plan.practice_id, "-", ""), 0, 20)}[.]vault[.]azure[.]net/secrets/${lookup(local.secret_keys, name, "invalid")}/[0-9a-f]{32}$", reference))])
      error_message = "Only exact versioned secrets in this Box's own vault are permitted."
    }
    precondition {
      condition = (!local.d.deploy_workloads || (can(regex("^[0-9a-f]{64}$", local.d.practice.migration_receipt_sha256)) && can(regex("^[0-9a-f]{64}$", local.d.practice.reservation_receipt_sha256)) &&
      try(startswith(local.d.practice.web_image, "${local.f.registry_server}/"), false) && can(regex("@sha256:[0-9a-f]{64}$", local.d.practice.web_image))))
      error_message = "Workloads wait for actual migration/reservation receipts and measured per-practice web image."
    }
    precondition {
      condition = ((!(local.d.create_migration_jobs || local.d.create_owner_reservation_jobs || local.d.deploy_workloads) ||
        alltrue([for name in ["DATABASE_URL", "REDIS_URL", "WORKSPACE_ENROLLMENT_ADMISSION_SECRET"] : contains(keys(local.d.practice.secret_references), name)])) &&
        (!(local.d.create_migration_jobs || local.d.create_owner_reservation_jobs) || contains(keys(local.d.practice.secret_references), "DATABASE_ADMIN_URL")) &&
        (!local.d.create_owner_reservation_jobs || (contains(keys(local.d.practice.secret_references), "OWNER_MANIFEST") && can(regex("^[0-9a-f]{64}$", local.d.practice.migration_receipt_sha256)))) &&
      (!local.d.bind_domains || (local.d.deploy_workloads && local.d.practice.dns_ownership_qualified)))
      error_message = "Private jobs require scoped references; reservation waits for migration, domains for actual ownership."
    }
    precondition {
      condition = (local.d.practice.api_env.BETA_BOX_ID == local.d.practice.plan.box_id && local.d.practice.api_env.CLERK_ORGANIZATION_ID == local.d.practice.plan.organization_id &&
        local.d.practice.api_env.WORKSPACE_ENROLLMENT_PRACTICE_ID == local.d.practice.plan.practice_id && local.d.practice.api_env.COSMAS_ENV == "early_adopter_beta" &&
        local.d.practice.api_env.DATA_MODE == "synthetic" && local.d.practice.api_env.AUTH_MODE == "clerk_jwt" && local.d.practice.api_env.WORKSPACE_ENROLLMENT_MANAGED == "true" &&
        local.d.practice.api_env.CLERK_SESSION_POLICY == "enrollment_default" && local.d.practice.api_env.CLERK_ISSUER == local.d.account.issuer && local.d.practice.api_env.CLERK_AUDIENCE == local.account_audience &&
      alltrue([for name in keys(local.d.practice.api_env) : !strcontains(name, "CORE") && !strcontains(name, "SECRET") && !contains(["DATABASE_URL", "REDIS_URL"], name)]))
      error_message = "This runtime must preserve registered Clerk/Box authority with no Core or secret public settings."
    }
    precondition {
      condition = local.google == null ? alltrue([for name in keys(local.d.practice.api_env) : !startswith(name, "GOOGLE_") && !startswith(name, "WORKSPACE_GOOGLE_")]) : try(
        toset(keys(local.google)) == toset(["client_id", "callback_uri"]) &&
        can(regex("^[A-Za-z0-9_-]{1,200}[.]apps[.]googleusercontent[.]com$", local.google.client_id)) &&
        local.google.callback_uri == "${local.d.account.api_origin}/connections/google/callback" &&
        alltrue([for name in ["WORKSPACE_GOOGLE_CONNECTION_ENABLED", "WORKSPACE_GOOGLE_MESSAGE_ENABLED", "WORKSPACE_GOOGLE_CALENDAR_ENABLED", "GOOGLE_CONNECTION_BROKER_ENABLED"] : local.d.practice.api_env[name] == "true"]) &&
        local.d.practice.api_env.GOOGLE_CONNECTION_CLIENT_ID == local.google.client_id &&
        local.d.practice.api_env.GOOGLE_CONNECTION_CALLBACK_URI == local.google.callback_uri &&
        local.d.practice.api_env.GOOGLE_CONNECTION_BROKER_ORIGIN == local.d.account.api_origin &&
        local.d.practice.api_env.GOOGLE_CONNECTION_RETURN_ORIGIN == local.d.practice.web_origin &&
      (!local.d.deploy_workloads || local.google_ready), false)
      error_message = "Google requires an explicit exact account broker/client, both Box-only custody references and no default enablement."
    }
  }
}

# Reuse the existing beta feature/configuration contract without editing it.
module "workspace_runtime" {
  for_each                = local.practices
  source                  = "../../beta/environment/modules/workspace-runtime"
  hosted_enabled          = true
  features                = merge({ WORKSPACE_TEAM_SETUP_ENABLED = true, WORKSPACE_AI_ACTIVITY_ENABLED = true, WORKSPACE_ROUTINES_ENABLED = true, WORKSPACE_APPOINTMENTS_ENABLED = true }, local.google_ready ? { WORKSPACE_GOOGLE_CONNECTION_ENABLED = true, WORKSPACE_GOOGLE_MESSAGE_ENABLED = true, WORKSPACE_GOOGLE_CALENDAR_ENABLED = true } : {})
  public_configuration    = local.google_ready ? { GOOGLE_CONNECTION_CLIENT_ID = local.google.client_id } : {}
  secret_references       = local.google_ready ? { for name in local.google_keys : name => { secret_name = local.secret_keys[name], version = reverse(split("/", each.value.secret_references[name]))[0] } } : {}
  api_origin              = each.value.plan.api_origin
  web_origin              = each.value.web_origin
  key_vault_uri           = azurerm_key_vault.box[each.key].vault_uri
  core_identity_client_id = ""
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "cbaw-${local.d.practice.plan.practice_id}.postgres.database.azure.com"
  resource_group_name = local.f.resource_group_name
  tags                = local.tags
}
resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "link-cews-postgres-${local.d.namespace}"
  resource_group_name   = local.f.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = local.f.vnet_id
  registration_enabled  = false
}
resource "azurerm_postgresql_flexible_server" "box" {
  for_each                          = local.practices
  name                              = "psql-${local.names[each.key]}"
  resource_group_name               = local.f.resource_group_name
  location                          = local.f.location
  version                           = "16"
  sku_name                          = "B_Standard_B1ms"
  storage_mb                        = 32768
  auto_grow_enabled                 = true
  backup_retention_days             = 7
  geo_redundant_backup_enabled      = false
  public_network_access_enabled     = false
  delegated_subnet_id               = local.f.postgres_subnet_id
  private_dns_zone_id               = azurerm_private_dns_zone.postgres.id
  administrator_login               = "box_bootstrap"
  administrator_password_wo         = var.postgres_admin_passwords[each.key]
  administrator_password_wo_version = 1
  authentication {
    password_auth_enabled         = true
    active_directory_auth_enabled = false
  }
  tags       = merge(local.tags, { box = each.value.plan.box_id })
  depends_on = [terraform_data.guard, azurerm_private_dns_zone_virtual_network_link.postgres]
  lifecycle {
    prevent_destroy = true
    # Azure selects the creation zone; later deployment stages preserve it.
    ignore_changes = [zone]
  }
}
resource "azurerm_postgresql_flexible_server_configuration" "tls" {
  for_each  = local.practices
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.box[each.key].id
  value     = "on"
}
resource "azurerm_postgresql_flexible_server_database" "box" {
  for_each  = local.practices
  name      = "cosmas_os"
  server_id = azurerm_postgresql_flexible_server.box[each.key].id
  charset   = "UTF8"
  collation = "en_US.utf8"
  lifecycle { prevent_destroy = true }
}
resource "azurerm_key_vault" "box" {
  for_each                      = local.practices
  name                          = "kvca${substr(replace(local.d.practice.plan.practice_id, "-", ""), 0, 20)}"
  resource_group_name           = local.f.resource_group_name
  location                      = local.f.location
  tenant_id                     = local.f.tenant_id
  sku_name                      = "standard"
  soft_delete_retention_days    = 90
  purge_protection_enabled      = true
  rbac_authorization_enabled    = true
  public_network_access_enabled = false
  network_acls {
    bypass         = "None"
    default_action = "Deny"
  }
  tags       = merge(local.tags, { box = each.value.plan.box_id })
  depends_on = [terraform_data.guard]
  lifecycle { prevent_destroy = true }
}
resource "azurerm_storage_account" "box" {
  for_each                          = local.practices
  name                              = "stca${substr(replace(local.d.practice.plan.practice_id, "-", ""), 0, 20)}"
  resource_group_name               = local.f.resource_group_name
  location                          = local.f.location
  account_tier                      = "Standard"
  account_replication_type          = "LRS"
  min_tls_version                   = "TLS1_2"
  public_network_access_enabled     = false
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  infrastructure_encryption_enabled = true
  blob_properties {
    versioning_enabled = true
    delete_retention_policy { days = 7 }
    container_delete_retention_policy { days = 7 }
  }
  tags       = merge(local.tags, { box = each.value.plan.box_id })
  depends_on = [terraform_data.guard]
  lifecycle { prevent_destroy = true }
}
resource "azurerm_storage_container" "box" {
  for_each              = local.practices
  name                  = "box-artifacts"
  storage_account_id    = azurerm_storage_account.box[each.key].id
  container_access_type = "private"
  lifecycle { prevent_destroy = true }
}
resource "azurerm_storage_container" "receipts" {
  for_each              = local.practices
  name                  = "hosting-receipts"
  storage_account_id    = azurerm_storage_account.box[each.key].id
  container_access_type = "private"
  lifecycle { prevent_destroy = true }
}
resource "azurerm_managed_redis" "box" {
  for_each                  = local.practices
  name                      = "redis-${local.names[each.key]}"
  resource_group_name       = local.f.resource_group_name
  location                  = local.f.location
  sku_name                  = "Balanced_B0"
  high_availability_enabled = true
  public_network_access     = "Disabled"
  default_database {
    access_keys_authentication_enabled            = true
    client_protocol                               = "Encrypted"
    clustering_policy                             = "NoCluster"
    eviction_policy                               = "NoEviction"
    persistence_append_only_file_backup_frequency = "1s"
  }
  tags       = merge(local.tags, { box = each.value.plan.box_id })
  depends_on = [terraform_data.guard]
  lifecycle { prevent_destroy = true }
}
locals {
  private_services = merge({}, [for key in keys(local.practices) : {
    "${key}-vault" = { practice = key, id = azurerm_key_vault.box[key].id, group = "vault", zone = local.f.vault_private_dns_zone_id }
    "${key}-blob"  = { practice = key, id = azurerm_storage_account.box[key].id, group = "blob", zone = local.f.blob_private_dns_zone_id }
    "${key}-redis" = { practice = key, id = azurerm_managed_redis.box[key].id, group = "redisEnterprise", zone = local.f.redis_private_dns_zone_id }
  }]...)
}
# Service DNS zones are read-only dedicated foundation inputs; this Box owns only its endpoint records.
resource "azurerm_private_endpoint" "box" {
  for_each            = local.private_services
  name                = "pe-cews-${local.d.namespace}-${each.key}"
  resource_group_name = local.f.resource_group_name
  location            = local.f.location
  subnet_id           = local.f.private_endpoint_subnet_id
  private_service_connection {
    name                           = "psc-${each.key}"
    private_connection_resource_id = each.value.id
    subresource_names              = [each.value.group]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = each.key
    private_dns_zone_ids = [each.value.zone]
  }
  tags = local.tags
}

resource "azurerm_user_assigned_identity" "runtime" {
  for_each            = local.practices
  name                = "id-${local.names[each.key]}"
  resource_group_name = local.f.resource_group_name
  location            = local.f.location
  tags                = local.tags
  depends_on          = [terraform_data.guard]
}
resource "azurerm_user_assigned_identity" "web" {
  for_each            = local.practices
  name                = "id-web-${local.names[each.key]}"
  resource_group_name = local.f.resource_group_name
  location            = local.f.location
  tags                = local.tags
  depends_on          = [terraform_data.guard]
}
resource "azurerm_role_assignment" "runtime_pull" {
  for_each             = local.practices
  scope                = local.f.container_registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.runtime[each.key].principal_id
}
resource "azurerm_role_assignment" "web_pull" {
  for_each             = local.practices
  scope                = local.f.container_registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.web[each.key].principal_id
}
resource "azurerm_role_assignment" "runtime_blob" {
  for_each             = local.practices
  scope                = azurerm_storage_container.box[each.key].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.runtime[each.key].principal_id
}
locals {
  runtime_grants = merge({}, [for key, secrets in local.runtime_secrets : { for name, reference in secrets : "${key}-${name}" => { practice = key, name = local.secret_keys[name] } }]...)
  runtime_env = { for key, p in local.practices : key => merge(p.api_env, module.workspace_runtime[key].public_env, local.google_ready ? {
    # Only this reviewed callback differs from the shared module's Box API callback.
    GOOGLE_CONNECTION_CALLBACK_URI = local.google.callback_uri
    } : {}, {
    AZURE_CLIENT_ID           = azurerm_user_assigned_identity.runtime[key].client_id
    AZURE_STORAGE_ACCOUNT_URL = trimsuffix(azurerm_storage_account.box[key].primary_blob_endpoint, "/")
    AZURE_BLOB_CONTAINER      = azurerm_storage_container.box[key].name
  }) }
  workloads = local.d.deploy_workloads ? merge({}, [for key in keys(local.practices) : {
    "${key}-api"    = { practice = key, kind = "api" }
    "${key}-worker" = { practice = key, kind = "worker" }
  }]...) : {}
}
resource "azurerm_role_assignment" "runtime_secret" {
  for_each             = local.runtime_grants
  scope                = "${azurerm_key_vault.box[each.value.practice].id}/secrets/${each.value.name}"
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.runtime[each.value.practice].principal_id
}
resource "azurerm_container_app" "runtime" {
  for_each                     = local.workloads
  name                         = "${each.value.kind}-${local.names[each.value.practice]}"
  resource_group_name          = local.f.resource_group_name
  container_app_environment_id = local.f.container_app_environment_id
  workload_profile_name        = "Consumption"
  revision_mode                = "Single"
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runtime[each.value.practice].id]
  }
  registry {
    server   = local.f.registry_server
    identity = azurerm_user_assigned_identity.runtime[each.value.practice].id
  }
  dynamic "secret" {
    for_each = local.runtime_secrets[each.value.practice]
    content {
      name                = local.secret_keys[secret.key]
      identity            = azurerm_user_assigned_identity.runtime[each.value.practice].id
      key_vault_secret_id = secret.value
    }
  }
  template {
    min_replicas = 1
    max_replicas = 1
    container {
      name    = each.value.kind
      image   = local.d.release.api_image
      cpu     = 0.5
      memory  = "1Gi"
      command = each.value.kind == "api" ? ["uvicorn"] : ["celery"]
      args    = each.value.kind == "api" ? ["cosmas_os.api.app:app", "--host", "0.0.0.0", "--port", "8000"] : ["-A", "cosmas_os.worker.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=1"]
      dynamic "env" {
        for_each = local.runtime_env[each.value.practice]
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.runtime_secrets[each.value.practice]
        content {
          name        = env.key
          secret_name = local.secret_keys[env.key]
        }
      }
      startup_probe {
        transport               = "HTTP"
        port                    = each.value.kind == "api" ? 8000 : 8001
        path                    = each.value.kind == "api" ? "/health" : "/ready"
        interval_seconds        = 5
        timeout                 = 5
        failure_count_threshold = 60
      }
      readiness_probe {
        transport               = "HTTP"
        port                    = each.value.kind == "api" ? 8000 : 8001
        path                    = "/ready"
        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 3
        success_count_threshold = 1
      }
    }
  }
  dynamic "ingress" {
    for_each = each.value.kind == "api" ? [1] : []
    content {
      external_enabled           = true
      allow_insecure_connections = false
      target_port                = 8000
      traffic_weight {
        latest_revision = true
        percentage      = 100
      }
    }
  }
  tags       = local.tags
  depends_on = [terraform_data.guard, azurerm_role_assignment.runtime_secret, azurerm_role_assignment.runtime_pull, azurerm_role_assignment.runtime_blob, azurerm_private_endpoint.box]
}
resource "azurerm_container_app" "web" {
  for_each                     = local.d.deploy_workloads ? local.practices : {}
  name                         = "web-${local.names[each.key]}"
  resource_group_name          = local.f.resource_group_name
  container_app_environment_id = local.f.container_app_environment_id
  workload_profile_name        = "Consumption"
  revision_mode                = "Single"
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.web[each.key].id]
  }
  registry {
    server   = local.f.registry_server
    identity = azurerm_user_assigned_identity.web[each.key].id
  }
  template {
    min_replicas = 1
    max_replicas = 1
    container {
      name   = "web"
      image  = each.value.web_image
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
    }
  }
  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8080
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
  tags       = local.tags
  depends_on = [azurerm_role_assignment.web_pull]
}
locals {
  domains = local.d.bind_domains ? merge({}, [for key, p in local.practices : {
    "${key}-api" = { practice = key, name = trimprefix(p.plan.api_origin, "https://"), kind = "api" }
    "${key}-web" = { practice = key, name = trimprefix(p.web_origin, "https://"), kind = "web" }
  }]...) : {}
}
resource "azurerm_container_app_custom_domain" "box" {
  for_each         = local.domains
  name             = each.value.name
  container_app_id = each.value.kind == "api" ? azurerm_container_app.runtime["${each.value.practice}-api"].id : azurerm_container_app.web[each.value.practice].id
  lifecycle {
    ignore_changes = [certificate_binding_type, container_app_environment_certificate_id]
  }
}
output "workspace_resources" {
  value = { for key, p in local.practices : key => {
    practice_id        = p.plan.practice_id, box_id = p.plan.box_id, organization_id = p.plan.organization_id,
    postgres_server_id = azurerm_postgresql_flexible_server.box[key].id, postgres_fqdn = azurerm_postgresql_flexible_server.box[key].fqdn,
    key_vault_id       = azurerm_key_vault.box[key].id, key_vault_uri = azurerm_key_vault.box[key].vault_uri,
    redis_id           = azurerm_managed_redis.box[key].id, redis_hostname = azurerm_managed_redis.box[key].hostname,
    storage_id         = azurerm_storage_account.box[key].id, runtime_identity_id = azurerm_user_assigned_identity.runtime[key].id,
    api_fqdn           = try(azurerm_container_app.runtime["${key}-api"].ingress[0].fqdn, null), web_fqdn = try(azurerm_container_app.web[key].ingress[0].fqdn, null),
    deployed           = local.d.deploy_workloads, owner_ready = false, registry_workspace_ready = false
  } }
}
output "domain_verification" {
  description = "Protected app-specific asuid values; use only for the four selected practice hostnames."
  sensitive   = true
  value = { for key, p in local.practices : key => {
    api = try(azurerm_container_app.runtime["${key}-api"].custom_domain_verification_id, null),
    web = try(azurerm_container_app.web[key].custom_domain_verification_id, null)
  } }
}

resource "azurerm_role_assignment" "allocator_secrets" {
  scope                = azurerm_key_vault.box["box"].id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = local.d.allocator_object_id
}
resource "azurerm_role_assignment" "allocator_receipts" {
  scope                = azurerm_storage_container.receipts["box"].id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = local.d.allocator_object_id
}
