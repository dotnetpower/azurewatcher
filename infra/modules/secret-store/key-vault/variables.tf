variable "name" {
  description = "Key Vault name (CAF: kv-<workload>[-env][-region])."
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

variable "tenant_id" {
  description = "Entra tenant id."
  type        = string
}

variable "executor_principal_id" {
  description = "OID of the executor MI. Granted 'Key Vault Secrets User'."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

