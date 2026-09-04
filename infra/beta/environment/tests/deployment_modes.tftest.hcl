mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      object_id       = "00000000-0000-4000-8000-000000000003"
      client_id       = "00000000-0000-4000-8000-000000000005"
      subscription_id = "00000000-0000-4000-8000-000000000001"
      tenant_id       = "00000000-0000-4000-8000-000000000002"
    }
  }

  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01"
      location = "centralus"
      tags = {
        track               = "B"
        product             = "cosmas-os"
        env                 = "early_adopter_beta"
        deployment_mode     = "synthetic_lab"
        data_classification = "synthetic-only"
        box_scope           = "dedicated"
        box_id              = "00000000-0000-4000-8000-000000000004"
        connectors          = "dark"
        managed             = "terraform"
      }
    }
  }

  mock_data "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-cosmas-os-beta-deploy-lab01"
      client_id    = "00000000-0000-4000-8000-000000000005"
      principal_id = "00000000-0000-4000-8000-000000000006"
    }
  }

  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-cosmas-beta-runtime-lab01"
      client_id    = "00000000-0000-4000-8000-000000000007"
      principal_id = "00000000-0000-4000-8000-000000000008"
    }
  }

  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.ContainerRegistry/registries/cosmasbetaacrlab01abc123"
      login_server = "cosmasbetaacrlab01abc123.azurecr.io"
    }
  }

  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.KeyVault/vaults/kvcosmaslab01abc123"
      vault_uri = "https://kvcosmaslab01abc123.vault.azure.net/"
    }
  }

  mock_resource "azurerm_key_vault_secret" {
    defaults = {
      id             = "https://kvcosmaslab01abc123.vault.azure.net/secrets/synthetic/00000000000000000000000000000000"
      versionless_id = "https://kvcosmaslab01abc123.vault.azure.net/secrets/synthetic"
    }
  }

  mock_resource "azurerm_postgresql_flexible_server" {
    defaults = {
      id   = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
      fqdn = "pg-cosmas-beta-lab01-abc123.postgres.database.azure.com"
    }
  }

  mock_resource "azurerm_managed_redis" {
    defaults = {
      id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.Cache/redisEnterprise/redis-cosmas-beta-lab01-abc123"
      hostname = "redis-cosmas-beta-lab01-abc123.centralus.redis.azure.net"
      default_database = {
        id                   = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.Cache/redisEnterprise/redis-cosmas-beta-lab01-abc123/databases/default"
        port                 = 10000
        primary_access_key   = "synthetic-test-key"
        secondary_access_key = "synthetic-test-key-secondary"
      }
    }
  }

  mock_resource "azurerm_storage_account" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.Storage/storageAccounts/cmbetastlab01abc123"
      primary_blob_endpoint = "https://cmbetastlab01abc123.blob.core.windows.net/"
    }
  }

  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.Storage/storageAccounts/cmbetastlab01abc123/blobServices/default/containers/box-artifacts"
    }
  }

  mock_resource "azurerm_virtual_network" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-beta-lab01"
    }
  }

  mock_resource "azurerm_subnet" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-beta-lab01/subnets/snet-mocked"
    }
  }

  mock_resource "azurerm_private_dns_zone" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.Network/privateDnsZones/example.invalid"
    }
  }

  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.OperationalInsights/workspaces/law-cosmas-beta-lab01"
    }
  }

  mock_resource "azurerm_monitor_action_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.Insights/actionGroups/ag-cosmas-beta-lab01"
    }
  }

  mock_resource "azurerm_monitor_metric_alert" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.Insights/metricAlerts/alert-cosmas-beta-api-unavailable-lab01"
    }
  }

  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id             = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/managedEnvironments/cae-cosmas-beta-lab01"
      default_domain = "synthetic.centralus.azurecontainerapps.io"
    }
  }

  mock_resource "azurerm_container_app" {
    defaults = {
      id                            = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/containerApps/ca-cosmas-beta-mocked"
      custom_domain_verification_id = "synthetic-domain-verification-id"
    }
  }

  mock_resource "azurerm_container_app_custom_domain" {
    defaults = {
      id                                               = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/containerApps/ca-web-cosmas-beta-lab01/customDomainName/app.beta.cosmaneura.com"
      container_app_environment_managed_certificate_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/managedEnvironments/cae-cosmas-beta-lab01/managedCertificates/app-beta"
    }
  }

  mock_resource "azurerm_container_app_job" {
    defaults = {
      id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-mocked-cosmas-beta-lab01"
    }
  }
}

