variable "subscription_id" {
  type        = string
  description = "Azure subscription selected by the owner for the isolated beta. No D2 or Track A default is permitted."

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be an explicit Azure subscription UUID."
  }
}

variable "tenant_id" {
  type        = string
  description = "Azure tenant that owns the isolated beta subscription and deploy identity."

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be an explicit Azure tenant UUID."
  }
}

variable "beta_id" {
  type        = string
  description = "Opaque, non-clinic beta identifier used in Azure resource names."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,8}[a-z0-9]$", var.beta_id)) && !strcontains(var.beta_id, "--")
    error_message = "beta_id must be 3-10 lowercase letters, numbers, or single internal hyphens and must not contain a clinic name."
  }
}

variable "location" {
  type        = string
  description = "Locked deployment region for the isolated beta. The reviewed D3 boundary is Central US."
  default     = "centralus"

  validation {
    condition     = var.location == "centralus"
    error_message = "D3 bootstrap location is locked to centralus."
  }
}

variable "deployment_mode" {
  type        = string
  description = "Explicit D3 data-classification gate. synthetic_lab permits invented data only; authorized_beta is PHI-capable only with the clinic, BAA, and PHI authorization evidence below."
  default     = "synthetic_lab"

  validation {
    condition     = contains(["synthetic_lab", "authorized_beta"], var.deployment_mode)
    error_message = "deployment_mode must be synthetic_lab or authorized_beta."
  }
}

variable "clinic_legal_name" {
  type        = string
  description = "Owner-supplied legal practice or covered-entity name. Required only for authorized_beta and never used in Azure names or tags."
  sensitive   = true
  default     = null
  nullable    = true

  validation {
    condition     = var.clinic_legal_name == null || try(length(trimspace(var.clinic_legal_name)), 0) >= 3
    error_message = "clinic_legal_name must be null or contain at least three non-whitespace characters."
  }
}

variable "box_id" {
  type        = string
  description = "Owner-approved UUID for the deployment's one dedicated logical Box; required in both modes."

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$", var.box_id))
    error_message = "box_id must be an explicit UUID."
  }
}

variable "baa_evidence_reference" {
  type        = string
  description = "Human-controlled reference proving applicable Azure, Clerk, and enabled-service BAA prerequisites. Required only for authorized_beta."
  sensitive   = true
  default     = null
  nullable    = true

  validation {
    condition     = var.baa_evidence_reference == null || try(length(trimspace(var.baa_evidence_reference)), 0) >= 3
    error_message = "baa_evidence_reference must be null or contain at least three non-whitespace characters."
  }
}

variable "phi_authorization_reference" {
  type        = string
  description = "Human-controlled reference to the separate PHI release authorization. Required only for authorized_beta."
  sensitive   = true
  default     = null
  nullable    = true

  validation {
    condition     = var.phi_authorization_reference == null || try(length(trimspace(var.phi_authorization_reference)), 0) >= 3
    error_message = "phi_authorization_reference must be null or contain at least three non-whitespace characters."
  }
}

variable "human_deploy_evidence_reference" {
  type        = string
  description = "Human-controlled approval/evidence reference for the production-like D3 deployment path."
  sensitive   = true
}

variable "region_evidence_reference" {
  type        = string
  description = "Human-reviewed region, SKU availability, residency, and quota evidence reference."
  sensitive   = true
}

variable "runner_network_evidence_reference" {
  type        = string
  description = "Human-reviewed design evidence for the no-public-IP runner, private state endpoint, DNS, NSG, and NAT boundary. Live reachability is proved after bootstrap."
  sensitive   = true
}

variable "state_vnet_address_space" {
  type        = list(string)
  description = "Address space for the isolated Terraform-state VNet."
  default     = ["10.254.0.0/24"]
}

variable "state_private_endpoint_subnet_prefixes" {
  type        = list(string)
  description = "CIDRs for the Terraform-state private endpoint subnet."
  default     = ["10.254.0.0/27"]
}

variable "state_runner_subnet_prefixes" {
  type        = list(string)
  description = "Dedicated CIDR for the no-public-IP human deployment runner. Must not overlap the state private-endpoint subnet."
  default     = ["10.254.0.32/27"]

  validation {
    condition     = length(var.state_runner_subnet_prefixes) == 1 && can(cidrhost(var.state_runner_subnet_prefixes[0], 1))
    error_message = "state_runner_subnet_prefixes must contain exactly one valid CIDR."
  }
}

variable "runner_admin_username" {
  type        = string
  description = "Local break-glass username. The VM has no public IP or inbound NSG path and accepts public-key authentication only."
  default     = "cosmasdeploy"

  validation {
    condition     = can(regex("^[a-z][a-z0-9_-]{2,30}$", var.runner_admin_username))
    error_message = "runner_admin_username must be a 3-31 character lowercase Linux username."
  }
}

variable "runner_admin_ssh_public_key" {
  type        = string
  description = "Human-controlled Ed25519 public key for break-glass recovery. No private key or password is accepted or stored."
  sensitive   = true

  validation {
    condition     = startswith(trimspace(var.runner_admin_ssh_public_key), "ssh-ed25519 ") && length(trimspace(var.runner_admin_ssh_public_key)) >= 75
    error_message = "runner_admin_ssh_public_key must be an explicit Ed25519 public key."
  }
}

variable "runner_vm_size" {
  type        = string
  description = "Trusted Launch-capable VM size for the protected human deployment runner."
  default     = "Standard_B2s"

  validation {
    condition     = var.runner_vm_size == "Standard_B2s"
    error_message = "The reviewed D3 protected runner size is fixed to Standard_B2s."
  }
}

variable "runner_image_version" {
  type        = string
  description = "Human-reviewed immutable Canonical Ubuntu 22.04 Gen2 marketplace image version for the protected runner; latest is forbidden."

  validation {
    condition     = var.runner_image_version == "22.04.202608060"
    error_message = "runner_image_version must remain the reviewed immutable Ubuntu Jammy Gen2 version 22.04.202608060."
  }
}

variable "monthly_budget_amount" {
  type        = number
  description = "Aggregate notification threshold across the exact state/runner and workload resource groups; this is not a hard spending cap."
  default     = 350

  validation {
    condition     = var.monthly_budget_amount == 350
    error_message = "monthly_budget_amount must remain the reviewed 350 aggregate alert threshold for both D3 resource groups."
  }
}

variable "budget_start_date" {
  type        = string
  description = "UTC first-of-month start for the subscription budget."

  validation {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-01T00:00:00Z$", var.budget_start_date))
    error_message = "budget_start_date must be the first day of a month in UTC."
  }
}

variable "budget_contact_emails" {
  type        = set(string)
  description = "Human-owned notification recipients for the aggregate D3 budget alert."
  sensitive   = true

  validation {
    condition     = length(var.budget_contact_emails) > 0 && alltrue([for email in var.budget_contact_emails : can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", email))])
    error_message = "At least one syntactically valid budget contact email is required."
  }
}
