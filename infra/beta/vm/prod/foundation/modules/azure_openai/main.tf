# Separate Azure OpenAI module. Default plan keeps enabled=false so no spend.
# Enabling requires enable_azure_openai=true in John's reviewed inputs at plan time.
# Local key auth stays enabled: CosmaBot runtime still reads WORKSPACE_LLM_API_KEY
# (see infra/beta/vm/runtime/entrypoint.py model_credential_required and
# src/cosmas_os/adapters/gpt41.py Bearer Authorization). Do not disable local auth.

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

# Matching staging/app T-USDZ deployment name and Data Zone Standard US shape.
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
    capacity = 10
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

resource "azurerm_role_assignment" "runtime_openai_user" {
  count                            = var.enabled ? 1 : 0
  scope                            = azurerm_cognitive_account.openai[0].id
  role_definition_name             = "Cognitive Services OpenAI User"
  principal_id                     = var.runtime_principal_id
  skip_service_principal_aad_check = true
}
