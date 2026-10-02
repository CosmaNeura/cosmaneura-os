terraform {
  required_version = ">= 1.9.0"
}

variable "hosted_enabled" {
  type    = bool
  default = false
}

variable "features" {
  type    = map(bool)
  default = {}
  validation {
    condition     = alltrue([for name in keys(var.features) : contains(["WORKSPACE_AI_ACTIVITY_ENABLED", "WORKSPACE_TEAM_SETUP_ENABLED", "WORKSPACE_ROUTINES_ENABLED", "WORKSPACE_RESEARCH_ENABLED", "WORKSPACE_RESEARCH_IO_ENABLED", "WORKSPACE_CORE_RECORD_ENABLED", "WORKSPACE_CORE_CONNECTION_ENABLED", "WORKSPACE_CORE_APPOINTMENT_SETUP_ENABLED", "WORKSPACE_ATHENA_CONNECTION_ENABLED", "WORKSPACE_ATHENA_VISIT_LINK_ENABLED", "WORKSPACE_PREP_ENABLED", "WORKSPACE_PREP_WORK_ENABLED", "WORKSPACE_APPOINTMENTS_ENABLED", "WORKSPACE_CAPTURE_NOTES_ENABLED", "WORKSPACE_CAPTURE_CORRECTIONS_ENABLED", "WORKSPACE_CAPTURE_RECOVERY_ENABLED", "WORKSPACE_CAPTURE_SOURCE_ENABLED", "WORKSPACE_CAPTURE_LONG_VISITS_ENABLED", "WORKSPACE_SCHEDULING_ENABLED", "WORKSPACE_SCHEDULING_LOGIN_ENABLED", "WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED", "WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED", "WORKSPACE_GOOGLE_CONNECTION_ENABLED", "WORKSPACE_GOOGLE_MESSAGE_ENABLED", "WORKSPACE_GOOGLE_CALENDAR_ENABLED", "WORKSPACE_MICROSOFT_CONNECTION_ENABLED", "VENDOR_SETUP_ENABLED", "VENDOR_WORK_ENABLED", "VENDOR_IO_ENABLED", "VENDOR_EVENTS_ENABLED", "FINANCE_SETUP_ENABLED", "FINANCE_WORK_ENABLED", "FINANCE_IO_ENABLED", "FINANCE_EVENTS_ENABLED", "PORTAL_SETUP_ENABLED", "PORTAL_WORK_ENABLED", "MEMBERSHIP_WORK_ENABLED", "INBOX_WORK_ENABLED", "INBOX_HANDOFF_ENABLED"], name)])
    error_message = "Only supported workspace feature flags may be supplied."
  }
}

variable "public_configuration" {
  type    = map(string)
  default = {}
  validation {
    condition     = alltrue([for name, value in var.public_configuration : contains(["CORE_CAPTURE_ORIGIN", "CORE_CAPTURE_SCOPE", "CORE_WEB_ORIGIN", "CORE_CONNECTION_TENANT_REF", "WORKSPACE_CAPTURE_BACKEND", "WORKSPACE_LLM_BACKEND", "SCHEDULING_ORIGIN", "SCHEDULING_GOOGLE_CLIENT_ID", "SCHEDULING_ENROLLMENT_PRACTICE_ID", "GOOGLE_CONNECTION_CLIENT_ID", "MICROSOFT_CONNECTION_TENANT_ID", "MICROSOFT_CONNECTION_CLIENT_ID", "RESEARCH_SOURCES", "RESEARCH_DATASET_MAPPINGS"], name) && length(value) > 0 && length(value) <= 16384])
    error_message = "Public configuration must use supported nonempty workspace settings; secrets are separate."
  }
}

variable "secret_references" {
  type    = map(object({ secret_name = string, version = string }))
  default = {}
  validation {
    condition = length(var.secret_references) <= 100 && alltrue([for name, value in var.secret_references :
      (contains(["SCHEDULING_GOOGLE_CLIENT_SECRET", "SCHEDULING_LOGIN_ENCRYPTION_KEY", "GOOGLE_CONNECTION_CLIENT_SECRET", "GOOGLE_CONNECTION_ENCRYPTION_KEY", "MICROSOFT_CONNECTION_CLIENT_SECRET", "MICROSOFT_CONNECTION_ENCRYPTION_KEY", "WORKSPACE_LLM_API_KEY", "RESEARCH_OPENFDA_API_KEY"], name) || can(regex("^COSMAS_MANAGED_SECRET_[A-Z][A-Z0-9_]{0,63}$", name))) &&
    can(regex("^[A-Za-z0-9-]{1,127}$", value.secret_name)) && can(regex("^[0-9a-f]{32}$", value.version))])
    error_message = "Secrets require supported environment names and exact Key Vault secret names/versions."
  }
}

