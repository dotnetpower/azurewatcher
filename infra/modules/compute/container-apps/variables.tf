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

