output "id" {
  value = azurerm_storage_account.documents.id
}

output "name" {
  value = azurerm_storage_account.documents.name
}

output "primary_dfs_endpoint" {
  value = azurerm_storage_account.documents.primary_dfs_endpoint
}

output "primary_blob_endpoint" {
  value = azurerm_storage_account.documents.primary_blob_endpoint
}

output "source_file_system" {
  value = azurerm_storage_data_lake_gen2_filesystem.documents.name
}

output "derived_file_system" {
  value = azurerm_storage_data_lake_gen2_filesystem.derived.name
}
