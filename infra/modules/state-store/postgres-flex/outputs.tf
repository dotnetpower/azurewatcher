output "id" {
  description = "Server resource id."
  value       = azurerm_postgresql_flexible_server.primary.id
}

output "fqdn" {
  description = "Fully qualified domain name."
  value       = azurerm_postgresql_flexible_server.primary.fqdn
}

output "name" {
  description = "Server name."
  value       = azurerm_postgresql_flexible_server.primary.name
}

output "database_name" {
  description = "Application database name."
  value       = azurerm_postgresql_flexible_server_database.primary.name
}

