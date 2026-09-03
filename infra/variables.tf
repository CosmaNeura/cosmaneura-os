variable "subscription_id" {
  type        = string
  description = "Azure subscription for OS synth only."
  default     = "bab2a709-1fcb-4c87-a9fc-802f7477ec13"
}

variable "location" {
  type        = string
  description = "Azure region for RG and most resources."
  default     = "eastus"
}

variable "postgres_location" {
  type        = string
  description = "Region for PostgreSQL Flexible Server. Defaults to centralus because this sponsorship subscription restricts Flexible Server provisioning in eastus/eastus2 (empty Version set / ParameterOutOfRange)."
  default     = "centralus"
}

variable "postgres_zone" {
  type        = string
  description = "Existing PostgreSQL availability zone, pinned to prevent drift."
  default     = "1"
}

variable "resource_group_name" {
  type        = string
  description = "OS-named resource group (must not collide with Track A)."
  default     = "cosmaneura-os-synth"
}

variable "name_prefix" {
  type        = string
  description = "Short prefix for resource names (alphanumeric where required)."
  default     = "cosmasossynth"
}

variable "postgres_admin_login" {
  type        = string
  description = "Postgres admin login (non-secret)."
  default     = "cosmas_os_admin"
}

variable "postgres_admin_password" {
  type        = string
  description = "Postgres admin password. Supply only at apply via TF_VAR_postgres_admin_password. Never commit."
  sensitive   = true
}

variable "api_image" {
  type        = string
  description = "Digest-pinned Cosmas OS image in the dedicated synth ACR."

  validation {
    condition     = can(regex("^cosmasossynthacrrkpt0e\\.azurecr\\.io/cosmas-os@sha256:[0-9a-f]{64}$", var.api_image))
    error_message = "api_image must be the digest-pinned cosmas-os image in the dedicated synth ACR."
  }
}

variable "worker_image" {
  type        = string
  description = "Digest-pinned Cosmas OS image in the dedicated synth ACR."

  validation {
    condition     = can(regex("^cosmasossynthacrrkpt0e\\.azurecr\\.io/cosmas-os@sha256:[0-9a-f]{64}$", var.worker_image))
    error_message = "worker_image must be the digest-pinned cosmas-os image in the dedicated synth ACR."
  }
}

variable "redis_sku_name" {
  type        = string
  description = "Azure Cache for Redis SKU name."
  default     = "Basic"
}

variable "redis_family" {
  type        = string
  description = "Azure Cache for Redis family."
  default     = "C"
}

variable "redis_capacity" {
  type        = number
  description = "Azure Cache for Redis capacity."
  default     = 0
}

variable "postgres_sku_name" {
  type        = string
  description = "Postgres Flexible Server SKU."
  default     = "B_Standard_B1ms"
}

variable "enable_public_postgres" {
  type        = bool
  description = "Allow public network access on Postgres for tiny synth (tighten before D3)."
  default     = true
}
