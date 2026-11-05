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
  type = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "Allocator host identity belongs to staging or production enrollment only."
  }
}

variable "resource_group_name" {
  type = string
  validation {
    condition     = can(regex("^rg-cosmabot-enrollment-(staging|production)-[a-z0-9-]{3,32}$", var.resource_group_name))
    error_message = "Use the dedicated enrollment resource group; never a clinical or Core group."
  }
}

variable "location" {
  type = string
  validation {
    condition     = contains(["centralus", "eastus2"], var.location)
    error_message = "Allocator host resources stay in Central US or East US 2."
  }
}

variable "vnet_name" {
  type        = string
  description = "Existing enrollment foundation VNet name inside the dedicated resource group."
  validation {
    condition     = can(regex("^vnet-cosmabot-enrollment-(staging|production)-[a-z0-9-]{3,32}$", var.vnet_name))
    error_message = "Attach only to the dedicated enrollment foundation VNet."
  }
}

variable "host_subnet_prefix" {
  type        = string
  description = "Non-delegated /26 inside the enrollment VNet for the private allocator host. Unused while create_resources is false."
  validation {
    condition = try(
      can(cidrnetmask(var.host_subnet_prefix)) &&
      split("/", var.host_subnet_prefix)[1] == "26",
      false
    )
    error_message = "Provide an explicit /26 host subnet prefix; the worker measures capacity and never enlarges subnets."
  }
}

variable "create_resources" {
  type        = bool
  default     = false
  description = "Keep false so plans create no Azure resources and bill nothing. Set true only after founder-authorized apply."
}

variable "hold_release_sha256" {
  type        = string
  default     = ""
  description = "Empty while held. When create_resources is true, must be the 64-hex SHA-256 of the protected hold-release receipt."
  validation {
    condition     = var.hold_release_sha256 == "" || can(regex("^[0-9a-f]{64}$", var.hold_release_sha256))
    error_message = "hold_release_sha256 must be empty while held or an exact 64-hex digest."
  }
}
