resource "azurerm_managed_redis" "beta" {
  name                      = local.redis_name
  resource_group_name       = data.azurerm_resource_group.beta.name
  location                  = var.location
  sku_name                  = var.redis_sku_name
  high_availability_enabled = true
  public_network_access     = "Disabled"
  tags                      = local.tags

  # Celery's Redis transport is not Redis Cluster-aware. Keep one logical
  # database, fail rather than evict queued work, and persist each write.
  default_database {
    access_keys_authentication_enabled            = true
    client_protocol                               = "Encrypted"
    clustering_policy                             = "NoCluster"
    eviction_policy                               = "NoEviction"
    persistence_append_only_file_backup_frequency = "1s"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_private_endpoint" "redis" {
  name                = "pe-redis-${var.beta_id}"
  resource_group_name = data.azurerm_resource_group.beta.name
  location            = var.location
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-redis-${var.beta_id}"
    private_connection_resource_id = azurerm_managed_redis.beta.id
    subresource_names              = ["redisEnterprise"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "redis"
    private_dns_zone_ids = [azurerm_private_dns_zone.redis.id]
  }
}
