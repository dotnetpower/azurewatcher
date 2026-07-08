variable "env_name" {
  description = "Container Apps environment name (CAF: cae-<workload>[-env][-region])."
  type        = string
}

variable "core_app_name" {
  description = "Container App name for the unified core (CAF: ca-<workload>[-env][-region]-core)."
  type        = string
}

variable "oob_job_name" {
  description = "Container Apps Job name for out-of-band scheduled probes (CAF: caj-<workload>[-env][-region]-oob)."
  type        = string
}

variable "rule_watcher_job_name" {
  description = "Container Apps Job name for the rule-catalog source watcher (CAF: caj-<workload>[-env][-region]-rule-watcher)."
  type        = string
}

variable "rule_watcher_cron_expression" {
  description = "Cron for the rule watcher job. Daily at 03:00 UTC; the CLI filters by manifest cadence so weekly / monthly sources fire from the same job."
  type        = string
  default     = "0 3 * * *"
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Enclosing resource group."
  type        = string
}

variable "log_workspace_id" {
  description = "Log Analytics workspace resource id (Container Apps binds here)."
  type        = string
}

variable "executor_identity_id" {
  description = "User-assigned MI resource id used by both the app and the job."
  type        = string
}

variable "image" {
  description = "Container image reference. Pin by digest in prod."
  type        = string
}

variable "max_replicas" {
  description = "KEDA scale ceiling."
  type        = number
  default     = 3
}

variable "core_cpu" {
  description = "CPU quota for the core container. Container Apps accepts increments of 0.25 up to 4.0."
  type        = number
  default     = 0.5

  validation {
    condition     = var.core_cpu >= 0.25 && var.core_cpu <= 4.0
    error_message = "core_cpu must be between 0.25 and 4.0 (Container Apps limit)."
  }
}

variable "core_memory" {
  description = "Memory quota for the core container (Container Apps expects Gi units, e.g. `1Gi`, `2Gi`)."
  type        = string
  default     = "1Gi"

  validation {
    condition     = can(regex("^[0-9]+(\\.[0-9]+)?Gi$", var.core_memory))
    error_message = "core_memory must be a Container Apps value like `1Gi` / `2.5Gi`."
  }
}

variable "oob_cpu" {
  description = "CPU quota for the out-of-band scheduled probes container (typically half of core)."
  type        = number
  default     = 0.25

  validation {
    condition     = var.oob_cpu >= 0.25 && var.oob_cpu <= 4.0
    error_message = "oob_cpu must be between 0.25 and 4.0."
  }
}

variable "oob_memory" {
  description = "Memory quota for the out-of-band container."
  type        = string
  default     = "0.5Gi"

  validation {
    condition     = can(regex("^[0-9]+(\\.[0-9]+)?Gi$", var.oob_memory))
    error_message = "oob_memory must be a Container Apps value like `0.5Gi`."
  }
}

variable "min_replicas" {
  description = <<-EOT
    Floor replica count. Day-zero default 1 keeps the P1 control loop
    reachable without a KEDA scale rule; a fork that adds a scale rule
    tied to Event Hubs unprocessed-message lag MAY flip this back to 0
    for scale-to-zero. If it stays 0 without a scale rule, incoming
    Kafka events never wake the app - a silent regression that only
    the KPI dashboard would eventually surface.
  EOT
  type        = number
  default     = 1

  validation {
    condition     = var.min_replicas >= 0 && var.min_replicas <= var.max_replicas
    error_message = "min_replicas must be >= 0 and <= max_replicas."
  }
}

# ---------------------------------------------------------------------------
# Persistence DSNs (Key Vault-backed).
#
# The core control plane reads three env vars for its Postgres seams
# (`FDAI_STATE_STORE_DSN`, `FDAI_OPERATOR_MEMORY_DSN`,
# `FDAI_T1_PATTERN_LIBRARY_DSN`). Each is delivered as a Container App
# `secret {}` block that resolves a Key Vault secret via the executor
# user-assigned MI (which the KV module has already granted `Secrets User`
# on). The env var references the Container App secret, not the KV URI, so
# rotating the KV value never touches the app template.
#
# Empty string means "not wired" - the composition root then falls back
# to the in-memory backend (`_build_state_store` etc. in `src/fdai/__main__.py`).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Core-config env vars.
#
# `EnvVarConfigProvider` in `src/fdai/shared/config/provider.py` REQUIRES
# these to be set at startup or the process raises `ConfigError` and
# refuses to boot (see `_ENV_VAR_MAP`). Without them the Container App
# would crash-loop, so they are wired here as plain (non-secret) env
# entries with sensible defaults where the schema permits.
# ---------------------------------------------------------------------------
variable "azure_tenant_id" {
  description = "Entra tenant id (`AZURE_TENANT_ID` in the runtime config)."
  type        = string
}

