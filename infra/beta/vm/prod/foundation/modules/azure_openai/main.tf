# Separate Azure OpenAI module. Variable default remains false for module safety.
# When enable_azure_openai=true in reviewed inputs, these resources appear in the
# plan John reviews. First-apply capacity is the minimum DataZoneStandard unit
# (1). Capacity increases only in the later LLM cutover ticket. Local key auth
# stays enabled for that later cutover; do not grant Cognitive Services OpenAI
# User to the runtime identity.

resource "azurerm_cognitive_account" "openai" {
  count                         = var.enabled ? 1 : 0
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  kind                          = "OpenAI"
  sku_name                      = "S0"
  custom_subdomain_name         = var.name
  public_network_access_enabled = false
  tags                          = var.tags

  network_acls {
    default_action = "Deny"
  }
}

# Same model as staging (gpt-4.1 / 2025-04-14) on Data Zone Standard US.
resource "azurerm_cognitive_deployment" "gpt41_dzus" {
  count                = var.enabled ? 1 : 0
  name                 = "gpt-4.1-dzus"
  cognitive_account_id = azurerm_cognitive_account.openai[0].id

  model {
    format  = "OpenAI"
    name    = "gpt-4.1"
    version = "2025-04-14"
  }

  sku {
    name     = "DataZoneStandard"
    capacity = 1
  }
}

resource "azurerm_private_dns_zone" "openai" {
  count               = var.enabled ? 1 : 0
  name                = "privatelink.openai.azure.com"
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "openai" {
  count                 = var.enabled ? 1 : 0
  name                  = "link-openai-prod"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.openai[0].name
  virtual_network_id    = var.virtual_network_id
  registration_enabled  = false
  tags                  = var.tags
}

resource "azurerm_private_endpoint" "openai" {
  count               = var.enabled ? 1 : 0
  name                = "pe-cbot-prod-openai-eus2-01"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.subnet_id
  tags                = var.tags

  private_service_connection {
    name                           = "psc-openai"
    private_connection_resource_id = azurerm_cognitive_account.openai[0].id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "openai"
    private_dns_zone_ids = [azurerm_private_dns_zone.openai[0].id]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.openai]
}
