mock_provider "azurerm" {
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-enrollment-mocked"
      principal_id = "00000000-0000-4000-8000-000000000003"
      client_id    = "00000000-0000-4000-8000-000000000004"
    }
  }
  mock_resource "azurerm_container_app" {
    defaults = {
      id                            = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-test/providers/Microsoft.App/containerApps/ca-cosmabot-enrollment-mocked"
      custom_domain_verification_id = "synthetic-ownership-token"
      ingress                       = { fqdn = "ca-account.synthetic.centralus.azurecontainerapps.io" }
    }
  }
}
mock_provider "external" {
  mock_data "external" {
    defaults = { result = { verified = "true", hostname = "synthetic-host", records_sha256 = "synthetic" } }
  }
}
variables {
  subscription_id              = "00000000-0000-4000-8000-000000000001"
  tenant_id                    = "00000000-0000-4000-8000-000000000002"
  environment                  = "staging"
  resource_group_name          = "rg-cosmabot-enrollment-staging-test"
  location                     = "centralus"
  container_app_environment_id = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-test/providers/Microsoft.App/managedEnvironments/cae-enrollment"
  container_registry_id        = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-test/providers/Microsoft.ContainerRegistry/registries/inventedenrollment"
  registry_server              = "inventedenrollment.azurecr.io"
  key_vault_id                 = "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmabot-enrollment-staging-test/providers/Microsoft.KeyVault/vaults/inventedenrollment"
  key_vault_uri                = "https://inventedenrollment.vault.azure.net/"
  rendered_directory           = "tests/staging-fixture"
}
run "defaults_create_neither_account_web_nor_domains" {
  command = plan
  assert {
    condition     = length(azurerm_container_app.staging_web) == 0 && length(azurerm_container_app_custom_domain.staging) == 0
    error_message = "Default plans must not deploy account web or bind public domains."
  }
}
run "qualified_apps_expose_exact_dns_without_binding" {
  command = apply
  variables {
    deploy_workload                = true
    database_preparation_qualified = true
    deploy_staging_web             = true
    staging_web_image              = "inventedenrollment.azurecr.io/account-web@sha256:3333333333333333333333333333333333333333333333333333333333333333"
  }
  assert {
    condition     = azurerm_container_app.staging_web[0].ingress[0].target_port == 8080 && length(azurerm_container_app_custom_domain.staging) == 0
    error_message = "The account image must use existing nginx port/health conventions, without early domain binding."
  }
  assert {
    condition     = output.staging_account_dns_records.account.cname.name == "onboarding.staging.cosmas.ai" && output.staging_account_dns_records.api.txt.name == "asuid.enrollment-api.staging.cosmas.ai"
    error_message = "Publish only the exact new owned account/API DNS records."
  }
  assert {
    condition     = azurerm_role_assignment.staging_web_registry[0].role_definition_name == "AcrPull"
    error_message = "The static web app needs image pull only; no private API vault/database identity."
  }
}
run "verified_dns_requests_two_managed_certificate_bindings" {
  command = apply
  variables {
    deploy_workload                = true
    database_preparation_qualified = true
    deploy_staging_web             = true
    staging_web_image              = "inventedenrollment.azurecr.io/account-web@sha256:3333333333333333333333333333333333333333333333333333333333333333"
    bind_staging_custom_domains    = true
  }
  assert {
    condition     = toset([for binding in azurerm_container_app_custom_domain.staging : binding.name]) == toset(["onboarding.staging.cosmas.ai", "enrollment-api.staging.cosmas.ai"])
    error_message = "Only the two exact new domains may receive managed certificate bindings."
  }
}
run "foreign_web_image_is_denied" {
  command = plan
  variables {
    deploy_workload                = true
    database_preparation_qualified = true
    deploy_staging_web             = true
    staging_web_image              = "foreign.azurecr.io/account-web@sha256:3333333333333333333333333333333333333333333333333333333333333333"
  }
  expect_failures = [terraform_data.staging_web_guard]
}
run "unpropagated_dns_denies_binding" {
  command = plan
  variables {
    deploy_workload                = true
    database_preparation_qualified = true
    deploy_staging_web             = true
    staging_web_image              = "inventedenrollment.azurecr.io/account-web@sha256:3333333333333333333333333333333333333333333333333333333333333333"
    bind_staging_custom_domains    = true
  }
  override_data {
    target = data.external.staging_dns
    values = { result = { verified = "false" } }
  }
  expect_failures = [azurerm_container_app_custom_domain.staging]
}
