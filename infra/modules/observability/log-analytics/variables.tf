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

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

