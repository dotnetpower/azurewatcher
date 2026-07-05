output "id" {
  description = "Key Vault resource id."
  value       = azurerm_key_vault.primary.id
}

output "uri" {
  description = "Vault URI (used by Container Apps KV references)."
  value       = azurerm_key_vault.primary.vault_uri
}

output "name" {
  description = "Vault name."
  value       = azurerm_key_vault.primary.name
}

