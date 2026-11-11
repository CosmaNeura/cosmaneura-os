variable "enable_azure_openai" {
  type        = bool
  description = "OFF by default. Set true in John's reviewed inputs at plan time so OpenAI resources appear in the plan he reviews. Creating them still requires his apply yes."
  default     = false
}

module "azure_openai" {
  source               = "./modules/azure_openai"
  enabled              = var.enable_azure_openai
  resource_group_name  = azurerm_resource_group.production.name
  location             = var.location
  name                 = var.enable_azure_openai ? "oai-cbot-prd-${var.resource_name_suffix}" : ""
  subnet_id            = azurerm_subnet.private_endpoints.id
  virtual_network_id   = azurerm_virtual_network.production.id
  runtime_principal_id = azurerm_user_assigned_identity.runtime.principal_id
  tags                 = local.tags
}
