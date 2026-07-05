variable "name" {
  description = "Postgres Flexible Server name (CAF: psql-<workload>[-env][-region])."
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
  description = "Entra tenant id for AAD authentication."
  type        = string
}

variable "administrator_login" {
  description = "Bootstrap admin login (rotate to AAD auth once running)."
  type        = string
  sensitive   = true
}

variable "administrator_password" {
  description = "Bootstrap admin password."
  type        = string
  sensitive   = true
}

variable "database_name" {
  description = "Application database name."
  type        = string
}

variable "sku_name" {
  description = "Postgres SKU. Day-zero: B_Standard_B1ms (Burstable). Scale up when measurement shows a need."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "storage_mb" {
  description = "Storage in MB. 32768 = 32 GB (Burstable minimum)."
  type        = number
  default     = 32768
}

variable "postgres_version" {
  description = "Postgres major version. pgvector is available on 16."
  type        = string
  default     = "16"
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

