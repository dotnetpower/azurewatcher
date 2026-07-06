resource "azurerm_container_app_environment" "primary" {
  name                       = var.env_name
  location                   = var.location
  resource_group_name        = var.resource_group_name
  log_analytics_workspace_id = var.log_workspace_id
  tags                       = var.tags
}

# Unified core app. Sidecars for trust-router / executor / audit-writer land as
# additional `container {}` blocks (localhost IPC) - see deploy-and-onboard.md
# § Compute Shape. Day-zero manifest keeps the single container as a placeholder.
resource "azurerm_container_app" "core" {
  name                         = var.core_app_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.executor_identity_id]
  }

  template {
    min_replicas = 0
    max_replicas = var.max_replicas

    container {
      name   = "core"
      image  = var.image
      cpu    = 0.5
      memory = "1Gi"
    }
  }

  tags = var.tags
}

# Out-of-band scheduled probes (cost anomalies, change detection sweep, etc.).
resource "azurerm_container_app_job" "oob" {
  name                         = var.oob_job_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  replica_timeout_in_seconds   = 300
  replica_retry_limit          = 3

  identity {
    type         = "UserAssigned"
    identity_ids = [var.executor_identity_id]
  }

  schedule_trigger_config {
    cron_expression          = "0 * * * *"
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name   = "oob"
      image  = var.image
      cpu    = 0.25
      memory = "0.5Gi"
    }
  }

  tags = var.tags
}

