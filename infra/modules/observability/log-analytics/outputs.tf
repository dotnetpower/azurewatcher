output "workspace_id" {
  description = "Log Analytics workspace resource id."
  value       = azurerm_log_analytics_workspace.primary.id
}

output "workspace_name" {
  description = "Workspace name."
  value       = azurerm_log_analytics_workspace.primary.name
}

