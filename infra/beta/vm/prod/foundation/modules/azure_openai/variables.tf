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

variable "tags" {
  type    = map(string)
  default = {}
}
