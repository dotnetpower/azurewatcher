output "id" {
  description = "Server resource id."
  value       = azurerm_postgresql_flexible_server.primary.id
}

output "fqdn" {
  description = "Fully qualified domain name."
  value       = azurerm_postgresql_flexible_server.primary.fqdn
}

output "name" {
  description = "Server name."
  value       = azurerm_postgresql_flexible_server.primary.name
}

output "database_name" {
  description = "Application database name."
  value       = azurerm_postgresql_flexible_server_database.primary.name
}

# ---------------------------------------------------------------------------
# Application DSNs.
#
# The core control plane reads three env vars:
#   - FDAI_STATE_STORE_DSN         (audit + KPI append-only tables)
#   - FDAI_OPERATOR_MEMORY_DSN     (HIL-approved operator memory)
#   - FDAI_T1_PATTERN_LIBRARY_DSN  (pgvector similarity reuse)
#
# Day-zero the three point at the same database (see deploy-and-onboard.md
# "PostgreSQL Flexible Server ... single store"). A fork MAY split them
# later without touching the core, since each is a separate env var.
#
# Marked `sensitive` because it embeds the bootstrap admin password. In
# production, forks rotate to AAD auth and swap this DSN for a token-based
# one; the shape (postgres connection URI) stays identical.
# ---------------------------------------------------------------------------
output "application_dsn" {
  description = "Postgres connection URI for the application database (sensitive; contains bootstrap admin password). Login + password are URL-encoded so a password containing `@` / `:` / `/` / `?` / `#` / `%` does not corrupt the URI."
  value       = "postgresql://${urlencode(var.administrator_login)}:${urlencode(var.administrator_password)}@${azurerm_postgresql_flexible_server.primary.fqdn}:5432/${var.database_name}?sslmode=require"
  sensitive   = true
}

