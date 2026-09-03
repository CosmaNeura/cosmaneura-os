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
  description = "Azure tenant recorded by the beta bootstrap root."

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be an explicit Azure tenant UUID."
  }
}

variable "state_vnet_id" {
  type        = string
  description = "Exact protected runner/state VNet ID emitted by bootstrap and forced by the deployment wrappers."

  validation {
    condition     = can(regex("^/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/rg-cosmas-os-beta-state-[a-z0-9-]+/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-[a-z0-9-]+$", var.state_vnet_id))
    error_message = "state_vnet_id must be the exact D3 bootstrap state VNet resource ID."
  }
}

variable "state_blob_private_dns_zone_id" {
  type        = string
  description = "Exact private Blob DNS zone ID emitted by bootstrap; shared by state and workload Blob private endpoints."

  validation {
    condition     = can(regex("^/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/rg-cosmas-os-beta-state-[a-z0-9-]+/providers/Microsoft.Network/privateDnsZones/privatelink\\.blob\\.core\\.windows\\.net$", var.state_blob_private_dns_zone_id))
    error_message = "state_blob_private_dns_zone_id must be the exact bootstrap Blob private DNS zone resource ID."
  }
}

variable "beta_id" {
  type        = string
  description = "Opaque, non-clinic beta identifier shared with the bootstrap root."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,8}[a-z0-9]$", var.beta_id)) && !strcontains(var.beta_id, "--")
    error_message = "beta_id must be 3-10 lowercase letters, numbers, or single internal hyphens and must not contain a clinic name."
  }
}

