variable "runtime_monitoring_enabled" {
  type        = bool
  default     = false
  description = "Install the official monitor agent and collect only the fixed health report."
}
variable "runtime_alerts_enabled" {
  type        = bool
  default     = false
  description = "Enable after the host probe and actual log ingestion have been verified."
  validation {
    condition     = !var.runtime_alerts_enabled || var.runtime_monitoring_enabled
    error_message = "Runtime alert activation requires runtime monitoring."
  }
}

locals {
  health_message_pattern = "^cosmabot-health-v1 \\{\"application\":\"(ok|failed)\",\"backup\":\"(ok|failed)\",\"observed_at\":\"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\"\\}$"
}

resource "azurerm_virtual_machine_extension" "health" {
  count                      = var.runtime_monitoring_enabled ? 1 : 0
  name                       = "AzureMonitorLinuxAgent"
  virtual_machine_id         = azurerm_linux_virtual_machine.workload.id
  publisher                  = "Microsoft.Azure.Monitor"
  type                       = "AzureMonitorLinuxAgent"
  type_handler_version       = "1.0"
  auto_upgrade_minor_version = true
  automatic_upgrade_enabled  = true
  settings = jsonencode({
    authentication = { managedIdentity = {
      "identifier-name"  = "mi_res_id"
      "identifier-value" = azurerm_user_assigned_identity.runtime.id
    } }
  })
  tags = local.tags
}

resource "azurerm_monitor_data_collection_rule" "health" {
  count               = var.runtime_monitoring_enabled ? 1 : 0
  name                = "dcr-cosmabot-health-eus2-lab01"
  resource_group_name = azurerm_resource_group.staging.name
  location            = var.location
  kind                = "Linux"
  data_sources {
    syslog {
      name           = "cosmabot-health"
      facility_names = ["local6"]
      log_levels     = ["Info"]
      streams        = ["Microsoft-Syslog"]
    }
  }
  destinations {
    log_analytics {
      name                  = "staging-health"
      workspace_resource_id = azurerm_log_analytics_workspace.staging.id
    }
  }
  data_flow {
    streams       = ["Microsoft-Syslog"]
    destinations  = ["staging-health"]
    transform_kql = "source | where Facility == 'local6' and ProcessName == 'cosmabot-health' | where SyslogMessage matches regex @'${local.health_message_pattern}'"
  }
  tags = local.tags
}

resource "azurerm_monitor_data_collection_rule_association" "health" {
  count                   = var.runtime_monitoring_enabled ? 1 : 0
  name                    = "cosmabot-health"
  target_resource_id      = azurerm_linux_virtual_machine.workload.id
  data_collection_rule_id = azurerm_monitor_data_collection_rule.health[0].id
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "runtime" {
  for_each                = var.runtime_monitoring_enabled ? toset(["application", "backup"]) : toset([])
  name                    = "alert-cbot-${each.key}-eus2-lab01"
  resource_group_name     = azurerm_resource_group.staging.name
  location                = var.location
  scopes                  = [azurerm_log_analytics_workspace.staging.id]
  description             = "CosmaBot ${each.key} has no successful health report for five minutes."
  severity                = 1
  enabled                 = var.runtime_alerts_enabled
  evaluation_frequency    = "PT1M"
  window_duration         = "PT10M"
  auto_mitigation_enabled = true
  # The Syslog table may not exist before the first health report. Activation
  # re-enables Azure validation after the exact query passes against live data.
  skip_query_validation = !var.runtime_alerts_enabled
  criteria {
    query                   = <<-KQL
      Syslog
      | where _ResourceId =~ '${azurerm_linux_virtual_machine.workload.id}'
      | where Facility == 'local6' and ProcessName == 'cosmabot-health'
      | where SyslogMessage matches regex @'${local.health_message_pattern}'
      | extend report = parse_json(substring(SyslogMessage, 18))
      | extend Observed = todatetime(report.observed_at), State = tostring(report.${each.key})
      | where Observed <= now() + 1m
      | summarize LastHealthy = maxif(Observed, State == 'ok')
      | project Unhealthy = iff(isnull(LastHealthy) or LastHealthy < ago(5m), 1, 0)
    KQL
    time_aggregation_method = "Maximum"
    metric_measure_column   = "Unhealthy"
    operator                = "GreaterThan"
    threshold               = 0
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }
  action {
    action_groups = [azurerm_monitor_action_group.health.id]
  }
  tags = local.tags
}
