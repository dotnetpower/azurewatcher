variable "name" {
  description = "Resource group name (CAF: rg-<workload>[-env][-region][-instance])."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "tags" {
  description = "Base tag set applied to the RG."
  type        = map(string)
  default     = {}
}

