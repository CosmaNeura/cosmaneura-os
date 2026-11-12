variable "enable_azure_openai" {
  type        = bool
  description = "Module safety default is false. Leave false for the default plan (no prod LLM endpoint). Set true in reviewed inputs to create the prod OpenAI account, gpt-4.1-dzus, private endpoint, and privatelink DNS in this first-apply plan."
  default     = false
}

module "azure_openai" {
  source              = "./modules/azure_openai"
  enabled             = var.enable_azure_openai
  resource_group_name = azurerm_resource_group.production.name
  location            = var.location
  name                = var.enable_azure_openai ? "oai-cbot-prd-${var.resource_name_suffix}" : ""
  subnet_id           = azurerm_subnet.private_endpoints.id
  virtual_network_id  = azurerm_virtual_network.production.id
  tags                = local.tags
}
