# Platform-metric alerts for every practice workspace allocated into this
# resource group. Scoping to the resource group with a target resource type
# makes each alert evaluate every current and future container app or database
# separately, so new practices are covered without per-practice alert work.
# Metrics carry counts, durations and percentages only, never request or row data.
locals {
  alerts_enabled = nonsensitive(var.alert_contact_email != null)
  container_app_alerts = local.alerts_enabled ? {
    server-errors = { metric = "Requests", aggregation = "Total", threshold = var.alert_5xx_per_5m, window = "PT5M", frequency = "PT1M", only_5xx = true, skip = false }
    restarts      = { metric = "RestartCount", aggregation = "Total", threshold = var.alert_restarts_per_15m, window = "PT15M", frequency = "PT5M", only_5xx = false, skip = false }
    slow          = { metric = "ResponseTime", aggregation = "Average", threshold = var.alert_response_ms, window = "PT15M", frequency = "PT5M", only_5xx = false, skip = true }
  } : {}
  postgres_alerts = local.alerts_enabled ? {
    cpu     = { metric = "cpu_percent", threshold = var.alert_postgres_cpu_percent }
    storage = { metric = "storage_percent", threshold = var.alert_postgres_storage_percent }
  } : {}
}

resource "azurerm_monitor_action_group" "practice_health" {
  count               = local.alerts_enabled ? 1 : 0
  name                = "ag-${local.name}"
  resource_group_name = azurerm_resource_group.enrollment.name
  short_name          = "cbothealth"
  enabled             = true
  tags                = local.tags
  email_receiver {
    name                    = "operations"
    email_address           = var.alert_contact_email
    use_common_alert_schema = true
  }
}

resource "azurerm_monitor_metric_alert" "container_apps" {
  for_each                 = local.container_app_alerts
  name                     = "alert-${local.name}-apps-${each.key}"
  resource_group_name      = azurerm_resource_group.enrollment.name
  scopes                   = [azurerm_resource_group.enrollment.id]
  target_resource_type     = "Microsoft.App/containerApps"
  target_resource_location = var.location
  description              = "Practice workspace apps: ${each.value.metric} ${each.value.aggregation} above ${each.value.threshold}. Metrics only; no application data."
  severity                 = 2
  enabled                  = true
  auto_mitigate            = true
  frequency                = each.value.frequency
  window_size              = each.value.window
  tags                     = local.tags
  criteria {
    metric_namespace       = "Microsoft.App/containerApps"
    metric_name            = each.value.metric
    aggregation            = each.value.aggregation
    operator               = "GreaterThan"
    threshold              = each.value.threshold
    skip_metric_validation = each.value.skip
    dynamic "dimension" {
      for_each = each.value.only_5xx ? [["5xx"]] : []
      content {
        name     = "statusCodeCategory"
        operator = "Include"
        values   = dimension.value
      }
    }
  }
  action { action_group_id = azurerm_monitor_action_group.practice_health[0].id }
}

resource "azurerm_monitor_metric_alert" "postgres" {
  for_each                 = local.postgres_alerts
  name                     = "alert-${local.name}-postgres-${each.key}"
  resource_group_name      = azurerm_resource_group.enrollment.name
  scopes                   = [azurerm_resource_group.enrollment.id]
  target_resource_type     = "Microsoft.DBforPostgreSQL/flexibleServers"
  target_resource_location = var.location
  description              = "Practice and enrollment databases: ${each.value.metric} above ${each.value.threshold} for 15 minutes. Metrics only."
  severity                 = 2
  enabled                  = true
  auto_mitigate            = true
  frequency                = "PT5M"
  window_size              = "PT15M"
  tags                     = local.tags
  criteria {
    metric_namespace       = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name            = each.value.metric
    aggregation            = "Average"
    operator               = "GreaterThan"
    threshold              = each.value.threshold
    skip_metric_validation = false
  }
  action { action_group_id = azurerm_monitor_action_group.practice_health[0].id }
}
