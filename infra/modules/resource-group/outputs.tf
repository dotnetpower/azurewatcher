output "name" {
  description = "Resource group name."
  value       = azurerm_resource_group.primary.name
}

output "id" {
  description = "Resource group id."
  value       = azurerm_resource_group.primary.id
}

output "location" {
  description = "Resource group location."
  value       = azurerm_resource_group.primary.location
}

