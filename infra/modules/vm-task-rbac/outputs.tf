output "role_definition_id" {
  description = "Target-scoped custom role granted to the executor identity."
  value       = azurerm_role_definition.vm_task_runner.role_definition_resource_id
}
