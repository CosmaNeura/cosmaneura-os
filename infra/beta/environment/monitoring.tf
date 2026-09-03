resource "azurerm_log_analytics_workspace" "beta" {
  name                = local.law_name
  resource_group_name = data.azurerm_resource_group.beta.name
  location            = data.azurerm_resource_group.beta.location
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