mock_provider "random" {
  mock_resource "random_string" {
    defaults = {
      result = "abc123"
    }
  }

  mock_resource "random_id" {
    defaults = {
      hex = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    }
  }
}

variables {
  subscription_id                   = "00000000-0000-4000-8000-000000000001"
  tenant_id                         = "00000000-0000-4000-8000-000000000002"
  beta_id                           = "lab01"
  state_vnet_id                     = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-lab01"
  state_blob_private_dns_zone_id    = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
  box_id                            = "00000000-0000-4000-8000-000000000004"
  registry_network_posture          = "private"
  clerk_org_id                      = "org_beta_lab_test"
  clerk_issuer_url                  = "https://clerk.example.invalid"
  clerk_jwks_url                    = "https://clerk.example.invalid/.well-known/jwks.json"
  clerk_audience                    = "cosmas-beta-lab"
  human_deploy_evidence_reference   = "deploy:test"
  runner_network_evidence_reference = "network:test"
  region_evidence_reference         = "region:test"
  auth_boundary_evidence_reference  = "auth:test"
  blob_adapter_evidence_reference   = "blob:test"
  phi_logging_evidence_reference    = "logging:test"
  backup_restore_evidence_reference = "recovery:test"
  capability_manifest_reference     = "manifest:test"
  broker_service_evidence_reference = "broker:test"
  postgres_admin_password           = "synthetic-test-password-1234"
  alert_contact_email               = "owner@example.invalid"
}

