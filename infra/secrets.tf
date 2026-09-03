locals {
  database_url = format(
    "postgresql+psycopg://%s:%s@%s:5432/cosmas_os?sslmode=require",
    replace(urlencode(var.postgres_admin_login), "+", "%20"),
    replace(urlencode(var.postgres_admin_password), "+", "%20"),
    azurerm_postgresql_flexible_server.synth.fqdn,
  )
  redis_url = format(
    "rediss://:%s@%s:%d/0?ssl_cert_reqs=required",
    replace(urlencode(azurerm_redis_cache.synth.primary_access_key), "+", "%20"),
    azurerm_redis_cache.synth.hostname,
    azurerm_redis_cache.synth.ssl_port,
  )
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = local.database_url
  key_vault_id = azurerm_key_vault.synth.id
  content_type = "Cosmas OS synth DATABASE_URL"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_secrets_officer_deployer]
}

resource "azurerm_key_vault_secret" "redis_url" {
  name         = "redis-url"
  value        = local.redis_url
  key_vault_id = azurerm_key_vault.synth.id
  content_type = "Cosmas OS synth REDIS_URL"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.kv_secrets_officer_deployer]
}
