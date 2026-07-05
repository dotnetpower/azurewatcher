output "environment_id" {
  description = "Container Apps Environment resource id."
  value       = azurerm_container_app_environment.primary.id
}

output "core_app_id" {
  description = "Core Container App resource id."
  value       = azurerm_container_app.core.id
}

output "core_app_name" {
  description = "Core Container App name."
  value       = azurerm_container_app.core.name
}

output "oob_job_name" {
  description = "Out-of-band Container Apps Job name."
  value       = azurerm_container_app_job.oob.name
}

