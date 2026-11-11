output "cognitive_account_id" {
  value = var.enabled ? azurerm_cognitive_account.openai[0].id : null
}

output "endpoint" {
  value = var.enabled ? azurerm_cognitive_account.openai[0].endpoint : null
}

output "created" {
  value = var.enabled
}
