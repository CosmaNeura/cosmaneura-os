output "cognitive_account_id" {
  value = var.enabled ? azurerm_cognitive_account.openai[0].id : null
}

output "endpoint" {
  value = var.enabled ? azurerm_cognitive_account.openai[0].endpoint : null
}

output "deployment_name" {
  value = var.enabled ? azurerm_cognitive_deployment.gpt41_dzus[0].name : null
}

output "private_endpoint_id" {
  value = var.enabled ? azurerm_private_endpoint.openai[0].id : null
}

output "private_dns_zone_id" {
  value = var.enabled ? azurerm_private_dns_zone.openai[0].id : null
}

output "created" {
  value = var.enabled
}
