output "id" {
  description = "ACR resource id."
  value       = azurerm_container_registry.primary.id
}

output "login_server" {
  description = "Login server URL (used in image references)."
  value       = azurerm_container_registry.primary.login_server
}

