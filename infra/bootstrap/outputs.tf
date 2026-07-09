# Handles the app config consumes: backend wiring + peering + runner IAM.

output "ops_resource_group_name" {
  value       = azurerm_resource_group.ops.name
  description = "Ops (hub) resource group."
}

output "ops_vnet_id" {
  value       = azurerm_virtual_network.ops.id
  description = "Ops (hub) VNet id. The app config peers its spoke VNet to this and links its private DNS zones here so the runner resolves app private endpoints."
}

output "ops_vnet_name" {
  value       = azurerm_virtual_network.ops.name
  description = "Ops (hub) VNet name (peering back-reference)."
}

output "state_storage_account_name" {
  value       = azurerm_storage_account.state.name
  description = "Terraform remote-state storage account. Feed to `terraform init -backend-config` in the app config / CI workflow."
}

output "state_container_name" {
  value       = azurerm_storage_container.state.name
  description = "Blob container holding the app's terraform state."
}

output "runner_principal_id" {
  value       = var.create_runner_vm ? azurerm_linux_virtual_machine.runner[0].identity[0].principal_id : null
  description = "Runner MI object id. The app config grants this Key Vault Secrets Officer on the app vault."
}

output "runner_vm_name" {
  value       = var.create_runner_vm ? azurerm_linux_virtual_machine.runner[0].name : null
  description = "Runner VM name (reach via az vm run-command / Bastion; no public IP)."
}

output "backend_config_hint" {
  value       = "resource_group_name=${azurerm_resource_group.ops.name} storage_account_name=${azurerm_storage_account.state.name} container_name=${azurerm_storage_container.state.name} key=${var.workload}-${var.env}.tfstate"
  description = "Copy into `terraform init -backend-config=...` for the app config."
}
