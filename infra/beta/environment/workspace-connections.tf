variable "workspace_features" {
  type    = map(bool)
  default = {}
}
variable "workspace_public_configuration" {
  type    = map(string)
  default = {}
}
variable "workspace_secret_references" {
  type    = map(object({ secret_name = string, version = string }))
  default = {}
}
variable "workspace_managed_manifest" {
  type    = object({ secret_name = string, version = string, sha256 = string })
  default = null
}

module "workspace_runtime" {
  source                  = "./modules/workspace-runtime"
  hosted_enabled          = var.workspace_hosted_enabled
  features                = var.workspace_features
  public_configuration    = var.workspace_public_configuration
  secret_references       = var.workspace_secret_references
  managed_manifest        = var.workspace_managed_manifest
  api_origin              = local.api_origin
  web_origin              = local.web_origin
  key_vault_uri           = azurerm_key_vault.beta.vault_uri
  core_identity_client_id = azurerm_user_assigned_identity.runtime.client_id
}
