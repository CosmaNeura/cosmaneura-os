resource "azurerm_log_analytics_workspace" "beta" {
  name                = local.law_name
  resource_group_name = data.azurerm_resource_group.beta.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  daily_quota_gb      = var.log_daily_quota_gb
  tags                = local.tags
}

# Metric metadata and the common alert schema contain no request bodies,
# database values, Blob paths, or other application data. The human must still
# use Azure's Action Group test control and retain delivery evidence before
# admitting testers.
resource "azurerm_monitor_action_group" "workload_health" {
  count = var.deploy_workloads && var.alert_contact_email != null ? 1 : 0

  name                = local.action_group_name
  resource_group_name = data.azurerm_resource_group.beta.name
  short_name          = "cosmasbeta"
  enabled             = true
  tags                = local.tags

  email_receiver {
    name                    = "d3-owner"
    email_address           = var.alert_contact_email
    use_common_alert_schema = true
  }
}

resource "azurerm_monitor_metric_alert" "api_unavailable" {
  count = var.deploy_workloads && var.alert_contact_email != null ? 1 : 0

  name                = local.api_health_alert_name
  resource_group_name = data.azurerm_resource_group.beta.name
  scopes              = [azurerm_container_app.api[0].id]
  description         = "PHI-safe D3 API availability alert: average active replicas below one."
  severity            = 1
  enabled             = true
  auto_mitigate       = true
  frequency           = "PT1M"
  window_size         = "PT5M"
  tags                = local.tags

  criteria {
    metric_namespace       = "Microsoft.App/containerApps"
    metric_name            = "Replicas"
    aggregation            = "Average"
    operator               = "LessThan"
    threshold              = 1
    skip_metric_validation = false
  }

  action {
    action_group_id = azurerm_monitor_action_group.workload_health[0].id
  }
}

resource "azurerm_monitor_metric_alert" "worker_unavailable" {
  count = var.deploy_workloads && var.alert_contact_email != null ? 1 : 0

  name                = local.worker_health_alert_name
  resource_group_name = data.azurerm_resource_group.beta.name
  scopes              = [azurerm_container_app.worker[0].id]
  description         = "PHI-safe D3 worker availability alert: average active replicas below one."
  severity            = 1
  enabled             = true
  auto_mitigate       = true
  frequency           = "PT1M"
  window_size         = "PT5M"
  tags                = local.tags

  criteria {
    metric_namespace       = "Microsoft.App/containerApps"
    metric_name            = "Replicas"
    aggregation            = "Average"
    operator               = "LessThan"
    threshold              = 1
    skip_metric_validation = false
  }

  action {
    action_group_id = azurerm_monitor_action_group.workload_health[0].id
  }
}

# Early-warning alerts. Like the replica alerts above, these use platform
# metrics only: counts, durations and percentages, never request or row data.
locals {
  # Only whether an address exists is used here, never the address itself.
  workload_alerts_enabled = var.deploy_workloads && nonsensitive(var.alert_contact_email != null)
}

resource "azurerm_monitor_metric_alert" "api_server_errors" {
  count = local.workload_alerts_enabled ? 1 : 0

  name                = "alert-cosmas-beta-api-5xx-${var.beta_id}"
  resource_group_name = data.azurerm_resource_group.beta.name
  scopes              = [azurerm_container_app.api[0].id]
  description         = "PHI-safe API alert: server errors (5xx) above the threshold in 5 minutes."
  severity            = 2
  enabled             = true
  auto_mitigate       = true
  frequency           = "PT1M"
  window_size         = "PT5M"
  tags                = local.tags

  criteria {
    metric_namespace       = "Microsoft.App/containerApps"
    metric_name            = "Requests"
    aggregation            = "Total"
    operator               = "GreaterThan"
    threshold              = var.alert_api_5xx_per_5m
    skip_metric_validation = false

    dimension {
      name     = "statusCodeCategory"
      operator = "Include"
      values   = ["5xx"]
    }
  }

  action {
    action_group_id = azurerm_monitor_action_group.workload_health[0].id
  }
}

resource "azurerm_monitor_metric_alert" "api_slow_responses" {
  count = local.workload_alerts_enabled ? 1 : 0

  name                = "alert-cosmas-beta-api-slow-${var.beta_id}"
  resource_group_name = data.azurerm_resource_group.beta.name
  scopes              = [azurerm_container_app.api[0].id]
  description         = "PHI-safe API alert: average response time above the threshold for 15 minutes."
  severity            = 2
  enabled             = true
  auto_mitigate       = true
  frequency           = "PT5M"
  window_size         = "PT15M"
  tags                = local.tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "ResponseTime"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.alert_api_response_ms
    # ResponseTime is a newer Container Apps metric; do not fail the apply if the
    # region has not exposed it yet. The alert starts evaluating once it exists.
    skip_metric_validation = true
  }

  action {
    action_group_id = azurerm_monitor_action_group.workload_health[0].id
  }
}

resource "azurerm_monitor_metric_alert" "workload_restarts" {
  for_each = local.workload_alerts_enabled ? {
    api    = azurerm_container_app.api[0].id
    worker = azurerm_container_app.worker[0].id
  } : {}

  name                = "alert-cosmas-beta-${each.key}-restarts-${var.beta_id}"
  resource_group_name = data.azurerm_resource_group.beta.name
  scopes              = [each.value]
  description         = "PHI-safe ${each.key} alert: repeated container restarts (crash loop) in 15 minutes."
  severity            = 2
  enabled             = true
  auto_mitigate       = true
  frequency           = "PT5M"
  window_size         = "PT15M"
  tags                = local.tags

  criteria {
    metric_namespace       = "Microsoft.App/containerApps"
    metric_name            = "RestartCount"
    aggregation            = "Total"
    operator               = "GreaterThan"
    threshold              = var.alert_restarts_per_15m
    skip_metric_validation = false
  }

  action {
    action_group_id = azurerm_monitor_action_group.workload_health[0].id
  }
}

resource "azurerm_monitor_metric_alert" "postgres_pressure" {
  for_each = local.workload_alerts_enabled ? {
    cpu     = { metric = "cpu_percent", threshold = var.alert_postgres_cpu_percent }
    storage = { metric = "storage_percent", threshold = var.alert_postgres_storage_percent }
  } : {}

  name                = "alert-cosmas-beta-postgres-${each.key}-${var.beta_id}"
  resource_group_name = data.azurerm_resource_group.beta.name
  scopes              = [azurerm_postgresql_flexible_server.beta.id]
  description         = "PHI-safe database alert: ${each.value.metric} above ${each.value.threshold} for 15 minutes."
  severity            = 2
  enabled             = true
  auto_mitigate       = true
  frequency           = "PT5M"
  window_size         = "PT15M"
  tags                = local.tags

  criteria {
    metric_namespace       = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name            = each.value.metric
    aggregation            = "Average"
    operator               = "GreaterThan"
    threshold              = each.value.threshold
    skip_metric_validation = false
  }

  action {
    action_group_id = azurerm_monitor_action_group.workload_health[0].id
  }
}
