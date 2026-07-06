resource "azurerm_postgresql_flexible_server" "primary" {
  name                         = var.name
  resource_group_name          = var.resource_group_name
  location                     = var.location
  version                      = var.postgres_version
  sku_name                     = var.sku_name
  storage_mb                   = var.storage_mb
  administrator_login          = var.administrator_login
  administrator_password       = var.administrator_password
  backup_retention_days        = 7
  geo_redundant_backup_enabled = false

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = true
    tenant_id                     = var.tenant_id
  }

  tags = var.tags

  lifecycle {
    # Zone is auto-assigned by Azure on the first apply and MUST NOT be
    # rewritten on subsequent applies - Postgres Flex only allows zone
    # swaps paired with a `standby_availability_zone` change (HA), which
    # this single-zone day-zero config does not use.
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "primary" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.primary.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# pgvector extension enabled via server-side azure.extensions configuration
# (Azure Database for PostgreSQL supports 'vector' as of PostgreSQL 16).
resource "azurerm_postgresql_flexible_server_configuration" "vector_extension" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.primary.id
  value     = "VECTOR"
}