variable "managed_manifest" {
  type    = object({ secret_name = string, version = string, sha256 = string })
  default = null
  validation {
    condition = var.managed_manifest == null ? true : (can(regex("^[A-Za-z0-9-]{1,127}$", var.managed_manifest.secret_name)) &&
    can(regex("^[0-9a-f]{32}$", var.managed_manifest.version)) && can(regex("^[0-9a-f]{64}$", var.managed_manifest.sha256)))
    error_message = "The managed-account manifest requires an exact secret version and content SHA256."
  }
}

variable "api_origin" { type = string }
variable "web_origin" { type = string }
variable "key_vault_uri" { type = string }
variable "core_identity_client_id" { type = string }

locals {
  enabled = { for name in ["WORKSPACE_AI_ACTIVITY_ENABLED", "WORKSPACE_TEAM_SETUP_ENABLED", "WORKSPACE_ROUTINES_ENABLED", "WORKSPACE_RESEARCH_ENABLED", "WORKSPACE_RESEARCH_IO_ENABLED", "WORKSPACE_CORE_RECORD_ENABLED", "WORKSPACE_CORE_CONNECTION_ENABLED", "WORKSPACE_CORE_APPOINTMENT_SETUP_ENABLED", "WORKSPACE_ATHENA_CONNECTION_ENABLED", "WORKSPACE_ATHENA_VISIT_LINK_ENABLED", "WORKSPACE_PREP_ENABLED", "WORKSPACE_PREP_WORK_ENABLED", "WORKSPACE_APPOINTMENTS_ENABLED", "WORKSPACE_CAPTURE_NOTES_ENABLED", "WORKSPACE_CAPTURE_CORRECTIONS_ENABLED", "WORKSPACE_CAPTURE_RECOVERY_ENABLED", "WORKSPACE_CAPTURE_SOURCE_ENABLED", "WORKSPACE_CAPTURE_LONG_VISITS_ENABLED", "WORKSPACE_SCHEDULING_ENABLED", "WORKSPACE_SCHEDULING_LOGIN_ENABLED", "WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED", "WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED", "WORKSPACE_GOOGLE_CONNECTION_ENABLED", "WORKSPACE_GOOGLE_MESSAGE_ENABLED", "WORKSPACE_GOOGLE_CALENDAR_ENABLED", "WORKSPACE_MICROSOFT_CONNECTION_ENABLED", "VENDOR_SETUP_ENABLED", "VENDOR_WORK_ENABLED", "VENDOR_IO_ENABLED", "VENDOR_EVENTS_ENABLED", "FINANCE_SETUP_ENABLED", "FINANCE_WORK_ENABLED", "FINANCE_IO_ENABLED", "FINANCE_EVENTS_ENABLED", "PORTAL_SETUP_ENABLED", "PORTAL_WORK_ENABLED", "MEMBERSHIP_WORK_ENABLED", "INBOX_WORK_ENABLED", "INBOX_HANDOFF_ENABLED"] : name => lookup(var.features, name, false) }
  public  = var.public_configuration
  core    = local.enabled.WORKSPACE_CORE_CONNECTION_ENABLED || lookup(local.public, "WORKSPACE_CAPTURE_BACKEND", "disabled") == "core"
  oauth = {
    scheduling = {
      enabled  = local.enabled.WORKSPACE_SCHEDULING_LOGIN_ENABLED
      public   = ["SCHEDULING_GOOGLE_CLIENT_ID"]
      secrets  = ["SCHEDULING_GOOGLE_CLIENT_SECRET", "SCHEDULING_LOGIN_ENCRYPTION_KEY"]
      callback = "SCHEDULING_GOOGLE_CALLBACK_URI"
      path     = "/connections/scheduling/google/callback"
      return   = "SCHEDULING_LOGIN_RETURN_ORIGIN"
    }
    google = {
      enabled  = local.enabled.WORKSPACE_GOOGLE_CONNECTION_ENABLED
      public   = ["GOOGLE_CONNECTION_CLIENT_ID"]
      secrets  = ["GOOGLE_CONNECTION_CLIENT_SECRET", "GOOGLE_CONNECTION_ENCRYPTION_KEY"]
      callback = "GOOGLE_CONNECTION_CALLBACK_URI"
      path     = "/connections/google/callback"
      return   = "GOOGLE_CONNECTION_RETURN_ORIGIN"
    }
    microsoft = {
      enabled  = local.enabled.WORKSPACE_MICROSOFT_CONNECTION_ENABLED
      public   = ["MICROSOFT_CONNECTION_TENANT_ID", "MICROSOFT_CONNECTION_CLIENT_ID"]
      secrets  = ["MICROSOFT_CONNECTION_CLIENT_SECRET", "MICROSOFT_CONNECTION_ENCRYPTION_KEY"]
      callback = "MICROSOFT_CONNECTION_CALLBACK_URI"
      path     = "/connections/microsoft/callback"
      return   = "MICROSOFT_CONNECTION_RETURN_ORIGIN"
    }
  }
  callbacks = merge({}, [for connection in values(local.oauth) : connection.enabled ? {
    (connection.callback) = "${var.api_origin}${connection.path}"
    (connection.return)   = var.web_origin
  } : {}]...)
  public_env = var.hosted_enabled ? merge(
    { for name, value in var.features : name => tostring(value) }, local.public, local.callbacks,
    local.core ? { CORE_CAPTURE_MANAGED_IDENTITY_CLIENT_ID = var.core_identity_client_id } : {},
    var.managed_manifest == null ? {} : { MANAGED_SERVICES_CONFIG_SHA256 = var.managed_manifest.sha256 }
  ) : {}
  references = var.hosted_enabled ? merge(var.secret_references,
    var.managed_manifest == null ? {} : { MANAGED_SERVICES_CONFIG_JSON = {
      secret_name = var.managed_manifest.secret_name, version = var.managed_manifest.version
  } }) : {}
  secret_env = { for name, reference in local.references : name => "ws-${substr(sha256(name), 0, 32)}" }
  secret_definitions = { for name, reference in local.references : local.secret_env[name] =>
  "${var.key_vault_uri}secrets/${reference.secret_name}/${reference.version}" }
}

