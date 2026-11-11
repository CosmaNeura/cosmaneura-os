variable "enabled" {
  type        = bool
  description = "When false, this module creates no Azure OpenAI resources. Requires a separate John yes to enable."
  default     = false
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "name" {
  type        = string
  description = "Cognitive account name when enabled; ignored when disabled."
  default     = ""
}

variable "subnet_id" {
  type        = string
  description = "Private-endpoints subnet for the OpenAI private endpoint when enabled."
}

variable "virtual_network_id" {
  type        = string
  description = "Production VNet id for the OpenAI private DNS zone link when enabled."
}

variable "runtime_principal_id" {
  type        = string
  description = "VM runtime user-assigned identity principal for Cognitive Services OpenAI User."
}

variable "tags" {
  type    = map(string)
  default = {}
}