variable "azure_subscription_id" {
  description = "Enclosing subscription id (`AZURE_SUBSCRIPTION_ID`)."
  type        = string
}

variable "azure_resource_group" {
  description = "Target resource group (`AZURE_RESOURCE_GROUP`); non-secret."
  type        = string
}

variable "azure_region" {
  description = "Azure region short name (`AZURE_REGION`)."
  type        = string
}

variable "kafka_bootstrap_servers" {
  description = "Event Hubs Kafka endpoint (`KAFKA_BOOTSTRAP_SERVERS`) - `<ns>.servicebus.windows.net:9093`."
  type        = string
}

variable "kafka_topic_events" {
  description = "Primary event-ingest topic (`KAFKA_TOPIC_EVENTS`)."
  type        = string
  default     = "aw.change.events"
}

variable "postgres_host" {
  description = "Postgres Flexible Server FQDN (`POSTGRES_HOST`) - non-secret label used for the startup log summary."
  type        = string
}

variable "postgres_database" {
  description = "Postgres database name (`POSTGRES_DATABASE`) - non-secret label."
  type        = string
}

variable "runtime_env" {
  description = "`RUNTIME_ENV` - one of `dev` / `staging` / `prod`."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.runtime_env)
    error_message = "runtime_env must be dev, staging, or prod."
  }
}

variable "autonomy_mode_default" {
  description = "`AUTONOMY_MODE_DEFAULT` - MUST default to `shadow` per coding-conventions."
  type        = string
  default     = "shadow"

  validation {
    condition     = contains(["shadow", "enforce"], var.autonomy_mode_default)
    error_message = "autonomy_mode_default must be shadow or enforce."
  }
}

variable "state_store_dsn_secret_id" {
  description = "Key Vault secret resource id backing FDAI_STATE_STORE_DSN. Empty = fall back to in-memory."
  type        = string
  default     = ""
  sensitive   = true
}

variable "operator_memory_dsn_secret_id" {
  description = "Key Vault secret resource id backing FDAI_OPERATOR_MEMORY_DSN. Empty = fall back to in-memory."
  type        = string
  default     = ""
  sensitive   = true
}

variable "pattern_library_dsn_secret_id" {
  description = "Key Vault secret resource id backing FDAI_T1_PATTERN_LIBRARY_DSN. Empty = fall back to in-memory."
  type        = string
  default     = ""
  sensitive   = true
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}


# ---------------------------------------------------------------------------
# Deep DB-DR drill (opt-in; see docs/runbooks/db-dr-drill.md).
# ---------------------------------------------------------------------------

variable "dr_drill_enabled" {
  description = "Toggle the scheduled DB-DR drill Container Apps Job."
  type        = bool
  default     = false
}

variable "dr_drill_job_name" {
  description = "Container Apps Job name for the DB-DR drill (32-char limit)."
  type        = string
  default     = ""
}

variable "dr_drill_cron_expression" {
  description = "Cron for the DB-DR drill. Default: 04:00 UTC on the 1st and 15th."
  type        = string
  default     = "0 4 1,15 * *"
}

variable "dr_drill_source_server_arm_id" {
  description = "ARM id of the production Postgres Flexible Server whose PITR checkpoint the drill restores. Required when dr_drill_enabled = true."
  type        = string
  default     = ""
}

variable "dr_drill_target_rg_prefix" {
  description = "Prefix for the isolated resource group the drill lands in."
  type        = string
  default     = "rg-fdai-dr-drill"
}

variable "dr_drill_target_server_prefix" {
  description = "Prefix for the drill target Postgres server name (short - timestamp is appended)."
  type        = string
  default     = "psql-drill"
}

variable "dr_drill_pitr_offset_minutes" {
  description = "How many minutes back from now the drill restore point sits."
  type        = number
  default     = 30
}

variable "dr_drill_dry_run" {
  description = "When true, the drill CLI logs its composed config and exits without touching Azure. Set false in production."
  type        = bool
  default     = true
}
