variable "name" {
  description = "Event Hubs namespace name (CAF: evhns-<workload>[-env][-region])."
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

variable "topics" {
  description = "Kafka topics to provision under this namespace. DLQ siblings (<topic>.dlq) are auto-created."
  type        = list(string)
}

variable "partition_count" {
  description = "Partition count per topic. Day-zero default 2."
  type        = number
  default     = 2
}

variable "sku" {
  description = "Event Hubs SKU. Standard supports Kafka wire on :9093."
  type        = string
  default     = "Standard"
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

