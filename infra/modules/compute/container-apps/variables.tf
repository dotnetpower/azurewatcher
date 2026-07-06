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
  default     = "rg-aiopspilot-dr-drill"
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
