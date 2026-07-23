output "id" {
  value = azurerm_storage_account.case_history.id
}

output "name" {
  value = azurerm_storage_account.case_history.name
}

output "container_url" {
  value = "${azurerm_storage_account.case_history.primary_blob_endpoint}${azurerm_storage_container.case_history.name}"
}
