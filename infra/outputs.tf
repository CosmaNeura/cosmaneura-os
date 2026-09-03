output "resource_group_name" {
  value = azurerm_resource_group.synth.name
}

output "location" {
  value = azurerm_resource_group.synth.location
}

output "acr_login_server" {
  value = azurerm_container_registry.synth.login_server
}

output "container_app_environment_id" {
  value = azurerm_container_app_environment.synth.id
}

output "api_fqdn" {
  value = try(azurerm_container_app.api.ingress[0].fqdn, null)
}

output "postgres_fqdn" {
  value = azurerm_postgresql_flexible_server.synth.fqdn
}

output "redis_hostname" {
  value = azurerm_redis_cache.synth.hostname
}

output "storage_account_name" {
  value = azurerm_storage_account.synth.name
}

output "key_vault_uri" {
  value = azurerm_key_vault.synth.vault_uri
}

output "managed_identity_client_id" {
  value = azurerm_user_assigned_identity.apps.client_id
}
