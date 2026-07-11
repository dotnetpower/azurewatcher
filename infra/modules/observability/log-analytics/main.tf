resource "azurerm_log_analytics_workspace" "primary" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_days
  # Cap ingestion so a runaway logger never turns into a runaway invoice.
  # `-1` opts out entirely (Azure default), any positive number is a hard
  # daily ceiling in GB. Day-zero default 1 GB matches the minimum-set
  # sizing in `docs/roadmap/deployment/deploy-and-onboard.md`.
  daily_quota_gb = var.daily_quota_gb
  tags           = var.tags
}

