variable "enable_azure_openai" {
  type        = bool
  description = "OFF by default. Creating Azure OpenAI requires a separate John yes beyond production hosting approval."
  default     = false
}

module "azure_openai" {
  source              = "./modules/azure_openai"
  enabled             = var.enable_azure_openai
  resource_group_name = azurerm_resource_group.production.name
  location            = var.location
  name                = var.enable_azure_openai ? "oai-cbot-prd-${var.resource_name_suffix}" : ""
  tags                = local.tags
}
