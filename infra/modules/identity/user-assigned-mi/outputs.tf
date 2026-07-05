output "resource_id" {
  description = "Managed Identity resource id."
  value       = azurerm_user_assigned_identity.primary.id
}

output "principal_id" {
  description = "OID for role assignments."
  value       = azurerm_user_assigned_identity.primary.principal_id
}

output "client_id" {
  description = "Client id used by workload identity federation."
  value       = azurerm_user_assigned_identity.primary.client_id
}

