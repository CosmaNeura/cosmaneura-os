variable "subscription_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "Use the explicitly reviewed subscription UUID."
  }
}
variable "tenant_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "Use the explicitly reviewed tenant UUID."
  }
}
variable "environment" {
  type    = string
  default = "staging"
  validation {
    condition     = var.environment == "staging"
    error_message = "This foundation is staging only; production requires a separate reviewed definition."
  }
}
variable "location" {
  type    = string
  default = "eastus2"
  validation {
    condition     = var.location == "eastus2"
    error_message = "This bounded staging foundation is fixed to East US 2."
  }
}
variable "resource_name_suffix" {
  type        = string
  description = "Fresh globally unique 6–8 character suffix; do not reuse the existing staging VM namespace."
  validation {
    condition     = can(regex("^[a-z0-9]{6,8}$", var.resource_name_suffix))
    error_message = "Use 6–8 lowercase letters/digits for a fresh enrollment namespace."
  }
}
variable "state_namespace" {
  type    = string
  default = "cosmabot-enrollment/staging/foundation-local-v1"
  validation {
    condition     = var.state_namespace == "cosmabot-enrollment/staging/foundation-local-v1"
    error_message = "Do not reuse another product's backend or state namespace."
  }
}
variable "bootstrap_key_file" {
  type        = string
  description = "Private 0600 encryption.passphrase file created by prepare.py, never its value."
  validation {
    condition     = startswith(var.bootstrap_key_file, "/") && endswith(var.bootstrap_key_file, "/encryption.passphrase")
    error_message = "Use the fresh protected bootstrap directory's encryption.passphrase."
  }
}
variable "postgres_admin_password" {
  type        = string
  sensitive   = true
  ephemeral   = true
  description = "Write-only server bootstrap password, supplied through the protected apply process; never stored in a plan/state."
  validation {
    condition     = length(var.postgres_admin_password) >= 32 && length(var.postgres_admin_password) <= 128
    error_message = "Use a newly generated 32–128 character bootstrap password."
  }
}
variable "postgres_admin_password_version" {
  type    = number
  default = 1
  validation {
    condition     = var.postgres_admin_password_version >= 1 && floor(var.postgres_admin_password_version) == var.postgres_admin_password_version
    error_message = "Increment the explicit write-only version for a reviewed password rotation."
  }
}
variable "vnet_address_prefix" {
  type        = string
  description = "Separately reviewed non-overlapping canonical RFC1918 IPv4 /20. No peering is provisioned."
  validation {
    condition = try(
      can(cidrnetmask(var.vnet_address_prefix)) &&
      can(regex("^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.)", var.vnet_address_prefix)) &&
      split("/", var.vnet_address_prefix)[1] == "20" &&
    cidrhost(var.vnet_address_prefix, 0) == split("/", var.vnet_address_prefix)[0], false)
    error_message = "Use a canonical private IPv4 /20 after checking existing Azure address spaces."
  }
}
variable "state_operator_ipv4" {
  type        = string
  description = "Exact reviewed public operator IPv4 address (one /32); private database/vault endpoints remain closed."
  validation {
    condition = try(
      can(cidrnetmask("${var.state_operator_ipv4}/32")) &&
      !can(regex("^(0\\.|10\\.|127\\.|169\\.254\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.|22[4-9]\\.|23[0-9]\\.)", var.state_operator_ipv4)) &&
      !strcontains(var.state_operator_ipv4, "/") && tonumber(split(".", var.state_operator_ipv4)[0]) < 224 &&
    cidrhost("${var.state_operator_ipv4}/32", 0) == var.state_operator_ipv4, false)
    error_message = "Allowlist one reviewed public operator IPv4 address, not a network or private address."
  }
}
variable "release_operator_object_id" {
  type        = string
  description = "Reviewed human/deployer principal. Scoped publication/state access only; Azure deployment/RunCommand permissions are separately held."
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.release_operator_object_id))
    error_message = "Use the reviewed release operator object UUID."
  }
}
