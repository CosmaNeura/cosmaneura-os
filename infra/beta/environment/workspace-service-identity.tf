variable "workspace_expected_runtime_client_id" {
  description = "Public managed-identity client ID recorded in Core's allowed OS caller. Null preserves independently configured legacy deployments."
  type        = string
  default     = null
  validation {
    condition     = var.workspace_expected_runtime_client_id == null || can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.workspace_expected_runtime_client_id))
    error_message = "Expected runtime identity must be null or a canonical client UUID."
  }
}