resource "terraform_data" "configuration_guard" {
  input = { public_env = local.public_env, secret_references = local.secret_definitions }
  lifecycle {
    precondition {
      condition     = var.hosted_enabled || (length(var.features) == 0 && length(var.public_configuration) == 0 && length(var.secret_references) == 0 && var.managed_manifest == null)
      error_message = "Workspace configuration requires the explicit hosted profile."
    }
    precondition {
      condition     = !var.hosted_enabled || (can(regex("^https://[a-z0-9.-]+$", var.api_origin)) && can(regex("^https://[a-z0-9.-]+$", var.web_origin)) && can(regex("^https://[a-z0-9-]+[.]vault[.]azure[.]net/$", var.key_vault_uri)))
      error_message = "Workspace origins and the dedicated Key Vault URI must be exact HTTPS destinations."
    }
    precondition {
      condition     = !local.core || (alltrue([for key in ["CORE_CAPTURE_ORIGIN", "CORE_CAPTURE_SCOPE"] : contains(keys(local.public), key)]) && can(regex("^[0-9a-f-]{36}$", var.core_identity_client_id)))
      error_message = "Core connectivity requires its reviewed origin, token scope and selected runtime identity."
    }
    precondition {
      condition     = !local.enabled.WORKSPACE_CORE_CONNECTION_ENABLED || contains(keys(local.public), "CORE_CONNECTION_TENANT_REF")
      error_message = "Core account connection requires the reviewed tenant reference."
    }
    precondition {
      condition = alltrue([for pair in [
        ["WORKSPACE_CORE_APPOINTMENT_SETUP_ENABLED", "WORKSPACE_CORE_CONNECTION_ENABLED"],
        ["WORKSPACE_ATHENA_CONNECTION_ENABLED", "WORKSPACE_CORE_CONNECTION_ENABLED"],
        ["WORKSPACE_ATHENA_VISIT_LINK_ENABLED", "WORKSPACE_ATHENA_CONNECTION_ENABLED"],
        ["WORKSPACE_SCHEDULING_LOGIN_ENABLED", "WORKSPACE_SCHEDULING_ENABLED"],
        ["WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED", "WORKSPACE_SCHEDULING_LOGIN_ENABLED"],
        ["WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED", "WORKSPACE_SCHEDULING_LOGIN_ENABLED"],
        ["WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED", "WORKSPACE_APPOINTMENTS_ENABLED"],
        ["WORKSPACE_GOOGLE_CALENDAR_ENABLED", "WORKSPACE_GOOGLE_CONNECTION_ENABLED"],
        ["WORKSPACE_GOOGLE_MESSAGE_ENABLED", "WORKSPACE_GOOGLE_CONNECTION_ENABLED"],
        ["WORKSPACE_PREP_WORK_ENABLED", "WORKSPACE_PREP_ENABLED"],
        ["WORKSPACE_RESEARCH_IO_ENABLED", "WORKSPACE_RESEARCH_ENABLED"],
        ["INBOX_HANDOFF_ENABLED", "INBOX_WORK_ENABLED"],
        ["VENDOR_IO_ENABLED", "VENDOR_WORK_ENABLED"], ["VENDOR_EVENTS_ENABLED", "VENDOR_WORK_ENABLED"],
        ["FINANCE_IO_ENABLED", "FINANCE_WORK_ENABLED"], ["FINANCE_EVENTS_ENABLED", "FINANCE_WORK_ENABLED"]
      ] : !local.enabled[pair[0]] || local.enabled[pair[1]]])
      error_message = "Dependent workspace features require their underlying reviewed workflow."
    }
    precondition {
      condition     = !local.enabled.WORKSPACE_SCHEDULING_ENABLED || contains(keys(local.public), "SCHEDULING_ORIGIN")
      error_message = "Scheduling requires the configured service origin."
    }
    precondition {
      condition     = !local.enabled.WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED || contains(keys(local.public), "SCHEDULING_ENROLLMENT_PRACTICE_ID")
      error_message = "Scheduling enrollment requires the separately reviewed practice."
    }
    precondition {
      condition = alltrue([for connection in values(local.oauth) : !connection.enabled ||
        (alltrue([for key in connection.public : contains(keys(local.public), key)]) &&
      alltrue([for key in connection.secrets : contains(keys(var.secret_references), key)]))])
      error_message = "Each enabled account connection requires its public client configuration and both credential/custody secret references."
    }
    precondition {
      condition     = !anytrue([for key in ["VENDOR_IO_ENABLED", "VENDOR_EVENTS_ENABLED", "FINANCE_IO_ENABLED", "FINANCE_EVENTS_ENABLED"] : local.enabled[key]]) || var.managed_manifest != null
      error_message = "Managed service execution/events require the exact installed-account manifest."
    }
    precondition {
      condition = (contains(["disabled", "core"], lookup(local.public, "WORKSPACE_CAPTURE_BACKEND", "disabled")) &&
      contains(["disabled", "azure_gpt41"], lookup(local.public, "WORKSPACE_LLM_BACKEND", "disabled")))
      error_message = "Capture/model backends must use supported implementations."
    }
    precondition {
      condition     = lookup(local.public, "WORKSPACE_LLM_BACKEND", "disabled") != "azure_gpt41" || contains(keys(var.secret_references), "WORKSPACE_LLM_API_KEY")
      error_message = "The selected model backend requires its separate credential reference."
    }
    precondition {
      condition     = !anytrue([for key in ["WORKSPACE_CAPTURE_NOTES_ENABLED", "WORKSPACE_CAPTURE_CORRECTIONS_ENABLED", "WORKSPACE_CAPTURE_RECOVERY_ENABLED", "WORKSPACE_CAPTURE_SOURCE_ENABLED", "WORKSPACE_CAPTURE_LONG_VISITS_ENABLED", "WORKSPACE_CORE_RECORD_ENABLED", "WORKSPACE_PREP_ENABLED"] : local.enabled[key]]) || lookup(local.public, "WORKSPACE_CAPTURE_BACKEND", "disabled") == "core"
      error_message = "Capture, preparation and Core record features require the configured Core capture backend."
    }
    precondition {
      condition     = !local.enabled.WORKSPACE_CORE_RECORD_ENABLED || contains(keys(local.public), "CORE_WEB_ORIGIN")
      error_message = "Core record navigation requires its reviewed web origin."
    }
  }
}

output "public_env" {
  value      = local.public_env
  depends_on = [terraform_data.configuration_guard]
}
output "secret_env" {
  value      = local.secret_env
  depends_on = [terraform_data.configuration_guard]
}
output "secret_definitions" {
  value      = local.secret_definitions
  depends_on = [terraform_data.configuration_guard]
}
