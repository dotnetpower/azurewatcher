variable "name" {
  description = "ACR name (CAF: cr<workload>[env][region][nn]; 5-50 alphanumeric ONLY, no hyphens)."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9]{5,50}$", var.name))
    error_message = "ACR name must be 5-50 alphanumeric characters with no hyphens."
  }
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Enclosing resource group."
  type        = string
}

variable "sku" {
  description = "ACR SKU. Basic covers day-zero; upgrade when geo-replication is measured to be needed."
  type        = string
  default     = "Basic"
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

