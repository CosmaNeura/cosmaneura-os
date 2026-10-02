variables {
  api_origin              = "https://api.example.invalid"
  web_origin              = "https://workspace.example.invalid"
  key_vault_uri           = "https://invented-beta.vault.azure.net/"
  core_identity_client_id = "00000000-0000-4000-8000-000000000001"
}

run "disabled_has_no_extra_configuration" {
  command = plan
  assert {
    condition     = length(output.public_env) == 0 && length(output.secret_env) == 0 && length(output.secret_definitions) == 0
    error_message = "Defaults must not configure services or obtain secrets."
  }
}

run "configured_account_connections" {
  command = plan
  variables {
    hosted_enabled = true
    features = {
      WORKSPACE_CORE_CONNECTION_ENABLED       = true
      WORKSPACE_ATHENA_CONNECTION_ENABLED     = true
      WORKSPACE_ATHENA_VISIT_LINK_ENABLED     = true
      WORKSPACE_SCHEDULING_ENABLED            = true
      WORKSPACE_SCHEDULING_LOGIN_ENABLED      = true
      WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED = true
      WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED = true
      WORKSPACE_APPOINTMENTS_ENABLED = true
      WORKSPACE_GOOGLE_CONNECTION_ENABLED     = true
      WORKSPACE_GOOGLE_MESSAGE_ENABLED        = true
      WORKSPACE_GOOGLE_CALENDAR_ENABLED       = true
      WORKSPACE_MICROSOFT_CONNECTION_ENABLED  = true
      VENDOR_WORK_ENABLED                     = true
      VENDOR_IO_ENABLED                       = true
    }
    public_configuration = {
      CORE_CAPTURE_ORIGIN               = "https://core-api.example.invalid"
      CORE_CAPTURE_SCOPE                = "api://invented-core/.default"
      CORE_CONNECTION_TENANT_REF        = "authority_tenant_00000000000000000000000000"
      SCHEDULING_ORIGIN                 = "https://scheduling.example.invalid"
      SCHEDULING_GOOGLE_CLIENT_ID       = "invented.apps.googleusercontent.com"
      SCHEDULING_ENROLLMENT_PRACTICE_ID = "00000000-0000-4000-8000-000000000004"
      GOOGLE_CONNECTION_CLIENT_ID       = "invented.apps.googleusercontent.com"
      MICROSOFT_CONNECTION_TENANT_ID    = "00000000-0000-4000-8000-000000000002"
      MICROSOFT_CONNECTION_CLIENT_ID    = "00000000-0000-4000-8000-000000000003"
    }
    secret_references = {
      SCHEDULING_GOOGLE_CLIENT_SECRET     = { secret_name = "scheduling-oauth", version = "00000000000000000000000000000001" }
      SCHEDULING_LOGIN_ENCRYPTION_KEY     = { secret_name = "scheduling-custody", version = "00000000000000000000000000000002" }
      GOOGLE_CONNECTION_CLIENT_SECRET     = { secret_name = "gmail-oauth", version = "00000000000000000000000000000003" }
      GOOGLE_CONNECTION_ENCRYPTION_KEY    = { secret_name = "gmail-custody", version = "00000000000000000000000000000004" }
      MICROSOFT_CONNECTION_CLIENT_SECRET  = { secret_name = "microsoft-oauth", version = "00000000000000000000000000000005" }
      MICROSOFT_CONNECTION_ENCRYPTION_KEY = { secret_name = "microsoft-custody", version = "00000000000000000000000000000006" }
      COSMAS_MANAGED_SECRET_DOCUMO_API    = { secret_name = "documo-api", version = "00000000000000000000000000000007" }
    }
    managed_manifest = {
      secret_name = "managed-accounts"
      version     = "00000000000000000000000000000008"
      sha256      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  }
  assert {
    condition     = output.public_env.GOOGLE_CONNECTION_CALLBACK_URI == "https://api.example.invalid/connections/google/callback" && output.public_env.SCHEDULING_GOOGLE_CALLBACK_URI == "https://api.example.invalid/connections/scheduling/google/callback" && output.public_env.MICROSOFT_CONNECTION_CALLBACK_URI == "https://api.example.invalid/connections/microsoft/callback"
    error_message = "Each connection must use its actual fixed API callback."
  }
  assert {
    condition     = output.public_env.GOOGLE_CONNECTION_RETURN_ORIGIN == "https://workspace.example.invalid" && output.public_env.CORE_CAPTURE_MANAGED_IDENTITY_CLIENT_ID == var.core_identity_client_id
    error_message = "Connection returns and Core identity must match the deployment."
  }
  assert {
    condition     = output.public_env.WORKSPACE_GOOGLE_CALENDAR_ENABLED == "true"
    error_message = "Calendar review must remain an explicit classified service feature."
  }
  assert {
    condition     = output.public_env.WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED == "true" && output.public_env.WORKSPACE_APPOINTMENTS_ENABLED == "true"
    error_message = "Patient setup must remain explicit and require appointment proposals."
  }
  assert {
    condition     = length(output.secret_definitions) == 8 && length(output.secret_env) == 8 && output.secret_definitions[output.secret_env.MANAGED_SERVICES_CONFIG_JSON] == "https://invented-beta.vault.azure.net/secrets/managed-accounts/00000000000000000000000000000008"
    error_message = "Manifest and account credentials must resolve to exact versions in the dedicated vault."
  }
  assert {
    condition     = !contains(keys(output.public_env), "GOOGLE_CONNECTION_CLIENT_SECRET") && !contains(keys(output.secret_env), "DATABASE_URL") && !contains(keys(output.public_env), "WORKSPACE_ATHENA_WRITE_ENABLED")
    error_message = "Public configuration must exclude secrets and cannot grant Athena writes or replace foundational settings."
  }
}

run "missing_oauth_custody_rejected" {
  command = plan
  variables {
    hosted_enabled       = true
    features             = { WORKSPACE_GOOGLE_CONNECTION_ENABLED = true }
    public_configuration = { GOOGLE_CONNECTION_CLIENT_ID = "invented.apps.googleusercontent.com" }
  }
  expect_failures = [terraform_data.configuration_guard]
}

run "calendar_work_requires_underlying_google_connection" {
  command = plan
  variables {
    hosted_enabled = true
    features       = { WORKSPACE_GOOGLE_CALENDAR_ENABLED = true }
  }
  expect_failures = [terraform_data.configuration_guard]
}

run "patient_setup_requires_sign_in_and_proposals" {
  command = plan
  variables {
    hosted_enabled = true
    features = { WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED = true }
  }
  expect_failures = [terraform_data.configuration_guard]
}

run "message_work_requires_underlying_google_connection" {
  command = plan
  variables {
    hosted_enabled = true
    features       = { WORKSPACE_GOOGLE_MESSAGE_ENABLED = true }
  }
  expect_failures = [terraform_data.configuration_guard]
}

run "unknown_feature_rejected" {
  command = plan
  variables {
    hosted_enabled = true
    features       = { WORKSPACE_ATHENA_WRITE_ENABLED = true }
  }
  expect_failures = [var.features]
}

run "foundational_secret_override_rejected" {
  command = plan
  variables {
    hosted_enabled    = true
    secret_references = { DATABASE_URL = { secret_name = "other-database", version = "00000000000000000000000000000001" } }
  }
  expect_failures = [var.secret_references]
}

run "unversioned_secret_rejected" {
  command = plan
  variables {
    hosted_enabled    = true
    secret_references = { GOOGLE_CONNECTION_CLIENT_SECRET = { secret_name = "oauth", version = "latest" } }
  }
  expect_failures = [var.secret_references]
}

run "managed_execution_without_accounts_rejected" {
  command = plan
  variables {
    hosted_enabled = true
    features       = { VENDOR_WORK_ENABLED = true, VENDOR_IO_ENABLED = true }
  }
  expect_failures = [terraform_data.configuration_guard]
}

run "athena_without_core_rejected" {
  command = plan
  variables {
    hosted_enabled = true
    features       = { WORKSPACE_ATHENA_CONNECTION_ENABLED = true }
  }
  expect_failures = [terraform_data.configuration_guard]
}
