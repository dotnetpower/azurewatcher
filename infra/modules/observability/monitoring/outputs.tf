output "action_group_id" {
  value       = azurerm_monitor_action_group.primary.id
  description = "Action group all metric alerts fire to."
}

output "alert_names" {
  value       = sort([for a in azurerm_monitor_metric_alert.this : a.name])
  description = "Provisioned metric alert names."
}
