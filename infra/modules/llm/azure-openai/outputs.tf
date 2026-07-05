output "endpoint" {
  description = "AOAI account endpoint (custom-subdomain URL)."
  value       = azurerm_cognitive_account.primary.endpoint
}

output "resource_id" {
  description = "Fully qualified ARM id of the Cognitive Services account."
  value       = azurerm_cognitive_account.primary.id
}

output "deployments" {
  description = "Map of capability name → deployment name (as created)."
  value = {
    for name, dep in azurerm_cognitive_deployment.capability : name => dep.name
  }
}

output "capacity_units" {
  description = "Map of capability name → capacity units (thousand TPM) actually provisioned."
  value = {
    for name, cap in local.deployments_by_name : name => cap.capacity_units
  }
}