run "synthetic_lab_omits_clinic_baa_and_phi_evidence" {
  command = plan

  assert {
    condition = (
      output.deployment_mode == "synthetic_lab" &&
      output.data_classification == "synthetic-only" &&
      output.runtime_data_mode == "synthetic"
    )
    error_message = "Synthetic Lab must plan only with synthetic runtime data mode and classification."
  }

  assert {
    condition = (
      one(azurerm_storage_account.beta.blob_properties).versioning_enabled == false &&
      length(one(azurerm_storage_account.beta.blob_properties).delete_retention_policy) == 0 &&
      length(one(azurerm_storage_account.beta.blob_properties).container_delete_retention_policy) == 0
    )
    error_message = "The synthetic-only D3 artifact account must disable versioning and omit Blob/container soft-delete retention."
  }

  assert {
    condition = (
      length(azurerm_key_vault_secret.clinic_approval_reference) == 0 &&
      length(azurerm_key_vault_secret.baa_evidence_reference) == 0 &&
      length(azurerm_key_vault_secret.phi_authorization_reference) == 0
    )
    error_message = "Synthetic Lab must not create clinic, BAA, or PHI authorization evidence secrets."
  }

  assert {
    condition     = length(terraform_data.authorized_beta_mode_lock) == 0
    error_message = "Synthetic Lab must not claim an authorized-beta mode lock."
  }

  assert {
    condition = (
      length(azurerm_container_app_job.database_preparation) == 0 &&
      length(azurerm_container_app_job.runtime_acceptance) == 0 &&
      length(azurerm_user_assigned_identity.database_preparation) == 0 &&
      length(azurerm_key_vault_secret.database_url) == 0 &&
      length(azurerm_key_vault_secret.redis_url) == 0 &&
      length(azurerm_key_vault_secret.human_deploy_evidence_reference) == 0 &&
      length(azurerm_key_vault_secret.runtime_acceptance_hmac_key) == 0 &&
      length(random_id.runtime_acceptance_hmac_key) == 0 &&
      length(azurerm_storage_container.artifacts) == 0 &&
      length(azurerm_role_assignment.runtime_blob) == 0
    )
    error_message = "The foundation must not create the database job or perform private workload Key Vault/Blob data-plane writes."
  }

  assert {
    condition     = length(var.enabled_connectors) == 0 && local.tags.connectors == "dark"
    error_message = "All external connectors must remain dark in Synthetic Lab."
  }

  assert {
    condition = (
      output.web_origin == "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io" &&
      output.web_default_fqdn == "ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io" &&
      output.web_custom_domain_verification_id == null &&
      output.web_custom_domain == null &&
      output.web_custom_domain_binding_enabled == false &&
      output.api_origin == "https://ca-api-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io" &&
      length(azurerm_container_app.web) == 0
    )
    error_message = "The foundation must reserve exact D3-only HTTPS origins without deploying a frontend prematurely."
  }

  assert {
    condition = (
      output.registry_network_posture == "private" &&
      output.registry_sku == "Premium" &&
      output.registry_public_network_access_enabled == false &&
      azurerm_container_registry.beta.sku == "Premium" &&
      azurerm_container_registry.beta.network_rule_bypass_option == "None" &&
      length(azurerm_private_endpoint.acr) == 1 &&
      length(azurerm_private_dns_zone.acr) == 1 &&
      length(azurerm_private_dns_zone_virtual_network_link.acr) == 1
    )
    error_message = "Private registry posture must use Premium ACR, disable its public endpoint, and create Private Link DNS resources."
  }

  assert {
    condition = (
      azurerm_key_vault.beta.public_network_access_enabled == false &&
      azurerm_key_vault.beta.network_acls[0].default_action == "Deny" &&
      azurerm_key_vault.beta.network_acls[0].bypass == "None"
    )
    error_message = "The D3 Key Vault must deny public access and must not grant the broad Azure trusted-services firewall bypass."
  }

  assert {
    condition = (
      output.state_vnet_id == var.state_vnet_id &&
      output.state_blob_private_dns_zone_id == var.state_blob_private_dns_zone_id &&
      output.postgres_private_dns_zone_id == azurerm_private_dns_zone.postgres.id &&
      azurerm_virtual_network_peering.beta_to_state.remote_virtual_network_id == var.state_vnet_id &&
      azurerm_virtual_network_peering.state_to_beta.virtual_network_name == "vnet-cosmas-os-beta-state-lab01" &&
      azurerm_virtual_network_peering.state_to_beta.remote_virtual_network_id == azurerm_virtual_network.beta.id &&
      azurerm_private_dns_zone_virtual_network_link.state_blob_to_beta.private_dns_zone_name == "privatelink.blob.core.windows.net" &&
      azurerm_private_dns_zone_virtual_network_link.postgres_to_runner.virtual_network_id == var.state_vnet_id &&
      azurerm_private_dns_zone_virtual_network_link.key_vault_to_runner.virtual_network_id == var.state_vnet_id &&
      azurerm_private_dns_zone_virtual_network_link.redis_to_runner.virtual_network_id == var.state_vnet_id &&
      length(azurerm_private_dns_zone_virtual_network_link.acr_to_runner) == 1 &&
      azurerm_private_endpoint.blob.private_dns_zone_group[0].private_dns_zone_ids[0] == var.state_blob_private_dns_zone_id
    )
    error_message = "The environment must peer bidirectionally with the protected runner and expose only its private data endpoints through the exact bootstrap DNS/VNet boundary."
  }

  assert {
    condition = (
      azurerm_managed_redis.beta.sku_name == "Balanced_B0" &&
      azurerm_managed_redis.beta.high_availability_enabled == true &&
      azurerm_managed_redis.beta.public_network_access == "Disabled" &&
      azurerm_managed_redis.beta.default_database[0].access_keys_authentication_enabled == true &&
      azurerm_managed_redis.beta.default_database[0].client_protocol == "Encrypted" &&
      azurerm_managed_redis.beta.default_database[0].clustering_policy == "NoCluster" &&
      azurerm_managed_redis.beta.default_database[0].eviction_policy == "NoEviction" &&
      azurerm_managed_redis.beta.default_database[0].persistence_append_only_file_backup_frequency == "1s" &&
      length(azurerm_private_endpoint.redis.private_service_connection[0].subresource_names) == 1 &&
      one(azurerm_private_endpoint.redis.private_service_connection[0].subresource_names) == "redisEnterprise" &&
      azurerm_private_dns_zone.redis.name == "privatelink.redis.azure.net" &&
      output.redis_private_hostname == "redis-cosmas-beta-lab01-abc123.centralus.redis.azure.net"
    )
    error_message = "D3 must use the reviewed private, TLS-only, HA/persistent Azure Managed Redis B0 broker configuration."
  }
}

