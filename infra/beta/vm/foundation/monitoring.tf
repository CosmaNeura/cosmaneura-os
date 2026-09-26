resource "azurerm_log_analytics_workspace" "staging" {
  name                = "law-cosmabot-staging-eus2-lab01"
  resource_group_name = azurerm_resource_group.staging.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.1
  tags                = local.tags
}
resource "azurerm_monitor_action_group" "health" {
  name                = "ag-cosmabot-staging-eus2-lab01"
  resource_group_name = azurerm_resource_group.staging.name
  short_name          = "cbotstage"
  enabled             = true
  email_receiver {
    name                    = "staging-owner"
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
  name                = "alert-cbot-${each.key}-eus2-lab01"
  resource_group_name = azurerm_resource_group.staging.name
  scopes              = [azurerm_linux_virtual_machine.workload.id]
  description         = "Synthetic staging VM infrastructure metric; no application data."
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
