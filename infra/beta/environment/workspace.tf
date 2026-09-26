variable "workspace_hosted_enabled" {
  type        = bool
  default     = false
  description = "Enable the authenticated standalone CosmaBot workspace in the beta image."
}

variable "workspace_apple_enabled" {
  type        = bool
  default     = false
  description = "Admit the exact Capacitor origin for separately configured beta iPhone clients."
}

variable "workspace_desktop_enabled" {
  type        = bool
  default     = false
  description = "Admit the exact native desktop authorized party. Bearer tokens remain native."
}

locals {
  workspace_client_origins = concat([local.web_origin],
    var.workspace_hosted_enabled && var.workspace_apple_enabled ? ["capacitor://localhost"] : [],
  var.workspace_hosted_enabled && var.workspace_desktop_enabled ? ["app://cosmas"] : [])
  workspace_runtime_env = var.workspace_hosted_enabled ? merge({
    WORKSPACE_ENABLED                          = "true"
    WORKSPACE_AUTHENTICATED_ENABLED            = "true"
    WORKSPACE_HOSTED_ENABLED                   = "true"
    WORKSPACE_DRAFT_RECOVERY_REQUIRED          = "true"
    WORKSPACE_TEAM_SETUP_ENABLED               = "true"
    WORKSPACE_AI_ACTIVITY_ENABLED              = "true"
    WORKSPACE_ROUTINES_ENABLED                 = "true"
    WORKSPACE_APPLE_HOSTED_TRANSPORT_ENABLED   = tostring(var.workspace_apple_enabled)
    WORKSPACE_DESKTOP_HOSTED_TRANSPORT_ENABLED = tostring(var.workspace_desktop_enabled)
  }, module.workspace_runtime.public_env) : {}
}

resource "terraform_data" "workspace_profile_guard" {
  input = local.workspace_runtime_env
  lifecycle {
    precondition {
      condition     = var.workspace_expected_runtime_client_id == null || var.workspace_expected_runtime_client_id == azurerm_user_assigned_identity.runtime.client_id
      error_message = "Core's selected OS caller must be the managed identity actually assigned to this runtime."
    }
    precondition {
      condition     = var.workspace_hosted_enabled || (!var.workspace_apple_enabled && !var.workspace_desktop_enabled)
      error_message = "Native beta origins require the hosted workspace."
    }
    precondition {
      condition = var.deployment_mode == "synthetic_lab" || (!var.workspace_apple_enabled && !var.workspace_desktop_enabled) || (
        local.workspace_identity_valid && local.workspace_native_release_valid
      )
      error_message = "Authorized native clients require the matching operational identity and separately accepted desktop/iPhone release evidence."
    }
    precondition {
      condition     = var.workspace_operational_identity == null || local.workspace_identity_valid
      error_message = "Operational client identity must match this API origin and the Clerk issuer, fixed JWKS, organization, audience and production public key."
    }
    precondition {
      condition     = var.workspace_native_release == null || (local.workspace_identity_valid && local.workspace_native_release_valid)
      error_message = "Native release evidence must bind this public identity and both distinct client archives to an explicit acceptance reference."
    }
  }
}
