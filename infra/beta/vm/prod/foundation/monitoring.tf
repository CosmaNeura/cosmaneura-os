resource "azurerm_log_analytics_workspace" "production" {
  name                = "law-cosmabot-prod-eus2-01"
  resource_group_name = azurerm_resource_group.production.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.1
  tags                = local.tags
}
resource "azurerm_monitor_action_group" "health" {
  name                = "ag-cosmabot-prod-eus2-01"
  resource_group_name = azurerm_resource_group.production.name
  short_name          = "cbotprod"
  enabled             = true
  email_receiver {
    name                    = "production-owner"
    email_address           = var.alert_contact_email
    use_common_alert_schema = true
  }
  tags = local.tags
}
locals {
  vm_alerts = {
    unavailable = { metric = "VmAvailabilityMetric", operator = "LessThan", threshold = 1, severity = 1, window = "PT5M" }
    cpu         = { metric = "Percentage CPU", operator = "GreaterThan", threshold = 85, severity = 2, window = "PT15M" }
    disk_iops   = { metric = "OS Disk IOPS Consumed Percentage", operator = "GreaterThan", threshold = 90, severity = 2, window = "PT15M" }
  }
}
resource "azurerm_monitor_metric_alert" "vm" {
  for_each            = local.vm_alerts
  name                = "alert-cbot-prod-${each.key}-eus2-01"
  resource_group_name = azurerm_resource_group.production.name
  scopes              = [azurerm_linux_virtual_machine.workload.id]
  description         = "Production VM infrastructure metric; no application data."
  severity            = each.value.severity
  enabled             = true
  auto_mitigate       = true
  frequency           = "PT1M"
  window_size         = each.value.window
  criteria {
    metric_namespace       = "Microsoft.Compute/virtualMachines"
    metric_name            = each.value.metric
    aggregation            = "Average"
    operator               = each.value.operator
    threshold              = each.value.threshold
    skip_metric_validation = false
  }
  action { action_group_id = azurerm_monitor_action_group.health.id }
  tags = local.tags
}
