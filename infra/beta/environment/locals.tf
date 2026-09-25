locals {
  name_token = substr(replace(lower(var.beta_id), "-", ""), 0, 12)

  is_authorized_beta  = var.deployment_mode == "authorized_beta"
  runtime_data_mode   = local.is_authorized_beta ? "authorized_beta" : "synthetic"
  data_classification = local.is_authorized_beta ? "phi-authorized" : "synthetic-only"
  registry_is_private = var.registry_network_posture == "private"

  resource_group_name       = "rg-cosmas-os-beta-${var.beta_id}"
  state_resource_group_name = "rg-cosmas-os-beta-state-${var.beta_id}"
  deploy_identity_name      = "id-cosmas-os-beta-deploy-${var.beta_id}"
  state_vnet_name           = "vnet-cosmas-os-beta-state-${var.beta_id}"

  expected_state_vnet_id                  = "/subscriptions/${var.subscription_id}/resourceGroups/${local.state_resource_group_name}/providers/Microsoft.Network/virtualNetworks/${local.state_vnet_name}"
  expected_state_blob_private_dns_zone_id = "/subscriptions/${var.subscription_id}/resourceGroups/${local.state_resource_group_name}/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"

  acr_name = substr(
    "cosmasbetaacr${local.name_token}${random_string.suffix.result}",
    0,
    50,
  )
  # Reserve all six random characters inside globally unique service-name limits.
  storage_name   = "cmbetast${local.name_token}${random_string.suffix.result}"
  key_vault_name = "kvcosmas${local.name_token}${random_string.suffix.result}"

  postgres_name               = "pg-cosmas-beta-${var.beta_id}-${random_string.suffix.result}"
  redis_name                  = "redis-cosmas-beta-${var.beta_id}-${random_string.suffix.result}"
  law_name                    = "law-cosmas-beta-${var.beta_id}"
  action_group_name           = "ag-cosmas-beta-${var.beta_id}"
  api_health_alert_name       = "alert-cosmas-beta-api-unavailable-${var.beta_id}"
  worker_health_alert_name    = "alert-cosmas-beta-worker-unavailable-${var.beta_id}"
  vnet_name                   = "vnet-cosmas-beta-${var.beta_id}"
  cae_name                    = "cae-cosmas-beta-${var.beta_id}"
  web_name                    = "ca-web-cosmas-beta-${var.beta_id}"
  api_name                    = "ca-api-cosmas-beta-${var.beta_id}"
  worker_name                 = "ca-worker-cosmas-beta-${var.beta_id}"
  database_job_name           = "caj-dbprep-cosmas-beta-${var.beta_id}"
  runtime_acceptance_job_name = "caj-runtime-accept-${var.beta_id}"
  web_identity_name           = "id-cosmas-beta-web-${var.beta_id}"
  runtime_identity_name       = "id-cosmas-beta-runtime-${var.beta_id}"
  database_identity_name      = "id-cosmas-beta-dbprep-${var.beta_id}"

  expected_database_server_id = "/subscriptions/${var.subscription_id}/resourceGroups/${local.resource_group_name}/providers/Microsoft.DBforPostgreSQL/flexibleServers/${local.postgres_name}"
  expected_database_job_id    = "/subscriptions/${var.subscription_id}/resourceGroups/${local.resource_group_name}/providers/Microsoft.App/jobs/${local.database_job_name}"

  image                      = var.image_digest == null ? null : "${azurerm_container_registry.beta.login_server}/cosmas-os@sha256:${var.image_digest}"
  database_preparation_image = var.database_preparation_image_digest == null ? null : "${azurerm_container_registry.beta.login_server}/cosmas-os@sha256:${var.database_preparation_image_digest}"
  web_image                  = var.web_image_digest == null ? null : "${azurerm_container_registry.beta.login_server}/cosmas-os-web@sha256:${var.web_image_digest}"

  database_admin_url = format(
    "postgresql+psycopg://%s:%s@%s:5432/cosmas_os?sslmode=verify-full&sslrootcert=system",
    urlencode(var.postgres_admin_login),
    replace(urlencode(var.postgres_admin_password), "+", "%20"),
    azurerm_postgresql_flexible_server.beta.fqdn,
  )

  api_origin       = "https://${local.api_name}.${azurerm_container_app_environment.beta.default_domain}"
  web_default_fqdn = "${local.web_name}.${azurerm_container_app_environment.beta.default_domain}"
  web_origin       = var.web_custom_domain == null ? "https://${local.web_default_fqdn}" : "https://${var.web_custom_domain}"

  redis_url = format(
    "rediss://:%s@%s:%d/0?ssl_cert_reqs=required",
    replace(urlencode(azurerm_managed_redis.beta.default_database[0].primary_access_key), "+", "%20"),
    azurerm_managed_redis.beta.hostname,
    azurerm_managed_redis.beta.default_database[0].port,
  )

  tags = {
    track               = "B"
    product             = "cosmas-os"
    env                 = "early_adopter_beta"
    deployment_mode     = var.deployment_mode
    data_classification = local.data_classification
    registry_posture    = var.registry_network_posture
    box_scope           = "dedicated"
    box_id              = var.box_id
    connectors          = "dark"
    managed             = "terraform"
  }
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "terraform_data" "prerequisite_guard" {
  input = {
    environment       = "early_adopter_beta"
    deployment_mode   = var.deployment_mode
    runtime_data_mode = local.runtime_data_mode
    evidence_digest = nonsensitive(sha256(join("|", [
      var.clinic_legal_name == null ? "" : var.clinic_legal_name,
      var.clerk_org_id == null ? "" : var.clerk_org_id,
      var.clinic_approval_reference == null ? "" : var.clinic_approval_reference,
      var.baa_evidence_reference == null ? "" : var.baa_evidence_reference,
      var.phi_authorization_reference == null ? "" : var.phi_authorization_reference,
      var.human_deploy_evidence_reference,
      var.runner_network_evidence_reference,
      var.runner_live_network_evidence_reference == null ? "" : var.runner_live_network_evidence_reference,
      var.region_evidence_reference,
      var.auth_boundary_evidence_reference,
      var.blob_adapter_evidence_reference,
      var.phi_logging_evidence_reference,
      var.backup_restore_evidence_reference,
      var.capability_manifest_reference,
      var.broker_service_evidence_reference,
      var.synthetic_public_registry_exception_reference == null ? "" : var.synthetic_public_registry_exception_reference,
      var.database_preparation_attestation == null ? "" : var.database_preparation_attestation.image_digest,
      var.database_preparation_attestation == null ? "" : var.database_preparation_attestation.schema_revision,
      var.database_preparation_attestation == null ? "" : var.database_preparation_attestation.evidence_sha256,
      var.database_preparation_attestation == null ? "" : var.database_preparation_attestation.execution_id,
      var.database_preparation_attestation == null ? "" : var.database_preparation_attestation.box_id,
      var.database_preparation_attestation == null ? "" : var.database_preparation_attestation.database_server_id,
      var.database_preparation_image_digest == null ? "" : var.database_preparation_image_digest,
      var.web_release_evidence_reference == null ? "" : var.web_release_evidence_reference,
      var.alert_contact_email == null ? "" : var.alert_contact_email,
    ])))
  }

  lifecycle {
    precondition {
      condition     = !local.is_authorized_beta || try(length(trimspace(var.clinic_legal_name)), 0) >= 3
      error_message = "authorized_beta requires a real named clinic/covered entity before any D3 Azure mutation."
    }
    precondition {
      condition     = !local.is_authorized_beta || try(length(trimspace(var.clinic_approval_reference)), 0) >= 3
      error_message = "authorized_beta requires a named-clinic approval reference before any D3 Azure mutation."
    }
    precondition {
      condition     = !local.is_authorized_beta || try(length(trimspace(var.baa_evidence_reference)), 0) >= 3
      error_message = "authorized_beta requires applicable Azure, Clerk, and enabled-service BAA evidence."
    }
    precondition {
      condition     = !local.is_authorized_beta || try(length(trimspace(var.phi_authorization_reference)), 0) >= 3
      error_message = "authorized_beta requires a separate human PHI authorization reference."
    }
    precondition {
      condition     = !local.is_authorized_beta || local.registry_is_private
      error_message = "authorized_beta requires registry_network_posture=private; a public-registry exception is synthetic-only."
    }
    precondition {
      condition = (
        (local.registry_is_private && var.synthetic_public_registry_exception_reference == null) ||
        (!local.registry_is_private && try(length(trimspace(var.synthetic_public_registry_exception_reference)), 0) >= 3)
      )
      error_message = "synthetic_public_registry_exception_reference must be null for private posture and is required for synthetic_public_exception."
    }
    precondition {
      condition     = length(trimspace(var.human_deploy_evidence_reference)) >= 3
      error_message = "Human deploy evidence is required before any production-like D3 plan or apply."
    }
    precondition {
      condition     = length(trimspace(var.runner_network_evidence_reference)) >= 3
      error_message = "The protected-runner private routing and DNS design must be reviewed before planning."
    }
    precondition {
      condition = !(
        var.enable_database_preparation_job || var.deploy_workloads
      ) || try(length(trimspace(var.runner_live_network_evidence_reference)), 0) >= 3
      error_message = "Database preparation and workloads require live evidence that the protected runner resolves and reaches the exact private workload endpoints."
    }
    precondition {
      condition     = length(trimspace(var.region_evidence_reference)) >= 3
      error_message = "Region, residency, quota, SKU, and calculator evidence is required."
    }
    precondition {
      condition     = length(trimspace(var.auth_boundary_evidence_reference)) >= 3
      error_message = "Clerk-to-Box/Principal authorization tests must pass before deployment."
    }
    precondition {
      condition     = length(trimspace(var.blob_adapter_evidence_reference)) >= 3
      error_message = "Managed-identity Azure Blob adapter tests must pass before deployment."
    }
    precondition {
      condition     = length(trimspace(var.phi_logging_evidence_reference)) >= 3
      error_message = "PHI-safe telemetry review evidence is required before deployment."
    }
    precondition {
      condition     = length(trimspace(var.backup_restore_evidence_reference)) >= 3
      error_message = "Backup, restore, purge, and retention evidence is required before deployment."
    }
    precondition {
      condition     = length(trimspace(var.capability_manifest_reference)) >= 3
      error_message = "A reviewed D3 capability manifest is required before deployment."
    }
    precondition {
      condition     = length(trimspace(var.broker_service_evidence_reference)) >= 3
      error_message = "The private Redis service and its cost/retirement posture must be reviewed before deployment."
    }
    precondition {
      condition = (
        lower(data.azurerm_client_config.current.subscription_id) == lower(var.subscription_id) &&
        lower(data.azurerm_client_config.current.tenant_id) == lower(var.tenant_id) &&
        lower(data.azurerm_client_config.current.client_id) == lower(data.azurerm_user_assigned_identity.deploy.client_id)
      )
      error_message = "Environment plans and applies require the exact dedicated D3 deploy identity in the approved subscription and tenant."
    }
    precondition {
      condition = alltrue([
        data.azurerm_resource_group.beta.tags["track"] == "B",
        data.azurerm_resource_group.beta.tags["product"] == "cosmas-os",
        data.azurerm_resource_group.beta.tags["env"] == "early_adopter_beta",
        data.azurerm_resource_group.beta.tags["deployment_mode"] == var.deployment_mode,
        data.azurerm_resource_group.beta.tags["data_classification"] == local.data_classification,
        data.azurerm_resource_group.beta.tags["box_id"] == var.box_id,
        data.azurerm_resource_group.state.tags["track"] == "B",
        data.azurerm_resource_group.state.tags["product"] == "cosmas-os",
        data.azurerm_resource_group.state.tags["env"] == "early_adopter_beta",
        data.azurerm_resource_group.state.tags["deployment_mode"] == var.deployment_mode,
        data.azurerm_resource_group.state.tags["data_classification"] == local.data_classification,
        data.azurerm_resource_group.state.tags["box_id"] == var.box_id,
      ])
      error_message = "Bootstrap state/workload resource-group tags must match this D3 Box, mode, and classification."
    }
    precondition {
      condition = (
        lower(var.state_vnet_id) == lower(local.expected_state_vnet_id) &&
        lower(var.state_blob_private_dns_zone_id) == lower(local.expected_state_blob_private_dns_zone_id)
      )
      error_message = "State VNet and Blob private DNS IDs must exactly match this subscription and D3 beta boundary."
    }
    precondition {
      condition = !var.deploy_workloads || (
        var.clerk_org_id != null &&
        var.clerk_issuer_url != null &&
        var.clerk_jwks_url != null &&
        var.clerk_audience != null
      )
      error_message = "deploy_workloads requires the production Clerk Organization, issuer, JWKS URL, and audience created for the foundation-derived web origin."
    }
    precondition {
      condition     = !var.deploy_workloads || var.image_digest != null
      error_message = "deploy_workloads requires an immutable image_digest already present in the dedicated ACR."
    }
    precondition {
      condition     = !var.enable_database_preparation_job || var.database_preparation_image_digest != null
      error_message = "enable_database_preparation_job requires the immutable reviewed database_preparation_image_digest."
    }
    precondition {
      condition     = !var.enable_database_preparation_job || var.runtime_database_url != null
      error_message = "enable_database_preparation_job requires the protected non-admin runtime_database_url."
    }
    precondition {
      condition     = !var.deploy_workloads || var.enable_database_preparation_job
      error_message = "deploy_workloads requires the manual database-preparation job to remain declared for repeatable forward-only migrations and verification."
    }
    precondition {
      condition     = !var.deploy_workloads || var.web_image_digest != null
      error_message = "deploy_workloads requires an immutable web_image_digest already present in the dedicated ACR."
    }
    precondition {
      condition     = !var.deploy_workloads || var.web_origin != null
      error_message = "deploy_workloads requires human approval of the exact D3 web_origin."
    }
    precondition {
      condition     = !var.deploy_workloads || var.web_custom_domain != null
      error_message = "deploy_workloads requires a dedicated web_custom_domain for production Clerk; DNS readiness remains separately gated."
    }
    precondition {
      condition     = !var.web_custom_domain_dns_ready || (var.web_custom_domain != null && var.deploy_workloads && var.web_image_digest != null)
      error_message = "web_custom_domain_dns_ready may be enabled only for a workload plan with a concrete web_custom_domain and web image."
    }
    precondition {
      condition     = !var.deploy_workloads || var.alert_contact_email != null
      error_message = "deploy_workloads requires one human-owned operational alert contact email."
    }
    precondition {
      condition     = !var.deploy_workloads || length(trimspace(var.web_release_evidence_reference == null ? "" : var.web_release_evidence_reference)) >= 3
      error_message = "deploy_workloads requires reviewed web release evidence tied to the web digest and derived API origin."
    }
    precondition {
      condition     = !var.deploy_workloads || var.runtime_database_url != null
      error_message = "deploy_workloads requires a verify-full runtime_database_url for a non-admin operational role."
    }
    precondition {
      condition     = !var.deploy_workloads || var.database_preparation_attestation != null
      error_message = "deploy_workloads requires the structured attestation from a completed manual database-preparation execution."
    }
    precondition {
      condition     = !var.deploy_workloads || local.database_preparation_matches_release
      error_message = "The database-preparation attestation must bind the exact Box, database server, job execution, workload image digest, and expected Alembic head."
    }
    precondition {
      condition     = startswith(local.resource_group_name, "rg-cosmas-os-beta-")
      error_message = "D3 resources must remain inside the dedicated beta naming boundary."
    }
  }
}

# Once an environment has entered authorized_beta, a normal plan cannot relabel
# it synthetic while retained data may still be PHI. Downgrade requires a
# separately reviewed decommission/reclassification procedure and code change.
resource "terraform_data" "authorized_beta_mode_lock" {
  count = local.is_authorized_beta ? 1 : 0

  input = {
    deployment_mode     = var.deployment_mode
    data_classification = local.data_classification
    runtime_data_mode   = local.runtime_data_mode
    box_id              = var.box_id
  }

  depends_on = [terraform_data.prerequisite_guard]

  lifecycle {
    prevent_destroy = true
  }
}
