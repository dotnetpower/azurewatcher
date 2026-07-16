output "name" {
  value = azurerm_container_app.ingestion.name
}

output "fqdn" {
  value = azurerm_container_app.ingestion.ingress[0].fqdn
}

output "id" {
  value = azurerm_container_app.ingestion.id
}

output "migrate_job_name" {
  value = azurerm_container_app_job.migrate.name
}
