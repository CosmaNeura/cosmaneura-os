resource "azurerm_redis_cache" "synth" {
  name                = local.redis_name
  resource_group_name = azurerm_resource_group.synth.name
  location            = azurerm_resource_group.synth.location
  capacity            = var.redis_capacity
  family              = var.redis_family
  sku_name            = var.redis_sku_name
  minimum_tls_version = "1.2"
  tags                = local.tags
}
