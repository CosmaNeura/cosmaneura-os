variable "subscription_id" {
  type        = string
  description = "Actual reviewed Azure subscription; no default account selection."
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be the reviewed subscription UUID."
  }
}
variable "tenant_id" {
  type        = string
  description = "Actual reviewed Azure tenant."
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be the reviewed tenant UUID."
  }
}
variable "location" {
  type    = string
  default = "eastus2"
  validation {
    condition     = var.location == "eastus2"
    error_message = "The VM staging foundation is fixed to East US 2 (eastus2)."
  }
}
variable "resource_name_suffix" {
  type        = string
  description = "Reviewed globally unique suffix for new ACR, vault and storage names."
  validation {
    condition     = can(regex("^[a-z0-9]{6,10}$", var.resource_name_suffix))
    error_message = "resource_name_suffix must be 6–10 lowercase letters/digits."
  }
}
variable "state_namespace" {
  type        = string
  description = "Fixed fresh-local bootstrap namespace; bootstrap_local.py binds the actual local backend path."
  validation {
    condition     = var.state_namespace == "cosmabot-vm/eastus2/lab01/local-initial"
    error_message = "Use the new dedicated cosmabot-vm/eastus2/lab01/local-initial namespace."
  }
}
variable "vnet_address_prefix" {
  type        = string
  description = "Reviewed non-overlapping canonical RFC1918 IPv4 /20 through /24, split into two subnets."
  validation {
    condition = try(
      can(cidrnetmask(var.vnet_address_prefix)) &&
      can(regex("^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.)", var.vnet_address_prefix)) &&
      tonumber(split("/", var.vnet_address_prefix)[1]) >= 20 &&
      tonumber(split("/", var.vnet_address_prefix)[1]) <= 24 &&
    cidrhost(var.vnet_address_prefix, 0) == split("/", var.vnet_address_prefix)[0], false)
    error_message = "Use a canonical, separately reviewed RFC1918 IPv4 /20–/24; confirm it does not overlap existing networks."
  }
}
variable "admin_username" {
  type        = string
  description = "Reviewed break-glass Linux account; no SSH ingress is provisioned."
  validation {
    condition     = can(regex("^[a-z][a-z0-9_-]{3,30}$", var.admin_username)) && !contains(["root", "admin", "administrator"], var.admin_username)
    error_message = "Use a non-root reviewed Linux administrator name."
  }
}
variable "admin_ssh_public_key" {
  type        = string
  description = "Operator-owned SSH PUBLIC key only. Private keys are never inputs."
  validation {
    condition     = can(regex("^ssh-(rsa|ed25519) [A-Za-z0-9+/]+={0,3}( [^\\r\\n]+)?$", trimspace(var.admin_ssh_public_key)))
    error_message = "Supply one operator-owned RSA or Ed25519 public key, never a private key."
  }
}
variable "ubuntu_image_version" {
  type        = string
  description = "Pinned Canonical Ubuntu 22.04 Gen2 image verified in East US 2 on September 25, 2026."
  default     = "22.04.202608060"
  validation {
    condition     = var.ubuntu_image_version == "22.04.202608060"
    error_message = "Use the reviewed immutable Ubuntu image version 22.04.202608060."
  }
}
variable "release_operator_object_id" {
  type        = string
  description = "Reviewed off-VM principal for ACR publication and Key Vault secret provisioning; never assigned to this VM."
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.release_operator_object_id))
    error_message = "release_operator_object_id must be the reviewed off-VM principal UUID."
  }
}
variable "alert_contact_email" {
  type        = string
  description = "Actual approved recipient for infrastructure-only health alerts."
  validation {
    condition     = can(regex("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$", var.alert_contact_email))
    error_message = "Supply the approved alert recipient's email address."
  }
}
