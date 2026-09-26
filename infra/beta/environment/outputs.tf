output "resource_group_name" {
  value = data.azurerm_resource_group.beta.name
}

output "location" {
  description = "Reviewed workload placement; existing bootstrap/state resource locations are unchanged."
  value       = var.location
}

output "api_max_replicas" {
  description = "Reviewed API replica cap used as an exact workload verification input."
  value       = var.api_max_replicas
}

output "environment" {
  value = "early_adopter_beta"
}

output "box_id" {
  description = "Exact dedicated logical Box UUID bound by bootstrap and the guarded deployment workflow."
  value       = var.box_id
}

output "state_vnet_id" {
  description = "Exact bootstrap state/protected-runner VNet peered to this environment."
  value       = var.state_vnet_id
}

output "state_blob_private_dns_zone_id" {
  description = "Exact bootstrap Blob private DNS zone shared by state and workload endpoints."
  value       = var.state_blob_private_dns_zone_id
}

output "workload_vnet_id" {
  description = "Exact workload VNet peered to the protected runner/state VNet."
  value       = azurerm_virtual_network.beta.id
}

output "private_endpoint_subnet_id" {
  description = "Exact subnet containing workload private endpoints."
  value       = azurerm_subnet.private_endpoints.id
}

output "postgres_subnet_id" {
  description = "Exact delegated subnet containing the PostgreSQL private address."
  value       = azurerm_subnet.postgres.id
}

output "postgres_private_dns_zone_id" {
  description = "Exact private DNS zone used by the D3 PostgreSQL server and protected recovery runner."
  value       = azurerm_private_dns_zone.postgres.id
}

output "deployment_mode" {
  value = var.deployment_mode
}

output "data_classification" {
  value = local.data_classification
}

output "runtime_data_mode" {
  value = local.runtime_data_mode
}

output "api_fqdn" {
  value = try(azurerm_container_app.api[0].ingress[0].fqdn, null)
}

output "api_origin" {
  description = "Exact public HTTPS API origin compiled into the reviewed beta web image. Available after the foundation creates the Container Apps environment."
  value       = local.api_origin
}

output "api_health_url" {
  value = try("https://${azurerm_container_app.api[0].ingress[0].fqdn}/health", null)
}

output "web_fqdn" {
  description = "Azure-generated default FQDN reported by the deployed web Container App; null before workloads."
  value       = try(azurerm_container_app.web[0].ingress[0].fqdn, null)
}

output "web_default_fqdn" {
  description = "Deterministic Azure-generated default FQDN used as the external DNS CNAME target, including before workloads are enabled."
  value       = local.web_default_fqdn
}

output "web_custom_domain_verification_id" {
  description = "Sensitive Container App verification value for the external asuid TXT record; null before the web app exists. This module does not manage public DNS."
  value       = try(azurerm_container_app.web[0].custom_domain_verification_id, null)
  sensitive   = true
}

output "web_custom_domain" {
  description = "Exact optional hostname selected for the web custom-domain binding."
  value       = var.web_custom_domain
}

output "web_custom_domain_binding_enabled" {
  description = "Whether the post-DNS managed-certificate custom-domain resource is declared."
  value       = length(azurerm_container_app_custom_domain.web) == 1
}

output "web_origin" {
  description = "Exact public HTTPS origin to approve in Clerk and resupply as web_origin; either the ACA default or the selected custom hostname."
  value       = local.web_origin
}

output "web_health_url" {
  value = length(azurerm_container_app.web) == 1 ? "${local.web_origin}/healthz" : null
}

output "image_reference" {
  value = local.image
}

output "web_image_reference" {
  value = local.web_image
}

output "workloads_enabled" {
  value = var.deploy_workloads
}

output "database_preparation_job_name" {
  description = "Manual, unscheduled database-preparation job name; null in the secret-free foundation stage."
  value       = try(azurerm_container_app_job.database_preparation[0].name, null)
}

output "database_preparation_job_enabled" {
  value = var.enable_database_preparation_job
}

output "database_preparation_job_resource_id" {
  description = "Exact manual database-preparation job resource ID, or null before it is enabled."
  value       = try(azurerm_container_app_job.database_preparation[0].id, null)
}

output "database_preparation_image_reference" {
  description = "Exact immutable image used by the manual database-preparation job, or null before it is enabled."
  value       = try(local.database_preparation_image, null)
}

output "database_preparation_identity_resource_id" {
  description = "Exact one-purpose identity used by the manual database-preparation job, or null before it is enabled."
  value       = try(azurerm_user_assigned_identity.database_preparation[0].id, null)
}

output "runtime_acceptance_job_name" {
  description = "Manual, unscheduled synthetic runtime-identity acceptance job name; null before workloads or in authorized mode."
  value       = try(azurerm_container_app_job.runtime_acceptance[0].name, null)
}

output "runtime_acceptance_job_resource_id" {
  description = "Exact manual runtime-identity acceptance job resource ID; null before synthetic workloads."
  value       = try(azurerm_container_app_job.runtime_acceptance[0].id, null)
}

