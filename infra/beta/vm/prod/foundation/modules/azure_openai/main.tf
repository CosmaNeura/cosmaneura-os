# Separate Azure OpenAI module. Default plan keeps enabled=false so no spend.
# Enabling requires an explicit John yes beyond the production hosting approval.

resource "azurerm_cognitive_account" "openai" {
  count                 = var.enabled ? 1 : 0
  name                  = var.name
  location              = var.location
  resource_group_name   = var.resource_group_name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = var.name
  tags                  = var.tags

  network_acls {
    default_action = "Deny"
  }
}
