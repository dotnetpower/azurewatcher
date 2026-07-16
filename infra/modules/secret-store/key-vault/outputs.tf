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

output "executor_role_definition_id" {
  description = "Role definition id used for the executor secret-reader assignment."
  value       = try(azurerm_role_assignment.executor_secrets_user[0].role_definition_id, "")
}
