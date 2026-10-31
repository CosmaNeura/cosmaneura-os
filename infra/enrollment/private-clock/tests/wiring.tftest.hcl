mock_provider "azurerm" {
  mock_resource "azurerm_private_dns_zone" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.Network/privateDnsZones/clock-mock1234.postgres.database.azure.com" }
  }
  mock_resource "azurerm_postgresql_flexible_server" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-cbot-clock-stg-mock1234", fqdn = "psql-cbot-clock-stg-mock1234.postgres.database.azure.com" }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = { id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-mock1234/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-clock", principal_id = "00000000-0000-4000-8000-000000000099" }
  }
}
variables {
  subscription_id         = "00000000-0000-4000-8000-000000000001"
  tenant_id               = "00000000-0000-4000-8000-000000000002"
  resource_name_suffix    = "mock1234"
  foundation_file         = "tests/foundation.json"
  bootstrap_key_file      = "tests/key.txt"
  postgres_admin_password = "Synthetic-Mock-Only-Aa1_"
}
run "closed_private_server" {
  command = plan
  assert {
    condition = (azurerm_postgresql_flexible_server.clock.version == "16" &&
      azurerm_postgresql_flexible_server.clock.sku_name == "B_Standard_B1ms" && azurerm_postgresql_flexible_server.clock.storage_mb == 32768 &&
      !azurerm_postgresql_flexible_server.clock.public_network_access_enabled && azurerm_postgresql_flexible_server.clock.location == "centralus" &&
      azurerm_postgresql_flexible_server.clock.delegated_subnet_id == "${local.f.vnet_id}/subnets/snet-postgres" &&
      azurerm_postgresql_flexible_server_database.clock.name == "cosmabot_enrollment_clock_lab" &&
      length(azurerm_container_app_job.clock) == 0 && length(azurerm_role_assignment.secret) == 0 && length(azurerm_role_assignment.runtime) == 0 &&
      length(output.private_clock.binding_sha256) == 0 && !output.private_clock.runtime_grants_created &&
    !output.private_clock.hosted_qualified && !output.private_clock.source_database_modified)
    error_message = "Only an independent private journal server is allowed; no job, vendor/grant or hosted-readiness claim."
  }
}
run "manual_bootstrap_scoped_secrets" {
  command = plan
  variables {
    binding_sha256 = { a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
    create_job     = true
    operation      = "bootstrap"
    image          = "acrcbotenrstgmock1234.azurecr.io/private-clock-job@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    secret_references = {
      admin    = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-bootstrap-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      a        = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-journal-a-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      b        = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-journal-b-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      bindings = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-bindings/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
    runtime_principal_ids = { a = "00000000-0000-4000-8000-000000000091", b = "00000000-0000-4000-8000-000000000092" }
  }
  assert {
    condition = (length(azurerm_role_assignment.secret) == 4 && length(azurerm_role_assignment.runtime) == 2 &&
      alltrue([for slot, grant in azurerm_role_assignment.runtime : endswith(grant.scope, "/enrollment-private-clock-journal-${slot}-url")]) &&
      length(azurerm_container_app_job.clock[0].manual_trigger_config) == 1 &&
      one(azurerm_container_app_job.clock[0].manual_trigger_config).parallelism == 1 &&
      length(azurerm_container_app_job.clock[0].schedule_trigger_config) == 0 && length(azurerm_container_app_job.clock[0].event_trigger_config) == 0 &&
      azurerm_container_app_job.clock[0].replica_retry_limit == 0 && !output.private_clock.manual_job_started &&
    azurerm_role_assignment.pull[0].role_definition_name == "AcrPull")
    error_message = "Manual bootstrap only; each runtime principal can read its own journal credential only."
  }
}
run "manual_check_excludes_admin" {
  command = plan
  variables {
    binding_sha256 = { a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
    create_job     = true
    image          = "acrcbotenrstgmock1234.azurecr.io/private-clock-job@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    secret_references = {
      a        = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-journal-a-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      b        = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-journal-b-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      bindings = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-bindings/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  }
  assert {
    condition     = length(azurerm_role_assignment.secret) == 3 && !contains(keys(azurerm_role_assignment.secret), "admin")
    error_message = "The recurring manual check must never read the administrator credential."
  }
}
run "deny_unbound_runtime_grant" {
  command = plan
  variables {
    binding_sha256        = {}
    runtime_principal_ids = { a = "00000000-0000-4000-8000-000000000091" }
  }
  expect_failures = [terraform_data.guard]
}
run "deny_unbound_job" {
  command = plan
  variables {
    binding_sha256 = {}
    create_job     = true
    image          = "acrcbotenrstgmock1234.azurecr.io/private-clock-job@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    secret_references = {
      a        = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-journal-a-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      b        = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-journal-b-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      bindings = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-bindings/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  }
  expect_failures = [terraform_data.guard]
}
run "deny_central_database_secret" {
  command = plan
  variables {
    binding_sha256 = { a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
    create_job     = true
    image          = "acrcbotenrstgmock1234.azurecr.io/private-clock-job@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    secret_references = {
      a        = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-database-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      b        = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-journal-b-url/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      bindings = "https://kv-cbot-enr-stg-mock1234.vault.azure.net/secrets/enrollment-private-clock-bindings/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  }
  expect_failures = [terraform_data.guard]
}