variable "location" {
  type        = string
  description = "Single region for ACA and private data services. Central US is provisional until region/quota evidence is recorded."
  default     = "centralus"
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

variable "registry_network_posture" {
  type        = string
  description = "Required ACR network choice. private provisions Premium ACR with Private Link; synthetic_public_exception permits Basic/public ACR only for a reviewed synthetic lab."

  validation {
    condition     = contains(["private", "synthetic_public_exception"], var.registry_network_posture)
    error_message = "registry_network_posture must be private or synthetic_public_exception."
  }
}

variable "synthetic_public_registry_exception_reference" {
  type        = string
  description = "Human-controlled review reference accepting authenticated public ACR exposure for a synthetic-only lab. Required only when registry_network_posture is synthetic_public_exception."
  sensitive   = true
  default     = null
  nullable    = true

  validation {
    condition     = var.synthetic_public_registry_exception_reference == null || try(length(trimspace(var.synthetic_public_registry_exception_reference)), 0) >= 3
    error_message = "synthetic_public_registry_exception_reference must be null or contain at least three non-whitespace characters."
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

variable "clerk_org_id" {
  type        = string
  description = "Production Clerk Organization ID mapped one-to-one to box_id. May remain null for the foundation and is required before workloads."
  sensitive   = true
  default     = null
  nullable    = true

  validation {
    condition     = var.clerk_org_id == null || (startswith(var.clerk_org_id, "org_") && length(trimspace(var.clerk_org_id)) > 4)
    error_message = "clerk_org_id must be null for the foundation or an explicit Clerk Organization ID."
  }
}

variable "clerk_issuer_url" {
  type        = string
  description = "HTTPS issuer for the approved production Clerk instance. May remain null for the foundation and is required before workloads."
  default     = null
  nullable    = true

  validation {
    condition     = var.clerk_issuer_url == null || can(regex("^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?/?$", var.clerk_issuer_url))
    error_message = "clerk_issuer_url must be null for the foundation or one exact HTTPS origin without credentials, path, query, or fragment."
  }
}

variable "clerk_jwks_url" {
  type        = string
  description = "HTTPS JWKS endpoint for the approved production Clerk instance. May remain null for the foundation and is required before workloads."
  default     = null
  nullable    = true

  validation {
    condition = var.clerk_jwks_url == null || (
      var.clerk_issuer_url != null &&
      can(regex("^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?/[^?#]+$", var.clerk_jwks_url)) &&
      startswith(var.clerk_jwks_url, "${trimsuffix(var.clerk_issuer_url, "/")}/")
    )
    error_message = "clerk_jwks_url must be null for the foundation or a credential-free HTTPS URL on the exact clerk_issuer_url origin, without query or fragment."
  }
}

variable "clerk_audience" {
  type        = string
  description = "Audience required on production Clerk session tokens. May remain null for the foundation and is required before workloads."
  default     = null
  nullable    = true

  validation {
    condition     = var.clerk_audience == null || length(trimspace(var.clerk_audience)) >= 3
    error_message = "clerk_audience must be null for the foundation or explicit."
  }
}

variable "web_origin" {
  type        = string
  description = "Human-approved exact HTTPS origin for the D3 web app. It is optional for the foundation and must equal either the derived ACA origin or https://web_custom_domain before workloads are enabled."
  default     = null
  nullable    = true

  validation {
    condition     = var.web_origin == null || can(regex("^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$", var.web_origin))
    error_message = "web_origin must be null or one exact HTTPS origin without wildcard, credentials, path, query, or fragment."
  }
}

variable "web_custom_domain" {
  type        = string
  description = "Optional new lowercase hostname for the D3 web app. Existing app/chat and staging-app/staging-chat cosmaneura.com hostnames are explicitly reserved and unmanaged here."
  default     = null
  nullable    = true

  validation {
    condition = var.web_custom_domain == null || try(
      var.web_custom_domain == lower(trimspace(var.web_custom_domain)) &&
      length(var.web_custom_domain) <= 253 &&
      can(regex("^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$", var.web_custom_domain)) &&
      !contains(["app.cosmaneura.com", "staging-app.cosmaneura.com", "chat.cosmaneura.com", "staging-chat.cosmaneura.com"], var.web_custom_domain),
      false,
    )
    error_message = "web_custom_domain must be a valid lowercase hostname and must not collide with app.cosmaneura.com, staging-app.cosmaneura.com, chat.cosmaneura.com, or staging-chat.cosmaneura.com."
  }
}

variable "web_custom_domain_dns_ready" {
  type        = bool
  description = "Explicit gate set true only after the exact external CNAME and asuid TXT records have been independently verified; Terraform does not manage DNS."
  default     = false
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

variable "clinic_approval_reference" {
  type        = string
  description = "Human-controlled reference recording the named clinic's approval for this isolated beta. Required only for authorized_beta."
  sensitive   = true
  default     = null
  nullable    = true

  validation {
    condition     = var.clinic_approval_reference == null || try(length(trimspace(var.clinic_approval_reference)), 0) >= 3
    error_message = "clinic_approval_reference must be null or contain at least three non-whitespace characters."
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
  description = "Human-controlled approval/evidence reference for this production-like D3 deployment."
  sensitive   = true
}

variable "runner_network_evidence_reference" {
  type        = string
  description = "Human-reviewed design evidence for the protected runner, private routing, and DNS boundary. Live reachability is evidenced separately after the foundation exists."
  sensitive   = true
}

variable "runner_live_network_evidence_reference" {
  type        = string
  description = "Live evidence that the protected runner resolves and reaches the exact private workload endpoints. Required before database preparation or workloads."
  sensitive   = true
  default     = null
  nullable    = true

  validation {
    condition     = var.runner_live_network_evidence_reference == null || try(length(trimspace(var.runner_live_network_evidence_reference)), 0) >= 3
    error_message = "runner_live_network_evidence_reference must be null before the foundation exists or contain at least three non-whitespace characters."
  }
}

variable "region_evidence_reference" {
  type        = string
  description = "Human-reviewed region, residency, quota, and SKU evidence reference."
  sensitive   = true
}

variable "auth_boundary_evidence_reference" {
  type        = string
  description = "Test evidence that Clerk identity determines Box and Principal and caller-supplied identity headers are rejected."
  sensitive   = true
}

variable "blob_adapter_evidence_reference" {
  type        = string
  description = "Test evidence that durable artifacts use the dedicated Azure Blob container through managed identity."
  sensitive   = true
}

variable "phi_logging_evidence_reference" {
  type        = string
  description = "Review evidence that ordinary telemetry excludes PHI, credentials, request bodies, and signed URLs."
  sensitive   = true
}

variable "backup_restore_evidence_reference" {
  type        = string
  description = "Human-approved backup/restore and retention runbook reference."
  sensitive   = true
}

variable "capability_manifest_reference" {
  type        = string
  description = "Reviewed D3 capability manifest reference; all external connector rungs remain dark."
  sensitive   = true
}

variable "broker_service_evidence_reference" {
  type        = string
  description = "Human review of the selected Redis service availability, retirement path, private networking, and monthly cost."
  sensitive   = true
}

variable "enabled_connectors" {
  type        = set(string)
  description = "D3 connector allow-list. It is intentionally forced empty until a separate D5 gate."
  default     = []

  validation {
    condition     = length(var.enabled_connectors) == 0
    error_message = "D3 preparation requires every Athena, Acuity, messaging, payment, Teams, and Track A connector to remain dark."
  }
}

variable "image_digest" {
  type        = string
  description = "SHA-256 digest only (without sha256:) for the reviewed live API/worker image. Required when deploy_workloads is true and promoted only after matching database-preparation evidence."
  default     = null
  nullable    = true

  validation {
    condition     = var.image_digest == null || can(regex("^[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be null or exactly 64 lowercase hexadecimal characters."
  }
}

variable "database_preparation_image_digest" {
  type        = string
  description = "SHA-256 digest only (without sha256:) for the database-preparation candidate image. It may advance independently while the prior API/worker digest remains live."
  default     = null
  nullable    = true

  validation {
    condition     = var.database_preparation_image_digest == null || can(regex("^[0-9a-f]{64}$", var.database_preparation_image_digest))
    error_message = "database_preparation_image_digest must be null or exactly 64 lowercase hexadecimal characters."
  }
}

variable "web_image_digest" {
  type        = string
  description = "SHA-256 digest only (without sha256:) for the reviewed production-configured D3 web image. Required when deploy_workloads is true."
  default     = null
  nullable    = true

  validation {
    condition     = var.web_image_digest == null || can(regex("^[0-9a-f]{64}$", var.web_image_digest))
    error_message = "web_image_digest must be null or exactly 64 lowercase hexadecimal characters."
  }
}

variable "web_release_evidence_reference" {
  type        = string
  description = "Human review reference tying the web digest to the source SHA, production Clerk publishable key, derived API origin, static scan, and rollback record. Required when workloads are enabled."
  sensitive   = true
  default     = null
  nullable    = true
}

variable "deploy_workloads" {
  type        = bool
  description = "Create the web, API, and worker only after the foundation ACR contains both immutable image digests and migrations and release evidence are approved."
  default     = false
}

variable "enable_database_preparation_job" {
  type        = bool
  description = "Create the manual, unscheduled in-network database preparation job. The foundation leaves this false and therefore carries no workload database URL."
  default     = false
}

variable "postgres_admin_login" {
  type        = string
  description = "Dedicated beta PostgreSQL administrator login."
  default     = "cosmas_beta_admin"

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9_]{2,62}$", var.postgres_admin_login))
    error_message = "postgres_admin_login must be a valid dedicated PostgreSQL role name."
  }
}

variable "postgres_admin_password" {
  type        = string
  description = "Human-supplied beta PostgreSQL password. It enters protected remote state and must never reach source, logs, or coding agents."
  sensitive   = true

  validation {
    condition     = length(var.postgres_admin_password) >= 24
    error_message = "postgres_admin_password must contain at least 24 characters."
  }
}

variable "runtime_database_url" {
  type        = string
  description = "Human-supplied verify-full DATABASE_URL for a non-admin operational role. It is required for the manual database-preparation job and for workloads."
  sensitive   = true
  default     = null
  nullable    = true

  validation {
    condition = var.runtime_database_url == null || (
      can(regex("^postgresql\\+psycopg://[^[:space:]@/]+:[^[:space:]@/]+@[^[:space:]/?#]+(:[0-9]{1,5})?/cosmas_os\\?sslmode=verify-full&sslrootcert=system$", var.runtime_database_url)) &&
      !startswith(lower(var.runtime_database_url), "postgresql+psycopg://${lower(var.postgres_admin_login)}:")
    )
    error_message = "runtime_database_url must target cosmas_os through psycopg with sslmode=verify-full, sslrootcert=system, and must not use postgres_admin_login."
  }
}

variable "database_preparation_attestation" {
  type = object({
    image_digest       = string
    schema_revision    = string
    evidence_sha256    = string
    execution_id       = string
    box_id             = string
    database_server_id = string
  })
  description = "Structured attestation from the completed manual database-preparation execution. It binds the live denial probes and schema head to the exact application image before workloads."
  sensitive   = true
  default     = null
  nullable    = true

  validation {
    condition = var.database_preparation_attestation == null || try(
      can(regex("^[0-9a-f]{64}$", var.database_preparation_attestation.image_digest)) &&
      var.database_preparation_attestation.schema_revision == "0002_external_identities" &&
      can(regex("^[0-9a-f]{64}$", var.database_preparation_attestation.evidence_sha256)) &&
      can(regex("^/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/rg-cosmas-os-beta-[a-z0-9-]+/providers/Microsoft.App/jobs/caj-dbprep-cosmas-beta-[a-z0-9-]+/executions/[A-Za-z0-9][A-Za-z0-9._-]{2,255}$", var.database_preparation_attestation.execution_id)) &&
      can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$", var.database_preparation_attestation.box_id)) &&
      can(regex("^/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/rg-cosmas-os-beta-[a-z0-9-]+/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-cosmas-beta-[a-z0-9-]+$", var.database_preparation_attestation.database_server_id)),
      false,
    )
    error_message = "database_preparation_attestation must contain the exact Box, database server, job execution, 64-hex image/evidence digests, and expected D3 schema revision."
  }
}

variable "postgres_sku_name" {
  type        = string
  description = "Cost-controlled PostgreSQL SKU selected from current calculator/quota evidence."
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  type        = number
  description = "PostgreSQL allocated storage in MiB."
  default     = 32768

  validation {
    condition     = var.postgres_storage_mb >= 32768
    error_message = "postgres_storage_mb must be at least 32768 MiB."
  }
}

variable "postgres_backup_retention_days" {
  type        = number
  description = "PostgreSQL point-in-time backup retention. Must agree with the clinic retention policy."
  default     = 7

  validation {
    condition     = var.postgres_backup_retention_days >= 7 && var.postgres_backup_retention_days <= 35
    error_message = "PostgreSQL backup retention must be between 7 and 35 days."
  }
}

variable "postgres_geo_redundant_backup_enabled" {
  type        = bool
  description = "Cost/resilience choice requiring explicit calculator and residency review."
  default     = false
}

variable "postgres_zone" {
  type        = string
  description = "Optional availability zone verified for the selected region; null lets Azure select."
  default     = null
  nullable    = true
}

variable "redis_sku_name" {
  type        = string
  description = "Private Azure Managed Redis SKU for the Celery broker. Balanced_B0 is the reviewed D3 minimum."
  default     = "Balanced_B0"

  validation {
    condition     = var.redis_sku_name == "Balanced_B0"
    error_message = "D3 requires the reviewed Azure Managed Redis Balanced_B0 broker SKU."
  }
}

variable "storage_replication_type" {
  type        = string
  description = "Blob durability/cost selection."
  default     = "LRS"

  validation {
    condition     = contains(["LRS", "ZRS", "GRS", "GZRS"], var.storage_replication_type)
    error_message = "storage_replication_type must be LRS, ZRS, GRS, or GZRS."
  }
}

variable "log_retention_days" {
  type        = number
  description = "PHI-safe Log Analytics retention."
  default     = 30

  validation {
    condition     = var.log_retention_days >= 30 && var.log_retention_days <= 730
    error_message = "log_retention_days must be between 30 and 730."
  }
}

variable "log_daily_quota_gb" {
  type        = number
  description = "Daily Log Analytics ingestion cap used as a cost guardrail."
  default     = 1

  validation {
    condition     = var.log_daily_quota_gb > 0
    error_message = "log_daily_quota_gb must be positive."
  }
}

variable "alert_contact_email" {
  type        = string
  description = "Human-owned address for PHI-safe D3 workload-health notifications. Required only when workloads are enabled."
  sensitive   = true
  default     = null
  nullable    = true

  validation {
    condition     = var.alert_contact_email == null || can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.alert_contact_email))
    error_message = "alert_contact_email must be null before workloads or one valid human-owned email address."
  }
}

variable "api_cpu" {
  type        = number
  description = "API vCPU allocation."
  default     = 0.5
}

variable "api_memory" {
  type        = string
  description = "API memory allocation."
  default     = "1Gi"
}

variable "api_min_replicas" {
  type        = number
  description = "API minimum replicas; one avoids beta login cold starts."
  default     = 1
}

variable "api_max_replicas" {
  type        = number
  description = "API maximum replicas."
  default     = 2
}

variable "web_cpu" {
  type        = number
  description = "Static web host vCPU allocation."
  default     = 0.25
}

variable "web_memory" {
  type        = string
  description = "Static web host memory allocation."
  default     = "0.5Gi"
}

variable "web_min_replicas" {
  type        = number
  description = "Static web host minimum replicas; zero permits scale-to-zero for the synthetic lab."
  default     = 0
}

variable "web_max_replicas" {
  type        = number
  description = "Static web host maximum replicas."
  default     = 1
}

variable "worker_cpu" {
  type        = number
  description = "Worker vCPU allocation."
  default     = 0.5
}

variable "worker_memory" {
  type        = string
  description = "Worker memory allocation."
  default     = "1Gi"
}

variable "worker_min_replicas" {
  type        = number
  description = "Worker minimum replicas for reliable beta processing."
  default     = 1

  validation {
    condition     = var.worker_min_replicas == 1
    error_message = "D3 worker_min_replicas is fixed at 1 so fake-only NotifyPort work cannot execute concurrently."
  }
}

variable "worker_max_replicas" {
  type        = number
  description = "Worker maximum replicas."
  default     = 1

  validation {
    condition     = var.worker_max_replicas == 1
    error_message = "D3 worker_max_replicas is fixed at 1 so fake-only NotifyPort work cannot execute concurrently."
  }
}

variable "vnet_address_space" {
  type        = list(string)
  description = "Dedicated beta VNet address space; it must not overlap D2, Track A, or the deploy runner network."
  default     = ["10.42.0.0/16"]
}

variable "aca_subnet_prefixes" {
  type        = list(string)
  description = "Dedicated Container Apps infrastructure subnet CIDRs."
  default     = ["10.42.0.0/23"]
}

variable "postgres_subnet_prefixes" {
  type        = list(string)
  description = "Dedicated PostgreSQL delegated subnet CIDRs."
  default     = ["10.42.2.0/28"]
}

variable "private_endpoint_subnet_prefixes" {
  type        = list(string)
  description = "Dedicated private endpoint subnet CIDRs."
  default     = ["10.42.2.32/27"]
}
