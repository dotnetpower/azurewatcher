variable "name" {
  description = "Log Analytics workspace name (CAF: log-<workload>[-env][-region])."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Enclosing resource group."
  type        = string
}

variable "retention_days" {
  description = "Data retention (days). UI-configurable post-deploy."
  type        = number
  default     = 30
}

variable "daily_quota_gb" {
  description = "Hard daily ingestion ceiling in GB. `-1` disables the cap (Azure default). Day-zero uses 1 GB per the minimum-set sizing; scale up when measurement shows a need."
  type        = number
  default     = 1

  validation {
    condition     = var.daily_quota_gb == -1 || var.daily_quota_gb > 0
    error_message = "daily_quota_gb must be -1 (uncapped) or a positive number of GB."
  }
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