output "runtime_acceptance_job_enabled" {
  value = length(azurerm_container_app_job.runtime_acceptance) == 1
}

output "container_app_environment_resource_id" {
  description = "Exact private Container Apps environment that hosts the D3 workload and manual preparation job."
  value       = azurerm_container_app_environment.beta.id
}

output "log_analytics_workspace_customer_id" {
  description = "Workspace customer ID used by the protected runner to retrieve only the sanitized job evidence line."
  value       = azurerm_log_analytics_workspace.beta.workspace_id
}

output "workload_health_action_group_id" {
  description = "Exact Action Group used for PHI-safe workload-health notifications; null before workloads."
  value       = try(azurerm_monitor_action_group.workload_health[0].id, null)
}

output "api_unavailable_metric_alert_id" {
  description = "Exact API replica-count alert resource; null before workloads."
  value       = try(azurerm_monitor_metric_alert.api_unavailable[0].id, null)
}

output "worker_unavailable_metric_alert_id" {
  description = "Exact worker replica-count alert resource; null before workloads."
  value       = try(azurerm_monitor_metric_alert.worker_unavailable[0].id, null)
}

output "acr_login_server" {
  value = azurerm_container_registry.beta.login_server
}

output "acr_resource_id" {
  value = azurerm_container_registry.beta.id
}

output "acr_private_endpoint_id" {
  description = "Exact ACR private endpoint ID; null for the reviewed synthetic public exception."
  value       = try(azurerm_private_endpoint.acr[0].id, null)
}

output "registry_network_posture" {
  value = var.registry_network_posture
}

output "registry_sku" {
  value = azurerm_container_registry.beta.sku
}

output "registry_public_network_access_enabled" {
  value = azurerm_container_registry.beta.public_network_access_enabled
}

output "registry_public_exception_reference_sha256" {
  description = "Non-reversible hash of the reviewed synthetic-only public-registry exception; null for private registry posture."
  value = var.registry_network_posture == "synthetic_public_exception" ? try(
    nonsensitive(sha256(var.synthetic_public_registry_exception_reference)),
    null,
  ) : null
}

output "runtime_identity_client_id" {
  value = azurerm_user_assigned_identity.runtime.client_id
}

output "web_identity_client_id" {
  description = "Client ID of the static host identity, which is intentionally limited to ACR pull."
  value       = azurerm_user_assigned_identity.web.client_id
}

output "key_vault_uri" {
  value = azurerm_key_vault.beta.vault_uri
}

output "key_vault_resource_id" {
  value = azurerm_key_vault.beta.id
}

output "key_vault_private_endpoint_id" {
  value = azurerm_private_endpoint.key_vault.id
}

output "postgres_private_fqdn" {
  value = azurerm_postgresql_flexible_server.beta.fqdn
}

output "postgres_resource_id" {
  value = azurerm_postgresql_flexible_server.beta.id
}

output "redis_private_hostname" {
  value = azurerm_managed_redis.beta.hostname
}

output "redis_resource_id" {
  value = azurerm_managed_redis.beta.id
}

output "redis_private_endpoint_id" {
  value = azurerm_private_endpoint.redis.id
}

output "blob_account_url" {
  value = azurerm_storage_account.beta.primary_blob_endpoint
}

output "blob_storage_account_id" {
  value = azurerm_storage_account.beta.id
}

output "blob_private_endpoint_id" {
  value = azurerm_private_endpoint.blob.id
}

output "runtime_identity_resource_id" {
  value = azurerm_user_assigned_identity.runtime.id
}

output "clerk_issuer_url" {
  description = "Non-secret Clerk issuer bound to the deployed runtime; null before workloads."
  value       = var.clerk_issuer_url
}

output "clerk_jwks_url" {
  description = "Non-secret Clerk JWKS URL bound to the deployed runtime; null before workloads."
  value       = var.clerk_jwks_url
}

output "clerk_audience" {
  description = "Non-secret Clerk audience bound to the deployed runtime; null before workloads."
  value       = var.clerk_audience
}

output "clerk_organization_id" {
  description = "Clerk Organization identifier bound one-to-one with this Box; null before workloads."
  value       = var.clerk_org_id
  sensitive   = true
}

output "human_deploy_evidence_reference_sha256" {
  description = "Non-reversible binding to the human deployment evidence reference."
  value       = nonsensitive(sha256(var.human_deploy_evidence_reference))
}

output "blob_container_name" {
  value = try(azurerm_storage_container.artifacts[0].name, null)
}

output "human_test_requirements" {
  value = [
    "HTTPS-only static web health, security headers, and fail-closed client configuration",
    "static web identity has ACR pull only and no Key Vault or Blob role",
    "Clerk login and Clerk Org to Box/Principal mapping",
    "cross-Box and caller-supplied identity rejection",
    "database and Redis connectivity without public endpoints",
    "managed-identity blob write/read/purge",
    "audit replay and PHI-safe logs",
    "backup/restore and retention reconciliation",
    "digest rollback",
  ]
}