run "rejects_mismatched_bootstrap_state_network" {
  command = plan

  variables {
    state_vnet_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-other/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-other"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "foundation_accepts_pending_production_clerk" {
  command = plan

  variables {
    clerk_org_id     = null
    clerk_issuer_url = null
    clerk_jwks_url   = null
    clerk_audience   = null
  }

  assert {
    condition     = length(azurerm_container_app.api) == 0 && length(azurerm_container_app.worker) == 0 && length(azurerm_container_app.web) == 0
    error_message = "A foundation plan may reserve its exact origins before production Clerk exists, but it must not create workloads."
  }
}

run "database_preparation_is_manual_digest_pinned_and_isolated" {
  command = plan

  variables {
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:database-preparation:test"
  }

  assert {
    condition = (
      length(azurerm_container_app_job.database_preparation) == 1 &&
      azurerm_container_app_job.database_preparation[0].template[0].container[0].image == "cosmasbetaacrlab01abc123.azurecr.io/cosmas-os@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" &&
      azurerm_container_app_job.database_preparation[0].template[0].container[0].command == tolist(["python", "-m", "cosmas_os.cli"]) &&
      azurerm_container_app_job.database_preparation[0].template[0].container[0].args[0] == "prepare-beta-database" &&
      azurerm_container_app_job.database_preparation[0].template[0].container[0].args[1] == "--confirm-forward-only" &&
      azurerm_container_app_job.database_preparation[0].manual_trigger_config[0].parallelism == 1 &&
      azurerm_container_app_job.database_preparation[0].manual_trigger_config[0].replica_completion_count == 1 &&
      azurerm_container_app_job.database_preparation[0].replica_retry_limit == 0
    )
    error_message = "Database preparation must be one digest-pinned, no-retry manual job with no event or schedule trigger."
  }

  assert {
    condition = (
      length(azurerm_user_assigned_identity.database_preparation) == 1 &&
      length(azurerm_role_assignment.database_preparation_acr_pull) == 1 &&
      azurerm_container_app_job.database_preparation[0].registry[0].identity == azurerm_user_assigned_identity.database_preparation[0].id &&
      length(azurerm_key_vault_secret.database_url) == 0 &&
      length(azurerm_key_vault_secret.redis_url) == 0 &&
      length(azurerm_key_vault_secret.human_deploy_evidence_reference) == 0
    )
    error_message = "The database job identity must have only ACR pull and the preparation stage must not write runtime workload secrets to Key Vault."
  }
}

run "database_preparation_rejects_missing_digest" {
  command = plan

  variables {
    enable_database_preparation_job        = true
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:database-preparation:test"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "database_preparation_rejects_missing_live_runner_evidence" {
  command = plan

  variables {
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = null
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "workloads_reject_skipped_database_preparation" {
  command = plan

  variables {
    deploy_workloads                       = true
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_origin                             = "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io"
    web_release_evidence_reference         = "web-release:test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:workloads:test"
    database_preparation_attestation = {
      image_digest       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-test"
      box_id             = "00000000-0000-4000-8000-000000000004"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "workloads_reject_missing_database_preparation_attestation" {
  command = plan

  variables {
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_origin                             = "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io"
    web_release_evidence_reference         = "web-release:test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:workloads:test"
    database_preparation_attestation       = null
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "workloads_reject_attestation_for_different_image" {
  command = plan

  variables {
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_origin                             = "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io"
    web_release_evidence_reference         = "web-release:test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:workloads:test"
    database_preparation_attestation = {
      image_digest       = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-test"
      box_id             = "00000000-0000-4000-8000-000000000004"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "workloads_reject_attestation_for_different_box" {
  command = plan

  variables {
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_origin                             = "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io"
    web_release_evidence_reference         = "web-release:test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:workloads:test"
    database_preparation_attestation = {
      image_digest       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-test"
      box_id             = "00000000-0000-4000-8000-000000000099"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "workloads_reject_pending_production_clerk" {
  command = plan

  variables {
    clerk_org_id                           = null
    clerk_issuer_url                       = null
    clerk_jwks_url                         = null
    clerk_audience                         = null
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_origin                             = "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io"
    web_release_evidence_reference         = "web-release:test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:workloads:test"
    database_preparation_attestation = {
      image_digest       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-test"
      box_id             = "00000000-0000-4000-8000-000000000004"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "workloads_reject_missing_web_digest" {
  command = plan

  variables {
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_origin                             = "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io"
    web_release_evidence_reference         = "web-release:test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:workloads:test"
    database_preparation_attestation = {
      image_digest       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-test"
      box_id             = "00000000-0000-4000-8000-000000000004"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "workloads_reject_unapproved_web_origin" {
  command = plan

  variables {
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_origin                             = "https://wrong.example.invalid"
    web_release_evidence_reference         = "web-release:test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:workloads:test"
    database_preparation_attestation = {
      image_digest       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-test"
      box_id             = "00000000-0000-4000-8000-000000000004"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  expect_failures = [azurerm_container_app.web[0]]
}

run "workloads_create_digest_pinned_https_web_host" {
  command = plan

  variables {
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_origin                             = "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io"
    web_release_evidence_reference         = "web-release:test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:workloads:test"
    database_preparation_attestation = {
      image_digest       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-test"
      box_id             = "00000000-0000-4000-8000-000000000004"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  assert {
    condition = (
      length(azurerm_container_app.web) == 1 &&
      azurerm_container_app.web[0].template[0].container[0].image == "cosmasbetaacrlab01abc123.azurecr.io/cosmas-os-web@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" &&
      azurerm_container_app.web[0].ingress[0].external_enabled == true &&
      azurerm_container_app.web[0].ingress[0].allow_insecure_connections == false &&
      azurerm_container_app.web[0].ingress[0].target_port == 8080 &&
      azurerm_container_app.web[0].template[0].container[0].startup_probe[0].path == "/healthz" &&
      azurerm_container_app.web[0].template[0].container[0].readiness_probe[0].path == "/healthz" &&
      azurerm_container_app.web[0].template[0].container[0].liveness_probe[0].path == "/healthz" &&
      length(azurerm_container_app.web[0].secret) == 0 &&
      azurerm_container_app.web[0].registry[0].identity == azurerm_user_assigned_identity.web.id &&
      azurerm_role_assignment.web_acr_pull.principal_id == azurerm_user_assigned_identity.web.principal_id
    )
    error_message = "Workload release must create one digest-pinned, HTTPS-only static web Container App with no secrets and an ACR-pull-only identity."
  }

  assert {
    condition = (
      output.web_origin == "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io" &&
      output.web_custom_domain_binding_enabled == false &&
      output.api_origin == "https://ca-api-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io"
    )
    error_message = "The reviewed web and API origins must be deterministic within the isolated D3 Container Apps environment."
  }

  assert {
    condition = (
      length(azurerm_container_app.worker) == 1 &&
      azurerm_container_app.worker[0].template[0].container[0].startup_probe[0].transport == "HTTP" &&
      azurerm_container_app.worker[0].template[0].container[0].startup_probe[0].port == 8001 &&
      azurerm_container_app.worker[0].template[0].container[0].startup_probe[0].path == "/ready" &&
      azurerm_container_app.worker[0].template[0].container[0].readiness_probe[0].transport == "HTTP" &&
      azurerm_container_app.worker[0].template[0].container[0].readiness_probe[0].port == 8001 &&
      azurerm_container_app.worker[0].template[0].container[0].readiness_probe[0].path == "/ready"
    )
    error_message = "The D3 worker must gate startup and readiness on its private Celery readiness endpoint."
  }

  assert {
    condition = (
      length(azurerm_container_app_job.runtime_acceptance) == 1 &&
      output.runtime_acceptance_job_enabled == true &&
      azurerm_container_app_job.runtime_acceptance[0].template[0].container[0].image == "cosmasbetaacrlab01abc123.azurecr.io/cosmas-os@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" &&
      azurerm_container_app_job.runtime_acceptance[0].identity[0].identity_ids == toset([azurerm_user_assigned_identity.runtime.id]) &&
      azurerm_container_app_job.runtime_acceptance[0].registry[0].identity == azurerm_user_assigned_identity.runtime.id &&
      azurerm_container_app_job.runtime_acceptance[0].template[0].container[0].command == tolist(["python", "-m", "cosmas_os.cli"]) &&
      azurerm_container_app_job.runtime_acceptance[0].template[0].container[0].args == tolist(["verify-beta-runtime", "--confirm-synthetic-only", "--confirm-runtime-uami"]) &&
      azurerm_container_app_job.runtime_acceptance[0].manual_trigger_config[0].parallelism == 1 &&
      azurerm_container_app_job.runtime_acceptance[0].manual_trigger_config[0].replica_completion_count == 1 &&
      azurerm_container_app_job.runtime_acceptance[0].replica_retry_limit == 0 &&
      length(azurerm_key_vault_secret.runtime_acceptance_hmac_key) == 1 &&
      random_id.runtime_acceptance_hmac_key[0].byte_length == 32 &&
      one([for item in azurerm_container_app_job.runtime_acceptance[0].template[0].container[0].env : item.value if item.name == "AZURE_CLIENT_ID"]) == azurerm_user_assigned_identity.runtime.client_id &&
      one([for item in azurerm_container_app_job.runtime_acceptance[0].template[0].container[0].env : item.value if item.name == "EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID"]) == azurerm_user_assigned_identity.runtime.client_id &&
      one([for item in azurerm_container_app_job.runtime_acceptance[0].template[0].container[0].env : item.secret_name if item.name == "COSMAS_ACCEPTANCE_HMAC_KEY"]) == "acceptance-hmac-key"
    )
    error_message = "Synthetic workloads must include one unscheduled exact-digest runtime acceptance job under the exact runtime UAMI with self-verifying client-ID binding."
  }

  assert {
    condition = (
      length(azurerm_monitor_action_group.workload_health) == 1 &&
      azurerm_monitor_action_group.workload_health[0].email_receiver[0].use_common_alert_schema == true &&
      length(azurerm_monitor_metric_alert.api_unavailable) == 1 &&
      azurerm_monitor_metric_alert.api_unavailable[0].scopes == toset([azurerm_container_app.api[0].id]) &&
      azurerm_monitor_metric_alert.api_unavailable[0].criteria[0].metric_namespace == "Microsoft.App/containerApps" &&
      azurerm_monitor_metric_alert.api_unavailable[0].criteria[0].metric_name == "Replicas" &&
      azurerm_monitor_metric_alert.api_unavailable[0].criteria[0].aggregation == "Average" &&
      azurerm_monitor_metric_alert.api_unavailable[0].criteria[0].operator == "LessThan" &&
      azurerm_monitor_metric_alert.api_unavailable[0].criteria[0].threshold == 1 &&
      azurerm_monitor_metric_alert.api_unavailable[0].criteria[0].skip_metric_validation == false &&
      length(azurerm_monitor_metric_alert.worker_unavailable) == 1 &&
      azurerm_monitor_metric_alert.worker_unavailable[0].scopes == toset([azurerm_container_app.worker[0].id]) &&
      azurerm_monitor_metric_alert.worker_unavailable[0].criteria[0].metric_namespace == "Microsoft.App/containerApps" &&
      azurerm_monitor_metric_alert.worker_unavailable[0].criteria[0].metric_name == "Replicas" &&
      azurerm_monitor_metric_alert.worker_unavailable[0].criteria[0].aggregation == "Average" &&
      azurerm_monitor_metric_alert.worker_unavailable[0].criteria[0].operator == "LessThan" &&
      azurerm_monitor_metric_alert.worker_unavailable[0].criteria[0].threshold == 1 &&
      azurerm_monitor_metric_alert.worker_unavailable[0].criteria[0].skip_metric_validation == false
    )
    error_message = "Workload release must create PHI-safe API and worker replica alerts using the common schema and the human-owned Action Group."
  }
}

run "workloads_create_custom_domain_only_after_dns_gate" {
  command = plan

  variables {
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_custom_domain                      = "app.beta.cosmaneura.com"
    web_custom_domain_dns_ready            = true
    web_origin                             = "https://app.beta.cosmaneura.com"
    web_release_evidence_reference         = "web-release:custom-domain-test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:custom-domain-test"
    database_preparation_attestation = {
      image_digest       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-test"
      box_id             = "00000000-0000-4000-8000-000000000004"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  assert {
    condition = (
      length(azurerm_container_app_custom_domain.web) == 1 &&
      azurerm_container_app_custom_domain.web[0].name == "app.beta.cosmaneura.com" &&
      azurerm_container_app_custom_domain.web[0].container_app_id == azurerm_container_app.web[0].id &&
      output.web_origin == "https://app.beta.cosmaneura.com" &&
      output.web_health_url == "https://app.beta.cosmaneura.com/healthz" &&
      output.web_default_fqdn == "ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io" &&
      output.web_custom_domain_verification_id == "synthetic-domain-verification-id" &&
      output.web_custom_domain_binding_enabled == true
    )
    error_message = "The reviewed custom hostname must bind only to the exact D3 web app and become the exact runtime/Clerk origin after the DNS-ready gate."
  }
}

run "workloads_stage_custom_domain_before_dns_gate" {
  command = plan

  variables {
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_custom_domain                      = "app.beta.cosmaneura.com"
    web_origin                             = "https://app.beta.cosmaneura.com"
    web_release_evidence_reference         = "web-release:custom-domain-test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:custom-domain-test"
    database_preparation_attestation = {
      image_digest       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-test"
      box_id             = "00000000-0000-4000-8000-000000000004"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  assert {
    condition = (
      length(azurerm_container_app.web) == 1 &&
      length(azurerm_container_app_custom_domain.web) == 0 &&
      output.web_origin == "https://app.beta.cosmaneura.com" &&
      output.web_default_fqdn == "ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io" &&
      output.web_custom_domain_verification_id == "synthetic-domain-verification-id" &&
      output.web_custom_domain_binding_enabled == false
    )
    error_message = "The pre-DNS workload stage must expose verification inputs without creating a custom-domain binding."
  }
}

run "rejects_reserved_existing_custom_domain" {
  command = plan

  variables {
    web_custom_domain = "app.cosmaneura.com"
  }

  expect_failures = [var.web_custom_domain]
}

run "rejects_reserved_existing_chat_domain" {
  command = plan

  variables {
    web_custom_domain = "staging-chat.cosmaneura.com"
  }

  expect_failures = [var.web_custom_domain]
}

run "rejects_non_lowercase_custom_domain" {
  command = plan

  variables {
    web_custom_domain = "App.Beta.cosmaneura.com"
  }

  expect_failures = [var.web_custom_domain]
}

run "rejects_shared_azure_container_apps_custom_domain" {
  command = plan

  variables {
    web_custom_domain = "borrowed.example.azurecontainerapps.io"
  }

  expect_failures = [var.web_custom_domain]
}

run "rejects_exact_azure_container_apps_domain" {
  command = plan

  variables {
    web_custom_domain = "azurecontainerapps.io"
  }

  expect_failures = [var.web_custom_domain]
}

run "workloads_reject_missing_alert_contact" {
  command = plan

  variables {
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    database_preparation_image_digest      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_origin                             = "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io"
    web_release_evidence_reference         = "web-release:test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:workloads:test"
    alert_contact_email                    = null
    database_preparation_attestation = {
      image_digest       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-test"
      box_id             = "00000000-0000-4000-8000-000000000004"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "database_candidate_can_advance_without_replacing_live_workloads" {
  command = plan

  variables {
    deploy_workloads                       = true
    enable_database_preparation_job        = true
    image_digest                           = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    database_preparation_image_digest      = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    web_image_digest                       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    web_origin                             = "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io"
    web_release_evidence_reference         = "web-release:test"
    runtime_database_url                   = "postgresql+psycopg://cosmas_runtime:synthetic-runtime-password@pg-cosmas-beta-lab01-abc123.postgres.database.azure.com:5432/cosmas_os?sslmode=verify-full&sslrootcert=system"
    runner_live_network_evidence_reference = "network-live:upgrade:test"
    database_preparation_attestation = {
      image_digest       = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      schema_revision    = "0002_external_identities"
      evidence_sha256    = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      execution_id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-lab01/executions/database-preparation-execution-current"
      box_id             = "00000000-0000-4000-8000-000000000004"
      database_server_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-lab01-abc123"
    }
  }

  assert {
    condition = (
      azurerm_container_app_job.database_preparation[0].template[0].container[0].image == "cosmasbetaacrlab01abc123.azurecr.io/cosmas-os@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" &&
      azurerm_container_app.api[0].template[0].container[0].image == "cosmasbetaacrlab01abc123.azurecr.io/cosmas-os@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" &&
      azurerm_container_app.worker[0].template[0].container[0].image == "cosmasbetaacrlab01abc123.azurecr.io/cosmas-os@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    error_message = "A candidate migration image must stage independently while the last-attested API and worker digest remains live."
  }
}

run "synthetic_lab_accepts_reviewed_public_registry_exception" {
  command = plan

  variables {
    registry_network_posture                      = "synthetic_public_exception"
    synthetic_public_registry_exception_reference = "risk-review:test"
  }

  assert {
    condition = (
      output.deployment_mode == "synthetic_lab" &&
      output.registry_network_posture == "synthetic_public_exception" &&
      output.registry_sku == "Basic" &&
      output.registry_public_network_access_enabled == true &&
      azurerm_container_registry.beta.sku == "Basic" &&
      azurerm_container_registry.beta.admin_enabled == false &&
      azurerm_container_registry.beta.anonymous_pull_enabled == false &&
      length(azurerm_private_endpoint.acr) == 0 &&
      length(azurerm_private_dns_zone.acr) == 0 &&
      length(azurerm_private_dns_zone_virtual_network_link.acr) == 0
    )
    error_message = "The reviewed synthetic exception must be an authenticated Basic/public ACR with no misleading Private Link resources."
  }
}

run "synthetic_lab_rejects_unreviewed_public_registry_exception" {
  command = plan

  variables {
    registry_network_posture = "synthetic_public_exception"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "private_registry_rejects_stale_public_exception_reference" {
  command = plan

  variables {
    synthetic_public_registry_exception_reference = "risk-review:test"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "authorized_beta_rejects_public_registry_exception" {
  command = plan

  variables {
    deployment_mode                               = "authorized_beta"
    registry_network_posture                      = "synthetic_public_exception"
    synthetic_public_registry_exception_reference = "risk-review:test"
    clinic_legal_name                             = "Invented Test Clinic"
    clinic_approval_reference                     = "clinic:test"
    baa_evidence_reference                        = "baa:test"
    phi_authorization_reference                   = "phi:test"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "authorized_beta_rejects_missing_clinic" {
  command = plan

  variables {
    deployment_mode             = "authorized_beta"
    clinic_approval_reference   = "clinic:test"
    baa_evidence_reference      = "baa:test"
    phi_authorization_reference = "phi:test"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "authorized_beta_rejects_missing_clinic_approval" {
  command = plan

  variables {
    deployment_mode             = "authorized_beta"
    clinic_legal_name           = "Invented Test Clinic"
    baa_evidence_reference      = "baa:test"
    phi_authorization_reference = "phi:test"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "authorized_beta_rejects_missing_baa" {
  command = plan

  variables {
    deployment_mode             = "authorized_beta"
    clinic_legal_name           = "Invented Test Clinic"
    clinic_approval_reference   = "clinic:test"
    phi_authorization_reference = "phi:test"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "authorized_beta_rejects_missing_phi_authorization" {
  command = plan

  variables {
    deployment_mode           = "authorized_beta"
    clinic_legal_name         = "Invented Test Clinic"
    clinic_approval_reference = "clinic:test"
    baa_evidence_reference    = "baa:test"
  }

  expect_failures = [terraform_data.prerequisite_guard]
}

run "authorized_beta_accepts_all_phi_prerequisites" {
  command = plan

  override_data {
    target = data.azurerm_resource_group.beta
    values = {
      id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01"
      location = "centralus"
      tags = {
        track               = "B"
        product             = "cosmas-os"
        env                 = "early_adopter_beta"
        deployment_mode     = "authorized_beta"
        data_classification = "phi-authorized"
        box_scope           = "dedicated"
        box_id              = "00000000-0000-4000-8000-000000000004"
        connectors          = "dark"
        managed             = "terraform"
      }
    }
  }

  override_data {
    target = data.azurerm_resource_group.state
    values = {
      id       = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01"
      location = "centralus"
      tags = {
        track               = "B"
        product             = "cosmas-os"
        env                 = "early_adopter_beta"
        deployment_mode     = "authorized_beta"
        data_classification = "phi-authorized"
        box_scope           = "dedicated"
        box_id              = "00000000-0000-4000-8000-000000000004"
        connectors          = "dark"
        managed             = "terraform"
      }
    }
  }

  variables {
    deployment_mode             = "authorized_beta"
    clinic_legal_name           = "Invented Test Clinic"
    clinic_approval_reference   = "clinic:test"
    baa_evidence_reference      = "baa:test"
    phi_authorization_reference = "phi:test"
  }

  assert {
    condition = (
      output.deployment_mode == "authorized_beta" &&
      output.data_classification == "phi-authorized" &&
      output.runtime_data_mode == "authorized_beta"
    )
    error_message = "Authorized beta must map to the PHI runtime mode only after all PHI prerequisites are present."
  }

  assert {
    condition = (
      length(azurerm_key_vault_secret.clinic_approval_reference) == 0 &&
      length(azurerm_key_vault_secret.baa_evidence_reference) == 0 &&
      length(azurerm_key_vault_secret.phi_authorization_reference) == 0
    )
    error_message = "Even an authorized-beta foundation must defer protected workload evidence secrets until workload enablement."
  }

  assert {
    condition     = length(terraform_data.authorized_beta_mode_lock) == 1
    error_message = "Authorized beta must create a non-downgradable mode lock."
  }

  assert {
    condition = (
      output.registry_network_posture == "private" &&
      output.registry_sku == "Premium" &&
      output.registry_public_network_access_enabled == false &&
      length(azurerm_private_endpoint.acr) == 1
    )
    error_message = "Authorized beta must fail closed to Premium/private ACR with no public network access."
  }
}

run "rejects_worker_scale_out" {
  command = plan

  variables {
    worker_max_replicas = 2
  }

  expect_failures = [var.worker_max_replicas]
}

run "rejects_worker_scale_to_zero" {
  command = plan

  variables {
    worker_min_replicas = 0
  }

  expect_failures = [var.worker_min_replicas]
}
