variable "workload" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "log_analytics_workspace_id" {
  description = "Log Analytics workspace the diagnostic settings stream to."
  type        = string
}

variable "action_group_name" {
  type    = string
  default = "ag-fdai-alerts"
}

variable "action_group_short_name" {
  description = "<= 12 chars, shown in SMS/email."
  type        = string
  default     = "fdai"
}

variable "alert_email" {
  description = "Email that receives alerts. Empty = no email receiver."
  type        = string
  default     = ""
}

variable "alert_webhook_url" {
  description = "Webhook (Teams/Slack/PagerDuty ingest) for alerts. Empty = none."
  type        = string
  default     = ""
}

# Resource ids to monitor. Empty string skips that resource's alerts.
variable "postgres_id" {
  type    = string
  default = ""
}

variable "key_vault_id" {
  type    = string
  default = ""
}

variable "event_hub_namespace_id" {
  type    = string
  default = ""
}

variable "container_app_id" {
  type    = string
  default = ""
}

# Tunable thresholds.
variable "postgres_cpu_threshold" {
  type    = number
  default = 80
}

variable "postgres_connection_threshold" {
  type    = number
  default = 80
}

variable "container_app_restart_threshold" {
  type    = number
  default = 5
}

variable "tags" {
  type    = map(string)
  default = {}
}
